"""텔레그램 실시간 수신 (선택) — 구독 중인 채널의 새 글을 받아 종목 언급을 보드에 붙임 (읽기 전용)

  radar.bat setup-telegram   api_id/api_hash 입력 → 전화번호·인증코드(·2단계 비밀번호) 로그인 → 받을 채널 고르기
보관 위치 (OneDrive·저장소 밖)
  세션 파일   %LOCALAPPDATA%\\krsc-radar\\telegram.session   ← 계정 열쇠와 같음. 절대 공유·커밋 금지
  api_hash    Windows 자격 증명 관리자 'krsc-radar-telegram'
  채널 목록   radar-out/telegram_channels.json · 받은 글 radar-out/telegram/날짜.jsonl (로컬 전용)
보내기 기능은 없음 (메시지 읽기만).
"""
import asyncio
import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "krsc-radar"
SESSION = LOCAL / "telegram"                                     # Telethon 이 .session 을 붙임
KR_SVC = "krsc-radar-telegram"
_STATE = {"running": False, "err": None, "n": 0}


def creds():
    try:
        import keyring
        a, h = keyring.get_password(KR_SVC, "api_id"), keyring.get_password(KR_SVC, "api_hash")
        return (int(a), h) if a and h else None
    except Exception:  # noqa: BLE001
        return None


def configured(out):
    return creds() is not None and (Path(str(SESSION) + ".session")).exists() and (out / "telegram_channels.json").exists()


def setup(out):
    """사용자가 직접 실행하는 대화형 설정 — 입력값은 이 PC에만 저장"""
    import getpass
    import keyring
    try:
        from telethon.sync import TelegramClient
    except ImportError:                                           # 선택 기능이라 기본 설치에 넣지 않음 → 처음 설정할 때 설치
        import subprocess
        import sys
        print("텔레그램 라이브러리(telethon)를 설치합니다...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-warn-script-location", "telethon==1.45.0"])
        if r.returncode != 0:
            print("설치 실패 — 명령창에서 다시 시도하거나 알려주세요."); return
        from telethon.sync import TelegramClient
    print("my.telegram.org → API development tools 에서 만든 api_id / api_hash 를 넣어주세요 (api_hash 는 화면에 안 보임).")
    a = input("api_id (숫자): ").strip()
    h = getpass.getpass("api_hash: ").strip()
    if not a.isdigit() or not h:
        print("취소했습니다."); return
    keyring.set_password(KR_SVC, "api_id", a)
    keyring.set_password(KR_SVC, "api_hash", h)
    LOCAL.mkdir(parents=True, exist_ok=True)
    print("이제 텔레그램 로그인: 전화번호(+82...) → 텔레그램 앱으로 온 코드 → (설정했다면) 2단계 비밀번호")
    with TelegramClient(str(SESSION), int(a), h) as cl:
        chans = [d for d in cl.iter_dialogs() if d.is_channel]
        for n, d in enumerate(chans, 1):
            print(f"  {n:3d}. {d.name}")
        pick = input("받을 채널 번호 (쉼표로 여러 개, 예: 1,4,7): ").strip()
        sel = []
        for x in pick.split(","):
            x = x.strip()
            if x.isdigit() and 1 <= int(x) <= len(chans):
                d = chans[int(x) - 1]
                sel.append({"id": d.id, "title": d.name})
    out.mkdir(parents=True, exist_ok=True)
    (out / "telegram_channels.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장했습니다: 채널 {len(sel)}개 — " + ", ".join(s["title"] for s in sel))
    print("세션 파일은 계정 열쇠와 같습니다. %LOCALAPPDATA%\\krsc-radar 폴더를 공유하거나 옮기지 마세요.")


def _store(out, rec):
    d = out / "telegram"
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{rec['dt'][:10].replace('-', '')}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _kst(d):
    return (d.astimezone(dt.timezone.utc) + dt.timedelta(hours=9)).replace(tzinfo=None)


def start(out, log):
    """보드 서버 안에서 백그라운드로 새 글 수신 (설정이 없으면 아무것도 안 함)"""
    if _STATE["running"] or not configured(out):
        return False
    chans = json.loads((out / "telegram_channels.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in chans]
    titles = {c["id"]: c["title"] for c in chans}
    a, h = creds()

    def run():
        from telethon import TelegramClient, events
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cl = TelegramClient(str(SESSION), a, h, loop=loop)

        async def main():
            await cl.connect()
            if not await cl.is_user_authorized():
                _STATE["err"] = "텔레그램 로그인이 풀렸습니다 — radar.bat setup-telegram 다시 실행"; log(_STATE["err"]); return
            seen = set()
            kst_now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
            today = dt.datetime(kst_now.year, kst_now.month, kst_now.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=9)   # 한국 0시 (UTC 기준)
            for cid in ids:                                      # 오늘 이미 올라온 글 채우기 (서버를 늦게 켰을 때)
                try:
                    async for m in cl.iter_messages(cid, limit=300):
                        if m.date < today:
                            break
                        if m.message and (cid, m.id) not in seen:
                            seen.add((cid, m.id))
                            _store(out, {"dt": f"{_kst(m.date):%Y-%m-%d %H:%M:%S}", "chat": titles.get(cid, str(cid)), "id": m.id, "text": m.message})
                except Exception as e:  # noqa: BLE001
                    log(f"텔레그램 채우기 실패 {titles.get(cid)}: {e!r}"[:160])
            _dedupe(out)

            @cl.on(events.NewMessage(chats=ids))
            async def handler(ev):
                m = ev.message
                if m.message:
                    _store(out, {"dt": f"{_kst(m.date):%Y-%m-%d %H:%M:%S}", "chat": titles.get(ev.chat_id, str(ev.chat_id)), "id": m.id, "text": m.message})
                    _STATE["n"] += 1
            log(f"텔레그램 수신 시작: {', '.join(titles.values())}")
            await cl.run_until_disconnected()

        try:
            loop.run_until_complete(main())
        except Exception as e:  # noqa: BLE001
            _STATE["err"] = f"텔레그램 수신 중단: {e!r}"[:200]; log(_STATE["err"])
        finally:
            _STATE["running"] = False

    _STATE["running"] = True
    threading.Thread(target=run, daemon=True).start()
    return True


def _dedupe(out):
    f = out / "telegram" / f"{dt.date.today():%Y%m%d}.jsonl"
    if not f.exists():
        return
    seen, keep = set(), []
    for ln in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        k = (r.get("chat"), r.get("id"))
        if k not in seen:
            seen.add(k); keep.append(ln)
    f.write_text("\n".join(keep) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------- 종목 언급 찾기
_PAT = {"key": None, "re": None, "map": None}
JOSA = set("은는이가을를의도와과로에만")
URL = re.compile(r"https?://\S+|www\.\S+")


def _matcher(base):
    key = base.get("asof")
    if _PAT["key"] != key:
        S = base["stocks"]
        mp = {}
        for c, n in zip(S["c"], S["n"]):
            if n and len(n) >= 2:
                mp.setdefault(n, c)
        _PAT.update(key=key, map=mp, re=re.compile("|".join(re.escape(n) for n in sorted(mp, key=len, reverse=True))))
    return _PAT["re"], _PAT["map"]


def mentions(out, base, since, until=None):
    """since 이후 받은 글에서 종목코드 → [{t, chat, text}]"""
    pat, mp = _matcher(base)
    res = {}
    days = {since.date(), (until or since).date(), dt.date.today()}
    for d in sorted(days):
        f = out / "telegram" / f"{d:%Y%m%d}.jsonl"
        if not f.exists():
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                t = dt.datetime.strptime(r["dt"], "%Y-%m-%d %H:%M:%S")
            except Exception:  # noqa: BLE001
                continue
            if t < since or (until and t > until):
                continue
            text = URL.sub(" ", r.get("text", ""))
            found = []
            for m in pat.finditer(text):
                nm, a, b = m.group(0), m.start(), m.end()
                if a > 0 and re.match(r"[가-힣A-Za-z0-9]", text[a - 1]):
                    continue
                if len(nm) <= 2 and b < len(text) and re.match(r"[가-힣]", text[b]) and text[b] not in JOSA:
                    continue
                if re.match(r"[A-Za-z0-9]", nm[-1]) and b < len(text) and re.match(r"[A-Za-z0-9]", text[b]):
                    continue
                found.append(mp[nm])
            for c in dict.fromkeys(found):
                res.setdefault(c, []).append({"t": r["dt"][5:16], "chat": r.get("chat", ""), "text": r.get("text", "")[:160]})
    return res


def status():
    return dict(_STATE)
