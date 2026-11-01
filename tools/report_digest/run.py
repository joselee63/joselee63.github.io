"""리포트 요약 — 실행 진입점 (레이더 가상환경 파이썬으로 실행: %LOCALAPPDATA%\\krsc-radar-venv\\Scripts\\python.exe)

  run.py update      새 글 받기 → 숫자 정리 → 사이트에 올리기 (Claude 없이, 1~2분) — 페이지의 '지금 업데이트' 버튼
  run.py prepare     새 글 받기 → 숫자 정리 → Claude 할 일(work/) 만들기 — 예약 작업 1단계
  run.py finalize    Claude 결과 합치기(베낌 검사) → 다시 정리 → 사이트에 올리기 — 예약 작업 마지막 단계
  run.py build       받기 없이 다시 정리만 (올리지 않음)
  run.py status      저장소 상태
  run.py bootstrap 내보내기.json   처음 한 번: 텔레그램 내보내기에서 글을 가져와 비공개 저장소 만들기
"""
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402


def _build():
    import build as B
    import parse as P
    t0 = time.time()
    U = P.parse_all(C.load_msgs())
    data, ctx = B.build(U)
    print(f"[build] 리포트 기록 {len(U):,}건 정리 ({time.time() - t0:.0f}초)")
    return data, ctx


def cmd_update(publish=True):
    import build as B
    import fetch
    try:
        fetch.fetch()
    except SystemExit as e:
        print(f"[fetch] 실패: {e}")
    data, ctx = _build()
    B.write_public(data, ctx)
    if publish:
        import publish as PB
        PB.publish()


def cmd_prepare():
    import fetch
    import work
    try:
        fetch.fetch()
    except SystemExit as e:
        print(f"[fetch] 실패 — 이미 받은 글로만 진행: {e}")
    data, ctx = _build()
    import build as B
    B.write_public(data, ctx)
    work.prepare(data, ctx, force_week="--week" in sys.argv)


def cmd_finalize():
    import build as B
    import publish as PB
    import work
    data, ctx = _build()
    work.merge(ctx)
    data, ctx = _build()
    B.write_public(data, ctx)
    if "--no-push" not in sys.argv:
        PB.publish()


def cmd_status():
    s = C.state()
    ms = C.load_msgs()
    rw = C.load_rw()
    print(json.dumps(dict(home=str(C.HOME), msgs=len(ms), last_msg=ms[-1]["date"] if ms else None, rw=len(rw), **s), ensure_ascii=False, indent=1))


def cmd_bootstrap(path):
    """텔레그램 데스크톱 JSON 내보내기 → msgs.jsonl (2026-01-15 이후, 글이 있는 것만) · config.json"""
    print(f"[bootstrap] 읽는 중: {path}")
    d = json.load(open(path, encoding="utf-8"))
    cfg = C.config()
    cfg.setdefault("salt", secrets.token_hex(16))
    cfg["channel_id"] = int(d["id"])
    C.CONFIG.write_text(json.dumps(cfg, indent=1), encoding="utf-8")

    def txt(m):
        t = m.get("text")
        return "".join(x if isinstance(x, str) else x.get("text", "") for x in t) if isinstance(t, list) else (t or "")
    have = {m["id"] for m in C.load_msgs()}
    out = []
    for m in d["messages"]:
        if m.get("type") != "message" or m["date"] < "2026-01-15" or m["id"] in have:
            continue
        t = txt(m)
        if not t.strip() and "file" not in m:
            continue
        out.append(dict(id=m["id"], date=m["date"], text=t, file=m.get("file_name") or ("F" if "file" in m else None), photo="photo" in m,
                        mime=m.get("mime_type"), fwd=bool(m.get("forwarded_from")), reply=m.get("reply_to_message_id"), size=m.get("file_size")))
    out.sort(key=lambda m: m["id"])
    C.append_msgs(out)
    C.save_state(bootstrap=path, last_id=max([m["id"] for m in C.load_msgs()] or [0]))
    print(f"[bootstrap] 글 {len(out):,}개 저장 → {C.MSGS}")


def cmd_import(rw_dir, ai_dir=None):
    """시안 때 만든 정리·해석 가져오기 (한 번만). 목표가 판정이 바뀐 리포트는 정리 글의 목표가 문장을 사실 값으로 바꿈"""
    data, ctx = _build()
    INT = ctx["INT"]
    alias = {m: i for i, v in INT.items() for m in v["raw"].get("members", [i])}     # 합쳐진 글 번호 → 대표 번호
    rw = {}
    for p in sorted(Path(rw_dir).glob("part*.json")):
        for k, v in json.loads(p.read_text(encoding="utf-8")).items():
            i = alias.get(int(k))
            if i is None:
                continue
            x = INT[i]["pub"]
            if "기록" in (v.get("tp") or "") or "기록상" in (v.get("tp") or ""):
                v["tp"] = _tp_sentence(x)
            rw[i] = v
    C.append_rw({k: v for k, v in rw.items() if k not in C.load_rw()})
    print(f"[import] 우리 말 정리 {len(rw)}건")
    if ai_dir:
        ai_dir = Path(ai_dir)
        (C.AI / "days").mkdir(parents=True, exist_ok=True)
        for p in sorted(ai_dir.glob("day_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            d["must"] = [dict(m, id=alias[int(m["id"])]) for m in d.get("must", []) if int(m["id"]) in alias]
            d["n_at"] = ctx["DAYS"].get(d["date"], {}).get("n", 0)
            C.jsave(C.AI / "days" / f"{d['date']}.json", d)
        sto = {}
        for f in ("stocks_a.json", "stocks_b.json"):
            if (ai_dir / f).exists():
                for n, v in json.loads((ai_dir / f).read_text(encoding="utf-8")).items():
                    sto[n] = dict(v, date="2026-11-01", n_at=None, at="2026-11-01T20:00:00")
        C.jsave(C.AI / "stocks.json", sto)
        if (ai_dir / "industry.json").exists():
            C.jsave(C.AI / "industry.json", dict(items=json.loads((ai_dir / "industry.json").read_text(encoding="utf-8")), at="2026-11-01T20:00:00"))
        if (ai_dir / "macro.json").exists():
            C.jsave(C.AI / "macro.json", dict(json.loads((ai_dir / "macro.json").read_text(encoding="utf-8")), at="2026-11-01T20:00:00"))
        print(f"[import] 해석: 날짜 {len(list((C.AI / 'days').glob('*.json')))}개 · 종목 {len(sto)}개 · 산업 · 매크로")


def _tp_sentence(x):
    if not x["tp"]:
        return ""
    s = f"목표가 {x['tp']:,.0f}{x['tpu'] or '원'}"
    if x["op"]:
        s += f", 투자의견 {x['op']}"
    if x["ch"] in ("상향", "하향") and x["pct"] is not None:
        s += f" — 직전 {x['prev']:,.0f}원에서 {abs(x['pct']):.1f}% {'올림' if x['ch'] == '상향' else '내림'}"
    elif x["ch"] == "유지":
        s += " — 직전과 같음"
    return s + "."


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    {"update": lambda: cmd_update("--no-push" not in a), "prepare": cmd_prepare, "finalize": cmd_finalize,
     "build": lambda: cmd_update(False) if "--fetch" in a else (lambda d: __import__("build").write_public(*d))(_build()),
     "status": cmd_status, "bootstrap": lambda: cmd_bootstrap(a[1]), "import": lambda: cmd_import(a[1], a[2] if len(a) > 2 else None)}[a[0]]()
