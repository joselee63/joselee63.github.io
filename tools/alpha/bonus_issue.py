"""무상증자 권리락 전략: 공시 다음날 시가 매수 → 권리락일(신주배정기준일 전 거래일, 공시에 미리 나옴) 기준 매도.
권리락일은 KRX 원주가÷수정주가 계수가 바뀌는 날로 찾음(공시된 날짜와 같음 → 미래정보 아님).
python tools/alpha/bonus_issue.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, base_mask, load_alpha, load_panel  # noqa: E402
from kind_events import load  # noqa: E402

P = load_panel()
cap = load_alpha("cap"); cap = cap[cap.ticker.isin(set(P.tickers))]
rc = P.align(cap, "close")
d = load(P, "무상증자결정")
for liqv in (5e8, 1e9, 5e9):
    m = base_mask(P, liq=False) & (P.tv20 >= liqv)
    e = d[m[d.i, d.j]]
    rows = []
    for i, j in zip(e.i, e.j):
        f = rc[i:i + 45, j] / P.c[i:i + 45, j]
        ch = f[:-1] / f[1:]
        if not np.isfinite(ch).any():
            continue
        k = int(np.nanargmax(np.abs(np.log(ch))))
        if abs(np.log(ch[k])) < np.log(1.09):      # 10% 미만 소규모(주식배당 등)는 제외
            continue
        x = i + k + 1                                # 권리락일 행
        if x + 1 >= P.T or x <= i + 1:
            continue
        ent = P.o[i + 1, j]
        r = {"date": P.dates[i], "days": x - i - 1, "ratio": ch[k],
             "pre_close": P.c[x - 1, j] / ent - 1,          # 권리락 전날 종가 매도
             "ex_open": P.o[x, j] / ent - 1,                # 권리락일 시가
             "ex_close": P.c[x, j] / ent - 1,               # 권리락일 종가
             "ex_next_open": P.o[x + 1, j] / ent - 1,       # 다음날 시가
             "ex_lim": P.day[x, j] >= 0.29}
        rows.append(r)
    t = pd.DataFrame(rows).dropna()
    print(f"\n== 거래대금 {liqv/1e8:.0f}억+ · 이벤트 {len(t)} · 공시→권리락 중앙 {t.days.median():.0f}거래일 · 권리락일 상한가 {t.ex_lim.mean()*100:.0f}%")
    for c in ("pre_close", "ex_open", "ex_close", "ex_next_open"):
        x = t[c] - COST_KR
        yr = x.groupby(t.date.dt.year).mean()
        s = np.sort(x)
        h = t.date <= t.date.median()
        print(f"  매도={c:12} 평균 {x.mean()*100:+.2f}% 중앙 {x.median()*100:+.2f}% 상위5%제외 {s[:int(len(s)*.95)].mean()*100:+.2f}% "
              f"승 {(x>0).mean()*100:.0f}% 하위1% {np.percentile(x,1)*100:+.1f}% t={x.mean()/x.std()*np.sqrt(len(x)):.2f} "
              f"앞/뒤 {x[h].mean()*100:+.2f}/{x[~h].mean()*100:+.2f} 플러스연도 {(yr>0).sum()}/{len(yr)}")
    print("   연도별(권리락일 종가 매도): " + " ".join(f"{y%100}:{v*100:+.1f}" for y, v in (t.ex_close - COST_KR).groupby(t.date.dt.year).mean().items()))
    print("   비율별(권리락일 종가): " + " ".join(f"{lo}~{hi}배:{(t[(t.ratio>=lo)&(t.ratio<hi)].ex_close-COST_KR).mean()*100:+.1f}(n={((t.ratio>=lo)&(t.ratio<hi)).sum()})" for lo, hi in ((1.09, 1.6), (1.6, 2.5), (2.5, 99))))
