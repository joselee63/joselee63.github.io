"""A4. 종목 선별 특성 (KOSDAQ>20일선 날 한정) — 후보 단위 구간별 밤수익 + 필터로 썼을 때 상위3 포트
python tools/closebet/stock_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, daily

COST = 0.0025
df = pd.read_pickle(CB / "cands.pkl"); days = pd.read_pickle(CB / "days2.pkl")
# 시장 필터: KOSDAQ>20일선 (t일 종가) 와 보수적 버전 (t−1일 종가 기준)
kq20 = days["kq_above20"]
kq20_lag = days["kq_above20"].shift(1).fillna(False).astype(bool)
df["R1"] = df["date"].map(kq20).fillna(False).astype(bool)
df["R1lag"] = df["date"].map(kq20_lag).fillna(False).astype(bool)
print(line(stats(daily(df[df["R1"]], 3), label="R1 KOSDAQ>20 (당일)")))
print(line(stats(daily(df[df["R1lag"]], 3), label="R1 KOSDAQ>20 (전날 기준, 보수적)")))
print(line(stats(daily(df[df["R1"] & df["R1lag"]], 3), label="R1 당일&전날 모두")))
# 15:20 근사 민감도: 20일선 대비 ±0.5% 경계는 판단 보류 → 경계 근처 날 성적
near = (days["kq_ma20"].abs() < 0.005)
print("경계(±0.5%) 근처 날 수:", int(near.sum()), "| 그 중 R1 날 성적:", line(stats(daily(df[df["R1"] & df["date"].map(near)], 3), label="경계근처")))

R = df[df["R1"]].copy()
# 그날 풀 내부 정규화
R["day_rk"] = R.groupby("date")["day"].rank(pct=True)


def bucket(col, bins=None, q=5):
    x = R[col]
    b = pd.qcut(x, q, duplicates="drop") if bins is None else pd.cut(x, bins)
    g = R.groupby(b, observed=True)["on"]
    med = R["date"].sort_values().iloc[len(R) // 2]
    g1 = R[R["date"] <= med].groupby(b[R["date"] <= med], observed=True)["on"].mean()
    g2 = R[R["date"] > med].groupby(b[R["date"] > med], observed=True)["on"].mean()
    print(f"\n[{col}] 후보 단위 비용후 평균 (n, 앞/뒤)")
    for k, v in g:
        print(f"   {str(k):24} n={len(v):6d} {(v.mean()-COST)*100:+6.2f}%  중앙 {(v.median()-COST)*100:+5.2f}  앞 {(g1.get(k,np.nan)-COST)*100:+5.2f} 뒤 {(g2.get(k,np.nan)-COST)*100:+5.2f}")


print("\nR1 날 전체 후보 평균 비용후:", round((R['on'].mean() - COST) * 100, 3), "%, 후보 수", len(R))
for col, bins in (("rank", [-1, 0, 2, 4, 9, 19, 999]), ("pos", [0.69, 0.8, 0.9, 0.97, 0.999, 1.0]),
                  ("day", [0.029, 0.05, 0.08, 0.12, 0.18, 0.25, 0.285]),
                  ("vol_mult", [2, 3, 5, 10, 1e9]), ("amt_rank", [0, 10, 30, 100, 300, 1e9]),
                  ("prior_strong20", [-1, 0, 1, 2, 99]), ("streak", [0, 1, 2, 3, 5, 99]),
                  ("r5_prior", None), ("r20", None), ("r60", None), ("to_hi52", None), ("gap_today", [-1, -0.01, 0.01, 0.03, 0.07, 1]),
                  ("oc_today", None), ("upper_wick", [-0.001, 0.001, 0.01, 0.03, 1]), ("hi_today", [0, 0.1, 0.2, 0.285, 1]),
                  ("sd60", None), ("amt", None), ("peer_n3", [-1, 0, 1, 2, 4, 10]), ("peer_ret", None), ("peer_corr", None),
                  ("sec_pool", [0, 1, 2, 3, 5, 99]), ("sec_rank", [0, 1, 2, 3, 99]), ("sec_ret", None), ("sec_up3", None),
                  ("kosdaq", [-1, 0.5, 2])):
    if col in ("kosdaq",):
        R[col] = R[col].astype(float)
    if col == "hi52":
        continue
    bucket(col, bins)
bucket("hi52", [-1, 0.5, 2]) if R.__setitem__("hi52", R["hi52"].astype(float)) is None else None
R.to_pickle(CB / "_R.pkl")
