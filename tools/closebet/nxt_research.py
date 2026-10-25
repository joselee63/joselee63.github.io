"""종베 시황 판단기 연구 — 장 마감 뒤(NXT 애프터 15:40~20:00)에 알 수 있는 정보와 미국 이벤트가 밤수익에 주는 영향
python tools/closebet/nxt_research.py

1) 나스닥 선물 장 마감 뒤 흐름 (야후 60분봉, 최근 ~2년)
   A = 15:00→20:00 KST 변화 (NXT 애프터 마감 전에 보임) · B = 20:00→다음 거래일 08:00 (매수 뒤, 모름)
   - A와 B의 상관: 저녁 선물 흐름이 밤새 이어지나
   - 다음날 시가 갭(KRX 종가 대비)에 대한 A·B 기울기: 코스피, 삼성전자, SK하이닉스, 대형주 종베 후보, 전체 종베 후보
2) 종목별 '미국 민감도' β = 밤사이 나스닥100 1%당 다음날 시가 갭(직전 250거래일, 그날까지 아는 값)
   - 해마다 유지되나(종목 순위 상관), 종베 후보의 밤 위험을 가르나
3) 미국 이벤트 밤(그날 밤 FOMC 발표·CPI 발표) — 종베 밤수익 평균·변동성·최악 (2018~)
무편향 일봉(상폐 포함), 매수 t일 종가 · 매도 t+1 시가(거래정지·상폐 반영 = large_cap.RET), 비용 0.25%.
"""
import numpy as np
import pandas as pd
import yfinance as yf
import large_cap as L

P, T, N = L.P, L.T, L.N
G = L.G
dates = P.dates
COST = 0.0025
with np.errstate(invalid="ignore", divide="ignore"):
    GAP = np.vstack([P.o[1:] / P.c[:-1] - 1, np.full((1, N), np.nan)])   # t일 종가 → t+1 시가 (단순)
RET = L.RET
WIDE = L.FINAL & L.REG_KQ[:, None] if L.REG_KQ.ndim == 1 else L.FINAL & L.REG_KQ   # 전체 종베 후보(+3%·거래량2배·고가권·코스닥>20)
LARGEC = L.SIG3 & L.LARGE & (L.GP >= 0.8 - 1e-12)                                   # 대형주 등급 후보 (레짐 무관)
col = {t: i for i, t in enumerate(P.tickers)}
SS, HX = col["005930"], col["000660"]
ix = G.ix
kospi = ix[ix.index_code == "1001"].set_index("date")[["open", "close"]].reindex(dates)
KGAP = (kospi["open"].shift(-1) / kospi["close"] - 1).to_numpy()
start18 = dates >= pd.Timestamp("2018-01-01")


def pr(*a):
    print(*a, flush=True)


def port(mask):
    """날짜별 후보 평균 밤수익(비용 후)"""
    m = mask & np.isfinite(RET)
    s = np.where(m, RET, 0).sum(1); n = m.sum(1)
    with np.errstate(invalid="ignore"):
        return pd.Series(np.where(n > 0, s / np.maximum(n, 1) - COST, np.nan), index=dates)


def slope(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    b = np.cov(x, y)[0, 1] / np.var(x, ddof=1)
    r = np.corrcoef(x, y)[0, 1]
    e = y - y.mean() - b * (x - x.mean())
    se = np.sqrt(e.var(ddof=2) / ((x - x.mean()) ** 2).sum())
    return b, b / se, r, ok.sum()


# ------------------------------------------------------------------ 1) 장 마감 뒤 나스닥 선물
pr("=" * 100)
pr("1) 나스닥 선물(NQ=F 60분봉) — 장 마감 뒤 흐름이 다음날 시가를 얼마나 미리 보여주나")
d = yf.download("NQ=F", interval="60m", period="730d", progress=False, auto_adjust=False)
if isinstance(d.columns, pd.MultiIndex):
    d.columns = d.columns.get_level_values(0)
d.index = pd.to_datetime(d.index, utc=True).tz_convert("Asia/Seoul").tz_localize(None)
cl = d["Close"].dropna()
starts = cl.index.values


def px(ts, stale_h=4):
    """ts 시각에 아는 마지막 가격 = 시작 ≤ ts−1h 인 마지막 봉의 종가 (stale_h 시간 넘게 비면 NaN)"""
    k = np.searchsorted(starts, np.datetime64(ts - pd.Timedelta(hours=1)), side="right") - 1
    if k < 0 or (ts - pd.Timestamp(starts[k])) > pd.Timedelta(hours=stale_h):
        return np.nan
    return float(cl.iloc[k])


rows = []
for t in range(T - 1):
    day, nday = dates[t], dates[t + 1]
    if day < cl.index[0] + pd.Timedelta(days=1):
        continue
    p15, p20 = px(day + pd.Timedelta(hours=15)), px(day + pd.Timedelta(hours=20))
    p08, p09 = px(nday + pd.Timedelta(hours=8), 30), px(nday + pd.Timedelta(hours=9), 30)
    rows.append((t, p20 / p15 - 1, p08 / p20 - 1, p09 / p20 - 1))
X = pd.DataFrame(rows, columns=["t", "A", "B", "B9"]).dropna()
ti = X["t"].to_numpy()
pr(f"표본 {len(X)}일 ({dates[ti[0]].date()} ~ {dates[ti[-1]].date()}) · A 표준편차 {X.A.std()*100:.2f}% · B {X.B.std()*100:.2f}%")
b, tt, r, n = slope(X.A.to_numpy(), X.B.to_numpy())
pr(f"  A(15→20시) → B(20시→다음날 8시) 상관 {r:+.3f} (기울기 {b:+.2f}, t {tt:+.1f}) — 0에 가까우면 저녁 흐름은 밤새 이어지지 않음(예측력 없음)")
for lo, hi, lab in ((-1, -0.005, "A ≤ −0.5%"), (-0.005, 0.005, "|A| < 0.5%"), (0.005, 1, "A ≥ +0.5%")):
    g = X[(X.A > lo) & (X.A <= hi)]
    pr(f"     {lab:12} {len(g):3d}일 · 이후 B 평균 {g.B.mean()*100:+.2f}%")
# 견고성: 순위 상관, 앞/뒤 절반, 큰 날 제외, 요일(월요일 아침 = 주말 넘김)
pr(f"     순위 상관 {X.A.rank().corr(X.B.rank()):+.3f} · 앞 절반 {X.A[:len(X)//2].corr(X.B[:len(X)//2]):+.3f} · 뒤 절반 {X.A[len(X)//2:].corr(X.B[len(X)//2:]):+.3f}")
cut = X.A.abs().quantile(0.95)
xx = X[X.A.abs() < cut]
pr(f"     |A| 상위 5% 제외 상관 {xx.A.corr(xx.B):+.3f} · B 대신 20시→다음날 9시(B9) 상관 {X.A.corr(X.B9):+.3f}")
wk = np.array([dates[t].weekday() for t in ti])
pr(f"     평일 밤만 {X.A[wk < 4].corr(X.B[wk < 4]):+.3f} · 금요일 밤(주말 넘김) {X.A[wk == 4].corr(X.B[wk == 4]):+.3f}")
# 15시 이전(장중) 선물 흐름도 이어지나: 07→15시(C) vs 15→다음날 8시
rows2 = []
for t in ti:
    day = dates[t]
    p07, p15 = px(day + pd.Timedelta(hours=8), 6), px(day + pd.Timedelta(hours=15))
    rows2.append(p15 / p07 - 1)
X["C"] = rows2
xc = X.dropna(subset=["C"])
pr(f"     참고: 장중(8→15시) 선물 흐름 C → 이후(15시→다음날 8시 = A+B) 상관 {xc.C.corr((1+xc.A)*(1+xc.B)-1):+.3f} (기존 연구: 15시 값은 종베와 무관)")

targets = {
    "코스피 지수": KGAP[ti],
    "삼성전자": GAP[ti, SS],
    "SK하이닉스": GAP[ti, HX],
    "대형주 등급 후보(평균)": port(LARGEC).to_numpy()[ti] + COST,
    "전체 종베 후보(평균)": port(WIDE).to_numpy()[ti] + COST,
}
pr("\n  다음날 시가 갭(KRX 종가 대비, 비용 전) = a + bA·A + bB·B  (A·B 1%당 갭 %)")
pr(f"  {'대상':22} {'bA':>6} {'t':>5} {'bB':>6} {'t':>5} {'R²(A만)':>8} {'R²(A+B)':>8} {'일수':>5}")
for k, y in targets.items():
    ok = np.isfinite(y)
    Xm = np.column_stack([np.ones(ok.sum()), X.A.to_numpy()[ok], X.B.to_numpy()[ok]])
    yy = y[ok]
    beta, *_ = np.linalg.lstsq(Xm, yy, rcond=None)
    res = yy - Xm @ beta
    s2 = res.var(ddof=3); cov = s2 * np.linalg.inv(Xm.T @ Xm)
    r2 = 1 - res.var() / yy.var()
    ba, *_ = np.linalg.lstsq(Xm[:, :2], yy, rcond=None)
    r2a = 1 - (yy - Xm[:, :2] @ ba).var() / yy.var()
    pr(f"  {k:22} {beta[1]:+6.2f} {beta[1]/np.sqrt(cov[1,1]):5.1f} {beta[2]:+6.2f} {beta[2]/np.sqrt(cov[2,2]):5.1f} {r2a*100:7.1f}% {r2*100:7.1f}% {ok.sum():5d}")

# 대형주 종베: 저녁 선물이 크게 빠진 날 / 오른 날의 성적 (NXT에서 '오늘은 쉰다' 판단 가능성)
pl = port(LARGEC & L.REG_KQ[:, None] if L.REG_KQ.ndim == 1 else LARGEC & L.REG_KQ).to_numpy()[ti]
pw = port(WIDE).to_numpy()[ti]
pr("\n  저녁 선물(A) 구간별 다음날 시가 성적 (비용 후, 코스닥>20일선 날) — 다만 NXT 가격이 이미 A를 반영했다면 이 차이는 못 먹음")
for lo, hi, lab in ((-1, -0.005, "A ≤ −0.5%"), (-0.005, 0.005, "|A| < 0.5%"), (0.005, 1, "A ≥ +0.5%")):
    m = (X.A.to_numpy() > lo) & (X.A.to_numpy() <= hi)
    a1, a2 = pl[m], pw[m]
    pr(f"     {lab:12} 대형주 {np.isfinite(a1).sum():3d}일 {np.nanmean(a1)*100:+.2f}% · 전체 {np.isfinite(a2).sum():3d}일 {np.nanmean(a2)*100:+.2f}%  | 코스피 갭 {np.nanmean(KGAP[ti][m])*100:+.2f}%")

# ------------------------------------------------------------------ 2) 종목별 미국 민감도
pr("\n" + "=" * 100)
pr("2) 종목별 미국 민감도 β (밤사이 나스닥100 1%당 다음날 시가 갭, 직전 250거래일)")
nd = yf.download("^NDX", start="2014-06-01", progress=False, auto_adjust=False)
if isinstance(nd.columns, pd.MultiIndex):
    nd.columns = nd.columns.get_level_values(0)
ndc = nd["Close"].dropna(); ndc.index = pd.to_datetime(ndc.index).tz_localize(None)
ud = ndc.index.values


def last_us(day):                       # day 이전(day 미포함) 마지막 미국 세션 종가 (KST day 09:00 전에 끝난 세션)
    k = np.searchsorted(ud, np.datetime64(day), side="left") - 1
    return float(ndc.iloc[k]) if k >= 0 else np.nan


NIGHT = np.full(T, np.nan)
for t in range(T - 1):
    NIGHT[t] = last_us(dates[t + 1]) / last_us(dates[t]) - 1      # t일 15:30 → t+1 09:00 사이 끝난 미국 세션들
gapdf = pd.DataFrame(GAP, index=dates)
nser = pd.Series(NIGHT, index=dates)
mx = gapdf.mul(nser, axis=0)
okm = gapdf.notna() & nser.notna().to_numpy()[:, None]
cnt = okm.rolling(250, min_periods=150).sum()
sx = nser.where(okm.any(axis=1))
xm = okm.mul(nser, axis=0).rolling(250, min_periods=150).sum() / cnt
x2 = okm.mul(nser ** 2, axis=0).rolling(250, min_periods=150).sum() / cnt
ym = gapdf.where(okm).rolling(250, min_periods=150).sum() / cnt
xy = mx.where(okm).rolling(250, min_periods=150).sum() / cnt
BETA = ((xy - xm * ym) / (x2 - xm ** 2)).shift(1).to_numpy()      # t일에 아는 값 (t−1 밤까지)
bl = BETA[np.nonzero(dates >= pd.Timestamp("2026-10-01"))[0][0]]
pr(f"  예시(2026-10 초 β): 삼성전자 {bl[SS]:.2f} · SK하이닉스 {bl[HX]:.2f} · 대형주 중앙 {np.nanmedian(np.where(L.LARGE[-30], bl, np.nan)):.2f} · 전 종목 중앙 {np.nanmedian(bl):.2f}")
yr = dates.year.to_numpy()
ann = {}
for y in range(2016, 2027):
    m = yr == y
    if m.sum() < 150:
        continue
    g, nn = GAP[m], NIGHT[m]
    ok = np.isfinite(g) & np.isfinite(nn)[:, None]
    xs = np.where(ok, nn[:, None], np.nan); ys = np.where(ok, g, np.nan)
    with np.errstate(invalid="ignore"):
        bx = (np.nanmean(xs * ys, 0) - np.nanmean(xs, 0) * np.nanmean(ys, 0)) / (np.nanmean(xs ** 2, 0) - np.nanmean(xs, 0) ** 2)
    ann[y] = pd.Series(np.where(ok.sum(0) >= 150, bx, np.nan))
rc = [ann[y].rank().corr(ann[y + 1].rank()) for y in ann if y + 1 in ann]
pr(f"  해마다 β 순위 유지(작년 vs 올해 스피어만): 평균 {np.mean(rc):+.2f} (연도별 " + " ".join(f"{v:+.2f}" for v in rc) + ")")

pr("\n  종베 후보를 β 3분위로 나눠 밤사이 나스닥100에 대한 밤수익 기울기 (2018~, 비용 후)")
for nm, mask in (("전체 종베 후보", WIDE), ("대형주 등급 후보", LARGEC)):
    ii, jj = np.nonzero(mask & np.isfinite(RET) & np.isfinite(BETA) & start18[:, None] & np.isfinite(NIGHT)[:, None])
    bb, rr, nn = BETA[ii, jj], RET[ii, jj] - COST, NIGHT[ii]
    q = np.nanquantile(bb, [1 / 3, 2 / 3])
    pr(f"   {nm} ({len(ii):,}건, β 경계 {q[0]:.2f}/{q[1]:.2f})")
    for lab, m in (("β 낮음", bb <= q[0]), ("β 중간", (bb > q[0]) & (bb <= q[1])), ("β 높음", bb > q[1])):
        s_, t_, r_, n_ = slope(nn[m], rr[m])
        dn, up = m & (nn <= -0.015), m & (nn >= 0.015)
        pr(f"     {lab}: 평균 {rr[m].mean()*100:+.2f}% · 나스닥 1%당 {s_:+.2f}%(t {t_:.1f}) · 나스닥 −1.5%↓ 밤 {rr[dn].mean()*100:+.2f}%({dn.sum()}) · +1.5%↑ 밤 {rr[up].mean()*100:+.2f}%({up.sum()}) · 표준편차 {rr[m].std()*100:.2f}%")

# ------------------------------------------------------------------ 3) 미국 이벤트 밤
pr("\n" + "=" * 100)
pr("3) 미국 이벤트 밤 — 그날 밤(한국 시각) FOMC 발표·CPI 발표가 있는 날의 종베 (2018~)")
FOMC = """2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-03-03 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16""".split()
CPI = """2018-01-12 2018-02-14 2018-03-13 2018-04-11 2018-05-10 2018-06-12 2018-07-12 2018-08-10 2018-09-13 2018-10-11 2018-11-14 2018-12-12
2019-01-11 2019-02-13 2019-03-12 2019-04-10 2019-05-10 2019-06-12 2019-07-11 2019-08-13 2019-09-12 2019-10-10 2019-11-13 2019-12-11
2020-01-14 2020-02-13 2020-03-11 2020-04-10 2020-05-12 2020-06-10 2020-07-14 2020-08-12 2020-09-11 2020-10-13 2020-11-12 2020-12-10
2021-01-13 2021-02-10 2021-03-10 2021-04-13 2021-05-12 2021-06-10 2021-07-13 2021-08-11 2021-09-14 2021-10-13 2021-11-10 2021-12-10
2022-01-12 2022-02-10 2022-03-10 2022-04-12 2022-05-11 2022-06-10 2022-07-13 2022-08-10 2022-09-13 2022-10-13 2022-11-10 2022-12-13
2023-01-12 2023-02-14 2023-03-14 2023-04-12 2023-05-10 2023-06-13 2023-07-12 2023-08-10 2023-09-13 2023-10-12 2023-11-14 2023-12-12
2024-01-11 2024-02-13 2024-03-12 2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14 2024-09-11 2024-10-10 2024-11-13 2024-12-11
2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12 2025-09-11 2025-10-24 2025-12-18
2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14 2026-08-12 2026-09-11 2026-10-14""".split()


def evmask(lst):
    """미국 날짜 d의 발표(FOMC 14:00 ET·CPI 08:30 ET)는 한국 d일 밤 → d일(또는 d 직전 한국 거래일) 종가 매수분이 맞음"""
    m = np.zeros(T, bool)
    for s in lst:
        k = np.searchsorted(dates.values, np.datetime64(s), side="right") - 1    # d 이하 마지막 한국 거래일
        if k >= 0 and k + 1 < T and dates[k + 1] > pd.Timestamp(s):
            m[k] = True
    return m


EV = {"FOMC 발표 밤": evmask(FOMC), "CPI 발표 밤": evmask(CPI)}
EV["둘 중 하나"] = EV["FOMC 발표 밤"] | EV["CPI 발표 밤"]
regkq = L.REG_KQ if L.REG_KQ.ndim == 1 else L.REG_KQ.any(1)
series = {"대형주 등급(코스닥>20)": port(LARGEC & regkq[:, None]), "전체 종베(코스닥>20)": port(WIDE), "코스피 갭(매일)": pd.Series(KGAP, index=dates)}
for sn, s in series.items():
    v = s.to_numpy(); base = np.isfinite(v) & start18
    pr(f"  [{sn}]  보통 밤: {np.nanmean(v[base & ~EV['둘 중 하나']])*100:+.2f}% · 표준편차 {np.nanstd(v[base & ~EV['둘 중 하나']])*100:.2f}% ({(base & ~EV['둘 중 하나']).sum()}일)")
    for en, em in EV.items():
        m = base & em
        if m.sum() < 5:
            continue
        x = v[m]; o = v[base & ~em]
        tt = (x.mean() - o.mean()) / np.sqrt(x.var(ddof=1) / len(x) + o.var(ddof=1) / len(o))
        pr(f"     {en:10} {m.sum():3d}일 · 평균 {x.mean()*100:+.2f}% (차 t {tt:+.1f}) · 표준편차 {x.std()*100:.2f}% · −2%↓ 밤 {np.mean(x < -0.02)*100:.0f}% (보통 {np.mean(o < -0.02)*100:.0f}%) · 최악 {x.min()*100:+.1f}%")
