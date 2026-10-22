"""A1. 해외·매크로: 매수 시점에 아는 값(prev) vs 밤사이 값(night)이 기준선 포트폴리오의 다음날 시가 수익을 얼마나 설명하나
python tools/closebet/macro_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, diff_t, daily

df = pd.read_pickle(CB / "cands.pkl"); days = pd.read_pickle(CB / "days.pkl")
base = df[df["mkt_ok"]]
s = daily(base, 3)                       # 비용 전 밤 수익
D = days.loc[s.index].copy(); D["port"] = s
print(line(stats(s, label="기준선 상위3"), True))

print("\n--- 상관 (포트 밤수익 vs 변수), 전체 / 앞 / 뒤 절반 ---")
med = D.index[len(D) // 2]
cols = [c for c in D.columns if c.endswith("_prev") or c.endswith("_night") or c in ("vix_lvl",)]
for c in cols:
    x = D[c]; ok = x.notna()
    r = np.corrcoef(x[ok], D.loc[ok, "port"])[0, 1]
    r1 = D[ok & (D.index <= med)][[c, "port"]].corr().iloc[0, 1]
    r2 = D[ok & (D.index > med)][[c, "port"]].corr().iloc[0, 1]
    print(f"{c:12} r={r:+.3f}  앞 {r1:+.3f} 뒤 {r2:+.3f}")

print("\n--- 밤사이 미국(SPX) 수익 구간별 포트 밤수익 (매도 판단용, 사후 정보) ---")
b = pd.cut(D["spx_night"], [-1, -0.02, -0.01, -0.003, 0.003, 0.01, 0.02, 1])
print(D.groupby(b, observed=True)["port"].agg(["count", "mean", "median"]).map(lambda v: round(v * 100, 2) if abs(v) < 5 else v))

print("\n--- 매수 판단용: 직전 미국 세션(t−1, 이미 알고 있음) 구간별 ---")
for c, bins in (("spx_prev", [-1, -0.015, -0.005, 0.005, 0.015, 1]), ("ndx_prev", [-1, -0.02, -0.007, 0.007, 0.02, 1]),
                ("sox_prev", [-1, -0.03, -0.01, 0.01, 0.03, 1]), ("vix_lvl", [0, 13, 16, 20, 25, 35, 99]),
                ("vix_prev", [-1, -0.08, -0.03, 0.03, 0.08, 0.15, 9]), ("krw_prev", [-1, -0.005, -0.002, 0.002, 0.005, 1]),
                ("nk_prev", [-1, -0.015, -0.005, 0.005, 0.015, 1])):
    g = D.groupby(pd.cut(D[c], bins), observed=True)["port"]
    print(c, " | ".join(f"{k}: n={len(v)} {(v.mean()-0.0025)*100:+.2f}%" for k, v in g))

print("\n--- 회귀: port ~ night 변수 (설명력) ---")
X = D[["spx_night", "ndx_night", "sox_night", "ewy_night", "vix_night"]].fillna(0)
for cs in (["spx_night"], ["ndx_night"], ["sox_night"], ["ewy_night"], ["spx_night", "sox_night", "ewy_night"]):
    A = np.c_[np.ones(len(X)), X[cs]]
    beta, *_ = np.linalg.lstsq(A, D["port"], rcond=None)
    res = D["port"] - A @ beta
    r2 = 1 - res.var() / D["port"].var()
    print(cs, "beta", np.round(beta[1:], 2), f"R2={r2:.3f}", f"잔차 평균(α) {beta[0]*100:+.3f}%")
A = np.c_[np.ones(len(X)), X[["spx_prev"]].fillna(0) if False else D[["spx_prev", "ndx_prev", "sox_prev"]].fillna(0)]
beta, *_ = np.linalg.lstsq(A, D["port"], rcond=None)
res = D["port"] - A @ beta
print("prev 변수 R2", round(1 - res.var() / D["port"].var(), 4), np.round(beta, 4))
D.to_pickle(CB / "_D.pkl")
