"""리포트 채널의 새 글만 받아 msgs.jsonl 에 붙인다 (읽기 전용).

- 로그인 정보: 레이더 세션 파일을 '읽기 전용'으로 열어 메모리 세션으로 접속 → 세션 파일에 쓰지 않으므로
  레이더가 켜져 있어도 부딪히지 않고, 세션은 이 PC 밖으로 나가지 않는다.
- api_id/api_hash: Windows 자격 증명 관리자 'krsc-radar-telegram' (레이더 설정 때 넣은 값)
- 채널 번호: %LOCALAPPDATA%\\krsc-reports\\config.json 의 channel_id (저장소에 넣지 않음)
사용: python fetch.py            → 새 글 받기 (마지막 글 번호 다음부터)
"""
import asyncio
import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402

SESSION = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "krsc-radar" / "telegram.session"
KST = dt.timezone(dt.timedelta(hours=9))


def _creds():
    import keyring
    a, h = keyring.get_password("krsc-radar-telegram", "api_id"), keyring.get_password("krsc-radar-telegram", "api_hash")
    if not (a and h):
        raise SystemExit("텔레그램 api_id/api_hash 가 없습니다 — tools/radar/radar.bat setup-telegram 을 먼저 실행하세요")
    return int(a), h


def _session(cid):
    """세션 파일에서 접속 정보·채널 해시만 읽기 전용으로 꺼내 메모리 세션을 만든다"""
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession
    if not SESSION.exists():
        raise SystemExit("텔레그램 세션 파일이 없습니다 — tools/radar/radar.bat setup-telegram 으로 로그인하세요")
    con = sqlite3.connect(f"file:{SESSION.as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        dc, addr, port, key = con.execute("select dc_id, server_address, port, auth_key from sessions").fetchone()
        row = con.execute("select hash from entities where id in (?, ?)", (-1000000000000 - cid, cid)).fetchone()
    finally:
        con.close()
    s = StringSession()
    s.set_dc(dc, addr, port)
    s.auth_key = AuthKey(data=key)
    return s, (row[0] if row else None)


def _compact(m):
    f = m.file
    name = getattr(f, "name", None) if f else None
    date = m.date.astimezone(KST).replace(tzinfo=None).isoformat(timespec="seconds")
    return dict(id=m.id, date=date, text=m.message or "", file=name if name else ("F" if m.document else None),
                photo=bool(m.photo), mime=getattr(f, "mime_type", None) if f else None,
                fwd=bool(m.fwd_from), reply=m.reply_to_msg_id if m.reply_to else None, size=getattr(f, "size", None) if f else None)


async def _fetch(cid, after, limit):
    from telethon import TelegramClient
    from telethon.tl.types import InputPeerChannel
    a, h = _creds()
    sess, ahash = _session(cid)
    cl = TelegramClient(sess, a, h, receive_updates=False)
    await cl.connect()
    try:
        if not await cl.is_user_authorized():
            raise SystemExit("텔레그램 로그인이 풀렸습니다 — tools/radar/radar.bat setup-telegram 다시 실행")
        if ahash is not None:
            peer = InputPeerChannel(cid, ahash)
        else:                                               # 세션에 채널 정보가 없으면 대화 목록에서 찾음
            peer = None
            async for d in cl.iter_dialogs():
                if d.is_channel and d.entity.id == cid:
                    peer = d.input_entity
                    break
            if peer is None:
                raise SystemExit("구독 목록에서 리포트 채널을 찾지 못했습니다")
        got = []
        async for m in cl.iter_messages(peer, min_id=after, reverse=True, limit=limit):
            got.append(_compact(m))
        return got
    finally:
        await cl.disconnect()


def fetch(limit=5000):
    cfg = C.config()
    cid = cfg.get("channel_id")
    if not cid:
        raise SystemExit("config.json 에 channel_id 가 없습니다 (run.py bootstrap 먼저)")
    have = C.load_msgs()
    after = max((m["id"] for m in have), default=0)
    got = asyncio.run(_fetch(int(cid), after, limit))
    got = [m for m in got if m["id"] > after]
    if got:
        C.append_msgs(got)
    C.save_state(fetched_at=C.kst_now().isoformat(timespec="seconds"), last_id=max([after] + [m["id"] for m in got]))
    n_rep = sum(1 for m in got if "제목:" in m["text"])
    print(f"[fetch] 새 글 {len(got)}개 (리포트 요약 {n_rep}개) · 마지막 글 {max([after] + [m['id'] for m in got])}")
    return got


if __name__ == "__main__":
    fetch()
