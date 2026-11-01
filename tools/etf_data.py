"""업종·테마 ETF 시점별 데이터 수집 — '신고가 섹터(ETF판)' 백테스트용 (지난 B3는 KRX 업종이 너무 넓어 기각)

데이터 출처: KRX 정보데이터시스템 (pykrx). data.krx.co.kr 조회는 KRX 로그인 필요 → KRX_ID/KRX_PW 환경변수
(저장소 GitHub Secrets 에만 있음 — .github/workflows/etf-data.yml 이 실행해 data 브랜치 etf/ 에 저장).

사용법:
    python tools/etf_data.py <출력폴더> [probe|list|ohlcv|pdf|all|verify]
      list   매달 첫 거래일에 상장돼 있던 ETF 목록(나중에 상장폐지된 ETF 포함) → etf/lists.csv (date,ticker)
             + 이름 → etf/names.csv (ticker,name)
      ohlcv  후보 ETF 일봉 2014~ → etf/ohlcv.csv.gz (date,ticker,open,high,low,close,volume,value,nav)
      pdf    후보 ETF 구성종목(PDF) 분기 첫 거래일 스냅샷 → etf/pdf/YYYYMMDD.csv (etf,code,name,shares,amount,weight)
             + 가장 최근 거래일 스냅샷(실전 화면용). 이미 받은 분기 파일은 건너뜀 → 시간 초과 뒤 다시 돌리면 이어받음
      verify 받은 파일 통계

후보 ETF: 이름으로 국내 주식형이 아닌 것만 미리 뺌(레버리지·인버스·선물·채권·금리·현금·통화·해외·원자재·혼합·리츠·TDF·커버드콜).
          지수형(코스피200 등)과 업종·테마형 구분은 구성종목을 보고 백테스트 쪽에서 함 (이름 규칙보다 정확).

시점 규칙: 백테스트는 t일에 '직전 스냅샷'의 구성종목만 쓴다 (look-ahead 방지). ETF 신고가 판정은 그날까지의 ETF 일봉만.
"""
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

START = "20140101"          # ETF 일봉 시작 (2015년부터 252일 비교가 되도록)
LIST_START = "2014-01-01"   # 월별 목록 시작
PDF_START = "2015-01-01"    # 분기 PDF 시작
SLEEP = 0.7
T0 = time.time()            # 시간 한도(Actions 6시간)는 프로세스 시작부터 잼

EXCLUDE = re.compile(
    r"레버리지|인버스|2X|3X|선물|채권|국채|국고채|회사채|크레딧|금리|CD|KOFR|SOFR|머니마켓|MMF|단기|통안|"
    r"달러|엔화|위안|유로|미국|美|중국|차이나|일본|인도|베트남|글로벌|선진국|신흥국|아시아|유럽|독일|대만|홍콩|"
    r"나스닥|NASDAQ|S&P|다우|필라델피아|원유|WTI|골드|금현물|금선물|은선물|구리|원자재|농산물|리츠|REIT|인프라|부동산|"
    r"TDF|TRF|혼합|채혼|커버드콜|프리미엄|버퍼|타겟|TIF|멀티에셋|자산배분|하이일드|물가|만기|인컴|"
    r"브라질|러시아|라틴|중남미|사우디|인니|인도네시아|멕시코|호주|캐나다|영국|프랑스|스페인|이탈리아|싱가포르|"
    r"항셍|니케이|토픽스|TOPIX|CSI|FTSE|STOXX|유로스탁스|월드|ACWI|해외")


def has_krx_login() -> bool:
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def today_str() -> str:
    return dt.date.today().strftime("%Y%m%d")


def trading_days():
    from pykrx import stock
    ix = stock.get_index_ohlcv_by_date(START, today_str(), "1001")
    return [d.strftime("%Y%m%d") for d in ix.index]


def firsts(days, freq):
    """각 달(M)·분기(Q)의 첫 거래일"""
    s = pd.Series(pd.to_datetime(days))
    key = s.dt.to_period(freq)
    return [d.strftime("%Y%m%d") for d in s.groupby(key).min()]


def retry(fn, tries=3, wait=3):
    last = None
    for k in range(tries):
        try:
            r = fn()
            time.sleep(SLEEP)
            return r
        except Exception as e:  # noqa: BLE001 — KRX 일시 오류는 재시도
            last = e
            time.sleep(wait * (k + 1))
    print(f"    [재시도 실패] {repr(last)[:160]}")
    return None


# ------------------------------------------------------------ 점검
def probe():
    from pykrx import stock
    t0 = time.time()
    a = stock.get_etf_ticker_list("20160104"); b = stock.get_etf_ticker_list("20251017")
    print(f"[probe] ETF 목록 2016-01-04 {len(a)}개 · 2025-10-17 {len(b)}개 ({time.time() - t0:.1f}s)")
    gone = [t for t in a if t not in set(b)][:5]
    print(f"[probe] 2016엔 있고 2025엔 없는(상장폐지) 예: {gone}")
    for t in ["091160"] + gone[:3]:
        try:
            print(f"[probe] 이름 {t}: {stock.get_etf_ticker_name(t)}")
        except Exception as e:
            print(f"[probe] 이름 {t}: EXC {repr(e)[:120]}")
    tests = [
        ("일봉 091160 2016", lambda: stock.get_etf_ohlcv_by_date("20160104", "20160115", "091160")),
        ("PDF 091160 현재", lambda: stock.get_etf_portfolio_deposit_file("091160")),
        ("PDF 091160 2016-01-04", lambda: stock.get_etf_portfolio_deposit_file("091160", "20160104")),
        ("PDF 091160 2020-01-02", lambda: stock.get_etf_portfolio_deposit_file("091160", "20200102")),
        ("PDF 305540(2차전지) 2021-01-04", lambda: stock.get_etf_portfolio_deposit_file("305540", "20210104")),
    ]
    if gone:
        tests += [(f"일봉 상폐 {gone[0]} 2016", lambda: stock.get_etf_ohlcv_by_date("20160104", "20160115", gone[0])),
                  (f"PDF 상폐 {gone[0]} 2016-01-04", lambda: stock.get_etf_portfolio_deposit_file(gone[0], "20160104"))]
    for name, fn in tests:
        t0 = time.time()
        try:
            r = fn()
            print(f"[probe] {name}: shape={getattr(r, 'shape', None)} cols={list(getattr(r, 'columns', []))} ({time.time() - t0:.1f}s)")
            if hasattr(r, "head") and len(r):
                print(r.head(4).to_string())
        except Exception as e:
            print(f"[probe] {name}: EXC {repr(e)[:160]}")
        time.sleep(SLEEP)
    print(f"[probe] 이름 제외 규칙으로 2025-10-17 목록 중 후보: {sum(1 for t in b if not EXCLUDE.search(name_of(t)))}개")


_NAMES = {}


def name_of(t):
    if t not in _NAMES:
        from pykrx import stock
        try:
            _NAMES[t] = stock.get_etf_ticker_name(t) or ""
        except Exception:  # noqa: BLE001
            _NAMES[t] = ""
    return _NAMES[t]


# ------------------------------------------------------------ ① 월별 목록 + 이름
def collect_list(out: Path):
    from pykrx import stock
    days = trading_days()
    rows = []
    for d in firsts([x for x in days if x >= LIST_START.replace("-", "")], "M") + [days[-1]]:
        ts = retry(lambda: stock.get_etf_ticker_list(d)) or []
        rows += [(d, t) for t in ts]
        print(f"  목록 {d}: {len(ts)}개")
    lst = pd.DataFrame(rows, columns=["date", "ticker"]).drop_duplicates()
    lst.to_csv(out / "lists.csv", index=False)
    names = [(t, name_of(t)) for t in sorted(lst.ticker.unique())]
    nm = pd.DataFrame(names, columns=["ticker", "name"])
    nm.to_csv(out / "names.csv", index=False, encoding="utf-8-sig")
    print(f"→ lists.csv {len(lst):,}행 (ETF {lst.ticker.nunique():,}개) · 이름 없음 {int((nm.name == '').sum())}개")


def candidates(out: Path):
    nm = pd.read_csv(out / "names.csv", dtype=str).fillna("")
    keep = nm[~nm.name.str.contains(EXCLUDE)]
    return set(keep.ticker)


# ------------------------------------------------------------ ② 일봉
def collect_ohlcv(out: Path):
    from pykrx import stock
    cand = sorted(candidates(out))
    parts, fails = [], []
    for n, t in enumerate(cand):
        df = retry(lambda: stock.get_etf_ohlcv_by_date(START, today_str(), t))
        if df is None or df.empty:
            fails.append(t); continue
        df = df.reset_index()
        cols = {"날짜": "date", "시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value", "NAV": "nav"}
        df = df.rename(columns=cols)[[c for c in cols.values() if c in df.rename(columns=cols).columns]]
        df.insert(1, "ticker", t)
        parts.append(df)
        if n % 50 == 0:
            print(f"  일봉 {n + 1}/{len(cand)} {t} {len(df)}일")
    allp = pd.concat(parts, ignore_index=True)
    allp.to_csv(out / "ohlcv.csv.gz", index=False, compression="gzip")
    print(f"→ ohlcv.csv.gz {len(allp):,}행 · ETF {allp.ticker.nunique():,}개 · 실패 {len(fails)} {fails[:10]}")


# ------------------------------------------------------------ ③ 구성종목 스냅샷
def collect_pdf(out: Path, deadline_min=320):
    from pykrx import stock
    t_start = T0
    pdir = out / "pdf"; pdir.mkdir(exist_ok=True)
    lst = pd.read_csv(out / "lists.csv", dtype=str)
    cand = candidates(out)
    days = trading_days()
    snaps = firsts([x for x in days if x >= PDF_START.replace("-", "")], "Q") + [days[-1]]
    for d in snaps:
        f = pdir / f"{d}.csv"
        if f.exists():
            continue
        month = d[:6]
        avail = lst[lst.date.str[:6] == month].ticker.unique()          # 그 달 첫날 목록 (분기 첫날과 같은 달)
        ts = sorted(set(avail) & cand)
        rows, nfail = [], 0
        for t in ts:
            if (time.time() - t_start) / 60 > deadline_min:
                print(f"  시간 한도 → {d} 미완료로 중단 (다음 실행에서 이어받음)"); return False
            df = retry(lambda: stock.get_etf_portfolio_deposit_file(t, d))
            if df is None or df.empty:
                nfail += 1; continue
            df = df.reset_index()
            code_col = df.columns[0]
            for _, r in df.iterrows():
                rows.append((t, str(r[code_col]), r.get("계약수"), r.get("금액"), r.get("비중")))
        pd.DataFrame(rows, columns=["etf", "code", "shares", "amount", "weight"]).to_csv(f, index=False)
        print(f"  PDF {d}: ETF {len(ts)}개 · 행 {len(rows):,} · 실패 {nfail} ({(time.time() - t_start) / 60:.0f}분)")
    return True


def verify(out: Path):
    for p in ("lists.csv", "names.csv", "ohlcv.csv.gz"):
        f = out / p
        if f.exists():
            df = pd.read_csv(f, dtype=str)
            print(f"{p}: {len(df):,}행 · {df.iloc[:, 1 if p != 'names.csv' else 0].nunique():,}개")
    pd_files = sorted((out / "pdf").glob("*.csv")) if (out / "pdf").exists() else []
    for f in pd_files:
        df = pd.read_csv(f, dtype=str)
        print(f"pdf/{f.name}: ETF {df.etf.nunique()} · 행 {len(df):,}")


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "data-backtest")
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    out = outdir / "etf"
    out.mkdir(parents=True, exist_ok=True)
    if mode == "verify":
        verify(out); return
    if not has_krx_login():
        print("KRX_ID/KRX_PW 없음 → 수집 불가 (GitHub Actions etf-data.yml 로 실행)"); return
    if mode == "probe":
        probe(); return
    if mode in ("list", "all"):
        collect_list(out)
    if mode in ("ohlcv", "all"):
        collect_ohlcv(out)
    if mode in ("pdf", "all"):
        collect_pdf(out)
    verify(out)


if __name__ == "__main__":
    main()
