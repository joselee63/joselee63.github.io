"""A7. 새 규칙(KOSDAQ>20일선 + 상한가터치·+25%↑ 제외) 파라미터 민감도 — 진입 조건 격자
python tools/closebet/sensitivity.py
"""
import numpy as np
import pandas as pd
from cb import CB, load_panel, stats, line

P = load_panel()
days = pd.read_pickle(CB / "days2.pkl")
kq_ok = days["kq_above20"].reindex(P.dates).fillna(False).to_numpy(bool)
nxt_o = np.vstack([P.o[1:], np.full((1, P.N), np.nan)])
on = nxt_o / P.c - 1
hi_t = P.h / P.prev - 1


def run(up=0.03, vm=2.0, pos=0.7, liq=1e9, k=3, cost=0.0025, regime=kq_ok, maxday=0.25, hitouch=True, sort="pos"):
    with np.errstate(invalid="ignore"):
        m = (P.day >= up) & (P.v > vm * P.v20) & (P.pos >= pos) & (P.tv20 >= liq) & np.isfinite(P.sd60)
        m &= (P.run >= 261) & (P.day < maxday) & regime[:, None] & np.isfinite(on)
        if hitouch:
            m &= hi_t < 0.285
    ii, jj = np.nonzero(m)
    d = pd.DataFrame({"i": ii, "pos": P.pos[ii, jj], "day": P.day[ii, jj], "on": on[ii, jj]})
    keys = ["pos", "day"] if sort == "pos" else ["day"]
    d = d.sort_values(["i"] + keys, ascending=[True] + [False] * len(keys))
    s = d.groupby("i").head(k).groupby("i")["on"].mean()
    s.index = P.dates[s.index]
    return stats(s, cost=cost)


def show(lab, r):
    r["label"] = lab
    print(line(r))


show("기본 (+3%·2배·0.7·10억·k3)", run())
show("기존 KOSPI>60 시장필터로", run(regime=P.mkt_ok))
for up in (0.02, 0.05, 0.07, 0.10):
    show(f"등락률 ≥ {up*100:.0f}%", run(up=up))
for vm in (1.0, 1.5, 3.0, 5.0):
    show(f"거래량 ≥ {vm}배", run(vm=vm))
for pos in (0.5, 0.8, 0.9, 0.95):
    show(f"고가권 ≥ {pos}", run(pos=pos))
for liq in (3e8, 3e9, 1e10):
    show(f"20일 거래대금 ≥ {liq/1e8:.0f}억", run(liq=liq))
for md in (0.2, 0.285):
    show(f"당일 상한 {md*100:.1f}% 미만", run(maxday=md))
show("상한가 터치 종목 포함", run(hitouch=False))
show("등락률 순 정렬(고가권 무시)", run(sort="day"))
for c in (0.002, 0.003, 0.004, 0.005):
    show(f"비용 {c*100:.1f}%", run(cost=c))
