"""리포트 레코드 → 공개용 데이터(out/data.json · out/ai.json) + Claude 작업 입력(work/)

- 목표가 변화: 같은 증권사의 직전 목표가와 비교. 본문 문구를 먼저 믿는다
  ① 본문 '기존 X원에서' ② 목표주가 줄의 '(유지)' ③ 본문 '목표주가 N% 상향/하향' ④ 직전 기록(0.55~2.2배·200일 안, 방향 단어와 어긋나지 않을 때)
  ⑤ 상향/하향 단어만 ⑥ 확인 필요(액면분할 등) / 첫 기록
- 공개 데이터에는 텔레그램 글 번호·채널 요약 문장·태그·파일명을 넣지 않는다 (번호는 pub_id 로 바꿈)
"""
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402
import parse as P   # noqa: E402

RANK = {"매도": 0, "중립": 1, "매수": 2}
PREV_RE = re.compile(r"(?:기존|종전|직전)\s*(?:목표주가\s*)?(?:TP\s*)?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(만\s*원|원)?\s*(?:에서|→|->|대비|으로부터)")
PCT_RE = re.compile(r"(?:목표주가|목표가|TP)[^.\n]{0,50}?(\d+(?:\.\d+)?)\s*%\s*(상향|하향)")
DIR_RE = re.compile(r"(?:목표주가|목표가|TP)[^.\n]{0,40}?(상향|하향|유지)")
DAILY_RE = re.compile(r"Daily|데일리|모닝|Morning|마감\s*시황|아침|Forex|FX Daily", re.I)


def day(r):
    return r["date"][:10]


# ---------------------------------------------------------------- 가격
def prices():
    """레이더가 저장한 가장 최근 KRX 전 종목 종가 (radar-out/snap/날짜/krx_close.json) + 시총(radar_base)"""
    close, mcap, asof = {}, {}, None
    rbp = C.REPO / "radar-out/radar_base.json"
    if rbp.exists():
        rb = json.loads(rbp.read_text(encoding="utf-8"))
        close = dict(zip(rb["stocks"]["c"], rb["stocks"]["close"]))
        mcap = dict(zip(rb["stocks"]["c"], rb["stocks"]["mc"]))
        asof = rb.get("asof")
    snaps = sorted((C.REPO / "radar-out/snap").glob("*/krx_close.json")) if (C.REPO / "radar-out/snap").exists() else []
    if snaps:
        close.update({k: v["px"] for k, v in json.loads(snaps[-1].read_text(encoding="utf-8")).items() if v.get("px")})
        d = snaps[-1].parent.name
        asof = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return close, mcap, asof


def code_of(n):
    return P.STOCK[n][0] if n in P.STOCK else None


def ind_of(n, fallback=None):
    if n in P.STOCK_IND_FIX:
        return P.STOCK_IND_FIX[n]
    if fallback:
        return fallback
    s = P.STOCK.get(n, ("", "", ""))[2]
    return P.KRX2IND.get(s, s) or None


# ---------------------------------------------------------------- 목표가 이벤트
def _text_prev(txt, tp, name=None):
    for sent in re.split(r"(?<=[.다음함])\s+|\n", txt):
        if not re.search(r"목표|TP", sent) or (name and name not in sent):
            continue
        m = PREV_RE.search(sent)
        if m:
            v = float(m.group(1).replace(",", "")) * (10000 if m.group(2) and "만" in m.group(2) else 1)
            if v >= 100 and 0.4 < tp / v < 2.5:
                return v
    return None


def _text_pct(txt, name=None):
    for sent in re.split(r"(?<=[.다음함])\s+|\n", txt):
        if name and name not in sent:
            continue
        m = PCT_RE.search(sent)
        if m:
            p = float(m.group(1)) * (1 if m.group(2) == "상향" else -1)
            if 0 < abs(p) < 150:
                return p
    return None


def events(U):
    ev = []
    for r in U:
        if not r["broker"]:
            continue
        if r["kind"] == "종목" and r["subj"] and r["tp"] and r["tp"]["u"] == "원":
            ev.append(dict(date=r["date"], name=r["subj"], broker=r["broker"], tp=r["tp"]["v"], op=r["op"], opch=r["opch"],
                           chw=r["tp"]["ch"], src=r["id"], text=r["text"]))
        for m in r["multi"]:
            if m["tp"] and m["tp"]["u"] == "원":
                ev.append(dict(date=r["date"], name=m["name"], broker=r["broker"], tp=m["tp"]["v"], op=m["op"], opch=m["opch"],
                               chw=m["tp"]["ch"], src=r["id"], text=r["text"], multi=True))
    ev.sort(key=lambda e: (e["date"][:10], bool(e.get("multi")), e["src"]))
    seen, out = set(), []
    for e in ev:                        # 같은 날·증권사·종목·목표가(종목+산업 리포트 중복)는 한 번만, 종목 리포트 우선
        k = (e["date"][:10], e["name"], e["broker"], e["tp"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    ev = sorted(out, key=lambda e: (e["date"], e["src"]))
    last = {}
    for e in ev:
        p = last.get((e["name"], e["broker"]))
        e["prev"], e["prevdate"], e["prevop"] = (p["tp"], p["date"][:10], p["op"]) if p else (None, None, None)
        nm = e["name"] if e.get("multi") else None
        txt, word = e["text"], e["chw"]
        if not word:
            m = DIR_RE.search(txt) if not e.get("multi") else None
            word = m.group(1) if m else None
        pv, src = None, None
        tv = _text_prev(txt, e["tp"], nm)
        tpct = _text_pct(txt, nm)
        gap = (dt.date.fromisoformat(e["date"][:10]) - dt.date.fromisoformat(e["prevdate"])).days if e["prevdate"] else 9999
        arch_ok = e["prev"] and 0.55 < e["tp"] / e["prev"] < 2.2 and gap <= 200
        if tv:
            pv, src = tv, "본문"
        elif word == "유지" and e["chw"] == "유지":
            pv, src = e["tp"], "본문"
        elif tpct is not None:
            pv, src = round(e["tp"] / (1 + tpct / 100)), "본문"
        elif arch_ok:
            r_ = e["tp"] / e["prev"] - 1
            if (word == "상향" and r_ < -0.004) or (word == "하향" and r_ > 0.004) or (word == "유지" and abs(r_) > 0.004):
                pv = None                  # 기록과 본문 방향이 어긋남 → 본문 단어만 씀
            else:
                pv, src = e["prev"], "기록"
        if pv:
            r_ = e["tp"] / pv - 1
            e["pct"] = round(r_ * 100, 1)
            e["ch"] = "상향" if r_ > 0.004 else "하향" if r_ < -0.004 else "유지"
            if src == "본문" and not (e["prev"] and abs(pv - e["prev"]) <= 1):
                e["prevdate"] = None
            e["prev"] = pv
        else:
            e["pct"] = None
            if word in ("상향", "하향", "유지"):
                e["ch"] = word
            elif e["prev"]:
                e["ch"] = "확인 필요"
            else:
                e["ch"] = "신규" if (e["opch"] == "신규" or word == "신규") else "첫 기록"
        e["opmove"] = None
        if e["prevop"] and e["op"] and e["prevop"] != e["op"] and gap <= 200:
            e["opmove"] = "상향" if RANK[e["op"]] > RANK[e["prevop"]] else "하향"
        elif e["opch"] in ("상향", "하향") and not e["prevop"] and not e.get("multi"):
            e["opmove"] = e["opch"]
        last[(e["name"], e["broker"])] = e
    for e in ev:
        e.pop("text", None)
    return ev


# ---------------------------------------------------------------- 원문 링크 (네이버 금융 리서치 — 주소만 만들고 수집하지 않음)
NV = "https://finance.naver.com/research/"
MACRO_PAGE = {"금리·채권": "debenture_list.naver", "증시 전략·시황": "invest_list.naver", "자산배분·퀀트·ETF": "invest_list.naver"}


def link(k, code, ind, broker):
    if k in ("종목", "IR") and code:
        return f"{NV}company_list.naver?searchType=itemCode&itemCode={code}"
    if k == "산업":
        return NV + "industry_list.naver"
    if k == "매크로" and broker and not re.search(r"은행|선물|뱅크", broker):
        return NV + MACRO_PAGE.get(ind, "economy_list.naver")
    return None


def short_author(a):
    a = re.sub(r"\([^)]*\)", "", a or "")
    a = re.sub(r"Analyst|애널리스트|연구원|RA|Research Associate|외\s*\d+\s*인|,\s*$", " ", a)
    return re.sub(r"\s+", " ", a).strip(" ,/")[:40]


def mentions(r):
    txt = " ".join([r["title"]] + r["tags"] + [b for s in r["secs"] for b in s["b"]] + [s["h"] for s in r["secs"]])
    found = set()
    for m in P.NAME_RE.finditer(txt):
        n = m.group(1) or m.group(2)
        if n and n in P.STOCK and not P.find_broker(n):
            found.add(n)
    if r["subj"] and r["kind"] in ("종목", "IR"):
        found.add(r["subj"])
    found |= {m["name"] for m in r["multi"]}
    return found


def score(x, tags=""):
    s, why = 0.0, []
    if x["opm"] in ("상향", "하향"):
        s += 4; why.append("투자의견 " + x["opm"])
    if x["pct"] is not None and abs(x["pct"]) >= 15:
        s += 3; why.append(f"목표가 {x['pct']:+.0f}%")
    elif x["pct"] is not None and abs(x["pct"]) >= 8:
        s += 1.5; why.append(f"목표가 {x['pct']:+.0f}%")
    if x["ch"] == "신규":
        s += 2; why.append("신규 커버리지")
    if x["k"] == "산업" and len(x["multi"]) >= 3:
        s += 2.5; why.append(f"산업 리포트 · 종목 {len(x['multi'])}개 의견")
    if re.search(r"2027|2028|연간\s*전망|Outlook|하반기\s*전망|산업전망", x["t"] + tags):
        s += 2.5; why.append("연간 전망")
    if x["k"] == "매크로" and x["ind"] in ("통화정책", "경제지표"):
        s += 1
    if x["up"] is not None and x["up"] >= 60:
        s += 1
    if x["k"] == "IR":
        s -= 5
    if DAILY_RE.search(x["t"] + tags):
        s -= 3
    return s, why


# ---------------------------------------------------------------- 메인 빌드
def build(U, rw=None, today=None):
    """U: parse_all 결과(전체 기록). rw: {글번호: 우리 말 정리}. 반환: (공개 data, 내부 ctx)"""
    rw = rw if rw is not None else C.load_rw()
    now = C.kst_now()
    today = today or now.date()
    w0 = (today - dt.timedelta(days=C.WINDOW_DAYS - 1)).isoformat()
    w1 = today.isoformat()
    wk0 = (today - dt.timedelta(days=6)).isoformat()                 # 이번 주(최근 7일)
    pw0, pw1 = (today - dt.timedelta(days=13)).isoformat(), (today - dt.timedelta(days=7)).isoformat()
    close, mcap, px_asof = prices()
    ev = events(U)
    by_src = collections.defaultdict(list)
    for e in ev:
        by_src[e["src"]].append(e)

    Wr = [r for r in U if w0 <= day(r) <= w1]
    REC, INT = [], {}                 # 공개 레코드 / 내부(글번호 → 레코드·채널 글)
    for r in Wr:
        code = code_of(r["subj"]) if r["subj"] else None
        e = next((x for x in by_src.get(r["id"], []) if x["name"] == r["subj"]), None) if r["kind"] == "종목" else None
        px = close.get(code) if code else None
        up = round((r["tp"]["v"] / px - 1) * 100, 1) if (px and r["tp"] and r["tp"]["u"] == "원") else None
        multi = []
        for m in r["multi"]:
            e2 = next((x for x in by_src.get(r["id"], []) if x["name"] == m["name"]), None)
            multi.append(dict(s=m["name"], op=m["op"], tp=m["tp"]["v"] if m["tp"] else None, ch=e2["ch"] if e2 else None, pct=e2["pct"] if e2 else None))
        x = dict(id=C.pub_id(r["id"]), d=r["date"][:16].replace("T", " "), rd=r["rdate"], k=r["kind"], s=r["subj"] or r["fsubj"], c=code,
                 ind=r["ind"], b=r["broker"] or "", au=short_author(r["author"]), t=r["title"], tg=[],
                 op=r["op"], tp=(r["tp"]["v"] if r["tp"] else None), tpu=(r["tp"]["u"] if r["tp"] else None),
                 ch=e["ch"] if e else None, prev=e["prev"] if e else None, pct=e["pct"] if e else None, prevd=e["prevdate"] if e else None,
                 opm=e["opmove"] if e else (r["opch"] if r["opch"] in ("상향", "하향") and not r["multi"] and r["kind"] != "산업" else None),
                 prevop=e["prevop"] if e else None, up=up, px=px, multi=multi, m=sorted(mentions(r))[:12],
                 ln=link(r["kind"], code, r["ind"], r["broker"]), rw=rw.get(r["id"]))
        REC.append(x)
        INT[r["id"]] = dict(pub=x, raw=r)
    pub_of = {k: v["pub"]["id"] for k, v in INT.items()}

    # 종목 집계 — 현재 목표가 = 증권사별 최근 120일 안 마지막 값
    cut = (today - dt.timedelta(days=120)).isoformat()
    latest = {}
    for e in ev:
        if e["date"][:10] >= cut:
            latest[(e["name"], e["broker"])] = e
    by_name = collections.defaultdict(list)
    for x in REC:
        if x["k"] == "종목" and x["s"] and x["c"]:
            by_name[x["s"]].append(x)
    for x in REC:
        for m in x["multi"]:
            by_name.setdefault(m["s"], [])
    ev_by_name = collections.defaultdict(list)
    h0 = (today - dt.timedelta(days=180)).isoformat()
    for e in ev:
        if e["date"][:10] >= h0:
            ev_by_name[e["name"]].append(e)
    STK = {}
    for n, rs in by_name.items():
        if n not in P.STOCK:
            continue
        code = code_of(n)
        cons = sorted([dict(b=e["broker"], tp=e["tp"], op=e["op"], d=e["date"][:10], ch=e["ch"], pct=e["pct"], prev=e["prev"])
                       for (nm, b), e in latest.items() if nm == n], key=lambda z: z["d"], reverse=True)
        tps = [z["tp"] for z in cons]
        w_ev = [e for e in ev_by_name.get(n, []) if w0 <= e["date"][:10] <= w1]
        px = close.get(code)
        STK[n] = dict(c=code, ind=ind_of(n, rs[0]["ind"] if rs else None), mk=P.STOCK[n][1], px=px, mc=mcap.get(code), n=len(rs),
                      ids=[x["id"] for x in rs], nb=len({x["b"] for x in rs}), cons=cons[:25],
                      avg=round(sum(tps) / len(tps)) if tps else None, hi=max(tps) if tps else None, lo=min(tps) if tps else None,
                      up_avg=round((sum(tps) / len(tps) / px - 1) * 100, 1) if (tps and px) else None,
                      nup=sum(e["ch"] == "상향" for e in w_ev), ndn=sum(e["ch"] == "하향" for e in w_ev),
                      nopup=sum(e["opmove"] == "상향" for e in w_ev), nopdn=sum(e["opmove"] == "하향" for e in w_ev),
                      last=max((x["d"] for x in rs), default=None),
                      hist=[[e["date"][:10], e["broker"], e["tp"]] for e in ev_by_name.get(n, [])][-120:] if len(rs) >= 2 else [])

    # 많이 언급 (최근 7일 vs 그 전 7일)
    ment, ment_p = collections.Counter(), collections.Counter()
    for x in REC:
        dd = x["d"][:10]
        (ment if dd >= wk0 else ment_p if pw0 <= dd <= pw1 else collections.Counter()).update(x["m"])
    HOT = [dict(s=n, n=c, prev=ment_p.get(n, 0), c=code_of(n), ind=(STK.get(n) or {}).get("ind") or ind_of(n)) for n, c in ment.most_common(60)]
    ind_n = collections.Counter(x["ind"] for x in REC if x["k"] in ("종목", "산업") and x["d"][:10] >= wk0 and x["ind"])
    ind_p = collections.Counter(x["ind"] for x in REC if x["k"] in ("종목", "산업") and pw0 <= x["d"][:10] <= pw1 and x["ind"])
    HOTIND = [dict(s=k, n=v, prev=ind_p.get(k, 0)) for k, v in ind_n.most_common() if k != "기타"]

    # 날짜별 통계
    DAYS = collections.OrderedDict()
    for x in sorted(REC, key=lambda z: z["d"]):
        D = DAYS.setdefault(x["d"][:10], dict(n=0, kind=collections.Counter(), br=collections.Counter(), up=0, dn=0, opup=0, opdn=0, new=0))
        D["n"] += 1
        D["kind"][x["k"]] += 1
        if x["b"]:
            D["br"][x["b"]] += 1
    for e in ev:
        D = DAYS.get(e["date"][:10])
        if D:
            D["up"] += e["ch"] == "상향"; D["dn"] += e["ch"] == "하향"
            D["opup"] += e["opmove"] == "상향"; D["opdn"] += e["opmove"] == "하향"; D["new"] += e["ch"] == "신규"
    for D in DAYS.values():
        D["kind"] = dict(D["kind"]); D["br"] = D["br"].most_common(8); D["nb"] = len(D["br"])

    # 목표가·의견 변화 목록
    TPCH = []
    for e in ev:
        if w0 <= e["date"][:10] <= w1 and (e["ch"] in ("상향", "하향", "신규") or e["opmove"]) and e["src"] in pub_of:
            code = code_of(e["name"]); px = close.get(code)
            TPCH.append(dict(d=e["date"][:10], s=e["name"], c=code, b=e["broker"], tp=e["tp"], prev=e["prev"], pct=e["pct"], ch=e["ch"],
                             op=e["op"], prevop=e["prevop"], opm=e["opmove"], id=pub_of[e["src"]], prevd=e["prevdate"],
                             up=round((e["tp"] / px - 1) * 100, 1) if px else None, ind=(STK.get(e["name"]) or {}).get("ind")))

    data = dict(built=now.strftime("%Y-%m-%d %H:%M"), px_asof=px_asof, w0=w0, w1=w1, wk0=wk0, n_all=len(U), recs=REC, stk=STK, hot=HOT,
                hotind=HOTIND, days=DAYS, tpch=TPCH, public=True, sched=["10:00", "20:40"])
    ctx = dict(INT=INT, pub_of=pub_of, ev=ev, w0=w0, w1=w1, wk0=wk0, STK=STK, DAYS=DAYS, IND_N=ind_n)
    return data, ctx


# ---------------------------------------------------------------- Claude 해석 → 공개 ai.json
def ai_public(ctx):
    pub_of = ctx["pub_of"]
    days = {}
    for p in sorted((C.AI / "days").glob("*.json")) if (C.AI / "days").exists() else []:
        d = C.jload(p)
        if ctx["w0"] <= d["date"] <= ctx["w1"]:
            d = dict(d, must=[dict(m, id=pub_of[int(m["id"])]) for m in d.get("must", []) if int(m["id"]) in pub_of])
            days[d["date"]] = d
    stocks = {n: v for n, v in (C.jload(C.AI / "stocks.json", {}) or {}).items() if n in ctx["STK"] and v.get("date", "") >= ctx["w0"]}

    def remap(grp):
        out = {}
        for k, v in (grp or {}).items():
            out[k] = dict(v, ids=[pub_of[int(i)] for i in v.get("ids", []) if int(i) in pub_of])
        return out
    ind = C.jload(C.AI / "industry.json", {}) or {}
    mac = C.jload(C.AI / "macro.json", {}) or {}
    return dict(days=days, stocks=stocks, industry=remap(ind.get("items")), ind_at=ind.get("at"),
                macro=dict(week=mac.get("week"), topics=remap(mac.get("topics")), at=mac.get("at")))


def write_public(data, ctx):
    C.jsave(C.OUT / "data.json", data, compact=True)
    C.jsave(C.OUT / "ai.json", ai_public(ctx), compact=True)
    n_rw = sum(1 for x in data["recs"] if x["rw"])
    print(f"[build] 공개 데이터: 리포트 {len(data['recs'])}건 (우리 말 정리 {n_rw}건) · {data['w0']}~{data['w1']} · "
          f"data.json {(C.OUT / 'data.json').stat().st_size // 1024}KB")
