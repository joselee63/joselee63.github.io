"""차트 게임 '영업이익 필터' 출제 조건용 실적 파일 만들기 (내 PC 에서 실행 → data-game/earn_kr.json 커밋)

규칙은 연구 '주도주 실적 검증' 검증 G 와 같음 (reports/주도주 사이클/실적 검증 사전 등록.md):
  · 분기 영업이익 성장률 g = 이번 분기 ÷ 전년 같은 분기 − 1 (흑자 전환 +1000%, 적자 전환 −1000%)
  · 알게 된 날 = 공시 접수일과 법정 기한(5/15 · 8/14 · 11/14 · 다음 해 3/31) 중 빠른 날
    (접수가 평소에도 기한보다 45일 넘게 늦는 회사 = 12월 결산이 아닌 회사 → 접수일 그대로), 그다음 거래일부터 사용
  · 성장률 백분위 = 전월 말 시가총액 5000억 원 이상 종목들의 g 분포 안에서의 위치 (그달 내내 같은 기준)
  · 흑자 = 최신 분기 영업이익 > 0 이고 최근 4분기 순이익 합 > 0 (4분기 합이 없으면 판단 안 함)

입력(내 PC 에만 있음): data-backtest/dart/quarters.csv (reports/주도주 사이클/스크립트/dart_fetch.py 로 수집)
                      data-alpha/alpha/cap/*/*.csv.gz (시점별 시가총액)
새 분기 실적이 나오면: dart_fetch.py 로 수집 → build → 이 스크립트 → data-game/earn_kr.json 커밋
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data-game" / "earn_kr.json"
BIG = 10.0
CAPMIN = 5e11


def growth(cur, prv):
    g = np.where(prv > 0, cur / prv - 1, np.nan)
    g = np.where((prv <= 0) & (cur > 0), BIG, g)
    return np.where((prv > 0) & (cur <= 0), -BIG, g)


def load_quarters():
    Q = pd.read_csv(REPO / "data-backtest" / "dart" / "quarters.csv", dtype={"tk": str, "rdate": str})
    Q = Q.sort_values(["tk", "year", "q"]).reset_index(drop=True)
    Q["g"] = growth(Q.op.to_numpy(), Q.op_p.to_numpy())
    Q["idx"] = Q.year * 4 + Q.q
    prev_ok = (Q.tk == Q.tk.shift(1)) & (Q.idx == Q.idx.shift(1) + 1)
    ok4 = prev_ok & prev_ok.shift(1, fill_value=False) & prev_ok.shift(2, fill_value=False)
    ttm_ni = Q.ni.rolling(4).sum().where(ok4)
    Q["prof"] = np.where(ttm_ni.notna() & Q.op.notna(), ((Q.op > 0) & (ttm_ni > 0)).astype(float), np.nan)
    dl = {1: "-05-15", 2: "-08-14", 3: "-11-14"}
    dead = pd.to_datetime([f"{y + 1}-03-31" if q == 4 else f"{y}{dl[q]}" for y, q in zip(Q.year, Q.q)])
    rdt = pd.to_datetime(Q.rdate, format="%Y%m%d")
    far = Q.tk.map((rdt - dead).dt.days.groupby(Q.tk).median() > 45)
    Q["known"] = pd.to_datetime(np.where(far, rdt.to_numpy(), np.minimum(rdt.to_numpy(), dead.to_numpy())))
    Q["known"] = Q.groupby("tk")["known"].cummax()       # 앞 분기보다 늦게 알려진 분기가 있으면 뒤 분기도 그날 이후 (연구와 같음)
    return Q


def load_cap():
    fs = sorted((REPO / "data-alpha" / "alpha" / "cap").glob("*/*.csv.gz"))
    cp = pd.concat([pd.read_csv(f, dtype={"ticker": str, "date": str}, usecols=["date", "ticker", "mcap"]) for f in fs], ignore_index=True)
    cp["date"] = pd.to_datetime(cp["date"])
    return cp


def main():
    Q = load_quarters()
    cp = load_cap()
    days = np.sort(cp.date.unique())
    mon = pd.DatetimeIndex(days).to_period("M")
    month_ends = days[np.r_[mon[1:] != mon[:-1], True]]
    E = {tk: (g.known.to_numpy(), g.g.to_numpy()) for tk, g in Q.groupby("tk")}
    thr = {}
    for d in month_ends:
        c = cp[(cp.date == d) & (cp.mcap >= CAPMIN)]
        gs = []
        for tk in c.ticker:
            if tk not in E:
                continue
            kn, g = E[tk]
            j = np.searchsorted(kn, d, side="left") - 1          # 알게 된 날 < 그날 (다음 거래일부터 사용)
            if j >= 0 and np.isfinite(g[j]):
                gs.append(g[j])
        if len(gs) >= 50:
            use = (pd.Timestamp(d).to_period("M") + 1).strftime("%Y%m")   # 전월 말 기준값을 다음 달에 사용
            thr[use] = [round(float(x), 4) for x in np.quantile(gs, np.arange(1, 100) / 100)]
    q = {}
    for tk, g in Q.groupby("tk"):
        q[tk] = [[int(k.strftime("%Y%m%d")), None if not np.isfinite(x) else round(float(x), 4), None if not np.isfinite(p) else int(p)]
                 for k, x, p in zip(g.known, g.g, g.prof)]
    OUT.parent.mkdir(exist_ok=True)
    meta = {"asof": int(Q.known.max().strftime("%Y%m%d")), "capmin": CAPMIN, "big": BIG}
    OUT.write_text(json.dumps({"meta": meta, "thr": thr, "q": q}, separators=(",", ":")), encoding="utf-8")
    print("월 기준", len(thr), f"({min(thr)}~{max(thr)})", "· 종목", len(q), "·", round(OUT.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
