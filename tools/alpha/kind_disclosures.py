"""KIND 공시 상세검색(로그인·API 키 불필요) — 이벤트 공시 목록 (분 단위 공시 시각, 상장폐지 종목 포함).
python tools/alpha/kind_disclosures.py <시작연도> <끝연도>
  → data-alpha/kind/<키워드>.csv (환경변수 KIND_OUT 로 변경 — alpha-reports.yml 은 data 브랜치 alpha/kind)  (time, kind_code, name, market, title, rcp)
kind_code 는 KIND 회사코드 5자리 = 종목코드 앞 5자리.
요청 사이 2.5초 (서버가 빠른 연속 요청에 '잠시 후 다시' 응답).
"""
import datetime as dt
import os
import html
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(os.environ.get("KIND_OUT", Path(__file__).resolve().parents[2] / "data-alpha" / "kind"))
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://kind.krx.co.kr/disclosure/details.do"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36",
      "Referer": URL + "?method=searchDetailsMain", "X-Requested-With": "XMLHttpRequest"}
KEYS = ["유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정", "자기주식취득결정",
        "자기주식취득신탁계약체결결정", "무상증자결정", "단일판매ㆍ공급계약체결", "최대주주변경"]
BASE = {f"disclosureType{k:02d}": "" for k in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 20)}
BASE.update(method="searchDetailsSub", currentPageSize="100", orderMode="1", orderStat="D", forward="details_sub",
            pDisclosureType01="", marketType="", repIsuSrtCd="", kosdaqSegment="", searchCodeType="",
            searchCorpName="", copyright="", bfrDsclsType="on")
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
S = requests.Session()


def get(key, sd, ed, page):
    for i in range(6):
        try:
            if i == 0 and page == 1:
                S.get(URL + "?method=searchDetailsMain", headers=UA, timeout=30)
            t = S.post(URL, data=dict(BASE, reportNm=key, fromDate=sd, toDate=ed, pageIndex=str(page)),
                       headers=UA, timeout=30).text
            time.sleep(2.5)
            if "잠시 후 다시" in t:
                print("   (대기)", flush=True); time.sleep(30 * (i + 1)); continue
            return t
        except Exception as e:  # noqa: BLE001
            print("   retry", repr(e)[:80]); time.sleep(10 * (i + 1))
    return ""


def parse(t):
    body = t[t.find("<tbody"):t.find("</tbody>")]
    out = []
    for r in ROW.findall(body):
        tm = re.search(r'<td class="txc">(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td>', r)
        cd = re.search(r"companysummary_open\('(\w+)'\)", r)
        ti = re.search(r"openDisclsViewer\('(\d+)'[^>]*title='([^']*)'", r)
        if not (tm and cd and ti):
            continue
        mk = re.search(r"alt='(코스닥|유가증권|코넥스)'", r)
        nm = re.search(r"title='([^']*)'>\s*[^<]*</a>", r)
        corr = "[정정]" in r
        out.append(dict(time=tm.group(1), kind_code=cd.group(1), name=html.unescape(nm.group(1)) if nm else "",
                        market=mk.group(1) if mk else "", title=html.unescape(ti.group(2)), corr=corr, rcp=ti.group(1)))
    return out


def total(t):
    m = re.search(r"전체 <em>([\d,]+)</em>건", t)
    return int(m.group(1).replace(",", "")) if m else 0


def main(y0, y1):
    for key in KEYS:
        f = OUT / f"{key.replace('ㆍ', '_')}.csv"
        old = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["ym"])
        done = set(old["ym"]) if len(old) else set()
        new = []
        for y in range(y0, y1 + 1):
            for mth in range(1, 13):
                sd = dt.date(y, mth, 1)
                if sd > dt.date.today():
                    break
                ed = (pd.Timestamp(sd) + pd.offsets.MonthEnd(0)).date()
                ym = f"{y}-{mth:02d}"
                if ym in done and ed < dt.date.today() - dt.timedelta(days=3):
                    continue
                t = get(key, sd.isoformat(), ed.isoformat(), 1)
                rows, n = parse(t), total(t)
                p = 2
                while len(rows) < n and p <= 30:
                    rr = parse(get(key, sd.isoformat(), ed.isoformat(), p))
                    if not rr:
                        break
                    rows += rr; p += 1
                for r in rows:
                    r["ym"] = ym
                new += rows
                print(f"  {key} {ym}: {len(rows)}/{n}", flush=True)
            if new:   # 연도마다 저장
                nd = pd.DataFrame(new)
                old = old[~old["ym"].isin(set(nd["ym"]))] if len(old) else old
                old = pd.concat([old, nd], ignore_index=True)
                old.to_csv(f, index=False, encoding="utf-8-sig")
                new = []


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
