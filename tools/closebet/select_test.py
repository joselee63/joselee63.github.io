"""A5. 선별 규칙 조합 (KOSDAQ>20일선 날) — 상위 k 포트폴리오
python tools/closebet/select_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line

R = pd.read_pickle(CB / "_R.pkl")


def port(d, key, k=3, asc=None):
    keys = key if isinstance(key, list) else [key]
    asc = asc or [False] * len(keys)
    d = d.sort_values(["date"] + keys, ascending=[True] + asc)
    return d.groupby("date").head(k).groupby("date")["on"].mean()


def show(lab, s):
    print(line(stats(s, label=lab)))


clean = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)]
print("== 상위3, 정렬 기준 비교")
show("S0 기준선 정렬(고가권→등락률)", port(R, ["pos", "day"]))
show("S1 상한가터치·+25%↑ 제외", port(clean, ["pos", "day"]))
show("S2 S1 + 테마동료 +3% 수 → 고가권", port(clean, ["peer_n3", "pos"]))
show("S2b S1 + 동료 평균등락률 순", port(clean, "peer_ret"))
show("S3 S1 + 업종 +3% 비율 순", port(clean, "sec_up3"))
show("S3b S1 + 업종 후보수 → 고가권", port(clean, ["sec_pool", "pos"]))
for z in (0, 1, 2, 3, 4):
    show(f"S4 S1 + 동료 +3% ≥{z} 필터, 고가권 정렬", port(clean[clean["peer_n3"] >= z], ["pos", "day"]))
show("S5 S1 + 윗꼬리<1% 필터", port(clean[clean["upper_wick"] < 0.01], ["pos", "day"]))
show("S6 S1 + 동료≥2 + 윗꼬리<1%", port(clean[(clean["peer_n3"] >= 2) & (clean["upper_wick"] < 0.01)], ["pos", "day"]))
# 복합 점수 (그날 풀 안 백분위 합)
c = clean.copy()
g = c.groupby("date")
c["sc"] = g["pos"].rank(pct=True) + g["peer_ret"].rank(pct=True) + g["sec_up3"].rank(pct=True)
show("S7 복합(고가권+동료등락+업종강도)", port(c, "sc"))
c["sc2"] = g["pos"].rank(pct=True) + g["peer_ret"].rank(pct=True)
show("S7b 복합(고가권+동료등락)", port(c, "sc2"))
print("\n== k 민감도 (S2 / S7)")
for k in (1, 2, 3, 5, 7, 10):
    show(f"S2 k={k}", port(clean, ["peer_n3", "pos"], k))
    show(f"S7 k={k}", port(c, "sc", k))
print("\n== 연도별")
for lab, s in (("S0", port(R, ["pos", "day"])), ("S2", port(clean, ["peer_n3", "pos"])), ("S7", port(c, "sc"))):
    print(line(stats(s, label=lab), True))
print("\n== 동료 집합 크기 민감도는 build 재실행 필요 — 업종(KRX) 기반 버전으로 대체 확인(S3)")
c.to_pickle(CB / "_C.pkl")
