from eng import *
def W(x): return x.astype(float)
def S_bh(P): return W(P*0+1), W(P*0)
def S_ma(n, inv=True, slope=False):
    def f(P):
        m = ma(P, n); up = P > m
        dn = ~up & m.notna()
        if slope: dn &= m < m.shift(5)
        return W(up), W(dn) if inv else W(P*0)
    return f
def S_mom(L, inv=True):
    def f(P):
        r = P / P.shift(L) - 1
        return W(r > 0), W(r <= 0) if inv else W(P*0)
    return f
def S_cross(a, b, inv=True):
    def f(P):
        x = ma(P, a) > ma(P, b); ok = ma(P, b).notna()
        return W(x & ok), W(~x & ok) if inv else W(P*0)
    return f
def S_step(ns=(20,40,60,90,120), mode="ls"):
    def f(P):
        k = sum((P > ma(P, n)).astype(int) for n in ns); ok = ma(P, max(ns)).notna()
        if mode == "lo": return (k / len(ns)).where(ok, 0), P*0
        net = (2 * k / len(ns) - 1).where(ok, 0)
        return net.clip(lower=0), (-net).clip(lower=0)
    return f
def S_rsi(lo=10, hi=90, trend=None, inv=True):
    """Connors식: RSI2<lo 롱 진입→종가>5일선 청산, RSI2>hi 인버스 진입→종가<5일선 청산. trend=n이면 n일선 위에서만 롱·아래서만 인버스"""
    def f(P):
        r = rsi(P, 2).values; m5 = ma(P, 5).values; p = P.values
        tr = ma(P, trend).values if trend else None
        wl = np.zeros(len(P)); wi = np.zeros(len(P)); st = 0
        for i in range(len(P)):
            if np.isnan(r[i]) or np.isnan(m5[i]): continue
            if st == 1 and p[i] > m5[i]: st = 0
            if st == -1 and p[i] < m5[i]: st = 0
            if st == 0:
                upok = (tr is None) or (not np.isnan(tr[i]) and p[i] > tr[i])
                dnok = (tr is None) or (not np.isnan(tr[i]) and p[i] < tr[i])
                if r[i] < lo and upok: st = 1
                elif r[i] > hi and dnok and inv: st = -1
            wl[i] = st == 1; wi[i] = st == -1
        return pd.Series(wl, P.index), pd.Series(wi, P.index)
    return f
def S_trend_bounce(n=200, hi=70):
    """n일선 위 = 롱, 아래 = RSI2>hi(반등) 때만 인버스(종가<5일선이면 청산), 나머진 현금"""
    def f(P):
        up = P > ma(P, n)
        wl, wi = S_rsi(lo=-1, hi=hi, trend=n)(P)
        return W(up), wi.where(~up, 0)
    return f

STRATS = {"보유": S_bh}
for n in (5, 10, 20, 60, 120, 200):
    STRATS[f"{n}일선 롱/현금"] = S_ma(n, inv=False)
    STRATS[f"{n}일선 롱/인버스"] = S_ma(n)
    STRATS[f"{n}일선 롱/인버스(하락기울기)"] = S_ma(n, slope=True)
for L in (20, 60, 120, 250):
    STRATS[f"{L}일 모멘텀 롱/현금"] = S_mom(L, inv=False)
    STRATS[f"{L}일 모멘텀 롱/인버스"] = S_mom(L)
for a, b in ((5, 20), (20, 60), (60, 120)):
    STRATS[f"{a}·{b} 교차 롱/인버스"] = S_cross(a, b)
STRATS["계단 20~120 롱/인버스"] = S_step()
STRATS["계단 20~120 롱/현금"] = S_step(mode="lo")
STRATS["계단 5~120 롱/인버스"] = S_step((5, 10, 20, 60, 120))
STRATS["RSI2 역추세 양방향"] = S_rsi()
STRATS["RSI2 롱만"] = S_rsi(inv=False)
STRATS["RSI2 + 200일선 방향"] = S_rsi(trend=200)
STRATS["200일선 위 롱 / 아래 반등시 인버스"] = S_trend_bounce()

PER = {"K": [("2010-01-04", "2026-11-02"), ("2010-01-04", "2017-12-31"), ("2018-01-02", "2026-11-02"), ("2003-01-02", "2026-11-02")],
       "Q": [("2016-08-10", "2026-11-02"), ("2016-08-10", "2020-12-31"), ("2021-01-04", "2026-11-02")]}
