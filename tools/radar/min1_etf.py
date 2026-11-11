"""KODEX 200·KODEX 인버스 1분봉 쌓기 — 장중 전략(ORB 등) 재검증용 (내 PC 전용, 사이트에 안 올림)

키움 REST 주식분봉차트(ka10080, 1분, 수정주가)는 약 1년치만 준다 → 매일 새 봉을 덧붙여 2~3년치를 만든다.

- 처음: 키움이 주는 과거 전부 (종목당 약 106쪽 · 40초 안팎)
- 그 뒤: 저장된 마지막 3거래일부터 다시 받아 덧붙임 (겹치는 봉은 새 값으로 — 장중에 받은 미완성 봉도 이때 고쳐짐)
- 수정주가가 바뀌면(분배금·분할 등) 겹치는 봉의 비율로 키움이 더는 안 주는 예전 봉까지 맞춤.
  고치기 전 파일은 OUT/{코드}.prev.csv 로 한 벌 남김. 보정 기록은 index.json 의 adj.
- 가격: KRX(코드 그대로 — ORB 백테스트 data/와 같은 값), 수정주가, 키움이 주는 봉 전부
  (09:00~15:19 · 15:30 종가 단일가 · 15:35 장후 시간외. 봉 시각 = 시작 시각)
- 저장: OUT/{코드}.csv (dt,o,h,l,c,v · dt = YYYYMMDDhhmm) · OUT/index.json (종목별 기간·봉 수·마지막 받은 시각·보정 기록)
- 키는 kiwoom.py 가 Windows 자격 증명 관리자 'kiwoom-real' 등에서 읽는다(값은 출력·저장하지 않음).

python min1_etf.py                  # 기본 OUT = radar-out/min1 · 보통은 레이더가 거래일 16:10 에 부름 (radar.bat min1 = 손으로 한 번)
python min1_etf.py OUT --codes 069500
python min1_etf.py OUT --refetch    # 키움이 주는 범위를 전부 다시 받기 (예전 봉은 지우지 않고 비율만 맞춤)
"""
import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kiwoom import Kiwoom, KiwoomError, num  # noqa: E402

CODES = {"069500": "KODEX 200", "114800": "KODEX 인버스"}
OUT = HERE.parents[1] / "radar-out" / "min1"
DONE_AT = "16:05"          # 이 시각 뒤에 받은 날은 다 찬 날로 봄 (장후 시간외 15:40 끝)
OVERLAP_DAYS = 3           # 덧붙일 때 겹쳐 받는 거래일 수 (마지막 날 제외)
ADJ_TOL = 2e-4             # 겹치는 봉 종가 비율이 이보다 벗어나면 수정주가가 바뀐 것으로 봄 (값이 같으면 정확히 1.0)
HEAD = ["dt", "o", "h", "l", "c", "v"]


def kst():
    return (datetime.now(timezone.utc) + timedelta(hours=9)).replace(tzinfo=None)


def _int(x):
    return int(x) if isinstance(x, float) and x == int(x) else x


# ====================================================================== 키움
def fetch(k, code, stop_before=None, max_pages=400):
    """1분봉을 최신부터 거꾸로. stop_before('YYYYMMDDhhmm')보다 오래된 봉이 나오면 멈춤 → {'YYYYMMDDhhmm': [o,h,l,c,v]}"""
    bars, cont, pages = {}, None, 0
    while True:
        d, cont = k.call("ka10080", "/api/dostk/chart", {"stk_cd": code, "tic_scope": "1", "upd_stkpc_tp": "1"}, cont)
        rows = d.get("stk_min_pole_chart_qry") or []
        pages += 1
        for r in rows:
            t = str(r.get("cntr_tm") or "")[:12]
            if len(t) < 12 or not t.isdigit():
                continue
            o, h, l, c = (num(r.get(x), True) for x in ("open_pric", "high_pric", "low_pric", "cur_prc"))
            if not (o and h and l and c):
                continue
            bars[t] = [_int(o), _int(h), _int(l), _int(c), int(num(r.get("trde_qty"), True) or 0)]
        oldest = min((str(r.get("cntr_tm"))[:12] for r in rows), default=None)
        if not cont or not rows or (stop_before and oldest and oldest < stop_before) or pages >= max_pages:
            return bars


# ====================================================================== 파일
def read_csv(f):
    if not f.exists():
        return {}
    out = {}
    with open(f, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["dt"]] = [_int(float(row[x])) for x in ("o", "h", "l", "c")] + [int(float(row["v"]))]
    return out


def write_csv(f, bars):
    tmp = f.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEAD)
        for t in sorted(bars):
            w.writerow([t] + bars[t])
    tmp.replace(f)


def read_index(out):
    try:
        return json.loads((Path(out) / "index.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def write_index(out, idx):
    f = Path(out) / "index.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def last_complete(out=OUT, codes=CODES):
    """모든 종목이 다 받아 둔 마지막 날 'YYYYMMDD' (없으면 '') — 장 끝나기 전에 받은 마지막 날은 덜 찬 날로 침"""
    info = read_index(out).get("codes", {})
    days = []
    for c in codes:
        u = info.get(c)
        if not u or not u.get("t"):
            return ""
        d = u["t"][:8]
        got = (u.get("u") or "").replace("-", "")                   # 'YYYYMMDD HH:MM'
        if not (got[:8] > d or got[9:] >= DONE_AT):
            d = (datetime.strptime(d, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        days.append(d)
    return min(days)


# ====================================================================== 덧붙이기 · 보정
def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def ratios(new, old, skip_day=None):
    """겹치는 봉의 (종가 비율, 거래량 비율, 겹친 봉 수) — skip_day(그날 장중에 받았을 수 있는 날)는 뺌"""
    ov = [t for t in new if t in old and t[:8] != skip_day]
    pr = _median([new[t][3] / old[t][3] for t in ov if old[t][3]])
    vr = _median([new[t][4] / old[t][4] for t in ov if old[t][4] and new[t][4]])
    return pr, vr, len(ov)


def update(k, code, out, refetch=False, log=print):
    """한 종목 받기/덧붙이기 → (index 항목, 새 봉 수, 메모)"""
    f = Path(out) / f"{code}.csv"
    old = read_csv(f)
    adj = None
    if not old:
        new = fetch(k, code)
        if not new:
            raise KiwoomError(f"{code}: 키움이 1분봉을 주지 않음")
        merged, note = new, f"처음 — 키움이 주는 과거 전부 ({min(new)[:8]}~)"
    else:
        days = sorted({t[:8] for t in old})
        lastday = days[-1]
        pr = vr = None
        if not refetch:
            start = days[-1 - OVERLAP_DAYS] if len(days) > OVERLAP_DAYS else days[0]
            new = fetch(k, code, stop_before=start + "0000")
            if not new:
                raise KiwoomError(f"{code}: 키움이 1분봉을 주지 않음")
            pr, vr, n_ov = ratios(new, old, skip_day=lastday)
            if pr is None:
                log(f"  {code} 겹치는 봉이 없음 ({n_ov}) — 전부 다시 받아 맞춤")
        if refetch or pr is None or abs(pr - 1) > ADJ_TOL:
            # 수정주가가 바뀜(또는 다시 받기) → 키움이 주는 범위를 전부 다시 받고, 그 밖의 예전 봉은 겹치는 봉 비율로 맞춤
            new = fetch(k, code)
            if not new:
                raise KiwoomError(f"{code}: 키움이 1분봉을 주지 않음")
            pr, vr, n_ov = ratios(new, old, skip_day=lastday)
            gap = pr is None                                         # 너무 오래 안 받아 키움 범위와 안 겹침 → 보정 없이 이어 붙임
            pr = 1.0 if gap or abs(pr - 1) <= ADJ_TOL else pr
            vr = vr if vr is not None and abs(vr - 1) > 1e-3 else 1.0
            merged = {t: ([round(x * pr) for x in v[:4]] + [round(v[4] * vr)]) if (pr != 1 or vr != 1) else v
                      for t, v in old.items() if t not in new}       # 키움이 안 주는 봉은 예전 값을 비율로 맞춰 남김
            merged.update(new)
            if gap:
                adj = {"at": kst().strftime("%Y-%m-%d %H:%M"), "gap": True, "kept_before": min(new)}
                note = f"겹치는 봉 없음 — {lastday} 뒤 빈 기간이 있고 예전 봉은 보정 없이 이어 붙임 (수정주가 차이가 있을 수 있음)"
            elif pr != 1 or vr != 1:
                shutil.copyfile(f, f.with_suffix(".prev.csv"))
                adj = {"at": kst().strftime("%Y-%m-%d %H:%M"), "price": round(pr, 6), "vol": round(vr, 6), "overlap": n_ov,
                       "kept_before": min(new)}
                note = f"수정주가 조정 — 예전 봉 가격 ×{pr:.5f} · 거래량 ×{vr:.4f} (겹친 봉 {n_ov}개, 전 파일은 {code}.prev.csv)"
            else:
                note = "다시 받기 — 값 변화 없음"
        else:
            merged = dict(old)
            merged.update(new)
            note = ""
    if len(merged) < len(old):                                       # 안전장치: 쌓아 둔 봉이 줄면 저장 안 함
        raise KiwoomError(f"{code}: 합친 봉({len(merged)})이 저장된 봉({len(old)})보다 적어 저장하지 않음")
    write_csv(f, merged)
    nnew = len(set(merged) - set(old))
    days = sorted({t[:8] for t in merged})
    it = {"name": CODES.get(code, code), "f": min(merged), "t": max(merged), "days": len(days), "bars": len(merged),
          "u": kst().strftime("%Y-%m-%d %H:%M")}
    return it, nnew, note, adj


def collect(out=OUT, codes=None, refetch=False, log=print):
    """전 종목 받기 → 실패한 코드 목록. index.json 갱신"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    codes = list(codes or CODES)
    idx = read_index(out)
    idx.setdefault("about", "KODEX 200·인버스 1분봉 (키움 ka10080, KRX, 수정주가) — tools/radar/min1_etf.py · 내 PC 전용")
    info = idx.setdefault("codes", {})
    k, fails, t0 = Kiwoom(), [], time.time()
    for code in codes:
        for attempt in (1, 2):
            try:
                it, nnew, note, adj = update(k, code, out, refetch, log)
                prev = info.get(code, {})
                it["adj"] = prev.get("adj", []) + ([adj] if adj else [])
                info[code] = it
                write_index(out, idx)
                log(f"1분봉 {code} {it['name']}: +{nnew}봉 · 전체 {it['bars']:,}봉 {it['days']}일 "
                    f"({it['f'][:8]}~{it['t'][:8]} {it['t'][8:]}){' · ' + note if note else ''}")
                break
            except (KiwoomError, OSError) as e:
                if attempt == 2:
                    fails.append(code)
                    log(f"1분봉 {code} 실패: {e}"[:300])
                else:
                    time.sleep(3)
    log(f"1분봉 저장 끝 — {len(codes) - len(fails)}/{len(codes)}종목 · {time.time() - t0:.0f}초 · {out}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(OUT))
    ap.add_argument("--codes", default="")
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    codes = [c.strip() for c in a.codes.split(",") if c.strip()] or None
    try:
        fails = collect(a.out, codes, a.refetch, log=lambda s: print(s, flush=True))
    except KiwoomError as e:                                         # 키 없음·토큰 실패 등
        print(f"1분봉 저장 실패: {e}")
        sys.exit(1)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
