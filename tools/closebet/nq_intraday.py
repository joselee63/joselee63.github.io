"""A1b. 장중 나스닥 선물 — 한국 t일 15:00(KST) 시점 NQ 가격 vs 직전 미국 정규장 종가(06:00 KST 무렵)
'매수 시점에 실제로 보이는' 선물 흐름이 다음날 시가 수익을 예고하나 (야후 60분봉, 최근 ~2년)
python tools/closebet/nq_intraday.py
"""
import numpy as np
import pandas as pd
import yfinance as yf
from cb import CB, stats, line

R = pd.read_pickle(CB / "_final_picks.pkl")
port = R.groupby("date")["on"].mean() - 0.0025
out = {}
for t in ("NQ=F", "ES=F"):
    d = yf.download(t, interval="60m", period="730d", progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("Asia/Seoul").tz_localize(None)
    c = d["Close"]
    rows = []
    for day in port.index:
        if day < c.index[0]:
            continue
        a = c[(c.index < day + pd.Timedelta(hours=7))]            # 07:00 KST 이전 마지막 = 미국 정규장 마감 무렵
        b = c[(c.index < day + pd.Timedelta(hours=15))]           # 15:00 KST 이전 마지막 봉 종가 (15:00 시점 값)
        if len(a) and len(b) and (day - a.index[-1]).days < 4:
            rows.append((day, b.iloc[-1] / a.iloc[-1] - 1))
    out[t] = pd.Series(dict(rows))
X = pd.DataFrame(out).join(port.rename("port"), how="inner").dropna()
print(f"표본 {len(X)}일 ({X.index.min().date()}~{X.index.max().date()})")
for t in ("NQ=F", "ES=F"):
    print(t, "상관", round(X[[t, "port"]].corr().iloc[0, 1], 3))
    for b, g in X.groupby(pd.cut(X[t], [-1, -0.005, -0.002, 0.002, 0.005, 1]), observed=True):
        print(f"   {str(b):18} n={len(g):3d} 포트 비용후 {g['port'].mean()*100:+.2f}%")
