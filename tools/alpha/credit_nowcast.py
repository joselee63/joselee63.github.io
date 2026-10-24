"""신용잔고 변화 · 반대매매를 '그날 알 수 있는 데이터'로 추정 (금투협 자료는 2거래일 늦게 나옴)
python tools/alpha/credit_nowcast.py
  · 신용잔고 일변화율 cr1(T) ← 그날 코스피·코스닥 등락, 개인·외국인·기관 순매수(전 종목 합계, 신용잔고 대비), 전날 등락
  · 반대매매 배수 fx(T) (직전 20일 중앙값 대비) ← T−1·T−2·T−3 등락(담보 부족 → 2거래일 뒤 실행), 20일 고점 대비 낙폭, 신용잔고 규모
  학습 2015-01 ~ 2022-12 / 검증 2023-01 ~ (표본 외) · 선형회귀(최소제곱)
"""
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
D = ROOT / "data-alpha" / "kofia"


def market_flows(adir):
    fs = sorted(glob.glob(str(Path(adir) / "flows" / "*" / "*.csv.gz")))
    parts = []
    for f in fs:
        x = pd.read_csv(f, usecols=["date", "frg_nv", "frg2_nv", "inst_nv", "indiv_nv"])
        parts.append(x.groupby("date").sum())
    fl = pd.concat(parts)
    fl.index = pd.to_datetime(fl.index.astype(str), format="%Y%m%d")
    fl["frg"] = fl.frg_nv + fl.frg2_nv.fillna(0)
    return fl[["frg", "inst_nv", "indiv_nv"]].rename(columns={"inst_nv": "inst", "indiv_nv": "indiv"}).groupby(level=0).sum()


def features(ix, money, credit, fl):
    df = ix.join(money, how="left").join(credit, how="left").join(fl, how="left")
    k, q = df.KOSPI, df.KOSDAQ
    df["rk"] = k.pct_change(); df["rq"] = q.pct_change()
    df["rk1"] = df.rk.shift(1); df["rq1"] = df.rq.shift(1); df["rq2"] = df.rq.shift(2); df["rk2"] = df.rk.shift(2); df["rq3"] = df.rq.shift(3)
    df["dd20"] = k / k.rolling(20).max() - 1
    cr_prev = df.credit.ffill().shift(1) * 1e6                       # 백만원 → 원
    for c in ("indiv", "frg", "inst"):
        df[c + "_s"] = df[c] / cr_prev                                # 순매수 ÷ 신용잔고
    df["cr1"] = df.credit.pct_change()
    med = df.forced.rolling(20, min_periods=15).median().shift(1)
    df["fx"] = np.log1p(df.forced / med)
    df["fx_raw"] = df.forced / med
    df["neg2"] = np.minimum(df.rq1, 0) + np.minimum(df.rq2, 0)        # 최근 이틀 코스닥 하락 합
    df["negk2"] = np.minimum(df.rk1, 0) + np.minimum(df.rk2, 0)
    return df


def fit(df, y, X, split="2023-01-01"):
    d = df.dropna(subset=[y] + X)
    tr, te = d[d.index < split], d[d.index >= split]
    A = np.c_[np.ones(len(tr)), tr[X].to_numpy()]
    b, *_ = np.linalg.lstsq(A, tr[y].to_numpy(), rcond=None)
    pred = lambda z: np.c_[np.ones(len(z)), z[X].to_numpy()] @ b
    r2 = lambda z: 1 - ((z[y] - pred(z)) ** 2).sum() / ((z[y] - z[y].mean()) ** 2).sum()
    return b, pred, r2(tr), r2(te), tr, te


if __name__ == "__main__":
    ix = pd.read_csv(D / "index.csv", parse_dates=["date"]).set_index("date")
    m = pd.read_csv(D / "money.csv", dtype={"date": str}); m.index = pd.to_datetime(m.pop("date"))
    c = pd.read_csv(D / "credit.csv", dtype={"date": str}); c.index = pd.to_datetime(c.pop("date"))
    fl = market_flows(ROOT / "data-alpha" / "alpha")
    df = features(ix, m, c, fl)
    df = df[df.index >= "2015-01-01"]
    print(f"수급 자료 {fl.index.min():%Y-%m-%d} ~ {fl.index.max():%Y-%m-%d}")

    print("\n[1] 신용잔고 일변화율 추정 (그날 장 마감 뒤 알 수 있는 값만)")
    for lab, X in (("지수만", ["rk", "rq"]), ("지수+수급", ["rk", "rq", "indiv_s", "frg_s", "inst_s"]),
                   ("지수+수급+전날", ["rk", "rq", "indiv_s", "frg_s", "inst_s", "rk1", "rq1"])):
        b, pred, r2a, r2b, tr, te = fit(df, "cr1", X)
        e = te.assign(p=pred(te))
        hit = e[e.cr1 <= -0.03]; fa = e[e.p <= -0.02]
        print(f"  {lab:14} R² 학습 {r2a:.2f} · 검증(2023~) {r2b:.2f} · 실제 −3%↓ {len(hit)}일 중 추정 −2%↓로 잡은 날 {(hit.p <= -0.02).sum()} · 추정 −2%↓ {len(fa)}일 중 실제 −2%↓ {(fa.cr1 <= -0.02).sum()}")
        print("     계수:", " ".join(f"{n}={v:+.4f}" for n, v in zip(["상수"] + X, b)))
    print("\n[2] 반대매매 배수 log(1+반대매매/20일중앙값) 추정 — T−1·T−2 하락으로 T 반대매매 예측")
    for lab, X in (("코스닥 T−1·T−2·T−3", ["rq1", "rq2", "rq3"]), ("+코스피·낙폭", ["rq1", "rq2", "rq3", "rk1", "rk2", "dd20"]),
                   ("+최근 이틀 하락합", ["rq1", "rq2", "rq3", "rk1", "rk2", "dd20", "neg2", "negk2"]),
                   ("+당일 등락 포함", ["rq", "rk", "rq1", "rq2", "rq3", "rk1", "rk2", "dd20", "neg2", "negk2"])):
        b, pred, r2a, r2b, tr, te = fit(df, "fx", X)
        e = te.assign(p=np.expm1(pred(te)))
        big = e[e.fx_raw >= 3]
        print(f"  {lab:20} R² 학습 {r2a:.2f} · 검증 {r2b:.2f} · 실제 3배↑ {len(big)}일 중 추정 2배↑ {(big.p >= 2).sum()} · 추정 2배↑ {(e.p >= 2).sum()}일 중 실제 2배↑ {(e[e.p >= 2].fx_raw >= 2).sum()}")
        print("     계수:", " ".join(f"{n}={v:+.3f}" for n, v in zip(["상수"] + X, b)))
    df.to_csv(D / "nowcast_features.csv")
