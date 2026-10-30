"""시가총액 1조 이상 종목의 15분봉 받기 — '파동 눌림 타점' HTML 용 (내 PC 전용, 사이트에 안 올림)

키움 REST 주식분봉차트(ka10080, 15분, 수정주가)로 정규장(09:00~15:30) 봉만 모아
OUT/{종목코드}.js 와 OUT/index.js 로 저장한다. HTML 이 <script> 로 읽으므로 파일을 직접 열어도 된다.

- 키움은 15분봉을 약 13개월치만 준다 → 처음엔 전부, 다음부턴 새 봉만 덧붙여 기록이 계속 길어진다.
- 수정주가가 바뀌면(분할·증자 등) 겹치는 봉의 비율로 예전 봉까지 맞춘다.
- 가격은 통합(KRX+NXT, 코드 뒤 _AL) — HTS 기본 차트(통합)에서 엑셀로 내보낸 값과 같다(SK하이닉스 6,441봉 중 6,440봉 일치).
  NXT 미거래 종목은 KRX 값이 그대로 나온다.
- 봉 시각은 시작 시각 기준: 09:00봉 = 09:00~09:15(시가 단일가 포함), 15:30봉 = 종가 단일가(+NXT 15:30~15:45) → 하루 27개.

python min15.py OUT                 # 시총 1조 이상 전체 (새 종목은 전부, 기존 종목은 새 봉만)
python min15.py OUT --codes 005930  # 특정 종목만
python min15.py OUT --full          # 처음부터 다시
python min15.py OUT --min-cap 5000  # 기준 바꾸기 (억 원)
python min15.py OUT --serve 8792 --page "JH존_파동 눌림 타점_v2.html"   # 화면의 '갱신' 버튼용 로컬 서버
"""
import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kiwoom import Kiwoom, KiwoomError, num  # noqa: E402

SLOTS = [f"{9 + m // 60:02d}{m % 60:02d}" for m in range(0, 391, 15)]   # 0900 … 1530 (27개)
SLOT = {s: i for i, s in enumerate(SLOTS)}
MK = {"0": "KOSPI", "10": "KOSDAQ"}


def universe(k, min_cap):
    """종목정보 리스트(ka10099) → 시총(상장주식수×현재가) ≥ min_cap 억 인 주식 (ETF·ETN·리츠 제외)"""
    out = []
    for mk in ("0", "10"):
        cont = None
        while True:
            d, cont = k.call("ka10099", "/api/dostk/stkinfo", {"mrkt_tp": mk}, cont)
            for r in d.get("list") or []:
                if r.get("marketName") not in ("거래소", "코스닥"):
                    continue
                cap = int(r["listCount"] or 0) * int(r["lastPrice"] or 0) / 1e8
                if cap >= min_cap:
                    out.append({"c": r["code"], "n": r["name"].strip(), "m": MK[mk], "cap": round(cap),
                                "s": r.get("upName") or ""})
            if not cont:
                break
    return out


def read_js(f):
    if not f.exists():
        return None
    t = f.read_text(encoding="utf-8")
    try:
        return json.loads(t[t.index("(") + 1:t.rindex(")")])
    except ValueError:
        return None


def write_js(f, fn, obj):
    tmp = f.with_suffix(".tmp")
    tmp.write_text(f"{fn}({json.dumps(obj, ensure_ascii=False, separators=(',', ':'))});\n", encoding="utf-8")
    tmp.replace(f)


def fetch(k, code, stop_before=None):
    """15분봉을 최신부터 거꾸로. stop_before('YYYYMMDDhhmm') 보다 오래된 쪽이 나오면 멈춤.
    → {'YYYYMMDDhhmm': [o,h,l,c,v]} (정규장만)"""
    bars, cont, pages = {}, None, 0
    while True:
        d, cont = k.call("ka10080", "/api/dostk/chart", {"stk_cd": code + "_AL", "tic_scope": "15", "upd_stkpc_tp": "1"}, cont)
        rows = d.get("stk_min_pole_chart_qry") or []
        pages += 1
        for r in rows:
            t = str(r.get("cntr_tm") or "")[:12]
            if len(t) < 12 or t[8:] not in SLOT:
                continue
            o, h, l, c = (num(r.get(x), True) for x in ("open_pric", "high_pric", "low_pric", "cur_prc"))
            if not (o and h and l and c):
                continue
            bars[t] = [o, h, l, c, int(num(r.get("trde_qty"), True) or 0)]
        oldest = min((str(r.get("cntr_tm"))[:12] for r in rows), default=None)
        if not cont or not rows or (stop_before and oldest and oldest < stop_before) or pages > 60:
            return bars


def pack(bars):
    """{'YYYYMMDDhhmm': [o,h,l,c,v]} → {'d': [날짜…], 'b': [[날짜번호, 칸, o,h,l,c,v], …]}"""
    days, b = [], []
    for t in sorted(bars):
        d = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        if not days or days[-1] != d:
            days.append(d)
        b.append([len(days) - 1, SLOT[t[8:]]] + [round(x) if isinstance(x, float) and x == int(x) else x for x in bars[t]])
    return {"d": days, "b": b}


def unpack(obj):
    out = {}
    for di, si, *v in obj.get("b", []):
        out[obj["d"][di].replace("-", "") + SLOTS[si]] = v
    return out


def update(k, code, out, full=False):
    """한 종목 받기/덧붙이기 → (저장한 봉 수, 새 봉 수, 메모)"""
    f = out / f"{code}.js"
    old = None if full else read_js(f)
    oldb = unpack(old) if old else {}
    if not oldb:
        new = fetch(k, code)
        merged, note = new, "처음"
    else:
        last = max(oldb)
        stop = (datetime.strptime(last[:8], "%Y%m%d").toordinal() - 3)          # 마지막 날 3일 전까지 겹치게
        stop = datetime.fromordinal(stop).strftime("%Y%m%d") + "0900"
        new = fetch(k, code, stop_before=stop)
        # 겹치는 봉 비교 (마지막 날은 장중 미완성 봉이 있을 수 있어 뺌)
        lastday = last[:8]
        ov = [t for t in new if t in oldb and t[:8] < lastday]
        ratio = None
        if ov:
            rs = sorted(new[t][3] / oldb[t][3] for t in ov if oldb[t][3])
            ratio = rs[len(rs) // 2] if rs else None
        if ratio is not None and abs(ratio - 1) > 0.002:
            # 수정주가가 바뀜 → 전부 다시 받고, 키움이 더는 안 주는 예전 봉은 비율로 맞춤
            new = fetch(k, code)
            first = min(new)
            ov2 = sorted(t for t in new if t in oldb)[:27]
            rs = sorted(new[t][3] / oldb[t][3] for t in ov2 if oldb[t][3])
            r2 = rs[len(rs) // 2] if rs else ratio
            merged = {t: [round(x * r2) for x in v[:4]] + [round(v[4] / r2)] for t, v in oldb.items() if t < first}
            merged.update(new)
            note = f"수정주가 조정 ×{r2:.4f}"
        else:
            merged = dict(oldb)
            merged.update(new)
            note = ""
    if not merged:
        return 0, 0, "봉 없음"
    nnew = len(set(merged) - set(oldb))
    obj = {"code": code, **pack(merged)}
    # 국면(일봉 20·60일선)을 15분봉 첫날부터 판정하려고, 그 앞 일봉 종가를 같이 둠 — 한 번 받으면 재사용
    keep = old and old.get("pre") and not note.startswith("수정주가") and old.get("d", [None])[0] == obj["d"][0]
    obj["pre"] = old["pre"] if keep else daily_pre(k, code, obj["d"][0])
    return obj, nnew, note


def daily_pre(k, code, first, n=90):
    """first(YYYY-MM-DD) 이전 n거래일 일봉 종가(수정주가) → [[날짜, 종가], …]. 실패하면 [] (다음 갱신 때 다시)"""
    try:
        d, _ = k.call("ka10081", "/api/dostk/chart", {"stk_cd": code, "base_dt": first.replace("-", ""), "upd_stkpc_tp": "1"})
    except KiwoomError:
        return []
    out = []
    for r in d.get("stk_dt_pole_chart_qry") or []:
        dt, c = str(r.get("dt") or ""), num(r.get("cur_prc"), True)
        if len(dt) == 8 and c and f"{dt[:4]}-{dt[4:6]}-{dt[6:]}" < first:
            out.append([f"{dt[:4]}-{dt[4:6]}-{dt[6:]}", round(c)])
    return sorted(out)[-n:]


class Store:
    """data15 폴더 + index.js 목록 — 명령줄 갱신과 화면 갱신 서버가 같이 씀"""

    def __init__(self, out, min_cap=10000):
        self.out, self.min_cap = Path(out), min_cap
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()                         # 파일 쓰기는 한 번에 하나
        self._k = None
        idx = read_js(self.out / "index.js") or {}
        self.upd = idx.get("upd")
        self.info = {u["c"]: u for u in idx.get("list", [])}

    @property
    def k(self):
        if self._k is None:
            self._k = Kiwoom()
        return self._k

    def refresh_universe(self):
        """시총 기준 종목 다시 확인 → 받을 코드 목록. 기준 아래로 내려간 종목도 목록엔 남김"""
        uni = universe(self.k, self.min_cap)
        new = {u["c"]: u for u in uni}
        for c, u in self.info.items():
            if c in new:
                new[c].update({x: u[x] for x in ("f", "t", "last", "nb", "u") if x in u})
            else:
                new[c] = dict(u, below=True)
        self.info = new
        return [u["c"] for u in uni]

    def update_code(self, code, full=False):
        """한 종목 받기 → (새 봉 수, 메모, 목록 항목). 실패하면 KiwoomError"""
        with self.lock:                                      # 같은 종목을 화면·전체 갱신이 동시에 고쳐 쓰지 않게
            obj, nnew, note = update(self.k, code, self.out, full)
            if not obj:
                raise KiwoomError(f"{code} {note}")
            u = self.info.setdefault(code, {"c": code, "n": code, "m": "", "cap": None, "s": ""})
            obj.update(name=u["n"], mk=u["m"])
            write_js(self.out / f"{code}.js", "W15", obj)
            u.update(f=obj["d"][0], t=obj["d"][-1], last=SLOTS[obj["b"][-1][1]], nb=len(obj["b"]),
                     u=datetime.now().strftime("%Y-%m-%d %H:%M"))
        return nnew, note, u

    def save_index(self, full_run=False):
        with self.lock:
            if full_run or not self.upd:
                self.upd = datetime.now().strftime("%Y-%m-%d %H:%M")
            have = {p.stem for p in self.out.glob("*.js") if p.stem != "index"}
            lst = sorted((u for c, u in self.info.items() if c in have), key=lambda u: -(u.get("cap") or 0))
            write_js(self.out / "index.js", "W15_INDEX", {"upd": self.upd, "min_cap": self.min_cap, "list": lst})
            return len(lst)

    def run(self, codes, full=False, log=print, progress=None):
        """여러 종목 받기. 키움 일시 오류(1631 등)는 맨 끝에서 한 번 더 → 실패 코드 목록"""
        t0, fails, queue, retried = time.time(), [], list(codes), set()
        for n, code in enumerate(queue, 1):
            if progress:
                progress(min(n, len(codes)), len(codes), self.info.get(code, {}).get("n", code))
            try:
                nnew, note, u = self.update_code(code, full)
            except KiwoomError as e:
                if code not in retried:
                    retried.add(code); queue.append(code)
                    log(f"[{n}/{len(codes)}] {code} 일시 오류 — 나중에 다시: {e}")
                else:
                    fails.append(code)
                    log(f"[{n}/{len(codes)}] {code} 실패: {e}")
                continue
            if n % 20 == 0 or note or n == len(codes):
                log(f"[{n}/{len(codes)}] {code} {u['n']} {u['nb']}봉 (+{nnew}) {u['f']}~{u['t']} {note} · {time.time() - t0:.0f}초")
        return fails


# ====================================================================== 화면 갱신 서버
def serve(store, port, page):
    """이 폴더를 http://127.0.0.1:port 로 보여 주고, 화면의 '갱신' 버튼 요청을 받아 키움에서 새 봉을 받는다.
    키 값은 브라우저로 가지 않는다(서버가 자격 증명 관리자에서 읽어 키움에만 보냄)."""
    import re
    import webbrowser
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, quote, urlparse

    import requests
    url = f"http://127.0.0.1:{port}/" + quote(page)
    try:                                                     # 이미 켜져 있으면 브라우저만
        if requests.get(f"http://127.0.0.1:{port}/api/ping", timeout=2).ok:
            print(f"이미 실행 중입니다 → {url}")
            webbrowser.open(url)
            return
    except Exception:  # noqa: BLE001
        pass

    job = {"running": False, "done": 0, "total": 0, "cur": "", "fails": [], "started": None, "finished": None, "msg": ""}

    def log(s):
        print(time.strftime("%H:%M:%S"), s, flush=True)

    def run_all():
        job.update(done=0, total=0, cur="", fails=[], started=time.strftime("%H:%M:%S"), finished=None, msg="종목 목록 확인 중")
        try:
            codes = store.refresh_universe()
            job.update(total=len(codes), msg="")
            log(f"전체 갱신 시작 — {len(codes)}종목")

            def prog(n, total, name):
                job.update(done=n - 1, total=total, cur=name)
            fails = store.run(codes, log=log, progress=prog)
            job.update(done=len(codes), fails=fails)
            store.save_index(full_run=True)
            log(f"전체 갱신 끝 — 실패 {len(fails)}")
        except Exception as e:  # noqa: BLE001
            job["msg"] = f"오류: {e}"[:300]
            log(job["msg"])
        finally:
            job.update(running=False, finished=time.strftime("%Y-%m-%d %H:%M:%S"), cur="")

    root = str(store.out.parent)

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, fmt, *args):                   # 파일 요청은 조용히
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            p = urlparse(self.path).path
            if p == "/api/ping":
                return self._json(200, {"ok": True})
            if p == "/api/status":
                return self._json(200, job)
            return super().do_GET()

        def do_POST(self):
            if self.headers.get("X-Wave") != "1":            # 다른 사이트가 몰래 부르는 것 차단 (사용자 지정 헤더는 교차 출처에서 못 붙임)
                return self._json(403, {"error": "forbidden"})
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/update":
                code = (q.get("code") or [""])[0].upper()
                if not re.fullmatch(r"[0-9A-Z]{6}", code):
                    return self._json(400, {"error": "종목코드가 이상합니다"})
                try:
                    nnew, note, it = store.update_code(code)
                    store.save_index()
                except Exception as e:  # noqa: BLE001
                    log(f"{code} 갱신 실패: {e}")
                    return self._json(502, {"error": str(e)[:300]})
                log(f"{code} {it['n']} 갱신 — 새 봉 {nnew}개, 마지막 {it['t']} {it['last']}")
                return self._json(200, {"code": code, "nnew": nnew, "t": it["t"], "last": it["last"], "note": note})
            if u.path == "/api/update-all":
                if not job["running"]:
                    job["running"] = True
                    threading.Thread(target=run_all, daemon=True).start()
                return self._json(200, job)
            return self._json(404, {"error": "없는 주소"})

    ThreadingHTTPServer.allow_reuse_address = False           # Windows 는 기본값이면 같은 포트를 두 프로그램이 같이 열 수 있음
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    log(f"파동 눌림 타점 → {url}  (이 창을 닫으면 '갱신' 버튼이 멈춥니다)")
    if os.environ.get("WAVE_NO_BROWSER") != "1":
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--codes", default="")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--min-cap", type=float, default=10000, help="억 원 (기본 1조)")
    ap.add_argument("--serve", type=int, default=0, help="화면 갱신 서버 포트 (예: 8792)")
    ap.add_argument("--page", default="", help="--serve 때 열 HTML 파일 이름")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    store = Store(a.out, a.min_cap)
    if a.serve:
        return serve(store, a.serve, a.page)

    t0 = time.time()
    uni = store.refresh_universe()
    codes = [c.strip() for c in a.codes.split(",") if c.strip()] or uni
    print(f"시총 {a.min_cap / 1e4:g}조 이상 {len(uni)}종목 · 이번에 받을 {len(codes)}종목", flush=True)
    fails = store.run(codes, a.full, log=lambda s: print(s, flush=True))
    n = store.save_index(full_run=not a.codes)
    print(f"끝 — {n}종목 저장 · 실패 {len(fails)}{' ' + ','.join(fails) if fails else ''} · {time.time() - t0:.0f}초")
    if fails:
        print("실패한 종목은 다시 실행하면 이어서 받습니다.")


if __name__ == "__main__":
    main()
