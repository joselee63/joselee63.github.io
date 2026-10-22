"""B3b. '테마 대장주(1등주)' 규칙 — 같은 날 같은 무리에서 여러 종목이 급등할 때 1등(등락률 최대) vs 후발주
무리 정의 ① KRX 업종(직전 분기 스냅샷) ② 가격상관 테마 동료(10종목) — 후보 풀(KOSDAQ>20일선 날)에서
python tools/closebet/leader_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, load_panel, peer_sets

COST = 0.0025
R = pd.read_pickle(CB / "_R.pkl")
R["dm"] = R["on"] - R.groupby("date")["on"].transform("mean")
print("① KRX 업종: 같은 날 같은 업종 후보 ≥3 인 경우, 업종 내 등락률 순위별")
X = R[R["sec_pool"] >= 3]
for k, g in X.groupby(X["sec_rank"].clip(upper=4)):
    print(f"   업종내 {int(k)}등{'+' if k==4 else ''}: n={len(g):5d} 비용후 {(g['on'].mean()-COST)*100:+.2f}% 날대비 {g['dm'].mean()*100:+.2f}%p 고가권1.0비율 {(g['pos']>=0.999).mean()*100:.0f}%")
X2 = X[X["pos"] >= 0.999]
print("   (종가=고가 종목만)", " | ".join(f"{int(k)}등: n={len(g)} {(g['on'].mean()-COST)*100:+.2f}%" for k, g in X2.groupby(X2['sec_rank'].clip(upper=4))))
# ② 가격상관 테마: 후보의 동료 중 오늘 자기보다 더 많이 오른 종목 수 (0=무리 1등)
P = load_panel(); ps = peer_sets(P); keys = np.array(sorted(ps))
lead = []
for i, j, d in zip(R["i"], R["j"], R["day"]):
    p = keys[keys <= i]
    if not len(p):
        lead.append(np.nan); continue
    pp = ps[p[-1]][0][j]
    if pp[0] < 0:
        lead.append(np.nan); continue
    dd = P.day[i, pp]
    lead.append(np.nansum(dd > d) if np.nansum(dd >= 0.03) >= 2 else np.nan)   # 동료 2개 이상 +3% 일 때만
R["lead"] = lead
Y = R[R["lead"].notna()]
print("② 테마 동료 2개+ 동반 급등일 때, 동료 중 나보다 더 오른 종목 수 (0=대장)")
for k, g in Y.groupby(Y["lead"].clip(upper=3)):
    print(f"   {int(k)}{'+' if k==3 else ''}: n={len(g):5d} 비용후 {(g['on'].mean()-COST)*100:+.2f}% 날대비 {g['dm'].mean()*100:+.2f}%p 평균등락 {g['day'].mean()*100:.1f}%")
Y2 = Y[Y["pos"] >= 0.999]
print("   (종가=고가 종목만)", " | ".join(f"{int(k)}: n={len(g)} {(g['on'].mean()-COST)*100:+.2f}%" for k, g in Y2.groupby(Y2['lead'].clip(upper=3))))
