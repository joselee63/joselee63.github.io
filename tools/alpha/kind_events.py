"""KIND 이벤트 공시 → 이후 초과수익 (유상증자·CB·BW·자사주·무상증자·공급계약·최대주주변경).
python tools/alpha/kind_events.py

시점: 공시 시각 < 08:30 → 그날 시가 매수, 그 외(장중·장후) → 다음 거래일 시가 매수.
[정정] 공시·종속회사 공시 제외. 같은 종목·같은 유형은 20거래일 안에 한 번만.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, base_mask, fwd, load_panel  # noqa: E402
from kr_analyst import show  # noqa: E402

KD = ROOT / "data-alpha" / "kind"


def load(P, key):
    f = KD / f"{key.replace('ㆍ', '_')}.csv"
    d = pd.read_csv(f, dtype=str)
    d = d[(d["corr"] != "True") & ~d["title"].str.contains("종속회사|자회사", na=False)]
    d["t"] = pd.to_datetime(d["time"])
    first5 = {}
    for t in P.tickers:
        first5.setdefault(t[:5], t)
    d["ticker"] = d["kind_code"].str.zfill(5).map(first5)
    d = d.dropna(subset=["ticker"])
    day = d["t"].dt.normalize()
    pre = (d["t"].dt.hour * 60 + d["t"].dt.minute) < 8 * 60 + 30
    ent = np.where(pre, P.dates.searchsorted(day, "left"), P.dates.searchsorted(day, "right"))
    d["i"] = ent - 1                                  # 신호 행 (fwd 는 i+1 시가 매수)
    d["j"] = d["ticker"].map(P.ti)
    d["date"] = d["t"]
    d = d[(d["i"] >= 0) & (d["i"] < P.T - 62)].sort_values(["ticker", "i"])
    keep, last = [], {}
    for idx, tk, i in zip(d.index, d["ticker"], d["i"]):
        if i - last.get(tk, -99) >= 20:
            keep.append(idx); last[tk] = i
    return d.loc[keep]


def attach(P, d, liq=True):
    m = base_mask(P, liq=liq)
    d = d[m[d["i"], d["j"]]].copy()
    for H in (1, 5, 20, 60):
        R = fwd(P, H)
        mu = np.nanmean(np.where(m, R, np.nan), axis=1)
        d[f"x{H}"] = R[d["i"], d["j"]] - mu[d["i"]]
    # 공시 직전 20일 수익률 (이미 오른 뒤인지)
    c = P.c
    d["pre20"] = c[d["i"], d["j"]] / c[np.maximum(d["i"] - 20, 0), d["j"]] - 1
    return d.dropna(subset=["x20"])


if __name__ == "__main__":
    P = load_panel()
    print("== 공시 이벤트 → 유니버스 대비 초과수익 % (괄호 = 월별 NW t) ==")
    for key in ["유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정", "자기주식취득결정",
                "자기주식취득신탁계약체결결정", "무상증자결정", "단일판매ㆍ공급계약체결", "최대주주변경"]:
        try:
            raw = load(P, key)
        except FileNotFoundError:
            print(f"  {key}: 데이터 없음"); continue
        for liq in (True, False):
            e = attach(P, raw, liq)
            lab = key + ("" if liq else " (유동성 무관)")
            show(e, np.ones(len(e), bool), lab)
        e = attach(P, raw, True)
        if key == "유상증자결정":
            for sub in ("제3자배정", "주주배정", "일반공모"):
                show(e, e["title"].str.contains(sub).to_numpy(), f"  └ {sub}")
        if key.startswith("자기주식"):
            show(e, (e["pre20"] < -0.1).to_numpy(), "  └ 직전 20일 −10% 이하")
        if key == "단일판매ㆍ공급계약체결":
            show(e, (e["pre20"] < 0).to_numpy(), "  └ 직전 20일 하락")
            show(e, e["market"].eq("유가증권").to_numpy(), "  └ 유가증권")
