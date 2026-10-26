"""키움 REST API — 종베 레이더가 쓰는 조회 API만 (주문 기능 없음)
규격: github.com/Kiwoom-Securities/Kiwoom-REST-API (kiwoom/_data/kiwoom_api_spec.json)

앱키·시크릿은 이 파일이나 저장소에 두지 않는다. 찾는 순서:
  1) 환경변수 APP_KEY / APP_SECRET (키움 공식 예제와 같은 이름)
  2) 키움 공식 CLI(kiwoomcli setup)의 현재 계좌 별칭 → Windows 자격 증명 관리자
  3) Windows 자격 증명 관리자 'kiwoom-real' (radar.bat setup-kiwoom 이 저장하는 곳 = kiwoomcli 기본 위치)
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import requests

BASE = "https://api.kiwoom.com"
MIN_GAP = 0.25                      # 요청 사이 최소 간격(초) — 유량 제한(1700) 회피
RATE_CODES = {1700, 1701, 1702}


class KiwoomError(Exception):
    pass


def _cli_profile_service():
    """kiwoomcli 의 현재 계좌 별칭이 있으면 그 자격 증명 저장소 이름"""
    try:
        from platformdirs import user_config_dir
        p = Path(user_config_dir("kiwoom")) / "settings.json"
        if not p.exists():
            return None
        cur = json.loads(p.read_text(encoding="utf-8")).get("current_profile")
        if not cur:
            return None
        return "kiwoom-profile-" + hashlib.sha256(cur.strip().encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def credentials():
    """(appkey, secretkey, 출처) 또는 None — 값 자체는 어디에도 출력하지 않음"""
    ak, sk = os.getenv("APP_KEY"), os.getenv("APP_SECRET")
    if ak and sk:
        return ak, sk, "환경변수"
    try:
        import keyring
    except ImportError:
        return None
    for svc, src in ((_cli_profile_service(), "kiwoomcli 계좌"), ("kiwoom-real", "자격 증명 관리자")):
        if not svc:
            continue
        try:
            ak, sk = keyring.get_password(svc, "appkey"), keyring.get_password(svc, "secretkey")
        except Exception:  # noqa: BLE001
            continue
        if ak and sk:
            return ak, sk, src
    return None


def save_credentials(appkey, secretkey):
    import keyring
    keyring.set_password("kiwoom-real", "appkey", appkey)
    keyring.set_password("kiwoom-real", "secretkey", secretkey)


def num(s, absval=False):
    """'+75,000' · '-1.25' · '' → float (부호 포함 숫자 문자열)"""
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-", "+"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return abs(v) if absval else v


class Kiwoom:
    def __init__(self):
        c = credentials()
        if not c:
            raise KiwoomError("키움 앱키가 없습니다 — radar.bat setup-kiwoom 으로 등록하세요")
        self._ak, self._sk, self.source = c
        self._token = None
        self._exp = 0.0
        self._last = 0.0
        self._lock = threading.Lock()
        self.s = requests.Session()

    # ------------------------------------------------------------------ 인증
    def _issue(self):
        r = self.s.post(BASE + "/oauth2/token", json={"grant_type": "client_credentials", "appkey": self._ak, "secretkey": self._sk},
                        headers={"Content-Type": "application/json;charset=UTF-8"}, timeout=20)
        d = r.json()
        if not d.get("token"):
            raise KiwoomError(f"토큰 발급 실패: {d.get('return_msg') or r.status_code}")
        self._token = d["token"]
        exp = d.get("expires_dt")                                 # 'YYYYMMDDhhmmss'
        try:
            self._exp = time.mktime(time.strptime(exp, "%Y%m%d%H%M%S")) - 600
        except Exception:  # noqa: BLE001
            self._exp = time.time() + 6 * 3600

    def _auth(self):
        if not self._token or time.time() > self._exp:
            self._issue()
        return "Bearer " + self._token

    # ------------------------------------------------------------------ 요청
    def call(self, api_id, path, body, cont=None):
        """한 번 요청 → (본문 dict, 다음 페이지 키 또는 None)"""
        for attempt in range(4):
            with self._lock:
                wait = MIN_GAP - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                h = {"Content-Type": "application/json;charset=UTF-8", "api-id": api_id, "authorization": self._auth()}
                if cont:
                    h["cont-yn"] = "Y"; h["next-key"] = cont
                r = self.s.post(BASE + path, json=body, headers=h, timeout=20)
                self._last = time.time()
            try:
                d = r.json()
            except ValueError:
                raise KiwoomError(f"{api_id}: JSON 아님 (HTTP {r.status_code})")
            rc = d.get("return_code")
            try:
                rc = int(rc) if rc is not None else 0
            except (TypeError, ValueError):
                rc = -1
            msg = str(d.get("return_msg") or "")
            if r.status_code == 401 or rc == 8005 or "8005" in msg:
                self._token = None; continue                      # 토큰 무효 → 한 번 재발급
            if rc in RATE_CODES or any(str(c) in msg for c in RATE_CODES):
                time.sleep(1.0 + attempt); continue
            if rc not in (0, None):
                raise KiwoomError(f"{api_id}: {msg} (code {rc})")
            nxt = r.headers.get("next-key") if (r.headers.get("cont-yn") or "").upper() == "Y" else None
            return d, nxt
        raise KiwoomError(f"{api_id}: 재시도 초과")

    # ------------------------------------------------------------------ 조회 API
    def rank_up(self, stex="1", min_rt=3.0, max_pages=15):
        """전일대비등락률상위(ka10027) — 상승률 순으로 min_rt% 이상 전부 (stex 1:KRX 2:NXT 3:통합)"""
        body = {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0000", "stk_cnd": "16", "crd_cnd": "0",
                "updown_incls": "1", "pric_cnd": "0", "trde_prica_cnd": "0", "stex_tp": stex}
        out, cont = [], None
        for _ in range(max_pages):
            d, cont = self.call("ka10027", "/api/dostk/rkinfo", body, cont)
            rows = d.get("pred_pre_flu_rt_upper") or []
            for x in rows:
                code = str(x.get("stk_cd", "")).split("_")[0].strip()
                rt = num(x.get("flu_rt"))
                if not code or rt is None:
                    continue
                out.append({"code": code, "name": (x.get("stk_nm") or "").strip(), "px": num(x.get("cur_prc"), True),
                            "rt": rt, "vol": num(x.get("now_trde_qty"), True), "sig": str(x.get("pred_pre_sig", "")),
                            "str": num(x.get("cntr_str"))})
            if not rows or not cont or (num(rows[-1].get("flu_rt")) or 0) < min_rt:
                break
        return [r for r in out if r["rt"] >= min_rt]

    def stock(self, code):
        """주식기본정보(ka10001) — 고가·저가·상한가·예상체결가·시총 등"""
        d, _ = self.call("ka10001", "/api/dostk/stkinfo", {"stk_cd": code})
        g = lambda k, a=True: num(d.get(k), a)
        return {"code": code, "name": (d.get("stk_nm") or "").strip(), "px": g("cur_prc"), "rt": g("flu_rt", False),
                "open": g("open_pric"), "high": g("high_pric"), "low": g("low_pric"), "upl": g("upl_pric"),
                "base": g("base_pric"), "exp": g("exp_cntr_pric"), "vol": g("trde_qty"), "mcap": g("mac"),
                "hi250": g("250hgst")}

    def index(self, mrkt_tp, inds_cd):
        """업종현재가(ka20001) — mrkt_tp 0:코스피 1:코스닥, inds_cd 001:코스피 종합 101:코스닥 종합"""
        d, _ = self.call("ka20001", "/api/dostk/sect", {"mrkt_tp": mrkt_tp, "inds_cd": inds_cd})
        return {"px": num(d.get("cur_prc"), True), "rt": num(d.get("flu_rt")), "open": num(d.get("open_pric"), True),
                "high": num(d.get("high_pric"), True), "low": num(d.get("low_pric"), True),
                "up": num(d.get("rising"), True), "down": num(d.get("fall"), True)}
