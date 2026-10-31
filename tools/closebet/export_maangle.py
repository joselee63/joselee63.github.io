"""퀀트 페이지 '이평각도 눌림 돌파' 백테스트용 데이터 → web/maangle.json  (한국만)
python tools/closebet/export_maangle.py   (MAANGLE_OUT 으로 출력 경로, BACKTEST_DIR · ALPHA_CACHE 로 일봉 패널 변경 가능)
매일 갱신: .github/workflows/closebet.yml (export_web.py 바로 뒤 — 같은 패널 캐시를 씀) → 릴리스 closebet-data → daily.yml 이 사이트에 넣음

정의는 tools/alpha/ma_angle.py 와 같음 (상장폐지 포함 무편향 일봉)
  주도 종목(LEAD): 종가>60일선 · 60일선이 20일 전보다 위 · 40일 안 52주 신고가 · 20일 평균 거래대금 30억↑ · 연속 상장 260일↑
  점수: 이평선 10개(5·7·10·12·15·20·25·30·40·60)마다 '오늘>어제'면 1점 → 동일 가중(eq) / 단기 가중(w, 60일선 1점~5일선 5.5점, ×100 반올림 — 차트 게임과 같음)
  신호: 점수가 문턱을 아래→위로 돌파 · 직전 15일 최저 점수 ≤ 바닥 · 그날 등락 +28.5% 미만 · 손절가(최근 15일 저가) < 종가×0.995
  매수: 신호 날 종가 · 손절: 15일 저가 이탈(시가가 더 낮으면 시가) · 익절: 진입가 + k×R(시가가 더 높으면 시가) · 최대 H거래일 뒤 종가
여기서는 '어느 조합으로든 신호가 될 수 있는 행'(문턱 0.7·0.8·0.9 중 하나를 돌파 · 바닥 ≤ 0.3)을 뽑고, 청산은 k∈{2,3,5,없음} × H∈{40,60,90} 12가지를
미리 계산해 둠 → 브라우저는 문턱·바닥·점수 종류·시장 필터·비용·보유 종목 수만 바꿔 가며 계산.
  ev 열: i 날짜 · j 종목 · se/sep/pe (동일 가중 오늘·어제 점수, 직전 15일 최저 ×100) · sw/swp/pw (단기 가중) · e 진입가 · st 손절가(÷진입가 ×1e4)
         tv 20일 평균 거래대금(억) · x[12] 청산 (거래일 수, 수익 ×1e4, 비용 전 · 순서 H 바깥·k 안쪽) · c 일별 종가(÷진입가 ×1000, 가장 늦은 청산일까지 · 정지일은 직전 값)
  마지막 날 신호는 x·c 가 비어 있음 → 페이지의 '오늘 신호'
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
import ma_angle as A  # noqa: E402  (패널 P · LEAD · low15 · score — 모듈 계산만, 실험 코드는 __main__ 에만 있음)

OUT = Path(os.environ.get("MAANGLE_OUT", ROOT / "web" / "maangle.json"))
P = A.P
o, h, l, c = A.o, A.h, A.l, A.c
T, N = P.T, P.N
KS = (2, 3, 5, 0)                     # 익절 R 배수 (0 = 익절 없음)
HS = (40, 60, 90)                     # 최대 보유 거래일
MAXH = max(HS)
LP = [5, 7, 10, 12, 15, 20, 25, 30, 40, 60]

sc_eq = A.score(LP)
sc_w = np.round(A.score(LP, [1 + 0.5 * (len(LP) - 1 - k) for k in range(len(LP))]) * 100) / 100


def prev_min(sc):
    return pd.DataFrame(sc).shift(1).rolling(15, min_periods=5).min().to_numpy()


def prev_day(sc):
    return np.vstack([np.full((1, N), np.nan), sc[:-1]])


pm_eq, pm_w = prev_min(sc_eq), prev_min(sc_w)
yd_eq, yd_w = prev_day(sc_eq), prev_day(sc_w)
with np.errstate(invalid="ignore"):
    cand = np.zeros((T, N), bool)
    for sc, yd, pm in ((sc_eq, yd_eq, pm_eq), (sc_w, yd_w, pm_w)):
        for thr in (0.7, 0.8, 0.9):
            cand |= (sc >= thr) & (yd < thr) & (pm <= 0.3)
    stop_ok = np.isfinite(A.low15) & (A.low15 < c * 0.995)
    m = cand & A.LEAD & np.isfinite(c) & (P.day < 0.285) & stop_ok
ii, jj = np.nonzero(m)
order = np.lexsort((jj, ii)); ii, jj = ii[order], jj[order]


def exit_of(i, j, e, stop, k, H):
    """ma_angle.backtest 와 같은 순서 → (끝난 날 i+d, 청산가) — 데이터가 끝나면 마지막 종가"""
    target = e + k * (e - stop) if k else np.inf
    kk = None
    for d in range(1, H + 1):
        t = i + d
        if t >= T:
            break
        if not np.isfinite(o[t, j]):
            continue
        if o[t, j] <= stop:
            return t, o[t, j]
        if o[t, j] >= target:
            return t, o[t, j]
        if l[t, j] <= stop:
            return t, stop
        if h[t, j] >= target:
            return t, target
        kk = t
    if kk is None or not np.isfinite(c[kk, j]):
        return None
    return kk, c[kk, j]


def q100(a, nan):
    return [nan if not np.isfinite(v) else int(round(v * 100)) for v in a]


ev = {k: [] for k in ("i", "j", "se", "sep", "pe", "sw", "swp", "pw", "e", "st", "tv", "x", "c")}
last = T - 1
for i, j in zip(ii.tolist(), jj.tolist()):
    e, stop = c[i, j], A.low15[i, j]
    xs = []
    if i < last:
        for H in HS:
            for k in KS:
                r = exit_of(i, j, e, stop, k, H)
                xs.append(None if r is None else (r[0] - i, int(round((r[1] / e - 1) * 1e4))))
        if all(x is None for x in xs):
            continue
        end = max(x[0] for x in xs if x is not None)
        path, pv = [], 1.0
        for d in range(1, end + 1):
            v = c[i + d, j]
            if np.isfinite(v):
                pv = v / e
            path.append(int(round(pv * 1000)))                   # 계좌 평가용이라 0.1% 단위면 충분 (파일 크기 절약)
    else:
        path = []
    ev["i"].append(i); ev["j"].append(j)
    ev["se"].append(q100([sc_eq[i, j]], -1)[0]); ev["sep"].append(q100([yd_eq[i, j]], 999)[0]); ev["pe"].append(q100([pm_eq[i, j]], 999)[0])
    ev["sw"].append(q100([sc_w[i, j]], -1)[0]); ev["swp"].append(q100([yd_w[i, j]], 999)[0]); ev["pw"].append(q100([pm_w[i, j]], 999)[0])
    ev["e"].append(round(float(e), 2)); ev["st"].append(int(round(stop / e * 1e4))); ev["tv"].append(int(P.tv20[i, j] / 1e8))
    ev["x"].append([v for x in xs for v in ((-1, 0) if x is None else x)])
    ev["c"].append(path)

used = sorted(set(ev["j"]))
remap = {j: n for n, j in enumerate(used)}
ev["j"] = [remap[j] for j in ev["j"]]
stocks = [{"c": P.tickers[j], "n": P.name.get(P.tickers[j], P.tickers[j]), "m": "Q" if P.is_kosdaq[j] else "K",
           "x": 1 if P.tickers[j] in P.delisted else 0} for j in used]
ks = pd.Series(P.kospi, index=P.dates)
kq = pd.Series(P.kosdaq, index=P.dates)
both60 = ((ks > ks.rolling(60).mean()) & (kq > kq.rolling(60).mean())).astype(int).tolist()
nn = lambda s: [None if not np.isfinite(v) else round(float(v), 2) for v in s]
out = {"asof": str(P.dates[-1].date()), "dates": [int(d.strftime("%Y%m%d")) for d in P.dates], "ks": nn(P.kospi), "kq": nn(P.kosdaq),
       "both60": both60, "KS": list(KS), "HS": list(HS), "stocks": stocks, "ev": ev}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"maangle: asof {out['asof']} · 신호 후보 {len(ev['i']):,} (마지막 날 {sum(1 for x in ev['i'] if x == last)}) · 종목 {len(stocks):,} · "
      f"{OUT.stat().st_size / 1e6:.1f}MB → {OUT}")
