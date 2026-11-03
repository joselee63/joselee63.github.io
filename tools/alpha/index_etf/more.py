from strat import *
K = pair("K"); Q = pair("Q")
A0, A1 = "2016-08-10", "2026-11-02"
idx = K.loc[A0:A1].index.intersection(Q.index)
def stt(r):
    s=(1+r).cumprod(); y=(s.index[-1]-s.index[0]).days/365.25
    yr=(1+r).groupby(r.index.year).prod()-1
    return f"연 {(s.iloc[-1]**(1/y)-1)*100:5.1f}%  MDD {((s/s.cummax()-1).min())*100:6.1f}%  샤프 {r.mean()/r.std()*np.sqrt(252):5.2f}  +년 {(yr>0).sum()}/{len(yr)}  앞 {((1+r[:'2020']).prod()**(1/4.4)-1)*100:5.1f} 뒤 {((1+r['2021':]).prod()**(1/5.8)-1)*100:5.1f}"
print("== ① 코스피 vs 코스닥 상대강도 (2016-08~, 종가 체결, 비용 반영)")
rK = run(K, *S_bh(K.cL), "close", A0, A1).pct_change().fillna(0)
rQ = run(Q, *S_bh(Q.cL), "close", A0, A1).pct_change().fillna(0)
print(f"  코스피 보유        {stt(rK)}")
print(f"  코스닥 보유        {stt(rQ)}")
print(f"  반반 보유          {stt((rK+rQ)/2)}")
ratio = (K.cL / Q.cL).reindex(K.index)
for L in (20, 60, 120):
    kst = (ratio > ratio.rolling(L).mean()).astype(float)   # 코스피가 상대적으로 강함
    # 회전: 강한 쪽 롱 100%
    a = run(K, kst, kst*0, "close", A0, A1).pct_change().fillna(0); b = run(Q, (1-kst).reindex(Q.index).fillna(0), Q.cL*0, "close", A0, A1).pct_change().fillna(0)
    print(f"  {L}일 상대강도 회전(강한 쪽 롱)  {stt((a+b).reindex(idx).fillna(0))}")
    # 스프레드: 강한 쪽 롱 50% + 약한 쪽 인버스 50%
    a = run(K, kst*0.5, (1-kst)*0.5, "close", A0, A1).pct_change().fillna(0)
    b = run(Q, ((1-kst)*0.5).reindex(Q.index).fillna(0), (kst*0.5).reindex(Q.index).fillna(0), "close", A0, A1).pct_change().fillna(0)
    print(f"  {L}일 상대강도 스프레드(롱+인버스) {stt((a+b).reindex(idx).fillna(0))}")

print("\n== ② RSI2 공포 매수(롱만) 견고성: 진입 RSI2<lo, 청산 종가>5일선 | 종가 체결 / 다음날 시가 체결")
for nm, df, p0 in (("코스피", K, ("2010-01-04","2026-11-02")), ("코스닥", Q, (A0, A1))):
    for lo in (5, 10, 15, 20, 30):
        wl, wi = S_rsi(lo=lo, inv=False)(df.cL)
        a = stats(run(df, wl, wi, "close", *p0)); b = stats(run(df, wl, wi, "open", *p0))
        print(f"  {nm} lo={lo:2}  종가 연 {a['cagr']*100:5.1f} MDD {a['mdd']*100:6.1f} 샤프 {a['sh']:4.2f} 투자 {a['expL']*100:3.0f}% 매매 {a['trd']:4.1f}/년 +년 {(a['yr']>0).sum()}/{len(a['yr'])} | 시가 연 {b['cagr']*100:5.1f} MDD {b['mdd']*100:6.1f}")
