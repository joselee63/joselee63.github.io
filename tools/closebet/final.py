"""최종 종가베팅 규칙 종합 검증 (기준선 대비) — 재현: build.py → regime_test.py → stock_test.py → day_test_r1.py → theme_test.py → final.py
python tools/closebet/final.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, nw_t

COST = 0.0025
df = pd.read_pickle(CB / "cands.pkl")
R = pd.read_pickle(CB / "_R.pkl").merge(pd.read_pickle(CB / "_theme.pkl"), on=["i", "j"])
D1 = pd.read_pickle(CB / "_D1.pkl")


def topk(d, keys, k):
    d = d.sort_values(["date"] + keys, ascending=[True] + [False] * len(keys))
    return d.groupby("date").head(k)


base = topk(df[df["mkt_ok"]], ["pos", "day"], 3)
C = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].copy()
C["top"] = (C["pos"] >= 0.999).astype(int)
v1 = topk(C, ["pos", "day"], 3)                         # 시장필터 교체 + 상한가터치 제외
v2 = topk(C, ["top", "theme_run", "day"], 3)            # + 테마 연속일 정렬
v2k5 = topk(C, ["top", "theme_run", "day"], 5)

w = pd.Series(1.0, D1.index)
w += 0.5 * ((D1["pool_pct"] >= 0.8) | (D1["theme_pct"] >= 0.8))
w += 0.5 * (D1["gapdays"] == 3)
w -= 0.5 * ((D1["dow"] == 3) | D1["opt_exp"])
w = w.clip(0.5, 2.0)

series = {}
print("=== 단계별 개선 (상위3, 비용 0.25%, 다음날 시가 매도)")
for lab, t in (("기준선 (KOSPI>60, 고가권→등락률)", base), ("① 시장필터 KOSDAQ>20일선·상한가터치 제외", v1),
               ("② ①+정렬 종가=고가→테마연속→등락률", v2), ("② 상위5", v2k5)):
    s = t.groupby("date")["on"].mean(); series[lab] = s
    print(line(stats(s, label=lab), True))
s2 = series["② ①+정렬 종가=고가→테마연속→등락률"] - COST
ww = w.reindex(s2.index).fillna(1.0)
x = s2 * ww / ww.mean()
print(f"\n③ ②+비중단계(평균 1배로 정규화): 일수 {len(x)} 평균 {x.mean()*100:+.3f}% 샤프(연) {x.mean()/x.std()*np.sqrt(250):.2f} vs ② {s2.mean()/s2.std()*np.sqrt(250):.2f} | 최악의밤 {x.min()*100:.1f}%")
for v in sorted(ww.unique()):
    m = ww == v; h = s2.index[len(s2) // 2]
    print(f"   배수 {v}: {m.sum()}일 평균 {s2[m].mean()*100:+.2f}% (앞 {s2[m & (s2.index<=h)].mean()*100:+.2f} / 뒤 {s2[m & (s2.index>h)].mean()*100:+.2f})")

print("\n=== 같은 날끼리 차이 (기준선이 매매한 날 ∩ 새 규칙이 매매한 날)")
b = series["기준선 (KOSPI>60, 고가권→등락률)"]
for lab in ("① 시장필터 KOSDAQ>20일선·상한가터치 제외", "② ①+정렬 종가=고가→테마연속→등락률"):
    s = series[lab]; j = b.index.intersection(s.index); d = s[j] - b[j]
    print(f"   {lab}: 공통 {len(j)}일 차이 {d.mean()*100:+.3f}%p t={nw_t(d.to_numpy(),1):.2f}")
only_b = b.index.difference(series["① 시장필터 KOSDAQ>20일선·상한가터치 제외"].index)
only_n = series["① 시장필터 KOSDAQ>20일선·상한가터치 제외"].index.difference(b.index)
print(f"   기준선만 매매한 날(새 규칙이 쉰 날) {len(only_b)}일: 기준선 비용후 {(b[only_b].mean()-COST)*100:+.2f}%")
print(f"   새 규칙만 매매한 날 {len(only_n)}일: 새 규칙 비용후 {(series['① 시장필터 KOSDAQ>20일선·상한가터치 제외'][only_n].mean()-COST)*100:+.2f}%")

print("\n=== 최악의 밤 10 (② 상위3)")
worst = s2.nsmallest(10)
for d, r in worst.items():
    names = v2[v2["date"] == d]
    print(f"   {d.date()} {r*100:+.1f}%  KOSDAQ당일 {D1.loc[d,'kq_ret']*100:+.1f}% 밤SPX {D1.loc[d,'spx_night']*100:+.1f}% | " +
          ", ".join(f"{t}:{o*100:+.0f}%" for t, o in zip(names["ticker"], names["on"])))
print("\n=== 종목 단위 꼬리 (② 상위3)")
print(f"   종목-밤 {len(v2)}건, −10%↓ {(v2['on']<=-0.10).mean()*100:.2f}%, −20%↓ {(v2['on']<=-0.20).sum()}건, 최악 {v2['on'].min()*100:.1f}%, +10%↑ {(v2['on']>=0.10).mean()*100:.1f}%")
v2.to_pickle(CB / "_final_picks.pkl")
