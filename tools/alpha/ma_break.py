"""이평선 이탈 역이용 — 주목받는 종목이 지켜보던 이동평균선을 종가로 깨는 날(손절 물량) 종가 매수 → 반등에 매도
python tools/alpha/ma_break.py
무편향 일봉(상장폐지 포함, data-backtest/), 2015~2026. 비용 왕복 0.25%.
  이탈일 t: 종가 < MA_n(t) 이고, 직전 k일 동안 종가가 계속 MA_n 위 (그 선이 '지지선'으로 보이던 상태)
  주목 종목: 20일 평균 거래대금 상위 N위 안 (그날 전체 종목 중) + 직전 60일 상승률 ≥ +x%
  청산: 다음날 시가 / 다음날 종가 / 3·5일 뒤 종가 / 'MA 위로 회복하면 그날 종가, 아니면 5일 뒤 종가'
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
from common import load_panel, roll  # noqa: E402

COST = 0.0025
P = load_panel()
T, N = P.T, P.N
c, o, h, l, v = P.c, P.o, P.h, P.l, P.v
with np.errstate(invalid="ignore", divide="ignore"):
    MA = {n: roll(c, n, "mean", minp=n) for n in (5, 10, 20, 60)}
    TVR = pd.DataFrame(P.tv20).rank(axis=1, ascending=False).to_numpy()      # 20일 평균 거래대금 순위 (1 = 최대)
    R60 = c / np.vstack([np.full((60, N), np.nan), c[:-60]]) - 1
    VR = v / P.v20
    above = {n: (c > MA[n]) for n in MA}
yr = P.dates.year.to_numpy()


def shift(a, k):
    out = np.full_like(a, np.nan, dtype=float)
    if k > 0:
        out[:-k] = a[k:]
    return out


NO, NC = shift(o, 1), shift(c, 1)
C3, C5 = shift(c, 3), shift(c, 5)
# 일반 지수(코스닥) 레짐
ix = pd.read_csv(ROOT / "data-backtest/sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
kq = ix[ix.index_code == "2001"].set_index("date")["close"].reindex(P.dates).ffill()
REG = (kq > kq.rolling(20).mean()).to_numpy()


def recover_exit(n, i, j):
    """MA_n 위로 종가 회복하면 그날 종가, 5일 안에 회복 못하면 5일 뒤 종가"""
    for d in range(1, 6):
        t = i + d
        if t >= T or not np.isfinite(c[t, j]):
            return np.nan
        if c[t, j] > MA[n][t, j] or d == 5:
            return c[t, j]
    return np.nan


def events(n, k=5, topn=100, r60=0.3, extra=None):
    with np.errstate(invalid="ignore"):
        prev_above = np.ones((T, N), bool)
        for d in range(1, k + 1):
            prev_above &= np.vstack([np.zeros((d, N), bool), above[n][:-d]])
        m = (c < MA[n]) & prev_above & (TVR <= topn) & (R60 >= r60) & np.isfinite(NO) & (P.run >= 120)
        m &= (c / P.prev - 1) > -0.285                                  # 하한가 잠김 제외 (체결 가능)
    if extra is not None:
        m &= extra
    ii, jj = np.nonzero(m)
    return ii, jj


def stats(lab, ii, jj, n=None, show_years=False):
    if not len(ii):
        print(f"  {lab:52} 0건"); return
    e = c[ii, jj]
    r = {"다음날시가": NO[ii, jj] / e - 1, "다음날종가": NC[ii, jj] / e - 1, "3일": C3[ii, jj] / e - 1, "5일": C5[ii, jj] / e - 1}
    if n is not None:
        r["회복/5일"] = np.array([recover_exit(n, i, j) for i, j in zip(ii, jj)]) / e - 1
    s = []
    for kk, x in r.items():
        x = x[np.isfinite(x)] - COST
        s.append(f"{kk} {x.mean()*100:+.2f}%(승{(x>0).mean()*100:.0f})")
    print(f"  {lab:52} {len(ii):5d}건 · " + " · ".join(s))
    if show_years:
        x = (NO[ii, jj] / e - 1) - COST; y = yr[ii]
        print("      다음날 시가 연도별: " + " ".join(f"{yy%100:02d}:{np.nanmean(x[y==yy])*100:+.2f}" for yy in sorted(set(y))))


if __name__ == "__main__":
    print(f"무편향 일봉 {P.dates[0]:%Y-%m-%d} ~ {P.dates[-1]:%Y-%m-%d} · 비용 왕복 {COST*100:.2f}% 반영")
    allm = np.isfinite(NO) & np.isfinite(c) & (TVR <= 100) & (P.run >= 120)
    ii, jj = np.nonzero(allm); stats("[기준] 거래대금 상위100 아무 날", ii[::20], jj[::20])
    print("\n[1] 이평선별 — 주목 종목(거래대금 상위 100 · 60일 +30%↑), 직전 5일 MA 위 → 종가 이탈")
    for n in (5, 10, 20, 60):
        ii, jj = events(n); stats(f"{n}일선 이탈", ii, jj, n, show_years=(n == 20))
    print("\n[2] 주목도 비교 (20일선 이탈)")
    for topn, r60, lab in ((30, 0.3, "상위30 · +30%"), (100, 0.3, "상위100 · +30%"), (100, 0.0, "상위100 · 상승 조건 없음"),
                           (100, 0.6, "상위100 · +60%↑(급등주)"), (500, 0.3, "상위500 · +30%"), (3000, -9, "조건 없음(전 종목)")):
        ii, jj = events(20, topn=topn, r60=r60); stats(lab, ii, jj, 20)
    print("\n[3] 이탈 모양 (20일선, 주목 종목)")
    with np.errstate(invalid="ignore"):
        depth = c / MA[20] - 1; day = c / P.prev - 1
    for lab, ex in (("얕게 이탈(MA −2% 이내)", depth > -0.02), ("깊게 이탈(MA −4% 이하)", depth <= -0.04),
                    ("거래량 2배↑ 동반(손절 물량)", VR >= 2), ("거래량 평소 이하", VR < 1),
                    ("당일 −5% 이하 급락", day <= -0.05), ("당일 −2%~0 완만", (day > -0.02)),
                    ("코스닥 20일선 위 장세", REG[:, None] & np.ones((T, N), bool)), ("코스닥 20일선 아래 장세", ~REG[:, None] & np.ones((T, N), bool))):
        ii, jj = events(20, extra=ex); stats(lab, ii, jj, 20)
    print("\n[4] 지지 기간 (20일선 위에 머문 일수)")
    for k in (3, 10, 20):
        ii, jj = events(20, k=k); stats(f"직전 {k}일 MA 위", ii, jj, 20)
    print("\n[5] 비교: 장중 MA 깼다가 종가 회복(가짜 이탈) — 그날 종가 매수")
    with np.errstate(invalid="ignore"):
        fake = (l < MA[20]) & (c > MA[20])
    for n in (20,):
        prev_above = np.ones((T, N), bool)
        for d in range(1, 6):
            prev_above &= np.vstack([np.zeros((d, N), bool), above[n][:-d]])
        m = fake & prev_above & (TVR <= 100) & (R60 >= 0.3) & np.isfinite(NO) & (P.run >= 120)
        ii, jj = np.nonzero(m); stats("20일선 장중 이탈 후 종가 회복", ii, jj, 20)
