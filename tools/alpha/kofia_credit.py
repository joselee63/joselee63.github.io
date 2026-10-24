"""금융투자협회 FreeSIS 일별 증시자금 → data-alpha/kofia/
python tools/alpha/kofia_credit.py [시작연도]
  money.csv  (STATSCU0100000060BO 증시자금추이): date, deposit(투자자예탁금), deriv_dep(파생 예수금), rp(RP 매도잔고),
             unpaid(위탁매매 미수금), forced(실제 반대매매금액), forced_pct(미수금 대비 반대매매 비중 %)  — 금액 단위 백만원
  credit.csv (STATSCU0100000070BO 신용공여 잔고): date, credit(신용융자 전체), credit_ks(유가증권), credit_kq(코스닥),
             short_bal(신용대주 전체), short_ks, short_kq, x8, pledge(예탁증권담보융자)  — 백만원
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parents[2] / "data-alpha" / "kofia"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
HD = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json; charset=UTF-8", "Referer": "https://freesis.kofia.or.kr/stat/FreeSIS.do"}
SETS = {
    "money": ("STATSCU0100000060BO", ["deposit", "deriv_dep", "rp", "unpaid", "forced", "forced_pct"]),
    "credit": ("STATSCU0100000070BO", ["credit", "credit_ks", "credit_kq", "short_bal", "short_ks", "short_kq", "x8", "pledge"]),
}


def get(obj, sd, ed):
    body = {"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D", "tmpV45": sd, "tmpV46": ed, "OBJ_NM": obj}}
    for i in range(5):
        try:
            r = requests.post(URL, headers=HD, data=json.dumps(body), timeout=60)
            return r.json().get("ds1") or []
        except Exception as e:  # noqa: BLE001
            print("  retry", e); time.sleep(5 * (i + 1))
    return []


def main(y0):
    today = dt.date.today()
    for name, (obj, cols) in SETS.items():
        rows = []
        for y in range(y0, today.year + 1):
            part = get(obj, f"{y}0101", f"{y}1231")
            rows += part
            print(name, y, len(part), flush=True)
            time.sleep(1)
        df = pd.DataFrame(rows)
        df = df.rename(columns={"TMPV1": "date", **{f"TMPV{i + 2}": c for i, c in enumerate(cols)}})
        df = df[["date"] + [c for c in cols if c in df.columns]].drop_duplicates("date").sort_values("date")
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"→ {OUT / (name + '.csv')} {len(df)}행 {df['date'].min()}~{df['date'].max()}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1998)
