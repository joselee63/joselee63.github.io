"""KRX 업종(섹터)분류 시점별 스냅샷 + 업종지수 일봉 수집 — B3(섹터 신고가) 필터 무편향 재검증용.

데이터 출처: KRX 정보데이터시스템 [12025] 업종분류현황 (pykrx get_market_sector_classifications).
과거 일자를 넣으면 그 날짜 기준 상장종목(이후 상장폐지된 종목 포함)의 업종분류가 나온다.

전제: data.krx.co.kr 조회는 KRX 로그인 필요 → KRX_ID/KRX_PW 환경변수
(저장소 GitHub Secrets에만 있음 — .github/workflows/sector-data.yml 이 실행해
 data 브랜치 sectors/ 에 저장). 로그인 없이 돌리면 KIND 폴백만 수행.

사용법:
    python tools/sector_data.py <출력폴더> [all|sectors|index|kind|verify]
      sectors  분기별(2016Q1~현재, 분기 첫 영업일) 업종분류 스냅샷 → sectors/classifications.csv
      index    KOSPI/KOSDAQ 전체 지수 목록 + 일봉(2015~) → sectors/index_list.csv, index_ohlcv.csv
      kind     (로그인 불필요 폴백) KIND 상장법인목록의 표준산업분류 → sectors/kind_industry.csv
      verify   classifications.csv 통계 출력 (업종 수·업종당 종목 수·상폐종목 포함 여부)
               같은 폴더 또는 ../data-backtest 의 universe.csv 가 있으면 상폐 교차 검증

한계 (중요):
  - 분기 첫 영업일 스냅샷 → 분기 중 업종 변경·신규상장은 다음 스냅샷부터 반영.
  - 지수 목록(index_list)은 '현재' 존재하는 지수 기준 → 폐지된 업종지수의 일봉은 빠질 수 있음.
  - KRX 업종 체계 개편(예: 2021년) 시점 전후로 업종명이 달라질 수 있음 — 스냅샷별 업종명이
    그 시점 체계인지 현재 체계 소급인지는 수집된 업종명 변화로 확인할 것.
  - KIND 폴백의 '업종'은 표준산업분류(세분류)라서 KRX 업종지수 체계와 다르고 현재 상장사만 포함.
"""
import datetime as dt
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

START = "20150101"          # 업종지수 일봉 시작
SNAP_START = "2016-01-01"   # 업종분류 스냅샷 시작 (분기 첫 영업일)
SLEEP = 1.0
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}


def has_krx_login() -> bool:
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def today_str() -> str:
    return dt.date.today().strftime("%Y%m%d")


def quarter_firsts():
    return list(pd.date_range(SNAP_START, dt.date.today(), freq="QS"))


# ------------------------------------------------------------ ① 업종분류 스냅샷
def collect_sectors(out: Path):
    from pykrx import stock

    rows = []
    fails = []
    for q in quarter_firsts():
        d = stock.get_nearest_business_day_in_a_week(q.strftime("%Y%m%d"), prev=False)
        for market in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_sector_classifications(d, market)
            time.sleep(SLEEP)
            if df is None or df.empty:
                print(f"  [실패] {d} {market}: 빈 응답")
                fails.append((d, market))
                continue
            df = df.reset_index()
            part = pd.DataFrame({
                "date": pd.Timestamp(d),
                "market": market,
                "ticker": df["종목코드"].astype(str).str.zfill(6),
                "name": df["종목명"],
                "sector": df["업종명"],
            })
            rows.append(part)
            print(f"  {d} {market}: {len(part)}종목 · {part['sector'].nunique()}업종")
    if not rows:
        raise RuntimeError("업종분류 스냅샷을 하나도 받지 못함 (KRX 로그인 여부 확인)")
    allrows = pd.concat(rows, ignore_index=True)
    f = out / "classifications.csv"
    allrows.to_csv(f, index=False, encoding="utf-8-sig")
    print(f"→ {f}: {len(allrows)}행, 스냅샷 {allrows['date'].nunique()}개, 실패 {len(fails)}건 {fails or ''}")


# ------------------------------------------------------------ ② 업종지수 일봉
def collect_index(out: Path):
    from pykrx import stock

    lst = []
    for market in ("KOSPI", "KOSDAQ"):
        for code in stock.get_index_ticker_list(market=market):
            lst.append({"index_code": code, "index_name": stock.get_index_ticker_name(code),
                        "market": market})
        time.sleep(SLEEP)
    lst = pd.DataFrame(lst)
    f = out / "index_list.csv"
    lst.to_csv(f, index=False, encoding="utf-8-sig")
    print(f"→ {f}: {len(lst)}개 지수")

    end = today_str()
    parts = []
    for _, r in lst.iterrows():
        df = stock.get_index_ohlcv_by_date(START, end, r["index_code"])
        time.sleep(SLEEP)
        if df is None or df.empty:
            print(f"  [실패] 지수 {r['index_code']} {r['index_name']}: 빈 응답")
            continue
        df = df.reset_index().rename(columns={
            "날짜": "date", "시가": "open", "고가": "high", "저가": "low",
            "종가": "close", "거래량": "volume", "거래대금": "value", "상장시가총액": "mktcap"})
        df.insert(1, "index_code", r["index_code"])
        parts.append(df[["date", "index_code", "open", "high", "low", "close", "volume"]])
        print(f"  {r['index_code']} {r['index_name']}: {len(df)}일")
    allidx = pd.concat(parts, ignore_index=True)
    f = out / "index_ohlcv.csv"
    allidx.to_csv(f, index=False, encoding="utf-8-sig")
    print(f"→ {f}: {len(allidx)}행 ({allidx['index_code'].nunique()}개 지수)")


# ------------------------------------------------------------ 폴백: KIND 표준산업분류
def collect_kind(out: Path):
    r = requests.get("https://kind.krx.co.kr/corpgeneral/corpList.do",
                     params={"method": "download", "searchType": "13"}, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_html(io.StringIO(r.content.decode("euc-kr", "replace")), converters={"종목코드": str})[0]
    res = pd.DataFrame({
        "date": pd.Timestamp(dt.date.today()),
        "market": df["시장구분"].replace({"유가": "KOSPI", "코스닥": "KOSDAQ", "코넥스": "KONEX"}),
        "ticker": df["종목코드"].str.strip().str.zfill(6),
        "name": df["회사명"],
        "industry": df["업종"],
    })
    f = out / "kind_industry.csv"
    res.to_csv(f, index=False, encoding="utf-8-sig")
    print(f"→ {f}: {len(res)}종목 (표준산업분류 {res['industry'].nunique()}개) — 현재 상장사만, KRX 업종지수 체계와 다름")


# ------------------------------------------------------------ ③ 검증
def verify(out: Path):
    f = out / "classifications.csv"
    if not f.exists():
        print(f"{f} 없음 — sectors 수집을 먼저 실행")
        return
    df = pd.read_csv(f, dtype={"ticker": str}, parse_dates=["date"])
    print(f"스냅샷 {df['date'].nunique()}개 ({df['date'].min().date()} ~ {df['date'].max().date()}), 총 {len(df)}행")
    for market, g in df.groupby("market"):
        per = g.groupby(["date", "sector"])["ticker"].count()
        print(f"\n[{market}] 업종 수(스냅샷별): {g.groupby('date')['sector'].nunique().min()}~"
              f"{g.groupby('date')['sector'].nunique().max()}, "
              f"업종당 종목 수: 중앙값 {per.median():.0f}, 최소 {per.min()}, 최대 {per.max()}")
        last = g[g["date"] == g["date"].max()]
        print(f"  최신 스냅샷 업종명 예: {sorted(last['sector'].unique())[:8]} …")
    # 업종명 체계가 중간에 바뀌는지
    by_year = df.assign(y=df["date"].dt.year).groupby("y")["sector"].nunique()
    print(f"\n연도별 업종명 개수: {dict(by_year)}")

    # 상폐 종목 포함 여부 (universe.csv 교차)
    for cand in (out / "universe.csv", out.parent / "universe.csv",
                 Path(__file__).resolve().parent.parent / "data-backtest" / "universe.csv"):
        if cand.exists():
            uni = pd.read_csv(cand, dtype={"ticker": str})
            delisted = set(uni.loc[uni["is_listed_now"] == False, "ticker"])  # noqa: E712
            hit = df[df["ticker"].isin(delisted)]
            print(f"\nuniverse.csv({cand}) 상폐 {len(delisted)}종목 중 "
                  f"{hit['ticker'].nunique()}종목이 과거 스냅샷에 등장 (행 {len(hit)})")
            if not hit.empty:
                ex = hit.sort_values("date").groupby("ticker").last().head(5)
                print("  예:", [(t, r['name'], str(r['date'].date())) for t, r in ex.iterrows()])
            break
    else:
        print("\nuniverse.csv 못 찾음 → 상폐 교차 검증 생략")


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "data-backtest")
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    out = outdir / "sectors"
    out.mkdir(parents=True, exist_ok=True)

    if mode == "verify":
        verify(out)
        return
    if mode in ("kind", "all"):
        collect_kind(out)
    if mode in ("sectors", "index", "all"):
        if not has_krx_login():
            print("KRX_ID/KRX_PW 없음 → 업종분류 스냅샷·업종지수 수집 불가 "
                  "(GitHub Actions sector-data.yml 로 실행하거나 환경변수 설정). KIND 폴백만 저장됨.")
            return
        if mode in ("sectors", "all"):
            collect_sectors(out)
        if mode in ("index", "all"):
            collect_index(out)
        verify(out)


if __name__ == "__main__":
    main()
