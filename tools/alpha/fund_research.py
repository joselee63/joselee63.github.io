"""펀더멘털(KRX 주간 PER/PBR/EPS/BPS/DIV) 횡단면 알파 + EPS 갱신 이벤트(연간 실적 서프라이즈 대용).
python tools/alpha/fund_research.py [pit|scan|event]

시점: 주 마지막 거래일 w 의 KRX 값 → w 다음 거래일 시가부터 사용 (값은 다음 주 갱신까지 유지).
  pit    EPS 가 바뀌는 시기 분포 (KRX 가 실적을 언제 반영하는지 = point-in-time 확인)
  scan   가치·퀄리티·배당 분위 (H=20·60)
  event  EPS 갱신 주: 증가율 분위 → 이후 20·60일 초과수익 (연간 PEAD)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, base_mask, load_alpha, load_panel, quantile_returns, qline, fwd, nw_t  # noqa: E402


def load_fund(P):
    f = load_alpha("fund")
    f = f[f["ticker"].isin(set(P.tickers))].sort_values(["ticker", "date"])
    return f


def weekly_to_daily(P, f, col):
    """주간 값 → 다음 거래일부터 적용되도록 1일 늦춰 ffill (최대 10거래일)"""
    a = P.align(f, col)
    a = pd.DataFrame(a).ffill(limit=10).shift(1).to_numpy()
    return a


def pit(f):
    g = f.groupby("ticker")
    f = f.copy()
    f["eps_prev"] = g["EPS"].shift()
    ch = f[(f["eps_prev"].notna()) & (f["EPS"] != f["eps_prev"])]
    print(f"EPS 변경 {len(ch):,}건 — 월별 분포(%)")
    print((ch["date"].dt.month.value_counts(normalize=True).sort_index() * 100).round(1).to_string())
    print("주(week of year) 상위:")
    print(ch["date"].dt.isocalendar().week.value_counts().head(12).to_string())
    print("연도별 변경 건수:", ch["date"].dt.year.value_counts().sort_index().to_dict())
    # 예: 삼성전자 EPS 시계열
    s = f[f["ticker"] == "005930"][["date", "EPS", "BPS", "DPS"]]
    s = s[s["EPS"] != s["EPS"].shift()]
    print(s.to_string())


def scan(P, f):
    m = base_mask(P, liq=True)
    per = weekly_to_daily(P, f, "PER"); pbr = weekly_to_daily(P, f, "PBR")
    eps = weekly_to_daily(P, f, "EPS"); bps = weekly_to_daily(P, f, "BPS"); div = weekly_to_daily(P, f, "DIV")
    with np.errstate(invalid="ignore", divide="ignore"):
        # KRX 는 적자 EPS 를 0 으로 표기 → 적자 = E/P 최저(동점 그룹)
        ep = np.where(per > 0, 1 / per, np.where(np.isfinite(per), -0.01, np.nan))
        bm = np.where(pbr > 0, 1 / pbr, np.nan)
        roe = np.where(bps > 0, np.where(eps > 0, eps / bps, -0.01), np.nan)     # 적자 = 최저 그룹
    def r(x):
        return pd.DataFrame(np.where(m, x, np.nan)).rank(axis=1, pct=True).to_numpy()
    feats = {
        "E/P (이익수익률)": ep, "B/M (1/PBR)": bm, "배당수익률": np.where(div >= 0, div, np.nan),
        "ROE (EPS/BPS)": roe,
        "가치+퀄리티: E/P+B/M+ROE 순위합": r(ep) + r(bm) + r(roe),
        "저PBR & 고ROE: B/M+ROE": r(bm) + r(roe),
        "흑자 저PER (E/P, 적자 제외)": np.where(per > 0, 1 / np.where(per > 0, per, 1), np.nan),
        "흑자 고ROE (적자 제외)": np.where(eps > 0, roe, np.nan),
    }
    for name, X in feats.items():
        for H in (20, 60):
            print(qline(quantile_returns(P, X, H, m), H, COST_KR, name), flush=True)
        print(qline(quantile_returns(P, X, 60, base_mask(P, liq=False)), 60, COST_KR, "  └ 유동성필터 없음"), flush=True)
    return feats


def event(P, f):
    """EPS 가 바뀐 주 = 새 연간 실적 반영. 증가율로 이벤트 분위."""
    f = f.copy()
    g = f.groupby("ticker")
    f["eps_prev"] = g["EPS"].shift()
    ch = f[(f["eps_prev"].notna()) & (f["EPS"] != f["eps_prev"])].copy()
    ch = ch[ch["date"].dt.month.isin([3, 4, 5, 6])]          # 연간 사업보고서 반영 시즌만
    with np.errstate(invalid="ignore", divide="ignore"):
        ch["g"] = (ch["EPS"] - ch["eps_prev"]) / ch["eps_prev"].abs()
    ch["turn"] = (ch["eps_prev"] <= 0) & (ch["EPS"] > 0)
    ch = ch[ch["ticker"].isin(P.ti)]
    ii = P.dates.searchsorted(ch["date"])                   # 그 주 마지막 거래일 행
    ch["i"] = ii; ch["j"] = ch["ticker"].map(P.ti)
    ch = ch[ch["i"] < P.T - 62]
    m = base_mask(P, liq=True)
    ch = ch[m[ch["i"], ch["j"]]]
    for H in (20, 60):
        R = fwd(P, H)
        mu = np.nanmean(np.where(m, R, np.nan), axis=1)
        ch[f"x{H}"] = R[ch["i"], ch["j"]] - mu[ch["i"]]
    ch = ch.dropna(subset=["x60"])
    ch["gq"] = ch.groupby(ch["date"].dt.year)["g"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)) + 1
    print(f"EPS 갱신 이벤트 {len(ch):,}건 (3~6월, 유동성 10억+)")
    for H in (20, 60):
        mm = ch.groupby("gq")[f"x{H}"].mean() * 100
        print(f"  증가율 5분위 H={H}: " + " ".join(f"Q{k}:{v:+.2f}" for k, v in mm.items()))
        t = ch[ch["turn"]][f"x{H}"]
        print(f"  흑자전환 H={H}: n={len(t)} 초과 {t.mean()*100:+.2f}%")
        q5 = ch[ch["gq"] == 5]
        yr = q5.groupby(q5["date"].dt.year)[f"x{H}"].mean() * 100
        print(f"  Q5 연도별: " + " ".join(f"{y%100}:{v:+.1f}" for y, v in yr.items()))
    return ch


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    P = load_panel()
    f = load_fund(P)
    print(f"펀더멘털 {f['date'].nunique()}주 · {f['ticker'].nunique()}종목")
    {"pit": lambda: pit(f), "scan": lambda: scan(P, f), "event": lambda: event(P, f)}[mode]()
