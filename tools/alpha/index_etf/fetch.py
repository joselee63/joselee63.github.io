"""지수 ETF 양방향 연구용 일봉: KODEX200·인버스·코스닥150·코스닥150선물인버스 + 지수 (네이버 수정주가 = 분배금 반영)"""
import requests, json, pandas as pd, time
def get(s):
    r = requests.get("https://api.finance.naver.com/siseJson.naver", params={"symbol": s, "requestType": 1, "startTime": "19900101", "endTime": "20261102", "timeframe": "day"}, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
    rows = json.loads(r.text.strip().replace("'", '"'))
    df = pd.DataFrame(rows[1:], columns=["date","open","high","low","close","volume","fr"])
    df["date"] = pd.to_datetime(df["date"].str.strip(), format="%Y%m%d")
    time.sleep(0.5)
    return df.set_index("date")[["open","high","low","close","volume"]].astype(float)
d = {s: get(s) for s in ["069500","114800","229200","251340","KPI200","KOSPI","KOSDAQ"]}
from pathlib import Path
out = Path(__file__).resolve().parents[3] / "data-alpha" / "index_etf" / "raw.pkl"; out.parent.mkdir(parents=True, exist_ok=True)
pd.to_pickle(d, out)
for k,v in d.items(): print(k, v.index[0].date(), v.index[-1].date(), len(v))
# 분배금 반영 여부: KODEX200 / KOSPI200 비율
r = (d["069500"].close / d["KPI200"].close).dropna()
print(r.resample("YE").last().round(2).to_string())
# 하루 비율 점프 (분배락)
j = r.pct_change(); print(j[j.abs()>0.006].tail(12))
