"""텔레그램 속보 글 → '기사 제목 + 원문 링크'만 골라 저장소 data 브랜치 news/tg/날짜.jsonl 로 올리기 (내 PC 전용)

  · 원문 수집은 종베 레이더(tools/radar/tg.py)가 radar-out/telegram/날짜.jsonl 에 함 — 이 파일은 계속 로컬 전용
  · 올리는 것: 기사 링크가 있는 글의 첫 줄(기사 제목) · 매체 · 원문 링크 · 시각
  · 올리지 않는 것: 링크 없는 채널 코멘트 · 급등 목록 · 채널 이름 · 세션 파일
  · 올린 뒤 GitHub 워크플로 news.yml 이 언론사 RSS 와 합쳐 사이트 시황판 뉴스(news.json)를 만듦

사용 (레이더가 장중 정해진 시각에 자동 호출):
  python tools/market/news_tg.py push          오늘·어제 파일을 data 브랜치에 올리고 news.yml 시작
  python tools/market/news_tg.py dump DIR       오늘·어제 파일을 DIR/날짜.jsonl 로만 저장 (확인용)
"""
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("RADAR_DIR", ROOT / "radar-out"))
REPO = "joselee63/joselee63.github.io"

MEDIA = {
    "yna.co.kr": "연합뉴스", "news1.kr": "뉴스1", "newsis.com": "뉴시스", "mt.co.kr": "머니투데이", "edaily.co.kr": "이데일리",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "sedaily.com": "서울경제", "heraldcorp.com": "헤럴드경제",
    "inews24.com": "아이뉴스24", "fnnews.com": "파이낸셜뉴스", "biz.chosun.com": "조선비즈", "chosun.com": "조선일보",
    "etnews.com": "전자신문", "dt.co.kr": "디지털타임스", "businesspost.co.kr": "비즈니스포스트", "asiae.co.kr": "아시아경제",
    "ekn.kr": "에너지경제", "dailian.co.kr": "데일리안", "thebell.co.kr": "더벨", "infostock.co.kr": "인포스탁",
    "zdnet.co.kr": "지디넷코리아", "hankookilbo.com": "한국일보", "donga.com": "동아일보", "joongang.co.kr": "중앙일보",
    "khan.co.kr": "경향신문", "hani.co.kr": "한겨레", "ytn.co.kr": "YTN", "mbn.co.kr": "MBN", "sbs.co.kr": "SBS",
    "kbs.co.kr": "KBS", "imbc.com": "MBC", "seoul.co.kr": "서울신문", "newspim.com": "뉴스핌", "ajunews.com": "아주경제",
    "etoday.co.kr": "이투데이", "wowtv.co.kr": "한국경제TV", "bizwatch.co.kr": "비즈워치", "ddaily.co.kr": "디지털데일리",
    "nocutnews.co.kr": "노컷뉴스", "kmib.co.kr": "국민일보", "munhwa.com": "문화일보", "segye.com": "세계일보",
    "naver.com": "네이버", "yahoo.com": "야후", "advfn.com": "ADVFN", "einfomax.co.kr": "연합인포맥스", "newsprime.co.kr": "프라임경제", "bloomberg.com": "블룸버그", "reuters.com": "로이터", "cnbc.com": "CNBC", "wsj.com": "WSJ",
    "ft.com": "FT", "nasdaq.com": "나스닥", "investing.com": "인베스팅", "paxnet.co.kr": "팍스넷", "pinpointnews.co.kr": "핀포인트뉴스",
    "dealsite.co.kr": "딜사이트", "theguru.co.kr": "더구루", "mediapen.com": "미디어펜", "newsway.co.kr": "뉴스웨이",
    "bloter.net": "블로터", "thelec.kr": "디일렉", "elec4.co.kr": "전기신문", "kpanews.co.kr": "약사공론", "hitnews.co.kr": "히트뉴스",
    "biospectator.com": "바이오스펙테이터", "yakup.com": "약업신문", "dnews.co.kr": "대한경제", "kbiz.co.kr": "중소기업뉴스",
}
TAGS = {"속보", "단독", "특징주", "컨콜", "종합", "1보", "2보", "3보", "공시", "마감", "개장", "장중", "시황", "긴급", "Breaking", "외신"}
URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+")


def media_of(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    host = host.split(":")[0]
    for d, n in MEDIA.items():
        if host == d or host.endswith("." + d):
            return n
    parts = host.split(".")
    return parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne") else (parts[-2] if len(parts) >= 2 else host)


def parse(text):
    """글 → (제목, 링크, 매체) 또는 None (기사 링크가 없으면 버림)"""
    urls = [u.rstrip(".,") for u in URL_RE.findall(text or "")]
    urls = [u for u in urls if not re.search(r"//(t\.me|telegram\.me|telegram\.org|youtu|www\.youtube)", u)]
    if not urls:
        return None
    title = None
    for line in str(text).splitlines():
        line = URL_RE.sub("", line).strip()
        line = re.sub(r"^[^\w\[\(]+", "", line).strip()                    # 맨 앞 이모지·기호
        if len(line) >= 8 and not line.startswith("[관련"):
            title = line
            break
    if not title:
        return None
    url = urls[0]; media = media_of(url)
    m = re.match(r"^\[([^\]]{1,14})\]\s*", title)                          # [매체] 머리말은 떼서 매체로
    if m and m.group(1).strip() not in TAGS:
        media = m.group(1).strip()
        title = title[m.end():].strip()
    title = re.sub(r"\s+", " ", title)[:160]
    return (title, url, media) if len(title) >= 6 else None


def norm(h):
    return re.sub(r"[\W_]+", "", re.sub(r"^\[[^\]]+\]", "", h))[:40]


def day_items(day):
    """radar-out/telegram/YYYYMMDD.jsonl → [{t, m, h, u}] (중복 제목 제거, 시각순)"""
    f = OUT / "telegram" / f"{day:%Y%m%d}.jsonl"
    if not f.exists():
        return []
    seen, out = set(), []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        p = parse(j.get("text", ""))
        if not p:
            continue
        k = norm(p[0])
        if k in seen:
            continue
        seen.add(k)
        out.append({"t": j["dt"][11:16], "m": p[2], "h": p[0], "u": p[1]})
    return sorted(out, key=lambda x: x["t"])


def to_jsonl(items):
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items)


def gh_path():
    g = shutil.which("gh")
    if g:
        return g
    for c in (r"C:\Program Files\GitHub CLI\gh.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe")):
        if os.path.exists(c):
            return c
    return None


def push(days=2, log=print, dispatch=True):
    """오늘(·어제) 파일을 data 브랜치 news/tg/ 에 올림 → 바뀐 게 있으면 news.yml 시작"""
    g = gh_path()
    if not g:
        log("뉴스 올리기: gh(GitHub CLI)가 없어 건너뜀"); return 0
    kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    changed = 0
    for i in range(days):
        day = (kst - dt.timedelta(days=i)).date()
        items = day_items(day)
        if not items:
            continue
        body = to_jsonl(items).encode("utf-8")
        path = f"news/tg/{day:%Y-%m-%d}.jsonl"
        r = subprocess.run([g, "api", f"repos/{REPO}/contents/{path}?ref=data"], capture_output=True, text=True, timeout=60)
        sha = None
        if r.returncode == 0:
            cur = json.loads(r.stdout)
            sha = cur.get("sha")
            try:
                if base64.b64decode(cur.get("content", "")) == body:
                    continue                                                  # 같으면 건너뜀
            except ValueError:
                pass
        req = {"message": f"news tg {day:%Y-%m-%d} ({len(items)}건)", "branch": "data",
               "content": base64.b64encode(body).decode("ascii")}
        if sha:
            req["sha"] = sha
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(req, tf)
        try:
            r = subprocess.run([g, "api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", tf.name],
                               capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(tf.name)
        if r.returncode == 0:
            changed += 1; log(f"뉴스 올리기: {path} {len(items)}건")
        else:
            log(f"뉴스 올리기 실패 {path}: {(r.stderr or r.stdout).strip()[:150]}")
    if changed and dispatch:
        r = subprocess.run([g, "workflow", "run", "news.yml", "-R", REPO], capture_output=True, text=True, timeout=60)
        log("사이트 뉴스 갱신 시작: " + ("성공" if r.returncode == 0 else "실패 " + (r.stderr or r.stdout).strip()[:150]))
    return changed


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "push"
    if cmd == "push":
        push()
    elif cmd == "dump":
        d = Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True)
        kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
        for i in range(2):
            day = (kst - dt.timedelta(days=i)).date()
            it = day_items(day)
            (d / f"{day:%Y-%m-%d}.jsonl").write_text(to_jsonl(it), encoding="utf-8", newline="\n")
            print(day, len(it))
    else:
        print(__doc__)
