"""종베 레이더 기초 데이터 → radar_base.json
closebet.yml 이 매일 18:37 export_web.py 끝에서 만들어 릴리스 'closebet-data'에 올림 (RADAR_OUT 환경변수).
로컬 보드(tools/radar/radar.py)가 다음 거래일 장중에 내려받아 키움 실시간 값과 합침.

담는 것 (기준일 D = 데이터 마지막 거래일)
  stocks : 종목별 전날 종가·20일 평균 거래량/거래대금·시총·상장일수·등급(밤 끼)·미국 민감도 β·테마 동료 10개·테마 연속일
  index  : 코스닥·코스피 최근 260일 종가 (장중 지수와 합쳐 계단20 계산)
  hot    : 연구 규칙 후보 수의 최근 250일 상위 20% 문턱 ('뜨거운 날')
  last   : D일 후보 (키움 키가 없을 때 '어제 기준' 화면용, 다음날 결과 채우기용)
정의는 large_cap.py · nxt_research.py 와 같음.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _night_ndx(dates):
    """t일 15:30 → t+1 09:00 사이에 끝난 미국 세션들의 나스닥100 수익 (실패하면 None)"""
    try:
        import yfinance as yf
        nd = yf.download("^NDX", start=str((dates[0] - pd.Timedelta(days=10)).date()), progress=False, auto_adjust=False)
        if isinstance(nd.columns, pd.MultiIndex):
            nd.columns = nd.columns.get_level_values(0)
        c = nd["Close"].dropna()
        c.index = pd.to_datetime(c.index).tz_localize(None)
        ud = c.index.values
        last = lambda day: float(c.iloc[np.searchsorted(ud, np.datetime64(day), side="left") - 1])
        out = np.full(len(dates), np.nan)
        for t in range(len(dates) - 1):
            out[t] = last(dates[t + 1]) / last(dates[t]) - 1
        return out
    except Exception as e:  # noqa: BLE001
        print("radar_base: 나스닥100 받기 실패 → β 생략", repr(e)[:120])
        return None


def run(L, out_path):
    P, G, T, N = L.P, L.G, L.T, L.N
    t = T - 1
    dates = P.dates
    with np.errstate(invalid="ignore", divide="ignore"):
        GAP = np.vstack([P.o[1:] / P.c[:-1] - 1, np.full((1, N), np.nan)])

    # 미국 민감도 β — 직전 250거래일 (D일 밤 갭은 아직 모름 → t−250 ~ t−1)
    beta = np.full(N, np.nan)
    sl = slice(max(0, t - 250), t)
    night = _night_ndx(dates[sl.start:t + 1])
    if night is not None:
        x = night[:-1][:, None]; y = GAP[sl]
        ok = np.isfinite(x) & np.isfinite(y)
        xs = np.where(ok, x, np.nan); ys = np.where(ok, y, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            cov = np.nanmean(xs * ys, 0) - np.nanmean(xs, 0) * np.nanmean(ys, 0)
            var = np.nanmean(xs ** 2, 0) - np.nanmean(xs, 0) ** 2
            beta = np.where(ok.sum(0) >= 150, cov / var, np.nan)

    # 테마 동료 (가장 최근 재계산 시점)
    ps = getattr(L, "ps", None)                                  # large_cap 이 이미 계산해 둔 것
    if ps is None:
        from cb import peer_sets
        ps = peer_sets(P)
    k0 = max(k for k in ps if k <= t)
    peers = ps[k0][0]

    MC = G.MC                                                    # 원 단위, D일 시총 = 다음 거래일의 '전날 시총'
    with np.errstate(invalid="ignore"):
        uni = np.isfinite(P.c[t]) & (np.nan_to_num(P.tv20[t]) >= 3e8) & (P.run[t] >= 60)
    J = np.nonzero(uni)[0]
    remap = {int(j): n for n, j in enumerate(J)}
    f = lambda a, d=0: [None if not np.isfinite(v) else round(float(v), d) for v in a]
    stocks = {
        "c": [P.tickers[j] for j in J],
        "n": [P.name.get(P.tickers[j], P.tickers[j]) for j in J],
        "m": ["Q" if P.is_kosdaq[j] else "K" for j in J],
        "close": f(P.c[t, J]),
        "v20": f(P.v20[t, J]),
        "tv20": f(P.tv20[t, J] / 1e8, 1),                       # 억
        "mc": f(MC[t, J] / 1e8),                                # 억
        "run": [int(P.run[t, j]) for j in J],
        "gp": f(L.GP[t, J], 3),                                 # 등급 백분위 (그해 워크포워드)
        "gm": f(L.GM[t, J] * 100, 3),                           # 등급 = 과거 +3% 신호 다음날 평균 갭(비용 후, %)
        "beta": f(beta[J], 2),
        "th": [int(L.THEME[t, j]) for j in J],                  # 테마 연속일 (D일까지)
        "hi252": f(P.hi252[t, J]),
        "peers": [[P.tickers[p] for p in peers[j] if p >= 0] for j in J],
    }

    def idx(code):
        s = G.ix[G.ix.index_code == code].set_index("date")["close"].reindex(dates).ffill()
        return [round(float(v), 2) for v in s.iloc[-260:]]

    cnt = L.FINAL.sum(1).astype(float)                           # 연구 규칙 후보 수 (일별)
    hot_thr = float(np.percentile(cnt[t - 249:t + 1], 80))

    # D일 후보 — 대형주 등급 / 전체(연구 최종 규칙)
    def cand(mask, keys):
        jj = np.nonzero(mask[t])[0]
        rows = []
        for j in jj:
            rows.append({"c": P.tickers[j], "n": P.name.get(P.tickers[j], P.tickers[j]), "px": round(float(P.c[t, j])),
                         "day": round(float(P.day[t, j]) * 100, 2), "pos": round(float(P.pos[t, j]), 3),
                         "vr": round(float(P.v[t, j] / P.v20[t, j]), 2) if P.v20[t, j] > 0 else None,
                         "gp": None if not np.isfinite(L.GP[t, j]) else round(float(L.GP[t, j]), 3),
                         "gm": None if not np.isfinite(L.GM[t, j]) else round(float(L.GM[t, j]) * 100, 3),
                         "th": int(L.THEME[t, j]), "beta": None if not np.isfinite(beta[j]) else round(float(beta[j]), 2)})
        rows.sort(key=keys)
        return rows

    large = L.SIG3 & L.LARGE & (L.GP >= 0.8 - 1e-12)
    out = {
        "asof": str(dates[t].date()),
        "dates": [str(d.date()) for d in dates[-260:]],
        "index": {"kq": idx("2001"), "ks": idx("1001")},
        "hot": {"thr": hot_thr, "today": float(cnt[t])},
        "stocks": stocks,
        "last": {
            "large": cand(large, lambda r: -(r["gm"] if r["gm"] is not None else -9)),
            "wide": cand(L.FINAL, lambda r: (-(r["pos"] >= 0.999), -r["th"], -r["day"])),
        },
    }
    s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(s, encoding="utf-8")
    nb = int(np.isfinite(beta[J]).sum())
    print(f"radar_base {out['asof']} · 종목 {len(J):,} (β {nb:,}) · 뜨거운 날 문턱 {hot_thr:.0f} (오늘 {cnt[t]:.0f}) · "
          f"후보 대형 {len(out['last']['large'])} / 전체 {len(out['last']['wide'])} · {len(s)/1e3:.0f}KB → {out_path}")
