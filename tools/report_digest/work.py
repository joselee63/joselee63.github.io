"""Claude 예약 작업용 입력 만들기(prepare) · 결과 합치기(merge)

work/                          (실행마다 새로 만듦, 비공개 — 채널 요약 원문이 들어 있음)
  todo.json                    할 일 목록
  rw_in/partN.txt → rw_out/partN.json      리포트별 우리 말 정리
  day_YYYY-MM-DD.txt → out/day_YYYY-MM-DD.json   그날 요약·꼭 볼 리포트
  stocks.txt → out/stocks.json             종목별 증권사 의견 합치기
  industry.txt → out/industry.json · macro.txt → out/macro.json   (하루 한 번, 20:40 실행)
"""
import collections
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402

RW_CAP = 240          # 한 번에 새로 정리할 리포트 수 (넘치면 최신부터, 나머지는 다음 실행)
RW_BATCH = 60
STOCK_CAP = 8


def _fact(x):
    f = f"종류={x['k']} | 대상={x['s'] or '-'} | 산업/주제={x['ind'] or '-'} | 증권사={x['b'] or '-'} | 제목={x['t']}"
    if x["op"]:
        f += f" | 의견={x['op']}"
    if x["tp"]:
        f += f" | 목표가={x['tp']:,.0f}{x['tpu'] or ''}"
    if x["ch"] in ("상향", "하향") and x["pct"] is not None:
        f += f" | 목표가변화={x['ch']} {x['pct']:+.1f}% (직전 {x['prev']:,.0f})"
    elif x["ch"]:
        f += f" | 목표가변화={x['ch']}"
    if x["opm"]:
        f += f" | 의견변화={x['prevop'] or '?'}→{x['op']}"
    if x["up"] is not None:
        f += f" | 종가대비 상승여력={x['up']:+.1f}%"
    return f


def _line(i, x, raw, nb=0, cut=160):
    head = f"#{i} [{x['k']}{'/' + x['ind'] if x['ind'] else ''}] {x['s'] or '-'} | {x['t']} | {x['b']}"
    if x["op"] or x["tp"]:
        head += f" | 의견 {x['op'] or '-'}"
        if x["tp"]:
            head += f" TP {x['tp']:,.0f}{x['tpu'] or ''}"
            if x["ch"] in ("상향", "하향") and x["pct"] is not None:
                head += f" ({x['ch']} {x['pct']:+.1f}%, 직전 {x['prev']:,.0f})"
            elif x["ch"]:
                head += f" ({x['ch']})"
        if x["opm"]:
            head += f" [의견 {x['opm']}: {x['prevop'] or '?'}→{x['op']}]"
        if x["up"] is not None:
            head += f" 상승여력 {x['up']:+.0f}%"
    if x["multi"]:
        head += " | 종목별: " + ", ".join(f"{m['s']}({m['op'] or '-'}/{(m['tp'] or 0):,.0f}{'/' + m['ch'] if m['ch'] in ('상향', '하향') else ''})" for m in x["multi"][:8])
    pts = [b for s in raw["secs"] for b in s["b"]][:nb]
    return head + ("\n    · " + "\n    · ".join(p[:cut] for p in pts) if pts else "")


def prepare(data, ctx, force_week=False):
    """할 일 정해서 work/ 에 입력 파일 쓰기. 반환: todo dict"""
    import build as B
    if C.WORK.exists():
        shutil.rmtree(C.WORK)
    for d in (C.WORK, C.WORK / "rw_in", C.WORK / "rw_out", C.WORK / "out"):
        d.mkdir(parents=True, exist_ok=True)
    INT = ctx["INT"]
    now = C.kst_now()
    todo = dict(at=now.isoformat(timespec="seconds"), rw=[], days=[], stocks=[], industry=False, macro=False)

    # 1) 우리 말 정리가 없는 리포트 (최신부터)
    need = [i for i, v in INT.items() if not v["pub"]["rw"] and v["pub"]["k"] != "IR"]
    need.sort(reverse=True)
    need = need[:RW_CAP]
    for n in range(0, len(need), RW_BATCH):
        part = sorted(need[n:n + RW_BATCH])
        name = f"part{n // RW_BATCH + 1}"
        with open(C.WORK / "rw_in" / f"{name}.txt", "w", encoding="utf-8") as f:
            for i in part:
                f.write(f"==== #{i}\n[사실] {_fact(INT[i]['pub'])}\n[채널 요약 원문]\n{INT[i]['raw']['text'].strip()}\n\n")
        todo["rw"].append(dict(name=name, n=len(part)))

    # 2) 그날 요약 — 오늘·어제 중 새 리포트가 붙은 날 (이미 쓴 요약보다 리포트가 10% 이상 늘었으면 다시)
    for d in sorted(ctx["DAYS"])[-2:]:
        D = ctx["DAYS"][d]
        old = C.jload(C.AI / "days" / f"{d}.json")
        if D["n"] < 3 or (old and old.get("n_at", 0) >= D["n"] * 0.9):
            continue
        xs = [(i, v["pub"], v["raw"]) for i, v in INT.items() if v["pub"]["d"][:10] == d]
        sc = sorted(((B.score(p, " ".join(raw["tags"]))[0], B.score(p, " ".join(raw["tags"]))[1], i) for i, p, raw in xs), reverse=True)
        with open(C.WORK / f"day_{d}.txt", "w", encoding="utf-8") as f:
            f.write(f"# {d} 리포트 {D['n']}건 · 종류 {D['kind']} · 목표가 상향 {D['up']} 하향 {D['dn']} · 의견 상향 {D['opup']} 하향 {D['opdn']}\n")
            f.write("## 점수 높은 후보 (규칙 점수 순, 위 25개)\n")
            for s, why, i in sc[:25]:
                f.write(f"[점수 {s:.1f} {'/'.join(why)}] " + _line(i, INT[i]["pub"], INT[i]["raw"], 5, 200) + "\n")
            f.write("\n## 그날 전체 (종류별)\n")
            for k in ("종목", "산업", "매크로", "해외종목"):
                f.write(f"\n### {k}\n")
                for i, p, raw in xs:
                    if p["k"] == k:
                        f.write(_line(i, p, raw) + "\n")
        todo["days"].append(dict(date=d, n=D["n"]))

    # 3) 종목 의견 합치기 — 최근 7일 리포트 3건 이상 + 지난번 해석 뒤 새 리포트가 붙은 종목, 최근 2일 리포트 많은 순
    sto = C.jload(C.AI / "stocks.json", {}) or {}
    wk0 = ctx["wk0"]
    d2 = (now.date() - dt.timedelta(days=1)).isoformat()
    cand = []
    for n, v in ctx["STK"].items():
        ids = [i for i in INT if INT[i]["pub"]["k"] == "종목" and INT[i]["pub"]["s"] == n]
        n7 = sum(1 for i in ids if INT[i]["pub"]["d"][:10] >= wk0)
        n2 = sum(1 for i in ids if INT[i]["pub"]["d"][:10] >= d2)
        if n7 >= 3 and n2 >= 1 and sto.get(n, {}).get("n_at") != len(ids):
            cand.append((n2, n7, n, ids))
    cand.sort(reverse=True)
    if cand:
        with open(C.WORK / "stocks.txt", "w", encoding="utf-8") as f:
            for n2, n7, n, ids in cand[:STOCK_CAP]:
                v = ctx["STK"][n]
                f.write(f"\n==== {n} ({v['c']}, {v['ind']}) 최근 {C.WINDOW_DAYS}일 리포트 {len(ids)}건 · 증권사 {v['nb']}곳 · 종가 {v['px']}\n")
                f.write(f"현재 목표가(증권사별 최근값) 평균 {v['avg']} 최고 {v['hi']} 최저 {v['lo']} 평균 상승여력 {v['up_avg']}% · 기간 상향 {v['nup']} 하향 {v['ndn']}\n")
                for i in sorted(ids)[-25:]:
                    f.write(_line(i, INT[i]["pub"], INT[i]["raw"], 3, 170) + "\n")
                todo["stocks"].append(dict(name=n, n_at=len(ids)))

    # 4) 산업·매크로 — 하루 한 번(20시 이후 실행) 또는 하루 넘게 안 썼으면
    def stale(p):
        a = (C.jload(p, {}) or {}).get("at")
        return not a or (now - dt.datetime.fromisoformat(a)).total_seconds() > 20 * 3600
    if force_week or now.hour >= 20 or stale(C.AI / "industry.json"):
        with open(C.WORK / "industry.txt", "w", encoding="utf-8") as f:
            f.write(f"# 최근 1주 ({wk0} ~ {ctx['w1']}) 산업 리포트와 종목 리포트\n")
            for ind, _ in ctx["IND_N"].most_common(12):
                if ind == "기타":
                    continue
                xs = [(i, v) for i, v in INT.items() if v["pub"]["d"][:10] >= wk0 and v["pub"]["ind"] == ind and v["pub"]["k"] == "산업"]
                st = [v["pub"] for i, v in INT.items() if v["pub"]["d"][:10] >= wk0 and v["pub"]["ind"] == ind and v["pub"]["k"] == "종목"]
                up = sum(1 for x in st if x["ch"] == "상향"); dn = sum(1 for x in st if x["ch"] == "하향")
                f.write(f"\n==== 산업: {ind} · 산업 리포트 {len(xs)}건 · 종목 리포트 {len(st)}건 (목표가 상향 {up} 하향 {dn})\n")
                for i, v in xs[:24]:
                    f.write(_line(i, v["pub"], v["raw"], 3, 160) + "\n")
                f.write("  [종목 리포트 제목들] " + " / ".join(f"{x['s']}:{x['t'][:40]}({x['ch'] or '-'})" for x in st[:30]) + "\n")
        todo["industry"] = True
    if force_week or now.hour >= 20 or stale(C.AI / "macro.json"):
        with open(C.WORK / "macro.txt", "w", encoding="utf-8") as f:
            f.write(f"# 최근 1주 ({wk0} ~ {ctx['w1']}) 매크로 리포트\n")
            for topic in ("통화정책", "금리·채권", "환율·외환", "경제지표", "증시 전략·시황", "원자재·유가", "자산배분·퀀트·ETF"):
                xs = [(i, v) for i, v in INT.items() if v["pub"]["d"][:10] >= wk0 and v["pub"]["k"] == "매크로" and v["pub"]["ind"] == topic]
                nd = [(i, v) for i, v in xs if not re.search(r"Daily|데일리|Forex|모닝|Morning|아침", v["pub"]["t"], re.I)] or xs
                f.write(f"\n==== 매크로: {topic} · {len(xs)}건\n")
                for i, v in nd[-22:]:
                    f.write(_line(i, v["pub"], v["raw"], 3, 160) + "\n")
        todo["macro"] = True
    # 5) 서브에이전트 지시문 (경로·개수 채움) → work/tasks/*.md — 예약 작업이 이 파일 내용을 그대로 하나씩 맡김
    T = C.WORK / "tasks"
    T.mkdir(exist_ok=True)
    P = Path(__file__).parent / "prompts"

    def task(name, tmpl, **kw):
        s = (P / tmpl).read_text(encoding="utf-8")
        for k, v in kw.items():
            s = s.replace("{" + k + "}", str(v))
        (T / f"{name}.md").write_text(s, encoding="utf-8")
    for x in todo["rw"]:
        task(f"rw_{x['name']}", "rewrite.md", IN=C.WORK / "rw_in" / f"{x['name']}.txt", OUT=C.WORK / "rw_out" / f"{x['name']}.json", N=x["n"])
    for x in todo["days"]:
        task(f"day_{x['date']}", "day.md", IN=C.WORK / f"day_{x['date']}.txt", OUT=C.WORK / "out" / f"day_{x['date']}.json", DATE=x["date"])
    if todo["stocks"]:
        task("stocks", "stocks.md", IN=C.WORK / "stocks.txt", OUT=C.WORK / "out" / "stocks.json", NAMES=", ".join(x["name"] for x in todo["stocks"]))
    if todo["industry"]:
        task("industry", "week.md", WHAT="산업별 모아 보기", WHAT_BY="산업별로", IN=C.WORK / "industry.txt", OUT=C.WORK / "out" / "industry.json")
    if todo["macro"]:
        task("macro", "week.md", WHAT="매크로(경제·금리·환율·시황) 모아 보기", WHAT_BY="매크로 주제별로", IN=C.WORK / "macro.txt", OUT=C.WORK / "out" / "macro.json")
    todo["tasks"] = sorted(p.name for p in T.glob("*.md"))
    C.jsave(C.WORK / "todo.json", todo)
    print(f"[prepare] 서브에이전트 지시문 {len(todo['tasks'])}개 → {T}")
    print(f"[prepare] 정리할 리포트 {sum(x['n'] for x in todo['rw'])}건 ({len(todo['rw'])}묶음, 남은 것 {len([i for i, v in INT.items() if not v['pub']['rw'] and v['pub']['k'] != 'IR']) - sum(x['n'] for x in todo['rw'])}건)"
          f" · 그날 요약 {[x['date'] for x in todo['days']]} · 종목 {[x['name'] for x in todo['stocks']]}"
          f" · 산업 {'O' if todo['industry'] else '-'} · 매크로 {'O' if todo['macro'] else '-'}")
    return todo


# ---------------------------------------------------------------- 점검 · 합치기
K = 8                                    # 채널 요약과 8어절 이상 연속 일치하면 '베낌'으로 보고 싣지 않음


def _norm(s):
    return re.sub(r"[^\w%.,]", " ", s).split()


def _grams(texts):
    g = set()
    for t in texts:
        w = _norm(t)
        g.update(tuple(w[i:i + K]) for i in range(len(w) - K + 1))
    return g


def _strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _copied(obj, grams):
    for s in _strings(obj):
        w = _norm(s)
        for i in range(len(w) - K + 1):
            if tuple(w[i:i + K]) in grams:
                return " ".join(w[i:i + K])
    return None


def merge(ctx):
    """work/ 결과를 비공개 저장소(rw.jsonl · ai/)에 합친다. 베낀 글은 버리고(다음 실행 때 다시 씀) 목록을 알린다"""
    INT = ctx["INT"]
    grams = _grams(v["raw"]["text"] for v in INT.values())
    have = C.load_rw()
    new, dropped, bad_json = {}, [], []
    for p in sorted((C.WORK / "rw_out").glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad_json.append(f"{p.name}: {e}"[:120]); continue
        for k, v in d.items():
            i = int(k)
            if i not in INT or not isinstance(v, dict) or not v.get("thesis"):
                continue
            hit = _copied(v, grams)
            if hit:
                dropped.append((i, hit)); continue
            new[i] = {f: v.get(f, "" if f in ("thesis", "est", "tp", "take") else []) for f in ("thesis", "numbers", "est", "tp", "risks", "take")}
    new = {k: v for k, v in new.items() if have.get(k) != v}
    if new:
        C.append_rw(new)
    (C.AI / "days").mkdir(parents=True, exist_ok=True)
    msgs = []
    for p in sorted((C.WORK / "out").glob("day_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad_json.append(f"{p.name}: {e}"[:120]); continue
        hit = _copied(d, grams)
        if hit:
            dropped.append((p.name, hit)); continue
        d["must"] = [m for m in d.get("must", []) if int(m["id"]) in INT]
        d["n_at"] = ctx["DAYS"].get(d["date"], {}).get("n", 0)
        d["at"] = C.kst_now().isoformat(timespec="seconds")
        C.jsave(C.AI / "days" / f"{d['date']}.json", d)
        msgs.append(f"요약 {d['date']}")
    todo = C.jload(C.WORK / "todo.json", {}) or {}
    p = C.WORK / "out" / "stocks.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            sto = C.jload(C.AI / "stocks.json", {}) or {}
            nat = {x["name"]: x["n_at"] for x in todo.get("stocks", [])}
            for n, v in d.items():
                hit = _copied(v, grams)
                if hit:
                    dropped.append((n, hit)); continue
                sto[n] = dict(v, date=ctx["w1"], n_at=nat.get(n), at=C.kst_now().isoformat(timespec="seconds"))
            C.jsave(C.AI / "stocks.json", sto)
            msgs.append(f"종목 {len(d)}개")
        except Exception as e:  # noqa: BLE001
            bad_json.append(f"stocks.json: {e}"[:120])
    for name in ("industry", "macro"):
        p = C.WORK / "out" / f"{name}.json"
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad_json.append(f"{name}.json: {e}"[:120]); continue
        hit = _copied(d, grams)
        if hit:
            dropped.append((name, hit)); continue
        if name == "industry":
            C.jsave(C.AI / "industry.json", dict(items=d, at=C.kst_now().isoformat(timespec="seconds")))
        else:
            C.jsave(C.AI / "macro.json", dict(d, at=C.kst_now().isoformat(timespec="seconds")))
        msgs.append(name)
    print(f"[merge] 우리 말 정리 {len(new)}건 저장 · {', '.join(msgs) or '해석 없음'}"
          + (f" · 베낌으로 버림 {len(dropped)}건 {dropped[:5]}" if dropped else "") + (f" · JSON 오류 {bad_json}" if bad_json else ""))
    return dict(rw=len(new), dropped=dropped, bad=bad_json)
