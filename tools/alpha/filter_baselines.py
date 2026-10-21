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
from kind_events import load as load_kind  # noqa: E402
from fund_research import load_fund, weekly_to_daily  # noqa: E402

USE_FLOWS = "--noflows" not in sys.argv


def recent_event(P, key, n=60, title=None):
    """t일까지(공시 시각 기준 t일 장 마감 전 공개분) 최근 n거래일 안에 해당 공시가 있었는지"""
    d = load_kind(P, key)
    if title:
        d = d[d["title"].str.contains(title, na=False)]
    a = np.zeros((P.T, P.N), np.float32)
    # load() 의 i = 진입 전날 행. 종가 진입 전략에선 공시가 t일 15:20 이전이어야 t일 종가에 반영 가능 → 보수적으로 i+1 부터 유효
    np.add.at(a, (np.minimum(d["i"].to_numpy() + 1, P.T - 1), d["j"].to_numpy()), 1)
    return pd.DataFrame(a).rolling(n, min_periods=1).sum().to_numpy() > 0


def other_filters(P):
    f = {}
    bad = recent_event(P, "유상증자결정", 60, "제3자") | recent_event(P, "최대주주변경", 60) | recent_event(P, "전환사채권발행결정", 60)
    f["최근60일 제3자유증·CB·최대주주변경 없음"] = ~bad
    f["최근60일 제3자유증·CB·최대주주변경 있음"] = bad
    f["최근20일 자사주 신탁·취득 공시"] = recent_event(P, "자기주식취득신탁계약체결결정", 20) | recent_event(P, "자기주식취득결정", 20)
    fund = load_fund(P)
    eps = weekly_to_daily(P, fund, "EPS")
    f["흑자(KRX EPS>0)"] = eps > 0
    f["적자(EPS=0)"] = eps == 0
    pbr = weekly_to_daily(P, fund, "PBR")
    f["PBR<1"] = (pbr > 0) & (pbr < 1)
    return f


def lag1(a):
    return np.vstack([np.full((1, a.shape[1]), np.nan), a[:-1]])


def flow_filters(P, F, mc):
    f = {}
    fi = F["frg"] + F.get("frg2", 0)
    fpi = fi + F["inst"]
    for n in (5, 20):
        x = lag1(intensity(fpi, mc, n))
        f[f"외+기 {n}일 순매수>0 (t−1까지)"] = x > 0
        f[f"외+기 {n}일 순매도 (t−1까지)"] = x < 0
        f[f"외국인 {n}일 순매수>0"] = lag1(intensity(fi, mc, n)) > 0
        if "pension" in F:
            f[f"연기금 {n}일 순매수>0"] = lag1(intensity(F["pension"], mc, n)) > 0
        xi = lag1(intensity(F["indiv"], mc, n))
        f[f"개인 {n}일 순매도"] = xi < 0
        f[f"개인 {n}일 순매수"] = xi > 0
    x20 = lag1(intensity(fpi, mc, 20))
    rk = pd.DataFrame(np.where(P.liq, x20, np.nan)).rank(axis=1, pct=True).to_numpy()
    f["외+기 20일 강도 상위30%"] = rk >= 0.7
    f["외+기 20일 강도 하위30%"] = rk <= 0.3
    for nd in (20, 60):
        c = lag1(intensity(F["corp"], mc, nd))
        rc = pd.DataFrame(np.where(P.liq, c, np.nan)).rank(axis=1, pct=True).to_numpy()
        f[f"기타법인 {nd}일 하위10% 제외"] = ~(rc <= 0.1)
        f[f"기타법인 {nd}일 하위10%만"] = rc <= 0.1
        f[f"기타법인 {nd}일 상위20%"] = rc >= 0.8
    f["사모 20일 순매수>0"] = lag1(intensity(F["pef"], mc, 20)) > 0
    return f


def run(P, filt, have):
    mask, on = overnight_pool(P)
    have_prev = np.r_[False, have[:-1]]
    mask &= (have & have_prev)[:, None]
    print("===== 종가베팅 (고가권→등락률 상위 3, 비용 0.25%) =====")
    s, _ = overnight_topk(P, mask, on, 3)
    print(fmt(summarize_daily(s, 1, COST_KR, "기준선(같은 기간)")), f"| 비용0.2%: {(s.mean()-COST_KR_OLD)*100:+.2f}%")
    for k, f in filt.items():
        m = mask & np.where(np.isnan(f.astype(float)), False, f)
        s, _ = overnight_topk(P, m, on, 3)
        print(fmt(summarize_daily(s, 1, COST_KR, "+" + k)), f"| 풀 {m.sum():,}")
    print("\n===== 추세추종 (계획 ⑨, 매매당 계좌 수익, 비용 포함) =====")
    ent = trend_signals(P) & have[:, None]
    tr, REF = trend_run(P, ent)
    print(trade_stats(tr["pnl"], tr["date"], "기준선(같은 기간)"))
    for k, f in filt.items():
        e2 = ent & np.where(np.isnan(f.astype(float)), False, f)
        t2, _ = trend_run(P, e2, REF)
        print(trade_stats(t2["pnl"], t2["date"], "+" + k))


if __name__ == "__main__":
    P = load_panel()
    filt = other_filters(P)
    have = np.ones(P.T, bool)
    if USE_FLOWS:
        F, mc, have = load_flows(P)
        filt.update(flow_filters(P, F, mc))
    run(P, filt, have)
