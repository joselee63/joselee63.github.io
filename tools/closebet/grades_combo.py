"""§8 계속 — 레짐 비교, 최종 규칙 + walk-forward 등급 결합, 등급표 위험지표(하위1% 갭·갭 변동성)의 꼬리 관리 효용
python tools/closebet/grades_combo.py
등급 = 그날 이전 '+3% 신호일 다음날 시가 수익' 확장 평균 (전 종목, 매일 갱신). 백분위는 그날 n≥minn 인 종목들 안에서.
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, nw_t
import grades_wf as G

P, T, N = G.P, G.T, G.N
COST = 0.0025
LIQ_Y = G.yearly_universe(G.amt250, 99999, 1e9)        # 매년 초 거래대금(250일 평균) 10억+ 전 종목


def wf_grade(minn):
    """연 1회 워크포워드 등급 (2015~ 확장 창), 체결가능 +3% 신호, 비용 0.25% — 노트북 셀 10 과 같은 방식"""
    M, Q, pct = G.yearly_grades(G.SIG_BUY, LIQ_Y, COST, minn=minn, start="2015-01-01")
    return M, Q, pct


def wf_gapvol():
    """연 1회: 그해 이전 '비신호일 포함 전체' 밤 갭 표준편차 (노트북 quality() 의 갭 변동성)"""
    out = np.full((T, N), np.nan)
    for y in sorted(set(G.yr))[1:]:
        t0 = np.argmax(G.yr == y)
        with np.errstate(all="ignore"):
            v = np.nanstd(G.GAP[:t0], 0)
        v[np.isfinite(G.GAP[:t0]).sum(0) < 250] = np.nan
        out[G.yr == y] = v
    return out


if __name__ == "__main__":
    R = pd.read_pickle(CB / "_R.pkl").merge(pd.read_pickle(CB / "_theme.pkl"), on=["i", "j"])
    allc = pd.read_pickle(CB / "cands.pkl")
    C = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].copy()
    C["top"] = (C["pos"] >= 0.999).astype(int)

    print("======== 레짐 비교 (같은 데이터·비용 0.25%·체결 가능)")
    ok_old = pd.Series(G.REG_OLD, P.dates); ok_kq = pd.Series(G.REG_KQ20, P.dates)
    # 내 선별(기준선 후보 풀, 레짐만 바꿈) — 정렬은 고가권→등락률 (테마 연속일은 KOSDAQ>20일 날만 계산돼 있음)
    A = allc[(allc["day"] < 0.25)]
    for lab, ok in (("KOSPI>60 (기존 연구 기준선)", pd.Series(P.mkt_ok, P.dates)), ("KOSPI>120 & KOSDAQ>60 (이전 체계)", ok_old),
                    ("KOSDAQ>20 (이번 연구)", ok_kq), ("이전 체계 & KOSDAQ>20", ok_old & ok_kq), ("KOSDAQ>20 이지만 이전 체계는 쉼", ok_kq & ~ok_old),
                    ("이전 체계는 매매, KOSDAQ<20", ok_old & ~ok_kq)):
        d = A[A["date"].map(ok).fillna(False).astype(bool)].sort_values(["date", "pos", "day"], ascending=[True, False, False])
        s = d.groupby("date").head(3).groupby("date")["on"].mean()
        print(line(stats(s[s.index >= "2016-01-01"], label="내 후보·" + lab)))
    # 이전 체계(무편향 시총 상위200, 등급 WF 연1회, 위험비중)에서 레짐만 바꿈 — 2018~, 비용 0.25%
    My, Qy, py = G.yearly_grades(G.SIG_BUY, G.PIT_CAP, COST, start="2015-01-01")
    for lab, reg in (("밤갭 레짐(이전)", G.REG_OLD), ("KOSDAQ>20", G.REG_KQ20), ("둘 다", G.REG_OLD & G.REG_KQ20), ("KOSPI>60", G.REG_KS60), ("없음", G.REG_ALL)):
        a, d = G.backtest(G.SIG_BUY, G.PIT_CAP, reg, My, Qy, py, COST, start="2018-01-01")
        G.summary("이전 체계 선별·" + lab, a, d, COST)

    print("\n======== 최종 규칙(KOSDAQ>20, 종가=고가→테마연속→등락률, 상위3) + walk-forward 등급")
    for minn in (30, 100):
        M, _Q, pct = wf_grade(minn)
        C[f"g{minn}"] = pct[C["i"], C["j"]]
        C[f"m{minn}"] = M[C["i"], C["j"]]
    print("후보 중 등급 계산 가능 비율 (n≥30 / n≥100):", round(C["g30"].notna().mean(), 2), round(C["g100"].notna().mean(), 2))
    C["dm"] = C["on"] - C.groupby("date")["on"].transform("mean")
    for gcol in ("g30", "g100"):
        b = pd.cut(C[gcol], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
        print(f"  후보 단위 {gcol} 5분위 (비용후 / 같은 날 대비):",
              " | ".join(f"{k}: n={len(v)} {(v['on'].mean()-COST)*100:+.2f}/{v['dm'].mean()*100:+.2f}" for k, v in C.groupby(b, observed=True)),
              f"| 등급없음 n={C[gcol].isna().sum()} {(C.loc[C[gcol].isna(),'on'].mean()-COST)*100:+.2f}")

    def port(d, keys, k=3):
        d = d.sort_values(["date"] + keys, ascending=[True] + [False] * len(keys))
        return d.groupby("date").head(k)

    base = port(C, ["top", "theme_run", "day"])
    sb = base.groupby("date")["on"].mean()
    print(line(stats(sb, label="최종 규칙 (기준)")))
    tests = {}
    for gcol in ("g30", "g100"):
        Cg = C.assign(gf=C[gcol].fillna(0.5))
        tests[f"{gcol} 하위20% 제외"] = port(Cg[Cg["gf"] > 0.2], ["top", "theme_run", "day"])
        tests[f"{gcol} 하위40% 제외"] = port(Cg[Cg["gf"] > 0.4], ["top", "theme_run", "day"])
        tests[f"{gcol} 상위20%(S·A)만"] = port(Cg[Cg["gf"] >= 0.8], ["top", "theme_run", "day"])
        tests[f"{gcol} 정렬 3순위(테마 다음)"] = port(Cg, ["top", "theme_run", "gf"])
        tests[f"{gcol} 정렬 2순위(종가=고가 다음)"] = port(Cg, ["top", "gf", "theme_run"])
        tests[f"{gcol} 정렬 1순위"] = port(Cg, ["gf", "top", "theme_run"])
    for lab, d in tests.items():
        s = d.groupby("date")["on"].mean()
        j = sb.index.intersection(s.index); dd = s[j] - sb[j]
        print(line(stats(s, label=lab)) + f" | 같은날 차 {dd.mean()*100:+.3f}%p t={nw_t(dd.to_numpy(),1):+.2f}")
    # 비중: 등급 상위 종목 1.5배
    for gcol in ("g30", "g100"):
        b2 = base.assign(w=np.where(base[gcol].fillna(0.5) >= 0.8, 1.5, np.where(base[gcol].fillna(0.5) <= 0.2, 0.5, 1.0)))
        s = (b2["on"] * b2["w"]).groupby(b2["date"]).sum() / b2.groupby("date")["w"].sum()
        x = (s - COST); e = sb - COST
        print(f"  {gcol} 비중(상위 1.5·하위 0.5, 종목간 재배분): 평균 {x.mean()*100:+.3f}% vs {e.mean()*100:+.3f}%  샤프 {x.mean()/x.std()*np.sqrt(250):.2f} vs {e.mean()/e.std()*np.sqrt(250):.2f}")

    print("\n======== 위험지표: 과거 하위1% 갭·갭 변동성(walk-forward, 연 1회)이 다음 밤의 꼬리를 예고하나 (최종 규칙 선택 종목)")
    _, p1, _ = wf_grade(30); sd = wf_gapvol()
    base = base.assign(p1=p1[base["i"], base["j"]], sd=sd[base["i"], base["j"]])
    print(f"  위험지표 계산 가능: {base['p1'].notna().mean()*100:.0f}%")
    for col, lab in (("p1", "과거 하위1% 갭"), ("sd", "과거 갭 변동성(전체일)")):
        q = pd.qcut(base[col], 4, duplicates="drop")
        for k, v in base.groupby(q, observed=True)["on"]:
            print(f"   {lab} {str(k):22} n={len(v):4d} 평균 {(v.mean()-COST)*100:+.2f}% 하위1% {np.percentile(v,1)*100:+5.1f}% 하위5% {np.percentile(v,5)*100:+5.1f}% −5%↓ 비율 {(v<=-0.05).mean()*100:.1f}%")
    # 이전 체계 비중 공식: 종목당 2%/|p1|, 최대 40% (계좌 대비) vs 균등 1/3
    b = base.dropna(subset=["p1"]).copy()
    b["w"] = np.minimum(0.02 / np.maximum(b["p1"].abs(), 0.01), 0.40)          # 노트북: max(|p01|,1%), 상한 40%
    tot = b.groupby("date")["w"].transform("sum"); b["w"] = np.where(tot > 1, b["w"] / tot, b["w"])   # 합 100% 초과 시 축소
    acct_f = (b["w"] * (b["on"] - COST)).groupby(b["date"]).sum()
    acct_e = ((b["on"] - COST) / 3).groupby(b["date"]).sum()
    inv = b.groupby("date")["w"].sum()
    for lab, x in (("2%/|하위1%|, 최대 40% (이전 체계)", acct_f), ("균등 1/3씩 (100% 투입)", acct_e), ("균등, 이전 체계와 같은 평균 투입", acct_e * inv.mean())):
        eq = (1 + x).cumprod(); dd = (eq / eq.cummax() - 1).min()
        print(f"   {lab:34} 계좌 일평균 {x.mean()*100:+.3f}% 샤프 {x.mean()/x.std()*np.sqrt(250):.2f} 최악의 밤 {x.min()*100:+.2f}% 최대낙폭 {dd*100:.1f}%")
    print(f"   (이전 체계 공식의 평균 총투입 {inv.mean()*100:.0f}%, 중앙 {inv.median()*100:.0f}%, 최대 {inv.max()*100:.0f}%)")
