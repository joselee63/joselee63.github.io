"""리포트 페이지 종목 상세의 일봉 차트 데이터 — reports/px/<종목코드>.json

reports.yml(GitHub Actions)이 리포트 데이터(data.json)를 올릴 때 실행한다.
data.json 의 종목마다 네이버 차트(fchart, 사이트 빌드와 같은 출처)에서 일봉 최근 약 2년(500봉)을 받아
{"d":[YYYYMMDD], "o":[], "h":[], "l":[], "c":[]} 로 저장한다. 표준 라이브러리만 쓴다.

  python px_charts.py data.json 출력폴더
받지 못한 종목은 건너뛴다(이전 파일이 있으면 그대로 남는다).
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://fchart.stock.naver.com/sise.nhn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BARS = 500


def fetch(code):
    q = urllib.parse.urlencode({"symbol": code, "timeframe": "day", "count": BARS, "requestType": 0})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": UA, "Referer": "https://finance.naver.com/"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    m = re.search(rb'encoding="([^"]+)"', raw[:200])
    text = raw.decode(m.group(1).decode() if m else "euc-kr", errors="replace")
    rows = {}
    for item in re.findall(r'<item data="([^"]*)"', text):
        p = item.split("|")
        try:
            d, o, h, l, c = int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])
        except (ValueError, IndexError):
            continue
        if c <= 0:
            continue
        o = o if o > 0 else c
        h = h if h > 0 else c
        l = l if l > 0 else c
        rows[d] = (o, max(o, h, l, c), min(o, h, l, c), c)
    if len(rows) < 2:
        raise ValueError("데이터 없음")
    ds = sorted(rows)
    num = lambda x: int(x) if float(x).is_integer() else round(x, 2)
    return {"d": ds, **{k: [num(rows[d][i]) for d in ds] for i, k in enumerate("ohlc")}}


def main(src, out):
    stk = json.loads(Path(src).read_text(encoding="utf-8")).get("stk", {})
    codes = sorted({v["c"] for v in stk.values() if v.get("c") and re.fullmatch(r"[0-9A-Z]{6}", v["c"])})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, []
    for code in codes:
        for i in range(3):
            try:
                rec = fetch(code)
                (out / f"{code}.json").write_text(json.dumps(rec, separators=(",", ":")), encoding="utf-8")
                ok += 1
                break
            except Exception as e:  # noqa: BLE001 — 한 종목 실패로 전체를 멈추지 않음
                if i == 2:
                    fail.append(f"{code}({e})")
                time.sleep(1 + i)
        time.sleep(0.05)
    print(f"일봉 차트 {ok}/{len(codes)} 종목" + (f" · 실패 {len(fail)}: {', '.join(fail[:10])}" if fail else ""))
    return 0 if ok or not codes else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
