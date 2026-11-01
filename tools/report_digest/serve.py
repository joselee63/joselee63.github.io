"""리포트 요약 — 이 PC 도우미 (http://127.0.0.1:8792)

- 페이지의 '지금 업데이트' 버튼이 여기로 요청 → 새 글 받기 · 숫자 정리 · 사이트에 올리기 (run.py update). 해석은 다음 예약 때 붙음.
- http://127.0.0.1:8792/ 에서 같은 페이지를 이 PC의 최신 데이터로 볼 수 있음.
- 이 PC 안에서만 열림(127.0.0.1). 사이트(joselee63.github.io)에서 누른 버튼도 받을 수 있게 CORS 허용.
실행: tools\\report_digest\\reports.bat
"""
import io
import json
import subprocess
import sys
import threading
import time
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402

PORT = 8792
ALLOW = {C.SITE, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
JOB = {"running": False, "log": [], "started": None, "ended": None, "ok": None}


def _job():
    JOB.update(running=True, log=[], started=time.time(), ended=None, ok=None)
    try:
        p = subprocess.Popen([sys.executable, "-u", str(Path(__file__).parent / "run.py"), "update"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        for ln in p.stdout:
            JOB["log"].append(ln.rstrip()[:300])
        JOB["ok"] = p.wait() == 0
    except Exception as e:  # noqa: BLE001
        JOB["log"].append(f"오류: {e!r}"[:300]); JOB["ok"] = False
    JOB.update(running=False, ended=time.time())


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        o = self.headers.get("Origin")
        if o in ALLOW:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/reports.html"):
            h = (C.REPO / "web" / "reports.html").read_text(encoding="utf-8")
            h = h.replace("<head>", '<head>\n<script>window.REPORTS_BASE="/";window.REPORTS_LOCAL=true;</script>', 1)
            return self._send(200, h, "text/html; charset=utf-8")
        if path in ("/data.json", "/ai.json"):
            f = C.OUT / path[1:]
            return self._send(200, f.read_bytes()) if f.exists() else self._send(404, "{}")
        if path == "/status":
            s = C.state()
            return self._send(200, json.dumps(dict(JOB, helper=True, fetched_at=s.get("fetched_at"), published_at=s.get("published_at")), ensure_ascii=False))
        self._send(404, "{}")

    def do_POST(self):
        if self.path.split("?")[0] != "/update":
            return self._send(404, "{}")
        o = self.headers.get("Origin")
        if o and o not in ALLOW:
            return self._send(403, '{"error":"origin"}')
        if JOB["running"]:
            return self._send(200, json.dumps({"ok": True, "already": True}))
        threading.Thread(target=_job, daemon=True).start()
        self._send(200, json.dumps({"ok": True}))


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"리포트 도우미: http://127.0.0.1:{PORT}  (이 창을 닫으면 멈춤)")
    if "--open" in sys.argv:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    srv.serve_forever()
