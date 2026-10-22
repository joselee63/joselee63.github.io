"""종가베팅 연구 공통 — 기준선 신호, 날짜·종목 특성(point-in-time), 평가 도구.

기준선 (docs/alpha-research.md·기존 연구와 동일):
  당일 +3%↑ · 거래량 20일 평균 2배↑ · 고가권 마감(pos≥0.7) · KOSPI>60일선 · 20일 평균 거래대금 10억↑
  · 상장 261일+ · 체결 가능(당일 +28.5% 미만) → '고가권 순 → 등락률 순' 상위 k, 다음날 시가 매도.

시점 규칙
  · 매수 판단(t일 15:20): t일 장중 값(종가 근사), t−1일까지의 모든 값, 미국은 t일 '이전' 미국 세션 종가까지.
  · t일 밤 미국 세션(US date = t)과 t+1 시가 갭은 '매도 판단'에만 쓴다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
from common import (BT, COST_KR, load_panel, overnight_pool, nw_t, roll)  # noqa: E402,F401

CB = ROOT / "data-closebet"


# ------------------------------------------------------------------ 기준선 후보 (전체 풀 + 순위)
def candidates(P, extra_mask=None, mkt_filter=True, need_next=True):
    """기준선 풀의 모든 후보 → DataFrame(i, j, rank(0=1등), pos, day, on, oc(다음날 종가까지), ...)
    mkt_filter=False 이면 KOSPI>60일선 조건을 빼고(따로 평가할 수 있게) mkt_ok 열을 남김"""
    with np.errstate(invalid="ignore"):
        strong = (P.day >= 0.03) & (P.v > 2 * P.v20)
        core = strong & (P.pos >= 0.7) & P.liq & np.isfinite(P.sd60) & (P.run >= 261) & (P.day < 0.285)
        if mkt_filter:
            core &= P.mkt_ok[:, None]
    nxt_o = np.vstack([P.o[1:], np.full((1, P.N), np.nan)])
    nxt_c = np.vstack([P.c[1:], np.full((1, P.N), np.nan)])
    nxt_h = np.vstack([P.h[1:], np.full((1, P.N), np.nan)])
    nxt_l = np.vstack([P.l[1:], np.full((1, P.N), np.nan)])
    on = nxt_o / P.c - 1
    if need_next:
        core &= np.isfinite(on)
    if extra_mask is not None:
        core &= extra_mask
    ii, jj = np.nonzero(core)
    df = pd.DataFrame({"i": ii, "j": jj, "pos": P.pos[ii, jj], "day": P.day[ii, jj], "on": on[ii, jj],
                       "oc": (nxt_c / P.c - 1)[ii, jj],           # 종가→다음날 종가
                       "nh": (nxt_h / P.c - 1)[ii, jj], "nl": (nxt_l / P.c - 1)[ii, jj],
                       "mkt_ok": P.mkt_ok[ii]})
    df["oc"] = df["oc"].fillna(df["on"])                          # 다음날 종가 없으면(정지) 시가로
    df = df.sort_values(["i", "pos", "day"], ascending=[True, False, False])
    df["rank"] = df.groupby("i").cumcount()
    df["npool"] = df.groupby("i")["i"].transform("size")
    df["date"] = P.dates[df["i"].to_numpy()]
    df["ticker"] = P.tickers[df["j"].to_numpy()]
    return df.reset_index(drop=True)


def daily(df, k=3, col="on", weight=None):
    """상위 k (rank<k) 동일가중 날짜별 평균 수익률(비용 전)"""
    d = df[df["rank"] < k] if k else df
    if weight is None:
        s = d.groupby("date")[col].mean()
    else:
        w = d[weight]
        s = (d[col] * w).groupby(d["date"]).sum() / w.groupby(d["date"]).sum()
    return s


def stats(s, cost=COST_KR, label="", base_days=None):
    """날짜별 포트폴리오 수익(비용 전) → 요약 dict"""
    s = s.dropna()
    if len(s) < 20:
        return dict(label=label, days=len(s))
    net = s - cost
    med = s.index[len(s) // 2]
    ym = net.groupby(s.index.year).mean()
    r = dict(label=label, days=len(s), net=net.mean(), t=nw_t(s.to_numpy(), 1), win=(net > 0).mean(),
             p1=np.percentile(net, 1), worst=net.min(), first=net[net.index <= med].mean(),
             second=net[net.index > med].mean(), yrpos=int((ym > 0).sum()), yrn=len(ym),
             sumnet=net.sum())
    r["years"] = " ".join(f"{str(y)[2:]}:{v*100:+.2f}" for y, v in ym.items())
    return r


def line(r, years=False):
    if r.get("net") is None:
        return f"{r['label']:44} 일수 {r['days']:5d} (표본 부족)"
    s = (f"{r['label']:44} 일수 {r['days']:5d} 비용후 {r['net']*100:+6.2f}% t={r['t']:5.2f} 승 {r['win']*100:3.0f}% "
         f"하위1% {r['p1']*100:+6.1f}% 최악 {r['worst']*100:+6.1f}% 앞/뒤 {r['first']*100:+.2f}/{r['second']*100:+.2f} "
         f"연도+ {r['yrpos']}/{r['yrn']} 누적 {r['sumnet']*100:+5.0f}%")
    if years:
        s += "\n" + " " * 46 + r["years"]
    return s


def diff_t(a, b):
    """두 날짜 집합의 평균 차이 Welch t"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 10 or len(b) < 10:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


# ------------------------------------------------------------------ 매크로 (미국 등) 정렬
def macro_frame(P):
    """KR 거래일 t 마다:
      *_prev : t일 15:20 이전에 끝난 마지막 해외 세션의 일간 수익률 (매수 판단에 사용 가능)
      *_night: t일 밤 해외 세션(다음 KR 거래일 개장 전 종료) 수익률 (매도 판단에만)
      vix_lvl: 직전 VIX 종가, krw_prev: 직전 원/달러 변화"""
    m = pd.read_csv(CB / "macro.csv", parse_dates=["date"])
    kd = pd.Series(P.dates)
    out = pd.DataFrame(index=P.dates)
    nxt = kd.shift(-1).fillna(kd.iloc[-1] + pd.Timedelta(days=1)).to_numpy()
    for key in ("spx", "ndx", "sox", "vix", "nq", "es", "ewy", "krw", "nk", "us10y"):
        x = m[m["key"] == key].dropna(subset=["close"]).set_index("date")["close"].sort_index()
        r = x.pct_change()
        # 마지막 세션 '날짜 < t' (해외 세션 date 는 현지 날짜; 미국 세션은 KR 다음날 새벽 종료)
        pos_prev = x.index.searchsorted(kd.to_numpy(), side="left") - 1
        pos_next = x.index.searchsorted(nxt, side="left") - 1
        cp = np.where(pos_prev >= 0, x.to_numpy()[np.maximum(pos_prev, 0)], np.nan)
        cn = np.where(pos_next >= 0, x.to_numpy()[np.maximum(pos_next, 0)], np.nan)
        rp = np.where(pos_prev >= 0, r.to_numpy()[np.maximum(pos_prev, 0)], np.nan)
        if key == "krw":
            # 환율 일봉은 시점이 애매 → 하루 더 늦춘 값만 매수 판단에 사용
            rp = np.where(pos_prev >= 1, r.to_numpy()[np.maximum(pos_prev - 1, 0)], np.nan)
        if key == "nk":
            # 닛케이는 같은 날 15:00 마감(한국 15:20 이전) → 당일 값 사용 가능
            pos_same = x.index.searchsorted(kd.to_numpy(), side="right") - 1
            rp = np.where(pos_same >= 0, r.to_numpy()[np.maximum(pos_same, 0)], np.nan)
        out[f"{key}_prev"] = rp
        out[f"{key}_night"] = np.where(pos_next > pos_prev, cn / cp - 1, 0.0)
        if key in ("vix", "us10y"):
            out[f"{key}_lvl"] = cp
    return out


# ------------------------------------------------------------------ 시장(날짜) 특성
def market_frame(P):
    """t일 장 마감 기준 시장 특성 (모두 t일 종가 근사 = 15:20 시점에 관찰 가능한 값)"""
    ix = pd.read_csv(BT / "sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
    out = pd.DataFrame(index=P.dates)
    for code, nm in (("1001", "ks"), ("2001", "kq")):
        x = ix[ix["index_code"] == code].set_index("date").reindex(P.dates)
        c = x["close"].ffill()
        out[f"{nm}_ret"] = c.pct_change()
        out[f"{nm}_oc"] = x["close"] / x["open"] - 1                       # 장중 흐름
        rng = (x["high"] - x["low"]).replace(0, np.nan)
        out[f"{nm}_pos"] = (x["close"] - x["low"]) / rng                     # 지수 마감 위치
        out[f"{nm}_rebound"] = (x["close"] - x["low"]) / x["open"]           # 저점 대비 반등폭
        out[f"{nm}_ma20"] = c / c.rolling(20).mean() - 1
        out[f"{nm}_ma60"] = c / c.rolling(60).mean() - 1
        out[f"{nm}_r5"] = c.pct_change(5)
        out[f"{nm}_dd"] = c / c.rolling(60).max() - 1
    live = np.isfinite(P.c) & np.isfinite(P.prev) & (P.run >= 20)
    with np.errstate(invalid="ignore"):
        up = (P.day > 0) & live
        dn = (P.day < 0) & live
        out["adv_ratio"] = up.sum(1) / np.maximum((up | dn).sum(1), 1)
        out["n_up5"] = ((P.day >= 0.05) & live).sum(1)
        out["n_dn5"] = ((P.day <= -0.05) & live).sum(1)
        out["n_limit"] = ((P.day >= 0.285) & live).sum(1)
        out["n_hi52"] = ((P.c >= P.hi252) & live).sum(1)
        out["n_live"] = live.sum(1)
        amt = np.where(live, P.amt, 0)
        tot = amt.sum(1)
        top10 = -np.sort(-amt, axis=1)[:, :10].sum(1)
        out["amt_top10"] = top10 / np.maximum(tot, 1)
        out["amt_tot_rel"] = tot / pd.Series(tot).rolling(20).mean().to_numpy()
    out["n_up5_rel"] = out["n_up5"] / out["n_live"]
    # 캘린더
    d = pd.Series(P.dates, index=P.dates)
    nxt = d.shift(-1)
    gap = (nxt - d).dt.days
    out["dow"] = d.dt.dayofweek
    out["gapdays"] = gap                           # 다음 거래일까지 달력일 (주말=3, 연휴≥4)
    out["pre_holiday"] = (gap >= 2) & (d.dt.dayofweek < 4) | (gap >= 4)
    out["month_end"] = d.dt.month != nxt.dt.month
    # 옵션만기: 매월 둘째 목요일(휴장이면 그 전 거래일) — 근사: 해당 월 둘째 목요일 이하 마지막 거래일
    exp = []
    for (y, mo), g in d.groupby([d.dt.year, d.dt.month]):
        first = pd.Timestamp(y, mo, 1)
        thu = first + pd.Timedelta(days=(3 - first.dayofweek) % 7 + 7)
        cand = g[g <= thu]
        if len(cand):
            exp.append(cand.iloc[-1])
    out["opt_exp"] = d.isin(exp)
    out["quad_exp"] = out["opt_exp"] & d.dt.month.isin([3, 6, 9, 12])
    return out


# ------------------------------------------------------------------ 종목 특성
def stock_features(P, df):
    """후보 행에 종목 특성 추가 (모두 t일 종가까지 정보)"""
    i, j = df["i"].to_numpy(), df["j"].to_numpy()
    c = P.c
    with np.errstate(invalid="ignore", divide="ignore"):
        strong = (P.day >= 0.03) & (P.v > 2 * P.v20)
        # 최근 20일 안에 같은 '강세 신호(+3%·거래량 2배)'가 있었는지 → 첫날 vs n일째
        sp = pd.DataFrame(strong.astype(float)).shift(1).rolling(20, min_periods=1).sum().to_numpy()
        df["prior_strong20"] = sp[i, j]
        # 연속 상승일수 (종가 기준)
        upd = (P.day > 0).astype(np.int16)
        streak = np.zeros_like(upd)
        for t in range(1, P.T):
            streak[t] = np.where(upd[t] > 0, streak[t - 1] + 1, 0)
        df["streak"] = streak[i, j]
        c5 = np.vstack([np.full((5, P.N), np.nan), c[:-5]])
        c20 = np.vstack([np.full((20, P.N), np.nan), c[:-20]])
        df["r5_prior"] = (P.prev / c5 - 1)[i, j]                 # t−1 까지 5일 (당일 제외)
        df["r20"] = (c / c20 - 1)[i, j]
        df["hi52"] = (c >= P.hi252)[i, j]
        df["to_hi52"] = (c / P.hi252)[i, j]
        df["vol_mult"] = (P.v / P.v20)[i, j]
        df["amt"] = P.amt[i, j]
        df["amt_rel"] = (P.amt / P.tv20)[i, j]
        df["sd60"] = P.sd60[i, j]
        df["gap_today"] = (P.o / P.prev - 1)[i, j]               # 당일 시가 갭
        df["oc_today"] = (P.c / P.o - 1)[i, j]                   # 당일 시가→종가
        df["upper_wick"] = ((P.h - P.c) / P.prev)[i, j]
        df["hi_today"] = (P.h / P.prev - 1)[i, j]                # 장중 고가 등락률 (상한가 터치?)
        df["kosdaq"] = P.is_kosdaq[j]
        m60 = P.m60
        df["above60"] = (c > m60)[i, j]
        df["r60"] = (c / np.vstack([np.full((60, P.N), np.nan), c[:-60]]) - 1)[i, j]
    # 거래대금 순위(그날 전체 상장 종목 중)
    amt = np.where(np.isfinite(P.amt), P.amt, -1)
    rk = (-amt).argsort(axis=1).argsort(axis=1)
    df["amt_rank"] = rk[i, j] + 1
    return df


# ------------------------------------------------------------------ 업종(테마) 동반 강세
def sector_map(P):
    """분기 스냅샷 업종 → 날짜×종목 업종코드 (직전 스냅샷 기준; 2016-01 이전은 첫 스냅샷 사용)"""
    cl = pd.read_csv(BT / "sectors/classifications.csv", dtype=str)
    cl["date"] = pd.to_datetime(cl["date"])
    cl["key"] = cl["market"] + ":" + cl["sector"]
    codes = {k: n for n, k in enumerate(sorted(cl["key"].unique()))}
    snaps = sorted(cl["date"].unique())
    S = np.full((P.T, P.N), -1, np.int32)
    for n, sd in enumerate(snaps):
        g = cl[cl["date"] == sd]
        a = np.full(P.N, -1, np.int32)
        jj = [P.ti.get(t) for t in g["ticker"]]
        for jx, k in zip(jj, g["key"]):
            if jx is not None:
                a[jx] = codes[k]
        lo = 0 if n == 0 else np.searchsorted(P.dates, sd)
        hi = P.T if n == len(snaps) - 1 else np.searchsorted(P.dates, snaps[n + 1])
        S[lo:hi] = a
    return S, {v: k for k, v in codes.items()}


def peer_sets(P, k=10, look=120, step=21):
    """가격 상관 기반 '테마 동료' — step 거래일마다 직전 look일 수익률 상관 상위 k 종목 (point-in-time).
    반환: 날짜행 → (재계산 시점 인덱스, peers[N,k])"""
    with np.errstate(invalid="ignore", divide="ignore"):
        lr = np.log(P.c / P.prev)
    res = {}
    for t0 in range(look, P.T, step):
        X = lr[t0 - look:t0]
        ok = np.isfinite(X).sum(0) >= look * 0.8
        ok &= np.nan_to_num(P.tv20[t0 - 1]) >= 3e8
        idx = np.nonzero(ok)[0]
        Y = X[:, idx]
        Y = np.where(np.isfinite(Y), Y, 0.0)
        Y = (Y - Y.mean(0)) / (Y.std(0) + 1e-12)
        C = (Y.T @ Y) / look
        np.fill_diagonal(C, -9)
        top = np.argsort(-C, axis=1)[:, :k]
        peers = np.full((P.N, k), -1, np.int32)
        peers[idx] = idx[top]
        corr = np.full((P.N, k), np.nan)
        corr[idx] = np.take_along_axis(C, top, 1)
        res[t0] = (peers, corr)
    return res


def peer_strength(P, df, ps, k=10):
    """후보마다: 테마 동료 k개 중 당일 +3% 이상 / +10% 이상 / 평균 등락률, 동료 상관 평균"""
    keys = np.array(sorted(ps))
    i, j = df["i"].to_numpy(), df["j"].to_numpy()
    n3 = np.full(len(df), np.nan); n10 = n3.copy(); mret = n3.copy(); mc = n3.copy()
    for r, (ii, jj) in enumerate(zip(i, j)):
        p = keys[keys <= ii]
        if not len(p):
            continue
        peers, corr = ps[p[-1]]
        pp = peers[jj]
        if pp[0] < 0:
            continue
        d = P.day[ii, pp[:k]]
        n3[r] = np.nansum(d >= 0.03); n10[r] = np.nansum(d >= 0.10); mret[r] = np.nanmean(d)
        mc[r] = np.nanmean(corr[jj, :k])
    df["peer_n3"], df["peer_n10"], df["peer_ret"], df["peer_corr"] = n3, n10, mret, mc
    return df
