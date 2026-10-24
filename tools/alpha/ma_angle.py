"""이평각도점수 — 이평선별로 '오늘 값 > 어제 값'이면 1점 (가중합, 최대 1.0으로 정규화). 주도 종목의 눌림 뒤 점수 반등 돌파 매수
python tools/alpha/ma_angle.py
무편향 일봉(상장폐지 포함), 2015~2026, 비용 왕복 0.5%
  대상(주도 종목): 종가 > 60일선, 60일선 20일 전보다 위, 최근 40일 안에 52주 신고가, 20일 평균 거래대금 30억↑, 상장 260일↑
  눌림: 최근 15일 안에 점수 ≤ 바닥 기준
  매수: 점수가 문턱을 아래→위로 돌파한 날 종가 (그날도 60일선 위)
  손절: 눌림 구간 최저가(최근 15일 저가) 이탈 → 그 가격(시가가 더 낮으면 시가) / 점수 0 → 그날 종가
  익절: 진입가 + k × (진입가 − 손절가) 도달 → 그 가격(시가가 더 높으면 시가) · 40일 안에 아무것도 없으면 종가 청산
  같은 종목은 보유 중 새 신호 무시
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
from common import load_panel, roll  # noqa: E402

COST = 0.005
P = load_panel()
T, N = P.T, P.N
c, o, h, l = P.c, P.o, P.h, P.l
yr = P.dates.year.to_numpy()
MAS = {}


def ma(n):
    if n not in MAS:
        MAS[n] = roll(c, n, "mean", minp=n)
    return MAS[n]


def score(periods, weights=None):
    w = np.ones(len(periods)) if weights is None else np.asarray(weights, float)
    s = np.zeros((T, N))
    for n, wi in zip(periods, w):
        m = ma(n)
        up = np.zeros((T, N)); up[1:] = (m[1:] > m[:-1])
        s += wi * up
    s = s / w.sum()
    s[:max(periods)] = np.nan
    return s


with np.errstate(invalid="ignore"):
    m60 = ma(60)
    m60up = m60 > np.vstack([np.full((20, N), np.nan), m60[:-20]])
    hi252 = roll(c, 252, "max", minp=252)
    nh = (c >= hi252).astype(float)
    nh40 = pd.DataFrame(nh).rolling(40, min_periods=1).max().to_numpy() > 0
    LEAD = (c > m60) & m60up & nh40 & (P.tv20 >= 3e9) & (P.run >= 260)
    low15 = roll(l, 15, "min", minp=10)


def backtest(sc, thr, floor=0.2, tgt=2.0, use_zero=True, hold=40, lead=LEAD, label="", show=True):
    with np.errstate(invalid="ignore"):
        prevmin = pd.DataFrame(sc).shift(1).rolling(15, min_periods=5).min().to_numpy()
        cross = (sc >= thr) & (np.vstack([np.full((1, N), np.nan), sc[:-1]]) < thr)
        sig = cross & (prevmin <= floor) & lead & np.isfinite(c) & (P.day < 0.285)
    ii, jj = np.nonzero(sig)
    order = np.lexsort((ii, jj)); ii, jj = ii[order], jj[order]
    rets, Rs, days, ys, kinds = [], [], [], [], []
    busy_until = {}
    for i, j in zip(ii, jj):
        if busy_until.get(j, -1) >= i:
            continue
        e = c[i, j]; stop = low15[i, j]
        if not (np.isfinite(stop) and stop < e * 0.995):
            continue
        R = e - stop; target = e + tgt * R
        exit_px, k, why = None, None, "time"
        for d in range(1, hold + 1):
            t = i + d
            if t >= T:
                break
            if not np.isfinite(o[t, j]):
                continue
            if o[t, j] <= stop:
                exit_px, why = o[t, j], "stop"; k = t; break
            if o[t, j] >= target:
                exit_px, why = o[t, j], "target"; k = t; break
            if l[t, j] <= stop:
                exit_px, why = stop, "stop"; k = t; break
            if h[t, j] >= target:
                exit_px, why = target, "target"; k = t; break
            if use_zero and sc[t, j] <= 1e-9:
                exit_px, why = c[t, j], "zero"; k = t; break
            k = t
        if exit_px is None:
            if k is None or not np.isfinite(c[k, j]):
                continue
            exit_px = c[k, j]
        busy_until[j] = k
        r = exit_px / e - 1 - COST
        rets.append(r); Rs.append((exit_px - e) / R); days.append(k - i); ys.append(yr[i]); kinds.append(why)
    r = np.array(rets); ys = np.array(ys); kinds = np.array(kinds)
    if not len(r):
        if show: print(f"  {label:44} 0건")
        return None
    yy = pd.Series(r).groupby(ys).mean()
    res = dict(n=len(r), mean=r.mean(), win=(r > 0).mean(), R=np.mean(Rs), days=np.mean(days), yrpos=int((yy > 0).sum()), yrn=len(yy),
               t=r.mean() / (r.std(ddof=1) / np.sqrt(len(r))), tgt=(kinds == "target").mean(), stp=(kinds == "stop").mean(), zero=(kinds == "zero").mean(), yy=yy)
    if show:
        print(f"  {label:44} {res['n']:5d}건 · 매매당 {res['mean']*100:+.2f}% (t {res['t']:.1f}) · 승률 {res['win']*100:3.0f}% · 평균 {res['R']:+.2f}R · "
              f"보유 {res['days']:.0f}일 · 익절 {res['tgt']*100:.0f}% 손절 {res['stp']*100:.0f}% 점수0 {res['zero']*100:.0f}% · 연도+ {res['yrpos']}/{res['yrn']}")
    return res


if __name__ == "__main__":
    S5 = [3, 5, 7, 10, 15]
    S10 = [3, 4, 5, 6, 7, 8, 10, 12, 15, 20]
    sets = {
        "5개 동일": score(S5),
        "5개 단기가중": score(S5, [5, 4, 3, 2, 1]),
        "5개 장기가중": score(S5, [1, 2, 3, 4, 5]),
        "10개 동일": score(S10),
        "10개 단기가중": score(S10, list(range(10, 0, -1))),
        "10개 장기가중": score(S10, list(range(1, 11))),
    }
    print(f"무편향 일봉 {P.dates[0]:%Y-%m-%d} ~ {P.dates[-1]:%Y-%m-%d} · 비용 왕복 {COST*100:.1f}%")
    print("\n[1] 점수 종류별 — 바닥 ≤0.2 → 문턱 0.6 돌파 · 손절 전저점/점수0 · 익절 2R")
    for k, sc in sets.items():
        backtest(sc, 0.6, label=k)
    sc = sets["5개 동일"]
    print("\n[2] 문턱 (5개 동일 · 2R)")
    for thr in (0.4, 0.6, 0.8, 1.0):
        backtest(sc, thr, label=f"문턱 {thr:.1f} 돌파")
    print("\n[3] 익절 손익비 · 점수0 손절 (5개 동일 · 문턱 0.6)")
    for tg in (1.5, 2.0, 3.0, 5.0):
        backtest(sc, 0.6, tgt=tg, label=f"익절 {tg}R")
    backtest(sc, 0.6, use_zero=False, label="점수0 손절 끄기 (전저점만)")
    print("\n[4] 바닥 깊이 (5개 동일 · 문턱 0.6)")
    for fl in (0.0, 0.2, 0.4):
        backtest(sc, 0.6, floor=fl, label=f"최근 15일 최저 점수 ≤ {fl:.1f}")
    print("\n[5] 대조군 — 주도 종목 조건 빼기 / 신호 없이 주도 종목 아무 날")
    with np.errstate(invalid="ignore"):
        loose = (c > m60) & (P.tv20 >= 3e9) & (P.run >= 260)
    backtest(sc, 0.6, lead=loose, label="주도 조건 약하게(60일선 위만)")
    rnd = LEAD & (np.random.default_rng(0).random((T, N)) < 0.02)
    # 무작위 진입: 점수 조건 대신 아무 날 (같은 손절·익절)
    sc_r = np.where(rnd, 1.0, 0.0); sc_r[1:][rnd[1:]] = 1.0
    print("  (무작위 진입 대조는 같은 손절·익절 규칙으로)")
    def random_entry():
        ii, jj = np.nonzero(rnd)
        rets = []
        for i, j in zip(ii, jj):
            e = c[i, j]; stop = low15[i, j]
            if not (np.isfinite(stop) and stop < e * 0.995) or i + 41 >= T:
                continue
            R = e - stop; target = e + 2 * R; ex = None
            for d in range(1, 41):
                t = i + d
                if not np.isfinite(o[t, j]): continue
                if o[t, j] <= stop: ex = o[t, j]; break
                if o[t, j] >= target: ex = o[t, j]; break
                if l[t, j] <= stop: ex = stop; break
                if h[t, j] >= target: ex = target; break
            if ex is None: ex = c[min(i + 40, T - 1), j]
            if np.isfinite(ex): rets.append(ex / e - 1 - COST)
        r = np.array(rets); print(f"  {'주도 종목 무작위 날 진입(같은 손절·2R)':44} {len(r):5d}건 · 매매당 {r.mean()*100:+.2f}% · 승률 {(r>0).mean()*100:.0f}%")
    random_entry()
    best = backtest(sc, 0.6, show=False)
    print("\n[6] 연도별 (5개 동일 · 문턱 0.6 · 2R): " + " ".join(f"{y%100:02d}:{v*100:+.2f}" for y, v in best["yy"].items()))
    # [7] 개선판 (2026-10-24 검증): 긴 이평 10개(5~60) · 문턱 0.8 · 전저점 손절만 · 3R · 최대 60일 · 코스피·코스닥 둘 다 60일선 위
    ix = pd.read_csv(ROOT / "data-backtest/sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
    g = lambda code: ix[ix.index_code == code].set_index("date")["close"].reindex(P.dates).ffill()
    ks, kq = g("1001"), g("2001")
    both60 = ((ks > ks.rolling(60).mean()) & (kq > kq.rolling(60).mean())).to_numpy()[:, None]
    scL = score([5, 7, 10, 12, 15, 20, 25, 30, 40, 60])
    print("\n[7] 개선판")
    backtest(scL, 0.8, tgt=3.0, use_zero=False, hold=60, label="10개(5~60)·0.8·3R")
    backtest(scL, 0.8, tgt=3.0, use_zero=False, hold=60, lead=LEAD & both60, label="10개(5~60)·0.8·3R·둘 다 60일선 위")
