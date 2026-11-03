from hybrid import *
def l2(s):
    a = stats(s); yr = a["yr"]
    return f"연 {a['cagr']*100:5.1f}%  MDD {a['mdd']*100:6.1f}%  샤프 {a['sh']:4.2f}  +년 {(yr>0).sum()}/{len(yr)}  " + " ".join(f"{y%100}:{v*100:4.0f}" for y, v in zip(yr.index.year, yr.values))
P = K.cL; one = P*0+1; zero = P*0
k = sum((P > ma(P, n)).astype(int) for n in (20,40,60,90,120)) / 5
p = ("2003-01-02","2009-12-31")
print("== 표본 밖 2003~2009 KODEX 200")
for com in (0.00015, 0.00004):
    print(f" 수수료 {com*100:.4f}%")
    print(f"   보유              {l2(run2(K, one, one, com, False, *p))}")
    print(f"   밤 롱만           {l2(run2(K, zero, one, com, False, *p))}")
    print(f"   계단 롱/현금       {l2(run2(K, k.shift().fillna(0), k, com, False, *p))}")
    print(f"   밤100%+낮 계단     {l2(run2(K, k.shift().fillna(0), one, com, False, *p))}")
print("\n== 같은 기간 추세 규칙(롱/인버스는 합성 인버스)")
for nm in ("20일 모멘텀 롱/현금", "120일선 롱/현금", "계단 20~120 롱/현금", "120일선 롱/인버스", "계단 20~120 롱/인버스", "60·120 교차 롱/인버스", "RSI2 롱만"):
    wl, wi = STRATS[nm](P)
    print(f"   {nm:<18} {l2(run(K, wl, wi, 'close', *p))}")
