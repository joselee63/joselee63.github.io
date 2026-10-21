"""공매도 횡단면 알파: 공매도 거래 비중·잔고 비율·잔고 증감.
python tools/alpha/short_research.py

시점: 공매도 거래량은 t일 장 마감 후 공개 → t+1 시가. 잔고는 T+2 공시 → 2거래일 늦춰 사용.
금지 기간(신호 없음): 2020-03-16~2021-05-02(전 종목), 2021-05-03~2023-11-05(KOSPI200·KOSDAQ150만 허용),
                     2023-11-06~2025-03-30(전면 금지). 금지 기간은 분석에서 제외.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COST_KR, base_mask, load_alpha, load_panel, quantile_returns, qline, roll  # noqa: E402

BANS = [("2020-03-16", "2021-05-02"), ("2023-11-06", "2025-03-30")]

if __name__ == "__main__":
    P = load_panel()
    s = load_alpha("short")
    s = s[s["ticker"].isin(set(P.tickers))]
    have = np.isin(P.dates, pd.DatetimeIndex(s["date"].unique()))
    ok = have.copy()
    for a, b in BANS:
        ok &= ~((P.dates >= pd.Timestamp(a)) & (P.dates <= pd.Timestamp(b)))
    print(f"공매도 데이터 {have.sum()}일 · 금지기간 제외 {ok.sum()}일")
    m = base_mask(P, liq=True) & ok[:, None]
    svr = P.align(s, "sv_ratio")                      # 당일 거래량 중 공매도 비중(%)
    sbr = P.align(s, "sb_ratio")                      # 잔고 ÷ 상장주식수 (%)
    sbr = pd.DataFrame(sbr).ffill(limit=3).shift(2).to_numpy()       # T+2 공시
    sb = pd.DataFrame(P.align(s, "sb")).ffill(limit=3).shift(2).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        sb_ch20 = np.log((sb + 1) / (np.vstack([np.full((20, P.N), np.nan), sb[:-20]]) + 1))
    feats = {
        "공매도 거래비중 1일": svr,
        "공매도 거래비중 20일 평균": roll(svr, 20, "mean", minp=15),
        "공매도 거래비중 급증(1일÷20일)": svr / (roll(svr, 20, "mean", minp=15) + 0.1),
        "공매도 잔고비율(T+2)": sbr,
        "공매도 잔고 20일 증감(log)": sb_ch20,
    }
    for name, X in feats.items():
        for H in (5, 20, 60):
            print(qline(quantile_returns(P, X, H, m), H, COST_KR, name), flush=True)
