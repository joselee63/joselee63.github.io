"""A6. 매도 방식 — 일봉(시가·고가·저가·종가)으로 가능한 범위
선택: KOSDAQ>20일선 날, 상한가터치·+25%↑ 제외, 고가권→등락률 상위3 (S1)
매도 판단에 쓸 수 있는 정보: 다음날 시가 갭(9:00), 밤사이 미국(9:00 전에 앎)
python tools/closebet/exit_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line

R = pd.read_pickle(CB / "_R.pkl"); days = pd.read_pickle(CB / "days2.pkl")
S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False])
S = S.groupby("date").head(3).copy()
S["spx_night"] = S["date"].map(days["spx_night"])
g = S["on"]                          # 시가 갭
o2c = (1 + S["oc"]) / (1 + S["on"]) - 1  # 다음날 시가→종가
S["o2c"] = o2c
P = lambda col: S.groupby("date")[col].mean()


def show(lab, x):
    S["_x"] = x
    print(line(stats(P("_x"), label=lab)))


show("E0 다음날 시가 매도", S["on"])
show("E1 다음날 종가 매도", S["oc"])
show("E2 시가 50% + 종가 50%", (S["on"] + S["oc"]) / 2)
print("\n-- 갭 구간별 '시가 이후 보유'(시가→종가)의 평균: 갭을 보고 결정할 수 있나")
for b, v in S.groupby(pd.cut(S["on"], [-1, -0.05, -0.02, -0.005, 0.005, 0.02, 0.05, 0.1, 1]), observed=True):
    print(f"   갭 {str(b):18} n={len(v):5d}  시가→종가 평균 {v['o2c'].mean()*100:+5.2f}%  중앙 {v['o2c'].median()*100:+5.2f}%  (종가가 시가보다 나은 비율 {(v['o2c']>0).mean()*100:.0f}%)")
print("\n-- 조건부 매도")
for th in (-0.03, -0.02, -0.01, 0.0):
    show(f"E3 갭<{th*100:+.0f}% 이면 종가까지, 아니면 시가", np.where(S["on"] < th, S["oc"], S["on"]))
for th in (0.05, 0.1):
    show(f"E4 갭>+{th*100:.0f}% 이면 종가까지, 아니면 시가", np.where(S["on"] > th, S["oc"], S["on"]))
print("\n-- 시가 후 지정가 익절 (고가가 닿으면 체결, 아니면 종가). 경로 무관하게 성립")
for tp in (0.01, 0.02, 0.03, 0.05):
    tgt = (1 + S["on"]) * (1 + tp) - 1
    show(f"E5 시가에 안 팔고 시가+{tp*100:.0f}% 지정가, 미체결 종가", np.where(S["nh"] >= tgt, tgt, S["oc"]))
    # 시가 50% + 나머지 지정가
    show(f"E6 시가 50% + 50% 시가+{tp*100:.0f}% 지정가/종가", 0.5 * S["on"] + 0.5 * np.where(S["nh"] >= tgt, tgt, S["oc"]))
print("\n-- 밤사이 미국 급락(SPX −1%↓, 9시 전에 앎)인 날: 시가 vs 종가")
m = S["spx_night"] <= -0.01
print(f"   n={m.sum()} 시가 {S.loc[m,'on'].mean()*100:+.2f}% 종가 {S.loc[m,'oc'].mean()*100:+.2f}% / 그 외 시가 {S.loc[~m,'on'].mean()*100:+.2f}% 종가 {S.loc[~m,'oc'].mean()*100:+.2f}%")
print("\n-- 시가 갭 분포(S1 상위3 종목 단위)")
print((S["on"].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]) * 100).round(2).to_string())
