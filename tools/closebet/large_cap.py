"""§9. 대형주 조건 — 20일 평균 거래대금 ≥300억 AND 시가총액 ≥5,000억 (point-in-time) 에서 세 체계 비교 + 대형주 풀 재최적화
python tools/closebet/large_cap.py [T][O]   (T: 비교표, O: 대형주 재최적화; 기본 둘 다)

공통: 기간 2018-01 ~ 2026-10 (이전 등급 체계가 2015~ 데이터로 등급을 만들 수 있는 첫 해 이후), 비용 0.25%,
      매수 t일 종가(체결 가능: 당일 +28.5% 미만), 매도 t+1 시가.
      ★ 거래정지: 다음날 시가가 없으면 '재개 후 첫 시가'로 청산, 상장폐지면 마지막 종가로 청산 (손실 반영, 표본에서 빼지 않음)
시총: data 브랜치 alpha/cap 일별 mcap 의 '신호 전날' 값. 거래대금: 20일 평균(수정종가×수정거래량, 당일 포함 — 15:20 근사).
계좌 지표(MDD·샤프·용량): 3슬롯 각 1/3 투입, 후보가 3개 미만이면 남는 슬롯은 현금.
"""
import sys
import numpy as np
import pandas as pd
from cb import CB, stats, nw_t, peer_sets
import grades_wf as G

P, T, N = G.P, G.T, G.N
COST = 0.0025
START = pd.Timestamp("2018-01-01")

# ------------------------------------------------------------ 청산 (거래정지·상폐 반영)
nxt_idx = np.full((T, N), -1, np.int32); cur = np.full(N, -1, np.int32)
fo = np.isfinite(P.o) & np.isfinite(P.c)
for t in range(T - 1, -1, -1):
    nxt_idx[t] = cur
    cur = np.where(fo[t], t, cur)
lastc = pd.DataFrame(P.c).ffill().to_numpy()
EXIT = np.full((T, N), np.nan); HALT = np.zeros((T, N), bool); DELIST = np.zeros((T, N), bool)
rows_t = np.arange(T)[:, None]
s = nxt_idx
ok = s >= 0
EXIT[ok] = P.o[s[ok], np.nonzero(ok)[1]]
HALT = ok & (s > rows_t + 1)
dl = np.isin(P.tickers, list(P.delisted))[None, :] & ~ok & np.isfinite(P.c)
EXIT[dl] = lastc[-1][np.nonzero(dl)[1]]           # 상폐: 데이터의 마지막 종가(정리매매 포함)
DELIST = dl
with np.errstate(invalid="ignore", divide="ignore"):
    RET = EXIT / P.c - 1

# ------------------------------------------------------------ 조건
MC1 = np.vstack([np.full((1, N), np.nan), G.MC[:-1]])               # 신호 전날 시총
with np.errstate(invalid="ignore"):
    LARGE = (P.tv20 >= 3e10) & (MC1 >= 5e11)
    BUY = np.isfinite(P.c) & (P.day < 0.285)
    BASE = (P.day >= 0.03) & (P.v > 2 * P.v20) & (P.pos >= 0.7) & P.liq & np.isfinite(P.sd60) & (P.run >= 261) & BUY
    HI_T = P.h / P.prev - 1
    FINAL = BASE & (P.day < 0.25) & (HI_T < 0.285)
    SIG3 = (P.day >= 0.03) & (P.run >= 60) & BUY                         # 이전 체계 신호 (+3%만)
VALID = np.isfinite(RET)
TOP = (P.pos >= 0.999).astype(float)

# 테마 연속일 (가격상관 동료 10, +3%↑ 3개 이상) — 전 종목·전 기간
ps = peer_sets(P); keys = np.array(sorted(ps))
up3 = (P.day >= 0.03).astype(np.int8)
hot = np.zeros((T, N), bool)
for a, k0 in enumerate(keys):
    k1 = keys[a + 1] if a + 1 < len(keys) else T
    peers = ps[k0][0]; okp = peers[:, 0] >= 0
    cnt = up3[k0:k1][:, np.where(okp[:, None], peers, 0)].sum(2)
    hot[k0:k1] = (cnt >= 3) & okp[None, :]
THEME = np.zeros((T, N), np.int16)
for t in range(T):
    THEME[t] = np.where(hot[t], (THEME[t - 1] if t else 0) + 1, 0)

# 등급 (연 1회 워크포워드, 2015~ 확장, 체결가능 +3% 신호, 거래대금 10억+ 종목 안 백분위)
LIQ_Y = G.yearly_universe(G.amt250, 99999, 1e9)
GM, GQ, GP = G.yearly_grades(G.SIG_BUY, LIQ_Y, COST, minn=60, start="2015-01-01")
GMc, GQc, GPc = G.yearly_grades(G.SIG_BUY, G.PIT_CAP, COST, minn=60, start="2015-01-01")   # 이전 체계 원래 유니버스
REG_KQ = G.REG_KQ20; REG_KS = P.mkt_ok


def pick(mask, keys_arr, k=3):
    """mask: 후보, keys_arr: 정렬키 배열 리스트(큰 값 우선). 반환 DataFrame(i,j,ret,...)"""
    m = mask & VALID
    m[:np.searchsorted(P.dates, START)] = False
    ii, jj = np.nonzero(m)
    d = pd.DataFrame({"i": ii, "j": jj})
    cols = []
    for n, a in enumerate(keys_arr):
        d[f"k{n}"] = a[ii, jj]; cols.append(f"k{n}")
    d = d.sort_values(["i"] + cols, ascending=[True] + [False] * len(cols))
    d["ncand"] = d.groupby("i")["j"].transform("size")
    d = d.groupby("i").head(k).copy()
    d["date"] = P.dates[d["i"]]
    d["ret"] = RET[d["i"], d["j"]]; d["amt"] = P.amt[d["i"], d["j"]]
    d["halt"] = HALT[d["i"], d["j"]]; d["delist"] = DELIST[d["i"], d["j"]]
    return d


def row(lab, d, k=3):
    s = d.groupby("date")["ret"].mean()
    r = stats(s, cost=COST, label=lab)
    acct = ((d["ret"] - COST) / k).groupby(d["date"]).sum()
    alld = P.dates[(P.dates >= START)]
    acct_full = acct.reindex(alld).fillna(0.0)
    eq = (1 + acct_full).cumprod(); mdd = (eq / eq.cummax() - 1).min()
    shp = acct_full.mean() / acct_full.std() * np.sqrt(250)
    yrs = (alld[-1] - alld[0]).days / 365.25
    nday = d["date"].nunique()
    lt3 = (d.groupby("date")["ncand"].first() < k).mean()
    cap = {}
    for acc in (1e8, 5e8, 1e9, 3e9):
        okd = (d["amt"] * 0.01 >= acc / k).groupby(d["date"]).all()
        cap[acc] = okd.mean()
    return dict(규칙=lab, 밤당=r.get("net", np.nan) * 100, t=r.get("t", np.nan), 승률=r.get("win", np.nan) * 100,
                연도=f"{r.get('yrpos',0)}/{r.get('yrn',0)}", 최악=r.get("worst", np.nan) * 100, 하위1=r.get("p1", np.nan) * 100,
                앞뒤=f"{r.get('first',np.nan)*100:+.2f}/{r.get('second',np.nan)*100:+.2f}",
                MDD=mdd * 100, 샤프=shp, 매매일비율=nday / len(alld) * 100, 연매매일=nday / yrs, 후보3미만=lt3 * 100,
                거래대금중앙억=d["amt"].median() / 1e8, 용량1억=cap[1e8] * 100, 용량5억=cap[5e8] * 100, 용량10억=cap[1e9] * 100,
                용량30억=cap[3e9] * 100, 정지=int(d["halt"].sum()), 상폐=int(d["delist"].sum()), 마10=int((d["ret"] <= -0.10).sum()),
                종목밤=len(d))


def fmt_table(rows):
    D = pd.DataFrame(rows)
    cols = ["규칙", "밤당", "t", "승률", "연도", "최악", "하위1", "MDD", "샤프", "매매일비율", "연매매일", "후보3미만", "거래대금중앙억",
            "용량1억", "용량5억", "용량10억", "용량30억", "정지", "상폐", "마10", "종목밤", "앞뒤"]
    return D[cols].round(2).to_string(index=False)


if __name__ == "__main__":
    ONLY = sys.argv[1] if len(sys.argv) > 1 else "TO"
    if "T" in ONLY:
        rows = []
        for cond, L in (("조건 없음", np.ones((T, N), bool)), ("대형(300억·5천억)", LARGE)):
            rows.append(row(f"① 기준선 · {cond}", pick(BASE & L & REG_KS[:, None], [P.pos, P.day])))
            rows.append(row(f"② 최종 규칙 · {cond}", pick(FINAL & L & REG_KQ[:, None], [TOP, THEME, P.day])))
            U = G.PIT_CAP if cond == "조건 없음" else L
            gp = GPc if cond == "조건 없음" else GP
            gm = GMc if cond == "조건 없음" else GM
            rows.append(row(f"③ 이전 등급(WF·KOSDAQ20) · {cond}", pick(SIG3 & U & REG_KQ[:, None] & (gp >= 0.8), [gm])))
        print("=== 비교표 (2018-01~2026-10, 비용 0.25%) — 밤당·최악·하위1 은 포트폴리오(%), MDD·샤프는 3슬롯 계좌, 용량 = 계좌별 '선택 3종목 모두 종목당 1/3이 그날 거래대금 1% 이내'인 날 비율(%)")
        print(fmt_table(rows))
        pd.DataFrame(rows).to_csv(CB / "large_cap_table.csv", index=False, encoding="utf-8-sig")
        print("대형 조건 충족 종목 수(일평균):", round(LARGE.sum(1)[P.dates >= START].mean(), 0),
              "| 그중 +3%·거래량2배·고가권 기준선 후보(일평균):", round((BASE & LARGE).sum(1)[P.dates >= START].mean(), 2))

    if "O" in ONLY:
        print("\n=== 대형주 풀 재최적화 (대형 조건, 2018~, 비용 0.25%, 상위 3) ===")
        res = []

        def test(lab, mask, keys, k=3):
            d = pick(mask, keys, k)
            r = row(lab, d, k)
            res.append(r)
            print(f"{lab:52} 밤당 {r['밤당']:+.2f}% t={r['t']:5.2f} 승 {r['승률']:3.0f}% 앞/뒤 {r['앞뒤']} 연도 {r['연도']} "
                  f"최악 {r['최악']:+.1f} MDD {r['MDD']:+.1f} 샤프 {r['샤프']:.2f} 연매매일 {r['연매매일']:.0f}")
        L = LARGE & BUY & (P.run >= 261)
        with np.errstate(invalid="ignore"):
            VM = P.v / P.v20
        print("-- 시장 필터 (신호 +3%·거래량2배·고가권, 정렬 고가권→등락률)")
        core = L & (P.day >= 0.03) & (VM > 2) & (P.pos >= 0.7)
        for rl, rg in (("없음", np.ones(T, bool)), ("KOSPI>60", REG_KS), ("KOSDAQ>20", REG_KQ), ("밤갭(이전)", G.REG_OLD)):
            test(f"시장 {rl}", core & rg[:, None], [P.pos, P.day])
        R = REG_KQ[:, None]
        print("-- 신호 문턱 (KOSDAQ>20, 정렬 고가권→등락률)")
        for up in (0.02, 0.03, 0.05, 0.07):
            for vm in (1.0, 1.5, 2.0, 3.0):
                test(f"등락 ≥{up*100:.0f}% · 거래량 ≥{vm}배", L & (P.day >= up) & (VM > vm) & (P.pos >= 0.7) & R, [P.pos, P.day])
        print("-- 고가권 문턱")
        for po in (0.0, 0.5, 0.7, 0.9):
            test(f"고가권 ≥{po}", L & (P.day >= 0.03) & (VM > 2) & (P.pos >= po) & R, [P.pos, P.day])
        print("-- 정렬 기준 (KOSDAQ>20, +3%·거래량2배·고가권0.7)")
        c2 = core & R
        GPf = np.nan_to_num(GP, nan=0.5)
        for lab, ks in (("고가권→등락률", [P.pos, P.day]), ("종가=고가→테마연속→등락률", [TOP, THEME, P.day]),
                        ("등락률", [P.day]), ("거래량배수", [VM]), ("등급", [GPf]), ("종가=고가→등급", [TOP, GPf]),
                        ("종가=고가→테마→등급", [TOP, THEME, GPf]), ("테마연속→고가권", [THEME, P.pos]),
                        ("고가권+등급 백분위 합", [np.nan_to_num(pd.DataFrame(np.where(c2, P.pos, np.nan)).rank(axis=1, pct=True).to_numpy()) + GPf])):
            test(f"정렬 {lab}", c2, ks)
        print("-- 등급 필터 (이전 체계식 +3%만 신호 vs 기준 신호)")
        for lab, m in (("+3%만, 등급 S·A, 등급순", SIG3 & LARGE & R & (GP >= 0.8)), ("+3%만, 등급 상위40%, 등급순", SIG3 & LARGE & R & (GP >= 0.6)),
                       ("+3%·거래량2배, 등급 S·A, 등급순", SIG3 & LARGE & R & (VM > 2) & (GP >= 0.8)),
                       ("+3%·고가권0.7, 등급 S·A, 등급순", SIG3 & LARGE & R & (P.pos >= 0.7) & (GP >= 0.8)),
                       ("+3%·고가권0.7·거래량2배, 등급 S·A", c2 & (GP >= 0.8))):
            test(lab, m, [GPf])
        print("-- 종목 수")
        for k in (1, 2, 3, 5):
            test(f"고가권→등락률 상위 {k}", c2, [P.pos, P.day], k)
        pd.DataFrame(res).to_csv(CB / "large_cap_opt.csv", index=False, encoding="utf-8-sig")

    if "R" in ONLY:
        print("\n=== 추천 후보(대형 조건 + 등급) 민감도 ===")
        R = REG_KQ[:, None]
        with np.errstate(invalid="ignore"):
            VM = P.v / P.v20

        def t2(lab, mask, keys, k=3, cost=COST):
            d = pick(mask, keys, k)
            s = d.groupby("date")["ret"].mean()
            r = stats(s, cost=cost, label=lab); rr = row(lab, d, k)
            print(f"{lab:46} 밤당 {r['net']*100:+.2f}% t={r['t']:5.2f} 승 {r['win']*100:3.0f}% 앞/뒤 {r['first']*100:+.2f}/{r['second']*100:+.2f} "
                  f"연도 {r['yrpos']}/{r['yrn']} 최악 {r['worst']*100:+.1f} MDD {rr['MDD']:+.1f} 샤프 {rr['샤프']:.2f} 연매매일 {rr['연매매일']:.0f}")
            return r
        for th in (0.5, 0.6, 0.7, 0.8, 0.9):
            t2(f"+3%, 등급 ≥{th:.1f}, 등급순", SIG3 & LARGE & R & (GP >= th), [GM])
        for mn in (30, 100):
            M2, Q2, P2 = G.yearly_grades(G.SIG_BUY, LIQ_Y, COST, minn=mn, start="2015-01-01")
            t2(f"+3%, 등급 ≥0.8 (최소신호 {mn}), 등급순", SIG3 & LARGE & R & (P2 >= 0.8), [M2])
        for up in (0.02, 0.05):
            t2(f"+{up*100:.0f}%, 등급 ≥0.8, 등급순", (P.day >= up) & (P.run >= 60) & BUY & LARGE & R & (GP >= 0.8), [GM])
        for vm in (1.5, 2.0):
            t2(f"+3%·거래량≥{vm}배, 등급 ≥0.6, 등급순", SIG3 & LARGE & R & (VM > vm) & (GP >= 0.6), [GM])
        for rl, rg in (("레짐 없음", np.ones(T, bool)), ("KOSPI>60", REG_KS), ("밤갭(이전)", G.REG_OLD)):
            t2(f"+3%, 등급 ≥0.8, {rl}", SIG3 & LARGE & rg[:, None] & (GP >= 0.8), [GM])
        for k in (1, 2, 5):
            t2(f"+3%, 등급 ≥0.8, 상위 {k}", SIG3 & LARGE & R & (GP >= 0.8), [GM], k)
        for c in (0.002, 0.003, 0.004):
            t2(f"+3%, 등급 ≥0.8, 비용 {c*100:.1f}%", SIG3 & LARGE & R & (GP >= 0.8), [GM], cost=c)
        d = pick(SIG3 & LARGE & R & (GP >= 0.8), [GM])
        print(stats(d.groupby("date")["ret"].mean(), cost=COST)["years"])
        # 내 최종 규칙과 같은 날 수익 상관 (조건 없음 최종 규칙 vs 대형 등급)
        a = pick(FINAL & REG_KQ[:, None], [TOP, THEME, P.day]).groupby("date")["ret"].mean()
        b = d.groupby("date")["ret"].mean()
        j = a.index.intersection(b.index)
        print(f"내 최종 규칙(전 종목) vs 대형 등급 체계: 같은 날 {len(j)}일, 수익 상관 {np.corrcoef(a[j], b[j])[0,1]:.2f}")
