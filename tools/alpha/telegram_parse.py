"""텔레그램 데스크톱 '대화 내보내기'(HTML 또는 JSON) → 메시지 표 (로컬 전용)
python tools/alpha/telegram_parse.py <내보내기 폴더> [이름]
  → data-alpha/telegram/<이름>.pkl  (id, dt[KST], text, react[반응 합], link, fwd)
원문은 채널 작성자의 저작물이므로 저장소·사이트에 올리지 않는다 (data-alpha 는 git 제외).
"""
import html
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data-alpha" / "telegram"
MSG = re.compile(r'<div class="message default clearfix[^"]*" id="message(-?\d+)">(.*?)(?=<div class="message (?:default|service)|\Z)', re.S)


def _clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_html(d):
    files = sorted(Path(d).glob("messages*.html"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 1))
    rows = []
    for p in files:
        s = p.read_text(encoding="utf-8")
        for mid, b in MSG.findall(s):
            dt = re.search(r'class="pull_right date details" title="([^"]+)"', b)
            tx = re.search(r'<div class="text">(.*?)</div>', b, re.S)
            rx = re.search(r'<span class="reactions">(.*?)</span>\s*</div>', b, re.S) or re.search(r'class="reactions"(.*)', b, re.S)
            react = sum(int(x) for x in re.findall(r'<span class="count">\s*(\d+)\s*</span>', rx.group(1))) if rx else 0
            text = _clean(tx.group(1)) if tx else ""
            rows.append({"id": int(mid), "dt": dt.group(1) if dt else None, "text": text, "react": react,
                         "link": bool(re.search(r"https?://", text)), "fwd": 'class="forwarded body"' in b})
    df = pd.DataFrame(rows).dropna(subset=["dt"])
    # '23.07.2019 12:49:19 UTC+09:00' → 한국 시각
    df["dt"] = pd.to_datetime(df["dt"].str[:19], format="%d.%m.%Y %H:%M:%S")
    return df


def parse_json(d):
    j = json.loads((Path(d) / "result.json").read_text(encoding="utf-8"))
    rows = []
    for m in j.get("messages", []):
        if m.get("type") != "message":
            continue
        t = m.get("text", "")
        if isinstance(t, list):
            t = "".join(x if isinstance(x, str) else x.get("text", "") for x in t)
        react = sum(r.get("count", 0) for r in m.get("reactions", []) or [])
        rows.append({"id": m["id"], "dt": m["date"], "text": t.strip(), "react": react,
                     "link": "http" in t, "fwd": "forwarded_from" in m})
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])                             # 내보낸 PC의 현지 시각(한국)
    return df


if __name__ == "__main__":
    d = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else d.name
    df = parse_json(d) if (d / "result.json").exists() else parse_html(d)
    df = df.sort_values("dt").drop_duplicates("id").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_pickle(OUT / f"{name}.pkl")
    print(f"{name}: 메시지 {len(df):,} ({df.dt.min():%Y-%m-%d} ~ {df.dt.max():%Y-%m-%d}) · 본문 있음 {(df.text.str.len() > 0).mean():.0%} · "
          f"링크 {df.link.mean():.0%} · 반응 중앙 {df.react.median():.0f} → {OUT / (name + '.pkl')}")
    print(df.groupby(df.dt.dt.year).agg(n=("id", "size"), react=("react", "median")).T.to_string())
