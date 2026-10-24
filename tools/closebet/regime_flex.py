"""레짐(시장 필터) 방식 비교 — 코스닥/코스피 고정 vs 둘 다 이탈 시만 멈춤 vs 더 강한 지수 추종 vs 종목 소속 시장
python tools/closebet/regime_flex.py
A. 대형주 종가베팅(등급): large_cap.py 와 같은 정의 (2018~, 비용 0.25%, 상위 3, 다음날 시가)
B. 52주 신고가 추세추종 이벤트: 60일선 위·상승 + 종가 52주 신고가(직전 20일엔 신고가 없음) + 거래량 2배 + 20일 평균 거래대금 30억↑ → 20·60거래일 뒤 수익(비용 0.5%)
"""
import numpy as np
import pandas as pd
import large_cap as L

P, G, T, N = L.P, L.G, L.T, L.N
ix = G.ix


def idx(code):
    return ix[ix.index_code == code].set_index("date")["close"].reindex(P.dates).ffill()


ks, kq = idx("1001"), idx("2001")
REG = {}
for n in (20, 60):
    a_ks = (ks > ks.rolling(n).mean()).to_numpy(); a_kq = (kq > kq.rolling(n).mean()).to_numpy()
    REG[f"코스닥>{n}일선"] = a_kq
    REG[f"코스피>{n}일선"] = a_ks
    REG[f"둘 중 하나라도 >{n}일선"] = a_ks | a_kq
    REG[f"둘 다 >{n}일선"] = a_ks & a_kq
    for lb in (20, 60):
        strong_ks = ((ks / ks.shift(lb)) >= (kq / kq.shift(lb))).to_numpy()   # 최근 lb일 더 강한 지수
        REG[f"더 강한 지수({lb}일 수익률)>{n}일선"] = np.where(strong_ks, a_ks, a_kq)
REG["필터 없음"] = np.ones(T, bool)
# 종목 소속 시장 지수 (2차원)
own = {}
for n in (20, 60):
    a_ks = (ks > ks.rolling(n).mean()).to_numpy(); a_kq = (kq > kq.rolling(n).mean()).to_numpy()
    own[f"종목 소속 시장>{n}일선"] = np.where(P.is_kosdaq[None, :], a_kq[:, None], a_ks[:, None])
yr = P.dates.year.to_numpy()


def cb_row(lab, reg2d):
    d = L.pick(L.SIG3 & L.LARGE & reg2d & (L.GP >= 0.8), [L.GM])
    r = L.row(lab, d)
    s = d.groupby("date")["ret"].mean() - L.COST
    yy = s.groupby(s.index.year).mean()
    print(f"  {lab:34} 밤당 {r['밤당']:+.2f}% t={r['t']:4.1f} 승 {r['승률']:3.0f}% 연도 {r['연도']} MDD {r['MDD']:+5.1f}% 샤프 {r['샤프']:.2f} 연매매일 {r['연매매일']:3.0f} | 25: {yy.get(2025, np.nan)*100:+.2f} 26: {yy.get(2026, np.nan)*100:+.2f}")


print("A. 대형주 종가베팅(등급) — 레짐만 바꿔 비교 (2018-01 ~ 2026-10)")
for k, v in REG.items():
    cb_row(k, v[:, None] & np.ones((T, N), bool))
for k, v in own.items():
    cb_row(k, v)

# ---------------- B. 52주 신고가 추세추종 이벤트 ----------------
c = P.c
with np.errstate(invalid="ignore", divide="ignore"):
    m60 = pd.DataFrame(c).rolling(60, min_periods=60).mean().to_numpy()
    m60up = m60 > np.vstack([np.full((10, N), np.nan), m60[:-10]])
    hi252 = pd.DataFrame(c).rolling(252, min_periods=252).max().to_numpy()
    nh = c >= hi252
    nh20 = pd.DataFrame(nh.astype(float)).shift(1).rolling(20, min_periods=1).max().to_numpy() > 0
    vr = P.v / P.v20
    base = (c > m60) & m60up & nh & ~nh20 & (vr >= 2) & (P.tv20 >= 3e9) & (P.run >= 260) & (P.day < 0.285)
f20 = np.vstack([c[20:], np.full((20, N), np.nan)]) / c - 1
f60 = np.vstack([c[60:], np.full((60, N), np.nan)]) / c - 1
start = np.searchsorted(P.dates, pd.Timestamp("2016-01-01"))


def nh_row(lab, reg2d):
    m = base & reg2d
    m[:start] = False
    ii, jj = np.nonzero(m)
    a, b = f20[ii, jj] - 0.005, f60[ii, jj] - 0.005
    ok = np.isfinite(b)
    y = yr[ii]
    by = lambda Y: np.nanmean(b[y == Y]) * 100 if (y == Y).any() else np.nan
    yrs = sorted(set(y[ok])); pos = sum(np.nanmean(b[y == Y]) > 0 for Y in yrs)
    print(f"  {lab:34} {len(ii):5d}건 · 20일 {np.nanmean(a)*100:+.2f}%(승{np.nanmean(a>0)*100:.0f}) · 60일 {np.nanmean(b)*100:+.2f}%(승{np.nanmean(b[ok]>0)*100:.0f}) · 60일 플러스 연도 {pos}/{len(yrs)} | 25: {by(2025):+.1f} 26: {by(2026):+.1f}")


print("\nB. 52주 신고가 추세추종 이벤트 (2016~, 비용 0.5%) — 레짐만 바꿔 비교")
for k, v in REG.items():
    nh_row(k, v[:, None] & np.ones((T, N), bool))
for k, v in own.items():
    nh_row(k, v)
