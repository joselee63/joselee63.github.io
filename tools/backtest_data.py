"""생존편향 없는 한국 주식 백테스트 데이터셋 수집.

유니버스 = KIND 현재 상장법인 목록 ∪ KIND 상장폐지 목록(2015-01-01 이후 폐지)
           (+ KRX_ID/KRX_PW 환경변수가 있으면 pykrx 분기별 get_market_ticker_list 스냅샷)
일봉 = pykrx get_market_ohlcv(수정주가, 네이버 출처) — 상장폐지 종목도 마지막 거래일까지 받아짐.

사용법 (중단 후 다시 실행하면 이미 받은 티커는 건너뜀):
    python tools/backtest_data.py            # universe → ohlcv → build 전부
    python tools/backtest_data.py build      # 수집 없이 결과 파일만 다시 만들기

출력 (data-backtest/):
    universe.csv            티커·이름·시장·상장일·폐지일·폐지사유·현재상장 여부
    ohlcv/{ticker}.pkl      티커별 일봉 체크포인트
    ohlcv_all.pkl           long format: date, ticker, open, high, low, close, volume, change
    listing_periods.csv     티커별 첫/마지막 거래일(실데이터 기준) → 임의 날짜의 유니버스 구성용
    snapshots_quarterly.csv 분기 첫 거래일마다 그 시점에 거래되던 티커 (date, ticker)
    snapshots_krx.csv       (KRX 로그인 시) pykrx 공식 분기별 티커 리스트
"""
import datetime as dt
import os
import re
import sys
import time
import io
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data-backtest"
OHLCV_DIR = OUT / "ohlcv"
START = "20150101"
SLEEP = 0.4
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}


def today_str():
    return dt.date.today().strftime("%Y%m%d")


def quarter_starts(start=START, end=None):
    end = pd.Timestamp(end or today_str())
    return list(pd.date_range(pd.Timestamp(start), end, freq="QS"))


# ---------------------------------------------------------------- universe
def kind_listed():
    r = requests.get("https://kind.krx.co.kr/corpgeneral/corpList.do",
                     params={"method": "download", "searchType": "13"}, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_html(io.StringIO(r.content.decode("euc-kr", "replace")), converters={"종목코드": str})[0]
    return pd.DataFrame({
        "ticker": df["종목코드"].str.strip().str.zfill(6),
        "name": df["회사명"],
        "market": df["시장구분"].replace({"유가": "KOSPI", "코스닥": "KOSDAQ", "코넥스": "KONEX"}),
        "listed_date": pd.to_datetime(df["상장일"], errors="coerce"),
    })


ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td class=\"first txc\"[^>]*>(\d+)</td>\s*"
    r"<td>\s*<img[^>]*alt='([^']*)'.*?companysummary_open\('(\w+)'\).*?title='([^']*)'.*?</td>\s*"
    r"<td class=\"txc\">([\d-]+)</td>\s*<td>(.*?)</td>", re.S)


def kind_delisted(from_date="2015-01-01"):
    s = requests.Session()
    s.headers.update(UA)
    main = s.get("https://kind.krx.co.kr/investwarn/delcompany.do",
                 params={"method": "searchDelCompanyMain"}, timeout=60)
    data = {"method": "searchDelCompanySub", "currentPageSize": "5000", "pageIndex": "1",
            "orderMode": "1", "orderStat": "D", "searchMode": "", "searchCodeType": "",
            "searchCorpName": "", "marketType": "", "repIsuSrtCd": "",
            "fromDate": from_date, "toDate": dt.date.today().isoformat(), "forward": "delcompany_sub"}
    r = s.post("https://kind.krx.co.kr/investwarn/delcompany.do", data=data,
               headers={"Referer": main.url, "X-Requested-With": "XMLHttpRequest"}, timeout=120)
    r.raise_for_status()
    rows = ROW_RE.findall(r.text)
    total = re.search(r"<td class=\"first txc\"[^>]*>(\d+)</td>", r.text)
    total = int(total.group(1)) if total else 0
    if len(rows) != total:
        raise RuntimeError(f"KIND 상장폐지 목록 파싱 불일치: {len(rows)}행 / 표시 {total}건")
    mk = {"유가증권": "KOSPI", "코스닥": "KOSDAQ", "코넥스": "KONEX"}
    return pd.DataFrame([{
        "ticker": (code + "0").zfill(6),
        "name": re.sub(r"\s+", " ", name).strip(),
        "market": mk.get(alt, alt),
        "delisted_date": pd.Timestamp(d),
        "delist_reason": re.sub(r"<[^>]+>", "", reason).strip(),
    } for _, alt, code, name, d, reason in rows])


def krx_snapshots():
    """KRX 로그인이 가능할 때만: 분기별 공식 상장 티커 리스트."""
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("KRX_ID/KRX_PW 없음 → pykrx 공식 분기 스냅샷 생략 (KIND 목록 + 실거래 기간으로 대체)")
        return None
    from pykrx import stock
    out = []
    for q in quarter_starts():
        d = stock.get_nearest_business_day_in_a_week(q.strftime("%Y%m%d"), prev=False)
        for t in stock.get_market_ticker_list(d, market="ALL"):
            out.append((pd.Timestamp(d), t))
        print(f"  KRX 스냅샷 {d}: 누적 {len(out)}")
        time.sleep(SLEEP)
    return pd.DataFrame(out, columns=["date", "ticker"])


def build_universe():
    OUT.mkdir(exist_ok=True)
    listed = kind_listed()
    print(f"KIND 현재 상장: {len(listed)}")
    time.sleep(SLEEP)
    deli = kind_delisted()
    print(f"KIND 2015년 이후 상장폐지: {len(deli)}")
    snaps = krx_snapshots()

    listed["is_listed_now"] = True
    deli = deli.sort_values("delisted_date").drop_duplicates("ticker", keep="last")
    uni = listed.merge(deli, on="ticker", how="outer", suffixes=("", "_d"))
    uni["name"] = uni["name"].fillna(uni["name_d"])
    uni["market"] = uni["market"].fillna(uni["market_d"])
    uni["is_listed_now"] = uni["is_listed_now"].eq(True)
    uni = uni.drop(columns=["name_d", "market_d"])
    if snaps is not None:
        snaps.to_csv(OUT / "snapshots_krx.csv", index=False)
        extra = sorted(set(snaps["ticker"]) - set(uni["ticker"]))
        print(f"KRX 스냅샷에만 있는 티커 {len(extra)}개 추가")
        uni = pd.concat([uni, pd.DataFrame({"ticker": extra, "is_listed_now": False})], ignore_index=True)
    uni = uni.sort_values("ticker").reset_index(drop=True)
    uni.to_csv(OUT / "universe.csv", index=False, encoding="utf-8-sig")
    print(f"유니버스 합계: {len(uni)} 티커 → {OUT / 'universe.csv'}")
    return uni


# ---------------------------------------------------------------- ohlcv
def fetch_ohlcv(tickers, end=None):
    from pykrx import stock
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    end = end or today_str()
    todo = [t for t in tickers if not (OHLCV_DIR / f"{t}.pkl").exists()]
    print(f"OHLCV: 전체 {len(tickers)} / 이미 받음 {len(tickers) - len(todo)} / 남음 {len(todo)}")
    failed, t0 = [], time.time()
    for i, t in enumerate(todo, 1):
        df = None
        for attempt in range(3):
            try:
                df = stock.get_market_ohlcv(START, end, t)
                break
            except Exception as e:  # 네트워크·파싱 오류 → 대기 후 재시도
                print(f"  {t} 실패({attempt + 1}/3): {e!r}")
                time.sleep(2 * (attempt + 1))
        if df is None:
            failed.append(t)
        else:
            df.to_pickle(OHLCV_DIR / f"{t}.pkl")  # 빈 결과도 저장해 재실행 시 건너뜀
        time.sleep(SLEEP)
        if i % 50 == 0 or i == len(todo):
            el = time.time() - t0
            print(f"  [{i}/{len(todo)}] {el / 60:.1f}분 경과, 남은 예상 {el / i * (len(todo) - i) / 60:.1f}분, 실패 {len(failed)}",
                  flush=True)
    if failed:
        (OUT / "failed.txt").write_text("\n".join(failed), encoding="utf-8")
        print(f"실패 {len(failed)}개 → failed.txt (다시 실행하면 재시도)")
    return failed


# ---------------------------------------------------------------- build
COLS = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume", "등락률": "change"}


def build_outputs():
    uni = pd.read_csv(OUT / "universe.csv", dtype={"ticker": str},
                      parse_dates=["listed_date", "delisted_date"])
    frames, periods = [], []
    for t in uni["ticker"]:
        p = OHLCV_DIR / f"{t}.pkl"
        if not p.exists():
            continue
        df = pd.read_pickle(p)
        if df.empty:
            periods.append({"ticker": t, "first_date": pd.NaT, "last_date": pd.NaT, "n_bars": 0})
            continue
        df = df.rename(columns=COLS)
        df = df[(df["close"] > 0)]
        df.index.name = "date"
        df = df.reset_index()
        df.insert(1, "ticker", t)
        frames.append(df)
        periods.append({"ticker": t, "first_date": df["date"].min(), "last_date": df["date"].max(),
                        "n_bars": len(df)})
    allpx = pd.concat(frames, ignore_index=True)
    allpx["ticker"] = allpx["ticker"].astype("category")
    allpx.to_pickle(OUT / "ohlcv_all.pkl")

    per = uni.merge(pd.DataFrame(periods), on="ticker", how="left")
    last_day = allpx["date"].max()
    per["has_data"] = per["n_bars"].fillna(0) > 0
    # 폐지일 이후에도 시세가 이어지면: 이전상장(같은 코드 유지) 또는 코드 재사용 → 폐지로 보지 않음
    per["delisted_in_data"] = per["has_data"] & (per["last_date"] < last_day - pd.Timedelta(days=10))
    per["code_reused_or_moved"] = per["delisted_date"].notna() & (per["last_date"] > per["delisted_date"] + pd.Timedelta(days=10))
    per.to_csv(OUT / "listing_periods.csv", index=False, encoding="utf-8-sig")

    dates = pd.DatetimeIndex(sorted(allpx["date"].unique()))
    snap = []
    for q in quarter_starts(end=last_day.strftime("%Y%m%d")):
        d = dates[dates.searchsorted(q)] if q <= dates[-1] else None
        if d is None:
            continue
        live = per[per["has_data"] & (per["first_date"] <= d) & (per["last_date"] >= d)]
        snap += [(d, t) for t in live["ticker"]]
    snap = pd.DataFrame(snap, columns=["date", "ticker"])
    snap.to_csv(OUT / "snapshots_quarterly.csv", index=False)

    # ---- 검증 출력
    n = int(per["has_data"].sum())
    dead = per[per["delisted_in_data"]]
    print("\n===== 결과 =====")
    print(f"유니버스 {len(per)} 티커, 일봉 보유 {n} 티커, 총 {len(allpx):,} 행 ({allpx['date'].min():%Y-%m-%d} ~ {last_day:%Y-%m-%d})")
    print(f"데이터가 과거에 끊긴(상장폐지) 티커: {len(dead)}")
    print(f"  KIND 폐지목록에 있는데 일봉 없음: {int((per['delisted_date'].notna() & ~per['has_data']).sum())}")
    print(f"  폐지일 뒤에도 시세 이어짐(이전상장/코드재사용): {int(per['code_reused_or_moved'].sum())}")
    print("  연도별 마지막 거래 티커 수:", dead["last_date"].dt.year.value_counts().sort_index().to_dict())
    print("  폐지 예시:")
    print(dead.sort_values("last_date").sample(min(8, len(dead)), random_state=0)[
        ["ticker", "name", "market", "last_date", "delisted_date", "delist_reason"]].to_string(index=False))
    cnt = snap.groupby("date").size()
    print("분기 스냅샷 종목 수(일부):", {f"{k:%Y-%m-%d}": v for k, v in cnt.iloc[::8].items()})
    ok = n >= 2500 and len(dead) >= 300
    print("완료 기준(2,500+ 티커, 상장폐지 다수):", "충족" if ok else "미충족")
    return ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "universe"):
        uni = build_universe()
    else:
        uni = pd.read_csv(OUT / "universe.csv", dtype={"ticker": str})
    if mode in ("all", "ohlcv"):
        fetch_ohlcv(list(uni["ticker"]))
    if mode in ("all", "build", "ohlcv"):
        build_outputs()


if __name__ == "__main__":
    main()
