"""저PBR 가치 포트폴리오 — 월말 신호, 익월 첫 거래일 시가 매수, 동일비중, 교체분 비용 0.25%.
python tools/alpha/value_portfolio.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_mask, load_panel, monthly_portfolio  # noqa: E402
from fund_research import load_fund, weekly_to_daily  # noqa: E402

P = load_panel(); f = load_fund(P)
pbr, per, eps, div = (weekly_to_daily(P, f, k) for k in ("PBR", "PER", "EPS", "DIV"))
with np.errstate(invalid="ignore", divide="ignore"):
    bm = np.where(pbr > 0, 1 / pbr, np.nan)
m = base_mask(P) & np.isfinite(pbr)
kospi = ~P.is_kosdaq[None, :]
prof = eps > 0
r = lambda x, mm: pd.DataFrame(np.where(mm, x, np.nan)).rank(axis=1, pct=True).to_numpy()
k = pd.Series(P.kospi, index=P.dates)
print(f"KOSPI 지수 연 {((k.iloc[-1]/k.iloc[0])**(252/len(k))-1)*100:+.1f}% (배당 제외)")
for n in (20, 30, 50):
    monthly_portfolio(P, bm, m & kospi, n, label=f"코스피 저PBR {n}")
monthly_portfolio(P, bm, m & kospi & prof, 30, label="코스피 흑자 저PBR 30")
monthly_portfolio(P, bm, m, 30, label="전체 저PBR 30")
monthly_portfolio(P, bm, m & P.is_kosdaq[None, :], 30, label="코스닥 저PBR 30")
for hm in (3, 6):
    monthly_portfolio(P, bm, m & kospi, 30, label=f"코스피 저PBR 30 · {hm}개월 보유", hold_months=hm)
mm = m & kospi & prof
monthly_portfolio(P, r(bm, mm) + r(np.nan_to_num(div), mm), mm, 30, label="코스피 흑자 저PBR+고배당 30")
# 대형 위주: 거래대금 상위 300 안에서
big = pd.DataFrame(np.where(m, P.tv20, np.nan)).rank(axis=1, ascending=False).to_numpy() <= 300
monthly_portfolio(P, bm, m & big, 30, label="거래대금 상위300 中 저PBR 30")
