from eng import *
def curve(r):
    s = (1 + r.fillna(0)).cumprod(); return s
def st(r, rc=None):
    s = curve(r); yrs = (s.index[-1]-s.index[0]).days/365.25
    cagr = s.iloc[-1]**(1/yrs)-1; mdd = (s/s.cummax()-1).min()
    sh = r.mean()/r.std()*np.sqrt(252)
    yr = (1+r).groupby(r.index.year).prod()-1
    return cagr, mdd, sh, yr
for nm, a0 in (("K","2010-01-04"),("Q","2016-08-10")):
    df = pair(nm).loc[a0:"2026-11-02"]
    on = df.oL/df.cL.shift()-1; idL = df.cL/df.oL-1
    idI = df.cI/df.oI-1; onI = df.oI/df.cI.shift()-1
    full = df.cL.pct_change()
    print(f"\n===== {nm}  {a0}~  (하루 평균 bp)  밤 롱 {on.mean()*1e4:.1f}  낮 롱 {idL.mean()*1e4:.1f}  낮 인버스 {idI.mean()*1e4:.1f}  밤 인버스 {onI.mean()*1e4:.1f}")
    print(f"  밤 승률 {(on>0).mean()*100:.0f}%  낮 롱 승률 {(idL>0).mean()*100:.0f}%")
    rows = {"보유(롱 종일)": full}
    for com in (0.00015, 0.00004, 0.0):
        c = 2*com
        rows[f"밤 롱만 (수수료 {com*100:.4f}%)"] = on - c
        rows[f"밤 롱 + 낮 인버스 ({com*100:.4f}%)"] = (1+on-c)*(1+idI-c)-1
    rows["낮 인버스만 (0.015%)"] = idI - 0.0003
    rows["낮 롱만 (0.015%)"] = idL - 0.0003
    hdr = sorted(set(full.index.year))
    print(f"  {'전략':<26}{'연':>7}{'MDD':>7}{'샤프':>6} | " + "".join(f"{str(y)[2:]:>5}" for y in hdr))
    for k, r in rows.items():
        cg, md, sh, yr = st(r.dropna())
        print(f"  {k:<26}{cg*100:7.1f}{md*100:7.1f}{sh:6.2f} | " + "".join(f"{yr.get(y,np.nan)*100:5.0f}" for y in hdr))
