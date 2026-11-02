"""퀀트 페이지 '터틀 트레이딩' · '터틀 수프' 백테스트용 일봉 → web/turtle.bin  (한국만)
python tools/closebet/export_turtle.py   (TURTLE_OUT 으로 출력 경로, BACKTEST_DIR · ALPHA_CACHE 로 일봉 패널 변경 가능)
매일 갱신: .github/workflows/closebet.yml (export_maangle.py 뒤 — 같은 패널 캐시를 씀) → 릴리스 closebet-data → daily.yml 이 사이트에 넣음

터틀은 불타기·N 손절·채널 청산이 서로 얽혀 미리 계산해 둘 조합이 너무 많으므로, 상장폐지 포함 전 종목의 일봉(시·고·저·종)을
압축해 보내고 규칙은 브라우저(quant.html 의 터틀 엔진)가 계산한다.

담는 범위: 20일 평균 거래대금 30억↑(그날 또는 전날)인 날마다 [그날 −60거래일, 가장 느슨한 청산(종가가 직전 20일 최저가 아래) 뒤 + 여유]
  → 매수 가능한 날의 과거 55일 채널·20일 평균 진폭(N)과, 그날 산 포지션이 끝날 때까지의 봉이 모두 들어감
가격: 로그 가격을 STEP(0.2%) 단위 정수로 — 시가는 앞날 종가와의 차이(갭), 종가는 시가와의 차이(몸통), 고가는 max(시,종) 위, 저가는 min(시,종) 아래
      (누적 오차 없음 · 가격 오차 ±0.1%)

파일 = gzip( [헤더 길이 4바이트 LE][헤더 JSON][면 g][면 b][면 h][면 l][면 v][면 f] )
  헤더: asof · step · dates(yyyymmdd) · stocks[{c,n,m,x}] · seg[[종목, 시작 날 번호, 길이, 첫날 앞 종가 수준]] · ks · kq(지수 종가) · tvcls · esc(면별 넘침 값)
  면 g/b/h/l: int8 (−128 이면 esc 목록에서 다음 값) · v: 20일 평균 거래대금 등급(tvcls 몇 개 이상인가, 0~5)의 앞날 차이(uint8, 256 순환)
  면 f: 비트0 거래 없음(정지) · 비트1 25일 지수이평 > 350일 지수이평 · 비트2 종가 > 200일선 · 비트3 종가 ≥ 52주 최고 종가 × 0.875
        · 비트4 거래량 ≥ 직전 20일 평균 × 2
"""
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "alpha"))
from common import load_panel  # noqa: E402

OUT = Path(os.environ.get("TURTLE_OUT", ROOT / "web" / "turtle.bin"))
STEP = 0.002          # 로그 가격 단위 (0.2%)
FLOOR = 3e9           # 담는 기준: 20일 평균 거래대금 30억
LB = 60               # 매수일 앞 과거 봉 (55일 채널 + 여유)
TAILMIN = 23          # 매수일 뒤 최소 봉 (수프 최대 20일 보유 + 다음날 매수)
TVCLS = (30, 50, 100, 300, 1000)   # 거래대금 등급 경계 (억) — 페이지의 거래대금 선택지

P = load_panel()
T, N = P.T, P.N
o, h, l, c, v = (a.copy() for a in (P.o, P.h, P.l, P.c, P.v))
fin = np.isfinite(c) & np.isfinite(o) & np.isfinite(h) & np.isfinite(l)
with np.errstate(invalid="ignore"):
    h = np.where(fin, np.fmax(h, np.fmax(o, c)), np.nan)          # 고가 < 시·종가 같은 원자료 오류 정리
    l = np.where(fin, np.fmin(l, np.fmin(o, c)), np.nan)

# ---- 종목별 파생 비트 (전체 기간으로 계산 — 잘린 구간이어도 값이 같게)
cf = pd.DataFrame(np.where(fin, c, np.nan)).ffill()
cnt = pd.DataFrame(fin.astype(float)).cumsum().to_numpy()
ema25 = cf.ewm(span=25, adjust=False).mean().to_numpy()
ema350 = cf.ewm(span=350, adjust=False).mean().to_numpy()
ma200 = cf.rolling(200, min_periods=200).mean().to_numpy()
hi252 = cf.rolling(252, min_periods=120).max().to_numpy()
vv = pd.DataFrame(np.where(fin, v, np.nan))
v20p = vv.shift(1).rolling(20, min_periods=15).mean().to_numpy()
with np.errstate(invalid="ignore"):
    flag = (~fin).astype(np.uint8)
    flag |= ((ema25 > ema350) & (cnt >= 250) & fin).astype(np.uint8) << 1
    flag |= ((c > ma200) & fin).astype(np.uint8) << 2
    flag |= ((c >= hi252 * 0.875) & fin).astype(np.uint8) << 3
    flag |= ((v >= 2 * v20p) & fin).astype(np.uint8) << 4
tv0 = np.where(np.isfinite(P.tv20), P.tv20, 0)
tvb = np.zeros((T, N), np.int32)
for x in TVCLS:
    tvb += tv0 >= x * 1e8

# ---- 담을 날 고르기
lowmin = pd.DataFrame(np.where(fin, l, np.nan)).rolling(20, min_periods=1).min().shift(1).to_numpy()
with np.errstate(invalid="ignore"):
    brk = fin & (c < lowmin)                                       # 가장 느슨한 청산: 종가가 직전 20일 최저가 아래
nb = np.full((T, N), T - 1, np.int32)
nxt = np.full(N, T - 1, np.int32)
for t in range(T - 1, -1, -1):
    nb[t] = nxt
    nxt = np.where(brk[t], t, nxt)
liq = (P.tv20 >= FLOOR) & fin
liq[1:] |= (P.tv20[:-1] >= FLOOR) & fin[1:]                         # 전날 거래대금으로 판단하는 날도 포함
ii, jj = np.nonzero(liq)
end = np.minimum(np.maximum(nb[ii, jj], ii + TAILMIN) + 2, T)
diff = np.zeros((T + 1, N), np.int32)
np.add.at(diff, (np.maximum(ii - LB, 0), jj), 1)
np.add.at(diff, (end, jj), -1)
inc = np.cumsum(diff, 0)[:T] > 0
first = np.argmax(fin, 0)
last = T - 1 - np.argmax(fin[::-1], 0)
ti = np.arange(T)[:, None]
inc &= (ti >= first) & (ti <= last) & fin.any(0)

# ---- 부호화
with np.errstate(invalid="ignore", divide="ignore"):
    qc = np.round(np.log(c) / STEP)
    qo = np.round(np.log(o) / STEP)
    qh = np.round(np.log(h) / STEP)
    ql = np.round(np.log(l) / STEP)
segs, planes = [], {k: [] for k in "gbhlvf"}
for j in range(N):
    col = inc[:, j]
    if not col.any():
        continue
    idx = np.nonzero(col)[0]
    cut = np.nonzero(np.diff(idx) > 1)[0]
    for seg in np.split(idx, cut + 1):
        f = fin[seg, j]
        if not f.any():
            continue
        s = pd.Series(np.where(f, qc[seg, j], np.nan)).ffill().bfill().to_numpy()      # 종가 수준 (정지 날은 앞 값)
        pv = np.concatenate([[s[0]], s[:-1]])                                           # 앞날 종가 수준
        qoo = np.where(f, qo[seg, j], s)
        gg = np.where(f, qoo - pv, 0)                                                   # 갭
        bb = np.where(f, s - qoo, 0)                                                    # 몸통 (정지 날 0 → 종가 유지)
        mx = np.maximum(qoo, s)
        mn = np.minimum(qoo, s)
        hh = np.where(f, qh[seg, j] - mx, 0)
        ll = np.where(f, mn - ql[seg, j], 0)
        tb = tvb[seg, j]
        vd = np.diff(np.concatenate([[0], tb])) % 256
        segs.append([int(j), int(seg[0]), int(len(seg)), int(s[0])])
        for k, a in zip("gbhl", (gg, bb, hh, ll)):
            planes[k].append(a.astype(np.int64))
        planes["v"].append(vd.astype(np.uint8))
        planes["f"].append(flag[seg, j].astype(np.uint8))

esc, blobs = {}, []
for k in "gbhl":
    a = np.concatenate(planes[k])
    bad = (a < -127) | (a > 127)
    esc[k] = a[bad].astype(int).tolist()
    b = np.where(bad, -128, a).astype(np.int8)
    blobs.append(b.tobytes())
for k in "vf":
    blobs.append(np.concatenate(planes[k]).tobytes())
D = sum(sg[2] for sg in segs)


def idx_list(arr):
    return [None if not np.isfinite(x) else round(float(x), 2) for x in arr]


stocks = [{"c": str(t), "n": P.name.get(t, str(t)), "m": "Q" if P.market.get(t) == "KOSDAQ" else "K", "x": 1 if t in P.delisted else 0}
          for t in P.tickers]
head = {"asof": P.dates[-1].strftime("%Y-%m-%d"), "step": STEP, "tvcls": list(TVCLS), "floor": FLOOR / 1e8,
        "dates": [int(d.strftime("%Y%m%d")) for d in P.dates], "stocks": stocks, "seg": segs, "days": D,
        "ks": idx_list(P.kospi), "kq": idx_list(P.kosdaq), "esc": esc}
hb = json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
raw = len(hb).to_bytes(4, "little") + hb + b"".join(blobs)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(gzip.compress(raw, 9))
print(f"turtle.bin {OUT.stat().st_size / 1e6:.2f}MB (풀면 {len(raw) / 1e6:.1f}MB) · 기준일 {head['asof']} · 날짜 {T} · 종목 {len({s[0] for s in segs})}"
      f" · 구간 {len(segs):,} · 봉 {D:,} · 넘침 " + " ".join(f"{k}{len(v)}" for k, v in esc.items()))
