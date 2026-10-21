"""미국 PEAD (실적 서프라이즈 후 드리프트) — yfinance 실적 발표일·EPS 서프라이즈, S&P 500 (+ S&P 400) 현재 구성종목.
python tools/alpha/us_pead.py fetch   → data-alpha/us/{earnings.csv, px_*.pkl}
python tools/alpha/us_pead.py test

시점: 발표 시각이 16:00 ET 이후 → 다음 거래일 시가 매수, 장전(<09:30) → 당일 시가 매수, 장중 → 다음날 시가.
수익: 매수 시가 → H거래일 후 종가, SPY 대비 초과. 비용 왕복 0.05%.
한계: 현재 구성종목만 → 생존편향. 판정은 '서프라이즈 상위 − 하위'(같은 편향 공유) 중심.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, nw_t  # noqa: E402

OUT = ROOT / "data-alpha" / "us"
OUT.mkdir(parents=True, exist_ok=True)
COST = 0.0005


def universe():
    import io, requests
    ua = {"User-Agent": "Mozilla/5.0"}
    out = []
    for url in ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"):
        html = requests.get(url, headers=ua, timeout=30).text
        t = pd.read_html(io.StringIO(html))[0]
        col = [c for c in t.columns if "Symbol" in str(c) or "Ticker" in str(c)][0]
        out += t[col].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(out))


def fetch():
    import yfinance as yf
    tks = universe()
    print(f"유니버스 {len(tks)}")
    f = OUT / "earnings.csv"
    have = set(pd.read_csv(f)["ticker"]) if f.exists() else set()
    rows = []
    for n, tk in enumerate(tks):
        if tk in have:
            continue
        try:
            e = yf.Ticker(tk).get_earnings_dates(limit=100)
        except Exception as ex:  # noqa: BLE001
            print(tk, "EXC", repr(ex)[:80]); time.sleep(1); continue
        if e is None or e.empty:
            continue
        e = e.reset_index()
        e.columns = ["dt", "est", "rep", "surp"]
        e["ticker"] = tk
        rows.append(e)
        if n % 50 == 0:
            print(n, tk, len(e), flush=True)
            pd.concat(rows).to_csv(f, mode="a", header=not f.exists(), index=False); rows = []
        time.sleep(0.3)
    if rows:
        pd.concat(rows).to_csv(f, mode="a", header=not f.exists(), index=False)
    px = yf.download(tks + ["SPY"], start="2003-01-01", auto_adjust=True, progress=False, threads=True)
    px[["Open", "Close"]].to_pickle(OUT / "px.pkl")
    print("가격", px.shape)


def test():
    e = pd.read_csv(OUT / "earnings.csv")
    px = pd.read_pickle(OUT / "px.pkl")
    O, C = px["Open"], px["Close"]
    dates = C.index
    e["dt"] = pd.to_datetime(e["dt"], utc=True).dt.tz_convert("America/New_York")
    e = e.dropna(subset=["surp"]).drop_duplicates(["ticker", "dt"])
    e = e[e["dt"].dt.tz_localize(None) < pd.Timestamp.today() - pd.Timedelta(days=2)]
    hh = e["dt"].dt.hour + e["dt"].dt.minute / 60
    day = e["dt"].dt.tz_localize(None).dt.normalize()
    # 진입일: 장전(<9.5) → 당일, 그 외 → 다음 거래일
    pos = dates.searchsorted(day)                                  # day 이상 첫 거래일
    same = dates[np.minimum(pos, len(dates) - 1)] == day
    ent = np.where((hh < 9.5) & same, pos, np.where(same, pos + 1, pos))
    e["ei"] = ent
    e = e[(e["ei"] > 1) & (e["ei"] < len(dates) - 61)]
    e = e[e["ticker"].isin(C.columns)]
    spyO, spyC = O["SPY"].to_numpy(), C["SPY"].to_numpy()
    res = []
    Cn, On = C.to_numpy(), O.to_numpy()
    col = {t: i for i, t in enumerate(C.columns)}
    for H in (1, 5, 20, 60):
        j = e["ticker"].map(col).to_numpy(); i = e["ei"].to_numpy()
        po = On[i, j]; pc = Cn[i + H - 1, j]
        # 발표 반응(직전 종가 → 진입 시가)
        prv = Cn[i - 1, j]
        r = pc / po - 1 - (spyC[i + H - 1] / spyO[i] - 1)
        e[f"x{H}"] = r
        e["gap"] = po / prv - 1 - (spyO[i] / spyC[i - 1] - 1)
    e = e.replace([np.inf, -np.inf], np.nan).dropna(subset=["x60", "gap"])
    e["yr"] = e["dt"].dt.year
    e = e[e["yr"] >= 2005]
    print(f"이벤트 {len(e):,} · 종목 {e['ticker'].nunique()} · {e['yr'].min()}~{e['yr'].max()}")
    # 분위: 발표 분기(월) 안에서 서프라이즈 5분위
    e["ym"] = e["dt"].dt.tz_localize(None).dt.to_period("Q")
    e["sq"] = e.groupby("ym")["surp"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)) + 1
    e["gq"] = e.groupby("ym")["gap"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)) + 1
    for key, lab in (("sq", "EPS 서프라이즈"), ("gq", "발표 반응(갭)")):
        print(f"\n== {lab} 5분위 → 진입 시가 후 SPY 대비 초과수익 (비용 전) ==")
        for H in (1, 5, 20, 60):
            m = e.groupby(key)[f"x{H}"].mean() * 100
            print(f"  H={H:>2}: " + " ".join(f"Q{k}:{v:+.2f}" for k, v in m.items()))
    # 전략: 서프라이즈 상위 20% & 반응 플러스 → 20/60일 보유
    for H in (20, 60):
        for cond, lab in ((e["sq"] == 5, "서프 Q5"), ((e["sq"] == 5) & (e["gq"] >= 4), "서프 Q5 & 반응 Q4-5"),
                          ((e["sq"] == 1), "서프 Q1"), ((e["sq"] == 1) & (e["gq"] <= 2), "서프 Q1 & 반응 Q1-2")):
            x = e.loc[cond, f"x{H}"]
            q = e.loc[cond]
            mon = q.groupby(q["dt"].dt.tz_localize(None).dt.to_period("M"))[f"x{H}"].mean()
            yrm = q.groupby("yr")[f"x{H}"].mean()
            half = q["yr"] <= 2015
            print(f"  {lab:22} H={H} n={len(x):5d} 초과 {x.mean()*100:+.2f}% (비용후 {(x.mean()-COST)*100:+.2f}) "
                  f"월별 t={nw_t(mon.to_numpy(), max(1, H//20)):.2f} 승 {(x>0).mean()*100:.0f}% 하위1% {np.percentile(x,1)*100:+.1f}% "
                  f"05-15/16-26 {x[half].mean()*100:+.2f}/{x[~half].mean()*100:+.2f} 플러스연도 {(yrm>0).sum()}/{len(yrm)}")
    e.to_pickle(OUT / "events.pkl")




def robust():
    """스프레드(Q5−Q1) 월별 t, 연도별, 서프라이즈 문턱 민감도, 최근 5년"""
    e = pd.read_pickle(OUT / "events.pkl")
    e["m"] = e["dt"].dt.tz_localize(None).dt.to_period("M")
    for H in (5, 20, 60):
        a = e[e.sq == 5].groupby("m")[f"x{H}"].mean(); b = e[e.sq == 1].groupby("m")[f"x{H}"].mean()
        s = (a - b).dropna()
        yr = s.groupby(s.index.year).mean()
        print(f"Q5−Q1 H={H}: {s.mean()*100:+.2f}% t={nw_t(s.to_numpy(), max(1,H//20)):.2f} 플러스연도 {(yr>0).sum()}/{len(yr)} | "
              + " ".join(f"{y%100}:{v*100:+.1f}" for y, v in yr.items()))
    print("서프라이즈 문턱별 H=20 초과(절대, 생존편향 포함):")
    for lo, hi in ((-1e9, -10), (-10, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 20), (20, 1e9)):
        q = e[(e.surp > lo) & (e.surp <= hi)]
        print(f"  ({lo:>6},{hi:>6}] n={len(q):6d} H1 {q.x1.mean()*100:+.2f} H20 {q.x20.mean()*100:+.2f} H60 {q.x60.mean()*100:+.2f}")
    r = e[e.yr >= 2021]
    print("최근(2021~) 5분위 H20:", " ".join(f"Q{k}:{v*100:+.2f}" for k, v in r.groupby("sq")["x20"].mean().items()))
    # 첫날(H1) 제외 드리프트: 2일째 시가 진입과 근사 → x20 - x1 (근사)
    print("첫날 제외 근사(H20−H1) Q5:", f"{(e[e.sq==5].x20-e[e.sq==5].x1).mean()*100:+.2f}%", "Q1:", f"{(e[e.sq==1].x20-e[e.sq==1].x1).mean()*100:+.2f}%")


if __name__ == "__main__":
    {"fetch": fetch, "test": test, "robust": lambda: robust()}[sys.argv[1]]()
