"""해외·매크로 일봉 수집 (yfinance) → data-closebet/macro.csv
python tools/closebet/fetch_macro.py
"""
from pathlib import Path
import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parents[2] / "data-closebet"
TICK = {"spx": "^GSPC", "ndx": "^NDX", "sox": "^SOX", "vix": "^VIX", "nq": "NQ=F", "es": "ES=F",
        "krw": "KRW=X", "ewy": "EWY", "kospi": "^KS11", "kosdaq": "^KQ11", "nk": "^N225", "us10y": "^TNX"}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rows = []
    for k, t in TICK.items():
        d = yf.download(t, start="2014-06-01", progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d[["Open", "High", "Low", "Close"]].reset_index()
        d.columns = ["date", "open", "high", "low", "close"]
        d["key"] = k
        rows.append(d)
        print(k, len(d), d["date"].min().date(), d["date"].max().date())
    pd.concat(rows).to_csv(OUT / "macro.csv", index=False)
