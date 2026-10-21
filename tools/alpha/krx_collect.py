"""비가격 알파 연구용 KRX 전 종목 횡단면 데이터 수집 (상장폐지 종목 포함 — 과거 날짜 조회).

KRX 정보데이터시스템은 로그인 필요 → KRX_ID/KRX_PW 환경변수 (GitHub Secrets, alpha-data.yml).
과거 일자로 조회하면 그날 거래된 전 종목(이후 상폐 포함)이 나오므로 생존편향이 없다.

사용법:
    python tools/alpha/krx_collect.py <출력폴더> <mode> [시작연도] [끝연도] [--have <기존 data 폴더>]
      probe   엔드포인트·속도·행 수 점검
      flows   일자별 · 투자자별 순매수(전 종목)   → alpha/flows/YYYY/YYYY-MM.csv.gz
              열: date, ticker, {주체}_nv(순매수거래대금, 원) …  주체: FLOW_INVESTORS
      cap     일자별 시가총액·상장주식수(전 종목) → alpha/cap/YYYY/YYYY-MM.csv.gz
      fund    주간(금요일·직전 거래일) PER/PBR/EPS/BPS/DIV/DPS → alpha/fund/YYYY.csv.gz
      short   일자별 공매도 거래량(전 종목) + 잔고(T+2 공시) → alpha/short/YYYY/YYYY-MM.csv.gz
      idx     KOSPI200(1028)·KOSDAQ150(2203) 구성종목: 6·12월은 매 거래일, 그 외 달은 첫 거래일
              → alpha/idx/YYYY.csv.gz (date, index, ticker)
    완료된 달(이번 달 이전, 파일 있음)은 --have 폴더에 있으면 건너뜀 → 재실행 시 이어받기.
"""
import datetime as dt
import os
import sys
import time
from pathlib import Path

import pandas as pd

SLEEP = float(os.environ.get("KRX_SLEEP", "0.25"))
FLOW_INVESTORS = ["외국인", "기관합계", "연기금", "투신", "사모", "금융투자", "보험", "은행",
                  "기타금융", "기타법인", "개인", "기타외국인"]
FLOW_KEY = {"외국인": "frg", "기관합계": "inst", "연기금": "pension", "투신": "trust", "사모": "pef",
            "금융투자": "fininv", "보험": "insur", "은행": "bank", "기타금융": "othfin",
            "기타법인": "corp", "개인": "indiv", "기타외국인": "frg2"}


def _retry(fn, tries=3):
    for i in range(tries):
        try:
            r = fn()
            time.sleep(SLEEP)
            return r
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"    [EXC] {repr(e)[:160]}")
                return None
            time.sleep(3 * (i + 1))


def trading_days(y0, y1):
    """KOSPI 지수 일봉으로 거래일 목록 (로그인 필요)."""
    from pykrx import stock
    s = f"{y0}0101"
    e = min(dt.date.today(), dt.date(y1, 12, 31)).strftime("%Y%m%d")
    df = _retry(lambda: stock.get_index_ohlcv_by_date(s, e, "1001"))
    if df is None or df.empty:
        raise RuntimeError("거래일 목록 실패 (로그인 확인)")
    return [d.strftime("%Y%m%d") for d in df.index]


def month_groups(days):
    out = {}
    for d in days:
        out.setdefault(d[:6], []).append(d)
    return out


def done_already(have: Path | None, rel: str, ym: str) -> bool:
    cur = dt.date.today().strftime("%Y%m")
    return have is not None and ym < cur and (have / rel).exists()


# ------------------------------------------------------------ 개별 수집기
def one_flows(d):
    from pykrx import stock
    parts = []
    for inv in FLOW_INVESTORS:
        df = _retry(lambda: stock.get_market_net_purchases_of_equities_by_ticker(d, d, "ALL", inv))
        if df is None or df.empty:
            if inv in ("외국인", "기관합계", "개인"):
                return None                      # 핵심 주체 실패 → 그날 통째로 재시도 대상
            continue
        s = df["순매수거래대금"].astype("int64").rename(FLOW_KEY[inv] + "_nv")
        parts.append(s)
    out = pd.concat(parts, axis=1).fillna(0).astype("int64")
    out.index.name = "ticker"
    out = out.reset_index()
    out.insert(0, "date", d)
    return out


def one_cap(d):
    from pykrx import stock
    df = _retry(lambda: stock.get_market_cap_by_ticker(d, "ALL"))
    if df is None or df.empty:
        return None
    df = df.rename(columns={"종가": "close", "시가총액": "mcap", "거래량": "volume",
                            "거래대금": "value", "상장주식수": "shares"})
    df.index.name = "ticker"
    df = df.reset_index()[["ticker", "close", "mcap", "volume", "value", "shares"]]
    df.insert(0, "date", d)
    return df


def one_fund(d):
    from pykrx import stock
    df = _retry(lambda: stock.get_market_fundamental_by_ticker(d, "ALL"))
    if df is None or df.empty:
        return None
    df.index.name = "ticker"
    df = df.reset_index()
    df.insert(0, "date", d)
    return df


def one_short(d):
    from pykrx import stock
    parts = []
    for mk in ("KOSPI", "KOSDAQ"):
        v = _retry(lambda: stock.get_shorting_volume_by_ticker(d, mk))
        b = _retry(lambda: stock.get_shorting_balance_by_ticker(d, mk))
        frame = pd.DataFrame()
        if v is not None and not v.empty:
            v = v.rename(columns={"공매도": "sv", "매수": "buyvol", "비중": "sv_ratio"})
            frame = v[[c for c in ("sv", "sv_ratio") if c in v.columns]]
        if b is not None and not b.empty:
            b = b.rename(columns={"공매도잔고": "sb", "상장주식수": "shares_b", "공매도금액": "sb_val",
                                  "시가총액": "mcap_b", "비중": "sb_ratio"})
            frame = frame.join(b[[c for c in ("sb", "sb_val", "sb_ratio") if c in b.columns]], how="outer")
        if not frame.empty:
            frame["market"] = mk
            parts.append(frame)
    if not parts:
        return None
    out = pd.concat(parts)
    out.index.name = "ticker"
    out = out.reset_index()
    out.insert(0, "date", d)
    return out


def run_daily(out: Path, have, kind, fn, y0, y1):
    days = trading_days(y0, y1)
    for ym, ds in month_groups(days).items():
        rel = f"alpha/{kind}/{ym[:4]}/{ym[:4]}-{ym[4:]}.csv.gz"
        if done_already(have, rel, ym):
            continue
        t0 = time.time()
        rows, miss = [], []
        for d in ds:
            r = fn(d)
            if r is None:
                r = fn(d)                         # 한 번 더
            if r is None:
                miss.append(d)
            else:
                rows.append(r)
        if not rows:
            print(f"  {ym}: 전부 실패")
            continue
        f = out / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(rows, ignore_index=True).to_csv(f, index=False, compression="gzip")
        print(f"  {ym}: {len(rows)}일 {sum(len(r) for r in rows)}행 실패 {miss} ({time.time()-t0:.0f}s)",
              flush=True)


def run_fund(out: Path, have, y0, y1):
    days = trading_days(y0, y1)
    s = pd.Series(pd.to_datetime(days), index=days)
    wk = s.groupby(s.dt.to_period("W-FRI")).max()          # 주 마지막 거래일
    for y in range(y0, y1 + 1):
        rel = f"alpha/fund/{y}.csv.gz"
        if have is not None and y < dt.date.today().year and (have / rel).exists():
            continue
        ds = [d.strftime("%Y%m%d") for d in wk if d.year == y]
        rows = [r for r in (one_fund(d) for d in ds) if r is not None]
        if rows:
            f = out / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            pd.concat(rows, ignore_index=True).to_csv(f, index=False, compression="gzip")
            print(f"  fund {y}: {len(rows)}/{len(ds)}주", flush=True)


def run_idx(out: Path, have, y0, y1):
    from pykrx import stock
    days = trading_days(y0, y1)
    for y in range(y0, y1 + 1):
        rel = f"alpha/idx/{y}.csv.gz"
        if have is not None and y < dt.date.today().year and (have / rel).exists():
            continue
        ds = [d for d in days if d[:4] == str(y)]
        pick = []
        for ym, g in month_groups(ds).items():
            pick += g if ym[4:] in ("05", "06", "11", "12") else g[:1]
        rows = []
        for d in pick:
            for code in ("1028", "2203"):
                r = _retry(lambda: stock.get_index_portfolio_deposit_file(code, d))
                if r is not None and len(r):
                    rows.append(pd.DataFrame({"date": d, "index": code, "ticker": list(r)}))
        if rows:
            f = out / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            pd.concat(rows, ignore_index=True).to_csv(f, index=False, compression="gzip")
            print(f"  idx {y}: {len(pick)}일", flush=True)


def probe():
    from pykrx import stock
    tests = [
        ("flows ALL 외국인 2016-03-02", lambda: stock.get_market_net_purchases_of_equities_by_ticker("20160302", "20160302", "ALL", "외국인")),
        ("flows ALL 연기금 2024-05-02", lambda: stock.get_market_net_purchases_of_equities_by_ticker("20240502", "20240502", "ALL", "연기금")),
        ("flows KOSDAQ 개인 2015-01-05", lambda: stock.get_market_net_purchases_of_equities_by_ticker("20150105", "20150105", "KOSDAQ", "개인")),
        ("cap ALL 2016-03-02", lambda: stock.get_market_cap_by_ticker("20160302", "ALL")),
        ("fund ALL 2016-03-04", lambda: stock.get_market_fundamental_by_ticker("20160304", "ALL")),
        ("fund ALL 2016-04-29", lambda: stock.get_market_fundamental_by_ticker("20160429", "ALL")),
        ("short vol KOSPI 2016-03-02", lambda: stock.get_shorting_volume_by_ticker("20160302", "KOSPI")),
        ("short bal KOSDAQ 2017-03-02", lambda: stock.get_shorting_balance_by_ticker("20170302", "KOSDAQ")),
        ("short bal KOSPI 2024-05-02", lambda: stock.get_shorting_balance_by_ticker("20240502", "KOSPI")),
        ("idx pdf 1028 2018-06-01", lambda: stock.get_index_portfolio_deposit_file("1028", "20180601")),
    ]
    for name, fn in tests:
        t0 = time.time()
        try:
            r = fn()
            el = time.time() - t0
            if hasattr(r, "shape"):
                print(f"[probe] {name}: {el:.2f}s shape={r.shape} cols={list(r.columns)}")
                if not r.empty:
                    print(r.head(3).to_string())
                    print(r.tail(2).to_string())
                    # 상폐 종목 포함 여부: 한진해운 117930 (2017-03 상폐)
                    if "117930" in r.index:
                        print("    → 117930(한진해운) 포함")
            else:
                print(f"[probe] {name}: {el:.2f}s len={len(r)} {list(r)[:5]}")
        except Exception as e:  # noqa: BLE001
            print(f"[probe] {name}: EXC {repr(e)[:200]}")
        time.sleep(0.5)


def main():
    a = sys.argv[1:]
    have = None
    if "--have" in a:
        i = a.index("--have")
        have = Path(a[i + 1])
        a = a[:i] + a[i + 2:]
    out = Path(a[0])
    mode = a[1] if len(a) > 1 else "probe"
    y0 = int(a[2]) if len(a) > 2 else 2015
    y1 = int(a[3]) if len(a) > 3 else dt.date.today().year
    out.mkdir(parents=True, exist_ok=True)
    print(f"mode={mode} {y0}~{y1} out={out} have={have}", flush=True)
    if mode == "probe":
        probe()
    elif mode == "flows":
        run_daily(out, have, "flows", one_flows, y0, y1)
    elif mode == "cap":
        run_daily(out, have, "cap", one_cap, y0, y1)
    elif mode == "short":
        run_daily(out, have, "short", one_short, max(y0, 2016), y1)
    elif mode == "idx":
        run_idx(out, have, y0, y1)
    elif mode == "fund":
        run_fund(out, have, y0, y1)
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
