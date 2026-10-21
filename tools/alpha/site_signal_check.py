"""사이트 수급 페이지 '수급 바닥 반등' 신호 무편향 재검증 (전 종목·상폐 포함, 2015~).
정의(web/supply.html): 오실레이터 = (외국인+기타외국인+기관) 10일 순매수 ÷ 시총, 점수 = 120일 스토캐스틱(0~100),
신호 = 최근 10일 안에 점수 ≤20 + 점수가 5일 전보다 상승 + 종가가 20일선 상향 회복. t+1 시가 매수, H일 보유.
python tools/alpha/site_signal_check.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_mask, fwd, load_panel, nw_t, roll, COST_KR  # noqa: E402
from flows_research import load_flows, intensity  # noqa: E402

P = load_panel()
F, mc, have = load_flows(P)
osc = intensity(F["frg"] + F["frg2"] + F["inst"], mc, 10)
lo, hi = roll(osc, 120, "min", minp=60), roll(osc, 120, "max", minp=60)
with np.errstate(invalid="ignore", divide="ignore"):
    sc = np.where(hi > lo, (osc - lo) / (hi - lo) * 100, np.nan)
low10 = roll((sc <= 20).astype(float), 10, "max", minp=1) > 0
sc5 = np.vstack([np.full((5, P.N), np.nan), sc[:-5]])
m20 = roll(P.c, 20, "mean", minp=20)
cross = (P.c > m20) & (P.prev <= np.vstack([np.full((1, P.N), np.nan), m20[:-1]]))
sig = low10 & (sc > sc5) & cross
for liq in (True, False):
    m = base_mask(P, liq=liq) & np.isfinite(mc)
    for H in (5, 20):
        R = fwd(P, H); mu = np.nanmean(np.where(m, R, np.nan), 1)
        for lab, S in (("수급 바닥 반등", sig), ("20일선 회복만", cross), ("20일선 회복 & 점수 80↑(과열)", cross & (sc >= 80))):
            ii, jj = np.nonzero(S & m & np.isfinite(R))
            x = R[ii, jj] - mu[ii]
            s = pd.Series(x, index=P.dates[ii]).groupby(level=0).mean()
            yr = s.groupby(s.index.year).mean()
            print(f"{'유동성10억+' if liq else '전체':8} H={H:>2} {lab:24} n={len(x):7,} 초과 {x.mean()*100:+.2f}% (일별 t={nw_t(s.to_numpy(), H):.1f}) "
                  f"절대 비용후 {np.nanmean(R[ii,jj])*100-COST_KR*100:+.2f}% 승 {(R[ii,jj]>COST_KR).mean()*100:.0f}% 플러스연도 {(yr>0).sum()}/{len(yr)}")
