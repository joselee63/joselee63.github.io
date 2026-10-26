"""종베 레이더 1단계 — 15:00~15:30 KRX 종가베팅 판단 보드 (내 PC 전용 · 사이트에 올리지 않음)

  radar.bat               보드 실행 → 브라우저 http://127.0.0.1:8790 (평일 정해진 시각에 자동 갱신)
  radar.bat run           지금 한 번 갱신하고 끝
  radar.bat setup-kiwoom  키움 앱키 등록 (입력값은 화면에 안 보이고 Windows 자격 증명 관리자에 저장)
  radar.bat setup-naver   네이버 검색 API 키 등록 (선택 — 없으면 뉴스는 '검색 링크'만)
  radar.bat check         연결 점검 (키 값은 출력하지 않음)

데이터
  기초(전날 밤): 릴리스 closebet-data/radar_base.json  ← closebet.yml 18:37 (tools/closebet/radar_base.py)
  실시간: 키움 REST (등락률 상위 ka10027 · 종목 기본정보 ka10001 · 업종 현재가 ka20001)
  공시: KIND 상세검색 (어제 15:30 이후) · 해외: 야후 · 뉴스: 네이버 검색 Open API(선택) · 체온계: 사이트 temp/index.json
규칙은 연구와 같음 (docs/closing-bet-research.md · reports/종베 레이더 제안.html)
기록: radar-out/snap/날짜/시각.json (매 갱신) · final.json (15:36 종가) · results.csv (다음날 09:06 시가) · picks.json (내 선택)
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path(os.environ.get("RADAR_DIR", ROOT / "radar-out"))
SNAP = OUT / "snap"
BASE_URL = "https://github.com/joselee63/joselee63.github.io/releases/download/closebet-data/radar_base.json"
TEMP_URL = "https://joselee63.github.io/temp/index.json"
PORT = int(os.environ.get("RADAR_PORT", "8790"))
COST = 0.25                                                      # 왕복 비용 %
sys.path.insert(0, str(HERE))
import kiwoom as KW  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}
# ※ numpy·pandas 같은 컴파일된 패키지를 쓰지 않음 — Windows 스마트 앱 컨트롤이 새 가상환경의 DLL을 막는 경우가 있어서

FOMC = {"2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
        "2027-10-27", "2027-12-08"}                              # 연준 공식 일정 (발표일 = 미국 날짜 = 한국 그날 밤)
CPI = {"2026-11-10", "2026-12-10", "2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13", "2027-05-12", "2027-06-10",
       "2027-07-14", "2027-08-11", "2027-09-14", "2027-10-14", "2027-11-10", "2027-12-10"}   # BLS 공식 일정
OVERSEAS = [("나스닥 선물", "NQ=F"), ("S&P 선물", "ES=F"), ("필라델피아 반도체", "^SOX"), ("SK하이닉스 ADR", "SKHY"),
            ("WTI 유가", "CL=F"), ("원/달러", "KRW=X"), ("VIX", "^VIX")]
SCHEDULE = {"base": ["08:40", "19:40"], "results": ["09:06"],
            "live": ["15:00", "15:06", "15:11", "15:15", "15:19", "15:23", "15:27"], "final": ["15:36"]}
LOG = []
STATE = {"running": False, "last": None, "next": None}
_lock = threading.Lock()


def log(msg):
    line = f"{now():%H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.append(line); del LOG[:-200]


def now():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).replace(tzinfo=None)   # 한국 시각 (서머타임 없음)


# ====================================================================== 거래일·이벤트
try:
    import holidays as _hol
    _KR = _hol.KR(years=range(2025, 2031))
except Exception:  # noqa: BLE001
    _KR = {}


def is_trading(d):
    return d.weekday() < 5 and d not in _KR and not (d.month == 12 and d.day == 31) and not (d.month == 5 and d.day == 1)


def next_trading(d):
    x = d + dt.timedelta(days=1)
    while not is_trading(x):
        x += dt.timedelta(days=1)
    return x


def prev_trading(d):
    x = d - dt.timedelta(days=1)
    while not is_trading(x):
        x -= dt.timedelta(days=1)
    return x


def option_expiry(d):
    """월 옵션 만기 = 둘째 목요일 (휴장이면 앞 거래일)"""
    x = dt.date(d.year, d.month, 1)
    th = [x + dt.timedelta(days=i) for i in range(31) if (x + dt.timedelta(days=i)).month == d.month and (x + dt.timedelta(days=i)).weekday() == 3]
    e = th[1]
    while not is_trading(e):
        e -= dt.timedelta(days=1)
    return e == d


def decision_day(t=None):
    t = t or now()
    d = t.date()
    if is_trading(d) and t.time() < dt.time(15, 40):
        return d
    return next_trading(d)


# ====================================================================== 기초 데이터
def load_base(force=False):
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "radar_base.json"
    want = prev_trading(now().date()) if now().time() < dt.time(19, 30) else (now().date() if is_trading(now().date()) else prev_trading(now().date()))
    b = None
    if f.exists():
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            b = None
    if force or b is None or b.get("asof", "") < str(want):
        try:
            r = requests.get(BASE_URL, timeout=60)
            r.raise_for_status()
            nb = r.json()
            f.write_text(r.text, encoding="utf-8")
            b = nb
            log(f"기초 데이터 받음 (기준일 {b['asof']})")
        except Exception as e:  # noqa: BLE001
            log(f"기초 데이터 받기 실패: {e!r}"[:200])
    if b is None:
        raise RuntimeError("기초 데이터(radar_base.json)가 없습니다 — 인터넷 연결을 확인하세요")
    S = b["stocks"]
    b["ix"] = {c: i for i, c in enumerate(S["c"])}
    return b


# ====================================================================== 공시 (KIND)
_KIND = {}                                                       # rcp → row


def disc_tag(title):
    t = title.replace(" ", "")
    if "자기주식취득" in t:
        return "자사주 취득", "up", "다음날 이어지는 편 (갭 +2.4%, 5일 +2.5%)"
    if "자기주식처분" in t:
        return "자사주 처분", "bad", "희석"
    if "단일판매" in t or "공급계약" in t:
        return "공급계약", "mid", "시가 반영 뒤 반납하는 편 — 매출 대비 %가 중요"
    if "무상증자" in t:
        return "무상증자", "mid", "갭 뒤 장중 반납 (−1.1%)"
    if "유상증자" in t:
        return "유상증자", "bad", "다음날 장중 약세 (−0.9%)"
    if "전환사채" in t or "신주인수권부사채" in t or "교환사채" in t:
        return "사채 발행", "bad", "희석 — 장중 약세"
    if "최대주주변경" in t:
        return "최대주주 변경", "bad", "장중 약세 (−1.1%)"
    if any(k in t for k in ("투자경고", "투자위험", "투자주의", "단기과열", "조회공시", "공매도과열", "매매거래정지")):
        return "과열·경보", "warn", "거래 제한·변동성 주의"
    if "영업(잠정)실적" in t or "매출액또는손익구조" in t or "실적" in t:
        return "실적", "info", ""
    return "기타", "info", ""


KIND_URL = "https://kind.krx.co.kr/disclosure/details.do"
KIND_H = dict(UA, **{"Referer": KIND_URL + "?method=searchDetailsMain", "X-Requested-With": "XMLHttpRequest"})
KIND_BASE = {f"disclosureType{k:02d}": "" for k in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 20)}
KIND_BASE.update(method="searchDetailsSub", currentPageSize="100", orderMode="1", orderStat="D", forward="details_sub",
                 pDisclosureType01="", marketType="", repIsuSrtCd="", kosdaqSegment="", searchCodeType="",
                 searchCorpName="", copyright="", bfrDsclsType="on", reportNm="")
_KS = requests.Session()
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def _kind_get(sd, ed, page):
    """KIND 상세검색 한 페이지 (로그인·키 불필요, 서버가 빠른 연속 요청을 싫어해 2.5초 간격)"""
    import html as _html  # noqa: F401
    for i in range(4):
        try:
            if page == 1 and i == 0:
                _KS.get(KIND_URL + "?method=searchDetailsMain", headers=KIND_H, timeout=20)
            t = _KS.post(KIND_URL, data=dict(KIND_BASE, fromDate=sd, toDate=ed, pageIndex=str(page)), headers=KIND_H, timeout=30).text
            time.sleep(2.5)
            if "잠시 후 다시" in t:
                time.sleep(10 * (i + 1)); continue
            return t
        except Exception:  # noqa: BLE001
            time.sleep(5 * (i + 1))
    return ""


def _kind_parse(t):
    import html as _html
    body = t[t.find("<tbody"):t.find("</tbody>")]
    out = []
    for r in _ROW.findall(body):
        tm = re.search(r'<td class="txc">(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td>', r)
        cd = re.search(r"companysummary_open\('(\w+)'\)", r)
        ti = re.search(r"openDisclsViewer\('(\d+)'[^>]*title='([^']*)'", r)
        if not (tm and cd and ti):
            continue
        nm = re.search(r"title='([^']*)'>\s*[^<]*</a>", r)
        out.append(dict(time=tm.group(1), kind_code=cd.group(1), name=_html.unescape(nm.group(1)) if nm else "",
                        title=_html.unescape(ti.group(2)), corr="[정정]" in r, rcp=ti.group(1)))
    return out


def kind_fetch(since):
    """since(datetime) 이후 공시 — 새 페이지만 받음 (요청 사이 2.5초)"""
    sd, ed = str(since.date()), str(now().date())
    got = 0
    for page in range(1, 16):
        t = _kind_get(sd, ed, page)
        rows = _kind_parse(t) if t else []
        if not rows:
            break
        new = 0
        for r in rows:
            if r["rcp"] not in _KIND:
                _KIND[r["rcp"]] = r; new += 1
        got += new
        oldest = min(dt.datetime.strptime(r["time"], "%Y-%m-%d %H:%M") for r in rows)
        if oldest < since or new == 0:
            break
    return got


def disc_for(code, since):
    k5 = code[:5]
    out = []
    for r in _KIND.values():
        if r["kind_code"].zfill(5) != k5:
            continue
        tm = dt.datetime.strptime(r["time"], "%Y-%m-%d %H:%M")
        if tm < since:
            continue
        tag, cls, note = disc_tag(r["title"])
        out.append({"t": r["time"][5:], "title": r["title"], "tag": tag, "cls": cls, "note": note, "corr": r.get("corr", False),
                    "url": f"https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={r['rcp']}"})
    out.sort(key=lambda x: x["t"], reverse=True)
    return out


# ====================================================================== 뉴스 (네이버 검색 Open API — 선택)
def naver_keys():
    a, b = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if a and b:
        return a, b
    try:
        import keyring
        a, b = keyring.get_password("krsc-radar-naver", "client_id"), keyring.get_password("krsc-radar-naver", "client_secret")
        return (a, b) if a and b else None
    except Exception:  # noqa: BLE001
        return None


NEWS_HUB = "https://naverapihub.apigw.ntruss.com/search/v1/news"      # 네이버 클라우드 NAVER API HUB (2026-07 이후 신규 발급 경로)
NEWS_OLD = "https://openapi.naver.com/v1/search/news.json"             # 옛 개발자센터 키 (2027-06-30까지 유예)


def news_for(name, since, keys):
    """네이버 뉴스 검색 — 화면에 '그대로 보여주기'용 (약관: 검색 결과의 AI 요약·학습 금지)"""
    if not keys:
        return None
    try:
        q = {"query": name, "display": 6, "sort": "date"}
        r = requests.get(NEWS_HUB, params=q, headers={"X-NCP-APIGW-API-KEY-ID": keys[0], "X-NCP-APIGW-API-KEY": keys[1]}, timeout=8)
        if r.status_code in (401, 403):
            r2 = requests.get(NEWS_OLD, params=q, headers={"X-Naver-Client-Id": keys[0], "X-Naver-Client-Secret": keys[1]}, timeout=8)
            if r2.status_code == 200:
                r = r2
        if r.status_code != 200:
            msg = {401: "인증 실패 — 키 확인", 403: "허용 안 됨 — Application에 '뉴스 검색' 포함 여부 확인", 429: "하루 허용량 초과"}.get(r.status_code, "")
            return [{"t": "", "title": f"(뉴스 API 오류 {r.status_code} {msg})", "url": "", "fresh": False}]
        out = []
        for it in r.json().get("items", []):
            try:
                pt = dt.datetime.strptime(it["pubDate"][:25], "%a, %d %b %Y %H:%M:%S")
            except Exception:  # noqa: BLE001
                pt = None
            title = re.sub(r"<[^>]+>", "", it.get("title", "")).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            out.append({"t": pt.strftime("%m-%d %H:%M") if pt else "", "title": title, "url": it.get("originallink") or it.get("link"),
                        "fresh": bool(pt and pt >= since)})
        return out
    except Exception as e:  # noqa: BLE001
        return [{"t": "", "title": f"(뉴스 받기 실패 {type(e).__name__})", "url": "", "fresh": False}]


# ====================================================================== 해외·체온계
def overseas():
    """야후 차트 API 직접 (yfinance 없이) — 현재가와 직전 종가"""
    out = []
    for nm, sym in OVERSEAS:
        try:
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + requests.utils.quote(sym, safe=""),
                             params={"range": "1d", "interval": "5m"}, headers=UA, timeout=10)
            m = r.json()["chart"]["result"][0]["meta"]
            last, prev = float(m["regularMarketPrice"]), float(m.get("chartPreviousClose") or m.get("previousClose"))
            out.append({"n": nm, "s": sym, "px": last, "chg": (last / prev - 1) * 100 if prev else None})
        except Exception:  # noqa: BLE001
            out.append({"n": nm, "s": sym, "px": None, "chg": None})
    return out


def temp_info():
    try:
        d = requests.get(TEMP_URL, timeout=15).json()
        sig = d.get("sig", {})
        nowr = d.get("now", [])
        fx = nowr[-1]["fx"] if nowr else None
        return {"panic": bool(sig.get("panic", {}).get("on")), "bottom": bool(sig.get("bottom", {}).get("on")),
                "top": bool(sig.get("top", {}).get("on")), "fx": fx, "asof": d.get("last")}
    except Exception:  # noqa: BLE001
        return None


# ====================================================================== 시황 판단
def step20(closes, live=None):
    xs = list(closes) + ([live] if live else [])
    cur = xs[-1]
    mas = {n: sum(xs[-n:]) / n for n in (20, 40, 60, 90, 120)}
    below = [n for n, m in mas.items() if cur < m]
    return max(0.0, 1 - 0.2 * len(below)), mas, below, cur


def judge(base, dday, kq_live, ks_live, hot_count, temp, live_mode):
    w20, mas, below, cur = step20(base["index"]["kq"], kq_live["px"] if kq_live else None)
    F = []
    lt = "g" if w20 >= 0.999 else ("y" if w20 > 0 else "r")
    F.append({"label": f"코스닥 계단20: {cur:,.2f} — " + ("모든 이평선 위" if not below else ", ".join(f"{n}일선" for n in below) + " 아래") + f" → {w20*100:.0f}%",
              "light": lt, "tag": "ok", "tagt": "검증됨"})
    nxt = next_trading(dday)
    gap = (nxt - dday).days
    fri = dday.weekday() == 4 and gap == 3
    longh = gap >= 4
    thu = dday.weekday() == 3
    oexp = option_expiry(dday)
    hot = hot_count is not None and hot_count >= base["hot"]["thr"]
    mult = 1.0 + (0.5 if hot else 0) + (0.5 if fri else 0) - (0.5 if (thu or oexp) else 0)
    mult = min(2.0, max(0.5, mult))
    wd = "월화수목금토일"[dday.weekday()]
    day_txt = f"{dday:%m/%d}({wd})"
    if fri:
        F.append({"label": f"{day_txt} 주말 넘김 → +0.5배 (금요일이 가장 좋은 날)", "light": "g", "tag": "part", "tagt": "일부 근거"})
    elif longh:
        F.append({"label": f"{day_txt} 긴 연휴 전 (다음 거래일 {nxt:%m/%d}) — 가산 없음, 약한 편", "light": "y", "tag": "part", "tagt": "일부 근거"})
    if thu or oexp:
        F.append({"label": f"{day_txt} " + ("옵션 만기일" if oexp else "목요일") + " → −0.5배", "light": "y", "tag": "part", "tagt": "일부 근거"})
    if not (fri or longh or thu or oexp):
        F.append({"label": f"{day_txt} 요일 가감 없음", "light": "g", "tag": "part", "tagt": "일부 근거"})
    if hot_count is not None:
        F.append({"label": f"후보 {hot_count}개 (뜨거운 날 문턱 {base['hot']['thr']:.0f}개)" + (" → +0.5배" if hot else ""),
                  "light": "g" if hot else "y", "tag": "part", "tagt": "일부 근거"})
    us = str(dday)
    fomc = us in FOMC
    if fomc:
        F.append({"label": "오늘 밤 FOMC 발표 (새벽 3~4시) → ×0.5 — 종베 성적이 나빴던 밤", "light": "r", "tag": "part", "tagt": "일부 근거"})
    if us in CPI:
        F.append({"label": "오늘 밤 미국 CPI 발표 — 종베 성적 차이 없음 (표시만)", "light": "g", "tag": "info", "tagt": "표시만"})
    panic = bool(ks_live and ks_live.get("rt") is not None and ks_live["rt"] <= -4.0)
    if panic:
        F.append({"label": f"코스피 {ks_live['rt']:+.2f}% — 패닉 낙주 신호: 삼성전자·SK하이닉스 종가 매수 → 다음날 시가 매도", "light": "g", "tag": "ok", "tagt": "검증됨"})
    if temp:
        if temp["panic"]:
            F.append({"label": "체온계: 반대매매 급증 = 투매 진행 중 신호 (바닥 아님)", "light": "r", "tag": "info", "tagt": "참고"})
        elif temp["bottom"]:
            F.append({"label": "체온계: 신용잔고 급감 = 바닥 신호", "light": "g", "tag": "info", "tagt": "참고"})
        elif temp.get("fx") is not None:
            F.append({"label": f"체온계: 반대매매 평소의 {temp['fx']:.1f}배 (추정)", "light": "g" if temp["fx"] < 2 else "y", "tag": "info", "tagt": "참고"})
    weight = w20 * mult * (0.5 if fomc else 1.0)
    return {"w20": w20, "mas": mas, "below": below, "kq": cur, "kq_rt": kq_live["rt"] if kq_live else None,
            "ks": ks_live["px"] if ks_live else base["index"]["ks"][-1], "ks_rt": ks_live["rt"] if ks_live else None,
            "mult": mult, "fomc": fomc, "weight": weight, "factors": F, "panic": panic, "day": str(dday),
            "next": str(nxt), "live": live_mode}


def events(dday):
    tonight = []
    if str(dday) in FOMC:
        tonight.append("FOMC 발표")
    if str(dday) in CPI:
        tonight.append("CPI 발표")
    nf = min((d for d in FOMC if d > str(dday)), default=None)
    nc = min((d for d in CPI if d > str(dday)), default=None)
    return {"tonight": tonight, "next_fomc": nf, "next_cpi": nc}


# ====================================================================== 후보 계산
def btag(b):
    if b is None:
        return "?"
    return "지수형" if b >= 0.6 else ("중간" if b >= 0.43 else "개별형")


def build_rows_live(kw, base, up, since, keys, now_t):
    S, ix = base["stocks"], base["ix"]
    up3 = {r["code"]: r for r in up}
    auction = dt.time(15, 20) <= now_t.time() < dt.time(15, 31)
    vthr = 2.0 if now_t.time() >= dt.time(15, 20) else 1.8              # 장중엔 거래량이 아직 덜 쌓임
    pre = []
    for r in up:
        i = ix.get(r["code"])
        if i is None or r["code"][-1] != "0" or "스팩" in r["name"]:
            continue
        v20 = S["v20"][i] or 0
        vr = (r["vol"] / v20) if v20 else None
        run = S["run"][i] + 1
        large_ok = (3 <= r["rt"] < 28.5 and run >= 60 and (S["tv20"][i] or 0) >= 300 and (S["mc"][i] or 0) >= 5000
                    and (S["gp"][i] or 0) >= 0.8 - 1e-9)
        wide_pre = 3 <= r["rt"] < 28.5 and (S["tv20"][i] or 0) >= 10 and run >= 261 and (vr or 0) >= vthr * 0.9
        if large_ok or wide_pre:
            pre.append((r, i, vr, large_ok))
    rows = []
    for r, i, vr, large_ok in pre:
        try:
            info = kw.stock(r["code"])
        except Exception as e:  # noqa: BLE001
            log(f"ka10001 {r['code']} 실패: {e}"[:160]); continue
        px = info["exp"] if (auction and info.get("exp")) else (info["px"] or r["px"])
        hi, lo, upl, bp = info["high"], info["low"], info["upl"], info["base"] or S["close"][i]
        pos = (px - lo) / (hi - lo) if hi and lo and hi > lo else 1.0
        touched = bool(upl and hi and hi >= upl) or bool(hi and bp and hi / bp - 1 >= 0.285)
        rt = (px / bp - 1) * 100 if bp else r["rt"]
        peers = S["peers"][i]
        pu = sorted([p for p in peers if p in up3], key=lambda p: -up3[p]["rt"])
        n_up = len(pu)
        streak = S["th"][i] + 1 if n_up >= 3 else 0
        name = S["n"][i]
        warn = []
        if touched:
            warn.append("상한가 터치 후 풀림")
        if rt >= 25:
            warn.append("+25%↑")
        row = {"code": r["code"], "name": name, "m": S["m"][i], "mc": S["mc"][i], "px": px, "rt": round(rt, 2),
               "vr": round(vr, 2) if vr else None, "pos": round(pos, 3), "top": pos >= 0.999, "touched": touched,
               "tv": round(px * (info["vol"] or r["vol"] or 0) / 1e8, 1), "gp": S["gp"][i], "gm": S["gm"][i],
               "beta": S["beta"][i], "btag": btag(S["beta"][i]), "th": streak, "n_up": n_up,
               "peers_up": [f"{S['n'][ix[p]] if p in ix else up3[p]['name']} {up3[p]['rt']:+.1f}%" for p in pu[:6]],
               "large": bool(large_ok), "wide": bool((not touched) and rt < 25 and pos >= 0.7 and (vr or 0) >= vthr),
               "disc": disc_for(r["code"], since), "warn": warn, "news": None,
               "nsearch": f"https://search.naver.com/search.naver?where=news&sort=1&query={requests.utils.quote(name)}"}
        if any(d["cls"] == "bad" for d in row["disc"]):
            warn.append("희석·악재 공시")
        rows.append(row)
    excluded = [x for x in rows if x["touched"] or x["rt"] >= 25]
    return rows, excluded


def build_rows_base(base, since):
    S, ix = base["stocks"], base["ix"]
    rows = []
    seen = {}
    for lst in ("large", "wide"):
        for r in base["last"][lst]:
            i = ix.get(r["c"])
            if r["c"] in seen:
                seen[r["c"]][lst] = True; continue
            name = r["n"]
            row = {"code": r["c"], "name": name, "m": S["m"][i] if i is not None else "", "mc": S["mc"][i] if i is not None else None,
                   "px": r["px"], "rt": r["day"], "vr": r["vr"], "pos": r["pos"], "top": r["pos"] >= 0.999, "touched": False,
                   "tv": None, "gp": r["gp"], "gm": r["gm"], "beta": r["beta"], "btag": btag(r["beta"]), "th": r["th"], "n_up": None,
                   "peers_up": [], "large": lst == "large", "wide": lst == "wide", "disc": disc_for(r["c"], since), "warn": [],
                   "news": None, "nsearch": f"https://search.naver.com/search.naver?where=news&sort=1&query={requests.utils.quote(name)}"}
            seen[r["c"]] = row
            rows.append(row)
    return rows


def order(rows):
    L = sorted([r for r in rows if r["large"]], key=lambda r: -(r["gm"] if r["gm"] is not None else -9))
    W = sorted([r for r in rows if r["wide"]], key=lambda r: (-(1 if r["top"] else 0), -r["th"], -r["rt"]))
    for k, lst in (("large", L), ("wide", W)):
        for n, r in enumerate(lst):
            r[f"rank_{k}"] = n + 1
    return L, W


# ====================================================================== 갱신
def refresh(kind="manual"):
    with _lock:
        if STATE["running"]:
            return False
        STATE["running"] = True
    t0 = time.time()
    errs = []
    try:
        t = now()
        base = load_base()
        dday = decision_day(t)
        today = t.date()
        live_window = is_trading(today) and dt.time(9, 0) <= t.time() < dt.time(15, 45) and base["asof"] < str(today)
        since = dt.datetime.combine(prev_trading(dday), dt.time(15, 30))
        keys = naver_keys()
        kw = None
        if live_window:
            try:
                kw = KW.Kiwoom()
            except Exception as e:  # noqa: BLE001
                errs.append(str(e))
                kw = None
        pool = ThreadPoolExecutor(4)
        f_kind = pool.submit(kind_fetch, since)
        f_ovs = pool.submit(overseas)
        f_temp = pool.submit(temp_info)
        kq = ks = None
        up = []
        if kw:
            try:
                kq = kw.index("1", "101"); ks = kw.index("0", "001")
                up = kw.rank_up("1", 3.0)
            except Exception as e:  # noqa: BLE001
                ip = KW.public_ip() if ("IP" in str(e) or "801" in str(e)) else None
                errs.append(f"키움: {e}" + (f" · 현재 IP {ip}" if ip else "")); kw = None
        try:
            f_kind.result(timeout=90)
        except Exception as e:  # noqa: BLE001
            errs.append(f"KIND 공시: {e!r}"[:160])
        if kw:
            rows, excluded = build_rows_live(kw, base, up, since, keys, t)
            mode = "live"
        else:
            rows, excluded = build_rows_base(base, since), []
            mode = "base"
        L, W = order(rows)
        hot_count = len(W) if mode == "live" else int(base["hot"]["today"])   # 연구 규칙 후보 수 (뜨거운 날 판단)
        if keys:                                                     # 뉴스: 화면 위쪽 후보부터 최대 20종목
            show = (L[:10] + W[:10])
            done = set()
            for r in show:
                if r["code"] in done:
                    continue
                done.add(r["code"])
                r["news"] = news_for(r["name"], since, keys)
        try:
            temp = f_temp.result(timeout=30)
        except Exception:  # noqa: BLE001
            temp = None
        mk = judge(base, dday, kq, ks, hot_count, temp, mode == "live")
        try:
            ovs = f_ovs.result(timeout=40)
        except Exception:  # noqa: BLE001
            ovs = []
        pool.shutdown(wait=False)
        picks = load_picks().get(str(dday if mode == "live" else base["asof"]), {})
        data = {"ts": f"{t:%Y-%m-%d %H:%M:%S}", "kind": kind, "mode": mode, "day": str(dday), "base_asof": base["asof"],
                "cand_day": str(today) if mode == "live" else base["asof"],
                "status": {"kiwoom": KW.credentials() is not None, "naver": keys is not None, "errors": errs,
                           "secs": round(time.time() - t0, 1)},
                "market": mk, "events": events(dday), "overseas": ovs, "temp": temp,
                "large": L, "wide": W, "excluded": excluded, "hot": {"count": hot_count, "thr": base["hot"]["thr"]},
                "picks": picks, "results": results_summary(), "kind_n": len(_KIND)}
        OUT.mkdir(parents=True, exist_ok=True)
        s = json.dumps(data, ensure_ascii=False)
        (OUT / "latest.json").write_text(s, encoding="utf-8")
        snap = json.loads(s)                                        # 기록용: 뉴스는 제목을 쌓지 않고 '건수·새 뉴스 수'만 (네이버 약관 존중)
        for lst in ("large", "wide", "excluded"):
            for r in snap.get(lst, []):
                if r.get("news") is not None:
                    r["news"] = {"n": len(r["news"]), "fresh": sum(1 for x in r["news"] if x.get("fresh"))}
        ss = json.dumps(snap, ensure_ascii=False)
        d = SNAP / data["cand_day"].replace("-", "")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{t:%H%M%S}.json").write_text(ss, encoding="utf-8")
        if kind == "final" and mode == "live":
            (d / "final.json").write_text(ss, encoding="utf-8")
        STATE["last"] = data["ts"]
        log(f"갱신 완료 [{kind}/{mode}] 대형 {len(L)} · 전체 {len(W)} · 공시 {len(_KIND)}건 · {time.time()-t0:.0f}초" + (f" · 오류 {errs}" if errs else ""))
        return True
    except Exception as e:  # noqa: BLE001
        log(f"갱신 실패: {e!r}"[:300]); traceback.print_exc()
        return False
    finally:
        STATE["running"] = False


# ====================================================================== 기록: 내 선택 · 다음날 시가
def load_picks():
    f = OUT / "picks.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def set_pick(day, code, name, lst, on):
    p = load_picks()
    d = p.setdefault(day, {})
    if on:
        d[code] = {"n": name, "l": lst, "ts": f"{now():%H:%M:%S}"}
    else:
        d.pop(code, None)
    (OUT / "picks.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


RES_COLS = ["date", "code", "name", "list", "rank", "close", "open_next", "gap", "picked"]


def fill_results():
    """전 거래일 15:36 스냅샷의 후보 → 오늘 시가로 다음날 갭 기록 (results.csv)"""
    day = prev_trading(now().date())
    d = SNAP / str(day).replace("-", "")
    f = d / "final.json"
    if not f.exists():
        snaps = sorted(d.glob("[0-9]*.json")) if d.exists() else []
        if not snaps:
            log(f"결과 채우기: {day} 스냅샷 없음"); return
        f = snaps[-1]
    snap = json.loads(f.read_text(encoding="utf-8"))
    rf = OUT / "results.csv"
    have = set()
    if rf.exists():
        with rf.open(encoding="utf-8-sig") as fh:
            have = {(r["date"], r["code"], r["list"]) for r in csv.DictReader(fh)}
    picks = load_picks().get(str(day), {})
    try:
        kw = KW.Kiwoom()
    except Exception as e:  # noqa: BLE001
        log(f"결과 채우기 건너뜀: {e}"); return
    rows, opens = [], {}
    for lst in ("large", "wide"):
        for r in snap.get(lst, []):
            if (str(day), r["code"], lst) in have:
                continue
            if r["code"] not in opens:
                try:
                    opens[r["code"]] = kw.stock(r["code"])["open"]
                except Exception as e:  # noqa: BLE001
                    log(f"시가 {r['code']} 실패 {e}"[:120]); opens[r["code"]] = None
            o = opens[r["code"]]
            rows.append({"date": str(day), "code": r["code"], "name": r["name"], "list": lst, "rank": r.get(f"rank_{lst}"),
                         "close": r["px"], "open_next": o, "gap": round((o / r["px"] - 1) * 100, 3) if o and r["px"] else "",
                         "picked": 1 if r["code"] in picks else 0})
    new = not rf.exists()
    with rf.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RES_COLS)
        if new:
            w.writeheader()
        w.writerows(rows)
    log(f"결과 채우기: {day} {len(rows)}행")


def results_summary():
    rf = OUT / "results.csv"
    if not rf.exists():
        return None
    with rf.open(encoding="utf-8-sig") as fh:
        R = [r for r in csv.DictReader(fh) if r["gap"] not in ("", None)]
    if not R:
        return None
    days = sorted({r["date"] for r in R})[-20:]
    R = [r for r in R if r["date"] in days]

    def agg(sel):
        g = [float(r["gap"]) - COST for r in sel]
        return {"n": len(g), "avg": round(sum(g) / len(g), 3) if g else None, "win": round(sum(x > 0 for x in g) / len(g), 2) if g else None}
    top = lambda lst: [r for r in R if r["list"] == lst and r["rank"] and int(r["rank"]) <= 3]
    mine = {}
    for r in R:
        if r["picked"] == "1":
            mine[(r["date"], r["code"])] = r
    recent = sorted(R, key=lambda r: (r["date"], r["list"], int(r["rank"] or 99)), reverse=True)[:30]
    return {"days": len(days), "large3": agg(top("large")), "wide3": agg(top("wide")), "mine": agg(list(mine.values())),
            "recent": recent}


# ====================================================================== 예약 실행 · 웹 서버
def scheduler():
    fired = set()
    try:
        load_base()
    except Exception as e:  # noqa: BLE001
        log(str(e))
    threading.Thread(target=refresh, args=("start",), daemon=True).start()
    while True:
        t = now()
        if is_trading(t.date()):
            hm = f"{t:%H:%M}"
            for job, times in SCHEDULE.items():
                for x in times:
                    key = (str(t.date()), job, x)
                    if key in fired or hm < x or hm > _plus(x, 3):
                        continue
                    fired.add(key)
                    if job == "base":
                        threading.Thread(target=lambda: load_base(True), daemon=True).start()
                    elif job == "results":
                        threading.Thread(target=fill_results, daemon=True).start()
                    else:
                        threading.Thread(target=refresh, args=(job,), daemon=True).start()
        nx = [f"{x}" for times in SCHEDULE.values() for x in times if x > f"{t:%H:%M}"]
        STATE["next"] = min(nx) if nx and is_trading(t.date()) else None
        time.sleep(15)


def _plus(hm, mins):
    h, m = map(int, hm.split(":"))
    x = h * 60 + m + mins
    return f"{x // 60:02d}:{x % 60:02d}"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (HERE / "board.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if self.path.startswith("/api/latest"):
            f = OUT / "latest.json"
            return self._send(200, f.read_text(encoding="utf-8") if f.exists() else "{}")
        if self.path.startswith("/api/status"):
            return self._send(200, json.dumps({"running": STATE["running"], "last": STATE["last"], "next": STATE["next"],
                                               "log": LOG[-30:]}, ensure_ascii=False))
        self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if self.path == "/api/refresh":
            if STATE["running"]:
                return self._send(200, '{"ok":false,"msg":"이미 갱신 중"}')
            threading.Thread(target=refresh, args=("manual",), daemon=True).start()
            return self._send(200, '{"ok":true}')
        if self.path == "/api/pick":
            set_pick(body["day"], body["code"], body.get("name", ""), body.get("list", ""), bool(body.get("on")))
            return self._send(200, '{"ok":true}')
        self._send(404, "{}")


def serve():
    OUT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    log(f"종베 레이더 실행 중 → http://127.0.0.1:{PORT}  (이 창을 닫으면 멈춤)")
    try:
        import webbrowser
        if os.environ.get("RADAR_NO_BROWSER") != "1":
            webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:  # noqa: BLE001
        pass
    srv.serve_forever()


# ====================================================================== 키 등록 · 점검
def setup_kiwoom():
    import getpass
    print("키움 OpenAPI 포털(openapi.kiwoom.com)에서 발급한 '실전' 앱키를 넣어주세요. 입력값은 화면에 보이지 않습니다.")
    ak = getpass.getpass("App Key: ").strip()
    sk = getpass.getpass("Secret Key: ").strip()
    if not ak or not sk:
        print("취소했습니다."); return
    KW.save_credentials(ak, sk)
    try:
        k = KW.Kiwoom(); k._issue()
        print("저장했고 토큰 발급까지 확인했습니다 (Windows 자격 증명 관리자 'kiwoom-real').")
    except Exception as e:  # noqa: BLE001
        print(f"저장은 했지만 토큰 발급이 안 됩니다: {e}\n  → 키 값, 포털의 서비스 신청 상태, IP 등록 여부를 확인하세요.")


def setup_naver():
    import getpass
    import keyring
    print("네이버 클라우드 콘솔 → NAVER API HUB → Application(뉴스 검색 포함)의 Client ID / Client Secret. 입력값은 화면에 보이지 않습니다.")
    a = getpass.getpass("Client ID: ").strip()
    b = getpass.getpass("Client Secret: ").strip()
    if not a or not b:
        print("취소했습니다."); return
    keyring.set_password("krsc-radar-naver", "client_id", a)
    keyring.set_password("krsc-radar-naver", "client_secret", b)
    r = news_for("삼성전자", now() - dt.timedelta(days=1), (a, b))
    print("저장했습니다. 시험 검색:", (r[0]["title"][:40] if r else "결과 없음"))


def check():
    c = KW.credentials()
    print("키움 앱키:", f"있음 ({c[2]})" if c else "없음 → radar.bat setup-kiwoom")
    print("이 네트워크의 공인 IP:", KW.public_ip() or "확인 실패", "← 키움 포털 '계좌 App Key 관리'에 등록돼 있어야 함 (최대 10개)")
    if c:
        try:
            k = KW.Kiwoom()
            ix = k.index("1", "101")
            print(f"  코스닥 현재 {ix['px']:,.2f} ({ix['rt']:+.2f}%) — 키움 연결 정상")
            up = k.rank_up("1", 3.0, max_pages=1)
            print(f"  등락률 상위 첫 페이지 {len(up)}종목")
        except Exception as e:  # noqa: BLE001
            print("  키움 호출 실패:", e)
    print("네이버 뉴스 키:", "있음" if naver_keys() else "없음 (선택) → radar.bat setup-naver")
    b = load_base()
    print(f"기초 데이터: 기준일 {b['asof']} · {len(b['stocks']['c']):,}종목 · 뜨거운 날 문턱 {b['hot']['thr']:.0f}")
    print(f"오늘 판단일 {decision_day()} · 다음 거래일 {next_trading(decision_day())}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    {"serve": serve, "run": lambda: refresh("manual"), "setup-kiwoom": setup_kiwoom, "setup-naver": setup_naver,
     "check": check, "results": fill_results}.get(cmd, serve)()
