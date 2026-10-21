"""캘린더 효과 (지수 → ETF로 실행 가정): 월말월초(TOM)·연휴 전·요일·12월/1월·밤/낮 분해.
python tools/alpha/calendar_effects.py
ETF 왕복 비용 0.05% 가정 (ETF 매도는 거래세 없음).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BT, nw_t  # noqa: E402

ix = pd.read_csv(BT / "sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
COST = 0.0005
for code, nm in (("1001", "KOSPI"), ("2001", "KOSDAQ"), ("1028", "KOSPI200")):
    d = ix[ix.index_code == code].set_index("date").sort_index()
    if d.empty:
        continue
    r = d["close"].pct_change()
    ovn = d["open"] / d["close"].shift() - 1
    intra = d["close"] / d["open"] - 1
    dates = d.index
    ym = dates.to_period("M")
    pos_in_m = pd.Series(1, index=dates).groupby(ym).cumsum()
    n_in_m = pd.Series(1, index=dates).groupby(ym).transform("sum")
    from_end = n_in_m - pos_in_m          # 0 = 월 마지막 거래일
    tom = (from_end == 0) | (pos_in_m <= 3)
    # 연휴 전: 다음 거래일까지 평일 2일 이상 빔
    nxt = pd.Series(dates[1:].tolist() + [pd.NaT], index=dates)
    gap_bd = pd.Series([np.busday_count(a.date(), b.date()) if pd.notna(b) else 1 for a, b in zip(dates, nxt)], index=dates)
    preh = gap_bd >= 2                   # 그날 종가 이후 평일 휴장 (r 은 '연휴 전날' 당일 수익)
    preh_next = preh.shift(1, fill_value=False)   # 연휴 직후 첫날
    print(f"\n===== {nm} {dates[0].date()}~{dates[-1].date()} 일평균 {r.mean()*100:+.3f}% =====")

    def show(mask, lab):
        x = r[mask].dropna(); y = r[~mask].dropna()
        yr = x.groupby(x.index.year).mean()
        print(f"  {lab:26} 일수 {len(x):5d} 평균 {x.mean()*100:+.3f}% (그외 {y.mean()*100:+.3f}%) "
              f"t={x.mean()/(x.std()/np.sqrt(len(x))):4.2f} 승 {(x>0).mean()*100:3.0f}% 플러스연도 {(yr>0).sum()}/{len(yr)}")
    show(tom, "월말월초(말1+초3)")
    for k in range(0, 3):
        show(from_end == k, f"  월말 {k}일 전")
    for k in range(1, 6):
        show(pos_in_m == k, f"  월초 {k}일째")
    show(preh, "연휴 전날")
    show(preh_next, "연휴 다음날")
    for wd, w in enumerate("월화수목금"):
        show(dates.weekday == wd, f"{w}요일")
    show(dates.month == 12, "12월")
    show((dates.month == 1), "1월")
    show((dates.month == 12) & (dates.day >= 15), "12월 후반")
    print(f"  밤(전일종가→시가) 평균 {ovn.mean()*100:+.3f}%/일 · 낮(시가→종가) {intra.mean()*100:+.3f}%/일")
    # 전략: 월말월초 4일만 보유 vs 상시 보유
    eq_tom = (1 + r.where(tom, 0)).prod() - 1
    nmon = ym.nunique()
    tom_month = r.where(tom, 0).groupby(ym).sum()
    print(f"  전략 TOM 4일 보유: 월평균 {tom_month.mean()*100:+.3f}% (비용 {COST*100:.2f}% 후 {(tom_month.mean()-COST)*100:+.3f}%) "
          f"t={nw_t(tom_month.to_numpy(),1):.2f} 플러스달 {(tom_month>COST).mean()*100:.0f}% · 누적 {eq_tom*100:+.0f}% vs 상시 {((1+r).prod()-1)*100:+.0f}% · {nmon}개월")
    h = len(tom_month) // 2
    print(f"    앞/뒤 절반 월평균 {tom_month.iloc[:h].mean()*100:+.3f}/{tom_month.iloc[h:].mean()*100:+.3f}%")
