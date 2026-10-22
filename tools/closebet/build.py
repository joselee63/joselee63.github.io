"""후보 테이블(시장필터 미적용 풀 전체) + 날짜 특성 → data-closebet/cands.pkl, days.pkl
python tools/closebet/build.py
"""
import time
import numpy as np
import pandas as pd
from cb import CB, load_panel, candidates, stock_features, sector_map, peer_sets, peer_strength, macro_frame, market_frame

if __name__ == "__main__":
    t0 = time.time()
    P = load_panel()
    df = candidates(P, mkt_filter=False)
    df = stock_features(P, df)
    S, names = sector_map(P)
    df["sector"] = S[df["i"], df["j"]]
    df["sector_name"] = df["sector"].map(names)
    # 같은 날 기준선 풀(시장필터 무관) 안에서 같은 업종 후보 수, 업종 내 등락률 순위
    df["sec_pool"] = df.groupby(["i", "sector"])["j"].transform("size").where(df["sector"] >= 0)
    df["sec_rank"] = df.groupby(["i", "sector"])["day"].rank(ascending=False, method="first").where(df["sector"] >= 0)
    # 업종 전체(상장 종목) 당일 평균 등락률·+3% 비율
    live = np.isfinite(P.day) & (P.run >= 20)
    secday = {}
    for t in np.unique(df["i"]):
        s = S[t]; d = P.day[t]; ok = live[t] & (s >= 0)
        g = pd.DataFrame({"s": s[ok], "d": d[ok]}).groupby("s")["d"]
        secday[t] = (g.mean(), (g.apply(lambda x: (x >= 0.03).mean())), g.size())
    df["sec_ret"] = [secday[t][0].get(s, np.nan) for t, s in zip(df["i"], df["sector"])]
    df["sec_up3"] = [secday[t][1].get(s, np.nan) for t, s in zip(df["i"], df["sector"])]
    print("sector done", time.time() - t0)
    ps = peer_sets(P)
    df = peer_strength(P, df, ps)
    print("peers done", time.time() - t0)
    df.to_pickle(CB / "cands.pkl")
    days = market_frame(P).join(macro_frame(P))
    days["pool_all"] = df.groupby("date").size().reindex(days.index).fillna(0)
    days.to_pickle(CB / "days.pkl")
    print(len(df), "rows", time.time() - t0)
