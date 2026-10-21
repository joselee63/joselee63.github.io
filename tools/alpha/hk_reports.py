"""한경 컨센서스 기업 리포트 목록 수집 (로그인 불필요) — 날짜·종목코드·목표가·투자의견·애널리스트·증권사.
python tools/alpha/hk_reports.py <시작 YYYY-MM-DD> <끝 YYYY-MM-DD>
  → data-alpha/reports/hk_YYYY.csv (연도별, 이어받기: 이미 받은 주는 건너뜀)
주 단위로 기간을 나눠 페이지(80행)를 넘김. 요청 사이 HK_SLEEP초(기본 1.2). **병렬 실행 금지** —
2026-10 로컬에서 4개 병렬로 돌리다 IP 가 차단(403)됨. 오류·차단 시 그 주는 저장하지 않고 즉시 중단.
출력 폴더: 환경변수 HK_OUT (기본 data-alpha/reports) — GitHub Actions(alpha-reports.yml)는 data 브랜치 alpha/reports.
"""
import os
import datetime as dt
import html
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(os.environ.get("HK_OUT", Path(__file__).resolve().parents[2] / "data-alpha" / "reports"))
SLEEP = float(os.environ.get("HK_SLEEP", "1.2"))


class Blocked(Exception):
    pass
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://consensus.hankyung.com/analysis/list"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}
TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG = re.compile(r"<[^>]+>")
S = requests.Session()


def clean(x):
    return html.unescape(TAG.sub(" ", x)).strip()


def page(sd, ed, p):
    for i in range(4):
        try:
            r = S.get(URL, params=dict(sdate=sd, edate=ed, report_type="CO", pagenum=80, now_page=p),
                      headers=UA, timeout=30)
            if r.status_code == 403:
                raise Blocked(r.text[:80])
            r.raise_for_status()
            if "<tbody" not in r.text:
                raise ValueError("tbody 없음")
            return r.text
        except Blocked:
            raise
        except Exception as e:  # noqa: BLE001
            print("  retry", sd, p, repr(e)[:80]); time.sleep(5 * (i + 1))
    raise RuntimeError(f"페이지 실패 {sd} p{p}")


def parse(t):
    body = t[t.find("<tbody"):t.find("</tbody>")]
    rows = []
    for tr in TR.findall(body):
        td = TD.findall(tr)
        if len(td) < 6:
            continue
        a = re.search(r"report_idx=(\d+)[^>]*>([^<]*)</a>", td[1])
        if not a:
            continue
        nm = html.unescape(a.group(2)).strip()
        m = re.match(r"(.*)\((\w{6})\)\s*$", nm)
        summ = re.search(r"<li>(.*?)</li>", td[1], re.S)
        rows.append(dict(date=clean(td[0]), idx=int(a.group(1)), name=m.group(1) if m else nm,
                         ticker=m.group(2) if m else "", tp=clean(td[2]).replace(",", ""),
                         op=clean(td[3]), analyst=clean(td[4]), firm=clean(td[5]),
                         summary=clean(summ.group(1))[:300] if summ else ""))
    return rows


def main(s, e):
    d0 = dt.date.fromisoformat(s); d1 = dt.date.fromisoformat(e)
    d0 -= dt.timedelta(days=d0.weekday())
    cur = d0
    while cur <= d1:
        y = cur.year
        f = OUT / f"hk_{y}.csv"
        old = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["wk"])
        done = set(old["wk"]) if "wk" in old else set()
        new = []
        try:
          while cur <= d1 and cur.year == y:
              we = min(cur + dt.timedelta(days=6), dt.date(y, 12, 31))
              wk = cur.isoformat()
              if wk not in done or we >= dt.date.today() - dt.timedelta(days=7):
                  rows, p = [], 1
                  while True:
                      rr = parse(page(cur.isoformat(), we.isoformat(), p))
                      rows += rr
                      time.sleep(SLEEP)
                      if len(rr) < 80 or p > 40:
                          break
                      p += 1
                  for r in rows:
                      r["wk"] = wk
                  new += rows
                  print(f"  {wk}~{we}: {len(rows)}건", flush=True)
              cur = we + dt.timedelta(days=1)
              if cur.year != y:
                  break
        finally:
            if new:
                nd = pd.DataFrame(new)
                old = old[~old["wk"].isin(set(nd["wk"]))] if len(old) else old
                pd.concat([old, nd], ignore_index=True).to_csv(f, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
