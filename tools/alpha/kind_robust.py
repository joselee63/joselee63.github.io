"""공시 이벤트 강건성 + 달력 포트폴리오(그날 보유 중인 이벤트 동일비중) — 자사주·무상증자 등.
python tools/alpha/kind_robust.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, base_mask, fwd, load_panel, nw_t, roll  # noqa: E402
from kind_events import load  # noqa: E402


def event_table(P, d, mask, label):
    d = d[mask[d["i"], d["j"]]]
    out = [f"  {label:30} n={len(d):5d}"]
    for H in (5, 10, 20, 40):
        R = fwd(P, H)
        mu = np.nanmean(np.where(mask, R, np.nan), axis=1)
        x = R[d["i"], d["j"]] - mu[d["i"]]
        raw = R[d["i"], d["j"]] - COST_KR
        out.append(f"H{H} 초과 {np.nanmean(x)*100:+.2f} 절대(비용후) {np.nanmean(raw)*100:+.2f}")
    return " | ".join(out)


def calendar_port(P, d, H, mask, cost=COST_KR, label=""):
    """시가→시가 일수익으로, 진입(i+1 시가)부터 H일 보유. 진입일에 비용 차감. 유니버스 동일가중 대비."""
    d = d[mask[d["i"], d["j"]]]
    o = pd.DataFrame(P.o).ffill().to_numpy()
    roo = np.full_like(o, np.nan); roo[:-1] = o[1:] / o[:-1] - 1
    roo[~np.isfinite(roo)] = 0
    pos = np.zeros((P.T, P.N), np.float32)
    ent = np.zeros((P.T, P.N), np.float32)
    for i, j in zip(d["i"].to_numpy(), d["j"].to_numpy()):
        a, b = i + 1, min(i + 1 + H, P.T)
        pos[a:b, j] = 1                      # 겹치면 1(재진입은 연장)
        ent[a, j] = 1
    n = pos.sum(1)
    pr = np.where(n > 0, (pos * roo).sum(1) / np.maximum(n, 1) - cost * ent.sum(1) / np.maximum(n, 1) / 1, 0.0)
    um = mask & np.isfinite(P.c)
    ur = np.where(um, roo, np.nan)
    uni = np.nanmean(ur, axis=1)
    s = pd.Series(pr, index=P.dates); u = pd.Series(np.where(n > 0, uni, 0), index=P.dates)
    act = n > 0
    eq = (1 + s).cumprod(); mdd = (eq / eq.cummax() - 1).min()
    yrs = len(s) / 252
    ex = (s - u)[act]
    yr = (s - u).groupby(s.index.year).sum()
    print(f"  [{label}] 보유일 {act.mean()*100:.0f}% 평균 {n[act].mean():.1f}종목 연 {(eq.iloc[-1]**(1/yrs)-1)*100:+.1f}% "
          f"MDD {mdd*100:.0f}% 보유일 초과 {ex.mean()*100:+.3f}%/일 t={nw_t(ex.to_numpy(), 5):.2f} 플러스연도 {(yr>0).sum()}/{len(yr)}")
    print("     연도별 초과(합 %): " + " ".join(f"{y%100}:{v*100:+.0f}" for y, v in yr.items()))
    return s


if __name__ == "__main__":
    P = load_panel()
    m10 = base_mask(P, liq=True)
    m0 = base_mask(P, liq=False)
    m5 = base_mask(P, liq=False) & (P.tv20 >= 5e8)
    m50 = base_mask(P, liq=False) & (P.tv20 >= 5e9)
    for key in ["자기주식취득신탁계약체결결정", "자기주식취득결정", "무상증자결정", "유상증자결정", "최대주주변경", "전환사채권발행결정"]:
        d = load(P, key)
        hrs = pd.to_datetime(d["time"]).dt.hour
        print(f"\n== {key} · 공시 시각: 장전(<9시) {(hrs<9).mean()*100:.0f}% 장중 {((hrs>=9)&(hrs<16)).mean()*100:.0f}% 장후 {(hrs>=16).mean()*100:.0f}%")
        for mm, lab in ((m0, "유동성 무관"), (m5, "거래대금 5억+"), (m10, "10억+"), (m50, "50억+")):
            print(event_table(P, d, mm, lab))
        if key.startswith("자기주식") or key == "무상증자결정":
            for H in (10, 20):
                calendar_port(P, d, H, m5, label=f"달력 포트 5억+ H{H}")
            calendar_port(P, d, 20, m10, label="달력 포트 10억+ H20")
