"""종베 후보 × 텔레그램 뉴스 — 매수 시점(15:20)까지 나온 뉴스·시황이 다음날 시가 성적을 가르나
python tools/alpha/telegram_closebet.py <이름>      (data-alpha/telegram/<이름>.pkl, 로컬 전용)

후보: ① 전체(연구 최종 규칙: +3%·거래량 2배·고가권·거래대금 10억·상장 1년, 코스닥>20일선)
      ② 대형주 등급(시총 5천억·거래대금 300억·+3%·등급 상위 20%)
결과: 종가 매수 → 다음날 시가 매도, 비용 0.25% 후 (large_cap.RET: 거래정지·상폐 반영)
뉴스 창: '알고 살 수 있는 뉴스' = 전 거래일 15:20 ~ 신호일 15:20 / '매수 뒤 뉴스' = 15:20 ~ 다음날 08:50 (갭 설명용)
같은 날 비교: 같은 날 후보끼리 비교해 '좋은 날' 효과를 뺀 값(같은 날 평균 대비 %p)도 함께 봄
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
COST = L.COST

# ------------------------------------------------------------------ 종목명 추출 (telegram_study.py 와 같은 규칙)
names = {}
for j, tk in enumerate(P.tickers):
    nm = P.name.get(tk)
    if nm and len(nm) >= 2:
        names.setdefault(nm, j)
for a, tk in {"기아차": "000270", "POSCO": "005490", "삼전": "005930", "하닉": "000660", "삼바": "207940", "현차": "005380",
              "엔솔": "373220", "두산중공업": "034020"}.items():
    if tk in P.ti:
        names.setdefault(a, P.ti[tk])
pat = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
JOSA = set("은는이가을를의도와과로에만")
URL = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:com|co\.kr|kr|me|net|io)/\S*")


def stocks_in(text):
    text = URL.sub(" ", text)
    out = []
    for m in pat.finditer(text):
        nm, a, b = m.group(0), m.start(), m.end()
        if a > 0 and re.match(r"[가-힣A-Za-z0-9]", text[a - 1]):
            continue
        if len(nm) <= 2 and b < len(text) and re.match(r"[가-힣]", text[b]) and text[b] not in JOSA:
            continue
        if re.match(r"[A-Za-z0-9]", nm[-1]) and b < len(text) and re.match(r"[A-Za-z0-9]", text[b]):
            continue
        out.append(names[nm])
    return list(dict.fromkeys(out))


M["first"] = M.text.str.split("\n").str[0]
M["js"] = M.text.map(stocks_in)
M["js1"] = M["first"].map(stocks_in)                              # 첫 줄(제목)에 나온 종목 = 기사의 주인공
M["ns"] = M.js.map(len)
CAT = [("수주·계약", r"수주|공급계약|계약 체결|납품|단일판매"), ("실적", r"실적|영업이익|매출액|흑자|어닝|최대 매출"),
       ("정책·정부", r"정부|정책|대통령|국회|법안|규제|지원금|예산|정상회담"), ("임상·허가", r"임상|FDA|허가|승인|식약처|품목"),
       ("M&A·지분", r"인수|합병|M&A|지분|최대주주|경영권"), ("기술·특허", r"특허|개발 성공|세계 최초|국내 최초|기술이전|상용화"),
       ("해외·수출", r"수출|미국|중국|유럽|글로벌|해외|일본|중동"), ("테마·관련주", r"관련주|테마|대장주|수혜"),
       ("악재", r"유상증자|전환사채|하락|급락|적자|소송|횡령|배임|거래정지|불성실")]
for lab, rg in CAT:
    M[lab] = M.text.str.contains(rg, regex=True)

# ------------------------------------------------------------------ 후보 · 뉴스 창 연결
reg = L.REG_KQ if L.REG_KQ.ndim == 1 else L.REG_KQ.any(1)
start = np.searchsorted(P.dates, pd.Timestamp("2019-08-01"))
WIDE = L.FINAL & reg[:, None] & np.isfinite(L.RET)
LARGE = L.SIG3 & L.LARGE & (L.GP >= 0.8 - 1e-12) & np.isfinite(L.RET)
for m in (WIDE, LARGE):
    m[:start] = False
active = np.zeros(T, bool)
mt = np.searchsorted(P.dates.normalize().values, M.dt.dt.normalize().values, side="left")
active[np.unique(mt[mt < T])] = True                              # 채널이 글을 올린 날만 (공백기 제외)

dd = P.dates.values
buy = dd + np.timedelta64(15 * 60 + 20, "m")                      # t일 15:20
prev_buy = np.r_[dd[:1] - np.timedelta64(1, "D"), buy[:-1]]       # 전 거래일 15:20
next_open = np.r_[dd[1:], dd[-1:] + np.timedelta64(1, "D")] + np.timedelta64(8 * 60 + 50, "m")
mdt = M.dt.values


def window_rows(t, lo, hi):
    a, b = np.searchsorted(mdt, lo[t], "right"), np.searchsorted(mdt, hi[t], "right")
    return M.iloc[a:b]


def features(mask):
    ii, jj = np.nonzero(mask)
    rows = []
    cache = {}
    for i, j in zip(ii, jj):
        if not active[i]:
            continue
        if i not in cache:
            cache[i] = (window_rows(i, prev_buy, buy), window_rows(i, buy, next_open))
        pre, post = cache[i]
        pm = pre[pre.js.map(lambda x: j in x)]
        qm = post[post.js.map(lambda x: j in x)]
        r = {"i": i, "j": j, "ret": L.RET[i, j] - COST, "yr": P.dates[i].year, "day": P.day[i, j],
             "n": len(pm), "prim": bool(pm.js1.map(lambda x: j in x).any()), "react": int(pm.react.sum()),
             "list_only": bool(len(pm) and (pm.ns >= 6).all()), "link": bool(pm.link.any()),
             "morning": bool(len(pm) and (pm.dt.dt.hour < 9).any()), "post_n": len(qm),
             "cobreadth": int(pm.ns.max()) if len(pm) else 0}
        for lab, _ in CAT:
            r[lab] = bool(pm[lab].any()) if len(pm) else False
        rows.append(r)
    D = pd.DataFrame(rows)
    D["dm"] = D.groupby("i").ret.transform("mean")                 # 같은 날 후보 평균
    D["ex"] = D.ret - D.dm
    return D


def show(D, sel, lab):
    g = D[sel]
    if len(g) < 15:
        print(f"    {lab:30} 표본 {len(g)} (부족)"); return
    multi = g[D.loc[sel, "i"].map(D.i.value_counts()) > 1]           # 같은 날 후보가 2개 이상인 경우만 같은 날 비교
    ex = multi.ex
    tt = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))) if len(ex) > 2 else np.nan
    print(f"    {lab:30} {len(g):5,}건 · 비용 후 {g.ret.mean()*100:+.2f}% · 승률 {np.mean(g.ret > 0)*100:3.0f}% · 중앙 {g.ret.median()*100:+.2f}% "
          f"· 같은 날 평균 대비 {ex.mean()*100:+.2f}%p (t {tt:+.1f}, {len(ex):,})")


for title, mask in (("① 전체 종베 후보 (연구 규칙, 코스닥>20일선)", WIDE), ("② 대형주 등급 후보 (레짐 무관)", LARGE)):
    D = features(mask)
    print("=" * 110)
    print(f"{title} — 채널 활동일 {D.i.nunique():,}일 · 후보 {len(D):,}건 · 매수 전 뉴스 있음 {np.mean(D.n > 0)*100:.0f}%")
    show(D, D.n == 0, "뉴스 없음")
    show(D, D.n > 0, "뉴스 있음 (전체)")
    show(D, (D.n > 0) & D.prim, "  └ 주인공(제목에 등장)")
    show(D, (D.n > 0) & ~D.prim & ~D.list_only, "  └ 본문·관련주로만 등장")
    show(D, (D.n > 0) & D.list_only, "  └ 6종목↑ 목록에만 등장")
    show(D, (D.n > 0) & D.morning, "  └ 아침(장전) 뉴스")
    show(D, D.n >= 3, "  └ 3번 이상 언급")
    show(D, (D.n > 0) & (D.react >= 30), "  └ 반응 30↑ (2022~)")
    print("   재료 유형 (매수 전 뉴스에 키워드)")
    for lab, _ in CAT:
        show(D, D[lab], f"  {lab}")
    print("   매수 뒤(15:20~다음날 08:50) 뉴스 — 판단엔 못 쓰지만 갭 설명")
    show(D, D.post_n > 0, "  매수 뒤 언급 있음")
    show(D, D.post_n == 0, "  매수 뒤 언급 없음")
    yy = D[D.n > 0].groupby("yr").ret.mean() - D[D.n == 0].groupby("yr").ret.mean()
    print("   연도별 (뉴스 있음 − 없음, %p): " + " ".join(f"{y % 100:02d}:{v*100:+.2f}" for y, v in yy.items()))

# ------------------------------------------------------------------ 시황: 그날 채널 글의 분위기 → 그날 종베 포트폴리오
print("=" * 110)
print("③ 시황 — 그날(전일 15:20~당일 15:20) 채널 글의 분위기와 그날 전체 종베 후보 평균 (비용 후)")
neg = re.compile(r"급락|폭락|하락|약세|공포|패닉|우려|쇼크|긴축|관세")
pos = re.compile(r"급등|상승|강세|신고가|랠리|호재|훈풍|기대")
mac = re.compile(r"나스닥|미국 증시|뉴욕증시|S&P|다우|연준|FOMC|금리|환율|달러|코스피|코스닥|지수")
port = pd.Series(np.where(WIDE, L.RET - COST, np.nan).tolist()).map(lambda r: np.nanmean(r) if np.isfinite(r).any() else np.nan)
rows = []
for i in np.nonzero(active & np.isfinite(port.to_numpy()))[0]:
    w = window_rows(i, prev_buy, buy)
    if len(w) < 5:
        continue
    txt = w.text
    rows.append({"i": i, "port": port.iloc[i], "n": len(w), "neg": txt.str.contains(neg).mean(), "pos": txt.str.contains(pos).mean(),
                 "mac": txt.str.contains(mac).mean(), "react": w.react.mean()})
S = pd.DataFrame(rows)
S["tone"] = S.pos - S.neg
for col, lab in (("n", "글 수"), ("tone", "분위기(긍정−부정 비율)"), ("neg", "부정 단어 비율"), ("mac", "거시·지수 글 비율")):
    q = S[col].quantile([1 / 3, 2 / 3]).to_numpy()
    lo, mid, hi = S[S[col] <= q[0]], S[(S[col] > q[0]) & (S[col] <= q[1])], S[S[col] > q[1]]
    print(f"    {lab:22} 하위 1/3 {lo.port.mean()*100:+.2f}% ({len(lo)}) · 중간 {mid.port.mean()*100:+.2f}% · 상위 1/3 {hi.port.mean()*100:+.2f}% ({len(hi)})")
