from strat import *
def run2(df, wD, wN, com=0.00015, spread=False, start=None, end=None):
    """낮 비중 wD(시가→종가), 밤 비중 wN(종가→다음 시가), 롱 ETF만. 둘 다 '어제 종가까지 정보'로 결정(wD), wN은 오늘 종가(15:20 근사).
    매매는 동시호가(시가·종가) → 기본은 수수료만, spread=True면 호가 반 칸 추가."""
    d = df.loc[start:end]
    wD = wD.reindex(d.index).fillna(0).values; wN = wN.reindex(d.index).fillna(0).values
    o, c = d.oL.values, d.cL.values
    rc = np.array([BASE.get(y, 2.5) / 100 / 252 for y in d.index.year])
    V = np.empty(len(d)); vL = 0.0; vC = 1.0; nt = 0
    def reb(vL, vC, w, p):
        tot = vL + vC; dl = tot * w - vL
        if abs(dl) < 1e-12: return vL, vC, 0
        cost = abs(dl) * (com + (0.5 * tick(p) / p if spread else 0))
        return tot * w, tot * (1 - w) - cost, 1
    for i in range(len(d)):
        if i > 0:
            vL *= o[i] / c[i - 1]; vC *= 1 + rc[i]
            vL, vC, k = reb(vL, vC, wD[i], o[i]); nt += k
            vL *= c[i] / o[i]
        vL, vC, k = reb(vL, vC, wN[i], c[i]); nt += k
        V[i] = vL + vC
    s = pd.Series(V, d.index); s.attrs["trades"] = nt; s.attrs["expL"] = (wD.mean() + wN.mean()) / 2; s.attrs["expI"] = 0
    return s
K = pair("K"); Q = pair("Q")
def line(nm, s):
    a = stats(s); yr = a["yr"]
    h1 = yr[yr.index.year <= (2017 if nm=="코스피" else 2020)]; h2 = yr[yr.index.year > (2017 if nm=="코스피" else 2020)]
    g = lambda x: ((1+x).prod()**(1/len(x))-1)*100
    return f"연 {a['cagr']*100:5.1f}%  MDD {a['mdd']*100:6.1f}%  샤프 {a['sh']:4.2f}  매매 {a['trd']:5.0f}회/년  +년 {(yr>0).sum()}/{len(yr)}  앞 {g(h1):5.1f} 뒤 {g(h2):5.1f}"
for nm, df, p in (("코스피", K, ("2010-01-04","2026-11-02")), ("코스닥", Q, ("2016-08-10","2026-11-02"))):
    P = df.cL; one = P*0+1; zero = P*0
    k = sum((P > ma(P, n)).astype(int) for n in (20,40,60,90,120)) / 5
    stepY = k.shift().fillna(0)            # 낮 비중: 어제 종가 기준 계단
    m120 = (P > ma(P,120)).astype(float)
    wd = pd.Series(P.index.dayofweek, P.index)
    notTF = ((wd != 3) & (wd != 4)).astype(float)
    print(f"\n===== {nm} {p[0]}~ (동시호가 체결)")
    for com in (0.00015, 0.00004):
        print(f" -- 수수료 한쪽 {com*100:.4f}%")
        cases = {
            "보유(종일 100%)": (one, one),
            "계단 20~120 롱/현금(낮·밤 같게)": (stepY, k),
            "밤 롱만(매일 종가 사서 시가 팖)": (zero, one),
            "밤 롱 (목·금 밤 제외)": (zero, notTF),
            "밤 100% + 낮은 계단 비중": (stepY, one),
            "밤 100% + 낮은 120일선 위면 100%": (m120.shift().fillna(0), one),
            "밤은 계단 비중 + 낮 0": (zero, k),
        }
        for kk, (a, b) in cases.items():
            print(f"   {kk:<32} {line(nm, run2(df, a, b, com, False, *p))}")
    print(f" -- 참고: 호가 반 칸까지 내는 경우(수수료 0.015%)  밤 롱만 {line(nm, run2(df, zero, one, 0.00015, True, *p))}")
