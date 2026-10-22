"""일일 종가베팅 체크리스트 (정량 항목 자동 계산) — 특정 날짜의 시황 판정 + 후보 순위
python tools/closebet/checklist.py [YYYY-MM-DD]     (기본: 데이터 마지막 날)

데이터: data-backtest/ohlcv_all.pkl·index_ohlcv.csv 가 그날까지 갱신돼 있어야 함.
장중(15:20) 실전에서는 HTS 조건검색으로 같은 조건을 걸고, 아래 '시황 판정' 항목만 이 스크립트/HTS 로 확인.
"""
import sys

import numpy as np
import pandas as pd

from cb import CB, load_panel, candidates, stock_features, peer_sets, market_frame

if __name__ == "__main__":
    P = load_panel()
    day = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else P.dates[-1]
    t = P.dates.searchsorted(day)
    if t >= P.T or P.dates[t] != day:
        sys.exit(f"{day.date()} 데이터 없음 (마지막 {P.dates[-1].date()})")
    M = market_frame(P)
    m = M.iloc[t]
    hist = M.iloc[max(0, t - 250):t + 1]
    df = candidates(P, mkt_filter=False, need_next=False)
    df = df[df["i"] == t]
    df = stock_features(P, df)
    pool_hist = candidates(P, mkt_filter=False, need_next=False).groupby("i").size().reindex(range(max(0, t - 250), t + 1)).fillna(0)
    pool_pct = (pool_hist.iloc[:-1] < pool_hist.iloc[-1]).mean()
    # 테마 연속일 (가격상관 동료 10종목 중 +3%↑ 3개 이상인 연속 일수)
    ps = peer_sets(P); keys = np.array(sorted(ps)); peers = ps[keys[keys <= t][-1]][0]
    up3 = P.day >= 0.03
    runs = []
    for j in df["j"]:
        pp = peers[j]; r = 0
        if pp[0] >= 0:
            while t - r >= 0 and np.nansum(up3[t - r, pp]) >= 3 and r < 10:
                r += 1
        runs.append(r)
    df["theme_run"] = runs
    df = df[(df["hi_today"] < 0.285) & (df["day"] < 0.25)]
    df["top"] = (df["pos"] >= 0.999).astype(int)
    df = df.sort_values(["top", "theme_run", "day"], ascending=False)

    kq_ok = m["kq_ma20"] > 0
    d = pd.Timestamp(day)
    nxt_gap = int(m["gapdays"]) if np.isfinite(m["gapdays"]) else (3 if d.dayofweek == 4 else 1)
    hot = pool_pct >= 0.8
    w = 1.0 + 0.5 * hot + 0.5 * (nxt_gap == 3) - 0.5 * ((d.dayofweek == 3) or bool(m["opt_exp"]))
    w = min(2.0, max(0.5, w))
    print(f"===== {d.date()} ({'월화수목금토일'[d.dayofweek]}) 종가베팅 체크리스트")
    print(f"[1] 시장 필터  KOSDAQ 20일선 대비 {m['kq_ma20']*100:+.1f}% → {'매매' if kq_ok else '쉬는 날 (매매 안 함)'}   (검증됨)")
    print(f"    참고: KOSPI 60일선 대비 {m['ks_ma60']*100:+.1f}%, KOSDAQ 당일 {m['kq_ret']*100:+.1f}%, 시가→종가 {m['kq_oc']*100:+.1f}%")
    print(f"[2] 뜨거운 날  후보 수 {len(df)} (최근 250일 중 백분위 {pool_pct*100:.0f}) → {'예 +0.5' if hot else '아니오'}   (일부 근거)")
    print(f"[3] 주말 넘김  {'예 +0.5' if nxt_gap == 3 else '아니오'} / 목요일·옵션만기 {'예 −0.5' if (d.dayofweek == 3 or m['opt_exp']) else '아니오'}   (일부 근거)")
    print(f"    → 비중 배수 {w if kq_ok else 0} (기본 = 계좌의 정해진 1배 투입액)")
    print(f"[4] 시장 폭  상승비율 {m['adv_ratio']*100:.0f}%, +5% {int(m['n_up5'])}종목, −5% {int(m['n_dn5'])}종목, 상한가 {int(m['n_limit'])}, 52주신고가 {int(m['n_hi52'])}   (참고)")
    print("\n후보 (정렬: 종가=고가 → 테마 연속일 → 등락률). 상위 3~5 매수, 다음날 시가 동시호가 전량 매도")
    nm = P.name
    for r, x in enumerate(df.head(10).itertuples()):
        print(f"  {r+1:2d}. {x.ticker} {nm.get(x.ticker, ''):12} 등락 {x.day*100:+5.1f}% 고가권 {x.pos:.2f} 거래량 {x.vol_mult:4.1f}배 "
              f"테마연속 {x.theme_run}일 윗꼬리 {x.upper_wick*100:.1f}% 거래대금 {x.amt/1e8:,.0f}억")
