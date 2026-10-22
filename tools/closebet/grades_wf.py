"""§8. 이전 체계(종베 스캐너 v9, strategy_analysis/overnight/jongbe_scanner_v9.ipynb) 무편향 재현·재검증
python tools/closebet/grades_wf.py [A][B][C]   (기본: 전부)

노트북의 실제 정의 (셀 1·2·3·10 코드 기준):
  유니버스  universe(200): FinanceDataReader '오늘' 상장 목록에서 '오늘' 시총 ≥1조, 시총 상위 200 → 생존·선택 편향
  데이터    START 2019-01-01, |갭|>30% 날은 기업행위로 보고 제외
  신호      전일 대비 +3% 이상 마감 (상한가 잠김 포함 — 체결 가능성 미반영)
  수익      gap = 다음날 시가/종가 − 1 − 비용 0.2%
  등급      종목별 과거 신호 '평균(gap−cost)'의 유니버스 내 백분위, 신호 ≥100건(셀 12-E 는 60건). S≥90, A≥80
  레짐      지수의 '밤 갭'(다음날 시가/종가−1) 이동평균: KOSPI 120일·KOSDAQ 60일 평균이 둘 다 > 0 (전날까지 값)
  백테스트  셀 10: 연 1회 재적합 워크포워드 (Y년 등급 = Y년 1월 1일 이전 데이터) ← 등급 자체는 사후편향 없음
            S·A 후보 중 등급순 최대 3, 비중 min(40%, 2%/max(|하위1% 갭|,1%)), 합 100% 초과 시 비례 축소, 나머지 현금
  등급표 csv(v9) 는 전체 기간 통계 → 그 표로 같은 기간을 백테스트하면 사후편향
여기서는 같은 규칙을 무편향 일봉(상폐 포함)에 그대로 적용하고, 유니버스만 바꿔 편향 크기를 잰다.
"""
import sys
import numpy as np
import pandas as pd
from cb import CB, load_panel, stats, line, nw_t

sys.path.insert(0, str(CB.parent / "tools" / "alpha"))
from common import BT, load_alpha  # noqa: E402

P = load_panel()
T, N = P.T, P.N
yr = P.dates.year.to_numpy()
first_of_year = np.r_[True, yr[1:] != yr[:-1]]
nxt_o = np.vstack([P.o[1:], np.full((1, N), np.nan)])
GAP = nxt_o / P.c - 1
with np.errstate(invalid="ignore"):
    GAP = np.where(np.abs(GAP) > 0.30, np.nan, GAP)                       # 노트북의 기업행위 제외
    SIG_ALL = (P.day >= 0.03) & np.isfinite(GAP) & (P.run >= 60)          # 노트북 원본 (잠김 포함)
    LOCK = P.day >= 0.285
SIG_BUY = SIG_ALL & ~LOCK                                                 # 체결 가능

# ---------------------------------------------------------------- 레짐
ix = pd.read_csv(BT / "sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])


def idx(code):
    x = ix[ix["index_code"] == code].set_index("date").reindex(P.dates)
    return x["open"], x["close"].ffill()


def gap_regime(code, win):
    o, c = idx(code)
    g = o.shift(-1) / c - 1                       # t일 종가 → t+1 시가
    return g.shift(1).rolling(win).mean()         # t일에 아는 값 (t일 시가까지)


REG_OLD = ((gap_regime("1001", 120) > 0) & (gap_regime("2001", 60) > 0)).to_numpy()
_, kqc = idx("2001"); _, ksc = idx("1001")
REG_KQ20 = (kqc > kqc.rolling(20).mean()).to_numpy()
REG_KS60 = P.mkt_ok
REG_ALL = np.ones(T, bool)

# ---------------------------------------------------------------- 유니버스
g = pd.read_csv(CB / "old_grades_mapped.csv", dtype={"ticker": str})
OLD = np.isin(P.tickers, g.loc[g["in_panel"], "ticker"])                    # 등급표 종목 (오늘 기준 선택)
cap = load_alpha("cap"); cap = cap[cap["ticker"].isin(set(P.tickers))]
MC = P.align(cap, "mcap")
MC = pd.DataFrame(MC).ffill(limit=5).to_numpy()


def yearly_universe(score, n, minval=-np.inf):
    U = np.zeros((T, N), bool); cur = np.zeros(N, bool)
    for t in range(T):
        if first_of_year[t] and t > 0:
            a = np.nan_to_num(score[t - 1], nan=-np.inf)
            top = np.argsort(-a)[:n]
            cur = np.zeros(N, bool); cur[top] = a[top] > max(minval, -np.inf)
        U[t] = cur
    return U


PIT_CAP = yearly_universe(MC, 200, 1e12)                                    # 매년 초 시총 ≥1조 상위 200 (그때 기준)
amt250 = pd.DataFrame(P.amt).rolling(250, min_periods=200).mean().to_numpy()
PIT_LIQ = yearly_universe(amt250, 300, 0)
# 오늘 시총 상위 200 (노트북 universe() 를 오늘 실행한 것과 같은 선택)
last_mc = MC[-1]
TODAY200 = np.zeros(N, bool); o = np.argsort(-np.nan_to_num(last_mc, nan=-1))[:200]; TODAY200[o] = last_mc[o] >= 1e12


# ---------------------------------------------------------------- 등급 (연 1회 워크포워드)
def yearly_grades(SIG, U, cost, minn=100, start="2019-01-01", window_years=None):
    """Y년 등급 = start ~ Y-01-01 이전 신호의 평균(gap−cost), p01. U: 그해 유니버스(행별)"""
    s0 = np.searchsorted(P.dates, pd.Timestamp(start))
    M = np.full((T, N), np.nan); Q = np.full((T, N), np.nan)
    for y in sorted(set(yr)):
        t0 = np.argmax(yr == y)
        lo = s0 if window_years is None else max(s0, np.searchsorted(P.dates, pd.Timestamp(f"{y - window_years}-01-01")))
        if t0 - lo < 250:
            continue
        X = np.where(SIG[lo:t0], GAP[lo:t0] - cost, np.nan)
        n = np.isfinite(X).sum(0)
        with np.errstate(all="ignore"):
            m = np.nanmean(X, 0); q = np.nanpercentile(X, 1, axis=0)
        ok = (n >= minn) & U[t0]
        M[yr == y] = np.where(ok, m, np.nan); Q[yr == y] = np.where(ok, q, np.nan)
    pct = pd.DataFrame(M).rank(axis=1, pct=True).to_numpy()
    return M, Q, pct


def full_grades(SIG, U, cost, minn=100, start="2019-01-01"):
    s0 = np.searchsorted(P.dates, pd.Timestamp(start))
    X = np.where(SIG[s0:], GAP[s0:] - cost, np.nan)
    n = np.isfinite(X).sum(0)
    with np.errstate(all="ignore"):
        m = np.nanmean(X, 0); q = np.nanpercentile(X, 1, axis=0)
    Uany = U.any(0) if U.ndim == 2 else U
    m = np.where((n >= minn) & Uany, m, np.nan); q = np.where((n >= minn) & Uany, q, np.nan)
    M = np.tile(m, (T, 1)); Q = np.tile(q, (T, 1))
    return M, Q, pd.DataFrame(M).rank(axis=1, pct=True).to_numpy()


def backtest(SIG, U, reg, M, Q, pct, cost, top=0.8, k=3, start="2022-01-01", sizing="risk", order=None):
    """노트북 셀 10 backtest() 재현. 반환: 계좌 일수익 Series, 거래 DataFrame"""
    m = SIG & U & reg[:, None] & (pct >= top if top else np.isfinite(M))
    ii, jj = np.nonzero(m)
    d = pd.DataFrame({"i": ii, "j": jj, "s": (M if order is None else order)[ii, jj], "q": Q[ii, jj], "g": GAP[ii, jj]})
    d = d[P.dates[d["i"]] >= pd.Timestamp(start)]
    d = d.sort_values(["i", "s"], ascending=[True, False]).groupby("i").head(k).copy()
    if sizing == "risk":
        d["w"] = np.minimum(0.40, 0.02 / np.maximum(np.abs(np.minimum(d["q"].fillna(-0.05), -0.01)), 0.01))
        tot = d.groupby("i")["w"].transform("sum")
        d["w"] = np.where(tot > 1, d["w"] / tot, d["w"])
    else:
        d["w"] = 1.0 / k
    d["date"] = P.dates[d["i"]]
    acct = ((d["g"] - cost) * d["w"]).groupby(d["date"]).sum()
    return acct, d


def summary(lab, acct, d, cost):
    eq = (1 + acct).cumprod(); dd = (eq / eq.cummax() - 1).min()
    tr = d["g"] - cost
    ym = acct.groupby(acct.index.year).apply(lambda s: (1 + s).prod() - 1)
    print(f"{lab:46} 매매일 {len(acct):4d} 건당 {tr.mean()*100:+.3f}% (t={tr.mean()/tr.std()*np.sqrt(len(tr)):4.1f}) "
          f"계좌/일 {acct.mean()*100:+.3f}% 누적 {eq.iloc[-1]:5.2f}배 MDD {dd*100:5.1f}% 노출 {d.groupby('date')['w'].sum().mean()*100:3.0f}% "
          f"연도+ {(ym>0).sum()}/{len(ym)}")


if __name__ == "__main__":
    ONLY = sys.argv[1] if len(sys.argv) > 1 else "ABC"
    C2 = 0.002
    rng = np.random.default_rng(0)
    RND = rng.random((T, N))
    if "A" in ONLY:
        print("======== A. 노트북 규칙 그대로 (비용 0.2%, 2022~, 레짐=밤갭, 위험비중) — 유니버스·등급 방식만 바꿈")
        for uname, U, sig in (("등급표 종목(오늘 선택)", np.tile(OLD, (T, 1)), SIG_ALL),
                              ("오늘 시총 상위200", np.tile(TODAY200, (T, 1)), SIG_ALL),
                              ("그때 시총 상위200 (무편향)", PIT_CAP, SIG_ALL),
                              ("그때 시총 상위200, 잠김 제외", PIT_CAP, SIG_BUY)):
            print(f"--- 유니버스: {uname} (종목 {int(U.any(0).sum())}, 그중 상폐 {int(np.isin(P.tickers[U.any(0)], list(P.delisted)).sum())})")
            Mf, Qf, pf = full_grades(sig, U, C2)
            a, d = backtest(sig, U, REG_OLD, Mf, Qf, pf, C2); summary("  등급 S·A · 전체기간 등급(사후, csv 방식)", a, d, C2)
            My, Qy, py = yearly_grades(sig, U, C2)
            a, d = backtest(sig, U, REG_OLD, My, Qy, py, C2); summary("  등급 S·A · 연1회 워크포워드 (노트북 셀10)", a, d, C2)
            My6, Qy6, py6 = yearly_grades(sig, U, C2, minn=60)
            a, d = backtest(sig, U, REG_OLD, My6, Qy6, py6, C2); summary("  등급 S·A · 워크포워드, 최소신호 60", a, d, C2)
            a, d = backtest(sig, U, REG_OLD, My, Qy, py, C2, top=None, order=RND); summary("  무작위 3 (등급 산출 종목 중)", a, d, C2)
            a, d = backtest(sig, U, REG_OLD, My, Qy, py, C2, top=None, order=P.v / P.v20); summary("  거래량배수 순 3", a, d, C2)
            a, d = backtest(sig, U, REG_ALL, My, Qy, py, C2); summary("  등급 S·A 워크포워드, 레짐 없음", a, d, C2)
        print("\n--- 기간 확장: 무편향 유니버스(그때 시총 상위200), 데이터 2015~, 백테스트 2018~, 비용 0.25%, 잠김 제외")
        C25 = 0.0025
        for lab, kw in (("확장 창", {}), ("롤링 3년 창", {"window_years": 3})):
            My, Qy, py = yearly_grades(SIG_BUY, PIT_CAP, C25, start="2015-01-01", **kw)
            for rl, rg in (("밤갭 레짐", REG_OLD), ("KOSDAQ>20", REG_KQ20)):
                a, d = backtest(SIG_BUY, PIT_CAP, rg, My, Qy, py, C25, start="2018-01-01"); summary(f"  등급 S·A {lab} · {rl}", a, d, C25)
            a, d = backtest(SIG_BUY, PIT_CAP, REG_OLD, My, Qy, py, C25, top=None, order=RND, start="2018-01-01"); summary(f"  무작위 3 {lab} · 밤갭 레짐", a, d, C25)

    if "B" in ONLY:
        print("\n======== B. 레짐 비교 — 같은 무편향 유니버스·신호·비용(0.25%)·체결가능, 신호 전체 동일가중 평균(선별 효과 제거)")
        for uname, U, sig in (("그때 시총 상위200", PIT_CAP, SIG_BUY), ("거래대금 10억+ 전 종목", P.liq, SIG_BUY)):
            for rl, rg in (("없음", REG_ALL), ("밤갭 KOSPI120·KOSDAQ60 (이전)", REG_OLD), ("KOSPI>60일선", REG_KS60),
                           ("KOSDAQ>20일선 (이번)", REG_KQ20), ("둘 다", REG_OLD & REG_KQ20),
                           ("이전만 열림", REG_OLD & ~REG_KQ20), ("KOSDAQ20만 열림", ~REG_OLD & REG_KQ20)):
                m = sig & U & rg[:, None]
                s = pd.Series(np.where(m, GAP, np.nan).tolist(), index=P.dates).map(lambda v: np.nanmean(v) if np.isfinite(v).any() else np.nan) if False else \
                    pd.Series(np.nansum(np.where(m, GAP, 0), 1) / np.maximum(m.sum(1), 1), index=P.dates)[m.sum(1) > 0]
                print(line(stats(s[s.index >= "2016-01-01"], cost=0.0025, label=f"{uname}·{rl}")))

    if "C" in ONLY:
        print("\n======== C. 등급의 지속성 — 과거 3년 평균 순위 vs 다음 1년 평균 (종목 단위, 과거≥30·다음≥10건, 체결가능 신호, 비용전)")
        yrs = sorted(set(yr))
        for uname, U in (("등급표 종목", np.tile(OLD, (T, 1))), ("그때 시총 상위200", PIT_CAP), ("거래대금 10억+", P.liq)):
            rows = []
            for y in yrs[3:]:
                past = (yr >= y - 3) & (yr < y); fut = yr == y
                Ut = U[np.argmax(fut)]
                sp = SIG_BUY[past] & Ut; sf = SIG_BUY[fut] & Ut
                npst, nf = sp.sum(0), sf.sum(0)
                mp = np.where(sp, GAP[past], 0).sum(0) / np.maximum(npst, 1)
                mf = np.where(sf, GAP[fut], 0).sum(0) / np.maximum(nf, 1)
                ok = (npst >= 30) & (nf >= 10)
                if ok.sum() < 30:
                    continue
                a, b = pd.Series(mp[ok]), pd.Series(mf[ok])
                rho = a.rank().corr(b.rank())
                q = pd.qcut(a.rank(method="first"), 5, labels=False)
                fq = b.groupby(q.values).mean()
                rows.append((y, int(ok.sum()), rho, *(fq.values * 100)))
            D = pd.DataFrame(rows, columns=["연도", "종목", "rho", "Q1", "Q2", "Q3", "Q4", "Q5"])
            print(f"--- {uname}: 평균 rho {D['rho'].mean():+.3f} (양수 {int((D['rho']>0).sum())}/{len(D)}년) | 다음해 평균(비용전%): " +
                  " ".join(f"{c} {D[c].mean():+.2f}" for c in ["Q1", "Q2", "Q3", "Q4", "Q5"]))
            print(D.round(3).to_string(index=False))
