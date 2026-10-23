"""퀀트 페이지 '종가베팅' 백테스트용 데이터 → web/closebet.json  (한국만)
python tools/closebet/export_web.py   (CLOSEBET_OUT 으로 출력 경로, BACKTEST_DIR 로 일봉 폴더 변경 가능)
매일 갱신: .github/workflows/closebet.yml (daily_data.py update → materialize → 이 스크립트 → 릴리스 closebet-data → daily.yml 이 사이트에 넣음)

무편향 일봉(상장폐지 포함, data-backtest/)에서 '후보가 될 수 있는 행'만 뽑아 브라우저가 조건을 바꿔 가며 백테스트할 수 있게 함.
  후보 행(마지막 날은 수익 null): 당일 +3% 이상 · 체결 가능(+28.5% 미만) · 상장 60일+ · 20일 평균 거래대금 10억+ · 청산 수익을 알 수 있음
  열(정수 압축): 날짜·종목 번호, 등락(×1e4), 고가권 위치(×1000), 거래량 배수(×100), 20일 평균 거래대금(억), 전날 시총(억),
                 장중 고가 등락(×1e4, 상한가 터치 판정), 수익(종가→다음 시가, 거래정지·상폐 반영, ×1e4), 테마 연속일, 상장 261일+
  등급 원자료: 종목·연도별 '체결 가능 +3% 신호'의 (건수, 다음날 시가 갭 합) — 브라우저가 연 1회 워크포워드 등급을 계산
  날짜별: 레짐 3종(KOSDAQ>20일선, KOSPI>60일선, 이전 체계 밤갭), 코스닥·코스피 종가
  panic: '패닉 낙주' 전략용 — 지수 시·고·저·종가, 시총 상위 20 경험 종목의 일봉과 날짜별 시총 순위(전날 기준)
large_cap.py 의 정의(RET·THEME·MC1·G.yearly_grades)를 그대로 가져다 씀 → 페이지 결과가 연구 표와 같아야 함.
"""
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import large_cap as L

P, G, T, N = L.P, L.G, L.T, L.N
OUT = Path(os.environ.get("CLOSEBET_OUT", L.CB.parent / "web" / "closebet.json"))

with np.errstate(invalid="ignore", divide="ignore"):
    VM = P.v / P.v20
    HI_T = P.h / P.prev - 1
    m = (P.day >= 0.03) & (P.day < 0.285) & (P.run >= 60) & (P.tv20 >= 1e9) & np.isfinite(P.c)
    m &= L.VALID | (np.arange(T) == T - 1)[:, None]          # 마지막 날은 수익을 아직 모름 → '최근 후보' 표시용 (r = null)
ii, jj = np.nonzero(m)
order = np.lexsort((jj, ii)); ii, jj = ii[order], jj[order]


def q(a, s, lo=None, hi=None, rnd=False):
    x = (np.round if rnd else np.floor)(a[ii, jj] * s)        # 기본 내림 → 문턱 비교(≥)가 원본과 정확히 같음
    if lo == "null":
        return [int(v) if np.isfinite(v) else None for v in x.tolist()]
    x = np.where(np.isfinite(x), x, -1 if lo is None else lo)
    if hi is not None:
        x = np.minimum(x, hi)
    return x.astype(np.int64).tolist()


used = np.unique(jj)
remap = -np.ones(N, np.int64); remap[used] = np.arange(len(used))

# 등급 원자료: 종목·연도별 체결 가능 +3% 신호 (건수, 갭 합) — G.yearly_grades 와 같은 신호·갭
yrs = sorted(set(G.yr)); y0 = 2015
gs, gn = [], []
X = np.where(G.SIG_BUY, G.GAP, np.nan)
for y in range(y0, max(yrs) + 1):
    r = G.yr == y
    gn.append(np.isfinite(X[r]).sum(0)); gs.append(np.nansum(X[r], 0))
gn = np.array(gn); gs = np.array(gs)
# 그해 등급 유니버스(LIQ_Y): 직전 250일 평균 거래대금 10억+ (연초 기준)
liq = np.array([L.LIQ_Y[np.argmax(G.yr == y)] for y in range(y0, max(yrs) + 1)])
gidx = np.nonzero((gn.sum(0) > 0) | liq.any(0))[0]

stocks = [{"c": P.tickers[j], "n": P.name.get(P.tickers[j], P.tickers[j]), "m": "Q" if P.is_kosdaq[j] else "K",
           "x": 1 if P.tickers[j] in P.delisted else 0} for j in used]
# 등급용 종목 중 후보에 없는 종목도 백분위 계산에는 들어가야 함 → 같은 목록에 추가
extra = [j for j in gidx if remap[j] < 0]
for j in extra:
    remap[j] = len(stocks)
    stocks.append({"c": P.tickers[j], "n": P.name.get(P.tickers[j], P.tickers[j]), "m": "Q" if P.is_kosdaq[j] else "K",
                   "x": 1 if P.tickers[j] in P.delisted else 0})

ix = G.ix


def idxc(code):
    return G.ix[G.ix["index_code"] == code].set_index("date")["close"].reindex(P.dates).ffill()


out = {
    "asof": P.dates[-1].strftime("%Y-%m-%d"),
    "dates": [d.strftime("%Y%m%d") for d in P.dates],
    "stocks": stocks,
    "reg": {"kq20": G.REG_KQ20.astype(int).tolist(), "ks60": np.asarray(P.mkt_ok).astype(int).tolist(),
            "old": G.REG_OLD.astype(int).tolist()},
    "kq": [None if pd.isna(v) else round(float(v), 2) for v in idxc("2001")],
    "ks": [None if pd.isna(v) else round(float(v), 2) for v in idxc("1001")],
    "rows": {
        "i": ii.tolist(), "j": remap[jj].tolist(),
        "d": q(P.day, 1e4), "p": q(P.pos, 1000), "v": q(VM, 100, hi=99999), "tv": q(P.tv20, 1e-8),
        "mc": q(L.MC1, 1e-8), "h": q(HI_T, 1e4), "r": q(L.RET, 1e4, lo="null", rnd=True), "th": L.THEME[ii, jj].astype(int).tolist(),
        "o": (P.run[ii, jj] >= 261).astype(int).tolist(),
        "hx": (L.HALT[ii, jj] | L.DELIST[ii, jj]).astype(int).tolist(),
    },
    "grade": {"y0": y0, "j": remap[gidx].tolist(),
              "n": gn[:, gidx].T.astype(int).tolist(), "s": np.round(gs[:, gidx].T * 1e4).astype(int).tolist(),
              "u": liq[:, gidx].T.astype(int).tolist()},
}
# ---------- 패닉일 낙주 (퀀트 '패닉 낙주' 전략) ----------
#   지수(코스피·코스닥) 일봉 시·고·저·종가 + '전날 시총 상위 20 안에 한 번이라도 들었던' 종목의 일봉과 날짜별 시총 순위
#   (순위 = 신호 전날 시총 기준, point-in-time · 상장폐지 종목도 포함)
def idx_ohlc(code):
    x = G.ix[G.ix["index_code"] == code].set_index("date").reindex(P.dates)
    return {k: [None if pd.isna(v) else round(float(v), 2) for v in x[k]] for k in ("open", "high", "low", "close")}


with np.errstate(invalid="ignore"):
    MCR = pd.DataFrame(L.MC1).rank(axis=1, ascending=False, method="first").to_numpy()
TOPN = 20
lead = np.nonzero(np.nanmin(np.where(MCR <= TOPN, MCR, np.inf), 0) <= TOPN)[0]


def px(a, j):
    return [None if not np.isfinite(v) else (int(round(v)) if v >= 100 else round(float(v), 2)) for v in a[:, j]]


out["panic"] = {
    "ks": idx_ohlc("1001"), "kq": idx_ohlc("2001"), "topn": TOPN,
    "stocks": [{"c": P.tickers[j], "n": P.name.get(P.tickers[j], P.tickers[j]), "x": 1 if P.tickers[j] in P.delisted else 0,
                "o": px(P.o, j), "h": px(P.h, j), "l": px(P.l, j), "c2": px(P.c, j),
                "rk": [int(r) if np.isfinite(r) and r <= TOPN else 0 for r in MCR[:, j]]} for j in lead],
}
print(f"panic: 상위{TOPN} 경험 종목 {len(lead)}개")
s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
OUT.write_text(s, encoding="utf-8")
print(f"rows {len(ii):,}  stocks {len(stocks):,}  grade stocks {len(gidx):,}  {len(s)/1e6:.1f}MB → {OUT}")
