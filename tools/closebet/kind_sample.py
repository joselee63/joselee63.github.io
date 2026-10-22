"""B2. 재료(공시) 표본 수집 — 최종 규칙 선택 종목 무작위 표본의 신호일 전후 KIND 공시 제목
python tools/closebet/kind_sample.py [n=800]
  → data-closebet/news_sample.csv  (표본: id, date, ticker, name — 수익률은 넣지 않음, 분류 후 결합)
  → data-closebet/news_kind.csv    (id 별 공시: time, title)
조회 구간: 신호일 −7일 ~ 신호일 +1일 (분 단위 시각으로 '매수 전/후' 구분은 분류 단계에서)
요청 간격 2.5초 (tools/alpha/kind_disclosures.get)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alpha"))
import kind_disclosures as K  # noqa: E402
from cb import CB  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 800

if __name__ == "__main__":
    R = pd.read_pickle(CB / "_R.pkl")
    uni = pd.read_csv(CB.parent / "data-backtest/universe.csv", dtype=str)
    name = dict(zip(uni["ticker"], uni["name"]))
    S = R[(R["hi_today"] < 0.285) & (R["day"] < 0.25)].sort_values(["date", "pos", "day"], ascending=[True, False, False])
    S = S.groupby("date").head(3)
    smp = S.sample(N, random_state=42).sort_values("date")[["date", "ticker"]].reset_index(drop=True)
    smp["id"] = range(len(smp))
    smp["name"] = smp["ticker"].map(name)
    smp.to_csv(CB / "news_sample.csv", index=False, encoding="utf-8-sig")
    f = CB / "news_kind.csv"
    done = set(pd.read_csv(f)["id"]) if f.exists() else set()
    first = True
    for _, x in smp.iterrows():
        if x["id"] in done:
            continue
        sd = (x["date"] - pd.Timedelta(days=7)).date().isoformat()
        ed = (x["date"] + pd.Timedelta(days=1)).date().isoformat()
        if first:
            K.S.get(K.URL + "?method=searchDetailsMain", headers=K.UA, timeout=30); first = False
        t = ""
        for _ in range(4):
            try:
                t = K.S.post(K.URL, data=dict(K.BASE, reportNm="", fromDate=sd, toDate=ed, pageIndex="1",
                                              searchCorpName=x["name"], repIsuSrtCd="A" + x["ticker"]),
                             headers=K.UA, timeout=30).text
                K.time.sleep(2.5)
                if "잠시 후 다시" in t:
                    K.time.sleep(30); continue
                break
            except Exception as e:  # noqa: BLE001
                print("retry", e); K.time.sleep(10)
        rows = [r for r in K.parse(t) if r["kind_code"] == x["ticker"][:5]]
        out = pd.DataFrame(rows or [dict(time="", title="(공시 없음)")])
        out["id"] = x["id"]
        out[["id", "time", "title"]].to_csv(f, mode="a", header=not f.exists(), index=False, encoding="utf-8-sig")
        if x["id"] % 50 == 0:
            print(x["id"], x["date"].date(), x["name"], len(rows), flush=True)
