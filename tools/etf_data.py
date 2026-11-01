"""업종·테마 ETF 시점별 데이터 수집 — '신고가 섹터(ETF판)' 백테스트용 (지난 B3는 KRX 업종이 너무 넓어 기각)

데이터 출처: KRX 정보데이터시스템 (pykrx 내부 조회 클래스). data.krx.co.kr 조회는 KRX 로그인 필요 → KRX_ID/KRX_PW 환경변수
(저장소 GitHub Secrets 에만 있음 — .github/workflows/etf-data.yml 이 실행해 data 브랜치 etf/ 에 저장).

왜 pykrx 기본 함수를 안 쓰나: get_etf_ticker_list(날짜)는 '지금 상장된 ETF 중 그날 이전 상장'만 돌려줘서 상장폐지 ETF가 빠짐
(2016-01-04 154개 vs 실제 약 200개 → 실패한 테마가 빠지는 생존편향). 대신
  · [13101] 전종목 시세(MDCSTAT04301)를 거래일마다 받음 → 그날 실제로 거래된 ETF 전부(나중에 폐지된 것 포함)의 이름·기초지수·OHLCV
  · [13108] PDF(MDCSTAT05001)는 ISIN 이 필요 → 단축코드로 ISIN 을 직접 계산 (KR7 + 코드 + 00 + 검사숫자) → 폐지 ETF 도 조회

사용법:
    python tools/etf_data.py <출력폴더> [probe|daily|pdf|all|verify]
      daily  거래일마다 전 종목 ETF 시세 → etf/daily/YYYYMM.csv.gz (date,ticker,name,index,open,high,low,close,volume,value,mktcap,nav)
             국내 주식형이 아닌 것(레버리지·인버스·채권·해외 등, 이름·기초지수로 판단)은 저장 안 함.
             이미 받은 달은 건너뜀(이번 달은 늘 다시) → 시간 한도 뒤 다시 돌리면 이어받음
      pdf    후보 ETF 구성종목 분기 첫 거래일 스냅샷 + 가장 최근 거래일 → etf/pdf/YYYYMMDD.csv (etf,code,name,shares,amount,weight)
      verify 받은 파일 통계

시점 규칙: 백테스트는 t일에 '직전 스냅샷'의 구성종목만 쓴다 (look-ahead 방지). ETF 신고가 판정은 그날까지의 ETF 일봉만.
지수형(코스피200 등)과 업종·테마형 구분은 구성종목을 보고 백테스트 쪽에서 함.
"""
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

START = "20140101"          # 일봉 시작 (2015년부터 252일 비교가 되도록)
PDF_START = "2015-01-01"    # 분기 PDF 시작
SLEEP = 0.6
T0 = time.time()            # 시간 한도(Actions 6시간)는 프로세스 시작부터 잼
DEADLINE_MIN = float(os.environ.get("ETF_DEADLINE_MIN", 320))   # 워크플로가 남은 시간을 넘겨줌

EXCLUDE = re.compile(
    r"레버리지|인버스|2X|3X|선물|채권|국채|국고채|회사채|크레딧|금리|CD|KOFR|SOFR|머니마켓|MMF|단기|통안|"
    r"달러|엔화|위안|유로|미국|美|중국|차이나|일본|인도|베트남|글로벌|선진국|신흥국|아시아|유럽|독일|대만|홍콩|"
    r"나스닥|NASDAQ|S&P|다우|필라델피아|원유|WTI|골드|금현물|금선물|은선물|구리|원자재|농산물|리츠|REIT|인프라|부동산|"
    r"TDF|TRF|혼합|채혼|커버드콜|프리미엄|버퍼|타겟|TIF|멀티에셋|자산배분|하이일드|물가|만기|인컴|"
    r"브라질|러시아|라틴|중남미|사우디|인니|인도네시아|멕시코|호주|캐나다|영국|프랑스|스페인|이탈리아|싱가포르|"
    r"항셍|니케이|토픽스|TOPIX|CSI|FTSE|STOXX|유로스탁스|월드|ACWI|해외|Bond|BOND|Treasury|USD|China|Japan|India|Global")

COLS = {"ISU_SRT_CD": "ticker", "ISU_ABBRV": "name", "IDX_IND_NM": "index", "TDD_OPNPRC": "open", "TDD_HGPRC": "high",
        "TDD_LWPRC": "low", "TDD_CLSPRC": "close", "ACC_TRDVOL": "volume", "ACC_TRDVAL": "value", "MKTCAP": "mktcap", "NAV": "nav"}


def has_krx_login() -> bool:
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def today_str() -> str:
    return dt.date.today().strftime("%Y%m%d")


def over_time() -> bool:
    return (time.time() - T0) / 60 > DEADLINE_MIN


def isin_of(code: str) -> str:
    """한국 ETF 단축코드 → ISIN (KR7 + 코드6 + 00 + 검사숫자, ISO 6166 Luhn)"""
    body = f"KR7{code}00"
    digits = "".join(str(int(ch, 36)) for ch in body)        # 문자 → 숫자 (A=10 … Z=35)
    total = 0
    for k, ch in enumerate(reversed(digits)):
        v = int(ch)
        if k % 2 == 0:
            v *= 2
            v = v - 9 if v > 9 else v
        total += v
    return body + str((10 - total % 10) % 10)


def trading_days():
    from pykrx import stock
    ix = stock.get_index_ohlcv_by_date(START, today_str(), "1001")
    return [d.strftime("%Y%m%d") for d in ix.index]


def quarter_firsts(days):
    s = pd.Series(pd.to_datetime([d for d in days if d >= PDF_START.replace("-", "")]))
    return [d.strftime("%Y%m%d") for d in s.groupby(s.dt.to_period("Q")).min()]


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


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").replace({"-": None, "": None}), errors="coerce")


def day_table(d):
    from pykrx.website.krx.etx.core import 전종목시세_ETF
    raw = 전종목시세_ETF().fetch(d)
    if raw is None or raw.empty:
        return None
    df = raw[[c for c in COLS if c in raw.columns]].rename(columns=COLS)
    for c in ("open", "high", "low", "close", "volume", "value", "mktcap", "nav"):
        if c in df:
            df[c] = num(df[c])
    df.insert(0, "date", d)
    return df


def keep_rows(df):
    txt = df["name"].fillna("") + " " + df.get("index", pd.Series("", index=df.index)).fillna("")
    return df[~txt.str.contains(EXCLUDE)]


def pdf_table(d, code):
    from pykrx.website.krx.etx.core import PDF
    raw = PDF().fetch(d, isin_of(code))
    if raw is None or raw.empty:
        return None
    m = {"COMPST_ISU_CD": "code", "COMPST_ISU_NM": "name", "COMPST_ISU_CU1_SHRS": "shares", "COMPST_AMT": "amount", "COMPST_RTO": "weight"}
    df = raw[[c for c in m if c in raw.columns]].rename(columns=m)
    for c in ("shares", "amount", "weight"):
        if c in df:
            df[c] = num(df[c])
    df.insert(0, "etf", code)
    return df


# ------------------------------------------------------------ 점검
def probe():
    from pykrx import stock
    for code, want in (("152100", "KR7152100004"), ("295820", "KR7295820005"), ("091160", None)):
        print(f"[probe] ISIN {code}: 계산 {isin_of(code)} · 기대 {want or '-'}")
    for d in ("20160104", "20251017"):
        t0 = time.time()
        df = day_table(d)
        print(f"[probe] 전종목 시세 {d}: {0 if df is None else len(df)}개 ({time.time() - t0:.1f}s) · 국내 주식형 후보 {0 if df is None else len(keep_rows(df))}개")
        if df is not None:
            print(df.head(3).to_string())
        time.sleep(SLEEP)
    now = set(stock.get_etf_ticker_list("20251017"))
    old = day_table("20160104")
    gone = old[~old.ticker.isin(now)] if old is not None else pd.DataFrame()
    print(f"[probe] 2016-01-04에 거래됐지만 지금은 없는(상장폐지) ETF: {len(gone)}개 · 예: {gone[['ticker', 'name']].head(8).values.tolist() if len(gone) else []}")
    test = [("091160", "20160104")] + ([(t, "20160104") for t in keep_rows(gone).ticker.head(3)] if len(gone) else [])
    for code, d in test:
        t0 = time.time()
        try:
            df = pdf_table(d, code)
            print(f"[probe] PDF {code} {d}: {0 if df is None else len(df)}행 ({time.time() - t0:.1f}s)")
            if df is not None:
                print(df.head(3).to_string())
        except Exception as e:
            print(f"[probe] PDF {code} {d}: EXC {repr(e)[:160]}")
        time.sleep(SLEEP)


# ------------------------------------------------------------ ① 거래일별 전 종목 시세
def collect_daily(out: Path):
    ddir = out / "daily"; ddir.mkdir(exist_ok=True)
    days = trading_days()
    this_month = days[-1][:6]
    months = sorted({d[:6] for d in days})
    for mth in months:
        f = ddir / f"{mth}.csv.gz"
        if f.exists() and mth != this_month:
            continue
        if over_time():
            print("  시간 한도 → 일봉 중단 (다음 실행에서 이어받음)"); return False
        parts, nfail = [], 0
        for d in [x for x in days if x[:6] == mth]:
            df = retry(lambda: day_table(d))
            if df is None:
                nfail += 1; continue
            parts.append(keep_rows(df))
        if not parts:
            print(f"  {mth}: 받은 날 없음"); continue
        allp = pd.concat(parts, ignore_index=True)
        allp.to_csv(f, index=False, compression="gzip")
        print(f"  {mth}: {allp.date.nunique()}일 · ETF {allp.ticker.nunique()}개 · 실패 {nfail}일 ({(time.time() - T0) / 60:.0f}분)")
    return True


def daily_frame(out: Path):
    fs = sorted((out / "daily").glob("*.csv.gz"))
    return pd.concat([pd.read_csv(f, dtype={"ticker": str, "date": str}) for f in fs], ignore_index=True)


# ------------------------------------------------------------ ② 구성종목 스냅샷
def collect_pdf(out: Path):
    pdir = out / "pdf"; pdir.mkdir(exist_ok=True)
    dd = daily_frame(out)
    days = sorted(dd.date.unique())
    snaps = quarter_firsts(days) + [days[-1]]
    for d in snaps:
        f = pdir / f"{d}.csv"
        if f.exists():
            continue
        ts = sorted(dd.loc[dd.date == d, "ticker"].unique())
        parts, nfail = [], 0
        for t in ts:
            if over_time():
                print(f"  시간 한도 → {d} 미완료로 중단 (다음 실행에서 이어받음)"); return False
            df = retry(lambda: pdf_table(d, t))
            if df is None or df.empty:
                nfail += 1; continue
            parts.append(df)
        if parts:
            pd.concat(parts, ignore_index=True).to_csv(f, index=False)
        print(f"  PDF {d}: ETF {len(ts)}개 · 받은 것 {len(parts)} · 실패 {nfail} ({(time.time() - T0) / 60:.0f}분)")
    return True


def verify(out: Path):
    if (out / "daily").exists() and any((out / "daily").glob("*.csv.gz")):
        dd = daily_frame(out)
        print(f"daily: {len(dd):,}행 · {dd.date.min()}~{dd.date.max()} · ETF {dd.ticker.nunique():,}개")
        for y in sorted({d[:4] for d in dd.date}):
            s = dd[dd.date.str[:4] == y]
            print(f"  {y}: 첫날 ETF {s[s.date == s.date.min()].ticker.nunique()}개")
    for f in sorted((out / "pdf").glob("*.csv")) if (out / "pdf").exists() else []:
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
    ok = True
    if mode in ("daily", "all"):
        ok = collect_daily(out)
    if ok and mode in ("pdf", "all"):
        collect_pdf(out)
    verify(out)


if __name__ == "__main__":
    main()
