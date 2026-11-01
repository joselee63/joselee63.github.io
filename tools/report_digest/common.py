"""리포트 요약 — 공통 경로·저장소

비공개(이 PC에만, OneDrive·저장소 밖):  %LOCALAPPDATA%\\krsc-reports\\
  config.json   채널 번호 등 (저장소에 넣지 않음)
  msgs.jsonl    채널 글 원문 (2026-01-15 이후, 새 글이 계속 붙음) — 절대 공유·업로드 금지
  rw.jsonl      리포트마다 우리 말 정리 (Claude 가 씀, 공개 데이터의 원본)
  ai/           날짜별 요약 · 종목 의견 합치기 · 산업 · 매크로 (Claude 가 씀)
  work/         Claude 작업 입력·출력 (실행마다 새로 만듦)
  out/          공개용 data.json · ai.json (릴리스 reports-data 로 올림)
텔레그램 세션은 레이더 것(%LOCALAPPDATA%\\krsc-radar\\telegram.session)을 읽기 전용으로만 씀.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("KRSC_REPORTS_HOME") or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "krsc-reports")
MSGS, RW, CONFIG, STATE = HOME / "msgs.jsonl", HOME / "rw.jsonl", HOME / "config.json", HOME / "state.json"
AI, WORK, OUT = HOME / "ai", HOME / "work", HOME / "out"
SITE = "https://joselee63.github.io"
REPO_SLUG = "joselee63/joselee63.github.io"
RELEASE = "reports-data"
WINDOW_DAYS = 14                     # 공개 페이지에 싣는 기간
for d in (HOME, AI, WORK, OUT):
    d.mkdir(parents=True, exist_ok=True)


def kst_now():
    return dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(**kw):
    s = state()
    s.update(kw)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def load_msgs():
    out = {}
    if MSGS.exists():
        with MSGS.open(encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    m = json.loads(ln)
                    out[m["id"]] = m
    return [out[k] for k in sorted(out)]


def append_msgs(ms):
    with MSGS.open("a", encoding="utf-8") as f:
        for m in ms:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def load_rw():
    out = {}
    if RW.exists():
        with RW.open(encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    r = json.loads(ln)
                    out[int(r["id"])] = r["rw"]
    return out


def append_rw(d):
    with RW.open("a", encoding="utf-8") as f:
        for k, v in d.items():
            f.write(json.dumps({"id": int(k), "rw": v}, ensure_ascii=False) + "\n")


def pub_id(msg_id):
    """공개용 번호 — 텔레그램 글 번호를 드러내지 않게 (config 의 비밀 소금으로 해시)"""
    salt = config().get("salt", "")
    return int(hashlib.sha1(f"{salt}:{msg_id}".encode()).hexdigest()[:10], 16)


def jload(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def jsave(p, obj, compact=False):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1),
                       encoding="utf-8")
