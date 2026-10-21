"""한국 증권사 리포트(한경 컨센서스) — 목표가·투자의견 변화 이벤트와 컨센서스 괴리율.
python tools/alpha/kr_analyst.py [events|xsec|all]

시점: 리포트 날짜 d (대개 장 전 배포지만 보수적으로) → d 이후 첫 거래일 '다음날' 시가 매수
      (d 가 거래일이면 d+1 시가). 낙관 기준(d 시가)도 참고로 병기.
변화율: 같은 증권사의 같은 종목 직전 리포트(365일 이내) 대비. 신규 커버리지 = 그 증권사의 직전 365일 리포트 없음.
수익: H거래일 보유(시가→시가), 같은 날 유니버스(유동성 10억+·매수 가능) 평균 대비 초과.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, COST_KR, base_mask, fwd, load_alpha, load_panel, nw_t, quantile_returns, qline, robust_q  # noqa: E402

RAT = {"strong buy": 2, "strongbuy": 2, "buy": 1, "매수": 1, "outperform": 1, "overweight": 1, "trading buy": 1,
       "tradingbuy": 1, "비중확대": 1, "적극매수": 2, "accumulate": 1, "add": 1,
       "hold": 0, "중립": 0, "neutral": 0, "marketperform": 0, "market perform": 0, "보유": 0, "equal-weight": 0,
       "sell": -1, "reduce": -1, "underperform": -1, "매도": -1, "비중축소": -1, "underweight": -1}


def load_reports():
    fs = sorted((ROOT / "data-alpha" / "reports").glob("hk_*.csv"))
    r = pd.concat((pd.read_csv(f, dtype=str) for f in fs), ignore_index=True)
    # 2017-03부터 링크 텍스트가 '종목명(코드)제목' 형식 → 이름에서 코드 추출
    code = r["name"].str.extract(r"\((\d{6})\)")[0]
    r["ticker"] = r["ticker"].where(r["ticker"].str.fullmatch(r"\d{6}", na=False), code)
    r["idx"] = pd.to_numeric(r["idx"], errors="coerce")
    r = r[r["ticker"].str.fullmatch(r"\d{6}", na=False)].drop_duplicates("idx")
    r["date"] = pd.to_datetime(r["date"])
    r["tp"] = pd.to_numeric(r["tp"], errors="coerce")
    r.loc[r["tp"] <= 0, "tp"] = np.nan
    r["rt"] = r["op"].str.strip().str.lower().map(RAT)
    r["firm"] = r["firm"].str.strip()
    r = r.sort_values(["ticker", "firm", "date", "idx"])
    g = r.groupby(["ticker", "firm"])
    r["pdate"] = g["date"].shift(); r["ptp"] = g["tp"].shift(); r["prt"] = g["rt"].shift()
    recent = (r["date"] - r["pdate"]).dt.days <= 365
    r["init"] = ~recent
    r["tpchg"] = np.where(recent, r["tp"] / r["ptp"] - 1, np.nan)
    r["rtchg"] = np.where(recent, r["rt"] - r["prt"], np.nan)
    return r


def attach(P, r, Hs=(1, 5, 20, 60)):
    r = r[r["ticker"].isin(P.ti)].copy()
    i = P.dates.searchsorted(r["date"], side="right") - 1          # d 이하 마지막 거래일 행 → fwd 는 i+1 시가 매수
    r["i"] = i; r["j"] = r["ticker"].map(P.ti)
    r = r[(r["i"] >= 1) & (r["i"] < P.T - 62)]
    m = base_mask(P)
    r = r[m[r["i"], r["j"]]]
    for H in Hs:
        R = fwd(P, H)
        mu = np.nanmean(np.where(m, R, np.nan), axis=1)
        r[f"x{H}"] = R[r["i"], r["j"]] - mu[r["i"]]
        # 낙관(d 당일 시가 매수): d 가 거래일일 때만 i-1 행 기준
        r[f"o{H}"] = np.where(P.dates[r["i"]] == r["date"], R[r["i"] - 1, r["j"]] - mu[r["i"] - 1], np.nan)
    return r.dropna(subset=["x20"])


def show(e, mask, lab, key="x"):
    q = e[mask].drop_duplicates(["ticker", "i"])                 # 같은 날 같은 종목 여러 건 → 1건
    if len(q) < 200:
        print(f"  {lab:32} n={len(q)} (표본 부족)"); return None
    parts = []
    for H in (1, 5, 20, 60):
        x = q[f"{key}{H}"].dropna()
        mon = x.groupby(q.loc[x.index, "date"].dt.to_period("M")).mean()
        parts.append(f"H{H} {x.mean()*100:+.2f}({nw_t(mon.to_numpy(), max(1, H // 20)):.1f})")
    x = q[f"{key}20"]
    med = q["date"].median(); yr = x.groupby(q["date"].dt.year).mean()
    print(f"  {lab:32} n={len(q):6d} " + " ".join(parts) +
          f" | H20 승 {(x>0).mean()*100:.0f}% 하위1% {np.percentile(x.dropna(),1)*100:+.1f}% 앞/뒤 {x[q['date']<=med].mean()*100:+.2f}/{x[q['date']>med].mean()*100:+.2f} 플러스연도 {(yr>0).sum()}/{len(yr)}")
    return q


def events(P, e):
    print(f"리포트 {len(e):,}건 (유동성 10억+, 매수 가능) · {e['date'].min().date()}~{e['date'].max().date()} · 증권사 {e['firm'].nunique()}")
    print("== 이벤트별 유니버스 대비 초과수익 % (괄호 = 월별 NW t값), 진입 = 리포트 다음 거래일 시가 ==")
    e = e[e["date"] >= "2015-01-01"]
    show(e, e["init"], "신규 커버리지")
    show(e, e["init"] & (e["rt"] >= 1), "신규 커버리지 + 매수")
    show(e, e["tpchg"] > 0, "목표가 상향(같은 증권사)")
    show(e, e["tpchg"] >= 0.2, "목표가 +20% 이상 상향")
    show(e, e["tpchg"] == 0, "목표가 유지")
    show(e, e["tpchg"] < 0, "목표가 하향")
    show(e, e["tpchg"] <= -0.2, "목표가 −20% 이상 하향")
    show(e, e["rtchg"] > 0, "투자의견 상향")
    show(e, e["rtchg"] < 0, "투자의견 하향 (예: 매수→중립)")
    show(e, e["rt"] <= 0, "중립·매도 의견 (전체)")
    show(e, e["op"].str.contains("Not Rated|N/R|NR", na=False), "Not Rated")
    print("== 참고: 낙관 진입(리포트 당일 시가) ==")
    show(e, e["tpchg"] >= 0.2, "목표가 +20% 상향 (당일 시가)", key="o")
    show(e, e["rtchg"] < 0, "의견 하향 (당일 시가)", key="o")
    # 목표가 변화율 5분위 (변경 리포트만)
    c = e.dropna(subset=["tpchg"]).drop_duplicates(["ticker", "i"])
    c = c[c["tpchg"] != 0]
    c["q"] = pd.qcut(c["tpchg"].rank(method="first"), 5, labels=False) + 1
    for H in (5, 20, 60):
        print(f"  목표가 변화율 5분위 H={H}: " + " ".join(f"Q{k}:{v*100:+.2f}" for k, v in c.groupby("q")[f"x{H}"].mean().items()))


def xsec(P, r):
    """일별 횡단면: 컨센서스 괴리율, 상향 모멘텀(최근 60일 상향−하향 건수), 커버리지 수"""
    cap = load_alpha("cap"); cap = cap[cap["ticker"].isin(set(P.tickers))]
    raw = pd.DataFrame(P.align(cap, "close")).ffill(limit=5).to_numpy()   # 원주가 (목표가와 같은 단위)
    r = r[r["ticker"].isin(P.ti)]
    r = r.assign(i=P.dates.searchsorted(r["date"], side="right") - 1, j=r["ticker"].map(P.ti))
    r = r[r["i"] >= 0]
    T, N = P.T, P.N
    up = np.zeros((T, N), np.float32); dn = np.zeros((T, N), np.float32); cnt = np.zeros((T, N), np.float32)
    np.add.at(up, (r["i"], r["j"]), (r["tpchg"] > 0).astype(np.float32))
    np.add.at(dn, (r["i"], r["j"]), (r["tpchg"] < 0).astype(np.float32))
    np.add.at(cnt, (r["i"], r["j"]), 1)
    roll = lambda a, n: pd.DataFrame(a).rolling(n, min_periods=1).sum().to_numpy()
    rev60 = roll(up, 60) - roll(dn, 60)
    cov180 = roll(cnt, 180)
    # 컨센서스 목표가: 증권사별 가장 최근 목표가(180일 이내) 평균 → 일별 (주 단위 계산 후 ffill)
    cons = np.full((T, N), np.nan)
    rr = r.dropna(subset=["tp"])[["i", "j", "firm", "tp"]]
    weeks = list(range(0, T, 5))
    for w in weeks:
        sub = rr[(rr["i"] <= w) & (rr["i"] > w - 126)]
        if sub.empty:
            continue
        last = sub.drop_duplicates(["j", "firm"], keep="last").groupby("j")["tp"].mean()
        cons[w, last.index.to_numpy()] = last.to_numpy()
    cons = pd.DataFrame(cons).ffill(limit=4).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        upside = cons / raw - 1
    m = base_mask(P)
    feats = {"컨센서스 괴리율(목표가/주가−1)": upside, "목표가 상향−하향 건수(60일)": np.where(cov180 > 0, rev60, np.nan),
             "커버리지 리포트 수(180일)": cov180, "상향 모멘텀 ÷ 커버리지": np.where(cov180 >= 3, rev60 / cov180, np.nan)}
    for name, X in feats.items():
        for H in (20, 60):
            print(qline(quantile_returns(P, X, H, m), H, COST_KR, name), flush=True)
    robust_q(P, upside, 60, m, "컨센서스 괴리율")
    robust_q(P, np.where(cov180 >= 3, rev60 / cov180, np.nan), 60, m, "상향 모멘텀÷커버리지")
    return feats


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    P = load_panel()
    r = load_reports()
    if mode in ("events", "all"):
        events(P, attach(P, r))
    if mode in ("xsec", "all"):
        xsec(P, r)
