"""시황판 데이터 (사이트 market.html 이 읽는 market.json) — closebet.yml 이 매일 일봉 저장소 갱신 뒤 실행

입력: 일봉 저장소 STORE (ohlcv.npz · universe.csv · index.csv — tools/closebet/daily_data.py), 사이트 섹터 분류 stocks.py,
      나스닥100 일봉(야후 — 실패하면 '미국 연동 비대칭'만 빈칸)
출력: market.json — 세 계기(호재·악재 / 추세 지속 / 쏠림·순환) + 60일 장세 띠 + 섹터 히트맵 + ADR×지수 지도 + 일정

방법 메모 (연구: 2026-10-28, 상장폐지 포함 전 종목 2015~)
  · 모든 수치는 11년 기록 대비 백분위로 '평소'와 비교
  · 예고력 = 그 값과 '다음 주 같은 값'의 상관(5일 간격 비중첩) — ★★ 0.15↑·앞뒤 절반 모두 0.05↑, ★ 0.08↑, 참고 = 무관
    5일 값은 거의 안 이어져서(r≈0.1) 판정엔 20일 값을 쓰고 5일 값은 '최근 변화'로만 보여줌
  · ADR = 20일 상승 종목 수 합 ÷ 하락 종목 수 합 × 100 (시장별). 칸 = 지수 20일 등락 3분위 × ADR 20일 변화 3분위
사용: python tools/market/market_board.py STORE OUT.json
"""
import json, math, sys, datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import stocks  # noqa: E402

STORE = Path(sys.argv[1] if len(sys.argv) > 1 else "store")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "market.json")

FOMC = ["2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
        "2027-10-27", "2027-12-08"]                       # 연준 발표일 (미국 날짜) — tools/radar/radar.py 와 같은 목록
CPI = ["2026-11-10", "2026-12-10", "2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13", "2027-05-12", "2027-06-10",
       "2027-07-14", "2027-08-11", "2027-09-14", "2027-10-14", "2027-11-10", "2027-12-10"]   # BLS 발표일

# ---------------------------------------------------------------- 일봉 → 날짜×종목 행렬
z = np.load(STORE / "ohlcv.npz", allow_pickle=False)
tk = z["tickers"]; ti = z["ti"]; dd = z["d"]
dates = np.unique(dd); D = len(dates); N = len(tk)
di = np.searchsorted(dates, dd)
def mat(a):
    m = np.full((D, N), np.nan, np.float64); m[di, ti] = a; return m
O, H, L, C, V = mat(z["o"]), mat(z["h"]), mat(z["l"]), mat(z["c"]), mat(z["v"])
del z
for m in (O, H, L, C):
    m[m <= 0] = np.nan
V[np.isnan(C)] = np.nan
uni = pd.read_csv(STORE / "universe.csv", dtype={"ticker": str})
name = dict(zip(uni.ticker, uni.name)); mkt_of = dict(zip(uni.ticker, uni.market))
ix = pd.read_csv(STORE / "index.csv", dtype={"index_code": str}, parse_dates=["date"])
T = D - 1
ds = [str(x) for x in dates]
dts = pd.to_datetime(ds)
kx = ix.pivot(index="date", columns="index_code", values="close").sort_index()
print("일봉", D, "일", ds[0], "~", ds[-1], "· 종목", N)

with np.errstate(invalid="ignore", divide="ignore"):
    PC = np.vstack([np.full((1, N), np.nan), C[:-1]])
    RET = C / PC - 1; GAP = O / PC - 1; TV = C * V
    RET[(np.abs(RET) > 0.31) | ~(V > 0)] = np.nan
    LIQ = (TV >= 1e9) & np.isfinite(RET)
    mret = np.array([np.nanmean(np.clip(RET[t][LIQ[t]], -.3, .3)) if LIQ[t].sum() > 50 else 0.0 for t in range(D)])
MI = np.cumprod(1 + np.nan_to_num(mret))


def roll(a, w):
    c = np.cumsum(np.nan_to_num(a)); out = c.copy(); out[w:] = c[w:] - c[:-w]; out[:w - 1] = np.nan; return out
def back(x, l):
    o = np.full(x.shape, np.nan); o[l:] = x[:-l]; return o
def fwd(x, l):
    o = np.full(x.shape, np.nan); o[:-l] = x[l:]; return o
def fsum(a, w=5):
    c = np.concatenate([[0], np.cumsum(np.nan_to_num(a))]); out = np.full(D, np.nan)
    out[:D - w] = c[1 + w:] - c[1:D - w + 1]; return out
def f(x, n=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, n) if math.isfinite(x) else None
def series_pct(x):
    h = np.sort(x[np.isfinite(x)]); out = np.full(len(x), np.nan)
    if len(h) < 30:
        return out
    ok = np.isfinite(x); out[ok] = 100 * np.searchsorted(h, x[ok]) / len(h); return out
def med(x):
    h = x[np.isfinite(x)]; return f(np.median(h)) if len(h) else None
def lastn(x, n=60):
    return [f(v) for v in x[T - n + 1:T + 1]]


W = 5
# ---------------------------------------------------------------- 계기 1: 호재·악재 반응
with np.errstate(invalid="ignore", divide="ignore"):
    gu = LIQ & (GAP >= 0.03) & (RET < 0.3); gu_h = gu & (C > O)
    gd = LIQ & (GAP <= -0.03); gd_h = gd & (C > O)
    gu_n, gu_k = gu.sum(1).astype(float), gu_h.sum(1).astype(float)
    gd_n, gd_k = gd.sum(1).astype(float), gd_h.sum(1).astype(float)
    GU5 = roll(gu_k, W) / roll(gu_n, W); GD5 = roll(gd_k, W) / roll(gd_n, W)
    GU20 = roll(gu_k, 20) / roll(gu_n, 20); GD20 = roll(gd_k, 20) / roll(gd_n, 20)

# 미국 연동 비대칭 (나스닥100 밤 → 다음날 코스피·코스닥 평균 등락, 최근 20일)
ndr = None
try:
    p1 = int(dt.datetime(2014, 11, 1).timestamp()); p2 = int(dt.datetime.now().timestamp()) + 86400
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?period1={p1}&period2={p2}&interval=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) > 2000:
        ndr = s.pct_change()
    print("나스닥100", len(s), "일 ~", s.index.max().date())
except Exception as e:                                    # noqa: BLE001
    print("::warning::나스닥100 못 받음 →", e)
kret = kx.pct_change()
night = np.full(D, np.nan); kr = np.full(D, np.nan)
for t in range(1, D):
    if ndr is not None:
        j = np.searchsorted(ndr.index.values, dts[t].to_datetime64()) - 1      # 한국 날짜보다 앞선 마지막 미국 거래일
        if j >= 1 and ndr.index.values[j] > dts[t - 1].to_datetime64() - np.timedelta64(4, "D"):
            night[t] = ndr.values[j]
    if dts[t] in kret.index:
        kr[t] = np.nanmean(kret.loc[dts[t], ["1001", "2001"]].values)
def asym(t, w=20):
    a = night[t - w + 1:t + 1]; b = kr[t - w + 1:t + 1]; ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]; up, dn = a > 0, a < 0
    if up.sum() < 4 or dn.sum() < 4:
        return None
    return dict(nu=int(up.sum()), nd=int(dn.sum()), ku=f(b[up].mean()), kd=f(b[dn].mean()),
                bu=float(b[up].mean() / a[up].mean()), bd=float(b[dn].mean() / a[dn].mean()))
ASY = np.full(D, np.nan)
for t in range(30, D):
    a = asym(t)
    if a:
        ASY[t] = a["bu"] - a["bd"]

# ---------------------------------------------------------------- 계기 2: 추세 지속 vs 되밀림
with np.errstate(invalid="ignore", divide="ignore"):
    up5 = LIQ & (H / PC - 1 >= 0.05) & (H > L)
    clv = (C - L) / (H - L)
    hc = up5 & (clv >= 0.75); tail = up5 & ((H - C) / H >= 0.04)
    st = LIQ & (RET >= 0.05) & (RET < 0.3)
    stp = np.vstack([np.zeros((1, N), bool), st[:-1]])
    ex = RET - mret[:, None]
    fol = stp & np.isfinite(RET)
    up5_n = up5.sum(1).astype(float); hc_k = hc.sum(1).astype(float); tail_k = tail.sum(1).astype(float)
    fol_n = fol.sum(1).astype(float); fol_s = np.where(fol, ex, 0).sum(1)
    HC5 = roll(hc_k, W) / roll(up5_n, W); TL5 = roll(tail_k, W) / roll(up5_n, W); FOL5 = roll(fol_s, W) / roll(fol_n, W)
    HC20 = roll(hc_k, 20) / roll(up5_n, 20); TL20 = roll(tail_k, 20) / roll(up5_n, 20); FOL20 = roll(fol_s, 20) / roll(fol_n, 20)
del clv, ex, stp, st
Cd = pd.DataFrame(C)
MA20 = Cd.rolling(20, min_periods=20).mean().values
MA60 = Cd.rolling(60, min_periods=60).mean().values
HH = pd.DataFrame(H).rolling(250, min_periods=200).max().shift(1).values
V20 = pd.DataFrame(V).rolling(20, min_periods=15).mean().shift(1).values
with np.errstate(invalid="ignore", divide="ignore"):
    trend = (C > MA60) & (MA60 > back(MA60, 5))
    liq3 = (TV >= 3e9) & (C >= 1000)
    brk = trend & liq3 & (C > HH)
    brk = brk & ~pd.DataFrame(brk).rolling(20, min_periods=1).max().shift(1).fillna(0).values.astype(bool)
    came = Cd.rolling(5).max().shift(1).values >= MA20 * 1.05
    pb = trend & (MA20 > back(MA20, 5)) & came & liq3 & (L <= MA20 * 1.01) & (C >= MA20 * 0.98)
    pb = pb & ~pd.DataFrame(pb).rolling(10, min_periods=1).max().shift(1).fillna(0).values.astype(bool)
    F5 = np.full((D, N), np.nan)
    F5[:-5] = C[5:] / C[:-5] - 1 - (MI[5:] / MI[:-5] - 1)[:, None]
del HH, came, trend
def ev_sums(m):
    ok = m & np.isfinite(F5)
    return np.where(ok, F5, 0).sum(1), ok.sum(1).astype(float), (ok & (F5 > 0)).sum(1).astype(float)
bs, bn, bw = ev_sums(brk); ps_, pn, pw = ev_sums(pb)
def win20(a):                               # 신호일 t−24 ~ t−5 (5일 뒤 결과가 나온 최근 20일)
    r = roll(a, 20); out = np.full(D, np.nan); out[5:] = r[:-5]; return out
with np.errstate(invalid="ignore", divide="ignore"):
    BM = win20(bs) / win20(bn); PM = win20(ps_) / win20(pn)
    BWR = win20(bw) / win20(bn); PWR = win20(pw) / win20(pn)
BVP = BM - PM; BN20, PN20 = win20(bn), win20(pn)
with np.errstate(invalid="ignore", divide="ignore"):
    cb = (RET >= 0.03) & (RET < 0.285) & (V >= 2 * V20) & (C >= H * 0.99) & (TV >= 3e9)
    NG = np.full((D, N), np.nan); NG[:-1] = O[1:] / C[:-1] - 1
night_cb = np.array([np.nanmean(NG[t][cb[t]]) if (cb[t] & np.isfinite(NG[t])).sum() >= 1 else np.nan for t in range(D)])
cb_n = cb.sum(1)
CB10 = pd.Series(night_cb).rolling(10, min_periods=6).mean().values
del NG, V20

# ---------------------------------------------------------------- 계기 3: 쏠림 vs 순환
col = {t: i for i, t in enumerate(tk)}
SECS = []
for nm_, items in stocks.SECTIONS[3:]:
    idxs = [col[c] for c, _, _ in items if c in col]
    if len(idxs) >= 3:
        SECS.append((nm_, idxs, [(c, n) for c, n, _ in items if c in col]))
K = len(SECS)
SR = np.full((D, K), np.nan)
for k, (_, idxs, _) in enumerate(SECS):
    r_ = np.clip(RET[:, idxs], -.3, .3); cnt = np.isfinite(r_).sum(1)
    with np.errstate(invalid="ignore"):
        SR[:, k] = np.where(cnt >= 3, np.nanmean(r_, 1), np.nan)
SRd = pd.DataFrame(SR)
S5 = (1 + SRd.fillna(0)).rolling(5).apply(np.prod, raw=True).values - 1
S20 = (1 + SRd.fillna(0)).rolling(20).apply(np.prod, raw=True).values - 1
M5 = pd.Series(1 + mret).rolling(5).apply(np.prod, raw=True).values - 1
M20 = pd.Series(1 + mret).rolling(20).apply(np.prod, raw=True).values - 1
PERS = np.full(D, np.nan); OV5 = np.full(D, np.nan)
for t in range(30, D):
    a, b = S5[t], S5[t - 5]; ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() >= 15 and np.isfinite(SR[t]).sum() >= 15:
        PERS[t] = pd.Series(a[ok]).rank().corr(pd.Series(b[ok]).rank())
        ta = set(np.argsort(-np.nan_to_num(a, nan=-9))[:5]); tb = set(np.argsort(-np.nan_to_num(b, nan=-9))[:5])
        OV5[t] = len(ta & tb)
PERS5 = pd.Series(PERS).rolling(5, min_periods=3).mean().values
TOP10 = np.full(D, np.nan)
for t in range(D):
    v = TV[t][np.isfinite(TV[t])]
    if len(v) > 300:
        TOP10[t] = np.sort(v)[-10:].sum() / v.sum()
TOP10_5 = pd.Series(TOP10).rolling(5, min_periods=3).mean().values
ks_cols = [col[t] for t in tk if mkt_of.get(t) == "KOSPI"]
with np.errstate(invalid="ignore", divide="ignore"):
    R20 = np.full((D, N), np.nan); R20[20:] = C[20:] / C[:-20] - 1
    F20 = np.full((D, N), np.nan); F20[:-20] = C[20:] / C[:-20] - 1
    ksi = kx["1001"].reindex(dts).values
    KS20 = ksi / back(ksi, 20) - 1
    KSMED = np.nanmedian(R20[:, ks_cols], 1)
GAPIX = KS20 - KSMED
with np.errstate(invalid="ignore"):
    A20 = (C > MA20) & np.isfinite(MA20) & LIQ
BREADTH = A20.sum(1) / np.maximum(1, (LIQ & np.isfinite(MA20)).sum(1))
del A20, MA20, MA60

# ---------------------------------------------------------------- 예고력 · 백분위 · 판정
TS = np.arange(300, D - 6, 5); HALF = len(TS) // 2
def corr_ts(x, y, idx):
    a_, b_ = x[idx], y[idx]; ok = np.isfinite(a_) & np.isfinite(b_)
    return float(np.corrcoef(a_[ok], b_[ok])[0, 1]) if ok.sum() > 30 else float("nan")
def predict(x, y, what):
    r_ = corr_ts(x, y, TS); r1 = corr_ts(x, y, TS[:HALF]); r2 = corr_ts(x, y, TS[HALF:])
    star = 2 if (r_ >= 0.15 and min(r1, r2) >= 0.05) else 1 if r_ >= 0.08 else 0
    return dict(r=f(r_, 2), r1=f(r1, 2), r2=f(r2, 2), star=star, what=what)
with np.errstate(invalid="ignore", divide="ignore"):
    Y = dict(gu=fsum(gu_k) / fsum(gu_n), gd=fsum(gd_k) / fsum(gd_n), hc=fsum(hc_k) / fsum(up5_n), tl=fsum(tail_k) / fsum(up5_n),
             fol=fsum(fol_s) / fsum(fol_n), bvp=fsum(bs) / fsum(bn) - fsum(ps_) / fsum(pn),
             cb=fsum(np.nan_to_num(night_cb)) / fsum(np.isfinite(night_cb).astype(float)), pers=fwd(PERS, 5))
PR = dict(
    GU20=predict(GU20, Y["gu"], "다음 주 갭상승 유지율"), GD20=predict(GD20, Y["gd"], "다음 주 갭하락 회복률"),
    ASY=predict(ASY, fwd(ASY, 20), "다음 20일 비대칭"),
    HC20=predict(HC20, Y["hc"], "다음 주 고가권 마감률"), TL20=predict(TL20, Y["tl"], "다음 주 윗꼬리율"),
    FOL20=predict(FOL20, Y["fol"], "다음 주 강세 다음날"), BVP=predict(BVP, Y["bvp"], "다음 주 돌파−눌림"),
    CB10=predict(CB10, Y["cb"], "다음 주 종베 갭"),
    PERS5=predict(PERS5, Y["pers"], "다음 주 섹터 순위 유지"), OV5=predict(OV5, fwd(OV5, 5), "다음 주 상위 섹터 유지"),
    BREADTH=predict(BREADTH, Y["pers"], "다음 주 섹터 순위 유지"),
    TOP10_5=predict(TOP10_5, Y["pers"], "다음 주 섹터 순위 유지"), GAPIX=predict(GAPIX, Y["pers"], "다음 주 섹터 순위 유지"),
)
P = {k: series_pct(v) for k, v in dict(GU20=GU20, GD20=GD20, ASY=ASY, HC20=HC20, TL20=TL20, FOL20=FOL20, BVP=BVP,
                                         CB10=CB10, PERS5=PERS5, OV5=OV5, TOP10_5=TOP10_5, GAPIX=GAPIX, BREADTH=BREADTH).items()}
kqs = kx["2001"].reindex(dts).values
STEP = np.full(D, np.nan)                     # 코스닥 계단 비중 (20·40·60·90·120일선 하나 깰 때마다 −20%)
for t in range(130, D):
    STEP[t] = 100 - 20 * sum(1 for w in (20, 40, 60, 90, 120) if kqs[t] < np.nanmean(kqs[t - w + 1:t + 1]))
S1 = P["GU20"]
with np.errstate(invalid="ignore"):
    S2 = np.nanmean(np.vstack([P["HC20"], P["FOL20"], P["BVP"]]), 0)
S3 = P["BREADTH"]
def v1(t):
    w, p = STEP[t], S1[t]
    if w <= 40:
        return "방어", ("호재엔 반응 → 재료주만 짧게" if p >= 60 else "호재도 안 먹힘 → 쉬기" if p <= 40 else "확인 후 소량")
    if w >= 80:
        return ("공격", "추세 위 + 호재 반응") if p >= 40 else ("보통", "추세는 위, 호재 반응은 약함")
    return "보통", ("호재엔 반응" if p >= 60 else "호재 반응 약함" if p <= 40 else "평범")
def v2(t):
    hc_, fo, bv = P["HC20"][t], P["FOL20"][t], P["BVP"][t]
    if bv >= 80 and fo < 50:
        return "눌림 금지", "눌림 매수가 연달아 실패(떨어지는 칼날) · 강세도 다음날 약함 → 확인 후 짧게"
    if bv >= 70 and hc_ <= 40:
        return "돌파만 소량", "눌림 매수가 특히 나쁨 (떨어지는 칼날)"
    if hc_ >= 60 and fo >= 50:
        return "불타기", "고가에 마감하고 다음날도 이어짐"
    if hc_ <= 40 and fo <= 50:
        return "눌림 대기", "오르면 밀림 → 싸게 기다리기"
    return "중립", "뚜렷한 스타일 없음"
def v3(t):
    p = S3[t]
    if p >= 60: return "주도 집중", "폭 넓은 장 → 주도 섹터가 이어질 확률↑"
    if p <= 40: return "순환·대기", "폭 좁은 장 → 주도 섹터가 자주 뒤집힘. 추격보다 쉬는 섹터를 낮게"
    return "혼합", "주도 유지와 순환이 섞임"
def metric(key, x, label, unit, desc, recent=None, win="20일"):
    return dict(key=key, label=label, unit=unit, desc=desc, win=win, v=f(x[T]), v5=f(x[T - 5]),
                rec=f(recent[T]) if recent is not None else None, med=med(x), pct=f(P[key][T], 1),
                pred=PR.get(key), spark=lastn(x))

vt1, vt2, vt3 = v1(T), v2(T), v3(T)
G1 = dict(score=f(S1[T], 1), score5=f(S1[T - 5], 1), verdict=vt1[0], sub=vt1[1], step=f(STEP[T], 0), step5=f(STEP[T - 5], 0), metrics=[
    metric("GU20", GU20, "갭상승 유지율", "%", "시가 +3%↑로 출발한 종목 중 종가가 시가 위에서 끝난 비율 — 호재를 사주는가", GU5),
    metric("GD20", GD20, "갭하락 회복률", "%", "시가 −3%↓로 출발한 종목 중 종가가 시가 위로 회복한 비율 — 악재를 받아주는가", GD5),
    metric("ASY", ASY, "미국 연동 비대칭", "배", "나스닥 오른 밤 따라 오르는 정도 − 빠진 밤 따라 빠지는 정도. 음수면 악재에만 반응"),
], asym=asym(T), n_gu=int(gu_n[T]), n_gd=int(gd_n[T]))
G2 = dict(score=f(S2[T], 1), score5=f(S2[T - 5], 1), verdict=vt2[0], sub=vt2[1], metrics=[
    metric("HC20", HC20, "고가권 마감률", "%", "장중 +5%↑ 간 종목 중 그날 범위 위쪽 1/4에서 끝난 비율", HC5),
    metric("TL20", TL20, "윗꼬리율", "%", "장중 +5%↑ 간 종목 중 고가에서 4%↑ 밀려 끝난 비율", TL5),
    metric("FOL20", FOL20, "강세 다음날 (시장 대비)", "%", "전날 +5%↑ 오른 종목의 다음날 평균 등락 − 시장 평균", FOL5),
    metric("BVP", BVP, "돌파 − 눌림 성적차", "%", "최근 20일 신호: 신고가 돌파 매수 vs 20일선 눌림 매수, 5일 뒤 시장 대비 성적 차이"),
    metric("CB10", CB10, "종베형 후보 다음날 갭", "%", "+3%↑·거래량 2배·고가권 마감 후보의 다음날 시가 갭 평균 (단순화 규칙)", win="10밤"),
], bo=dict(m=f(BM[T]), w=f(BWR[T], 3), n=int(np.nan_to_num(BN20[T]))), pb=dict(m=f(PM[T]), w=f(PWR[T], 3), n=int(np.nan_to_num(PN20[T]))),
   bo_med=med(BM), pb_med=med(PM))
G3 = dict(score=f(S3[T], 1), score5=f(S3[T - 5], 1), verdict=vt3[0], sub=vt3[1], metrics=[
    metric("BREADTH", BREADTH, "20일선 위 종목 비율", "%", "거래대금 10억↑ 종목 중 종가가 20일선 위인 비율 — 시장의 폭", win="당일"),
    metric("PERS5", PERS5, "섹터 순위 지속성", "", "이번 5일 섹터 순위와 직전 5일 순위의 상관. +면 주도 섹터 유지, −면 뒤집힘", win="5일"),
    metric("OV5", OV5, "상위 5개 섹터 유지 수", "개", "직전 5일 상위 5개 섹터 중 이번 5일에도 상위 5에 남은 수", win="5일"),
    metric("TOP10_5", TOP10_5, "거래대금 상위 10종목 비중", "%", "전체 거래대금 중 상위 10종목 몫. 높으면 대형주 몇 개가 시장을 좌우", win="5일"),
    metric("GAPIX", GAPIX, "코스피 − 종목 중앙값", "%", "코스피 20일 등락 − 코스피 종목 20일 등락 중앙값. +면 지수만 오름, −면 대형주가 더 빠짐", win="20일"),
], conc=f(P["TOP10_5"][T], 1))
band = dict(dates=ds[T - 59:T + 1], s1=lastn(S1), s2=lastn(S2), s3=lastn(S3), step=lastn(STEP),
            v1=[v1(t)[0] for t in range(T - 59, T + 1)], v2=[v2(t)[0] for t in range(T - 59, T + 1)],
            v3=[v3(t)[0] for t in range(T - 59, T + 1)])

# ---------------------------------------------------------------- 사례 (마지막 날)
def nm(i): return name.get(tk[i], tk[i])
def ex_list(mask, n=5):
    idx = sorted(np.where(mask)[0], key=lambda i: -np.nan_to_num(TV[T, i]))[:n]
    return [dict(c=tk[i], n=nm(i), gap=f(GAP[T, i] * 100, 1), ret=f(RET[T, i] * 100, 1),
                 hi=f((H[T, i] / PC[T, i] - 1) * 100, 1), tv=f(TV[T, i] / 1e8, 0)) for i in idx]
ex1 = dict(gu_hold=ex_list(gu_h[T]), gu_fail=ex_list(gu[T] & ~gu_h[T]), gd_rec=ex_list(gd_h[T]), gd_fail=ex_list(gd[T] & ~gd_h[T]))
ex2 = dict(hc=ex_list(hc[T]), tail=ex_list(tail[T]))
cb_nights = [dict(d=ds[t], n=int(cb_n[t]), g=f(night_cb[t] * 100, 2)) for t in range(T - 10, T)]
_o = np.argsort(-np.nan_to_num(TV[T]))[:5]
toptv = [dict(n=nm(i), tv=f(TV[T, i] / 1e12, 2), ret=f(RET[T, i] * 100, 1)) for i in _o]
tvsum = f(np.nansum(TV[T]) / 1e12, 1)

# ---------------------------------------------------------------- 섹터 히트맵
heat = []
for k, (nmS, idxs, mem) in enumerate(SECS):
    r5m = [(c, n, f((C[T, col[c]] / C[T - 5, col[c]] - 1) * 100, 1), f(RET[T, col[c]] * 100, 1)) for c, n in mem]
    part = [x for x in r5m if x[2] is not None]
    heat.append(dict(n=nmS, d=[f(v * 100, 2) for v in SR[T - 19:T + 1, k]], r5=f(S5[T, k] * 100, 2), r20=f(S20[T, k] * 100, 2),
                     rel5=f((S5[T, k] - M5[T]) * 100, 2), rel20=f((S20[T, k] - M20[T]) * 100, 2),
                     part=f(100 * sum(1 for x in part if x[2] > 0) / len(part), 0) if part else None,
                     mem=[dict(c=c, n=n, r5=a, r1=b) for c, n, a, b in sorted(r5m, key=lambda x: -(x[2] if x[2] is not None else -99))]))
nxt = [k for k in sorted(range(K), key=lambda k: -((S20[T, k] - M20[T]) if np.isfinite(S20[T, k]) else -9))
       if np.isfinite(S5[T, k]) and S5[T, k] - M5[T] < 0 and S20[T, k] - M20[T] > 0][:5]
tops = [int(np.nanargmax(np.where(np.isfinite(SR[t]), SR[t], -9))) for t in range(T - 9, T + 1)]
G3.update(heat_dates=ds[T - 19:T + 1], heat=heat, next=[SECS[k][0] for k in nxt], tops=[SECS[k][0] for k in tops],
          mkt5=f(M5[T] * 100, 2), mkt20=f(M20[T] * 100, 2))

# ---------------------------------------------------------------- ADR(등락비율) × 지수
yrs = np.array([int(x[:4]) for x in ds])
LAB = {(2, 0): "대형주 쏠림 상승", (2, 1): "대형주 주도 상승", (2, 2): "고른 상승",
       (1, 0): "숨은 약세", (1, 1): "보합", (1, 2): "중소형 강세",
       (0, 0): "전부 하락", (0, 1): "지수 하락 · 폭은 버팀", (0, 2): "대형주만 하락 · 중소형 버팀"}
fPERS = fwd(PERS, 5)
ADRJ = {}
for code, mname in (("1001", "KOSPI"), ("2001", "KOSDAQ")):
    cols = np.array([mkt_of.get(t) == mname for t in tk])
    r_ = RET[:, cols]
    adv = (r_ > 0).sum(1).astype(float); dec = (r_ < 0).sum(1).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        ADR = roll(adv, 20) / roll(dec, 20) * 100
        I = kx[code].reindex(dts).values
        I20 = I / back(I, 20) - 1; fI20 = fwd(I, 20) / I - 1
        MED20 = np.nanmedian(R20[:, cols], 1); fMED20 = np.nanmedian(F20[:, cols], 1)
        dA = ADR - back(ADR, 20)
    tv60 = pd.DataFrame(TV[:, cols]).rolling(60, min_periods=40).mean().values
    BIG = np.full(D, np.nan); SMALL = np.full(D, np.nan)
    rr = R20[:, cols]
    for t in range(80, D):
        v = tv60[t]; ok = np.isfinite(v)
        if ok.sum() < 200: continue
        thr = np.sort(v[ok])[-50]
        BIG[t] = np.nanmedian(rr[t][ok & (v >= thr)]); SMALL[t] = np.nanmedian(rr[t][ok & (v < thr)])
    okd = np.arange(D) >= 140
    qi = np.nanquantile(I20[okd], [1 / 3, 2 / 3]); qa = np.nanquantile(dA[okd], [1 / 3, 2 / 3])
    ci = np.where(I20 <= qi[0], 0, np.where(I20 >= qi[1], 2, 1)); ca = np.where(dA <= qa[0], 0, np.where(dA >= qa[1], 2, 1))
    valid = okd & np.isfinite(I20) & np.isfinite(dA)
    base = valid & np.isfinite(fMED20)
    bm, bi = np.nanmean(fMED20[base]), np.nanmean(fI20[base])
    cells = []
    for i in range(3):
        for a in range(3):
            msk = valid & (ci == i) & (ca == a)
            ys = []
            for yy in range(int(yrs[0]), int(yrs[-1]) + 1):
                mm = msk & (yrs == yy) & np.isfinite(fMED20); rest = ~msk & valid & (yrs == yy) & np.isfinite(fMED20)
                if mm.sum() >= 10 and rest.sum() >= 10: ys.append(np.mean(fMED20[mm]) - np.mean(fMED20[rest]))
            g = lambda x: np.nanmean(x[msk]) if msk.sum() else np.nan
            cells.append(dict(i=i, a=a, lab=LAB[(i, a)], n=int(msk.sum()), I20=f(g(I20) * 100, 1), MED=f(g(MED20) * 100, 1),
                              BS=f(g(BIG - SMALL) * 100, 1), fMED=f((g(fMED20) - bm) * 100, 2), fI=f((g(fI20) - bi) * 100, 2),
                              fPERS=f(g(fPERS), 3), yp=sum(1 for v in ys if v > 0), yn=len(ys)))
    ADRJ[mname] = dict(adr=f(ADR[T], 1), adr20=f(ADR[T - 20], 1), dA=f(dA[T], 1), I20=f(I20[T] * 100, 1), MED20=f(MED20[T] * 100, 1),
                       BS=f((BIG[T] - SMALL[T]) * 100, 1), ci=int(ci[T]), ca=int(ca[T]), qi=[f(v * 100, 1) for v in qi], qa=[f(v, 1) for v in qa],
                       spark=lastn(ADR), cells=cells)
    print(f"ADR {mname}: {ADR[T]:.1f} (20일 전 {ADR[T - 20]:.1f}) · 칸 {LAB[(int(ci[T]), int(ca[T]))]}")

# ---------------------------------------------------------------- 지수 · 배지 · 일정
def ixrow(code, nmI):
    s = kx[code].dropna()
    return dict(n=nmI, c=f(s.iloc[-1], 2), d1=f((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2),
                d5=f((s.iloc[-1] / s.iloc[-6] - 1) * 100, 2), d20=f((s.iloc[-1] / s.iloc[-21] - 1) * 100, 2),
                mas={str(w): f(s.iloc[-w:].mean(), 2) for w in (20, 40, 60, 90, 120)})
IDX = [ixrow("1001", "코스피"), ixrow("2001", "코스닥")]
kq = IDX[1]; below = [w for w in (20, 40, 60, 90, 120) if kq["c"] < kq["mas"][str(w)]]
asof = dt.datetime.strptime(ds[T], "%Y%m%d").date()
ks1 = IDX[0]["d1"] or 0
WD = "월화수목금토일"
def us_dst(d):                                  # 미국 서머타임 (3월 둘째 일요일 ~ 11월 첫째 일요일)
    mar = dt.date(d.year, 3, 8); mar += dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.date(d.year, 11, 1); nov += dt.timedelta(days=(6 - nov.weekday()) % 7)
    return mar <= d < nov
def lab(d, hhmm=None):
    return f"{d.month}/{d.day}({WD[d.weekday()]})" + (f" {hhmm}" if hhmm else "")
cal = []
for s in FOMC:
    d = dt.date.fromisoformat(s)
    k = d + dt.timedelta(days=1)
    cal.append((k, lab(k, "03:00" if us_dst(d) else "04:00"), "FOMC 금리 결정", "발표 전날 밤 종베 절반 (일부 근거)", s))
for s in CPI:
    d = dt.date.fromisoformat(s)
    cal.append((d, lab(d, "21:30" if us_dst(d) else "22:30"), "미국 CPI", "", s))
for y, m in ((asof.year + (asof.month + i - 1) // 12, (asof.month + i - 1) % 12 + 1) for i in range(0, 3)):
    d = dt.date(y, m, 1); d += dt.timedelta(days=(3 - d.weekday()) % 7 + 7)        # 둘째 목요일
    cal.append((d, lab(d), "옵션 만기일", "종베 −0.5배 (일부 근거)", None))
    d1 = dt.date(y, m, 1)
    pm = (d1 - dt.timedelta(days=1)).month
    cal.append((d1, lab(d1), f"{pm}월 수출입 동향", "반도체 수출 확인", None))
cal = sorted([c for c in cal if asof < c[0] <= asof + dt.timedelta(days=35)], key=lambda c: c[0])[:6]
fomc_soon = next((c for c in cal if c[2].startswith("FOMC") and (c[0] - asof).days <= 3), None)
badges = [
    dict(t=f"코스닥 20일선 {'아래' if 20 in below else '위'}", light="r" if 20 in below else "g", tag="검증됨",
         d=f"코스닥 {kq['c']:.2f} · 20일선 {kq['mas']['20']:.2f} — 종가베팅 시장 필터"),
    dict(t=f"계단 비중 {max(0, 100 - 20 * len(below))}%", light="r" if len(below) >= 3 else "y" if below else "g", tag="검증됨",
         d="코스닥이 " + (", ".join(f"{w}일선" for w in below) or "모든 이평선") + (" 아래" if below else " 위") + " → 하나 깰 때마다 −20%"),
    dict(t="패닉일" if ks1 <= -4 else "패닉일 아님", light="r" if ks1 <= -4 else "g", tag="검증됨",
         d="코스피 종가 −4%↓ 날 삼전·하닉 종가 매수 → 다음날 +1.97% (35일)"),
]
if fomc_soon:
    badges.insert(2, dict(t=f"FOMC 발표 {fomc_soon[1]}", light="y", tag="일부 근거",
                          d="FOMC 발표 밤 종베 약세(전체 −0.22% vs +0.19%) → 그날 밤 종베 비중 절반"))

# 뉴스 반응용 (tools/market/news_board.py 가 읽음): 섹터 구성 종목·섹터의 최근 25거래일 등락(%) · 최근 90거래일 날짜
NP = 25
mem_codes = sorted({c for _, _, mem in SECS for c, _ in mem})
px = dict(dates=ds[T - NP + 1:T + 1],
          stock={c: [f(v * 100, 2) for v in RET[T - NP + 1:T + 1, col[c]]] for c in mem_codes},
          sector={nmS: [f(v * 100, 2) for v in SR[T - NP + 1:T + 1, k]] for k, (nmS, _, _) in enumerate(SECS)},
          members={nmS: [[c, n] for c, n in mem] for nmS, _, mem in SECS})

out = dict(asof=ds[T], built=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
           idx=IDX, badges=badges, cal=[dict(d=c[1], t=c[2], note=c[3]) for c in cal],
           G1=G1, G2=G2, G3=G3, band=band, ex1=ex1, ex2=ex2, cb_nights=cb_nights, toptv=toptv, tvsum=tvsum, adr=ADRJ,
           sessions=ds[-90:], px=px)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
print(f"market.json {OUT.stat().st_size:,} bytes · 기준일 {ds[T]} · 판정 {vt1[0]} / {vt2[0]} / {vt3[0]}")
