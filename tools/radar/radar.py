"""종베 레이더 — 15:00~15:30 KRX 종가베팅 · 16:00~20:00 NXT 애프터 · 08:05~08:46 아침 점검 (내 PC 전용 · 사이트에 올리지 않음)

  radar.bat               보드 실행 → 브라우저 http://127.0.0.1:8790 (평일 정해진 시각에 자동 갱신)
  radar.bat run           지금 한 번 갱신하고 끝 (15시 모드) · radar.bat nxt / radar.bat am  NXT 애프터 / 아침 점검 한 번
  radar.bat setup-telegram 텔레그램 실시간 수신 설정 (선택 — 내 계정으로 구독 채널 새 글 읽기)
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
            "live": ["15:00", "15:06", "15:11", "15:15", "15:19", "15:23", "15:27"], "final": ["15:36"], "krxclose": ["15:37"],
            "nxt": ["16:00", "17:00", "18:00", "19:00", "19:30", "19:45"], "nxt1955": ["19:55"], "nxtclose": ["20:03"],
            "am": ["08:05", "08:20", "08:31", "08:40"], "am0845": ["08:46"]}
# 사이트(GitHub Actions) 워크플로를 정시에 시작 — GitHub 예약 실행은 이 저장소에서 매일 4~5시간씩 늦게 시작됨(2026-10 관찰)
# 순서: 종가베팅 데이터 → 투자자별 수급 → 시총 등 → 사이트 빌드 → 리포트. 늦게 도는 GitHub 예약은 백업(이미 만든 날은 건너뜀)
SITE_REPO = "joselee63/joselee63.github.io"
NEWS_JOBS = ["08:45", "10:00", "11:30", "13:30", "15:45", "17:30", "19:50"]   # 사이트 시황판 뉴스 올리는 시각 (tools/market/news_tg.py)
SITE_JOBS = [("18:42", "closebet.yml"), ("20:10", "investor-data.yml"), ("20:50", "alpha-data.yml"),
             ("21:10", "daily.yml"), ("21:20", "alpha-reports.yml")]
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


def theme_map(kw, errs, max_age_days=3):
    """키움 테마 구성(테마 → 종목)을 하루 한 번 받아 radar-out/kiwoom_themes.json 에 저장 (약 140번 호출, 40초 안팎)"""
    f = OUT / "kiwoom_themes.json"
    old = None
    if f.exists():
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
            if old.get("day") == str(now().date()):
                return old
        except Exception:  # noqa: BLE001
            old = None
    try:
        allt = kw.themes_all()
        names, members = {}, {}
        for t in allt:
            names[t["cd"]] = t["nm"]
            members[t["cd"]] = kw.theme_members(t["cd"])
        by = {}
        for cd, cs in members.items():
            for c in cs:
                by.setdefault(c, []).append(cd)
        m = {"day": str(now().date()), "names": names, "by": by}
        f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        log(f"키움 테마 구성 받음: 테마 {len(names)} · 종목 {len(by)}")
        return m
    except Exception as e:  # noqa: BLE001
        errs.append(f"테마 구성: {e}"[:120])
        if old and (now().date() - dt.date.fromisoformat(old["day"])).days <= max_age_days:
            return old
        return None


def add_themes(rows, kw, errs, base):
    """후보마다 ① 키움 테마(직접 소속) ② 추정 테마(같이 움직이는 동료 10종목의 키움 테마 중 2개↑ 겹침) ③ 동료 이름.
    테마 등락률·상승 종목 수는 매 갱신 실시간. 키움 키가 없으면 동료 이름만."""
    S, ix = base["stocks"], base["ix"]
    for r in rows:
        i = ix.get(r["code"])
        r["peers_nm"] = [S["n"][ix[p]] for p in (S["peers"][i] if i is not None else [])[:6] if p in ix]
    if kw is None:
        if not KW.credentials():
            return []
        try:
            kw = KW.Kiwoom()
        except Exception:  # noqa: BLE001
            return []
    stats = {}
    try:
        for t in kw.themes_all():
            stats[t["cd"]] = t
    except Exception as e:  # noqa: BLE001
        errs.append(f"테마 등락: {e}"[:120])
    tm = theme_map(kw, errs)
    if tm is None:
        return []
    names, by = tm["names"], tm["by"]

    def info(cd, cnt=None):
        st = stats.get(cd, {})
        return {"cd": cd, "nm": names.get(cd, st.get("nm", cd)), "rt": st.get("rt"), "up": st.get("up"), "n": st.get("n"),
                "main": st.get("main", ""), **({"cnt": cnt} if cnt is not None else {})}
    for r in rows:
        own = by.get(r["code"], [])
        r["themes"] = sorted([info(cd) for cd in own], key=lambda t: -(t["rt"] if t["rt"] is not None else -99))
        i = ix.get(r["code"])
        cnt = {}
        for p in (S["peers"][i] if i is not None else []):
            for cd in by.get(p, []):
                if cd not in own:
                    cnt[cd] = cnt.get(cd, 0) + 1
        r["themes_inf"] = [info(cd, n) for cd, n in sorted(cnt.items(), key=lambda x: -x[1]) if n >= 2][:4]
    top = sorted([t for t in stats.values() if (t["n"] or 0) >= 3 and t["rt"] is not None], key=lambda t: -t["rt"])[:10]
    return top


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
        themes_top = add_themes(rows, kw, errs, base)
        tgm = tg_mentions(base, since)
        for r in rows + excluded:
            r["tg"] = (tgm or {}).get(r["code"], []) if tgm is not None else None
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
                "themes_top": themes_top,
                "picks": picks, "results": results_summary(), "kind_n": len(_KIND)}
        OUT.mkdir(parents=True, exist_ok=True)
        s = json.dumps(data, ensure_ascii=False)
        (OUT / "latest.json").write_text(s, encoding="utf-8")
        snap = _strip_news(data, ("large", "wide", "excluded"))   # 기록용: 뉴스·텔레그램은 원문 대신 건수만 (네이버 약관 존중)
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


# ====================================================================== 2단계: NXT 애프터 · 아침 점검
_MODE = {"nxt": {"running": False, "last": None}, "am": {"running": False, "last": None}}


def yahoo_series(sym, rng="5d", itv="5m"):
    """야후 분봉 → [(한국 시각, 종가)]"""
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + requests.utils.quote(sym, safe=""),
                     params={"range": rng, "interval": itv}, headers=UA, timeout=12)
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    cl = res["indicators"]["quote"][0].get("close") or []
    out = []
    for a, c in zip(ts, cl):
        if c is not None:
            out.append((dt.datetime.fromtimestamp(a, dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=9), float(c)))
    return out


def futures_since(ref):
    """나스닥·S&P 선물: ref(한국 시각, 보통 그날 15:00) 이후 변화 — 저녁 흐름(A) / 밤사이 흐름"""
    out = []
    for nm, sym in (("나스닥 선물", "NQ=F"), ("S&P 선물", "ES=F")):
        try:
            ser = yahoo_series(sym)
            before = [c for t, c in ser if ref - dt.timedelta(hours=3) <= t <= ref]
            p0, p1 = (before[-1] if before else None), ser[-1][1]
            out.append({"n": nm, "s": sym, "ref": p0, "px": p1, "chg": (p1 / p0 - 1) * 100 if p0 else None,
                        "at": f"{ser[-1][0]:%H:%M}"})
        except Exception:  # noqa: BLE001
            out.append({"n": nm, "s": sym, "ref": None, "px": None, "chg": None, "at": ""})
    return out


def yahoo_last(sym, prepost=True):
    """야후 1분봉(프리·애프터 포함) → 마지막 가격·시각·직전 정규장 종가·세션"""
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + requests.utils.quote(sym, safe=""),
                     params={"range": "1d", "interval": "1m", "includePrePost": "true" if prepost else "false"}, headers=UA, timeout=12)
    res = r.json()["chart"]["result"][0]
    m = res["meta"]
    ts = res.get("timestamp") or []
    cl = res["indicators"]["quote"][0].get("close") or []
    pts = [(a, c) for a, c in zip(ts, cl) if c is not None]
    last_t, last = (pts[-1] if pts else (m.get("regularMarketTime"), m.get("regularMarketPrice")))
    per = m.get("currentTradingPeriod") or {}
    ses = "정규장"
    for k, lab in (("pre", "프리마켓"), ("post", "애프터마켓")):
        p0 = per.get(k) or {}
        if p0.get("start") and p0.get("start") <= (last_t or 0) < p0.get("end", 0):
            ses = lab
    prev = m.get("regularMarketPrice") if ses in ("프리마켓", "애프터마켓") else m.get("chartPreviousClose")   # 프리·애프터는 직전 정규장 종가 대비
    if ses == "정규장" and last_t and (time.time() - last_t) > 1800:
        ses = "마감"
    return {"px": float(last) if last else None, "prev": float(prev) if prev else None, "reg": m.get("regularMarketPrice"),
            "at": (dt.datetime.fromtimestamp(last_t, dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%m-%d %H:%M") if last_t else "",
            "ses": ses}


def us_macro(kw, krx_hynix=None, nxt_hynix=None):
    """저녁·아침 시황: 미국채 10년물(^TNX)·10년 국채선물(ZN=F)·SK하이닉스 ADR(키움 미국주식, 프리·애프터 반영)·EWY(MSCI 한국 ETF)"""
    out = {}
    try:
        t = yahoo_last("^TNX", prepost=False)
        out["tnx"] = {"n": "미국채 10년물", "px": t["px"], "chg_bp": (t["px"] - t["prev"]) * 100 if t["px"] and t["prev"] else None,
                      "at": t["at"], "note": "CBOE 지수 — 미국 정규장 시간에만 갱신"}
    except Exception:  # noqa: BLE001
        pass
    try:
        z = yahoo_last("ZN=F", prepost=False)
        out["zn"] = {"n": "10년 국채선물 (가격)", "px": z["px"], "chg": (z["px"] / z["prev"] - 1) * 100 if z["px"] and z["prev"] else None,
                     "at": z["at"], "note": "24시간 거래 — 가격이 오르면 금리 하락"}
    except Exception:  # noqa: BLE001
        pass
    adr = None
    try:
        y = yahoo_last("SKHY")
        adr = {"ses": y["ses"], "at": y["at"], "px": y["px"], "prev": y["prev"], "fx": None, "src": "yahoo"}
    except Exception:  # noqa: BLE001
        y = None
    if kw is not None:
        try:
            d, _ = kw.call("usa20100", "/api/us/mrkcond", {"stex_tp": "ND", "stk_cd": "SKHY"})
            px, base, fx = KW.num(d.get("cur_prc"), True), KW.num(d.get("base_close_pric"), True), KW.num(d.get("base_exrt"), True)
            if px:
                adr = {"ses": (y or {}).get("ses", ""), "at": f"{now():%m-%d %H:%M}", "px": px, "prev": base, "fx": fx, "src": "키움"}
        except Exception:  # noqa: BLE001
            pass
    if adr and adr.get("px"):
        if not adr.get("fx"):
            try:
                adr["fx"] = yahoo_last("KRW=X", prepost=False)["px"]
            except Exception:  # noqa: BLE001
                pass
        adr["chg"] = (adr["px"] / adr["prev"] - 1) * 100 if adr.get("prev") else None
        if adr.get("fx"):
            adr["krw"] = adr["px"] * adr["fx"] * 10                    # ADR 1주 = 보통주 1/10주
            if krx_hynix:
                adr["prem_krx"] = (adr["krw"] / krx_hynix - 1) * 100
            if nxt_hynix:
                adr["prem_nxt"] = (adr["krw"] / nxt_hynix - 1) * 100
        out["adr"] = adr
    try:
        e = yahoo_last("EWY")
        out["ewy"] = {"n": "EWY (MSCI 한국 ETF)", "px": e["px"], "chg": (e["px"] / e["prev"] - 1) * 100 if e["px"] and e["prev"] else None,
                      "at": e["at"], "ses": e["ses"]}
    except Exception:  # noqa: BLE001
        pass
    out["k200n"] = kospi200_night()
    return out


def kospi200_night():
    """코스피200 야간선물 — 키움 REST 에 선물 시세가 없어 KIS(한국투자증권) 키가 있을 때만 (kis.py)"""
    try:
        import kis
    except ImportError:
        return {"need": "KIS"}
    try:
        return kis.night_future() if kis.configured() else {"need": "KIS"}
    except Exception as e:  # noqa: BLE001
        return {"need": "KIS", "err": str(e)[:120]}


def yahoo_closes(base, day):
    """야후 정규장 종가 (20종목씩 묶어 요청) — 16:00 이후엔 키움 KRX 현재가가 시간외 단일가로 바뀌므로 이걸로 채움"""
    S = base["stocks"]
    items = [(c, f"{c}.{'KQ' if m == 'Q' else 'KS'}") for c, m in zip(S["c"], S["m"])]
    out = {}
    for i in range(0, len(items), 20):
        chunk = items[i:i + 20]
        try:
            r = requests.get("https://query1.finance.yahoo.com/v7/finance/spark",
                             params={"symbols": ",".join(y for _, y in chunk), "range": "1d", "interval": "1d"}, headers=UA, timeout=15)
            for x in r.json().get("spark", {}).get("result") or []:
                resp = (x.get("response") or [{}])[0]
                m = resp.get("meta", {})
                px, prev, tm = m.get("regularMarketPrice"), m.get("chartPreviousClose"), m.get("regularMarketTime")
                if not px or not tm:
                    continue
                if (dt.datetime.fromtimestamp(tm, dt.timezone.utc) + dt.timedelta(hours=9)).date() != day:
                    continue                                       # 그날 체결이 아님 (거래정지 등)
                out[x["symbol"].split(".")[0]] = {"px": float(px), "rt": (px / prev - 1) * 100 if prev else None, "src": "yahoo"}
        except Exception:  # noqa: BLE001
            continue
    return out


def krx_closes(kw, day, errs, base=None):
    """그날 KRX 정규장 종가 — snap/날짜/krx_close.json 에 한 번 저장
    ※ 키움 KRX 현재가는 16:00~18:00 시간외 단일가 체결로 바뀜 → 키움 값은 15:31~16:00 사이 것만 종가로 인정, 그 밖엔 야후 정규장 종가"""
    d = SNAP / str(day).replace("-", "")
    f = d / "krx_close.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    t = now()
    m = {}
    if t.date() == day and dt.time(15, 31) <= t.time() < dt.time(16, 0):
        try:
            rows = kw.rank_all("1", 45)
            m = {c: {"px": r["px"], "rt": r["rt"], "n": r["name"], "src": "kiwoom"} for c, r in rows.items() if r.get("px")}
        except Exception as e:  # noqa: BLE001
            errs.append(f"KRX 종가: {e}"[:120])
    elif (t.date() > day or t.time() >= dt.time(16, 0)) and base is not None:
        m = yahoo_closes(base, day)
        if len(m) < 300:
            errs.append(f"KRX 종가(야후) {len(m)}종목뿐 — 일부 종목 장후 변화 없음")
    if len(m) >= 300:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        log(f"KRX 종가 저장: {len(m):,}종목 ({next(iter(m.values()))['src']})")
    return m


def day_snapshot(day, names=("final.json",)):
    d = SNAP / str(day).replace("-", "")
    for nm in names:
        f = d / nm
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
    snaps = sorted(d.glob("[0-9]*.json")) if d.exists() else []
    if snaps and "final.json" in names:
        return json.loads(snaps[-1].read_text(encoding="utf-8"))
    return None


def tg_mentions(base, since, until=None):
    try:
        import tg
        return tg.mentions(OUT, base, since, until) if tg.configured(OUT) else None
    except Exception:  # noqa: BLE001
        return None


def stock_row(base, code, extra=None):
    S, ix = base["stocks"], base["ix"]
    i = ix.get(code)
    r = {"code": code, "name": S["n"][i] if i is not None else code, "m": S["m"][i] if i is not None else "",
         "mc": S["mc"][i] if i is not None else None, "beta": S["beta"][i] if i is not None else None,
         "gp": S["gp"][i] if i is not None else None, "gm": S["gm"][i] if i is not None else None,
         "btag": btag(S["beta"][i] if i is not None else None),
         "nsearch": f"https://search.naver.com/search.naver?where=news&sort=1&query={requests.utils.quote(S['n'][i] if i is not None else code)}"}
    if extra:
        r.update(extra)
    return r


def cause_of(rows):
    """재료형(장후 공시·새 뉴스·텔레그램) / 동반형(같이 움직이는 종목 중 재료형이 있음) / 원인 미확인"""
    by = {r["code"]: r for r in rows}
    for r in rows:
        tags = [d["tag"] for d in r.get("disc") or [] if d["cls"] != "info"]
        nf = sum(1 for n in (r.get("news") or []) if n.get("fresh"))
        nt = len(r.get("tg") or [])
        r["n_fresh"], r["n_tg"] = nf, nt
        if tags or nf or nt:
            r["cause"] = "재료형"
            r["cause_txt"] = " · ".join(([f"공시 {tags[0]}"] if tags else []) + ([f"새 뉴스 {nf}"] if nf else []) + ([f"텔레그램 {nt}"] if nt else []))
        else:
            r["cause"] = None
    for r in rows:
        if r["cause"]:
            continue
        lead = [p for p in r.get("peers_c", []) if p in by and by[p]["cause"] == "재료형"]
        if lead:
            r["cause"], r["cause_txt"] = "동반형", f"동반: {by[lead[0]]['name']}"
        else:
            r["cause"], r["cause_txt"] = "미확인", "원인 미확인 (뉴스·공시 없음)"


def _strip_news(data, lists):
    snap = json.loads(json.dumps(data, ensure_ascii=False))
    for lst in lists:
        for r in snap.get(lst, []):
            if isinstance(r.get("news"), list):
                r["news"] = {"n": len(r["news"]), "fresh": sum(1 for x in r["news"] if x.get("fresh"))}
            if isinstance(r.get("tg"), list):
                r["tg"] = len(r["tg"])
    return snap


def refresh_nxt(kind="manual"):
    st = _MODE["nxt"]
    if st["running"]:
        return False
    st["running"] = True
    t0, errs = time.time(), []
    try:
        t = now()
        day = t.date() if is_trading(t.date()) else prev_trading(t.date())
        base = load_base()
        S, ix = base["stocks"], base["ix"]
        since = dt.datetime.combine(day, dt.time(15, 20))
        kw = KW.Kiwoom()
        pool = ThreadPoolExecutor(3)
        f_kind = pool.submit(kind_fetch, since)
        f_fut = pool.submit(futures_since, dt.datetime.combine(day, dt.time(15, 0)))
        f_ovs = pool.submit(overseas)
        closes = krx_closes(kw, day, errs, base)
        nx = kw.rank_all("2", 20)
        ovt = {}                                                  # KRX 시간외 단일가 (16:00~18:00, 10분마다 체결)
        if dt.time(16, 0) <= t.time() <= dt.time(18, 15) and t.date() == day:
            try:
                ovt = {c: r["px"] for c, r in kw.rank_all("1", 45).items() if r.get("px")}
            except Exception as e:  # noqa: BLE001
                errs.append(f"시간외 단일가: {e}"[:100])
        keys = naver_keys()
        # ① 오늘 종베 후보의 NXT 가격
        fs = day_snapshot(day)
        cands, seen = [], set()
        if fs and fs.get("cand_day") == str(day):
            for lst, lab in (("large", "대형"), ("wide", "전체")):
                for r in fs.get(lst, [])[:8]:
                    if r["code"] in seen:
                        continue
                    seen.add(r["code"])
                    kc = (closes.get(r["code"]) or {}).get("px") or r["px"]
                    q = nx.get(r["code"])
                    cands.append(stock_row(base, r["code"], {"src": f"{lab} {r.get('rank_' + lst, '')}위", "krx": kc, "krx_rt": r.get("rt"),
                                                             "nxt": q["px"] if q else None, "nxt_vol": q["vol"] if q else None,
                                                             "gap": round((q["px"] / kc - 1) * 100, 2) if q and kc and q["px"] else None}))
        # ② NXT 장후 등락 (NXT 현재가 ÷ KRX 종가)
        mv = []
        for c, q in nx.items():
            kc = (closes.get(c) or {}).get("px")
            i = ix.get(c)
            if not kc or not q.get("px") or i is None or (S["tv20"][i] or 0) < 10:
                continue
            mv.append((q["px"] / kc - 1, c, q, kc))
        up = sorted([x for x in mv if x[0] >= 0.02], key=lambda x: -x[0])[:40]
        dn = sorted([x for x in mv if x[0] <= -0.03], key=lambda x: x[0])[:12]
        movers, losers = [], []
        for lst, src in ((up, movers), (dn, losers)):
            for g, c, q, kc in lst:
                src.append(stock_row(base, c, {"krx": kc, "krx_rt": (closes.get(c) or {}).get("rt"), "nxt": q["px"], "nxt_vol": q["vol"],
                                              "gap": round(g * 100, 2), "src": "NXT 장후"}))
        try:
            f_kind.result(timeout=90)
        except Exception as e:  # noqa: BLE001
            errs.append(f"KIND 공시: {e!r}"[:120])
        tgm = tg_mentions(base, since)
        allr = cands + movers + losers
        for r in allr:
            r["disc"] = disc_for(r["code"], since)
            r["tg"] = (tgm or {}).get(r["code"], []) if tgm is not None else None
            i = ix.get(r["code"])
            r["peers_c"] = S["peers"][i] if i is not None else []
            o = ovt.get(r["code"])
            if o and r.get("krx") and abs(o / r["krx"] - 1) > 1e-9:
                r["ovt"], r["ovt_gap"] = o, round((o / r["krx"] - 1) * 100, 2)
        if keys:
            done = {}
            for r in (cands + movers[:15] + losers[:5]):
                if r["code"] not in done:
                    done[r["code"]] = news_for(r["name"], since, keys)
                r["news"] = done[r["code"]]
        add_themes(allr, kw, errs, base)
        cause_of(movers + losers + cands)
        for r in allr:
            r.pop("peers_c", None)
        fut = f_fut.result(timeout=40) if not f_fut.exception() else []
        try:
            ovs = f_ovs.result(timeout=40)
        except Exception:  # noqa: BLE001
            ovs = []
        pool.shutdown(wait=False)
        try:
            macro = us_macro(kw, (closes.get("000660") or {}).get("px"), (nx.get("000660") or {}).get("px"))
        except Exception as e:  # noqa: BLE001
            macro = {}; errs.append(f"미국 시황: {e!r}"[:100])
        nq = next((x for x in fut if x["s"] == "NQ=F"), {})
        A = nq.get("chg")
        warn = None
        if A is not None and abs(A) >= 0.5:
            warn = (f"나스닥 선물이 15시 이후 {A:+.2f}% — 이렇게 크게 움직인 저녁은 밤새 같은 방향으로 더 가는 편이었습니다 "
                    f"(2024-06~2026-10, 이후 평균 {'+0.57' if A > 0 else '−0.63'}%). 지수형(β 높음) 종목에 영향이 큽니다.")
        for r in allr:
            if r.get("beta") is not None and A is not None:
                r["est"] = round(r["beta"] * A, 2)                    # 저녁 선물 흐름 × β (평균적 반응, 참고)
        data = {"ts": f"{t:%Y-%m-%d %H:%M:%S}", "kind": kind, "day": str(day), "base_asof": base["asof"],
                "status": {"errors": errs, "secs": round(time.time() - t0, 1), "nxt_n": len(nx), "krx_n": len(closes),
                           "krx_src": (next(iter(closes.values()), {}) or {}).get("src", ""),
                           "naver": keys is not None, "tg": tgm is not None},
                "futures": fut, "warn": warn, "overseas": ovs, "events": events(day), "macro": macro,
                "cands": cands, "movers": movers, "losers": losers, "cand_found": bool(fs and fs.get("cand_day") == str(day)),
                "cand_src": {"ts": (fs or {}).get("ts"), "kind": (fs or {}).get("kind")},
                "results": results_nxt_summary(), "kind_n": len(_KIND)}
        s = json.dumps(data, ensure_ascii=False)
        (OUT / "latest_nxt.json").write_text(s, encoding="utf-8")
        snap = json.dumps(_strip_news(data, ("cands", "movers", "losers")), ensure_ascii=False)
        d = SNAP / str(day).replace("-", "")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"nxt_{t:%H%M%S}.json").write_text(snap, encoding="utf-8")
        if kind in ("nxt1955", "nxtclose"):
            (d / ("nxt_1955.json" if kind == "nxt1955" else "nxt_close.json")).write_text(snap, encoding="utf-8")
        st["last"] = data["ts"]
        log(f"NXT 갱신 [{kind}] 후보 {len(cands)} · 장후 급등 {len(movers)} · 급락 {len(losers)} · NXT {len(nx)}종목 · {time.time()-t0:.0f}초" + (f" · 오류 {errs}" if errs else ""))
        return True
    except Exception as e:  # noqa: BLE001
        msg = f"NXT 갱신 실패: {e}"
        if "8050" in str(e) or "IP" in str(e):
            msg += f" · 현재 IP {KW.public_ip()}"
        log(msg[:300]); traceback.print_exc()
        (OUT / "latest_nxt.json").write_text(json.dumps({"ts": f"{now():%Y-%m-%d %H:%M:%S}", "error": msg}, ensure_ascii=False), encoding="utf-8")
        st["last"] = f"{now():%Y-%m-%d %H:%M:%S}"
        return False
    finally:
        st["running"] = False


def refresh_am(kind="manual"):
    st = _MODE["am"]
    if st["running"]:
        return False
    st["running"] = True
    t0, errs = time.time(), []
    try:
        t = now()
        day = t.date() if (is_trading(t.date()) and t.time() < dt.time(15, 40)) else next_trading(t.date())
        prev = prev_trading(day)
        base = load_base()
        kw = KW.Kiwoom()
        since = dt.datetime.combine(prev, dt.time(15, 20))
        pool = ThreadPoolExecutor(3)
        f_kind = pool.submit(kind_fetch, since)
        f_fut = pool.submit(futures_since, dt.datetime.combine(prev, dt.time(15, 0)))
        f_ovs = pool.submit(overseas)
        fs = day_snapshot(prev)
        nf = day_snapshot(prev, ("nxt_close.json", "nxt_1955.json"))
        picks = load_picks().get(str(prev), {})
        kc_file = SNAP / str(prev).replace("-", "") / "krx_close.json"
        kcl = json.loads(kc_file.read_text(encoding="utf-8")) if kc_file.exists() else {}
        src = {}
        if fs:
            for lst, lab in (("large", "대형"), ("wide", "전체")):
                for r in fs.get(lst, [])[:5]:
                    src.setdefault(r["code"], []).append(f"{lab} {r.get('rank_' + lst, '')}위")
        n1955 = {}
        if nf:
            for r in nf.get("cands", []) + nf.get("movers", [])[:15]:
                n1955[r["code"]] = r.get("nxt")
                if r.get("src") == "NXT 장후":
                    src.setdefault(r["code"], []).append(f"NXT 장후 {r.get('gap', 0):+.1f}%")
        for c in picks:
            src.setdefault(c, []).insert(0, "내 선택")
        rows = []
        for c, labs in list(src.items())[:50]:
            try:
                k = kw.stock(c)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{c}: {e}"[:80]); continue
            try:
                q = kw.stock(c + "_NX") if t.time() >= dt.time(8, 0) else None
            except Exception:  # noqa: BLE001
                q = None
            close = ((kcl.get(c) or {}).get("px")                    # 어제 15:37에 저장한 KRX 종가가 가장 정확
                     or (fs and next((r["px"] for lst in ("large", "wide") for r in fs.get(lst, []) if r["code"] == c), None))
                     or k.get("base"))
            exp = k.get("exp") if dt.time(8, 30) <= t.time() < dt.time(9, 0, 30) else None
            pre = q.get("px") if q else None
            rows.append(stock_row(base, c, {"src": labs, "picked": c in picks, "krx": close, "nxt1955": n1955.get(c),
                                            "pre": pre, "pre_gap": round((pre / close - 1) * 100, 2) if pre and close else None,
                                            "exp": exp, "exp_gap": round((exp / close - 1) * 100, 2) if exp and close else None,
                                            "open": k.get("open") if t.time() >= dt.time(9, 0, 30) else None}))
        try:
            f_kind.result(timeout=90)
        except Exception as e:  # noqa: BLE001
            errs.append(f"KIND 공시: {e!r}"[:120])
        tgm = tg_mentions(base, since)
        fut = f_fut.result(timeout=40) if not f_fut.exception() else []
        nq = next((x for x in fut if x["s"] == "NQ=F"), {})
        for r in rows:
            r["disc"] = disc_for(r["code"], since)
            r["tg"] = (tgm or {}).get(r["code"], []) if tgm is not None else None
            if r.get("beta") is not None and nq.get("chg") is not None:
                r["est"] = round(r["beta"] * nq["chg"], 2)
        try:
            ovs = f_ovs.result(timeout=40)
        except Exception:  # noqa: BLE001
            ovs = []
        pool.shutdown(wait=False)
        try:
            hy = next((r for r in rows if r["code"] == "000660"), None)
            macro = us_macro(kw, (kcl.get("000660") or {}).get("px"), (hy or {}).get("pre"))
        except Exception as e:  # noqa: BLE001
            macro = {}; errs.append(f"미국 시황: {e!r}"[:100])
        data = {"ts": f"{t:%Y-%m-%d %H:%M:%S}", "kind": kind, "day": str(day), "prev": str(prev), "macro": macro,
                "status": {"errors": errs, "secs": round(time.time() - t0, 1), "tg": tgm is not None},
                "futures": fut, "overseas": ovs, "rows": rows, "kind_n": len(_KIND)}
        s = json.dumps(data, ensure_ascii=False)
        (OUT / "latest_am.json").write_text(s, encoding="utf-8")
        d = SNAP / str(day).replace("-", "")
        d.mkdir(parents=True, exist_ok=True)
        snap = json.dumps(_strip_news(data, ("rows",)), ensure_ascii=False)
        (d / f"am_{t:%H%M%S}.json").write_text(snap, encoding="utf-8")
        if kind == "am0845":
            (d / "am_0845.json").write_text(snap, encoding="utf-8")
        st["last"] = data["ts"]
        log(f"아침 점검 [{kind}] {len(rows)}종목 · {time.time()-t0:.0f}초" + (f" · 오류 {errs}" if errs else ""))
        return True
    except Exception as e:  # noqa: BLE001
        msg = f"아침 점검 실패: {e}"
        if "8050" in str(e) or "IP" in str(e):
            msg += f" · 현재 IP {KW.public_ip()}"
        log(msg[:300]); traceback.print_exc()
        (OUT / "latest_am.json").write_text(json.dumps({"ts": f"{now():%Y-%m-%d %H:%M:%S}", "error": msg}, ensure_ascii=False), encoding="utf-8")
        st["last"] = f"{now():%Y-%m-%d %H:%M:%S}"
        return False
    finally:
        st["running"] = False


NXT_COLS = ["date", "code", "name", "src", "cause", "krx_close", "gap_1955", "nxt_1955", "nxt_close", "pre_0845", "open_next",
            "r_1955_open", "r_1955_pre", "disc", "news_fresh", "tg"]


def fill_results_nxt(kw, opens):
    """전 거래일 19:55 NXT 스냅샷 → 오늘 08:45 프리·09:00 시가 (results_nxt.csv): 'NXT 19:55 매수 → 시가/프리 매도' 검증용"""
    day = prev_trading(now().date())
    a = day_snapshot(day, ("nxt_1955.json",))
    if not a:
        log(f"NXT 결과: {day} 19:55 스냅샷 없음"); return
    b = day_snapshot(day, ("nxt_close.json",)) or {}
    am = day_snapshot(now().date(), ("am_0845.json",)) or {}
    closeq = {r["code"]: r.get("nxt") for r in b.get("cands", []) + b.get("movers", []) + b.get("losers", [])}
    pre = {r["code"]: r.get("pre") for r in am.get("rows", [])}
    rf = OUT / "results_nxt.csv"
    have = set()
    if rf.exists():
        with rf.open(encoding="utf-8-sig") as fh:
            have = {(r["date"], r["code"], r["src"]) for r in csv.DictReader(fh)}
    rows = []
    for lst in ("cands", "movers", "losers"):
        for r in a.get(lst, []):
            key = (str(day), r["code"], r.get("src", lst))
            if key in have or not r.get("nxt"):
                continue
            if r["code"] not in opens:
                try:
                    opens[r["code"]] = kw.stock(r["code"])["open"]
                except Exception:  # noqa: BLE001
                    opens[r["code"]] = None
            o, n1 = opens[r["code"]], r["nxt"]
            p = pre.get(r["code"])
            rows.append({"date": str(day), "code": r["code"], "name": r["name"], "src": r.get("src", lst), "cause": r.get("cause") or "",
                         "krx_close": r.get("krx"), "gap_1955": r.get("gap"), "nxt_1955": n1, "nxt_close": closeq.get(r["code"]),
                         "pre_0845": p, "open_next": o, "r_1955_open": round((o / n1 - 1) * 100, 3) if o and n1 else "",
                         "r_1955_pre": round((p / n1 - 1) * 100, 3) if p and n1 else "",
                         "disc": len([d for d in r.get("disc") or [] if d.get("cls") != "info"]),
                         "news_fresh": (r.get("news") or {}).get("fresh", "") if isinstance(r.get("news"), dict) else "",
                         "tg": r.get("tg") if isinstance(r.get("tg"), int) else ""})
    new = not rf.exists()
    with rf.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=NXT_COLS)
        if new:
            w.writeheader()
        w.writerows(rows)
    log(f"NXT 결과 채우기: {day} {len(rows)}행")


def results_nxt_summary():
    rf = OUT / "results_nxt.csv"
    if not rf.exists():
        return None
    with rf.open(encoding="utf-8-sig") as fh:
        R = [r for r in csv.DictReader(fh) if r["r_1955_open"] not in ("", None)]
    if not R:
        return None
    days = sorted({r["date"] for r in R})[-20:]
    R = [r for r in R if r["date"] in days]

    def agg(sel, col="r_1955_open"):
        g = [float(r[col]) - COST for r in sel if r[col] not in ("", None)]
        return {"n": len(g), "avg": round(sum(g) / len(g), 3) if g else None, "win": round(sum(x > 0 for x in g) / len(g), 2) if g else None}
    mv = [r for r in R if r["src"] == "NXT 장후"]
    return {"days": len(days), "cands": agg([r for r in R if r["src"] != "NXT 장후"]),
            "mat": agg([r for r in mv if r["cause"] == "재료형"]), "co": agg([r for r in mv if r["cause"] == "동반형"]),
            "unk": agg([r for r in mv if r["cause"] == "미확인"]), "mat_pre": agg([r for r in mv if r["cause"] == "재료형"], "r_1955_pre"),
            "recent": sorted(R, key=lambda r: (r["date"], r["src"]), reverse=True)[:30]}


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
    if not f.exists():                                            # 15:36 확정본이 없으면 15:20 이후 스냅샷만 (장중 가격을 종가로 쓰면 결과가 틀어짐)
        snaps = sorted(x for x in (d.glob("[0-9]*.json") if d.exists() else []) if x.stem >= "152000")
        if not snaps:
            log(f"결과 채우기: {day} 15:20 이후 스냅샷 없음 — 건너뜀"); return
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


def fill_all():
    """09:06 — 어제 종베 후보의 시가 결과 + 어제 19:55 NXT 목록의 프리·시가 결과"""
    try:
        fill_results()
    except Exception as e:  # noqa: BLE001
        log(f"결과 채우기 실패: {e!r}"[:200])
    try:
        fill_results_nxt(KW.Kiwoom(), {})
    except Exception as e:  # noqa: BLE001
        log(f"NXT 결과 채우기 실패: {e!r}"[:200])


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
def prebuild_themes():
    """키움 테마 구성을 미리 받아 둠 (15:00 갱신이 기다리지 않게)"""
    if not KW.credentials():
        return
    try:
        errs = []
        theme_map(KW.Kiwoom(), errs)
        if errs:
            log(f"테마 구성 준비 실패: {errs}")
    except Exception as e:  # noqa: BLE001
        log(f"테마 구성 준비 실패: {e!r}"[:160])


def gh_path():
    import shutil
    g = shutil.which("gh")
    if g:
        return g
    for c in (r"C:\Program Files\GitHub CLI\gh.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe")):
        if os.path.exists(c):
            return c
    return None


def site_dispatch(wf):
    """GitHub 워크플로 수동 시작 (gh CLI 로그인 필요 · 끄려면 환경변수 RADAR_SITE_TRIGGER=0)"""
    if os.environ.get("RADAR_SITE_TRIGGER") == "0":
        return
    g = gh_path()
    if not g:
        log(f"사이트 워크플로 {wf}: gh(GitHub CLI)가 없어 건너뜀"); return
    import subprocess
    try:
        r = subprocess.run([g, "workflow", "run", wf, "-R", SITE_REPO], capture_output=True, text=True, timeout=60)
        log(f"사이트 워크플로 시작 {wf}: " + ("성공" if r.returncode == 0 else "실패 " + (r.stderr or r.stdout).strip()[:150]))
    except Exception as e:  # noqa: BLE001
        log(f"사이트 워크플로 {wf} 실패: {e!r}"[:160])


def news_push(dispatch=True):
    """텔레그램 속보 중 '기사 제목 + 원문 링크'만 저장소 data 브랜치 news/tg/ 로 올리고 news.yml 시작 (끄려면 RADAR_SITE_TRIGGER=0)"""
    if os.environ.get("RADAR_SITE_TRIGGER") == "0" or not (OUT / "telegram").exists():
        return
    try:
        sys.path.insert(0, str(ROOT / "tools" / "market"))
        import news_tg
        news_tg.push(log=log, dispatch=dispatch)
    except Exception as e:  # noqa: BLE001
        log(f"뉴스 올리기 실패: {e!r}"[:160])


def scheduler():
    fired = set()
    try:
        load_base()
    except Exception as e:  # noqa: BLE001
        log(str(e))
    threading.Thread(target=prebuild_themes, daemon=True).start()
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
                        threading.Thread(target=lambda: (load_base(True), prebuild_themes()), daemon=True).start()
                    elif job == "results":
                        threading.Thread(target=fill_all, daemon=True).start()
                    elif job == "krxclose":
                        threading.Thread(target=lambda: krx_closes(KW.Kiwoom(), now().date(), [], load_base()), daemon=True).start()
                    elif job in ("nxt", "nxt1955", "nxtclose"):
                        threading.Thread(target=refresh_nxt, args=(job,), daemon=True).start()
                    elif job in ("am", "am0845"):
                        threading.Thread(target=refresh_am, args=(job,), daemon=True).start()
                    else:
                        threading.Thread(target=refresh, args=(job,), daemon=True).start()
            for x in NEWS_JOBS:                                  # 사이트 시황판 뉴스: 텔레그램 기사 제목·링크 올리기
                key = (str(t.date()), "news", x)
                if key in fired or hm < x or hm > _plus(x, 5):
                    continue
                fired.add(key)
                threading.Thread(target=news_push, daemon=True).start()
            for x, wf in SITE_JOBS:
                key = (str(t.date()), "site", x)
                if key in fired or hm < x or hm > _plus(x, 5):
                    continue
                fired.add(key)
                threading.Thread(target=site_dispatch, args=(wf,), daemon=True).start()
        hm = f"{t:%H:%M}"
        if "07:00" <= hm <= "23:30" and t.minute % 30 == 0:          # 30분마다 텔레그램 기사만 올림 — 사이트 '뉴스 새로고침' 버튼용
            key = (str(t.date()), "newsq", hm)                       # 장 마감 뒤 미국 실적·지표 뉴스까지, 주말도 (작업 시작은 안 함)
            if key not in fired:
                fired.add(key)
                threading.Thread(target=news_push, args=(False,), daemon=True).start()
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
            m = "nxt" if "m=nxt" in self.path else ("am" if "m=am" in self.path else "")
            f = OUT / (f"latest_{m}.json" if m else "latest.json")
            return self._send(200, f.read_text(encoding="utf-8") if f.exists() else "{}")
        if self.path.startswith("/api/status"):
            try:
                import tg
                tgs = tg.status()
                tgs["configured"] = tg.configured(OUT)
            except Exception:  # noqa: BLE001
                tgs = {"configured": False}
            return self._send(200, json.dumps({"running": STATE["running"], "last": STATE["last"], "next": STATE["next"],
                                               "running_nxt": _MODE["nxt"]["running"], "last_nxt": _MODE["nxt"]["last"],
                                               "running_am": _MODE["am"]["running"], "last_am": _MODE["am"]["last"],
                                               "now": f"{now():%Y-%m-%d %H:%M:%S}", "tg": tgs, "log": LOG[-30:]}, ensure_ascii=False))
        self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if self.path.startswith("/api/refresh"):
            m = "nxt" if "m=nxt" in self.path else ("am" if "m=am" in self.path else "")
            fn = {"nxt": refresh_nxt, "am": refresh_am}.get(m, refresh)
            busy = _MODE[m]["running"] if m else STATE["running"]
            if busy:
                return self._send(200, '{"ok":false,"msg":"이미 갱신 중"}')
            threading.Thread(target=fn, args=("manual",), daemon=True).start()
            return self._send(200, '{"ok":true}')
        if self.path == "/api/pick":
            set_pick(body["day"], body["code"], body.get("name", ""), body.get("list", ""), bool(body.get("on")))
            return self._send(200, '{"ok":true}')
        self._send(404, "{}")


def serve():
    OUT.mkdir(parents=True, exist_ok=True)
    try:                                                          # 이미 켜져 있으면 브라우저만 열고 끝 (중복 실행 = 예약 갱신 두 번)
        if requests.get(f"http://127.0.0.1:{PORT}/api/status", timeout=2).ok:
            print(f"종베 레이더가 이미 실행 중입니다 → http://127.0.0.1:{PORT} 를 엽니다.")
            if os.environ.get("RADAR_NO_BROWSER") != "1":
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{PORT}")
            return
    except Exception:  # noqa: BLE001
        pass
    ThreadingHTTPServer.allow_reuse_address = False               # Windows 는 기본값이면 같은 포트를 두 프로그램이 동시에 열 수 있음
    threading.Thread(target=scheduler, daemon=True).start()
    try:
        import tg
        tg.start(OUT, log)
    except Exception as e:  # noqa: BLE001
        log(f"텔레그램 수신 시작 실패: {e!r}"[:160])
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
    try:
        import tg
        print("텔레그램 수신:", "설정됨" if tg.configured(OUT) else "없음 (선택) → radar.bat setup-telegram")
    except Exception:  # noqa: BLE001
        print("텔레그램 수신: telethon 미설치")
    b = load_base()
    print(f"기초 데이터: 기준일 {b['asof']} · {len(b['stocks']['c']):,}종목 · 뜨거운 날 문턱 {b['hot']['thr']:.0f}")
    print(f"오늘 판단일 {decision_day()} · 다음 거래일 {next_trading(decision_day())}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    def _setup_tg():
        import tg
        tg.setup(OUT)
    {"serve": serve, "run": lambda: refresh("manual"), "nxt": lambda: refresh_nxt("manual"), "am": lambda: refresh_am("manual"),
     "setup-kiwoom": setup_kiwoom, "setup-naver": setup_naver, "setup-telegram": _setup_tg,
     "check": check, "results": fill_all}.get(cmd, serve)()
