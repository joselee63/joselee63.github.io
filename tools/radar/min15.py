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
"""
import argparse
import json
import sys
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
    return obj, nnew, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--codes", default="")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--min-cap", type=float, default=10000, help="억 원 (기본 1조)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    k = Kiwoom()
    uni = universe(k, a.min_cap)
    info = {u["c"]: u for u in uni}
    idx_old = read_js(out / "index.js") or {}
    for u in idx_old.get("list", []):                       # 시총이 기준 아래로 내려간 종목도 계속 찾을 수 있게
        if u["c"] in info:
            info[u["c"]].update({x: u[x] for x in ("f", "t", "last", "nb") if x in u})
        else:
            info[u["c"]] = dict(u, below=True)
    codes = [c.strip() for c in a.codes.split(",") if c.strip()] or [u["c"] for u in uni]
    print(f"시총 {a.min_cap / 1e4:g}조 이상 {len(uni)}종목 · 이번에 받을 {len(codes)}종목", flush=True)

    t0, fails = time.time(), []
    for n, code in enumerate(codes, 1):
        try:
            obj, nnew, note = update(k, code, out, a.full)
        except KiwoomError as e:
            fails.append(code)
            print(f"[{n}/{len(codes)}] {code} 실패: {e}", flush=True)
            continue
        if not obj:
            fails.append(code)
            print(f"[{n}/{len(codes)}] {code} {note}", flush=True)
            continue
        u = info.setdefault(code, {"c": code, "n": code, "m": "", "cap": None, "s": ""})
        obj.update(name=u["n"], mk=u["m"])
        write_js(out / f"{code}.js", "W15", obj)
        u.update(f=obj["d"][0], t=obj["d"][-1], last=SLOTS[obj["b"][-1][1]], nb=len(obj["b"]))
        if n % 20 == 0 or note or n == len(codes):
            print(f"[{n}/{len(codes)}] {code} {u['n']} {len(obj['b'])}봉 (+{nnew}) {obj['d'][0]}~{obj['d'][-1]} {note}"
                  f" · {time.time() - t0:.0f}초", flush=True)

    have = {p.stem for p in out.glob("*.js") if p.stem != "index"}
    lst = sorted((u for c, u in info.items() if c in have), key=lambda u: -(u.get("cap") or 0))
    write_js(out / "index.js", "W15_INDEX", {"upd": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                             "min_cap": a.min_cap, "list": lst})
    print(f"끝 — {len(lst)}종목 저장 · 실패 {len(fails)}{' ' + ','.join(fails) if fails else ''} · {time.time() - t0:.0f}초")
    if fails:
        print("실패한 종목은 다시 실행하면 이어서 받습니다.")


if __name__ == "__main__":
    main()
