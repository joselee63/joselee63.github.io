"""A6b. 분봉으로 본 매도 타이밍 (야후 60분봉 최근 ~2년 / 5분봉 최근 60일, 09:00~15:00만 제공)
최종 선별 규칙의 상위5 종목 → 다음날 시가 / 9:05·9:10·9:15·9:30 / 10:00 / 11:00 매도 비교
python tools/closebet/intraday_exit.py fetch   # 분봉 받기 (data-closebet/intraday/)
python tools/closebet/intraday_exit.py         # 분석
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from cb import CB

OUT = CB / "intraday"
R = pd.read_pickle(CB / "_R.pkl")
S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False])
S = S.groupby("date").head(5).copy()


def sym(t, kq):
    return f"{t}.{'KQ' if kq else 'KS'}"


def fetch():
    import yfinance as yf
    OUT.mkdir(exist_ok=True)
    rec = S[S["date"] >= pd.Timestamp.today() - pd.Timedelta(days=725)]
    for iv, per, since in (("60m", "730d", 725), ("5m", "60d", 58)):
        r = rec[rec["date"] >= pd.Timestamp.today() - pd.Timedelta(days=since)]
        tick = sorted(set(zip(r["ticker"], r["kosdaq"])))
        print(iv, len(tick), "종목")
        for t, kq in tick:
            f = OUT / f"{t}_{iv}.csv"
            if f.exists():
                continue
            try:
                d = yf.download(sym(t, kq), interval=iv, period=per, progress=False)
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(0)
                d.to_csv(f)
            except Exception as e:
                print(t, e)
            time.sleep(0.3)


def load(t, iv):
    f = OUT / f"{t}_{iv}.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f, index_col=0)
    if not len(d):
        return None
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("Asia/Seoul").tz_localize(None)
    return d


def analyse():
    nd = {}
    dates = sorted(R["date"].unique())
    nxt = dict(zip(dates[:-1], dates[1:]))
    for iv, marks in (("60m", ["09:00", "10:00", "11:00", "13:00", "14:00"]), ("5m", ["09:05", "09:10", "09:15", "09:20", "09:30", "10:00"])):
        rows = []
        for _, x in S.iterrows():
            d = load(x["ticker"], iv)
            if d is None or x["date"] not in nxt:
                continue
            day = d[d.index.normalize() == nxt[x["date"]]]
            if len(day) < 3:
                continue
            c0 = (1 + x["on"])  # 시가 / 전일 종가
            o_bar = day["Open"].iloc[0]
            row = {"date": x["date"], "on": x["on"]}
            for m in marks:
                # m 시각 '직전 봉의 종가' = 그 시각 가격
                hh, mm = map(int, m.split(":"))
                tm = day.index[0].normalize() + pd.Timedelta(hours=hh, minutes=mm)
                b = day[day.index < tm]
                if not len(b):
                    continue
                row[m] = c0 * b["Close"].iloc[-1] / o_bar - 1
            # 9:00~9:30 균등 분할(5분봉) / 9:00~10:00 평균가
            if iv == "5m":
                f30 = day[day.index < day.index[0].normalize() + pd.Timedelta(hours=9, minutes=30)]
                row["split_0930"] = c0 * ((f30["Open"] + f30["Close"]) / 2).mean() / o_bar - 1 if len(f30) else np.nan
            rows.append(row)
        if not rows:
            print(iv, "데이터 없음"); continue
        T = pd.DataFrame(rows)
        print(f"\n=== {iv}: 종목-밤 {len(T)}건, {T['date'].nunique()}일 ({T['date'].min().date()}~{T['date'].max().date()}) — 비용 전, 종목 단위 평균")
        cols = ["on"] + [c for c in T.columns if c not in ("date", "on")]
        for c in cols:
            v = T[c].dropna()
            dd = (T[c] - T["on"]).dropna()
            print(f"   {('시가' if c=='on' else c):12} 평균 {v.mean()*100:+6.2f}%  중앙 {v.median()*100:+6.2f}%  | 시가 대비 {dd.mean()*100:+5.2f}%p (t={dd.mean()/dd.std()*np.sqrt(len(dd)):+.2f}, 시가보다 나은 비율 {(dd>0).mean()*100:.0f}%)")
        # 갭 크기별
        T["gb"] = pd.cut(T["on"], [-1, -0.02, 0, 0.02, 0.05, 1])
        c = "10:00" if "10:00" in T else None
        if c:
            print("   갭 구간별 10:00 매도 − 시가 매도:", " | ".join(f"{k}: n={len(g)} {(g[c]-g['on']).mean()*100:+.2f}%p" for k, g in T.groupby("gb", observed=True)))


if __name__ == "__main__":
    if "fetch" in sys.argv:
        fetch()
    analyse()
