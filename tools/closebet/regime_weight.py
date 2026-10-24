"""레짐을 '쉬기(0/1)' 대신 '비중 조절'로 — 종가베팅(대형주 등급) · 52주 신고가 추세추종
python tools/closebet/regime_weight.py
비중 방식 (지수 = 종가베팅은 코스닥, 신고가는 코스피·코스닥 각각 계산 후 더 낮은 쪽 = 보수적)
  이진   : 기준선(20일 / 신고가 60일) 위 100% · 아래 0%      ← 지금 방식
  절반   : 위 100% · 아래 50%
  계단10 : 20·40·60·90·120일선을 하나 깰 때마다 −10% (최저 50%) · 다시 올라서면 +10%
  계단20 : 같은 선, 하나당 −20% (최저 0%)
  연속   : 5·10·20·40·60·120일선 중 위에 있는 비율
  (신고가는 기준선이 60일이라 계단은 60·90·120·180·250일선)
A. 종가베팅: 밤 계좌 수익 = 비중 × Σ(수익 − 0.25%)/3, 2018~
B. 신고가: 신호마다 '계좌의 5% × 비중' 투입, 60거래일 뒤 청산(비용 0.5%) → 청산일에 손익 반영(복리 없이 누적)
"""
import numpy as np
import pandas as pd
import large_cap as L

P, G, T, N = L.P, L.G, L.T, L.N
ix = G.ix


def idx(code):
    return ix[ix.index_code == code].set_index("date")["close"].reindex(P.dates).ffill()


ks, kq = idx("1001"), idx("2001")


def weights(s, base, ladder, cont):
    above = lambda n: (s > s.rolling(n).mean()).to_numpy()
    w = {}
    w["이진"] = above(base).astype(float)
    w["절반"] = np.where(above(base), 1.0, 0.5)
    nb = sum((~above(n)).astype(int) for n in ladder)
    w["계단10"] = np.clip(1 - 0.1 * nb, 0.5, 1)
    w["계단20"] = np.clip(1 - 0.2 * nb, 0, 1)
    w["연속"] = sum(above(n).astype(float) for n in cont) / len(cont)
    w["항상 100%"] = np.ones(T)
    return w


def acct_stats(daily, start):
    d = pd.Series(daily, index=P.dates)[P.dates >= start]
    eq = (1 + d).cumprod(); yrs = (d.index[-1] - d.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; mdd = (eq / eq.cummax() - 1).min()
    sh = d.mean() / d.std() * np.sqrt(250) if d.std() > 0 else np.nan
    yy = d.groupby(d.index.year).apply(lambda x: (1 + x).prod() - 1)
    return cagr, mdd, sh, yy


START = pd.Timestamp("2018-01-01")
print("A. 대형주 종가베팅(등급) — 레짐 비중 방식 (코스닥 기준, 2018-01 ~ 2026-10)")
d = L.pick(L.SIG3 & L.LARGE & (L.GP >= 0.8), [L.GM])                  # 레짐 없이 후보 → 비중으로 조절
night = ((d["ret"] - L.COST) / 3).groupby(d["i"]).sum().reindex(range(T)).fillna(0).to_numpy()
W = weights(kq, 20, [20, 40, 60, 90, 120], [5, 10, 20, 40, 60, 120])
rows = []
for k, w in W.items():
    w1 = np.r_[w]                                                       # t일 종가에 아는 지수 상태로 그날 밤 비중
    daily = np.nan_to_num(w1) * night
    cagr, mdd, sh, yy = acct_stats(daily, START)
    expo = np.nanmean(np.where(night != 0, np.nan_to_num(w1), np.nan)[P.dates >= START])
    rows.append((k, cagr, mdd, sh, expo, yy))
    print(f"  {k:8} 연평균 {cagr*100:+6.1f}% · MDD {mdd*100:6.1f}% · 샤프 {sh:.2f} · 매매일 평균 비중 {expo*100:3.0f}% · 수익/MDD {cagr/abs(mdd):.2f} | "
          + " ".join(f"{y%100:02d}:{v*100:+.0f}" for y, v in yy.items()))

# ---------------- B. 52주 신고가 ----------------
c = P.c
with np.errstate(invalid="ignore", divide="ignore"):
    m60 = pd.DataFrame(c).rolling(60, min_periods=60).mean().to_numpy()
    m60up = m60 > np.vstack([np.full((10, N), np.nan), m60[:-10]])
    hi252 = pd.DataFrame(c).rolling(252, min_periods=252).max().to_numpy()
    nh = c >= hi252
    nh20 = pd.DataFrame(nh.astype(float)).shift(1).rolling(20, min_periods=1).max().to_numpy() > 0
    vr = P.v / P.v20
    base = (c > m60) & m60up & nh & ~nh20 & (vr >= 2) & (P.tv20 >= 3e9) & (P.run >= 260) & (P.day < 0.285)
start = np.searchsorted(P.dates, pd.Timestamp("2016-01-01"))
base[:start] = False
ii, jj = np.nonzero(base)
ex = np.minimum(ii + 60, T - 1)
r = c[ex, jj] / c[ii, jj] - 1 - 0.005
ok = np.isfinite(r) & (ii + 60 < T)
ii, jj, ex, r = ii[ok], jj[ok], ex[ok], r[ok]
Wks = weights(ks, 60, [60, 90, 120, 180, 250], [20, 40, 60, 120, 250])
Wkq = weights(kq, 60, [60, 90, 120, 180, 250], [20, 40, 60, 120, 250])
print("\nB. 52주 신고가 추세추종 — 모든 신호에 비중만 달리 (60일 보유, 2016~, 비용 0.5%) · 비중 = 코스피·코스닥 중 낮은 쪽")
print("   (수익이 소수 대박 종목에 몰려 있어 '동시 N종목' 계좌 시뮬은 어떤 신호를 먼저 잡느냐에 휘둘림 → 투입 비중당 수익·연도별 안정성으로 비교)")
yrs_e = P.dates.year.to_numpy()[ii]
for k in Wks:
    w = np.minimum(Wks[k], Wkq[k])[ii]
    per = np.sum(w * r) / max(w.sum(), 1e-9)
    yy = pd.Series(w * r).groupby(yrs_e).sum() / pd.Series(w).groupby(yrs_e).sum().replace(0, np.nan)
    tot = pd.Series(w * r).groupby(yrs_e).sum()
    print(f"  {k:8} 투입 비중당 +{per*100:.2f}% · 평균 비중 {w.mean()*100:3.0f}% · 신호당 기대 손익(비중×수익) {np.mean(w*r)*100:+.2f}% · 손실 연도 {int((tot<0).sum())}/{len(tot)} · 최악 연도 {tot.min()/len(r)*1e4:+.1f}bp/신호 | "
          + " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in yy.items()))
