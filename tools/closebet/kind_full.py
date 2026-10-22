"""B2c. 전수 재료 분석 — data 브랜치 alpha/kind (8개 이벤트 공시, 전 종목 2015~) × 최종 규칙 선택 4,424건
매수 전 공시 = (t−1 15:30, t 15:20], 매수 후 = (t 15:20, t+1 09:00]
python tools/closebet/kind_full.py
"""
import numpy as np
import pandas as pd
from cb import CB, ROOT

V = pd.read_pickle(CB / "_final_picks.pkl")
R = pd.read_pickle(CB / "_R.pkl")
dates = sorted(R["date"].unique()); prv = dict(zip(dates[1:], dates[:-1])); nxt = dict(zip(dates[:-1], dates[1:]))
ev = []
for f in (ROOT / "data-alpha/alpha/kind").glob("*.csv"):
    d = pd.read_csv(f, dtype=str)
    d["key"] = f.stem
    ev.append(d)
ev = pd.concat(ev)
ev["time"] = pd.to_datetime(ev["time"])
ev["k5"] = ev["kind_code"].str.zfill(5)
V["k5"] = V["ticker"].str[:5]
V["pre0"] = V["date"].map(prv) + pd.Timedelta(hours=15, minutes=30)
V["buy"] = V["date"] + pd.Timedelta(hours=15, minutes=20)
V["sell"] = V["date"].map(nxt) + pd.Timedelta(hours=9)
M = V[["date", "ticker", "k5", "pre0", "buy", "sell", "on"]].merge(ev[["k5", "time", "key", "title"]], on="k5")
pre = M[(M["time"] > M["pre0"]) & (M["time"] <= M["buy"])]
post = M[(M["time"] > M["buy"]) & (M["time"] <= M["sell"])]
wk = M[(M["time"] > M["buy"] - pd.Timedelta(days=30)) & (M["time"] <= M["pre0"])]
COST = 0.0025
print(f"최종 선택 {len(V)}건, 비용후 평균 {(V['on'].mean()-COST)*100:+.2f}%")
for lab, X in (("매수 전(신선)", pre), ("최근 30일(전날 15:30 이전)", wk), ("매수 후~다음날 9시 (판단 불가)", post)):
    print(f"\n[{lab}] 공시 있는 종목-밤 {X[['date','ticker']].drop_duplicates().shape[0]}건")
    for k, g in X.drop_duplicates(["date", "ticker", "key"]).groupby("key"):
        r = g["on"] - COST
        print(f"   {k:16} n={len(r):4d} 비용후 {r.mean()*100:+6.2f}% 중앙 {r.median()*100:+5.2f}% 승 {(r>0).mean()*100:3.0f}%")
    has = V.set_index(["date", "ticker"]).index.isin(X.set_index(["date", "ticker"]).index)
    print(f"   (없음) n={(~has).sum()} 비용후 {(V.loc[~has,'on'].mean()-COST)*100:+.2f}%")
