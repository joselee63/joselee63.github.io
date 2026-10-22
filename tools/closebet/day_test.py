"""A2. 날짜(시황) 조건: 매수 시점(t일 15:20)에 알 수 있는 시장 특성으로 '쉬는 날'을 고를 수 있나
python tools/closebet/day_test.py
각 조건: 해당하는 날 / 아닌 날 의 상위3 비용후 평균, 차이 t, 앞·뒤 절반 각각의 차이
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, diff_t, daily

COST = 0.0025
df = pd.read_pickle(CB / "cands.pkl"); days = pd.read_pickle(CB / "days.pkl")


def test(D, name, cond):
    cond = cond.reindex(D.index).fillna(False).astype(bool)
    a, b = D.loc[cond, "port"] - COST, D.loc[~cond, "port"] - COST
    med = D.index[len(D) // 2]
    h1 = cond & (D.index <= med); h2 = cond & (D.index > med)
    d1 = D.loc[h1, "port"].mean() - D.loc[~cond & (D.index <= med), "port"].mean()
    d2 = D.loc[h2, "port"].mean() - D.loc[~cond & (D.index > med), "port"].mean()
    yr = (D.loc[cond, "port"] - COST).groupby(D.index[cond].year).mean()
    print(f"{name:34} 해당 {cond.sum():4d}일 {a.mean()*100:+6.2f}% (하위1% {np.percentile(a,1)*100 if len(a)>5 else np.nan:+5.1f}) | 나머지 {b.mean()*100:+6.2f}% "
          f"| 차 t={diff_t(a,b):+5.2f} | 앞 {d1*100:+5.2f} 뒤 {d2*100:+5.2f} | 해당일 플러스연도 {(yr>0).sum()}/{len(yr)}")


def run(D, title):
    print(f"\n========== {title}: {line(stats(D['port'], label=''))}")
    q = lambda c, p: D[c] <= D[c].quantile(p)
    Q = lambda c, p: D[c] >= D[c].quantile(p)
    print("-- 지수 당일 흐름")
    test(D, "KOSPI 당일 −1% 이하", D["ks_ret"] <= -0.01)
    test(D, "KOSPI 당일 +1% 이상", D["ks_ret"] >= 0.01)
    test(D, "KOSDAQ 당일 −1.5% 이하", D["kq_ret"] <= -0.015)
    test(D, "KOSDAQ 당일 +1.5% 이상", D["kq_ret"] >= 0.015)
    test(D, "KOSDAQ 마감위치 하위 20%(약세마감)", q("kq_pos", .2))
    test(D, "KOSDAQ 마감위치 상위 20%(막판강세)", Q("kq_pos", .8))
    test(D, "KOSDAQ 시가→종가 하위20%", q("kq_oc", .2))
    test(D, "KOSDAQ 장중 반등 상위20%", Q("kq_rebound", .8))
    test(D, "KOSDAQ < 20일선", D["kq_ma20"] < 0)
    test(D, "KOSDAQ < 60일선", D["kq_ma60"] < 0)
    test(D, "KOSDAQ 5일 −5% 이하", D["kq_r5"] <= -0.05)
    test(D, "KOSDAQ 5일 +5% 이상(과열)", D["kq_r5"] >= 0.05)
    test(D, "KOSPI 60일 고점대비 −10% 이하", D["ks_dd"] <= -0.10)
    print("-- 시장 폭·쏠림")
    test(D, "상승종목비율 하위20%", q("adv_ratio", .2))
    test(D, "상승종목비율 상위20%", Q("adv_ratio", .8))
    test(D, "+5% 종목수 상위20%", Q("n_up5_rel", .8))
    test(D, "+5% 종목수 하위20%", q("n_up5_rel", .2))
    test(D, "−5% 종목수 상위20%", Q("n_dn5", .8))
    test(D, "상한가 종목수 ≥10", D["n_limit"] >= 10)
    test(D, "상한가 종목수 ≤2", D["n_limit"] <= 2)
    test(D, "52주신고가 종목수 상위20%", Q("n_hi52", .8))
    test(D, "거래대금 상위10 쏠림 상위20%", Q("amt_top10", .8))
    test(D, "전체 거래대금 20일평균 1.3배↑", D["amt_tot_rel"] >= 1.3)
    test(D, "기준선 후보 수 ≥40(과열)", D["pool_all"] >= 40)
    test(D, "기준선 후보 수 ≤8", D["pool_all"] <= 8)
    print("-- 해외(매수 시점에 아는 값)")
    test(D, "직전 SOX −3% 이하", D["sox_prev"] <= -0.03)
    test(D, "직전 NDX −1.5% 이하", D["ndx_prev"] <= -0.015)
    test(D, "직전 VIX +10% 이상", D["vix_prev"] >= 0.10)
    test(D, "VIX 수준 ≥ 25", D["vix_lvl"] >= 25)
    test(D, "VIX 20~25", (D["vix_lvl"] >= 20) & (D["vix_lvl"] < 25))
    test(D, "닛케이 당일 −1.5% 이하", D["nk_prev"] <= -0.015)
    test(D, "원/달러 직전 +0.3% 이상(원화약세)", D["krw_prev"] >= 0.003)
    print("-- 캘린더")
    for k, nm in enumerate("월화수목금"):
        test(D, f"{nm}요일", D["dow"] == k)
    test(D, "연휴 전(다음 거래일까지 4일+)", D["gapdays"] >= 4)
    test(D, "주말 전(금)", D["gapdays"] == 3)
    test(D, "월말", D["month_end"])
    test(D, "옵션만기일", D["opt_exp"])
    test(D, "선물·옵션 동시만기", D["quad_exp"])
    test(D, "12월", pd.Series(D.index.month == 12, D.index))
    test(D, "1월", pd.Series(D.index.month == 1, D.index))


if __name__ == "__main__":
    base = df[df["mkt_ok"]]
    D = days.join(daily(base, 3).rename("port"), how="inner")
    run(D, "기준선(KOSPI>60일선) 상위3")
    # 시장필터를 빼면 어떤가 (KOSPI<60일선 날만)
    off = df[~df["mkt_ok"]]
    D2 = days.join(daily(off, 3).rename("port"), how="inner")
    print("\n[참고] KOSPI<60일선 날 상위3:", line(stats(D2["port"], label="")))
    print("[참고] KOSPI<60일선 & KOSDAQ>20일선:", line(stats(D2.loc[D2["kq_ma20"] > 0, "port"], label="")))
    print("[참고] KOSPI<60일선 & KOSDAQ>60일선:", line(stats(D2.loc[D2["kq_ma60"] > 0, "port"], label="")))
