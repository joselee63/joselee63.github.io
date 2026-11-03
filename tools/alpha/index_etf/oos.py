from hybrid import *
import warnings; warnings.filterwarnings("ignore")
for nm, df in (("KODEX200", K), ("코스닥150", Q)):
    L = df[["oL","cL"]].copy(); L["pc"] = L.cL.shift()
    st = (L.oL == L.pc).groupby(L.index.year).mean()
    print(nm, "시가=전일종가(거래 없는 시가 의심) 비율:", " ".join(f"{y%100}:{v*100:.0f}%" for y, v in st.items() if v > 0.03) or "3% 넘는 해 없음")
print("\n== 표본 밖 2003-01~2009-12 KODEX 200 (실제 가격)")
D = K.loc["2003-01-02":"2009-12-31"]
on = D.oL/D.cL.shift()-1; idd = D.cL/D.oL-1
print(f"  밤 평균 {on.mean()*1e4:.1f}bp (승률 {(on>0).mean()*100:.0f}%)  낮 평균 {idd.mean()*1e4:.1f}bp")
for y in range(2003, 2010):
    a = on[str(y)]; b = idd[str(y)]
    print(f"   {y}: 밤 누적 {np.expm1(np.log1p(a).sum())*100:6.1f}%  낮 누적 {np.expm1(np.log1p(b).sum())*100:6.1f}%  종일 {np.expm1(np.log1p(D.cL.pct_change()[str(y)]).sum())*100:6.1f}%")
wd = D.index.dayofweek; nx = on.shift(-1)
print("  요일별 밤(그날 종가→다음 시가) bp: " + " ".join(f"{'월화수목금'[k]} {nx[wd==k].mean()*1e4:5.1f}" for k in range(5)))
P = K.cL; one = P*0+1; zero = P*0; w = pd.Series(P.index.dayofweek, P.index); notTF = ((w!=3)&(w!=4)).astype(float)
for com in (0.00015, 0.00004):
    print(f"  수수료 {com*100:.4f}%  보유 {line('코스피', run2(K, one, one, com, False, '2003-01-02','2009-12-31'))}")
    print(f"  {'':16}밤 롱 {line('코스피', run2(K, zero, one, com, False, '2003-01-02','2009-12-31'))}")
    print(f"  {'':16}목금 제외 {line('코스피', run2(K, zero, notTF, com, False, '2003-01-02','2009-12-31'))}")
print("\n== 요일별 밤 bp, 연구 기간 반씩")
for nm, df, cut in (("코스피", K, "2017"), ("코스닥", Q, "2020")):
    on = (df.oL/df.cL.shift()-1).shift(-1); wd = df.index.dayofweek
    for a, b in ((("2010" if nm=="코스피" else "2016-08"), cut), (str(int(cut)+1), "2026")):
        x = on[a:b]; ww = x.index.dayofweek
        print(f"  {nm} {a}~{b}: " + " ".join(f"{'월화수목금'[k]} {x[ww==k].mean()*1e4:5.1f}" for k in range(5)))
