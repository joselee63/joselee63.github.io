"""반대매매 · 신용잔고 · 예탁금으로 시장 바닥/고점 가늠 — 이벤트 분석
python tools/alpha/credit_signals.py
데이터: data-alpha/kofia/{money,credit}.csv (kofia_credit.py), 코스피·코스닥 일봉(네이버 fchart, data-alpha/kofia/index.csv 캐시)
시점: 금투협 자료는 T일 수치가 다음 날 공표 → 기본 진입은 T+1 종가 (T 종가 진입은 참고용)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

D = Path(__file__).resolve().parents[2] / "data-alpha" / "kofia"


def index():
    f = D / "index.csv"
    if f.exists():
        return pd.read_csv(f, parse_dates=["date"]).set_index("date")
    out = {}
    for code in ("KOSPI", "KOSDAQ"):
        r = requests.get("https://fchart.stock.naver.com/sise.nhn", params={"symbol": code, "timeframe": "day", "count": 7000, "requestType": 0},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        rows = re.findall(r'data="([^"]+)"', r.text)
        s = pd.Series({pd.Timestamp(x.split("|")[0]): float(x.split("|")[4]) for x in rows})
        out[code] = s
    df = pd.DataFrame(out).sort_index(); df.index.name = "date"
    df.to_csv(f)
    return df


ix = index()
m = pd.read_csv(D / "money.csv", dtype={"date": str}); m["date"] = pd.to_datetime(m["date"])
c = pd.read_csv(D / "credit.csv", dtype={"date": str}); c["date"] = pd.to_datetime(c["date"])
df = ix.join(m.set_index("date"), how="inner").join(c.set_index("date"), how="inner")
df = df[df.index >= "2006-04-14"].copy()                       # 반대매매 자료 시작
df = df[(df.credit > 0)]
k = df.KOSPI
for h in (1, 5, 20, 60, 120):
    df[f"f{h}"] = k.shift(-h - 1) / k.shift(-1) - 1                # T+1 종가 진입
df["f20_t"] = k.shift(-20) / k - 1                               # T 종가 진입(참고)
df["mdd60"] = pd.concat([k.shift(-i - 1) for i in range(1, 61)], axis=1).min(axis=1) / k.shift(-1) - 1   # 진입 후 60일 안 최저
df["mup60"] = pd.concat([k.shift(-i - 1) for i in range(1, 61)], axis=1).max(axis=1) / k.shift(-1) - 1
df["kday"] = k.pct_change()
df["k5"] = k / k.shift(5) - 1
# 바닥 근접: 신호일이 전후 20거래일 최저 종가에서 몇 % 위인가 (사후 확인용)
lo = k.rolling(41, center=True, min_periods=21).min(); hi = k.rolling(41, center=True, min_periods=21).max()
df["fromlo"] = k / lo - 1; df["fromhi"] = k / hi - 1
# 신호 재료
df["forced_x"] = df.forced / df.forced.rolling(20, min_periods=15).median().shift(1)   # 반대매매 ÷ 직전 20일 중앙값
df["cr1"] = df.credit.pct_change()
df["cr5"] = df.credit / df.credit.shift(5) - 1
df["cr60"] = df.credit / df.credit.shift(60) - 1
df["cr_rel"] = df.credit / df.credit.rolling(250, min_periods=200).mean() - 1
df["dep20"] = df.deposit / df.deposit.shift(20) - 1
df["dep_rel"] = df.deposit / df.deposit.rolling(250, min_periods=200).mean() - 1
# 신용잔고 ÷ 지수 (레버리지 강도 근사: 잔고가 지수보다 빨리 늘면 빚투 비중 상승)
df["cr_idx"] = df.credit / k
df["cr_idx_rel"] = df.cr_idx / df.cr_idx.rolling(250, min_periods=200).mean() - 1

BASE = df.dropna(subset=["f20"])


def declust(mask, gap=10):
    """gap 거래일 안에 이어진 신호는 첫날만"""
    idx = np.nonzero(mask.to_numpy())[0]; keep = []; last = -10**9
    for i in idx:
        if i - last > gap:
            keep.append(i)
        last = i
    return df.index[keep]


def show(lab, mask, gap=10, cols=("f5", "f20", "f60", "f120"), extra=True):
    dts = declust(mask.fillna(False), gap)
    x = df.loc[dts].dropna(subset=["f20"])
    if not len(x):
        print(f"  {lab:46} 0건"); return x
    s = " · ".join(f"{cc} {x[cc].mean()*100:+5.1f}%(승{(x[cc]>0).mean()*100:3.0f}%)" for cc in cols if x[cc].notna().any())
    e = f" · 60일내 최저 {x.mdd60.mean()*100:+5.1f}% · 바닥대비 {x.fromlo.median()*100:4.1f}%" if extra else ""
    print(f"  {lab:46} {len(x):3d}건 · {s}{e}")
    return x


if __name__ == "__main__":
    print(f"기간 {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d} · {len(df)}일 (진입 = 신호 다음날 종가, 코스피)")
    b = BASE
    print(f"[기준] 아무 날: f5 {b.f5.mean()*100:+.2f}% · f20 {b.f20.mean()*100:+.2f}%(승{(b.f20>0).mean()*100:.0f}%) · f60 {b.f60.mean()*100:+.2f}% · f120 {b.f120.mean()*100:+.2f}% · 60일내 최저 {b.mdd60.mean()*100:+.1f}%")
    print("\n[바닥] 반대매매 급증 (직전 20일 중앙값 대비 배수, 10일 내 중복 제거)")
    for kx in (2, 3, 4, 6):
        show(f"반대매매 ≥ {kx}배", df.forced_x >= kx)
    for q in (0.95, 0.99):
        th = df.forced.quantile(q); show(f"반대매매 금액 상위 {int((1-q)*100)}% ({th/100:,.0f}억+)", df.forced >= th)
    print("\n[바닥] 신용잔고 급감")
    for th in (-0.02, -0.03, -0.05):
        show(f"신용잔고 하루 {th*100:.0f}% 이하", df.cr1 <= th)
    for th in (-0.05, -0.08, -0.12):
        show(f"신용잔고 5일 {th*100:.0f}% 이하", df.cr5 <= th)
    print("\n[바닥] 결합")
    show("반대매매 ≥3배 + 신용잔고 하루 −2%↓", (df.forced_x >= 3) & (df.cr1 <= -0.02))
    show("반대매매 ≥3배 + 신용잔고 5일 −5%↓", (df.forced_x >= 3) & (df.cr5 <= -0.05))
    show("반대매매 ≥4배 + 코스피 5일 −8%↓", (df.forced_x >= 4) & (df.k5 <= -0.08))
    show("코스피 5일 −8%↓ 단독 (비교)", df.k5 <= -0.08)
    show("반대매매 ≥3배 인데 신용잔고 감소 1% 미만(청산 덜 됨)", (df.forced_x >= 3) & (df.cr1 > -0.01) & (df.k5 <= -0.05))
    print("\n[고점] 신용잔고 과열")
    for th in (0.20, 0.30, 0.45):
        show(f"신용잔고 1년 평균 대비 +{th*100:.0f}%↑", df.cr_rel >= th, gap=60, cols=("f20", "f60", "f120"))
    for th in (0.15, 0.25):
        show(f"신용잔고 60일 증가 +{th*100:.0f}%↑", df.cr60 >= th, gap=60, cols=("f20", "f60", "f120"))
    for th in (0.15, 0.25):
        show(f"신용잔고÷지수 1년 평균 대비 +{th*100:.0f}%↑", df.cr_idx_rel >= th, gap=60, cols=("f20", "f60", "f120"))
    print("\n[고점] 투자자예탁금 과열")
    for th in (0.15, 0.25, 0.40):
        show(f"예탁금 20일 증가 +{th*100:.0f}%↑", df.dep20 >= th, gap=60, cols=("f20", "f60", "f120"))
    for th in (0.40, 0.70):
        show(f"예탁금 1년 평균 대비 +{th*100:.0f}%↑", df.dep_rel >= th, gap=60, cols=("f20", "f60", "f120"))
    print("\n[고점] 구간별(신용잔고 1년 평균 대비 수준) 이후 수익 — 중복 포함 전체 일수")
    df["bk"] = pd.cut(df.cr_rel, [-1, -0.1, 0, 0.1, 0.2, 0.3, 9])
    print(df.dropna(subset=["f60"]).groupby("bk", observed=True).agg(일수=("f60", "size"), f20=("f20", "mean"), f60=("f60", "mean"), f120=("f120", "mean"), 최저60=("mdd60", "mean")).round(3).to_string())
    df.to_csv(D / "signals.csv")
