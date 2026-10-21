"""미국 애널리스트 의견·목표가 변경 이벤트 (yfinance upgrades_downgrades, 2012~) — S&P 500+400 현재 구성종목.
python tools/alpha/us_analyst.py fetch|test

시점: 이벤트 시각(GradeDate)이 장 시작 전이면 당일 시가, 그 외 다음 거래일 시가 매수 (보수적으로 항상 '다음 거래일 시가'도 병기).
수익: SPY 대비 초과, 비용 왕복 0.05%. 생존편향(현재 구성종목) 주의 → 상향 vs 하향 차이 중심 판정.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, nw_t  # noqa: E402
from us_pead import universe  # noqa: E402

OUT = ROOT / "data-alpha" / "us"
COST = 0.0005


def fetch():
    import yfinance as yf
    f = OUT / "updown.csv"
    have = set(pd.read_csv(f)["ticker"]) if f.exists() else set()
    rows = []
    for n, tk in enumerate(universe()):
        if tk in have:
            continue
        try:
            u = yf.Ticker(tk).upgrades_downgrades
        except Exception as ex:  # noqa: BLE001
            print(tk, "EXC", repr(ex)[:80]); time.sleep(1); continue
        if u is None or u.empty:
            continue
        u = u.reset_index(); u["ticker"] = tk
        rows.append(u)
        if n % 50 == 0:
            print(n, tk, len(u), flush=True)
            pd.concat(rows).to_csv(f, mode="a", header=not f.exists(), index=False); rows = []
        time.sleep(0.3)
    if rows:
        pd.concat(rows).to_csv(f, mode="a", header=not f.exists(), index=False)


def test():
    u = pd.read_csv(OUT / "updown.csv")
    px = pd.read_pickle(OUT / "px.pkl")
    O, C = px["Open"], px["Close"]
    dates = C.index
    u["dt"] = pd.to_datetime(u["GradeDate"])
    print(f"이벤트 {len(u):,} · {u['dt'].min().date()}~{u['dt'].max().date()} · 시각 분포(시):",
          u["dt"].dt.hour.value_counts().head(5).to_dict())
    day = u["dt"].dt.normalize()
    pos = dates.searchsorted(day)
    pos = np.minimum(pos, len(dates) - 1)
    same = dates[pos] == day
    u["ei"] = np.where(same, pos + 1, pos)          # 보수적: 발표 다음 거래일 시가
    u = u[(u["ei"] > 1) & (u["ei"] < len(dates) - 61) & u["ticker"].isin(C.columns)]
    col = {t: i for i, t in enumerate(C.columns)}
    j = u["ticker"].map(col).to_numpy(); i = u["ei"].to_numpy()
    On, Cn = O.to_numpy(), C.to_numpy()
    s_o, s_c = O["SPY"].to_numpy(), C["SPY"].to_numpy()
    for H in (1, 5, 20, 60):
        u[f"x{H}"] = Cn[i + H - 1, j] / On[i, j] - 1 - (s_c[i + H - 1] / s_o[i] - 1)
    u["pre"] = Cn[i - 1, j] / Cn[np.maximum(i - 6, 0), j] - 1
    u = u.replace([np.inf, -np.inf], np.nan).dropna(subset=["x60"])
    with np.errstate(invalid="ignore", divide="ignore"):
        u["tpchg"] = u["currentPriceTarget"] / u["priorPriceTarget"] - 1
    u["yr"] = u["dt"].dt.year
    # 같은 날 같은 종목 여러 건 → 종목·날짜 단위 이벤트로 묶기
    def show(m, lab):
        q = u[m].drop_duplicates(["ticker", "ei"])
        if len(q) < 100:
            print(f"  {lab:28} n={len(q)} (표본 부족)"); return
        out = []
        for H in (1, 5, 20, 60):
            x = q[f"x{H}"]
            mon = x.groupby(q["dt"].dt.to_period("M")).mean()
            out.append(f"H{H} {x.mean()*100:+.2f}(t={nw_t(mon.to_numpy(), max(1, H//20)):.1f})")
        x = q["x20"]; half = q["yr"] <= 2019
        yrm = x.groupby(q["yr"]).mean()
        print(f"  {lab:28} n={len(q):6d} " + " ".join(out) +
              f" | H20 비용후 {(x.mean()-COST)*100:+.2f} 승 {(x>0).mean()*100:.0f}% 하위1% {np.percentile(x,1)*100:+.1f}% "
              f"~19/20~ {x[half].mean()*100:+.2f}/{x[~half].mean()*100:+.2f} 플러스연도 {(yrm>0).sum()}/{len(yrm)}")
    a = u["Action"].str.lower()
    print("\n== 이벤트 유형별 SPY 대비 초과수익(%) — 발표 다음 거래일 시가 진입 ==")
    show(a == "up", "의견 상향(up)")
    show(a == "down", "의견 하향(down)")
    show(a == "init", "신규 커버리지(init)")
    show((a == "main") & (u["tpchg"] > 0), "의견 유지·목표가 상향")
    show((a == "main") & (u["tpchg"] < 0), "의견 유지·목표가 하향")
    show(u["tpchg"] >= 0.2, "목표가 +20% 이상 상향")
    show(u["tpchg"] <= -0.2, "목표가 -20% 이상 하향")
    show((a == "up") & (u["pre"] < 0), "상향 & 직전 5일 하락")
    show((a == "down") & (u["pre"] > 0), "하향 & 직전 5일 상승")
    # 목표가 상향 건수 모멘텀: 최근 30일 목표가 상향 − 하향 수 ≥ 3
    u.to_pickle(OUT / "updown_events.pkl")


if __name__ == "__main__":
    {"fetch": fetch, "test": test}[sys.argv[1]]()
