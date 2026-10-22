"""B3. 테마 첫날 vs n일째 — 가격상관 '테마 동료' 10종목 중 +3%↑가 3개 이상인 날을 '테마 강세일'로 보고,
신호일까지 연속 며칠째인지(당일 포함)에 따른 다음날 시가 수익 (KOSDAQ>20일선 날, 후보 단위 + 상위3)
python tools/closebet/theme_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, load_panel, peer_sets

COST = 0.0025
P = load_panel()
R = pd.read_pickle(CB / "_R.pkl")
ps = peer_sets(P)
keys = np.array(sorted(ps))
up3 = P.day >= 0.03


def theme_run(i, j, back=10):
    p = keys[keys <= i]
    if not len(p):
        return np.nan, np.nan
    peers = ps[p[-1]][0][j]
    if peers[0] < 0:
        return np.nan, np.nan
    run = 0
    for d in range(0, back):
        if i - d < 0:
            break
        if np.nansum(up3[i - d, peers]) >= 3:
            run += 1
        else:
            break
    hot5 = sum(np.nansum(up3[i - d, peers]) >= 3 for d in range(1, 6) if i - d >= 0)
    return run, hot5


v = np.array([theme_run(i, j) for i, j in zip(R["i"], R["j"])])
R["theme_run"], R["theme_hot5"] = v[:, 0], v[:, 1]
R["dm"] = R["on"] - R.groupby("date")["on"].transform("mean")
med = R["date"].sort_values().iloc[len(R) // 2]
print("후보 단위 (비용후 / 같은날 평균 대비) — theme_run: 0=오늘 테마 강세 아님, 1=첫날, 2=2일째 ...")
for k, g in R.groupby(R["theme_run"].clip(upper=5)):
    a, b = g[g["date"] <= med], g[g["date"] > med]
    print(f"  run={int(k)}: n={len(g):6d} 비용후 {(g['on'].mean()-COST)*100:+.2f}% 날대비 {g['dm'].mean()*100:+.2f}%p 앞 {(a['on'].mean()-COST)*100:+.2f} 뒤 {(b['on'].mean()-COST)*100:+.2f}")
print("오늘 테마 강세 종목 중, 직전 5일 테마 강세 일수:")
T = R[R["theme_run"] >= 1]
for k, g in T.groupby("theme_hot5"):
    print(f"  직전5일 중 {int(k)}일: n={len(g):5d} 비용후 {(g['on'].mean()-COST)*100:+.2f}% 날대비 {g['dm'].mean()*100:+.2f}%p")
S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False]).groupby("date").head(3)
print("최종 선별 상위3 내부:")
for k, g in S.groupby(S["theme_run"].clip(upper=4)):
    print(f"  run={int(k)}: n={len(g):5d} 비용후 {(g['on'].mean()-COST)*100:+.2f}% 날대비 {g['dm'].mean()*100:+.2f}%p")
R[["i", "j", "theme_run", "theme_hot5"]].to_pickle(CB / "_theme.pkl")
