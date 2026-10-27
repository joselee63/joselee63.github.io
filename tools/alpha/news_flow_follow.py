"""'뉴스로 튄 종목에 외인·기관 돈이 따라붙으면 계속 오른다' 가설 검증 (영상 'COF 종목필터' 주장)
python tools/alpha/news_flow_follow.py

이벤트(D일): 유동 종목(20일 평균 거래대금 10억↑·상장 60일↑)이 +5%↑(+28.5% 미만, 잠김 제외) & 거래량 전날까지 20일 평균의 3배↑,
           직전 20거래일 안에 같은 이벤트가 없던 '첫 급등'. 뉴스판 = 그날(전일 15:20~당일 15:20) 텔레그램 두 채널 언급 종목만.
따라붙음: D+1~D+3 외인+기관 순매수 합 ÷ 시총 (개인도 같이). 이 수급은 D+3 저녁에 확정 → 진입 = D+4 시가.
성과: D+4 시가 → h거래일 뒤 종가(5·10·20·40), 같은 D의 유동 종목 전체 평균 대비 초과. 상폐·정지는 마지막 종가.
t값은 같은 날 이벤트를 한 덩어리로 묶어 계산(날짜 평균의 t).
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_panel, roll  # noqa: E402
from flows_research import load_flows  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
P = load_panel()
T, N = P.T, P.N
F, mc, have = load_flows(P)
fpi = (F["frg"] + F.get("frg2", 0) + F["inst"]).astype(float)
ind = F["indiv"].astype(float)
c, o = P.c, P.o
cff = pd.DataFrame(c).ffill().to_numpy()
H = (5, 10, 20, 40)


def sh(a, s):
    """a[t+s] 를 t 자리에"""
    out = np.full_like(a, np.nan, dtype=float)
    if s > 0:
        out[:-s] = a[s:]
    else:
        out[-s:] = a[:T + s]
    return out


# ------------------------------------------------------------------ 이벤트
v20p = sh(P.v20, -1)
UNI = (P.tv20 >= 1e9) & (P.run >= 60) & np.isfinite(c)
with np.errstate(invalid="ignore"):
    POP = UNI & (P.day >= 0.05) & (P.day < 0.285) & (P.v >= 3 * v20p)
prior = roll(sh(POP.astype(float), -1), 20, "max", minp=1)
EV = POP & ~(np.nan_to_num(prior) > 0)
HV = np.broadcast_to(have[:, None], (T, N)).astype(float)
okf = (HV > 0) & (sh(HV, 3) > 0)                         # D 와 D+3 모두 수급 데이터 존재
EV &= okf & np.isfinite(mc)
EV[T - 48:] = False

# 수급 특징
S3f = sh(fpi, 1) + sh(fpi, 2) + sh(fpi, 3)
S3i = sh(ind, 1) + sh(ind, 2) + sh(ind, 3)
with np.errstate(invalid="ignore", divide="ignore"):
    X3 = S3f / mc
    X0 = fpi / mc
    I0 = ind / mc
STREAK3 = (sh(fpi, 1) > 0) & (sh(fpi, 2) > 0) & (sh(fpi, 3) > 0)
HOLD = sh(c, 3) >= c                                     # D+3 종가가 D 종가 이상 = 가격 버팀

# 성과: D+4 시가 → D+3+h 종가
o4 = sh(o, 4)
R = {}
BEN = {}
for h in H:
    with np.errstate(invalid="ignore", divide="ignore"):
        r = sh(cff, 3 + h) / o4 - 1
    R[h] = r
    m = UNI & np.isfinite(r)
    BEN[h] = np.where(m, r, 0).sum(1) / np.maximum(m.sum(1), 1)
with np.errstate(invalid="ignore", divide="ignore"):
    CONT20 = sh(cff, 20) / c - 1                          # D 종가 → D+20 종가 (지속 여부)

ti, tj = np.nonzero(EV)
ev = pd.DataFrame({"t": ti, "j": tj})
ev["date"] = P.dates[ti]
ev["yr"] = ev.date.dt.year
for nm, a in (("x3", X3), ("x0", X0), ("i0", I0), ("s3i", S3i), ("s3f", S3f), ("streak", STREAK3), ("hold", HOLD),
              ("cont20", CONT20), ("day", P.day)):
    ev[nm] = a[ti, tj]
for h in H:
    ev[f"r{h}"] = R[h][ti, tj]
    ev[f"x{h}"] = R[h][ti, tj] - BEN[h][ti]
ev = ev[np.isfinite(ev.r20) & np.isfinite(ev.x3)].reset_index(drop=True)

# ------------------------------------------------------------------ 뉴스(텔레그램 두 채널) 언급
names = {}
for j, tk in enumerate(P.tickers):
    nm = P.name.get(tk)
    if nm and len(nm) >= 2:
        names.setdefault(nm, j)
ALIAS = {"기아차": "000270", "POSCO": "005490", "삼전": "005930", "하닉": "000660", "삼바": "207940", "현차": "005380",
         "엔솔": "373220", "두산중공업": "034020"}
for a, tk in ALIAS.items():
    if tk in P.ti:
        names.setdefault(a, P.ti[tk])
pat = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
JOSA = set("은는이가을를의도와과로에만")
HANGUL = re.compile(r"[가-힣A-Za-z0-9]")
URL = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:com|co\.kr|kr|me|net|io)/\S*")


def stocks_in(text):
    text = URL.sub(" ", text)
    out = []
    for m in pat.finditer(text):
        nm = m.group(0)
        a, b = m.start(), m.end()
        if a > 0 and HANGUL.match(text[a - 1]):
            continue
        if len(nm) <= 2 and b < len(text) and re.match(r"[가-힣]", text[b]) and text[b] not in JOSA:
            continue
        if re.match(r"[A-Za-z0-9]", nm[-1]) and b < len(text) and re.match(r"[A-Za-z0-9]", text[b]):
            continue
        out.append(names[nm])
    return list(dict.fromkeys(out))


M = pd.concat([pd.read_pickle(ROOT / "data-alpha" / "telegram" / f"{n}.pkl") for n in ("surge_daily", "ch2")])
M = M[M.text.str.len() > 0]
M = M[M.text.map(lambda s: len(stocks_in(s)) <= 5)]            # 6종목↑ 목록 글은 뉴스로 보지 않음
dd = P.dates.normalize().values
day = M.dt.dt.normalize().values
tod = (M.dt.dt.hour * 60 + M.dt.dt.minute).to_numpy()
k = np.searchsorted(dd, day, side="left")
is_td = (k < T) & (dd[np.minimum(k, T - 1)] == day)
k = np.where(is_td & (tod >= 920), k + 1, k)                    # 15:20 이후 글은 다음 거래일 재료
M = M.assign(t=k, js=M.text.map(stocks_in))
E = M[M.t < T].explode("js").dropna(subset=["js"])
NEWS = np.zeros((T, N), bool)
NEWS[E.t.to_numpy(int), E.js.to_numpy(int)] = True
ev["news"] = NEWS[ev.t, ev.j]
tg_start = M.dt.min()
print(f"이벤트(첫 급등) {len(ev):,}건 ({ev.date.min():%Y-%m}~{ev.date.max():%Y-%m}) · 뉴스 확인 {ev.news.sum():,}건 (텔레그램 {tg_start:%Y-%m}~)")


# ------------------------------------------------------------------ 출력 도우미
def tstat(d, col):
    g = d.groupby("t")[col].mean()
    return g.mean() / (g.std(ddof=1) / np.sqrt(len(g))) if len(g) > 2 else np.nan


def line(lab, d, hs=H):
    if len(d) < 30:
        print(f"  {lab:30} 표본 {len(d)} (부족)"); return
    parts = []
    for h in hs:
        parts.append(f"{h}일 {d[f'x{h}'].mean()*100:+5.2f}%p(t{tstat(d, f'x{h}'):+4.1f})")
    print(f"  {lab:30} {len(d):6,}건 | " + " · ".join(parts) + f" | 20일 승률 {np.mean(d.x20 > 0)*100:3.0f}%")


def diff(lab, a, b, h=20):
    ya = a.groupby("yr")[f"x{h}"].mean(); yb = b.groupby("yr")[f"x{h}"].mean()
    dlt = (ya - yb).dropna()
    print(f"  {lab}: {h}일 차이 {(a[f'x{h}'].mean()-b[f'x{h}'].mean())*100:+.2f}%p · 연도별 " +
          " ".join(f"{y%100:02d}:{v*100:+.1f}" for y, v in dlt.items()) + f" → 플러스 {(dlt > 0).sum()}/{len(dlt)}년")


def section(title, d):
    print(f"\n== {title} ==  (초과 = 같은 날 유동 종목 평균 대비, 진입 D+4 시가)")
    print(f"  '계속 오름' 비율: D 종가→D+20 종가 +10%↑ {np.mean(d.cont20 > 0.10)*100:.0f}% · 플러스 {np.mean(d.cont20 > 0)*100:.0f}% (D+4 진입 전 구간 포함)")
    line("전체", d)
    a = d[(d.s3f > 0) & (d.s3i < 0)]; b = d[(d.s3f < 0) & (d.s3i > 0)]
    line("손바뀜 (외+기 매수·개인 매도)", a)
    line("개인만 (외+기 매도·개인 매수)", b)
    line("외+기 3일 연속 순매수", d[d.streak])
    q = d.x3.rank(pct=True)
    line("외+기 3일/시총 상위 1/3", d[q > 2 / 3])
    line("외+기 3일/시총 하위 1/3", d[q <= 1 / 3])
    diff("손바뀜 − 개인만", a, b)
    diff("상위1/3 − 하위1/3", d[q > 2 / 3], d[q <= 1 / 3])
    print("  -- 가격 버팀(D+3 종가 ≥ D 종가)과 겹치는지 2×2 --")
    for hl, hm in (("버팀", d.hold), ("밀림", ~d.hold)):
        line(f"{hl} & 외+기 매수", d[hm & (d.s3f > 0)])
        line(f"{hl} & 외+기 매도", d[hm & (d.s3f <= 0)])
    print("  -- D일(급등 당일) 누가 샀나 --")
    line("D일 외+기 순매수", d[d.x0 > 0])
    line("D일 개인만 순매수", d[(d.x0 <= 0) & (d.i0 > 0)])
    line("D일 개인만 → 이후 손바뀜", d[(d.x0 <= 0) & (d.i0 > 0) & (d.s3f > 0) & (d.s3i < 0)])


section("모든 첫 급등 (2015~)", ev)
section("뉴스 확인된 첫 급등 (텔레그램 언급)", ev[ev.news])
section("뉴스 없는 첫 급등 (텔레그램 기간만)", ev[~ev.news & (ev.date >= tg_start)])
ev.to_pickle(ROOT / "data-alpha" / "news_flow_events.pkl")
