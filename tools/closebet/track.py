"""실전 추적 — 검증한 전략의 신호를 '그날' 기록하고, 결과는 이후 가격으로 채움 (기록한 신호는 다시 계산하지 않음)
export_web.py 가 large_cap(L) 을 불러온 뒤 TRACK_OUT 이 있으면 run(L) 호출. 기존 기록은 TRACK_IN (없으면 새로 시작).
  · cb    대형주 종가베팅(등급): 시총 5천억·거래대금 300억↑, +3%↑(+28.5% 미만), 코스닥>20일선, 등급 상위 20%, 등급순 3종목 → 종가 매수 · 다음날 시가 매도
  · panic 패닉 낙주: 코스피 종가 −4%↓ → 삼성전자·SK하이닉스 종가 매수 · 다음날 시가 매도
  · credit 신용잔고 바닥: 금투협 신용융자 잔고 하루 −3%↓(−5%↓ 강) → 자료 공표일(신호일 +2거래일) 코스피 종가 진입 · 5·20거래일 뒤
  · ma    이평선 깊은 이탈: 거래대금 상위100·60일 +30%↑, 직전 5일 20일선 위 → 20일선 −4%↓ 이탈 + 거래량 2배↑ → 종가 매수 · 다음날 시가 매도
비용: 주식 왕복 0.25%, 코스피(지수) 0
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

START = os.environ.get("TRACK_START", "20261022")   # 연구 데이터(~2026-10-21) 이후 = 표본 외 (TRACK_START 는 시험용)
COST = 0.0025
META = {
    "cb": {"name": "대형주 종가베팅 (등급)", "rule": "시총 5천억·20일 평균 거래대금 300억↑ · 당일 +3%↑(+28.5% 미만) · 등급 상위 20% · 등급순 3종목 → 종가 매수, 다음날 시가 매도 · 비중 = 계단20(코스닥이 20·40·60·90·120일선을 하나 깰 때마다 −20%, 2026-10-26부터)",
           "exp": 0.0029, "win": 0.58, "unit": "밤", "src": "2018~2026 워크포워드 (상장폐지 포함) · 비용 0.25% 후"},
    "panic": {"name": "패닉 낙주", "rule": "코스피 종가 −4% 이하 → 삼성전자·SK하이닉스 종가 매수, 다음날 시가 매도",
              "exp": 0.0172, "win": 0.69, "unit": "회", "src": "2015~2026 (35회) · 비용 0.25% 후"},
    "credit": {"name": "신용잔고 바닥 신호", "rule": "금투협 신용융자 잔고 하루 −3% 이하(−5% 이하 = 강) → 자료가 나오는 날(신호일 +2거래일) 코스피 종가 진입, 5·20거래일 뒤 평가",
               "exp": 0.039, "win": 0.71, "unit": "회", "src": "2006~2026 (−5%↓ 14회, 5일 기준) · 지수 기준"},
    "ma": {"name": "이평선 깊은 이탈 받기", "rule": "거래대금 상위 100·60일 +30%↑, 직전 5일 20일선 위 → 종가가 20일선보다 4% 이상 아래 + 거래량 평소의 2배↑ → 종가 매수, 다음날 시가 매도",
           "exp": 0.0158, "win": 0.58, "unit": "회", "src": "2015~2026 (53회, t≈1.5 · 통계적으로 약함) · 비용 0.25% 후"},
}


def kofia_credit():
    body = {"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D", "tmpV45": "20260701", "tmpV46": "20991231", "OBJ_NM": "STATSCU0100000070BO"}}
    r = requests.post("https://freesis.kofia.or.kr/meta/getMetaDataList.do", data=json.dumps(body), timeout=60,
                      headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json; charset=UTF-8", "Referer": "https://freesis.kofia.or.kr/stat/FreeSIS.do"})
    d = pd.DataFrame(r.json().get("ds1") or [])
    if not len(d):
        return pd.Series(dtype=float)
    s = pd.Series(d["TMPV2"].astype(float).to_numpy(), index=pd.to_datetime(d["TMPV1"], format="%Y%m%d")).sort_index()
    return s[s > 0]


def run(L, path_in, path_out):
    P, G = L.P, L.G
    dates = P.dates; T = len(dates)
    ds = [d.strftime("%Y%m%d") for d in dates]
    pos = {d: i for i, d in enumerate(ds)}
    log = {"start": START, "trades": []}
    if path_in and Path(path_in).exists():
        try:
            log = json.load(open(path_in, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    have = {(t["s"], t["d"]) for t in log["trades"]}
    name = lambda j: P.name.get(P.tickers[j], P.tickers[j])
    kidx = G.ix[G.ix["index_code"] == "1001"].set_index("date")["close"].reindex(dates).ffill().to_numpy()
    kq = G.ix[G.ix["index_code"] == "2001"].set_index("date")["close"].reindex(dates).ffill()
    w20 = np.clip(1 - 0.2 * sum((kq < kq.rolling(n).mean()).astype(int) for n in (20, 40, 60, 90, 120)), 0, 1).to_numpy()
    t0 = pos.get(START) if START in pos else int(np.searchsorted(np.array(ds), START))
    with np.errstate(invalid="ignore", divide="ignore"):
        ma20 = pd.DataFrame(P.c).rolling(20, min_periods=20).mean().to_numpy()
        tvr = pd.DataFrame(P.tv20).rank(axis=1, ascending=False).to_numpy()
        r60 = P.c / np.vstack([np.full((60, P.N), np.nan), P.c[:-60]]) - 1
        vr = P.v / P.v20
    new = 0
    for i in range(max(t0, 61), T):
        d = ds[i]
        # 종가베팅 (대형주 등급)
        if ("cb", d) not in have:
            step = d >= "20261026"                         # 2026-10-26부터 계단20 비중 (그 전 기록은 '코스닥 20일선 위만' 규칙)
            on = (w20[i] > 0) if step else bool(L.REG_KQ[i])
            m = L.SIG3[i] & L.LARGE[i] & on & (L.GP[i] >= 0.8 - 1e-12)
            jj = np.nonzero(m)[0]
            jj = jj[np.argsort(-np.nan_to_num(L.GM[i, jj], nan=-9), kind="stable")][:3]
            log["trades"].append({"s": "cb", "d": d, "reg": bool(on), "w": round(float(w20[i]), 2) if step else (1.0 if on else 0.0),
                                  "picks": [{"c": P.tickers[j], "n": name(j), "j": int(j), "px": float(P.c[i, j]), "day": round(float(P.day[i, j]), 4)} for j in jj]})
            new += 1
        # 패닉 낙주
        if ("panic", d) not in have and i > 0 and kidx[i] / kidx[i - 1] - 1 <= -0.04:
            jj = [P.ti[c] for c in ("005930", "000660") if c in P.ti and np.isfinite(P.c[i, P.ti[c]])]
            log["trades"].append({"s": "panic", "d": d, "kday": round(float(kidx[i] / kidx[i - 1] - 1), 4),
                                  "picks": [{"c": P.tickers[j], "n": name(j), "j": int(j), "px": float(P.c[i, j])} for j in jj]})
            new += 1
        # 이평선 깊은 이탈
        if ("ma", d) not in have:
            ok = np.ones(P.N, bool)
            for k in range(1, 6):
                ok &= P.c[i - k] > ma20[i - k]
            with np.errstate(invalid="ignore"):
                m = ok & (P.c[i] <= ma20[i] * 0.96) & (vr[i] >= 2) & (tvr[i] <= 100) & (r60[i] >= 0.3) & (P.run[i] >= 120) & (P.day[i] > -0.285)
            jj = np.nonzero(m)[0]
            if len(jj):
                log["trades"].append({"s": "ma", "d": d, "picks": [{"c": P.tickers[j], "n": name(j), "j": int(j), "px": float(P.c[i, j]),
                                                                    "day": round(float(P.day[i, j]), 4), "vr": round(float(vr[i, j]), 1)} for j in jj]})
                new += 1
    # 신용잔고 바닥 (금투협, 공표일 = 신호일 +2거래일)
    try:
        cr = kofia_credit()
        cr1 = cr.pct_change()
        for dt_, v in cr1.items():
            d = dt_.strftime("%Y%m%d")
            if d < START or not (v <= -0.03) or ("credit", d) in have:
                continue
            if d not in pos or pos[d] + 2 >= T:
                continue                                     # 공표일이 아직 안 옴
            e = pos[d] + 2
            log["trades"].append({"s": "credit", "d": d, "strong": bool(v <= -0.05), "cr1": round(float(v), 4), "entry_d": ds[e], "px": float(kidx[e])})
            new += 1
    except Exception as ex:  # noqa: BLE001
        print("  실전 추적: 금투협 자료 실패", ex)
    # 결과 채우기 (가격이 나온 것만)
    for t in log["trades"]:
        i = pos.get(t["d"])
        if t["s"] == "credit":
            e = pos.get(t["entry_d"])
            for h in (5, 20):
                if e is not None and e + h < T and f"r{h}" not in t:
                    t[f"r{h}"] = round(float(kidx[e + h] / t["px"] - 1), 5); t[f"x{h}"] = ds[e + h]
            t["done"] = "r20" in t
            continue
        if i is None or t.get("done"):
            continue
        rs = []
        for p in t["picks"]:
            if "r" in p:
                rs.append(p["r"]); continue
            j = p["j"]; k = i + 1
            while k < T and not np.isfinite(P.o[k, j]):
                k += 1                                       # 거래정지면 재개 후 첫 시가
            if k < T:
                p["xpx"] = float(P.o[k, j]); p["xd"] = ds[k]; p["r"] = round(p["xpx"] / p["px"] - 1 - COST, 5); rs.append(p["r"])
        if t["picks"] and len(rs) == len(t["picks"]):
            t["r"] = round(float(np.mean(rs)), 5); t["done"] = True
        elif not t["picks"]:
            t["done"] = True                                 # 후보 없음 (쉬는 날)
    log["meta"] = META
    log["asof"] = ds[-1]
    log["trades"].sort(key=lambda t: (t["d"], t["s"]))
    json.dump(log, open(path_out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"  실전 추적: 새 기록 {new}건 · 전체 {len(log['trades'])}건 · 기준일 {log['asof']} → {path_out}")
