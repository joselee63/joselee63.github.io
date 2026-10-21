"""수급(투자자별 순매수) 횡단면 알파 스캔 — 전 종목(상폐 포함) KRX 횡단면 데이터.
python tools/alpha/flows_research.py [scan|site]

시점: t일 수급은 장 마감 후(저녁) 공개 → t+1 시가 매수 → H일 뒤 시가 매도.
강도 = N일 순매수 합 ÷ t일 시가총액. 분위는 매일 유니버스(유동성 10억+, 매수 가능) 안에서.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (COST_KR, base_mask, load_alpha, load_panel, quantile_returns, qline,  # noqa: E402
                    roll, topk_returns, nw_t)

INV = ["frg", "frg2", "inst", "pension", "trust", "pef", "fininv", "insur", "bank", "othfin", "corp", "indiv"]


def load_flows(P):
    fl = load_alpha("flows")
    fl = fl[fl["ticker"].isin(set(P.tickers))]
    fdates = pd.DatetimeIndex(sorted(fl["date"].unique()))
    have = np.isin(P.dates, fdates)
    out = {}
    for k in INV:
        col = f"{k}_nv"
        if col not in fl.columns:
            continue
        a = P.align(fl, col).astype(np.float32)
        a[have & np.isnan(a)] = 0.0             # 그날 데이터는 있는데 종목이 없으면 순매수 0
        out[k] = a
    cap = load_alpha("cap")
    cap = cap[cap["ticker"].isin(set(P.tickers))]
    mc = P.align(cap, "mcap")
    mc = pd.DataFrame(mc).ffill(limit=5).to_numpy()
    mc[mc <= 0] = np.nan
    return out, mc, have


def intensity(nv, mc, n):
    s = roll(nv.astype(float), n, "sum", minp=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return s / mc


def streak(pos):
    st = np.zeros(pos.shape, np.float32)
    for i in range(1, pos.shape[0]):
        st[i] = np.where(pos[i], st[i - 1] + 1, 0)
    return st


def scan(P, F, mc, have):
    m_liq = base_mask(P, liq=True) & have[:, None] & np.isfinite(mc)
    m_all = base_mask(P, liq=False) & have[:, None] & np.isfinite(mc)
    fi = F["frg"] + F.get("frg2", 0)
    fpi = fi + F["inst"]
    feats = {}
    for n in (1, 5, 20, 60):
        feats[f"외+기 {n}일/시총"] = intensity(fpi, mc, n)
    for n in (5, 20, 60):
        feats[f"외국인 {n}일/시총"] = intensity(fi, mc, n)
        feats[f"기관계 {n}일/시총"] = intensity(F["inst"], mc, n)
        for k, lab in (("pension", "연기금"), ("trust", "투신"), ("pef", "사모"), ("fininv", "금융투자"),
                       ("corp", "기타법인"), ("indiv", "개인")):
            if k in F:
                feats[f"{lab} {n}일/시총"] = intensity(F[k], mc, n)
    # 연속 순매수 일수 (외국인·기관 동시)
    both = (fi > 0) & (F["inst"] > 0)
    feats["외·기 동시 연속순매수일"] = streak(both)
    feats["외국인 연속순매수일"] = streak(fi > 0)
    feats["연기금 연속순매수일"] = streak(F["pension"] > 0) if "pension" in F else None
    # 수급 서프라이즈: 오늘 외+기 강도 ÷ 지난 60일 강도 표준편차
    i1 = intensity(fpi, mc, 1)
    sd = roll(i1, 60, "std", minp=40)
    with np.errstate(invalid="ignore", divide="ignore"):
        feats["외+기 1일 z(60일)"] = i1 / sd
    # 가격-수급 괴리: 20일 수익률 하위 30% 안에서만 외+기 20일 강도 (그 외 NaN)
    c = P.c
    r20 = np.full_like(c, np.nan); r20[20:] = c[20:] / c[:-20] - 1
    rk = pd.DataFrame(np.where(m_liq, r20, np.nan)).rank(axis=1, pct=True).to_numpy()
    f20 = intensity(fpi, mc, 20)
    feats["괴리: 20일 하락 하위30% 中 외+기20일"] = np.where(rk <= 0.3, f20, np.nan)
    feats["괴리: 20일 상승 상위30% 中 외+기20일"] = np.where(rk >= 0.7, f20, np.nan)
    # 스마트(연기금+투신+사모) 대 개인
    if all(k in F for k in ("pension", "trust", "pef")):
        feats["연기금+투신+사모 20일/시총"] = intensity(F["pension"] + F["trust"] + F["pef"], mc, 20)

    rows = []
    print(f"{'신호':30} {'H':>4} {'q1 … q10 (H일 수익률 %, 비용 전)':^60} | 요약")
    for name, X in feats.items():
        if X is None:
            continue
        for H in (5, 20, 60):
            q = quantile_returns(P, X, H, m_liq)
            print(qline(q, H, COST_KR, name), flush=True)
            d = q.dropna(subset=["q10", "uni"])
            ex = d["q10"] - d["uni"]
            med = d.index[len(d) // 2]
            rows.append(dict(sig=name, H=H, top=d["q10"].mean(), uni=d["uni"].mean(), ex=ex.mean(),
                             t=nw_t(ex.to_numpy(), H), bot_ex=(d["q1"] - d["uni"]).mean(),
                             t_bot=nw_t((d["q1"] - d["uni"]).to_numpy(), H),
                             ex1=ex[ex.index <= med].mean(), ex2=ex[ex.index > med].mean(),
                             yrpos=int((ex.groupby(ex.index.year).mean() > 0).sum()),
                             nyr=ex.index.year.nunique()))
        # 전 종목(유동성 필터 없음) H=20
        q = quantile_returns(P, X, 20, m_all)
        print(qline(q, 20, COST_KR, "  └ 유동성필터 없음"), flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(Path(__file__).resolve().parents[2] / "data-alpha" / "flows_scan.csv", index=False, encoding="utf-8-sig")
    return res


if __name__ == "__main__":
    P = load_panel()
    F, mc, have = load_flows(P)
    print(f"수급 데이터 {have.sum()}일 ({P.dates[have][0].date()}~{P.dates[have][-1].date()}), 주체 {list(F)}")
    scan(P, F, mc, have)
