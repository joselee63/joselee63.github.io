"""
주체별 추정 평균단가가 지지·저항으로 작동하는가 (수급 매물대 차트 연구)
  · 입력: 사이트 supply/index.json (종가·외국인·기관, 억원) + supply/profile.json (개인)
  · 평균단가: 순매수 금액 ÷ 종가 = 추정 주식 수, 이동평균법 '보유분'만 추적(매도는 평단으로 차감)
              + 반감기 H일로 오래된 물량을 서서히 잊음 → 구간 시작일을 고르지 않아도 됨
  · 대조군: 같은 반감기의 가격 지수이동평균(EMA) — 평단선이 '그냥 이동평균'보다 나아야 의미가 있음
  · 신호: 위에서 내려와 평단 ±b 안에 들어온 날(지지 시험) / 아래에서 올라와 들어온 날(저항 시험)
  · 결과는 다음날 종가 진입 기준(종목별 수급은 장 마감 뒤 공개) — 같은 날 전 종목 평균 대비 초과수익
  · 한계: 현재 상장 297종목만(생존 편향), 종가 기준 추정 평단
사용: python supply_cost_study.py <supply 폴더>
"""
import json, sys, math
from collections import defaultdict

D = sys.argv[1]
idx = json.load(open(D + "/index.json", encoding="utf-8"))
pj = json.load(open(D + "/profile.json", encoding="utf-8"))
assert pj["codes"] == [s["c"] for s in idx["stocks"]]
dates = idx["dates"]; N = len(dates); K = len(idx["stocks"])
ENTS = ["외국인", "기관", "개인"]
HS = [20, 60, 120, 250]
B = 0.02            # 평단 근처 = ±2%
LEV = 0.05          # 먼저 닿는 쪽: 평단 +5% / −5%
HOR = [5, 10, 20]

C, FL = [], []
for k in range(K):
    C.append([x if (x is not None and x > 0) else None for x in idx["c"][k]])
    FL.append({"외국인": [0.0 if v is None else v for v in idx["f"][k]],
               "기관": [0.0 if v is None else v for v in idx["i"][k]],
               "개인": [0.0 if v is None else v for v in pj["p"][k]]})

# 같은 날 전 종목 평균 (다음날 종가 진입 → h일 보유)
mkt = {h: [None] * N for h in HOR}
for h in HOR:
    for t in range(N - h):
        s = n = 0
        for k in range(K):
            a, b = C[k][t], C[k][t + h]
            if a and b:
                s += b / a - 1; n += 1
        mkt[h][t] = s / n if n else None


def inventory(c, amt, H):
    d = 0.5 ** (1 / H)
    q = V = 0.0; A = [None] * N; Q = [0.0] * N
    for t in range(N):
        if c[t] is None:
            continue
        q *= d; V *= d
        a = amt[t]; s = a / c[t]
        if s > 0:
            q += s; V += a
        elif s < 0 and q > 0:
            red = min(-s, q); V -= red * V / q; q -= red
        if q > 1e-9:
            A[t] = V / q; Q[t] = q
    return A, Q


def ema(c, H):
    d = 0.5 ** (1 / H); e = None; out = [None] * N
    for t in range(N):
        if c[t] is None:
            continue
        e = c[t] if e is None else e * d + c[t] * (1 - d)
        out[t] = e
    return out


def rollcorr(x, c, w=60):
    out = [None] * N
    r = [None] + [(c[t] / c[t - 1] - 1) if (c[t] and c[t - 1]) else None for t in range(1, N)]
    for t in range(w, N):
        xs, ys = [], []
        for j in range(t - w + 1, t + 1):
            if r[j] is not None:
                xs.append(x[j]); ys.append(r[j])
        if len(xs) < 40:
            continue
        mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys)); sxx = sum((a - mx) ** 2 for a in xs); syy = sum((b - my) ** 2 for b in ys)
        if sxx > 0 and syy > 0:
            out[t] = sxy / math.sqrt(sxx * syy)
    return out


def outcome(c, t, lvl, kind):
    """t+1 종가 진입. 초과수익(h일) + 20일 안에 먼저 닿은 쪽 (지지: +5% 반등 먼저 = 성공, 저항: −5% 하락 먼저 = 성공)"""
    e = t + 1
    if e >= N or not c[e]:
        return None
    ex = {}
    for h in HOR:
        if e + h < N and c[e + h] and mkt[h][e] is not None:
            ex[h] = c[e + h] / c[e] - 1 - mkt[h][e]
    first = None
    for j in range(t + 1, min(N, t + 21)):
        if not c[j]:
            continue
        if c[j] >= lvl * (1 + LEV):
            first = "up"; break
        if c[j] <= lvl * (1 - LEV):
            first = "down"; break
    return {"ex": ex, "first": first, "yr": dates[t] // 10000}


def touches(c, L, frm):
    """frm='above': 위에서 내려와 L±B 안 / 'below': 아래에서 올라와. 같은 선 재신호는 10일 쉼"""
    out, last = [], -99
    for t in range(1, N):
        a0, a1 = L[t - 1], L[t]
        if not (a0 and a1 and c[t] and c[t - 1]):
            continue
        inb = a1 * (1 - B) <= c[t] <= a1 * (1 + B)
        came = c[t - 1] > a0 * (1 + B) if frm == "above" else c[t - 1] < a0 * (1 - B)
        if inb and came and t - last >= 10:
            out.append(t); last = t
    return out


R = defaultdict(list)       # key → [outcome]
for k in range(K):
    c = C[k]; sh = idx["stocks"][k]["sh"]
    cor = {e: rollcorr(FL[k][e], c) for e in ENTS}
    for H in HS:
        inv = {e: inventory(c, FL[k][e], H) for e in ENTS}
        E = ema(c, H)
        for t in touches(c, E, "above"):
            o = outcome(c, t, E[t], "sup")
            if o: R[("지지", "EMA", H, "-")].append(o)
        for t in touches(c, E, "below"):
            o = outcome(c, t, E[t], "res")
            if o: R[("저항", "EMA", H, "-")].append(o)
        for e in ENTS:
            A, Q = inv[e]
            for t in touches(c, A, "above"):
                o = outcome(c, t, A[t], "sup")
                if not o:
                    continue
                pos = Q[t] * 1e8 / sh * 100                       # 보유 추정 % (상장주식수 대비)
                cs = {x: cor[x][t] for x in ENTS}
                drv = cs[e] is not None and cs[e] > 0.2 and all(cs[e] >= (cs[x] if cs[x] is not None else -9) for x in ENTS)
                R[("지지", e, H, "전체")].append(o)
                R[("지지", e, H, "주도" if drv else "비주도")].append(o)
                R[("지지", e, H, "보유≥1%" if pos >= 1 else "보유<1%")].append(o)
                if drv and pos >= 1:
                    R[("지지", e, H, "주도+보유≥1%")].append(o)
            for t in touches(c, A, "below"):
                o = outcome(c, t, A[t], "res")
                if not o:
                    continue
                pos = Q[t] * 1e8 / sh * 100
                R[("저항", e, H, "전체")].append(o)
                R[("저항", e, H, "보유≥1%" if pos >= 1 else "보유<1%")].append(o)


def summ(L, kind):
    n = len(L)
    out = {"n": n}
    for h in HOR:
        v = [o["ex"][h] for o in L if h in o["ex"]]
        if v:
            m = sum(v) / len(v); sd = (sum((x - m) ** 2 for x in v) / max(1, len(v) - 1)) ** .5
            out[h] = (m * 100, m / sd * len(v) ** .5 if sd else 0)
    f = [o["first"] for o in L if o["first"]]
    good = "up" if kind == "지지" else "down"
    out["hit"] = 100 * sum(1 for x in f if x == good) / len(f) if f else float("nan")
    yrs = defaultdict(list)
    for o in L:
        if 20 in o["ex"]:
            yrs[o["yr"]].append(o["ex"][20])
    out["yrs"] = {y: 100 * sum(v) / len(v) for y, v in sorted(yrs.items()) if len(v) >= 30}
    return out


rows = []
for key in sorted(R, key=lambda x: (x[0], x[2], x[1], x[3])):
    s = summ(R[key], key[0])
    rows.append({"kind": key[0], "line": key[1], "H": key[2], "cut": key[3], **{str(k): v for k, v in s.items()}})
json.dump(rows, open(sys.argv[2] if len(sys.argv) > 2 else "supply_cost_study.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
for r in rows:
    f = lambda h: "%+.2f%%(t%.1f)" % r[h] if h in r else "-"
    print("%s H%-3d %-4s %-10s n=%5d  5일 %s  10일 %s  20일 %s  먼저닿음 %.0f%%  연도별20일 %s" % (
        r["kind"], r["H"], r["line"], r["cut"], r["n"], f("5"), f("10"), f("20"), r["hit"],
        " ".join("%d:%+.1f" % (y % 100, v) for y, v in r["yrs"].items())))
