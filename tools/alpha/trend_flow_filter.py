"""추세추종(계획 ⑨)에 외국인+기관 수급 필터 — 기간·문턱 민감도, 연도별, 비용 민감도.
필터는 진입일(t) 종가 매수 전에 알 수 있는 t−1일까지 수급만 사용.  python tools/alpha/trend_flow_filter.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_panel, trend_signals, trend_run, trade_stats  # noqa: E402
from flows_research import load_flows, intensity  # noqa: E402
from filter_baselines import lag1  # noqa: E402

P = load_panel()
F, mc, have = load_flows(P)
fpi = F["frg"] + F["frg2"] + F["inst"]
ent = trend_signals(P) & have[:, None]
tr, REF = trend_run(P, ent)
print(trade_stats(tr["pnl"], tr["date"], "기준선"))
yr0 = tr.groupby(tr["date"].dt.year)["pnl"].mean()
res = {}
for nd in (5, 10, 20, 40, 60):
    x = lag1(intensity(fpi, mc, nd))
    rk = pd.DataFrame(np.where(P.liq, x, np.nan)).rank(axis=1, pct=True).to_numpy()
    for lab, f in ((">0", x > 0), ("상위50%", rk >= 0.5), ("상위30%", rk >= 0.7), ("상위10%", rk >= 0.9)):
        t2, _ = trend_run(P, ent & np.nan_to_num(f).astype(bool), REF)
        print(trade_stats(t2["pnl"], t2["date"], f"외+기 {nd}일 {lab}"))
        res[(nd, lab)] = t2
for key in ((20, "상위30%"), (20, ">0"), (40, "상위30%")):
    t2 = res[key]
    yr = t2.groupby(t2["date"].dt.year)["pnl"].mean()
    print(f"\n연도별 매매당 % — 기준선 vs 외+기 {key[0]}일 {key[1]}")
    print("  " + " ".join(f"{y%100}:{a*100:+.2f}/{b*100:+.2f}" for y, a, b in zip(yr0.index, yr0.values, yr.reindex(yr0.index).values)))
    print(f"  개선된 연도 {(yr.reindex(yr0.index) > yr0).sum()}/{len(yr0)}")
# 외+기 + 개인 결합
xi = lag1(intensity(F["indiv"], mc, 20)); x20 = lag1(intensity(fpi, mc, 20))
t2, _ = trend_run(P, ent & np.nan_to_num((x20 > 0) & (xi < 0)).astype(bool), REF)
print(trade_stats(t2["pnl"], t2["date"], "외+기20>0 & 개인20<0"))
pen = lag1(intensity(F["pension"], mc, 20))
rk = pd.DataFrame(np.where(P.liq, x20, np.nan)).rank(axis=1, pct=True).to_numpy()
t2, _ = trend_run(P, ent & np.nan_to_num((rk >= 0.7) & (pen > 0)).astype(bool), REF)
print(trade_stats(t2["pnl"], t2["date"], "외+기20 상위30% & 연기금20>0"))
# 매매 수가 줄어든 만큼 계좌 성과가 정말 나은지: 연간 합계(동시 보유 제한 없음 가정)
for lab, t in (("기준선", tr), ("외+기20 상위30%", res[(20, "상위30%")]), ("외+기20>0", res[(20, ">0")])):
    s = t.groupby(t["date"].dt.year)["pnl"].sum()
    print(f"  [{lab}] 연평균 매매 {len(t)/11.8:.0f}회 · 매매당 합계 연평균 {s.mean()*100:+.1f}%(2%룰 기준 R 합)")

# ---- 수급이 가격 모멘텀과 별개 정보인가: 같은 기간 수익률 상위 30% 필터와 비교, 그리고 2×2 교차
print("\n== 수급 vs 가격 모멘텀 (40일) ==")
c = P.c
r40 = np.full_like(c, np.nan); r40[41:] = c[40:-1] / c[:-41] - 1           # t−1 까지 40일 수익률
rkp = pd.DataFrame(np.where(P.liq, r40, np.nan)).rank(axis=1, pct=True).to_numpy()
x40 = lag1(intensity(fpi, mc, 40))
rkf = pd.DataFrame(np.where(P.liq, x40, np.nan)).rank(axis=1, pct=True).to_numpy()
for lab, f in (("가격 40일 상위30%", rkp >= 0.7), ("수급 40일 상위30%", rkf >= 0.7),
               ("가격 상위30% & 수급 상위30%", (rkp >= 0.7) & (rkf >= 0.7)),
               ("가격 상위30% & 수급 하위70%", (rkp >= 0.7) & (rkf < 0.7)),
               ("가격 하위70% & 수급 상위30%", (rkp < 0.7) & (rkf >= 0.7)),
               ("가격 하위70% & 수급 하위70%", (rkp < 0.7) & (rkf < 0.7))):
    t2, _ = trend_run(P, ent & np.nan_to_num(f).astype(bool), REF)
    print(trade_stats(t2["pnl"], t2["date"], lab))
# 수급을 시총 대비가 아니라 거래대금 대비로 (유동성 정규화 민감도)
amt40 = pd.DataFrame(P.amt).rolling(40, min_periods=30).sum().to_numpy()
xv = lag1(pd.DataFrame(fpi.astype(float)).rolling(40, min_periods=40).sum().to_numpy() / amt40)
rkv = pd.DataFrame(np.where(P.liq, xv, np.nan)).rank(axis=1, pct=True).to_numpy()
t2, _ = trend_run(P, ent & np.nan_to_num(rkv >= 0.7).astype(bool), REF)
print(trade_stats(t2["pnl"], t2["date"], "외+기 40일 ÷ 거래대금 상위30%"))
