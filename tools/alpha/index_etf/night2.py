from eng import *
R = RAW
# 지수 자체도 밤>낮인가 (코스피200 지수 시가 = 구성종목 시가)
for s, a0 in (("KPI200","2010-01-04"),("KOSPI","2010-01-04"),("KOSDAQ","2010-01-04")):
    d = R[s].loc[a0:]; on = d.open/d.close.shift()-1; idd = d.close/d.open-1
    h = d.index.year < 2018
    print(f"{s:7} 밤 {on.mean()*1e4:5.1f}bp 낮 {idd.mean()*1e4:5.1f}bp | 앞 밤 {on[h].mean()*1e4:5.1f} 낮 {idd[h].mean()*1e4:5.1f} | 뒤 밤 {on[~h].mean()*1e4:5.1f} 낮 {idd[~h].mean()*1e4:5.1f}")
for nm, a0 in (("K","2010-01-04"),("Q","2016-08-10")):
    df = pair(nm); P = df.cL
    on = (df.oL/df.cL.shift()-1); idL = df.cL/df.oL-1; idI = df.cI/df.oI-1
    gap = on.copy()
    D = pd.DataFrame({"on": on.shift(-1), "idL": idL, "idI": idI, "gap": gap}).loc[a0:"2026-11-02"]
    # on.shift(-1): 오늘 종가 기준 장세에서 오늘 밤 수익
    print(f"\n== {nm}: 갭 크기(오늘 시가/어제 종가)별 오늘 낮 수익 (bp)")
    D["q"] = pd.cut(D.gap, [-1,-0.02,-0.01,-0.005,-0.002,0.002,0.005,0.01,0.02,1])
    print(D.groupby("q", observed=True).agg(n=("idL","size"), 낮롱=("idL", lambda x: x.mean()*1e4), 낮인버스=("idI", lambda x: x.mean()*1e4)).round(1).to_string())
    print(f"== {nm}: 장세별 밤·낮 (bp, 오늘 종가 기준 장세 → 오늘 밤 / 오늘 낮은 어제 종가 기준 장세)")
    for n in (20, 60, 120):
        up = (P > ma(P, n))
        u_on = up.reindex(D.index); u_id = up.shift().reindex(D.index)
        print(f"  {n}일선 위: 밤 {D.on[u_on].mean()*1e4:5.1f} 낮 {D.idL[u_id==True].mean()*1e4:5.1f} | 아래: 밤 {D.on[~u_on].mean()*1e4:5.1f} 낮 {D.idL[u_id==False].mean()*1e4:5.1f}  낮인버스 아래 {D.idI[u_id==False].mean()*1e4:5.1f}")
    wd = D.index.dayofweek
    print(f"  요일별 밤(그날 종가→다음 거래일 시가): " + " ".join(f"{'월화수목금'[k]} {D.on[wd==k].mean()*1e4:5.1f}" for k in range(5)))
    print(f"  요일별 낮: " + " ".join(f"{'월화수목금'[k]} {D.idL[wd==k].mean()*1e4:5.1f}" for k in range(5)))
