"""비가격 신호를 기준선 전략(종가베팅·추세추종)에 필터로 더했을 때 개선되는지.
python tools/alpha/filter_baselines.py

시점: 두 기준선 모두 t일 '종가'에 진입 → t일 수급·공매도는 아직 공개 전. 필터는 t−1일까지의 정보만.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (COST_KR, COST_KR_OLD, load_panel, overnight_pool, overnight_topk, summarize_daily,  # noqa: E402
                    fmt, trend_signals, trend_run, trade_stats)
from flows_research import load_flows, intensity  # noqa: E402


def lag1(a):
    return np.vstack([np.full((1, a.shape[1]), np.nan), a[:-1]])


if __name__ == "__main__":
    P = load_panel()
    F, mc, have = load_flows(P)
    fi = F["frg"] + F.get("frg2", 0)
    fpi = fi + F["inst"]
    filt = {}
    for n in (5, 20):
        x = lag1(intensity(fpi, mc, n))
        filt[f"외+기 {n}일 순매수>0 (t−1까지)"] = x > 0
        filt[f"외+기 {n}일 순매도 (t−1까지)"] = x < 0
        xf = lag1(intensity(fi, mc, n))
        filt[f"외국인 {n}일 순매수>0"] = xf > 0
        if "pension" in F:
            filt[f"연기금 {n}일 순매수>0"] = lag1(intensity(F["pension"], mc, n)) > 0
        xi = lag1(intensity(F["indiv"], mc, n))
        filt[f"개인 {n}일 순매도"] = xi < 0
        filt[f"개인 {n}일 순매수"] = xi > 0
    # 횡단면 상위 30% (외+기 20일 강도)
    x20 = lag1(intensity(fpi, mc, 20))
    rk = pd.DataFrame(np.where(P.liq, x20, np.nan)).rank(axis=1, pct=True).to_numpy()
    filt["외+기 20일 강도 상위30%"] = rk >= 0.7
    filt["외+기 20일 강도 하위30%"] = rk <= 0.3

    mask, on = overnight_pool(P)
    have_prev = np.r_[False, have[:-1]]
    mask &= (have & have_prev)[:, None]
    print("===== 종가베팅 (고가권→등락률 상위 3, 비용 0.25% / 0.20%) =====")
    s, _ = overnight_topk(P, mask, on, 3)
    print(fmt(summarize_daily(s, 1, COST_KR, "기준선(수급 기간)")), f"| 0.2%: {(s.mean()-COST_KR_OLD)*100:+.2f}%")
    for k, f in filt.items():
        m = mask & np.where(np.isnan(f.astype(float)), False, f)
        s, _ = overnight_topk(P, m, on, 3)
        print(fmt(summarize_daily(s, 1, COST_KR, "+" + k)), f"| 풀 {m.sum():,}")
    # 정렬키로 사용 (필터 대신 우선순위)
    s, _ = overnight_topk(P, mask, on, 3, extra_key=np.nan_to_num(x20 > 0).astype(float))
    print(fmt(summarize_daily(s, 1, COST_KR, "정렬: 외+기20일>0 우선 → 고가권")))

    print("\n===== 추세추종 (계획 ⑨, 매매당 계좌 수익, 비용 포함) =====")
    ent = trend_signals(P) & have[:, None]
    tr, REF = trend_run(P, ent)
    print(trade_stats(tr["pnl"], tr["date"], "기준선(수급 기간)"))
    for k, f in filt.items():
        e2 = ent & np.where(np.isnan(f.astype(float)), False, f)
        t2, _ = trend_run(P, e2, REF)
        print(trade_stats(t2["pnl"], t2["date"], "+" + k))
