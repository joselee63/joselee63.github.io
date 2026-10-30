"""시황판 뉴스 (사이트 news.json) — GitHub 워크플로 news.yml 이 하루 여러 번 실행

입력
  · 언론사 RSS (연합뉴스 경제·마켓+ · 한국경제 증권 · 전자신문) — 실행 때마다 받아 data 브랜치 news/rss/날짜.jsonl 에 쌓음
  · 텔레그램 속보의 '기사 제목 + 원문 링크' — 내 PC 레이더가 data 브랜치 news/tg/날짜.jsonl 에 올림 (tools/market/news_tg.py)
  · market.json (tools/market/market_board.py) — 섹터 구성 종목, 최근 거래일, 종목·섹터 등락 (반응 표시용)
출력 news.json
  · quad: 섹터별 최근 5거래일 뉴스량(평소 60거래일 대비) × 5일 주가(시장 대비) — 뉴스가 먹히는 섹터
  · rising / cool / top: 헤드라인 단어 온도 (최근 5거래일 vs 직전 20거래일, 규칙 기반 단어 세기) · today: 오늘 vs 직전 3일 평균
  · feed: 섹터별·전체 최신 기사 (제목 · 매체 · 원문 링크 · 그 뒤 주가 반응)
사용: python tools/market/news_board.py NEWS_DIR market.json OUT.json
"""
import datetime as dt
import email.utils
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import requests

NEWS = Path(sys.argv[1] if len(sys.argv) > 1 else "news")
MKT = Path(sys.argv[2] if len(sys.argv) > 2 else "market.json")
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else "news.json")
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST).replace(tzinfo=None)

RSS = [("연합뉴스", "https://www.yna.co.kr/rss/economy.xml"), ("연합뉴스", "https://www.yna.co.kr/rss/market.xml"),
       ("한국경제", "https://www.hankyung.com/feed/finance"), ("전자신문", "https://rss.etnews.com/Section901.xml")]

KW = {
    "반도체 대형 · 메모리": ["HBM", "D램", "디램", "낸드", "메모리"], "반도체 장비 (전공정 · HBM · 후공정)": ["반도체 장비", "TC본더", "하이브리드 본딩", "본더"],
    "반도체 소재 · 부품 · 테스트": ["반도체 소재", "프로브카드", "테스트 소켓"], "시스템반도체 · 디자인하우스": ["파운드리", "팹리스", "NPU", "디자인하우스"],
    "전자부품 · AI 기판 · 광통신": ["MLCC", "기판", "광통신", "유리기판", "광모듈"], "AI 데이터센터 · 클라우드 · 통신": ["데이터센터", "클라우드", "통신3사"],
    "전력기기 · 전선 (AI 전력 인프라)": ["변압기", "전력기기", "전선", "송전", "전력망"], "원자력 · SMR": ["원전", "SMR", "원자력"],
    "2차전지 셀": ["배터리", "2차전지", "이차전지"], "2차전지 소재 · 장비": ["양극재", "음극재", "리튬", "전해액", "분리막"],
    "ESS · 태양광 · 풍력 · 수소": ["ESS", "태양광", "풍력", "수소"], "조선 · 조선기자재": ["조선", "LNG선", "선박", "MASGA", "마스가", "함정"],
    "방산": ["방산", "K9", "K2전차", "무기", "천궁", "레드백"], "우주항공": ["우주", "위성", "발사체", "누리호", "스페이스X"],
    "로봇 · 휴머노이드": ["로봇", "휴머노이드"], "자동차 · 부품": ["자동차", "완성차", "전기차"],
    "AI 소프트웨어 · 플랫폼 · 보안": ["소버린", "AI 에이전트", "해킹", "보안주", "사이버"], "양자 · 보안 통신": ["양자"],
    "디지털자산 · 스테이블코인 · 결제": ["스테이블코인", "비트코인", "가상자산", "코인", "원화 스테이블"],
    "제약 · 바이오 대형": ["바이오시밀러", "제약"], "바이오 플랫폼 · 비만 · 신약 (미국 피어 연동)": ["비만", "신약", "임상", "기술이전", "FDA", "GLP"],
    "의료기기 · 미용 · 의료AI": ["의료기기", "미용기기", "보톡스", "톡신", "의료AI"], "K-뷰티": ["화장품", "K뷰티", "K-뷰티"],
    "K-푸드 · 음식료": ["라면", "불닭", "식품", "K푸드", "K-푸드"], "엔터 · 미디어": ["엔터", "아이돌", "K팝", "콘서트", "드라마"],
    "게임": ["게임", "신작"], "은행 · 금융지주 (밸류업)": ["은행", "금융지주", "밸류업"], "증권 · 보험": ["증권사", "보험사"],
    "지주사 (지배구조 · 상법개정)": ["지주사", "상법", "자사주 소각", "지배구조"], "건설 · 인프라": ["건설", "재건", "주택"],
    "철강 · 비철 · 화학 · 정유": ["철강", "석유화학", "정유", "구리", "아연"], "해운 · 항공 · 여행 · 카지노": ["해운", "항공", "여행", "카지노", "운임"],
    "유통 · 의류 · 가전": ["유통", "백화점", "면세", "가전"],
}
ALIAS = {"SK하이닉스": ["하이닉스"], "한화에어로스페이스": ["한화에어로"], "LG에너지솔루션": ["LG엔솔"], "현대자동차": ["현대차"]}
# 이야기 온도에서 빼는 일반 단어 — 실적 용어·동작·정도·시간처럼 '무엇에 대한 이야기인지' 말해 주지 않는 말 (별도 파일, 직접 고쳐도 됨)
STOP = set(re.sub(r"#.*", "", (Path(__file__).with_name("news_stopwords.txt")).read_text(encoding="utf-8")).split())
STOP |= {"관련", "업계", "가운데", "밝혔다", "없어", "만에"}
KEEP_END = {"캐나다", "키트루다", "라이다", "플로리다", "혼다", "아이다"}     # '~다' 로 끝나도 남길 이름
MIXED = ("오픈AI", "챗GPT", "스페이스X")                                  # 한글+영문 붙은 이름은 통째로
PART = ("으로", "에서", "에게", "까지", "부터", "에도", "에는", "이다", "하는", "했다", "한다", "된다",
        "들", "에", "의", "은", "는", "이", "가", "을", "를", "과", "와", "도", "로", "만", "서")
RAW = Counter()     # 헤드라인 단어를 조사 떼기 전 모양 그대로 센 수 — main() 에서 채움


def f(x, n=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, n) if math.isfinite(x) else None


def norm(h):
    return re.sub(r"[\W_]+", "", re.sub(r"^\[[^\]]+\]", "", h))[:40]


# ---------------------------------------------------------------- RSS 받아 쌓기
def fetch_rss():
    got = 0
    for media, url in RSS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (kr-sector-charts news)"}, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::RSS 실패 {media} {url}: {e!r}"[:200]); continue
        by_day = defaultdict(list)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip()
            pd_ = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
            if not title or not link or not pd_:
                continue
            try:
                t = email.utils.parsedate_to_datetime(pd_)
            except (TypeError, ValueError):
                try:
                    t = dt.datetime.fromisoformat(pd_.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=KST)
            t = t.astimezone(KST).replace(tzinfo=None)
            by_day[t.date()].append({"t": f"{t:%H:%M}", "m": media, "h": re.sub(r"\s+", " ", title)[:160], "u": link})
        for day, items in by_day.items():
            p = NEWS / "rss" / f"{day:%Y-%m-%d}.jsonl"
            old = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
            have = {x["u"] for x in old}
            new = [x for x in items if x["u"] not in have]
            if new:
                p.parent.mkdir(parents=True, exist_ok=True)
                allx = sorted(old + new, key=lambda x: x["t"])
                p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in allx), encoding="utf-8", newline="\n")
                got += len(new)
    print("RSS 새 기사", got)


# ---------------------------------------------------------------- 불러오기
def load(days=140):
    recs = []
    for src in ("tg", "rss"):
        for p in sorted((NEWS / src).glob("*.jsonl")) if (NEWS / src).exists() else []:
            try:
                day = dt.date.fromisoformat(p.stem)
            except ValueError:
                continue
            if (NOW.date() - day).days > days:
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    x = json.loads(line)
                    hh, mm = map(int, x["t"].split(":"))
                except (ValueError, KeyError):
                    continue
                recs.append((dt.datetime(day.year, day.month, day.day, hh, mm), src, x["m"], x["h"], x["u"]))
    recs.sort(key=lambda r: r[0])
    seen, out = set(), []
    for r in recs:                                       # 같은 기사(제목) 중복 제거 — 먼저 나온 것 유지
        k = norm(r[3])
        if k in seen:
            continue
        seen.add(k); out.append(r)
    return out


WORD = r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]{1,}"


def strip_part(w):
    """조사 떼기. 한 글자 조사(이·가·로·서 …)는 떼고 남은 말이 따로도 자주 쓰일 때만 뗀다
    → '삼성전자가'→'삼성전자', 하지만 '디스플레이'·'제미나이'·'마운자로'·'국제유가'·'김정은' 은 그대로."""
    for p in PART:
        if len(w) > len(p) + 1 and w.endswith(p):
            stem = w[:-len(p)]
            if len(p) >= 2 or not RAW or RAW[stem] * 2 >= RAW[w]:
                return stem
            return w
    return w


def toks(h):
    h = re.sub(r"^\[[^\]]+\]", "", h)
    out = set()
    for m in MIXED:
        if m in h:
            out.add(m); h = h.replace(m, " ")
    for w in re.findall(WORD, h):
        if re.match(r"[가-힣]", w):
            w = strip_part(w)
            if w.endswith(("다", "까")) and w not in KEEP_END:      # 한다·나선다·뚫었다·될까 … 같은 서술어
                continue
            if w.endswith("는"):                                     # 만드는·노리는·커지는 … 꾸밈말 (명사+는 은 위에서 이미 뗌)
                continue
        else:
            if not (w.isupper() or len(w) >= 4):
                continue
            w = w.upper() if len(w) <= 5 else w
        if len(w) >= 2 and w not in STOP:
            out.add(w)
    return out


def main():
    fetch_rss()
    M = json.loads(MKT.read_text(encoding="utf-8"))
    px = M.get("px") or {}
    sessions = list(M.get("sessions") or M["band"]["dates"])
    asof = M["asof"]
    d0 = dt.datetime.strptime(sessions[-1], "%Y%m%d").date()       # 앞으로의 평일(공휴일 무시)을 거래일로 이어 붙임
    target = len(sessions) + 8
    while len(sessions) < target:
        d0 += dt.timedelta(days=1)
        if d0.weekday() < 5:
            sessions.append(f"{d0:%Y%m%d}")
    sidx = {d: i for i, d in enumerate(sessions)}

    def sess(t):
        d = f"{t:%Y%m%d}"
        if d < sessions[0]:
            return None
        for i, s in enumerate(sessions):
            if s > d or (s == d and t.hour * 60 + t.minute < 930):
                return i
        return None

    members = px.get("members") or {h["n"]: [[m["c"], m["n"]] for m in h["mem"]] for h in M["G3"]["heat"]}
    SECS = list(members.keys())
    K = len(SECS)
    pats = []
    for s in SECS:
        names = []
        for c, n in members[s]:
            names.append((n, c))
            for a in ALIAS.get(n, []):
                names.append((a, c))
        pats.append((names, KW.get(s, [])))

    def name_in(n, h):
        if len(n) >= 4:
            return n in h
        return re.search(r"(?<![가-힣A-Za-z0-9])" + re.escape(n) + r"(?![가-힣A-Za-z0-9])", h) is not None

    recs = load()
    for r in recs:
        RAW.update(re.findall(WORD, re.sub(r"^\[[^\]]+\]", "", r[3])))
    print("기사", len(recs), "(텔레그램", sum(1 for r in recs if r[1] == "tg"), "· RSS", sum(1 for r in recs if r[1] == "rss"), ")")
    pxd = {d: i for i, d in enumerate(px.get("dates") or [])}
    S5 = {h["n"]: h.get("rel5") for h in M["G3"]["heat"]}

    cnt = {"tg": defaultdict(lambda: [0] * K), "all": defaultdict(lambda: [0] * K)}
    tot = {"tg": Counter(), "all": Counter()}
    feed = defaultdict(list); allfeed = []
    tagged = []
    for t, src, media, h, u in recs:
        j = sess(t)
        if j is None:
            continue
        hit = []
        for k, (names, kws) in enumerate(pats):
            stock = next(((n, c) for n, c in names if len(n) >= 2 and name_in(n, h)), None)
            kw = next((w for w in kws if w in h), None)
            if stock or kw:
                hit.append((k, stock))
        for key in (("tg", "all") if src == "tg" else ("all",)):
            tot[key][j] += 1
            for k, _ in hit:
                cnt[key][j][k] += 1
        tagged.append((t, src, h, j))
        if (NOW - t).days <= 14:
            sday = sessions[j]; done = sday <= asof
            base = dict(t=f"{t:%m/%d %H:%M}", m=media, h=h, u=u, s="tg" if src == "tg" else "rss",
                        sec=[SECS[k] for k, _ in hit][:2], live=not done, sd=f"{sday[4:6]}/{sday[6:]}")
            if hit:
                allfeed.append(base)
            for k, stock in hit:
                r = None; who = stock[0] if stock else "섹터"
                if done and sday in pxd:
                    arr = (px.get("stock") or {}).get(stock[1]) if stock else (px.get("sector") or {}).get(SECS[k])
                    r = arr[pxd[sday]] if arr else None
                feed[k].append(dict(base, who=who, r=r))

    jT = sidx.get(asof)
    use = "tg"
    if jT is not None:
        rt = sum(tot["tg"][j] for j in range(jT - 4, jT + 1)); bt = sum(tot["tg"][j] for j in range(jT - 64, jT - 4))
        if rt < 150 or bt < 1500:
            use = "all"
    quad = []
    if jT is not None:
        C = cnt[use]; Tt = tot[use]
        rec_t = sum(Tt[j] for j in range(jT - 4, jT + 1)); base_t = sum(Tt[j] for j in range(jT - 64, jT - 4))
        nb = max(1, sum(1 for j in range(jT - 64, jT - 4) if Tt[j] > 0) / 5)          # 기준 기간을 5일 묶음 수로
        jN = sess(NOW)
        for k, s in enumerate(SECS):
            rc = sum(C[j][k] for j in range(jT - 4, jT + 1)); bc = sum(C[j][k] for j in range(jT - 64, jT - 4))
            a = (rc + 1) / (rec_t + 30); b = (bc + 12) / (base_t + 360)
            quad.append(dict(n=s, x=f(math.log2(a / b), 3), y=f(S5.get(s)), cnt=rc, base=f(bc / nb, 1),
                             today=C[jN][k] if jN is not None else 0))
    # 단어 온도: 최근 5거래일(오늘 포함) vs 직전 20거래일
    jN = sess(NOW) or (jT or 0)
    rc_, bc_ = Counter(), Counter(); rt_ = bt_ = 0
    for t, src, h, j in tagged:
        if use == "tg" and src != "tg":
            continue
        if jN - 4 <= j <= jN:
            rc_.update(toks(h)); rt_ += 1
        elif jN - 24 <= j < jN - 4:
            bc_.update(toks(h)); bt_ += 1
    kw = [(w, c, bc_[w], ((c + 2) / (rt_ + 50)) / ((bc_[w] + 2) / (bt_ + 50))) for w, c in rc_.items() if c >= 6]
    rising = sorted([x for x in kw if x[3] >= 1.6], key=lambda x: -x[3] * math.log(x[1]))[:16]
    cool = sorted([(w, rc_[w], c, ((rc_[w] + 2) / (rt_ + 50)) / ((c + 2) / (bt_ + 50))) for w, c in bc_.items() if c >= 20],
                  key=lambda x: x[3])
    cool = [x for x in cool if x[3] <= 0.5][:10]
    top = sorted(kw, key=lambda x: -x[1])[:12]
    # 오늘 많이 나온 단어: 오늘(달력 날짜) 헤드라인 vs 직전 3일(기사 30건 이상인 날) 평균 — 하루 중간이라도 '비중'으로 비교
    byday = defaultdict(list)
    for t, src, h, j in tagged:
        if use == "tg" and src != "tg":
            continue
        byday[t.date()].append(h)
    days = sorted(d for d, hs in byday.items() if len(hs) >= 30 or d == NOW.date())
    day_t = NOW.date() if len(byday.get(NOW.date(), [])) >= 30 else next((d for d in reversed(days) if len(byday[d]) >= 30), None)
    today, today_n, day_b = [], 0, []
    if day_t:
        day_b = [d for d in days if d < day_t and len(byday[d]) >= 30][-3:]
        tc, bc3 = Counter(), Counter()
        for h in byday[day_t]:
            tc.update(toks(h))
        for d in day_b:
            for h in byday[d]:
                bc3.update(toks(h))
        today_n = len(byday[day_t]); bn = sum(len(byday[d]) for d in day_b)
        if day_b:
            nd = len(day_b)
            tw = [(w, c, f(bc3[w] / nd, 1), ((c + 1) / (today_n + 30)) / ((bc3[w] + 1) / (bn + 90))) for w, c in tc.items() if c >= 3]
            today = sorted([x for x in tw if x[3] >= 1.8], key=lambda x: -x[3] * math.log(x[1] + 1))[:14]
    W = lambda L: [dict(w=w, c=c, b=b, r=f(r)) for w, c, b, r in L]
    tg_last = max((r[0] for r in recs if r[1] == "tg"), default=None)
    out = dict(built=f"{NOW:%Y-%m-%d %H:%M}", asof=asof, basis=use, n_rec=rt_, n_base=bt_,
               tg_last=f"{tg_last:%m/%d %H:%M}" if tg_last else None,
               last=f"{recs[-1][0]:%m/%d %H:%M}" if recs else None,
               quad=quad, rising=W(rising), cool=W(cool), top=W(top),
               today=W(today), today_d=f"{day_t:%m/%d}" if day_t else None, today_n=today_n,
               today_b=[f"{d:%m/%d}" for d in day_b],
               feed={SECS[k]: list(reversed(v))[:20] for k, v in feed.items()}, all=list(reversed(allfeed))[:40])
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"news.json {OUT.stat().st_size:,} bytes · 기준 {use} · 텔레그램 마지막 {out['tg_last']} · 뜨는 단어 {[x['w'] for x in out['rising'][:8]]}")


if __name__ == "__main__":
    main()
