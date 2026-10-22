"""A3. 시장 필터 재설계 — KOSPI>60일선 대신/추가로 무엇이 좋은가 (시장필터 미적용 전체 후보에서)
분위수는 과거 250거래일 롤링(그날 포함) 기준 → 미래 정보 없음.
python tools/closebet/regime_test.py
"""
import numpy as np
import pandas as pd
from cb import CB, stats, line, daily

df = pd.read_pickle(CB / "cands.pkl"); days = pd.read_pickle(CB / "days.pkl")


def rollpct(x, n=250):
    return x.rolling(n, min_periods=120).apply(lambda a: (a[:-1] < a[-1]).mean() if len(a) > 1 else np.nan, raw=True)


days["up5_pct"] = rollpct(days["n_up5_rel"])
days["adv_pct"] = rollpct(days["adv_ratio"])
days["kqoc_pct"] = rollpct(days["kq_oc"])
days["pool_pct"] = rollpct(days["pool_all"])
days["kq_above20"] = days["kq_ma20"] > 0
days["kq_above60"] = days["kq_ma60"] > 0
days["ks_above60"] = days["ks_ma60"] > 0
days.to_pickle(CB / "days2.pkl")

port_all = daily(df, 3)                 # 시장필터 없이 그날 풀 상위3
D = days.join(port_all.rename("port"), how="inner")


def show(name, cond):
    c = cond.reindex(D.index).fillna(False).astype(bool)
    print(line(stats(D.loc[c, "port"], label=name)))


print("후보 있는 전체 날:", line(stats(D["port"], label="필터 없음")))
show("R0 KOSPI>60일선 (기준선)", D["ks_above60"])
show("R1 KOSDAQ>20일선", D["kq_above20"])
show("R2 KOSDAQ>60일선", D["kq_above60"])
show("R3 KOSPI>60 & KOSDAQ>20", D["ks_above60"] & D["kq_above20"])
show("R4 KOSPI>60 or KOSDAQ>20", D["ks_above60"] | D["kq_above20"])
for m in (5, 10, 20, 40):
    show(f"   KOSDAQ>{m}일선 (민감도)", D["kq_ma20"].notna() & (pd.Series(np.nan, D.index) if False else True) & (days["kq_ma20"].reindex(D.index) > -9) & (
        (pd.read_pickle(CB / "days.pkl")["kq_ma20"] * 0 + 1).reindex(D.index) > 0) & (D.index.isin(D.index)) & (
        (lambda s: s.reindex(D.index))(pd.Series(0, days.index)) == 0) if False else None) if False else None
# KOSDAQ n일선 민감도 (직접 계산)
ix = pd.read_csv(CB.parent / "data-backtest/sectors/index_ohlcv.csv", dtype={"index_code": str}, parse_dates=["date"])
kq = ix[ix["index_code"] == "2001"].set_index("date")["close"].reindex(days.index).ffill()
for m in (5, 10, 20, 40, 60, 120):
    show(f"   KOSDAQ>{m}일선", kq / kq.rolling(m).mean() > 1)
print()
show("R1 + 약세마감 아님(kq 시가→종가 하위20% 제외)", D["kq_above20"] & (D["kqoc_pct"] > 0.2))
show("R1 + +5%종목수 하위20% 제외", D["kq_above20"] & (D["up5_pct"] > 0.2))
show("R1 + 상승비율 하위20% 제외", D["kq_above20"] & (D["adv_pct"] > 0.2))
show("R1 + KOSDAQ 당일 > −1.5%", D["kq_above20"] & (D["kq_ret"] > -0.015))
show("R1 + 후보수 ≥ 9", D["kq_above20"] & (D["pool_all"] >= 9))
show("R1 + 약세마감·+5%하위 제외", D["kq_above20"] & (D["kqoc_pct"] > 0.2) & (D["up5_pct"] > 0.2))
show("R1 + 목요일 제외", D["kq_above20"] & (D["dow"] != 3))
show("R1 + 옵션만기 제외", D["kq_above20"] & ~D["opt_exp"])
show("R1 + 닛케이 −1.5%↓ 제외", D["kq_above20"] & ~(D["nk_prev"] <= -0.015))
show("R1 + 직전SOX −3%↓ 제외", D["kq_above20"] & ~(D["sox_prev"] <= -0.03))
print("\n쉬는 날(R1 불충족) 성적:")
show("KOSDAQ<20일선 날", ~D["kq_above20"])
show("KOSDAQ<20일선 & KOSPI>60 (기준선은 매매)", ~D["kq_above20"] & D["ks_above60"])
print("\n연도별:")
for nm, c in (("R0", D["ks_above60"]), ("R1", D["kq_above20"]), ("R1+약세제외", D["kq_above20"] & (D["kqoc_pct"] > 0.2) & (D["up5_pct"] > 0.2))):
    print(line(stats(D.loc[c.fillna(False), "port"], label=nm), True))
