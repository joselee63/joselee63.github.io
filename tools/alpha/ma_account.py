"""이평각도 눌림 돌파 — '계좌' 성과 개선 연구 엔진
python tools/alpha/ma_account.py   → reports/이평각도 계좌/data/results.json

퀀트 페이지(web/quant.html maRun)와 같은 계좌 시뮬레이션을 파이썬으로 옮기고, 아래 손잡이를 하나씩 바꿔 본다.
  ① 신호가 몰릴 때 고르는 순서   ② 비중 정하는 법(동일 / 손절폭 기준 위험 고정)   ③ 청산(회전 속도)
  ④ 시장 필터                    ⑤ 쉬는 돈 굴리기                                  ⑥ 동시 보유 수 · 하루 신규 매수 한도
기준: 동일 가중 점수 · 눌림 ≤0.2 → 0.8 돌파 · 주도 종목 · 둘 다 60일선 위 · 3R · 60일 · 동시 10종목 · 종목당 1/10 · 비용 0.5%
검증 규칙(미리 정함): 앞 절반(2015~2020)에서 고른 설정이 뒤 절반(2021~)에서도 기준보다 연수익·낙폭이 낫거나 같아야 '채택'
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
import ma_angle as A  # noqa: E402

P = A.P
o, h, l, c = A.o, A.h, A.l, A.c
T, N = P.T, P.N
DATES = P.dates
LP = [5, 7, 10, 12, 15, 20, 25, 30, 40, 60]
COST = 0.005
SPLIT = int(np.searchsorted(DATES, pd.Timestamp("2021-01-01")))

cff = pd.DataFrame(c).ffill().to_numpy()                     # 평가용 종가 (정지일은 직전 값)
ks = pd.Series(P.kospi); kq = pd.Series(P.kosdaq)


def above(s, n):
    return (s > s.rolling(n).mean()).to_numpy()


MKT = {
    "both60": above(ks, 60) & above(kq, 60),
    "none": np.ones(T, bool),
    "either60": above(ks, 60) | above(kq, 60),
    "ks60": above(ks, 60),
    "kq60": above(kq, 60),
    "both20": above(ks, 20) & above(kq, 20),
    "both120": above(ks, 120) & above(kq, 120),
}
# 계단식 비중: 두 지수 × (20·60·120일선) 6개 중 위에 있는 수 ÷ 6
STAIR = sum(above(s, n).astype(float) for s in (ks, kq) for n in (20, 60, 120)) / 6

etf = pd.read_csv(ROOT / "data-alpha/etf_069500.csv", parse_dates=["날짜"]).set_index("날짜")["종가"].reindex(DATES).ffill()
ETF = etf.to_numpy(float)                                     # KODEX 200 (분배금 미포함 → 보수적)


def scores():
    sc_eq = A.score(LP)
    sc_w = np.round(A.score(LP, [1 + 0.5 * (len(LP) - 1 - k) for k in range(len(LP))]) * 100) / 100
    return {"e": sc_eq, "w": sc_w}


SC = scores()


def candidates(sc="e", thr=0.8, floor=0.2):
    s = SC[sc]
    with np.errstate(invalid="ignore"):
        pm = pd.DataFrame(s).shift(1).rolling(15, min_periods=5).min().to_numpy()
        yd = np.vstack([np.full((1, N), np.nan), s[:-1]])
        stop_ok = np.isfinite(A.low15) & (A.low15 < c * 0.995)
        m = (s >= thr) & (yd < thr) & (pm <= floor) & A.LEAD & np.isfinite(c) & (P.day < 0.285) & stop_ok
    m[T - 1] = False                                          # 마지막 날 신호는 결과를 모름
    ii, jj = np.nonzero(m)
    order = np.lexsort((jj, ii))
    ii, jj = ii[order], jj[order]
    e = c[ii, jj]; st = A.low15[ii, jj]
    with np.errstate(invalid="ignore", divide="ignore"):
        rs120 = c[ii, jj] / c[np.maximum(ii - 120, 0), jj] - 1
    return pd.DataFrame({
        "i": ii, "j": jj, "e": e, "stop": st, "sd": 1 - st / e,           # sd = 손절폭(진입가 대비)
        "tv": P.tv20[ii, jj], "rs120": rs120, "nh": c[ii, jj] / P.hi252[ii, jj],
        "pm": pd.DataFrame(s).shift(1).rolling(15, min_periods=5).min().to_numpy()[ii, jj],
        "day": P.day[ii, jj], "vol": P.sd60[ii, jj], "kq": P.is_kosdaq[jj].astype(int),
    })


def exit_one(i, j, e, stop, k=3, H=60, early=None, be=None, tstop=None, trail=None):
    """ma_angle.backtest 순서를 따르는 청산 → (청산일, 청산가, 종류) · 데이터가 끝나면 마지막 종가
    early=(R배, 일수): 일수 안에 종가가 진입가−R배×R 이하면 그날 종가 매도 (실패 신호 조기 정리)
    be=R배: 장중 고가가 진입가+R배×R 를 찍은 다음 날부터 손절가를 진입가로
    tstop=(일수, R배): 그날 종가가 진입가+R배×R 미만이면 종가 매도 (안 가는 종목 정리)
    trail=R배: 최고 종가 − R배×R 를 손절가로 끌어올림(종가 기준 판단, 다음 날 시가/장중 체결)"""
    R = e - stop
    target = e + k * R if k else np.inf
    stp = stop
    hi_c = e
    last = None
    for d in range(1, H + 1):
        t = i + d
        if t >= T:
            break
        if not np.isfinite(o[t, j]):
            continue
        if o[t, j] <= stp:
            return t, o[t, j], "stop" if stp <= stop + 1e-9 else "trail"
        if o[t, j] >= target:
            return t, o[t, j], "target"
        if l[t, j] <= stp:
            return t, stp, "stop" if stp <= stop + 1e-9 else "trail"
        if h[t, j] >= target:
            return t, target, "target"
        cl = c[t, j]
        if early and d <= early[1] and cl <= e - early[0] * R:
            return t, cl, "early"
        if tstop and d == tstop[0] and cl < e + tstop[1] * R:
            return t, cl, "tstop"
        if be is not None and h[t, j] >= e + be * R:
            stp = max(stp, e)
        if trail is not None and np.isfinite(cl):
            hi_c = max(hi_c, cl)
            stp = max(stp, hi_c - trail * R)
        last = t
    if last is None or not np.isfinite(c[last, j]):
        return None
    return last, c[last, j], "time"


def exits(cd, **kw):
    out = np.full((len(cd), 2), np.nan)
    kinds = []
    for n, (i, j, e, st) in enumerate(zip(cd.i.to_numpy(), cd.j.to_numpy(), cd.e.to_numpy(), cd.stop.to_numpy())):
        r = exit_one(int(i), int(j), e, st, **kw)
        if r is None:
            kinds.append(None); continue
        out[n] = (r[0], r[1] / e - 1)
        kinds.append(r[2])
    return out, np.array(kinds, dtype=object)


def per_trade(cd, ex, mkt="both60", busy=True):
    """연구 방식 매매당 통계 (같은 종목 보유 중 신호 무시)"""
    ok = MKT[mkt][cd.i.to_numpy()] & np.isfinite(ex[:, 0])
    rs, ys = [], []
    bu = {}
    for n in np.nonzero(ok)[0]:
        i, j = int(cd.i.iat[n]), int(cd.j.iat[n])
        if busy and bu.get(j, -1) >= i:
            continue
        bu[j] = int(ex[n, 0])
        rs.append(ex[n, 1] - COST); ys.append(DATES[i].year)
    r = np.array(rs)
    return dict(n=len(r), avg=r.mean() * 100, t=r.mean() / (r.std(ddof=1) / np.sqrt(len(r))), win=(r > 0).mean() * 100)


def sim(cd, ex, slots=10, prio="tv", asc=False, mkt="both60", sizing="eq", risk=0.01, cap=0.2, maxpos=None,
        max_new=None, cash_rate=0.0, overlay=False, stair=False, t0=0, t1=None, cost=COST, seed=None, ret_eq=False):
    """퀀트 페이지 maRun 과 같은 계좌 시뮬레이션 + 손잡이
    sizing='eq'  : 종목당 평가액/slots (현금 한도)
    sizing='risk': 종목당 평가액 × risk ÷ 손절폭, 최대 평가액×cap · 보유 종목 수는 maxpos(기본 slots)까지
    max_new      : 하루 신규 매수 한도
    cash_rate    : 쉬는 현금 연이자 (예: 0.02)
    overlay      : 쉬는 현금을 KODEX 200 에 — True: 시장 필터가 켜진 날만 (꺼지면 현금) · "always": 늘
    stair        : 시장 필터 대신 계단식 비중 (6개 이평선 중 위에 있는 비율 × 목표 비중)"""
    t1 = T - 1 if t1 is None else t1
    maxpos = maxpos or slots
    gate = MKT[mkt]
    I = cd.i.to_numpy(); J = cd.j.to_numpy(); E = cd.e.to_numpy(); SD = cd.sd.to_numpy()
    if prio == "random":
        key = np.random.default_rng(seed).random(len(cd))
    else:
        key = cd[prio].to_numpy(float)
        key = np.where(np.isfinite(key), key, -np.inf if not asc else np.inf)
        if asc:
            key = -key
    valid = np.isfinite(ex[:, 0])
    by_t = {}
    for n in np.nonzero(valid)[0]:
        t = int(I[n])
        if t < t0 or t > t1:
            continue
        if not stair and not gate[t]:
            continue
        if stair and STAIR[t] <= 0:
            continue
        by_t.setdefault(t, []).append(n)
    cash, eq, inv = 1.0, np.full(t1 - t0 + 1, np.nan), 0.0
    opn = []                                                     # [n, j, amt, end, r]
    held = set()
    taken = []
    on_etf = False
    for t in range(t0, t1 + 1):
        # 쉬는 돈 굴리기 (어제 상태 기준)
        if overlay and on_etf and np.isfinite(ETF[t]) and np.isfinite(ETF[t - 1]):
            cash *= ETF[t] / ETF[t - 1]
        elif cash_rate:
            cash *= 1 + cash_rate / 252
        freed = []
        keep = []
        for p in opn:
            if p[3] <= t:
                cash += p[2] * (1 + p[4] - cost); freed.append(p[1])
            else:
                keep.append(p)
        opn = keep
        mtm = sum(p[2] * cff[t, p[1]] / E[p[0]] for p in opn)
        eqv = cash + mtm
        inv += mtm / eqv if eqv > 0 else 0
        lst = by_t.get(t)
        if lst:
            lst = sorted(lst, key=lambda n: -key[n])
            new = 0
            for n in lst:
                j = int(J[n])
                if j in held:
                    continue
                if len(opn) >= maxpos or (max_new is not None and new >= max_new):
                    continue
                if sizing == "eq":
                    want = eqv / slots
                else:
                    want = min(eqv * risk / max(SD[n], 1e-3), eqv * cap)
                if stair:
                    want *= STAIR[t]
                amt = min(want, cash)
                if amt <= 1e-9:
                    continue
                cash -= amt; held.add(j); new += 1
                opn.append([n, j, amt, int(ex[n, 0]), ex[n, 1]])
                taken.append(n)
        for j in freed:
            if not any(p[1] == j for p in opn):
                held.discard(j)
        eq[t - t0] = eqv
        on_etf = overlay == "always" or (bool(overlay) and bool(gate[t]))
    res = stats(eq, t0)
    tk = np.array(taken, int)
    res.update(n=len(tk), avg=float((ex[tk, 1] - cost).mean() * 100) if len(tk) else 0.0, inv=inv / len(eq) * 100)
    if ret_eq:
        res["eq"] = eq
    return res


def cagr(eq, t0, a, b):
    """eq 의 [a, b] 행 구간 연수익 (a,b 는 전체 날짜 인덱스)"""
    a = max(a, t0); b = min(b, t0 + len(eq) - 1)
    if b <= a:
        return np.nan
    v0, v1 = eq[a - t0], eq[b - t0]
    yrs = (DATES[b] - DATES[a]).days / 365.25
    return ((v1 / v0) ** (1 / yrs) - 1) * 100


def mdd(x):
    x = np.asarray(x, float)
    if not len(x):
        return np.nan
    pk = np.maximum.accumulate(x)
    return float((x / pk - 1).min() * 100)


def stats(eq, t0):
    t1 = t0 + len(eq) - 1
    yrs = {}
    for y in range(DATES[t0].year, DATES[t1].year + 1):
        idx = np.nonzero((DATES.year == y))[0]
        a, b = max(idx[0] - 1, t0), min(idx[-1], t1)
        if b <= a:
            continue
        yrs[y] = (eq[b - t0] / eq[a - t0] - 1) * 100
    return dict(cagr=cagr(eq, t0, t0, t1), mdd=mdd(eq), h1=cagr(eq, t0, t0, SPLIT - 1), h2=cagr(eq, t0, SPLIT - 1, t1),
                m1=mdd(eq[:max(SPLIT - t0, 0)]), m2=mdd(eq[max(SPLIT - 1 - t0, 0):]), yrs=yrs)


def bench(x, t0=0):
    x = np.asarray(x, float)[t0:]
    return stats(x / x[0], t0)


if __name__ == "__main__":
    import time
    t_ = time.time()
    cd = candidates()
    ex, kd = exits(cd, k=3, H=60)
    print(f"후보 {len(cd):,} · 청산 계산 {time.time() - t_:.0f}s")
    pt = per_trade(cd, ex)
    print(f"연구 방식 매매당: {pt['n']:,}건 {pt['avg']:+.2f}% t {pt['t']:.1f} 승률 {pt['win']:.0f}%")
    b = sim(cd, ex)
    print(f"계좌 기준: 연 {b['cagr']:+.1f}% MDD {b['mdd']:.1f}% · 편입 {b['n']}건 평균 {b['avg']:+.2f}% · 투자비중 {b['inv']:.0f}% · 앞 {b['h1']:+.1f}% 뒤 {b['h2']:+.1f}%")
    k = bench(P.kospi)
    print(f"코스피: 연 {k['cagr']:+.1f}% MDD {k['mdd']:.1f}% · 앞 {k['h1']:+.1f}% 뒤 {k['h2']:+.1f}%")
