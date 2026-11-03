from strat import *
K = pair("K"); Q = pair("Q")
PER = [("코스피 03~09", K, "2003-01-02", "2009-12-31"), ("코스피 10~17", K, "2010-01-04", "2017-12-31"), ("코스피 18~26", K, "2018-01-02", "2026-11-02"),
       ("코스닥 16~20", Q, "2016-08-10", "2020-12-31"), ("코스닥 21~26", Q, "2021-01-04", "2026-11-02")]
def stepw(P, ns, inv0=0.0):
    k = sum((P > ma(P, n)).astype(int) for n in ns); ok = ma(P, max(ns)).notna()
    wl = (k / len(ns)).where(ok, 0); wi = ((k == 0) & ok).astype(float) * inv0
    return wl, wi
rows = {"보유": lambda P: S_bh(P)}
for ns in ((10,20,40,60,120), (20,40,60,90,120), (20,60,120,200), (60,90,120,150,200), (5,10,20,60,120)):
    rows[f"계단 {'·'.join(map(str,ns))}"] = (lambda ns: lambda P: stepw(P, ns))(ns)
rows["계단 20~120 + 전부 깨면 인버스 50%"] = lambda P: stepw(P, (20,40,60,90,120), 0.5)
rows["계단 20~120 + 전부 깨면 인버스 100%"] = lambda P: stepw(P, (20,40,60,90,120), 1.0)
for mode in ("close", "open"):
    print(f"\n체결={mode}   (각 칸: 연수익 / MDD)")
    print(f"{'':30}" + "".join(f"{p[0]:>16}" for p in PER))
    for k, f in rows.items():
        out = []
        for nm, df, a, b in PER:
            wl, wi = f(df.cL); s = stats(run(df, wl, wi, mode, a, b, tax=0.154))
            out.append(f"{s['cagr']*100:6.1f}/{s['mdd']*100:5.0f}")
        print(f"{k:<30}" + "".join(f"{x:>16}" for x in out))
# 두 시장 반반 (2016-08~)
print("\n== 두 시장 반반 2016-08~2026-11 (종가 체결)")
a0, a1 = "2016-08-10", "2026-11-02"
for k in ("보유", "계단 20·40·60·90·120"):
    rK = run(K, *rows[k](K.cL), "close", a0, a1).pct_change().fillna(0)
    rQ = run(Q, *rows[k](Q.cL), "close", a0, a1).pct_change().fillna(0)
    r = ((rK + rQ.reindex(rK.index).fillna(0)) / 2); s = (1 + r).cumprod(); s.attrs = {}
    st = stats(s); print(f"  {k:<22} 연 {st['cagr']*100:5.1f}%  MDD {st['mdd']*100:6.1f}%  샤프 {st['sh']:4.2f}  " + " ".join(f"{y%100}:{v*100:4.0f}" for y, v in zip(st['yr'].index.year, st['yr'].values)))
# 지금 상태
for nm, df in (("코스피", K), ("코스닥", Q)):
    P = df.cL; ns = (20,40,60,90,120)
    print(f"  {nm} 2026-11-02 종가 기준: " + " ".join(f"{n}일선 {'위' if P.iloc[-1] > ma(P,n).iloc[-1] else '아래'}({(P.iloc[-1]/ma(P,n).iloc[-1]-1)*100:+.1f}%)" for n in ns) + f" → 롱 비중 {sum(P.iloc[-1] > ma(P,n).iloc[-1] for n in ns)*20}%")
