"""A8. 자금관리 — 종목 수·비중 단계·레버리지(투입 비율)별 복리 곡선, 최대낙폭, 꼬리
최종 선별: KOSDAQ>20일선 날, 상한가터치·+25%↑ 제외, 고가권→등락률 상위 k, 다음날 시가 매도, 비용 0.25%
비중 단계(모두 15:20에 아는 값): 기본 1.0 / 뜨거운 날(후보수 롤링상위20% 또는 테마동반 상위20%) +0.5
  / 주말 전(금요일·연휴 아님) +0.5 / 목요일·옵션만기일 −0.5
python tools/closebet/money_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line

COST = 0.0025
R = pd.read_pickle(CB / "_R.pkl"); D1 = pd.read_pickle(CB / "_D1.pkl")
S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False])


def port(k):
    return S.groupby("date").head(k).groupby("date")["on"].mean() - COST


def weights(D):
    w = pd.Series(1.0, D.index)
    hot = (D["pool_pct"] >= 0.8) | (D["theme_pct"] >= 0.8)
    w += 0.5 * hot
    w += 0.5 * (D["gapdays"] == 3)
    w -= 0.5 * ((D["dow"] == 3) | D["opt_exp"])
    return w.clip(0.5, 2.0)


def sim(r, f, w=None):
    """r: 날짜별 비용후 포트 수익, f: 자본 대비 투입 비율, w: 날짜별 비중 배수"""
    x = r * f * (w if w is not None else 1.0)
    eq = (1 + x).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    # 연속 손실
    neg = (x < 0).astype(int)
    run = (neg.groupby((neg != neg.shift()).cumsum()).cumsum()).max()
    worst20 = x.rolling(20).sum().min()
    return f"투입 {f:.1f}배 CAGR {cagr*100:6.1f}% 최대낙폭 {dd*100:6.1f}% 최악의밤 {x.min()*100:5.1f}% 최악20일 {worst20*100:6.1f}% 최장연속손실 {run}일 샤프(연) {x.mean()/x.std()*np.sqrt(250):.2f}"


for k in (3, 5):
    r = port(k)
    print(f"\n==== 상위 {k} (매매일 {len(r)}, 평균 비용후 {r.mean()*100:+.3f}%)")
    for f in (0.5, 1.0, 1.5, 2.0):
        print("  균등 ", sim(r, f))
    w = weights(D1).reindex(r.index).fillna(1.0)
    print("  비중단계 평균 배수", round(w.mean(), 2), "| 배수별 날수", w.value_counts().sort_index().to_dict())
    for f in (0.5, 1.0, 1.5):
        print("  단계 ", sim(r, f / w.mean(), w), f"(평균 투입 {f:.1f}배로 맞춤)")
    # 단계별 실제 성적
    for v in sorted(w.unique()):
        print(f"    배수 {v}: n={int((w==v).sum())} 평균 {r[w==v].mean()*100:+.2f}%  앞/뒤 {r[(w==v)&(r.index<=r.index[len(r)//2])].mean()*100:+.2f}/{r[(w==v)&(r.index>r.index[len(r)//2])].mean()*100:+.2f}")
# 기존 기준선과 비교
B = R  # 참고
print("\n== 체결 용량: 선택 종목의 당일 거래대금(억) 분포 (상위3)")
t3 = S.groupby("date").head(3)
print((t3["amt"] / 1e8).describe(percentiles=[.1, .25, .5, .75]).round(1).to_string())
print("연도별 중앙값(억):", (t3.groupby(t3["date"].dt.year)["amt"].median() / 1e8).round(0).to_dict())
for cap in (1e7, 3e7, 1e8, 3e8):
    # 종목당 투입금이 그날 거래대금의 1%를 넘지 않게 하면, 투입 가능한 날의 비율
    ok = (t3["amt"] * 0.01 >= cap / 3).groupby(t3["date"]).all()
    print(f"  계좌 {cap/1e8:.1f}억(종목당 {cap/3/1e6:.0f}백만) → 3종목 모두 당일 거래대금 1% 이내인 날 {ok.mean()*100:.0f}%")
