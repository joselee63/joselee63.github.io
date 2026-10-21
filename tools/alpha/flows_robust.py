"""수급 상위 후보(기타법인·사모·개인) 강건성 + 실전 포트폴리오.  python tools/alpha/flows_robust.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_mask, load_panel, robust_q, periodic_portfolio  # noqa: E402
from flows_research import load_flows, intensity  # noqa: E402
from kind_events import load as load_kind  # noqa: E402

P = load_panel()
F, mc, have = load_flows(P)
m = base_mask(P) & np.isfinite(mc)
corp20 = intensity(F["corp"], mc, 20)
for n in (5, 20, 60):
    X = intensity(F["corp"], mc, n)
    for H in (5, 20, 60):
        robust_q(P, X, H, m, f"기타법인 {n}일")
robust_q(P, corp20, 20, m & ~P.is_kosdaq[None, :], "기타법인20 코스피")
robust_q(P, corp20, 20, m & P.is_kosdaq[None, :], "기타법인20 코스닥")
big = pd.DataFrame(np.where(m, mc, np.nan)).rank(axis=1, ascending=False).to_numpy() <= 500
robust_q(P, corp20, 20, m & big, "기타법인20 시총 상위500")
m50 = base_mask(P, liq=False) & np.isfinite(mc) & (P.tv20 >= 5e9)
robust_q(P, corp20, 20, m50, "기타법인20 거래대금50억+")
robust_q(P, intensity(F["pef"], mc, 20), 20, m, "사모 20일")
robust_q(P, intensity(F["indiv"], mc, 20), 20, m, "개인 20일(상위=개인 순매수)")
# 자사주 공시가 있었던 종목·날짜를 뺀 뒤에도 남는가 (자사주 효과와 분리)
bb = np.zeros((P.T, P.N), np.float32)
for key in ("자기주식취득결정", "자기주식취득신탁계약체결결정"):
    d = load_kind(P, key)
    np.add.at(bb, (d["i"].to_numpy(), d["j"].to_numpy()), 1)
recent_bb = pd.DataFrame(bb).rolling(120, min_periods=1).sum().to_numpy() > 0
robust_q(P, np.where(recent_bb, np.nan, corp20), 20, m, "기타법인20 (최근120일 자사주공시 제외)")
print("\n== 실전 포트폴리오: 기타법인 20일 순매수/시총 상위 n, K일마다 교체 ==")
for n, K in ((20, 20), (30, 20), (20, 10), (20, 5), (50, 20)):
    periodic_portfolio(P, corp20, m, n, K, label=f"상위{n} · {K}일 교체")
periodic_portfolio(P, corp20, m & ~P.is_kosdaq[None, :], 20, 20, label="코스피만 상위20 · 20일")
periodic_portfolio(P, corp20, m & big, 20, 20, label="시총500 안 상위20 · 20일")
for off in (5, 10, 15):
    periodic_portfolio(P, corp20, m, 20, 20, label=f"상위20 · 20일 (시작 {off}일 이동)", offset=off)
