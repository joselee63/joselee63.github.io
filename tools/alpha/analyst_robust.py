"""리포트 이벤트 강건성: 신규 커버리지·Not Rated·목표가 +20% 상향 — 유동성·중앙값·달력 포트폴리오.
python tools/alpha/analyst_robust.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, base_mask, fwd, load_panel  # noqa: E402
from kr_analyst import load_reports  # noqa: E402
from kind_robust import calendar_port  # noqa: E402

P = load_panel()
r = load_reports()
r = r[(r["date"] >= "2015-01-01") & r["ticker"].isin(P.ti)].copy()
r["i"] = P.dates.searchsorted(r["date"], side="right") - 1
r["j"] = r["ticker"].map(P.ti)
r = r[(r["i"] >= 1) & (r["i"] < P.T - 62)]
evs = {"신규 커버리지": r["init"], "Not Rated": r["op"].str.contains("Not Rated|N/R|^nr$|NR", case=False, na=False),
       "신규 커버리지 & NR 아님": r["init"] & ~r["op"].str.contains("Not Rated|N/R|^nr$|NR", case=False, na=False),
       "목표가 +20% 상향": r["tpchg"] >= 0.2}
for lab, msk in evs.items():
    d = r[msk.to_numpy()].drop_duplicates(["ticker", "i"])
    print(f"\n== {lab} ==")
    for liqv, ln in ((0, "유동성 무관"), (5e8, "5억+"), (1e9, "10억+"), (5e9, "50억+")):
        m = base_mask(P, liq=False) & (P.tv20 >= liqv) if liqv else base_mask(P, liq=False)
        e = d[m[d["i"], d["j"]]]
        out = []
        for H in (5, 20, 60):
            R = fwd(P, H); mu = np.nanmean(np.where(m, R, np.nan), 1)
            x = R[e["i"], e["j"]] - mu[e["i"]]; a = R[e["i"], e["j"]] - COST_KR
            out.append(f"H{H} 초과 {np.nanmean(x)*100:+.2f}(중앙 {np.nanmedian(x)*100:+.2f}) 절대 {np.nanmean(a)*100:+.2f}")
        print(f"  {ln:8} n={len(e):6d} " + " | ".join(out))
    m = base_mask(P, liq=False) & (P.tv20 >= 1e9)
    calendar_port(P, d, 20, m, label=f"{lab} 달력 10억+ H20")
