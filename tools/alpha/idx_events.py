"""KOSPI200·KOSDAQ150 정기변경(6·12월) 편입/편출 이벤트.
python tools/alpha/idx_events.py

구성종목 스냅샷: 5·6·11·12월은 매 거래일 → 편입 '효력일'(처음 구성에 나타난 날)을 정확히 앎.
정기변경 발표는 효력일 약 2~3주 전(KRX 공지). 미래정보를 피하려고 '효력일 −7거래일 종가'(발표 이후가 확실한 시점)에 진입.
  A. 발표 후 드리프트: 효력일−7 종가 매수 → 효력일 전날 종가 매도 (지수펀드 매수 체결 시점)
  B. 효력일 이후 되돌림: 효력일 시가 → +20거래일 시가
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, load_alpha, load_panel  # noqa: E402

P = load_panel()
ix = load_alpha("idx")
ix["ticker"] = ix["ticker"].astype(str).str.zfill(6)
ix["index"] = ix["index"].astype(str)
lastc = pd.DataFrame(P.c).ffill().to_numpy()
mkt_r = None
rows = []
for code, g in ix.groupby("index"):
    snaps = sorted(g["date"].unique())
    mem = {d: set(g.loc[g["date"] == d, "ticker"]) for d in snaps}
    for a, b in zip(snaps[:-1], snaps[1:]):
        if b.month not in (6, 12) or (b - a).days > 7:          # 정기변경 달의 연속 스냅샷만
            continue
        for kind, tks in (("편입", mem[b] - mem[a]), ("편출", mem[a] - mem[b])):
            for t in tks:
                if t not in P.ti:
                    continue
                e = P.dates.searchsorted(b)                    # 효력일 행
                j = P.ti[t]
                if e - 8 < 0 or e + 21 >= P.T:
                    continue
                A = lastc[e - 1, j] / lastc[e - 8, j] - 1
                Am = np.nanmean(lastc[e - 1] / lastc[e - 8] - 1)
                B = P.o[e + 20, j] / P.o[e, j] - 1 if np.isfinite(P.o[e, j]) else np.nan
                Bm = np.nanmean(P.o[e + 20] / P.o[e] - 1)
                rows.append(dict(index={"1028": "KOSPI200", "2203": "KOSDAQ150"}.get(code, code), kind=kind,
                                 eff=b, A=A - COST_KR, Aex=A - Am, B=B - COST_KR, Bex=B - Bm))
r = pd.DataFrame(rows).drop_duplicates(["index", "kind", "eff", "A"])
print(f"정기변경 이벤트 {len(r)} · 효력일 {sorted(r['eff'].dt.strftime('%Y-%m').unique())}")
for (ind, kind), g in r.groupby(["index", "kind"]):
    for c, lab in (("A", "효력일−7 종가→전날 종가"), ("B", "효력일 시가→+20일")):
        x = g[c].dropna(); xe = g[c + "ex"].dropna()
        yr = x.groupby(g.loc[x.index, "eff"].dt.year).mean()
        print(f"  {ind} {kind} [{lab}] n={len(x)} 비용후 {x.mean()*100:+.2f}% (중앙 {x.median()*100:+.2f}) 시장대비 {xe.mean()*100:+.2f}% "
              f"t={xe.mean()/xe.std()*np.sqrt(len(xe)):.1f} 승 {(x>0).mean()*100:.0f}% 플러스 회차연도 {(yr>0).sum()}/{len(yr)}")

# ---- 민감도: 진입(효력일 −k 종가) · 청산(효력일 전날 종가 / 효력일 시가)
print("\n== 편입 종목 진입·청산 시점 민감도 (비용 후 평균 / 중앙 / 시장대비 t) ==")
for code, nm in (("1028", "KOSPI200"), ("2203", "KOSDAQ150")):
    g = ix[ix["index"] == code]
    snaps = sorted(g["date"].unique()); mem = {d: set(g.loc[g["date"] == d, "ticker"]) for d in snaps}
    ev = []
    for a, b in zip(snaps[:-1], snaps[1:]):
        if b.month in (6, 12) and (b - a).days <= 7:
            ev += [(P.dates.searchsorted(b), P.ti[t]) for t in mem[b] - mem[a] if t in P.ti]
    ev = sorted(set(ev))
    for k in (3, 5, 7, 10, 12):
        for ex_lab, ex in (("전날 종가", lambda e, j: lastc[e - 1, j]), ("효력일 시가", lambda e, j: P.o[e, j])):
            x = np.array([ex(e, j) / lastc[e - k, j] - 1 for e, j in ev if e - k >= 0])
            mk = np.array([np.nanmean(lastc[e - 1] / lastc[e - k] - 1) for e, j in ev if e - k >= 0])
            xe = x - mk
            print(f"  {nm} 진입 −{k:>2} 종가 → {ex_lab}: n={len(x)} 평균 {np.nanmean(x-COST_KR)*100:+.2f}% 중앙 {np.nanmedian(x-COST_KR)*100:+.2f}% "
                  f"시장대비 t={np.nanmean(xe)/np.nanstd(xe)*np.sqrt(np.isfinite(xe).sum()):.1f}")
