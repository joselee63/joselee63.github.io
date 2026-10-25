"""장 마감 뒤 공시 — NXT 애프터(15:40~20:00)에 나온 공시는 다음날 KRX 시가에 얼마나 반영되고, 그 뒤엔 이어지나
python tools/closebet/afterhours_disc.py
데이터: data-alpha/alpha/kind (8개 이벤트 공시, 전 종목 2015~), 무편향 일봉.
시점: 공시 시각이 t일(한국 거래일) 15:30~20:00 → 'NXT 애프터 시간' / 20:00~다음 거래일 08:00 → 'NXT 닫힌 밤'
지표(비용 전): 갭 = t+1 시가 ÷ t 종가 − 1 · 당일 = t+1 종가 ÷ t+1 시가 − 1 · 5일 = t+5 종가 ÷ t+1 시가 − 1
※ NXT 애프터 체결가 기록이 없어 'NXT에서 샀다면 얼마를 먹었나'는 측정 불가 — 반응의 크기·지속성만 본다.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import grades_wf as G

ROOT = Path(__file__).resolve().parents[2]
P, T, N = G.P, G.T, G.N
dates = P.dates
k5 = {t[:5]: j for j, t in enumerate(P.tickers)}
ev = []
for f in (ROOT / "data-alpha/alpha/kind").glob("*.csv"):
    d = pd.read_csv(f, dtype=str); d["key"] = f.stem; ev.append(d)
ev = pd.concat(ev)
ev = ev[~ev["title"].str.contains("정정|철회|취소", na=False)].copy()
ev["time"] = pd.to_datetime(ev["time"])
ev["j"] = ev["kind_code"].str.zfill(5).map(k5)
ev = ev.dropna(subset=["j"]); ev["j"] = ev["j"].astype(int)
dv = dates.values
rows = []
for r in ev.itertuples():
    tm = r.time
    k = np.searchsorted(dv, np.datetime64(tm.normalize()), side="right") - 1      # 공시 날짜 이하 마지막 거래일
    if k < 0 or k + 5 >= T:
        continue
    hm = tm.hour * 60 + tm.minute
    same = dates[k] == tm.normalize()
    if same and 15 * 60 + 30 <= hm < 20 * 60:
        win, t0 = "애프터(15:30~20:00)", k
    elif (same and hm >= 20 * 60) or (not same):
        win, t0 = "닫힌 밤(20:00~08:00)", k
    elif same and hm < 8 * 60:
        win, t0 = "닫힌 밤(20:00~08:00)", k - 1
    else:
        continue                                                                      # 장중 공시는 제외
    j = r.j
    c0, o1, c1, c5 = P.c[t0, j], P.o[t0 + 1, j], P.c[t0 + 1, j], P.c[t0 + 5, j]
    if not (np.isfinite(c0) and np.isfinite(o1) and np.isfinite(c1) and np.isfinite(c5)) or t0 < 260:
        continue
    big = P.tv20[t0, j] >= 3e10
    rows.append((r.key, win, big, o1 / c0 - 1, c1 / o1 - 1, c5 / o1 - 1, dates[t0].year))
D = pd.DataFrame(rows, columns=["key", "win", "big", "gap", "day", "d5", "yr"])
D = D[D["yr"] >= 2016]
print(f"장 마감 뒤 공시 {len(D):,}건 (2016~, 정정·철회 제외, 장중 공시 제외)")
print(f"{'공시':22} {'시간':20} {'규모':8} {'건수':>6} {'갭 평균':>8} {'갭 중앙':>8} {'갭≥+3%':>7} {'다음날 시가→종가':>14} {'시가→5일':>9}")
for (k, w, b), g in D.groupby(["key", "win", "big"]):
    if len(g) < 30:
        continue
    print(f"{k:22} {w:20} {'대형' if b else '중소형':8} {len(g):6d} {g.gap.mean()*100:+7.2f}% {g.gap.median()*100:+7.2f}% {np.mean(g.gap >= 0.03)*100:6.0f}% "
          f"{g.day.mean()*100:+13.2f}% {g.d5.mean()*100:+8.2f}%")
