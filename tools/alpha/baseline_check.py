"""기준선 재현: 종가베팅(고가권→등락률 상위 3·5) · 추세추종(계획 ⑨) — 이전 연구 수치와 맞는지 확인.
python tools/alpha/baseline_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from common import (COST_KR, COST_KR_OLD, load_panel, overnight_pool, overnight_topk,  # noqa: E402
                    summarize_daily, fmt, trend_signals, trend_run, trade_stats)

P = load_panel()
print(f"패널 {P.T}일 × {P.N}종목 ({P.dates[0].date()}~{P.dates[-1].date()}), 상폐 {len(P.delisted & set(P.tickers))}")
mask, on = overnight_pool(P)
print(f"종가베팅 풀 신호 {mask.sum():,}건")
for k in (3, 5):
    s, _ = overnight_topk(P, mask, on, k)
    for cost in (COST_KR_OLD, COST_KR):
        print(fmt(summarize_daily(s, 1, cost, f"종가베팅 상위{k} 비용{cost*100:.2f}%")))
ent = trend_signals(P)
tr, REF = trend_run(P, ent)
print(f"REF={REF:.4f}")
print(trade_stats(tr["pnl"], tr["date"], "추세추종 유동성10억+시장필터"))
