"""텔레그램 채널 언급 → 주가 반응 (무편향 일봉, 로컬 전용 데이터)
python tools/alpha/telegram_study.py <이름>      (data-alpha/telegram/<이름>.pkl ← telegram_parse.py)

1) 글마다 종목명 추출 (가장 긴 이름 우선, 두 글자 이름은 조사 외 한글이 붙으면 버림)
2) 언급 시각 → 시점 구분
   장전 (거래일 08:50 전, 휴장일 글은 다음 거래일 장전) : 진입 = 그날 시가
   장중 (09:00~15:20)                                  : 진입 = 그날 종가 (종베처럼 매수 가능)
   장후 (15:20~20:00, NXT 애프터) · 밤 (20:00~)        : 진입 = 다음날 시가 (참고: 종가→다음날 시가 갭)
3) 비교군 = 같은 날·같은 구간(장전은 '시가 갭' 구간, 장중·장후는 '당일 등락률' 구간)의 언급 안 된 종목 평균
   (거래대금 20일 평균 10억↑ · 상장 60일↑) → 초과수익 = 언급 종목 − 비교군
같은 날 같은 종목은 시점별 첫 언급만. 비용은 표시하지 않음(초과수익 비교라 상쇄).
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "closebet"))
import large_cap as L  # noqa: E402

P, T, N = L.P, L.T, L.N
name = sys.argv[1] if len(sys.argv) > 1 else "surge_daily"
M = pd.read_pickle(ROOT / "data-alpha" / "telegram" / f"{name}.pkl")
M = M[M.text.str.len() > 0].reset_index(drop=True)

# ------------------------------------------------------------------ 종목명 사전
names = {}
for j, tk in enumerate(P.tickers):
    nm = P.name.get(tk)
    if nm and len(nm) >= 2:
        names.setdefault(nm, j)
ALIAS = {"기아차": "000270", "POSCO": "005490", "삼전": "005930", "하닉": "000660", "삼바": "207940", "현차": "005380",
         "엔솔": "373220", "셀트리온헬스케어": "091990", "두산중공업": "034020", "현대중공업지주": "267250"}
for a, tk in ALIAS.items():
    if tk in P.ti:
        names.setdefault(a, P.ti[tk])
pat = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
JOSA = set("은는이가을를의도와과로에만")
HANGUL = re.compile(r"[가-힣A-Za-z0-9]")


URL = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:com|co\.kr|kr|me|net|io)/\S*")


def stocks_in(text):
    text = URL.sub(" ", text)                                     # 링크 주소 속 영문자가 종목명(LS·SK 등)으로 잡히지 않게
    out = []
    for m in pat.finditer(text):
        nm = m.group(0)
        a, b = m.start(), m.end()
        if a > 0 and HANGUL.match(text[a - 1]):
            continue                                              # 앞에 글자가 붙으면 다른 단어의 일부
        if len(nm) <= 2 and b < len(text) and re.match(r"[가-힣]", text[b]) and text[b] not in JOSA:
            continue                                              # 두 글자 이름 + 조사 아닌 한글 = 일반 단어일 가능성
        if re.match(r"[A-Za-z0-9]", nm[-1]) and b < len(text) and re.match(r"[A-Za-z0-9]", text[b]):
            continue                                              # 영문으로 끝나는 이름 뒤에 영문·숫자가 이어지면 다른 단어
        out.append(names[nm])
    return list(dict.fromkeys(out))


M["js"] = M.text.map(stocks_in)
M["ns"] = M.js.map(len)
M["kind"] = np.select([M.ns >= 6, M.text.str.contains("관련주"), M.link], ["목록", "관련주", "뉴스"], "코멘트")
print(f"[{name}] 본문 메시지 {len(M):,} · 종목 언급 메시지 {(M.ns > 0).sum():,} ({(M.ns > 0).mean():.0%}) · 언급 {M.ns.sum():,}건")
print("  종류:", M[M.ns > 0].kind.value_counts().to_dict())

# ------------------------------------------------------------------ 시점 → 거래일
dd = P.dates.normalize().values
tod = M.dt.dt.hour * 60 + M.dt.dt.minute
day = M.dt.dt.normalize().values
k = np.searchsorted(dd, day, side="left")                       # day 이상 첫 거래일
is_td = (k < T) & (dd[np.minimum(k, T - 1)] == day)
bucket = np.where(~is_td, "장전", np.where(tod < 530, "장전", np.where(tod < 540, "x", np.where(tod < 920, "장중", np.where(tod < 1200, "장후", "밤")))))
M["t"] = k; M["bk"] = bucket
E = M[(M.ns > 0) & (M.bk != "x") & (M.t < T - 6)].explode("js").rename(columns={"js": "j"})
E["j"] = E.j.astype(int)
E = E.sort_values("dt").drop_duplicates(["t", "j", "bk"])
print(f"  언급 이벤트(종목·날·시점 첫 언급) {len(E):,} · 시점별 {E.bk.value_counts().to_dict()}")

# ------------------------------------------------------------------ 수익 행렬
c, o = P.c, P.o
with np.errstate(invalid="ignore", divide="ignore"):
    DAY = P.day                                                   # 그날 등락 (종가/전일종가)
    GAPO = o / P.prev - 1                                         # 그날 시가 갭
    OC = c / o - 1                                                # 그날 시가→종가
    nx = lambda a, s: np.vstack([a[s:], np.full((s, N), np.nan)])
    R_CO1 = nx(o, 1) / c - 1                                      # 종가 → 다음날 시가
    R_CC1 = nx(c, 1) / c - 1                                      # 종가 → 다음날 종가
    R_CC5 = nx(c, 5) / c - 1                                      # 종가 → 5일 뒤 종가
    R_O1C1 = nx(c, 1) / nx(o, 1) - 1                              # 다음날 시가 → 종가
    R_O1C5 = nx(c, 5) / nx(o, 1) - 1                              # 다음날 시가 → 5일 뒤 종가
    R_OC5 = nx(c, 4) / o - 1                                      # 그날 시가 → 4일 뒤 종가 (5거래일)
    UNI = (P.tv20 >= 1e9) & (P.run >= 60) & np.isfinite(c) & np.isfinite(o)

BINS_DAY = np.array([-0.05, -0.02, 0.0, 0.03, 0.07, 0.15, 0.25])
BINS_GAP = np.array([-0.03, -0.01, 0.0, 0.01, 0.03, 0.07, 0.15])


def bucket_mean(R, KEY, bins, mention_mask):
    """날짜 × 구간별 비교군(언급 안 된 유동 종목) 평균"""
    B = np.digitize(np.nan_to_num(KEY, nan=-9), bins)
    ok = UNI & np.isfinite(R) & np.isfinite(KEY) & ~mention_mask
    out = np.full((T, len(bins) + 1), np.nan)
    for b in range(len(bins) + 1):
        m = ok & (B == b)
        s = np.where(m, R, 0).sum(1); n = m.sum(1)
        with np.errstate(invalid="ignore"):
            out[:, b] = np.where(n >= 5, s / np.maximum(n, 1), np.nan)
    return B, out


MENT = np.zeros((T, N), bool)
MENT[E.t.to_numpy(), E.j.to_numpy()] = True                     # 어떤 시점이든 그날 언급된 종목은 비교군에서 뺌


def excess(ev, R, KEY, bins):
    B, base = bucket_mean(R, KEY, bins, MENT)
    t, j = ev.t.to_numpy(), ev.j.to_numpy()
    r = R[t, j]; b = base[t, B[t, j]]
    ok = np.isfinite(r) & np.isfinite(b) & UNI[t, j]
    return r[ok], (r - b)[ok], ok


def line(lab, r, x):
    if len(x) < 20:
        print(f"    {lab:34} 표본 {len(x)} (부족)"); return
    tt = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    print(f"    {lab:34} {len(x):6,}건 · 평균 {r.mean()*100:+6.2f}% · 비교군 대비 {x.mean()*100:+6.2f}%p (t {tt:+5.1f}) · 승률 {np.mean(r > 0)*100:3.0f}%")


def yearly(ev, R, KEY, bins):
    r, x, ok = excess(ev, R, KEY, bins)
    yr = P.dates.year.to_numpy()[ev.t.to_numpy()[ok]]
    s = pd.Series(x).groupby(yr).agg(["mean", "size"])
    return " ".join(f"{y % 100:02d}:{m*100:+.2f}({n})" for y, (m, n) in s.iterrows())


tv = E.t.to_numpy(); jv = E.j.to_numpy()
E["dayret"] = DAY[tv, jv]; E["gap"] = GAPO[tv, jv]
print("\n0) 언급은 오르기 전인가 후인가 — 언급 당일 등락률 분포")
for bk in ("장전", "장중", "장후", "밤"):
    g = E[(E.bk == bk) & np.isfinite(E.dayret)]
    print(f"    {bk}: {len(g):,}건 · 당일 등락 중앙 {g.dayret.median()*100:+.1f}% · +5%↑ {np.mean(g.dayret >= 0.05)*100:.0f}% · +20%↑ {np.mean(g.dayret >= 0.2)*100:.0f}% · 하락 {np.mean(g.dayret < 0)*100:.0f}%")

print("\n1) 장전 언급 (진입 = 그날 시가, 비교군 = 같은 날 시가 갭이 비슷한 종목)")
pre = E[E.bk == "장전"]
for lab, R in (("그날 시가→종가", OC), ("시가→5거래일 종가", R_OC5)):
    r, x, _ = excess(pre, R, GAPO, BINS_GAP); line(lab, r, x)
for kd in ("뉴스", "관련주", "코멘트", "목록"):
    r, x, _ = excess(pre[pre.kind == kd], OC, GAPO, BINS_GAP); line(f"  {kd} · 그날 시가→종가", r, x)
print("    연도별(시가→종가 초과):", yearly(pre, OC, GAPO, BINS_GAP))

print("\n2) 장중 언급 (진입 = 그날 종가 = 종베, 비교군 = 같은 날 등락률이 비슷한 종목)")
intra = E[E.bk == "장중"]
for lab, R in (("종가→다음날 시가", R_CO1), ("종가→다음날 종가", R_CC1), ("종가→5일 뒤 종가", R_CC5)):
    r, x, _ = excess(intra, R, DAY, BINS_DAY); line(lab, r, x)
up = intra[intra.dayret >= 0.03]
r, x, _ = excess(up, R_CO1, DAY, BINS_DAY); line("  당일 +3%↑ 종목만 · 다음날 시가", r, x)
for kd in ("뉴스", "관련주", "코멘트", "목록"):
    r, x, _ = excess(intra[intra.kind == kd], R_CO1, DAY, BINS_DAY); line(f"  {kd} · 다음날 시가", r, x)
print("    연도별(다음날 시가 초과):", yearly(intra, R_CO1, DAY, BINS_DAY))

print("\n3) 장후·밤 언급 (참고: 종가→다음날 시가 갭 / 실제 진입 = 다음날 시가)")
aft = E[E.bk.isin(["장후", "밤"])]
for lab, R in (("[참고] 종가→다음날 시가 갭", R_CO1), ("다음날 시가→종가", R_O1C1), ("다음날 시가→5일 뒤 종가", R_O1C5)):
    r, x, _ = excess(aft, R, DAY, BINS_DAY); line(lab, r, x)
for bk in ("장후", "밤"):
    r, x, _ = excess(aft[aft.bk == bk], R_CO1, DAY, BINS_DAY); line(f"  {bk} · [참고] 다음날 시가 갭", r, x)
print("    연도별(갭 초과):", yearly(aft, R_CO1, DAY, BINS_DAY))

print("\n4) 반응(이모지) 많은 글 (2022~) — 장중·장후 언급, 다음날 시가 갭 초과")
rx = E[(E.dt >= "2022-01-01") & E.bk.isin(["장중", "장후", "밤"])].copy()
if len(rx) > 100:
    q = rx.react.quantile([0.5, 0.9]).to_numpy()
    for lab, g in (("반응 하위 50%", rx[rx.react <= q[0]]), ("반응 상위 10%", rx[rx.react >= q[1]])):
        r, x, _ = excess(g, R_CO1, DAY, BINS_DAY); line(lab + f" (≥{q[1]:.0f})" if "상위" in lab else lab, r, x)

print("\n5) 종베 후보(연구 규칙: +3%·거래량 2배·고가권, 코스닥>20일선)와 겹치면")
reg = L.REG_KQ if L.REG_KQ.ndim == 1 else L.REG_KQ.any(1)
cand = L.FINAL & reg[:, None] & np.isfinite(L.RET)
cand[: np.searchsorted(P.dates, pd.Timestamp("2019-08-01"))] = False
before = np.zeros((T, N), bool); after = np.zeros((T, N), bool)
gi = E[E.bk.isin(["장전", "장중"])]; before[gi.t.to_numpy(), gi.j.to_numpy()] = True
ga = E[E.bk.isin(["장후", "밤"])]; after[ga.t.to_numpy(), ga.j.to_numpy()] = True
active = np.zeros(T, bool); active[np.unique(E.t)] = True              # 채널이 활동한 날만
cand &= active[:, None]
for lab, m in (("언급 없음", cand & ~before & ~after), ("15:20 전 언급 있음 (판단에 사용 가능)", cand & before),
               ("장 마감 뒤 언급 (판단엔 못 씀)", cand & after & ~before)):
    r = L.RET[m] - L.COST
    if len(r) >= 20:
        print(f"    {lab:34} {len(r):6,}건 · 비용 후 밤수익 {r.mean()*100:+.2f}% · 승률 {np.mean(r > 0)*100:.0f}% · 중앙 {np.median(r)*100:+.2f}%")

print("\n7) 장후 언급 — 올린 시각별 다음날 시가 갭(참고)과 다음날 시가→종가")
aft2 = E[E.bk.isin(["장후", "밤"])].copy()
hm = aft2.dt.dt.hour * 60 + aft2.dt.dt.minute
for lab, lo, hi in (("15:20~16:00", 920, 960), ("16:00~18:00", 960, 1080), ("18:00~20:00", 1080, 1200), ("20:00~24:00", 1200, 1440)):
    g = aft2[(hm >= lo) & (hm < hi)]
    r, x, _ = excess(g, R_CO1, DAY, BINS_DAY); line(f"{lab} · [참고] 다음날 시가 갭", r, x)
    r, x, _ = excess(g, R_O1C1, DAY, BINS_DAY); line(f"{lab} · 다음날 시가→종가", r, x)

print("\n8) 재료 유형(글 속 키워드) — 장중·장후 언급")
CAT = [("수주·공급계약", r"수주|공급계약|계약 체결|납품|단일판매"), ("실적", r"실적|영업이익|매출액|흑자|어닝"),
       ("정책·정부", r"정부|정책|대통령|국회|법안|규제|지원금|예산"), ("임상·허가", r"임상|FDA|허가|승인|식약처|품목"),
       ("M&A·지분", r"인수|합병|M&A|지분|최대주주|경영권"), ("기술·특허", r"특허|개발 성공|세계 최초|국내 최초|기술이전"),
       ("해외·수출", r"수출|미국|중국|유럽|글로벌|해외"), ("테마·관련주", r"관련주|테마|대장주|수혜")]
ev2 = E[E.bk.isin(["장중", "장후", "밤"])].copy()
for lab, rg in CAT:
    g = ev2[ev2.text.str.contains(rg, regex=True)]
    gi_ = g[g.bk == "장중"]; ga_ = g[g.bk != "장중"]
    r1, x1, _ = excess(gi_, R_CO1, DAY, BINS_DAY)
    r2, x2, _ = excess(ga_, R_CO1, DAY, BINS_DAY)
    r3, x3, _ = excess(ga_, R_O1C1, DAY, BINS_DAY)
    f = lambda x: (f"{x.mean()*100:+.2f}%p(t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.1f}, {len(x):,})" if len(x) >= 20 else f"표본 {len(x)}")
    print(f"    {lab:12} 장중→다음날 시가 {f(x1)} | 장후→[참고]갭 {f(x2)} · 다음날 시가→종가 {f(x3)}")

print("\n6) 가장 많이 언급된 종목 (언급 이벤트 수)")
top = E.groupby("j").size().sort_values(ascending=False).head(15)
print("    " + " · ".join(f"{P.name.get(P.tickers[j], P.tickers[j])} {n}" for j, n in top.items()))
