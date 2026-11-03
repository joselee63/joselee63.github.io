from strat import *
K = pair("K"); Q = pair("Q")
PK = K.cL; PQ = Q.cL
both_dn = lambda n: ((PK < ma(PK, n)) & (PQ.reindex(PK.index) < ma(PQ, n).reindex(PK.index)))
def inv_leg(df, cond, hold=None, p0=None, p1=None, mode="close"):
    """cond 날 종가에 인버스 진입. hold=None이면 cond 동안 보유, 숫자면 그 거래일 수만큼 보유."""
    c = cond.reindex(df.index).fillna(False)
    if hold:
        w = c.astype(float).rolling(hold, min_periods=1).max()
    else:
        w = c.astype(float)
    s = run(df, w*0, w, mode, p0, p1, tax=0.0); st = stats(s)
    s2 = run(df, w*0, w, mode, p0, p1, tax=0.154)
    # 인버스 들고 있던 날만의 일평균 (bp)
    r = s.pct_change(); wd = w.reindex(r.index).shift().fillna(0) > 0
    return f"인버스 보유일 {wd.mean()*100:4.0f}%  보유일 평균 {r[wd].mean()*1e4:6.1f}bp  계좌 연 {st['cagr']*100:5.1f}% (세후 {stats(s2)['cagr']*100:5.1f}%)  MDD {st['mdd']*100:6.1f}%  +년 {(st['yr']>0).sum()}/{len(st['yr'])}"
for nm, df, P, p in (("코스피", K, PK, ("2010-01-04","2026-11-02")), ("코스닥", Q, PQ, ("2016-08-10","2026-11-02"))):
    print(f"\n== {nm} 인버스만 (나머지 현금)")
    m20, m60, m120, m200 = ma(P,20), ma(P,60), ma(P,120), ma(P,200)
    hi = P.rolling(252).max(); dd = P/hi-1
    vol = P.pct_change().rolling(20).std()*np.sqrt(252)
    r2 = rsi(P, 2)
    tests = {
        "60일선 아래": P < m60,
        "60일선 아래 + 60일선 하락": (P < m60) & (m60 < m60.shift(5)),
        "두 지수 모두 60일선 아래": both_dn(60),
        "두 지수 모두 120일선 아래": both_dn(120),
        "고점 −10%↓ + 20일선 아래": (dd < -0.10) & (P < m20),
        "고점 −20%↓ + 20일선 아래": (dd < -0.20) & (P < m20),
        "20일 변동성 25%↑ + 60일선 아래": (vol > 0.25) & (P < m60),
        "하락장 과매수(200일선 아래·RSI2>90) 3일": (P < m200) & (r2 > 90),
        "하락장 과매수 5일": (P < m200) & (r2 > 90),
        "아무 때나 과매수(RSI2>95) 3일": r2 > 95,
        "5일 +5%↑ 급반등 3일": P/P.shift(5)-1 > 0.05,
    }
    for k, c in tests.items():
        h = 3 if "3일" in k else (5 if "5일" in k and "급반등" not in k else None)
        if "급반등" in k: h = 3
        print(f"  {k:<30} {inv_leg(df, c, h, *p)}")
