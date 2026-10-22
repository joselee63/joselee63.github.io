"""A2b. KOSDAQ>20일선 날 + S1 선별(상위3) 안에서의 시황 조건 (비중 조절 후보)
python tools/closebet/day_test_r1.py
"""
import numpy as np
import pandas as pd
from cb import CB, daily
from day_test import test, run

R = pd.read_pickle(CB / "_R.pkl"); days = pd.read_pickle(CB / "days2.pkl")
S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False])
port = S.groupby("date").head(3).groupby("date")["on"].mean()
theme = R.groupby("date")["peer_n3"].mean()
D = days.join(port.rename("port"), how="inner")
D["theme"] = theme
D["theme_pct"] = D["theme"].expanding(120).apply(lambda a: (a[:-1] < a[-1]).mean(), raw=True)
D["hi52_pct"] = (D["n_hi52"] / D["n_live"]).rolling(250, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean(), raw=True)
run(D, "R1+S1 상위3")
print("-- 테마·롤링 분위 (point-in-time)")
test(D, "테마동반(풀 평균 동료+3%) 상위20%", D["theme_pct"] >= 0.8)
test(D, "테마동반 하위20%", D["theme_pct"] <= 0.2)
test(D, "후보수 롤링 상위20%", D["pool_pct"] >= 0.8)
test(D, "후보수 롤링 하위20%", D["pool_pct"] <= 0.2)
test(D, "+5%종목 롤링 하위20%", D["up5_pct"] <= 0.2)
test(D, "KOSDAQ 시가→종가 롤링 하위20%", D["kqoc_pct"] <= 0.2)
test(D, "신고가 비율 롤링 상위20%", D["hi52_pct"] >= 0.8)
test(D, "목요일 & 옵션만기 아님", (D["dow"] == 3) & ~D["opt_exp"])
test(D, "목요일 & 옵션만기", (D["dow"] == 3) & D["opt_exp"])
D.to_pickle(CB / "_D1.pkl")
