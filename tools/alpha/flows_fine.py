"""기타법인 신호 상위 구간 세분화 + 극단값 제외 포트폴리오.  python tools/alpha/flows_fine.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_mask, load_panel, fwd, nw_t, periodic_portfolio  # noqa: E402
from flows_research import load_flows, intensity  # noqa: E402

P = load_panel()
F, mc, have = load_flows(P)
m = base_mask(P) & np.isfinite(mc)
for nd in (20, 60):
    X = intensity(F["corp"], mc, nd)
    rk = pd.DataFrame(np.where(m, X, np.nan)).rank(axis=1, pct=True).to_numpy()
    R = fwd(P, 20); mu = np.nanmean(np.where(m, R, np.nan), 1)
    print(f"\n기타법인 {nd}일 순매수/시총 — 백분위 구간별 20일 초과수익 (매일, 동일가중)")
    for lo, hi in ((0, .02), (.02, .1), (.5, .8), (.8, .9), (.9, .95), (.95, .98), (.98, .995), (.995, 1.0)):
        sel = m & (rk > lo) & (rk <= hi) & np.isfinite(R)
        cnt = sel.sum(1)
        ex = np.where(cnt >= 3, (np.where(sel, R, 0).sum(1) / np.maximum(cnt, 1)) - mu, np.nan)
        s = pd.Series(ex, index=P.dates).dropna()
        med_int = np.nanmedian(np.where(sel, X, np.nan)) * 100
        print(f"  {lo*100:5.1f}~{hi*100:5.1f}%: 하루 {cnt.mean():5.1f}종목 강도 중앙 {med_int:+.3f}%시총 초과 {s.mean()*100:+.2f}% t={nw_t(s.to_numpy(),20):.1f}")
    # 극단 제외 포트폴리오: 90~98 백분위 안에서 무작위가 아닌 '강도 순' 상위 n → 즉 98% 미만으로 자른 뒤 상위
    Xc = np.where(rk <= 0.98, X, np.nan)
    for n, K in ((30, 20), (50, 20), (50, 10), (100, 20)):
        periodic_portfolio(P, Xc, m, n, K, label=f"{nd}일 · 98백분위 이하 상위{n} · {K}일 교체")
    Xb = np.where((rk >= 0.9) & (rk <= 0.98), rk, np.nan)
    periodic_portfolio(P, np.where(np.isfinite(Xb), np.random.default_rng(0).random(Xb.shape), np.nan), m, 50, 20,
                       label=f"{nd}일 · 90~98백분위 무작위50 · 20일")
