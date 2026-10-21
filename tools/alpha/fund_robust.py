"""가치 신호 강건성: 연도별·앞뒤·이웃 분위·보유기간·흑자 필터.  python tools/alpha/fund_robust.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_mask, load_panel, robust_q  # noqa: E402
from fund_research import load_fund, weekly_to_daily  # noqa: E402

P = load_panel(); f = load_fund(P)
m = base_mask(P)
per, pbr, eps, div = (weekly_to_daily(P, f, k) for k in ("PER", "PBR", "EPS", "DIV"))
with np.errstate(invalid="ignore", divide="ignore"):
    bm = np.where(pbr > 0, 1 / pbr, np.nan)
    ep = np.where(per > 0, 1 / np.where(per > 0, per, 1), np.where(np.isfinite(per), -0.01, np.nan))
r = lambda x: pd.DataFrame(np.where(m, x, np.nan)).rank(axis=1, pct=True).to_numpy()
prof = eps > 0
for H in (20, 60, 120):
    robust_q(P, bm, H, m, "B/M")
robust_q(P, np.where(div > 0, div, np.where(np.isfinite(div), 0, np.nan)), 60, m, "배당수익률")
robust_q(P, r(ep) + r(bm), 60, m, "E/P+B/M")
robust_q(P, np.where(prof, bm, np.nan), 60, m, "흑자 中 B/M")
robust_q(P, bm, 60, m & P.is_kosdaq[None, :], "B/M 코스닥만")
robust_q(P, bm, 60, m & ~P.is_kosdaq[None, :], "B/M 코스피만")
# 적자 vs 흑자 (적자 회피 필터)
R = __import__("common").fwd(P, 60)
for lab, mm in (("흑자", m & prof), ("적자(EPS=0)", m & (eps == 0))):
    x = np.where(mm, R, np.nan); u = np.where(m & np.isfinite(eps), R, np.nan)
    d = pd.Series(np.nanmean(x, 1) - np.nanmean(u, 1), index=P.dates).dropna()
    yr = d.groupby(d.index.year).mean()
    print(f"  [{lab}] 60일 초과 {d.mean()*100:+.2f}% 연도별 " + " ".join(f"{y%100}:{v*100:+.1f}" for y, v in yr.items()))
