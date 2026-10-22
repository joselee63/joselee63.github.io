"""종가베팅 매일 갱신용 무편향 일봉 저장소 (상장폐지 포함 전 종목) — .github/workflows/closebet.yml

저장소(store/, GitHub 릴리스 'closebet-data' 의 첨부 파일로 보관 — 매일 덮어써서 git 기록이 쌓이지 않음):
  ohlcv.npz      전 종목 수정주가 일봉 (2015~, 상폐 종목은 마지막 거래일까지 그대로 보관)
  universe.csv   KIND 현재 상장 ∪ 2015년 이후 상장폐지 (tools/backtest_data.py 와 같은 정의)
  index.csv      KOSPI(1001)·KOSDAQ(2001) 지수 일봉 (레짐 계산용)
  frozen.txt     연구 데이터에서 일봉이 비어 있던 오래된 종목 — 연구 결과와 같게 하려고 계속 비워 둠 (pack 이 만듦)
                 (2026-10 수집 때 015360~016100 구간 9종목(한국전력 등)이 빈 결과로 저장됨 → 넣으면 연구 수치가 바뀜)

python tools/closebet/daily_data.py pack STORE          # 로컬 data-backtest/ → STORE (처음 한 번)
python tools/closebet/daily_data.py update STORE        # KIND 목록 + 네이버 최근 봉 이어 붙이기
python tools/closebet/daily_data.py materialize STORE   # STORE → data-backtest/ (export_web.py 입력 형식)

일봉 출처는 연구 데이터와 같은 네이버 fchart 수정주가(pykrx get_market_ohlcv(adjusted=True) 가 부르는 바로 그 주소).
매일 종목마다 최근 30봉을 받아 저장된 값과 겹치는 날의 시·고·저·종가를 비교 →
  같으면 그 구간을 새 값으로 바꾸고(거래량 확정치 반영) 새 날을 붙임,
  다르면(액면분할·무상증자 등으로 과거 수정주가가 바뀜) 그 종목은 2015년부터 다시 받아 통째로 교체.
"""
import datetime as dt
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import backtest_data as BD  # noqa: E402

BT = Path(os.environ.get("BACKTEST_DIR", ROOT / "data-backtest"))
START = pd.Timestamp("2015-01-01")
FCHART = "https://fchart.stock.naver.com/sise.nhn"
RECENT = 30                    # 매일 받는 최근 봉 수 (겹치는 구간으로 수정주가 변경 감지)
KEEP_DELISTED_DAYS = 45        # 목록에서 빠진 지 얼마 안 된 종목은 정리매매 마지막 봉까지 계속 받아 봄
WORKERS, SLEEP = 4, 0.15
KST = dt.timezone(dt.timedelta(hours=9))
INDEX = {"1001": "KOSPI", "2001": "KOSDAQ"}

_S = threading.local()          # 스레드마다 세션 하나


def _session():
    if not hasattr(_S, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": BD.UA["User-Agent"], "Referer": "https://finance.naver.com/"})
        _S.s = s
    return _S.s


def now_kst():
    return dt.datetime.now(KST)


def full_count():
    return (pd.Timestamp(now_kst().date()) - START).days + 2      # pykrx 와 같은 방식 (2015-01-01 부터)


def fchart(symbol, count, price=int):
    """네이버 fchart 일봉 → DataFrame(date, open, high, low, close, volume). 장중(15:45 전)의 오늘 봉은 버림."""
    last = None
    for a in range(3):
        try:
            r = _session().get(FCHART, params={"symbol": symbol, "timeframe": "day", "count": count, "requestType": 0}, timeout=30)
            r.raise_for_status()
            m = re.search(rb'encoding="([^"]+)"', r.content[:200])          # 보통 EUC-KR (build_site.parse_fchart 와 같은 처리)
            text = r.content.decode(m.group(1).decode() if m else "euc-kr", errors="replace")
            if "<chartdata" not in text:
                raise ValueError("fchart 응답 형식이 다름")
            rows = [x.split("|")[:6] for x in re.findall(r'<item data="([^"]*)"', text)]
            break
        except Exception as e:                       # 네트워크·파싱 오류 → 잠깐 쉬고 다시
            last = e
            time.sleep(2 * (a + 1))
    else:
        raise RuntimeError(f"{symbol}: {last!r}")
    time.sleep(SLEEP)
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for k in ("open", "high", "low", "close"):
        df[k] = df[k].astype(float).astype(price) if price is int else df[k].astype(float)
    df["volume"] = df["volume"].astype(np.int64)
    n = now_kst()
    if n.time() < dt.time(15, 45):
        df = df[df["date"] < pd.Timestamp(n.date())]
    return df[df["date"] >= START].reset_index(drop=True)


# ------------------------------------------------------------------ 저장소 읽기·쓰기
def load_store(store):
    z = np.load(Path(store) / "ohlcv.npz", allow_pickle=False)
    tk = z["tickers"]
    df = pd.DataFrame({"ticker": tk[z["ti"]], "date": pd.to_datetime(z["d"].astype(str), format="%Y%m%d"),
                       "open": z["o"].astype(np.int64), "high": z["h"].astype(np.int64), "low": z["l"].astype(np.int64),
                       "close": z["c"].astype(np.int64), "volume": z["v"].astype(np.int64)})
    uni = pd.read_csv(Path(store) / "universe.csv", dtype={"ticker": str}, parse_dates=["listed_date", "delisted_date"])
    ix = pd.read_csv(Path(store) / "index.csv", dtype={"index_code": str}, parse_dates=["date"])
    return df, uni, ix


def load_frozen(store):
    f = Path(store) / "frozen.txt"
    return set(f.read_text().split()) if f.exists() else set()


def save_store(store, df, uni, ix):
    store = Path(store); store.mkdir(parents=True, exist_ok=True)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    tk, ti = np.unique(df["ticker"].to_numpy(str), return_inverse=True)
    np.savez_compressed(store / "ohlcv.npz", tickers=tk.astype("U6"), ti=ti.astype(np.int32),
                        d=df["date"].dt.strftime("%Y%m%d").astype(np.int32).to_numpy(),
                        o=df["open"].to_numpy(np.int32), h=df["high"].to_numpy(np.int32), l=df["low"].to_numpy(np.int32),
                        c=df["close"].to_numpy(np.int32), v=df["volume"].to_numpy(np.int64))
    uni.to_csv(store / "universe.csv", index=False, encoding="utf-8-sig")
    ix.sort_values(["index_code", "date"]).to_csv(store / "index.csv", index=False, encoding="utf-8-sig")


def pack(store):
    """로컬 data-backtest/ (tools/backtest_data.py 결과) → 저장소"""
    df = pd.read_pickle(BT / "ohlcv_all.pkl")
    df["ticker"] = df["ticker"].astype(str)
    assert df[["open", "high", "low", "close"]].max().max() < 2**31
    uni = pd.read_csv(BT / "universe.csv", dtype={"ticker": str}, parse_dates=["listed_date", "delisted_date"])
    ix = pd.read_csv(BT / "sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
    ix = ix[ix["index_code"].isin(INDEX)]
    save_store(store, df.drop(columns=["change"]), uni, ix)
    # 일봉이 없던 종목 중 상장 1년 반 넘은 것(=연구 기간 시세가 빠진 것)은 고정. 최근 상장은 300봉 전엔 패널에 안 들어가므로 계속 받음
    cut = df["date"].max() - pd.Timedelta(days=550)
    fz = uni[~uni["ticker"].isin(set(df["ticker"])) & (uni["listed_date"].isna() | (uni["listed_date"] < cut))]["ticker"]
    (Path(store) / "frozen.txt").write_text(" ".join(sorted(fz)))
    print(f"frozen {len(fz)}: {sorted(fz)}")
    print(f"pack: {len(df):,}행 · {df['ticker'].nunique():,}종목 · ~{df['date'].max():%Y-%m-%d} → {store}")


# ------------------------------------------------------------------ 매일 갱신
def _merge_one(old, new):
    """old·new: 한 종목 일봉(날짜순). 겹치는 날 가격이 같으면 이어 붙인 결과, 다르면 None(전체 재수집 필요)
    저장된 마지막 날은 장 마감 전 값일 수 있어(연구 데이터의 2026-10-21 이 그랬음) 비교에서 빼고 새 값으로 바꿈"""
    if old is None or not len(old):
        return None
    if not len(new):
        return old
    lo, hi = new["date"].iloc[0], old["date"].iloc[-1]
    a = old[(old["date"] >= lo) & (old["date"] < hi)].set_index("date")
    b = new[new["date"] < hi].set_index("date")
    if not a.index.equals(b.index):
        return None
    k = ["open", "high", "low", "close"]
    if not (a[k].to_numpy() == b[k].to_numpy()).all():
        return None
    return pd.concat([old[old["date"] < lo], new], ignore_index=True)


def update(store):
    df, uni_old, ix = load_store(store)
    n0, t0, d0 = len(df), df["ticker"].nunique(), df["date"].max()

    # 1) 유니버스: KIND 현재 상장 ∪ 상장폐지 (backtest_data.build_universe 와 같은 합치기)
    listed = BD.kind_listed(); time.sleep(0.5); deli = BD.kind_delisted()
    uni = BD.merge_universe(listed, deli)
    lost = uni_old[~uni_old["ticker"].isin(uni["ticker"])].assign(is_listed_now=False)   # 목록에서 사라진 옛 종목도 유지
    uni = pd.concat([uni, lost], ignore_index=True).sort_values("ticker").reset_index(drop=True)
    print(f"KIND 현재 상장 {len(listed):,} · 상장폐지 {len(deli):,} → 유니버스 {len(uni):,} (이전 {len(uni_old):,})")

    # 2) 받을 종목: 지금 상장 + 최근까지 시세가 있던 종목(정리매매 마지막 봉)
    last = df.groupby("ticker")["date"].max()
    recent = set(last[last >= pd.Timestamp(now_kst().date()) - pd.Timedelta(days=KEEP_DELISTED_DAYS)].index)
    frozen = load_frozen(store)
    todo = sorted((set(uni.loc[uni["is_listed_now"], "ticker"]) | recent) - frozen)
    old = {t: g.reset_index(drop=True) for t, g in df[df["ticker"].isin(todo)].groupby("ticker", sort=False)}
    print(f"고정(연구 데이터에 시세 없던 종목, 받지 않음) {len(frozen)}")
    print(f"받을 종목 {len(todo):,} (지금 상장 {int(uni['is_listed_now'].sum()):,} + 최근 시세 {len(recent - set(uni.loc[uni['is_listed_now'], 'ticker'])):,})")

    stat = {"same": 0, "append": 0, "refetch": 0, "new": 0, "empty": 0, "fail": 0}
    fails, refetched = [], []

    def work(t):
        try:
            o = old.get(t)
            if o is None:
                n = fchart(t, full_count())
                return t, (n if len(n) else None), ("new" if len(n) else "empty")
            n = fchart(t, RECENT)
            m = _merge_one(o, n)
            if m is not None:
                return t, m, ("append" if m["date"].iloc[-1] > o["date"].iloc[-1] else "same")
            n = fchart(t, full_count())
            refetched.append(t)
            return t, (n if len(n) else o), "refetch"
        except Exception as e:
            fails.append(f"{t} {e}")
            return t, None, "fail"

    res = {}
    t_start = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (t, d, s) in enumerate(ex.map(work, todo), 1):
            stat[s] += 1
            if d is not None:
                res[t] = d
            if k % 500 == 0:
                print(f"  {k:,}/{len(todo):,} {time.time() - t_start:.0f}초 {stat}", flush=True)
    print(f"네이버 일봉: {stat} ({time.time() - t_start:.0f}초)")
    if fails:
        print("  실패 예:", fails[:5])
    if stat["fail"] > 0.05 * len(todo):
        raise SystemExit(f"실패가 너무 많음 ({stat['fail']}/{len(todo)}) — 저장소를 바꾸지 않음")
    if refetched:
        print(f"  과거 값이 바뀌어(수정주가 등) 2015년부터 다시 받은 종목 {len(refetched)}:", sorted(refetched)[:30])

    keep = df[~df["ticker"].isin(res)]
    parts = [keep] + [d.assign(ticker=t)[keep.columns] for t, d in res.items()]
    df = pd.concat(parts, ignore_index=True)
    df = df[df["close"] > 0]

    # 3) 지수 (KOSPI·KOSDAQ): 새 날만 붙임 (기존 행은 KRX 원자료 그대로). 네이버 지수 거래량은 천 주 단위
    for code, sym in INDEX.items():
        n = fchart(sym, RECENT, price=float)
        cur = ix[ix["index_code"] == code]
        hi = cur["date"].max()
        ov = n[n["date"] <= hi].merge(cur, on="date", suffixes=("", "_k"))
        bad = ov[(ov["close"] - ov["close_k"]).abs() > 0.011]
        if len(bad):
            print(f"::warning::{sym} 지수 종가가 저장값과 다름 {len(bad)}일 (예: {bad.iloc[0]['date']:%Y-%m-%d})")
        add = n[n["date"] > hi].assign(index_code=code, volume=lambda x: x["volume"] * 1000)
        ix = pd.concat([ix, add[ix.columns]], ignore_index=True)
        print(f"지수 {sym}: +{len(add)}일 (~{ix[ix['index_code'] == code]['date'].max():%Y-%m-%d})")

    # 4) 점검 — 줄어들면 안 됨
    n1, t1, d1 = len(df), df["ticker"].nunique(), df["date"].max()
    print(f"일봉 {n0:,} → {n1:,}행 · 종목 {t0:,} → {t1:,} · 마지막 날 {d0:%Y-%m-%d} → {d1:%Y-%m-%d}")
    if n1 < n0 * 0.999 or t1 < t0 or d1 < d0:
        raise SystemExit("저장소가 줄어듦 — 저장하지 않음")
    kd = ix.groupby("index_code")["date"].max()
    if (kd < d1).any():
        raise SystemExit(f"지수 날짜({kd.to_dict()})가 일봉 마지막 날({d1:%Y-%m-%d})보다 이름 — 저장하지 않음")
    save_store(store, df, uni, ix)


# ------------------------------------------------------------------ export_web.py 입력 만들기
def materialize(store, out=BT):
    """저장소 → out/ohlcv_all.pkl · universe.csv · listing_periods.csv · sectors/index_ohlcv.csv
    (tools/backtest_data.py build_outputs 와 같은 형식·같은 listing_periods 정의)"""
    out = Path(out); (out / "sectors").mkdir(parents=True, exist_ok=True)
    df, uni, ix = load_store(store)
    df = df[df["close"] > 0].sort_values(["ticker", "date"]).reset_index(drop=True)
    prev = df.groupby("ticker")["close"].shift(1)
    df["change"] = (df["close"] - prev) / prev * 100
    df = df[["date", "ticker", "open", "high", "low", "close", "volume", "change"]]
    df["ticker"] = df["ticker"].astype("category")
    df.to_pickle(out / "ohlcv_all.pkl")
    uni.to_csv(out / "universe.csv", index=False, encoding="utf-8-sig")
    g = df.groupby("ticker", observed=True)["date"]
    periods = pd.DataFrame({"first_date": g.min(), "last_date": g.max(), "n_bars": g.size()}).reset_index()
    periods["ticker"] = periods["ticker"].astype(str)
    per = BD.listing_periods(uni, periods, df["date"].max())
    per.to_csv(out / "listing_periods.csv", index=False, encoding="utf-8-sig")
    ix.sort_values(["date", "index_code"]).to_csv(out / "sectors/index_ohlcv.csv", index=False, encoding="utf-8-sig")
    print(f"materialize: {len(df):,}행 · {df['ticker'].nunique():,}종목 · ~{df['date'].max():%Y-%m-%d} → {out}")


if __name__ == "__main__":
    cmd, store = sys.argv[1], Path(sys.argv[2])
    if cmd == "pack":
        pack(store)
    elif cmd == "update":
        update(store)
    elif cmd == "materialize":
        materialize(store, Path(sys.argv[3]) if len(sys.argv) > 3 else BT)
    else:
        raise SystemExit(__doc__)
