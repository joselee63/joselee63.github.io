"""시장 수급 — 코스피·코스닥 투자자별 순매수(외국인·기관·개인) · 프로그램 차익/비차익 순매수 · 지수 일봉
   키움 REST '통합(KRX+NXT)' 기준 일별 → 릴리스 flow-data/market.json → flow.yml 이 사이트 flow/market.json 으로

  · 키움 API (조회만): 업종별투자자순매수 ka10051(하루 1번 호출, 억 원) · 프로그램매매추이 일자별 ka90010(백만 원) · 업종일봉 ka20006
      거래소구분 3 = 통합(KRX+NXT), 2 = NXT만 → KRX만 = 통합 − NXT (페이지에서 세 기준 모두 볼 수 있게 NXT 몫도 저장)
      NXT 출범(2025-03-04) 전은 통합 = KRX (NXT 몫은 0으로 두고 조회하지 않음)
  · 외국인 = 외국인 + 기타외국인(내국인대우외국인) — KRX '외국인 합계', NXT 공식 통계와 같은 기준 (2026-11-10 NXT 사이트 숫자와 일치 확인)
  · 그날 값은 NXT 마감 확정(20:05) 뒤에만 넣음 · 최근 3거래일은 매번 다시 받아 덮어씀(사후 수정)
  · 저장: 내 PC radar-out/flow/market.json (캐시) — 없으면 릴리스에서 받아 이어 붙임
  · 실행: 레이더(radar.py)가 거래일 20:12 에 자동 · 직접: python tools/market/flow_kiwoom.py [--no-upload] [--start YYYYMMDD]
  · 키움 앱키는 Windows 자격 증명 관리자(레이더와 같은 'kiwoom-real')에서 읽음 — 이 파일은 키를 보거나 저장하지 않음
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "radar"))
import kiwoom as KW  # noqa: E402

REPO = "joselee63/joselee63.github.io"
RELEASE = "flow-data"
ASSET = "market.json"
CACHE = ROOT / "radar-out" / "flow" / ASSET
START = "20210104"                 # 처음 받을 때 시작일
NXT_START = "20250304"             # NXT 출범일
REFETCH = 3                        # 최근 N거래일은 매번 다시 받음
FINAL = dt.time(20, 5)             # NXT 확정 시각 — 그 전에는 오늘 값을 넣지 않음
MKT = {"kospi":  {"inv": "0", "ind": "001", "prog": ("P001_AL01", "P001_NX01")},
       "kosdaq": {"inv": "1", "ind": "101", "prog": ("P101_AL02", "P101_NX02")}}
KEYS = ("o", "h", "l", "c", "v",                 # 지수 시·고·저·종, 거래대금(억)
        "f", "i", "p", "ar", "na",               # 통합: 외국인 · 기관 · 개인 · 프로그램 차익 · 비차익 (억)
        "nf", "ni", "np", "nar", "nna")          # 그중 NXT 몫
_run_lock = threading.Lock()


def now():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).replace(tzinfo=None)


def num(s):
    """'+4,500' · '-111302' · '--1234' · '' → float 또는 None"""
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    while s[:2] in ("--", "+-", "-+"):
        s = "-" + s[2:]
    if s in ("", "-", "+"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def eok(v, div=1):
    return None if v is None else int(round(v / div))


# ---------------------------------------------------------------- 키움 조회
def pages(k, api_id, path, body, key, stop, max_pages=40, dkey="dt"):
    """연속 조회 — 가장 오래된 날짜가 stop 보다 앞이면 멈춤"""
    out, cont = [], None
    for _ in range(max_pages):
        d, cont = k.call(api_id, path, body, cont)
        rows = d.get(key) or []
        out += rows
        if not cont or not rows or str(rows[-1].get(dkey, ""))[:8] < stop:
            break
    return out


def program(k, mrkt_tp, stex, today, stop):
    """프로그램매매추이 일자별(ka90010) → {YYYYMMDD: (차익, 비차익)} 억 원"""
    rows = pages(k, "ka90010", "/api/dostk/mrkcond", {"date": today, "amt_qty_tp": "1", "mrkt_tp": mrkt_tp, "min_tic_tp": "0", "stex_tp": stex},
                 "prm_trde_trnsn", stop, dkey="cntr_tm")
    out = {}
    for r in rows:
        d = str(r.get("cntr_tm") or "")[:8]
        if len(d) == 8 and d >= stop:
            out[d] = (eok(num(r.get("dfrt_trde_netprps")), 100), eok(num(r.get("ndiffpro_trde_netprps")), 100))
    return out


def index_daily(k, inds_cd, today, stop):
    """업종일봉(ka20006) → {YYYYMMDD: (시, 고, 저, 종, 거래대금 억)}"""
    rows = pages(k, "ka20006", "/api/dostk/chart", {"inds_cd": inds_cd, "base_dt": today}, "inds_dt_pole_qry", stop)
    out = {}
    for r in rows:
        d = str(r.get("dt") or "")
        c = num(r.get("cur_prc"))
        if len(d) == 8 and d >= stop and c:
            px = [abs(num(r.get(x)) or c) / 100 for x in ("open_pric", "high_pric", "low_pric")] + [abs(c) / 100]
            out[d] = tuple(round(x, 2) for x in px) + (eok(num(r.get("trde_prica")), 100),)
    return out


def investor(k, mrkt_tp, ind, day, stex):
    """업종별투자자순매수(ka10051) 종합 행 → (외국인+기타외국인, 기관계, 개인) 억 원 · 없으면 None"""
    d, _ = k.call("ka10051", "/api/dostk/sect", {"mrkt_tp": mrkt_tp, "amt_qty_tp": "0", "base_dt": day, "stex_tp": stex})
    rows = d.get("inds_netprps") or []
    r = next((x for x in rows if str(x.get("inds_cd", "")).split("_")[0] == ind), None)
    if not r or (stex == "3" and not str(r.get("cur_prc") or "").strip()):
        return None
    f, nf = num(r.get("frgnr_netprps")), num(r.get("native_trmt_frgnr_netprps"))
    if f is None:
        return None
    return (eok(f + (nf or 0)), eok(num(r.get("orgn_netprps"))), eok(num(r.get("ind_netprps"))))


# ---------------------------------------------------------------- 저장 · 불러오기
def gh_path():
    g = shutil.which("gh")
    if g:
        return g
    for c in (r"C:\Program Files\GitHub CLI\gh.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe")):
        if os.path.exists(c):
            return c
    return None


def gh(*args, check=True):
    g = gh_path()
    if not g:
        raise RuntimeError("gh(GitHub CLI)가 없습니다")
    r = subprocess.run([g, *args, "-R", REPO], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} 실패: {(r.stderr or r.stdout).strip()[:200]}")
    return r


def to_rows(doc):
    """열 형식 JSON → {시장: {날짜: {키: 값}}}"""
    rows = {m: {} for m in MKT}
    if not doc:
        return rows
    for m in MKT:
        cols = doc.get(m) or {}
        for j, d in enumerate(doc.get("d") or []):
            rows[m][str(d)] = {x: cols[x][j] if j < len(cols.get(x) or []) else None for x in KEYS}
    return rows


def load(log):
    for src in ("cache", "release"):
        try:
            if src == "cache":
                if not CACHE.exists():
                    continue
                return json.loads(CACHE.read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as td:
                if gh("release", "download", RELEASE, "-p", ASSET, "-D", td, check=False).returncode != 0:
                    return None
                log("시장 수급: 내 PC 기록이 없어 릴리스에서 이어 받음")
                return json.loads((Path(td) / ASSET).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"시장 수급: {src} 읽기 실패 {e!r}"[:160])
    return None


def build_doc(rows, dates):
    doc = {"built": f"{now():%Y-%m-%d %H:%M}", "asof": f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}", "unit": "억원",
           "src": "키움증권 REST API · 거래소구분 통합(KRX+NXT) — 업종별투자자순매수(ka10051) · 프로그램매매추이 일자별(ka90010) · 업종일봉(ka20006)",
           "nxt_start": NXT_START, "d": [int(d) for d in dates]}
    for m in MKT:
        doc[m] = {x: [rows[m].get(d, {}).get(x) for d in dates] for x in KEYS}
    return doc


# ---------------------------------------------------------------- 수집
def collect(log=print, start=None, upload=True, dispatch=True):
    """빠진 날 + 최근 REFETCH 거래일을 받아 합치고 저장 · 올림 → (기준일, 새로 받은 날 수)"""
    if not _run_lock.acquire(blocking=False):
        log("시장 수급: 이미 수집 중"); return None
    try:
        t = now()
        today = f"{t:%Y%m%d}"
        doc = load(log)
        rows = to_rows(doc)
        have = sorted(set(rows["kospi"]) & set(rows["kosdaq"]))
        start = start or (have[0] if have else START)
        k = KW.Kiwoom()
        last_ok = today if t.time() >= FINAL else (t.date() - dt.timedelta(days=1)).strftime("%Y%m%d")
        # 1) 거래일 목록 · 프로그램 · 지수 (연속 조회는 필요한 만큼만)
        stop = start if not have or start < have[0] else have[-REFETCH:][0]
        prog, idx = {}, {}
        for m, c in MKT.items():
            prog[m] = (program(k, c["prog"][0], "3", today, stop), program(k, c["prog"][1], "2", today, max(stop, NXT_START)))
            idx[m] = index_daily(k, c["ind"], today, stop)
        days = sorted(d for d in set(prog["kospi"][0]) & set(idx["kospi"]) & set(idx["kosdaq"]) if start <= d <= last_ok)
        if not days and not have:
            log("시장 수급: 받을 거래일이 없음"); return None
        redo = set(have[-REFETCH:])
        need = [d for d in days if d not in rows["kospi"] or d not in rows["kosdaq"] or d in redo
                or rows["kospi"][d].get("f") is None or rows["kosdaq"][d].get("f") is None]
        log(f"시장 수급: 거래일 {len(days)}일 확인 · 투자자별 새로 받을 날 {len(need)}일")
        got = 0
        for j, d in enumerate(need):
            for m, c in MKT.items():
                tot = investor(k, c["inv"], c["ind"], d, "3")
                if tot is None:
                    continue
                nx = investor(k, c["inv"], c["ind"], d, "2") if d >= NXT_START else (0, 0, 0)
                nx = nx or (0, 0, 0)
                r = rows[m].setdefault(d, {})
                r.update(dict(zip(("f", "i", "p"), tot)))
                r.update(dict(zip(("nf", "ni", "np"), nx)))
            got += 1
            if (j + 1) % 100 == 0:
                log(f"시장 수급: 투자자별 {j + 1}/{len(need)}일")
        for m in MKT:
            p3, p2 = prog[m]
            for d in days:
                r = rows[m].setdefault(d, {})
                if d in idx[m]:
                    r.update(dict(zip(("o", "h", "l", "c", "v"), idx[m][d])))
                if d in p3:
                    r["ar"], r["na"] = p3[d]
                    r["nar"], r["nna"] = p2.get(d, (0, 0)) if d >= NXT_START else (0, 0)
        dates = sorted(d for d in set(rows["kospi"]) & set(rows["kosdaq"])
                       if all(rows[m][d].get("c") is not None and rows[m][d].get("f") is not None for m in MKT))
        new = build_doc(rows, dates)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(new, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(CACHE)
        lastk, lastq = new["kospi"], new["kosdaq"]
        log(f"시장 수급: 저장 {len(dates)}일 · 기준일 {new['asof']} · 코스피 외국인 {lastk['f'][-1]:+,}억 기관 {lastk['i'][-1]:+,}억 "
            f"개인 {lastk['p'][-1]:+,}억 비차익 {(lastk['na'][-1] or 0):+,}억 · 코스닥 외국인 {lastq['f'][-1]:+,}억")
        if upload:
            if gh("release", "view", RELEASE, check=False).returncode != 0:
                gh("release", "create", RELEASE, "--prerelease", "--title", "시장 수급 데이터",
                   "--notes", "코스피·코스닥 투자자별 순매수·프로그램 매매(KRX+NXT 통합) — 내 PC 의 tools/market/flow_kiwoom.py 가 거래일 20:12 에 올림")
            gh("release", "upload", RELEASE, str(CACHE), "--clobber")
            log("시장 수급: 릴리스 flow-data 에 올림")
            if dispatch and os.environ.get("RADAR_SITE_TRIGGER") != "0":
                r = gh("workflow", "run", "flow.yml", check=False)
                log("시장 수급: 사이트 반영(flow.yml) " + ("시작" if r.returncode == 0 else "실패 " + (r.stderr or "").strip()[:120]))
        return new["asof"], got
    finally:
        _run_lock.release()


def cached_asof():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8")).get("asof")
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    st = a[a.index("--start") + 1] if "--start" in a else None
    collect(start=st, upload="--no-upload" not in a, dispatch="--no-dispatch" not in a)
