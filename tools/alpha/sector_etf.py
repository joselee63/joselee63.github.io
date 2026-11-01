"""신고가 섹터(ETF판) — 업종·테마 ETF 가 '52주 신고가 영역'인지 판정하고, 이평각도 신호 종목에 섹터 꼬리표를 붙이는 엔진
데이터: data 브랜치 etf/ (tools/etf_data.py · etf-data.yml) 를 받아 둔 폴더 (기본 data-etf/etf, 환경변수 ETF_DIR)
  daily/YYYYMM.csv.gz  거래일별 전 종목 ETF 시세 (상장폐지 ETF 포함, 국내 주식형만)
  pdf/YYYYMMDD.csv     분기 첫 거래일 구성종목 스냅샷

시점 규칙
  · ETF 판정은 그날 종가까지의 ETF 일봉만 사용
  · 종목의 섹터 소속은 '그날 이전 가장 최근 스냅샷'의 구성종목 (분기 중 편입은 다음 스냅샷부터)
  · ETF 는 1년 이상 거래된 뒤부터 판정 (252일 전 가격·120일선이 필요) → 새로 생긴 테마 ETF 의 착시를 일부 차단
"""
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ETF_DIR = Path(os.environ.get("ETF_DIR", ROOT / "data-etf" / "etf"))

# 시장 전체·스타일·그룹 ETF (섹터가 아님) — 이름이나 기초지수에 있으면 제외
STYLE = re.compile(r"배당|가치|밸류|성장|퀄리티|로우볼|저변동|모멘텀|ESG|지배구조|스마트베타|우선주|동일가중|사회책임|기업가치|"
                   r"Value|Quality|Momentum|Dividend|LowVol|펀더멘털|대형|중형|소형|중소형|KTOP|TOP ?10|탑텐|그룹|"
                   r"코스피|KOSPI|코스닥|KOSDAQ|KRX ?300|KRX ?100|MSCI|K200|200|100|150|K-?뉴딜지수\(전체\)|액티브$")
# 위 규칙에 걸려도 '코스피 200 정보기술'처럼 업종 지수면 섹터로 인정
SECTOR_WORD = re.compile(r"정보기술|IT|에너지|화학|철강|소재|건설|중공업|금융|경기소비재|생활소비재|필수소비재|산업재|헬스케어|"
                         r"커뮤니케이션|미디어|반도체|은행|증권|보험|자동차|운송|조선|바이오|2차전지|배터리|방산|원자력|원전|"
                         r"게임|엔터|인터넷|소프트웨어|통신|유틸리티|기계|화장품|여행|레저|음식료|유통|제약")


def load_daily(dates):
    fs = sorted((ETF_DIR / "daily").glob("*.csv.gz"))
    dd = pd.concat([pd.read_csv(f, dtype={"ticker": str, "date": str}) for f in fs], ignore_index=True)
    dd["date"] = pd.to_datetime(dd["date"])
    close = dd.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").reindex(dates)
    value = dd.pivot_table(index="date", columns="ticker", values="value", aggfunc="last").reindex(dates)
    meta = dd.sort_values("date").groupby("ticker").agg(name=("name", "last"), index=("index", "last"),
                                                         first=("date", "min"), last=("date", "max"))
    return adjust_splits(close), value, meta


def adjust_splits(close):
    """국내 주식형 ETF 는 하루 ±30% 가 불가능 → 그런 점프는 분할·병합으로 보고 과거 가격을 맞춤"""
    c = close.copy()
    prev = c.ffill().shift(1)
    ratio = c / prev
    jump = (ratio < 0.7) | (ratio > 1.43)
    adj = ratio.where(jump, 1.0).fillna(1.0)
    # t 이후 모든 점프 배율의 곱을 t 의 가격에 곱함
    fac = adj[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    return c * fac


def load_pdf():
    snaps = {}
    for f in sorted((ETF_DIR / "pdf").glob("*.csv")):
        df = pd.read_csv(f, dtype={"etf": str, "code": str})
        snaps[pd.Timestamp(f.stem)] = df
    return snaps


def classify(meta, snaps, tickers_in_panel):
    """섹터 ETF 판정: 스타일·시장 전체가 아니고(업종 지수는 예외), 구성종목 5~59개, 국내 상장주 비중 70%↑"""
    nh, dom = {}, {}
    tset = set(tickers_in_panel)
    for d, df in snaps.items():
        for e, g in df.groupby("etf"):
            w = g["weight"].fillna(0)
            nh.setdefault(e, []).append(int((w > 0).sum()))
            dom.setdefault(e, []).append(float(w[g["code"].isin(tset)].sum()) / max(float(w.sum()), 1e-9))
    rows = []
    for e, r in meta.iterrows():
        txt = f"{r['name']} {r['index']}"
        style = bool(STYLE.search(txt)) and not bool(SECTOR_WORD.search(str(r["index"])) or SECTOR_WORD.search(str(r["name"]).split(" ", 1)[-1]))
        n = float(np.median(nh[e])) if e in nh else np.nan
        dm = float(np.median(dom[e])) if e in dom else np.nan
        sector = (not style) and 5 <= n <= 59 and dm >= 0.7
        rows.append((e, r["name"], r["index"], n, dm, style, sector))
    return pd.DataFrame(rows, columns=["etf", "name", "index", "n_hold", "dom", "style", "sector"]).set_index("etf")


def hot_flags(close, ms=60, ml=120, mom=252, rise=20, above=True, near=None):
    """'52주 신고가 영역' 섹터: 종가 > mom일 전 · ms일선 > ml일선 · 두 이평선 모두 rise일 전보다 위 · (선택) 종가 > ms일선
    near: 최근 near일 안에 252일 최고 종가를 찍었을 것 (변형)"""
    c = close
    a = c.rolling(ms, min_periods=ms).mean()
    b = c.rolling(ml, min_periods=ml).mean()
    ok = (c > c.shift(mom)) & (a > b) & (a > a.shift(rise)) & (b > b.shift(rise))
    if above:
        ok &= c > a
    if near:
        hi = c.rolling(252, min_periods=252).max()
        ok &= (c >= hi).astype(float).rolling(near, min_periods=1).max() > 0
    return ok.fillna(False)


def membership(snaps, sector_etfs, ti, wmin=1.0):
    """스냅샷 날짜 → (ETF → 패널 열 번호 배열, 종목 열 → ETF 목록)"""
    out = {}
    for d, df in snaps.items():
        g = df[df["etf"].isin(sector_etfs) & (df["weight"].fillna(0) >= wmin)].sort_values(["etf", "weight"], ascending=[True, False])
        e2j, j2e = {}, {}
        for e, gg in g.groupby("etf"):
            js = np.array([ti[c] for c in gg["code"] if c in ti], int)
            if len(js):
                e2j[e] = js
                for j in js:
                    j2e.setdefault(int(j), []).append(e)
        out[d] = (e2j, j2e)
    return out


def tag(cd, P, close, hot, mem, top=3, top_pct=None, by="ret60"):
    """신호 행마다 섹터 꼬리표: insec(섹터 ETF 소속) · hot(소속 ETF 중 신고가 영역 있음) · lead(그 신고가 ETF 안 주도주) · nhot"""
    dates = P.dates
    snap_d = sorted(mem)
    snap_i = np.searchsorted(dates, pd.DatetimeIndex(snap_d))
    hotv = hot.to_numpy()
    col = {e: k for k, e in enumerate(hot.columns)}
    c = P.c
    I = cd.i.to_numpy(); J = cd.j.to_numpy()
    insec = np.zeros(len(cd), bool); hh = np.zeros(len(cd), bool); ld = np.zeros(len(cd), bool); nhot = np.zeros(len(cd), int)
    for n, (i, j) in enumerate(zip(I, J)):
        k = np.searchsorted(snap_i, i, side="right") - 1
        if k < 0:
            continue
        e2j, j2e = mem[snap_d[k]]
        es = j2e.get(int(j), [])
        if not es:
            continue
        insec[n] = True
        for e in es:
            if e not in col or not hotv[i, col[e]]:
                continue
            hh[n] = True; nhot[n] += 1
            js = e2j[e]
            if by == "ret60":
                with np.errstate(invalid="ignore", divide="ignore"):
                    sc = c[i, js] / c[max(i - 60, 0), js] - 1
            else:   # 비중 순은 스냅샷 순서(비중 큰 순)를 그대로 — e2j 를 비중 순으로 만들었으므로 앞쪽이 대장
                sc = -np.arange(len(js), dtype=float)
            ok = np.isfinite(sc)
            if not ok[js == j].any():
                continue
            mine = sc[js == j][0]
            rank = int((sc[ok] > mine).sum())                       # 0 = 1등
            lim = top if top_pct is None else max(1, int(np.ceil(ok.sum() * top_pct)))
            if rank < lim:
                ld[n] = True
    out = cd.copy()
    out["insec"] = insec; out["hot"] = hh; out["lead"] = ld; out["nhot"] = nhot
    return out
