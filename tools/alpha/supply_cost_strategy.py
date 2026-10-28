"""
수급 평단 지지 매매 백테스트 (supply_cost_study.py 결과를 규칙으로)
  진입: 외국인이 '주도 주체'(최근 60일 일별 순매수와 등락률 상관 > 0.2이고 세 주체 중 최고)
        + 외국인 보유분 추정 ≥ 상장주식 1%(선택) + 주가가 위에서 내려와 외국인 추정 평단 ±2% 안
        → 다음날 종가 매수 (종목별 수급은 장 마감 뒤 공개)
  청산: 여러 방식 비교 — 20일 보유 / 손절(평단 −5% 종가 이탈) / 목표(+8%·+12%·개인 평단)
  비용: 왕복 0.3% · 초과수익 = 같은 기간 전 종목 동일가중 평균 대비
사용: python supply_cost_strategy.py <supply 폴더>
"""
import json, sys, math
from collections import defaultdict

D = sys.argv[1]
idx = json.load(open(D + "/index.json", encoding="utf-8"))
pj = json.load(open(D + "/profile.json", encoding="utf-8"))
dates = idx["dates"]; N = len(dates); K = len(idx["stocks"])
COST = 0.003; B = 0.02
C = [[x if (x is not None and x > 0) else None for x in idx["c"][k]] for k in range(K)]
F = [[0.0 if v is None else v for v in idx["f"][k]] for k in range(K)]
I = [[0.0 if v is None else v for v in idx["i"][k]] for k in range(K)]
P = [[0.0 if v is None else v for v in pj["p"][k]] for k in range(K)]

# 전 종목 동일가중 지수 (일별 평균 수익률 누적)
mret = [0.0] * N
for t in range(1, N):
    s = n = 0
    for k in range(K):
        if C[k][t] and C[k][t - 1]:
            s += C[k][t] / C[k][t - 1] - 1; n += 1
    mret[t] = s / n if n else 0
MI = [1.0] * N
for t in range(1, N):
    MI[t] = MI[t - 1] * (1 + mret[t])


def inventory(c, amt, H):
    d = 0.5 ** (1 / H); q = V = 0.0; A = [None] * N; Q = [0.0] * N
    for t in range(N):
        if c[t] is None:
            continue
        q *= d; V *= d; a = amt[t]; s = a / c[t]
        if s > 0:
            q += s; V += a
        elif s < 0 and q > 0:
            red = min(-s, q); V -= red * V / q; q -= red
        if q > 1e-9:
            A[t] = V / q; Q[t] = q
    return A, Q


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


EXITS = {
    "20일 보유": dict(stop=None, tgt=None),
    "20일·손절(평단−5%)": dict(stop=0.05, tgt=None),
    "20일·손절·목표+8%": dict(stop=0.05, tgt=0.08),
    "20일·손절·목표+12%": dict(stop=0.05, tgt=0.12),
    "20일·손절·개인평단 목표": dict(stop=0.05, tgt="retail"),
    "40일·손절·목표+12%": dict(stop=0.05, tgt=0.12, hold=40),
}
trades = defaultdict(list)
for H in (60, 120, 250):
    for k in range(K):
        c = C[k]; sh = idx["stocks"][k]["sh"]
        cf, ci, cp = rollcorr(F[k], c), rollcorr(I[k], c), rollcorr(P[k], c)
        A, Q = inventory(c, F[k], H)
        AR, QR = inventory(c, P[k], H)
        for need_pos in (False, True):
            last = -99
            for t in range(61, N - 2):
                a0, a1 = A[t - 1], A[t]
                if not (a0 and a1 and c[t] and c[t - 1]) or t - last < 10:
                    continue
                if not (a1 * (1 - B) <= c[t] <= a1 * (1 + B) and c[t - 1] > a0 * (1 + B)):
                    continue
                if cf[t] is None or cf[t] <= 0.2 or (ci[t] is not None and ci[t] > cf[t]) or (cp[t] is not None and cp[t] > cf[t]):
                    continue
                if need_pos and Q[t] * 1e8 / sh * 100 < 1:
                    continue
                last = t
                e = t + 1
                if not c[e]:
                    continue
                for name, X in EXITS.items():
                    hold = X.get("hold", 20); lvl = a1; tgt = X["tgt"]
                    if tgt == "retail":
                        tg = AR[t] if (AR[t] and AR[t] > c[e] * 1.03) else c[e] * 1.12
                    elif tgt:
                        tg = c[e] * (1 + tgt)
                    else:
                        tg = None
                    x = None
                    for j in range(e + 1, min(N, e + hold + 1)):
                        if not c[j]:
                            continue
                        x = j
                        if X["stop"] and c[j] < lvl * (1 - X["stop"]):
                            break
                        if tg and c[j] >= tg:
                            break
                    if x is None:
                        continue
                    if e + hold >= N and not ((X["stop"] and c[x] < lvl * (1 - X["stop"])) or (tg and c[x] >= tg)):
                        continue                                  # 아직 끝나지 않은 거래 제외
                    r = c[x] / c[e] - 1 - COST
                    ex = r - (MI[x] / MI[e] - 1)
                    trades[(H, "보유≥1%" if need_pos else "전체", name)].append((r, ex, x - e, dates[t] // 10000))

print("H    조건      청산                       거래수  평균순수익  초과수익(t)   승률  평균보유  연도별 초과")
for key in sorted(trades):
    L = trades[key]; n = len(L)
    if not n:
        continue
    r = sum(x[0] for x in L) / n; ex = [x[1] for x in L]; m = sum(ex) / n
    sd = (sum((v - m) ** 2 for v in ex) / max(1, n - 1)) ** .5
    win = 100 * sum(1 for x in L if x[0] > 0) / n; hd = sum(x[2] for x in L) / n
    yrs = defaultdict(list)
    for x in L:
        yrs[x[3]].append(x[1])
    ys = " ".join("%d:%+.1f(%d)" % (y % 100, 100 * sum(v) / len(v), len(v)) for y, v in sorted(yrs.items()))
    print("%-4d %-8s %-24s %5d  %+6.2f%%  %+6.2f%%(t%.1f)  %3.0f%%  %4.1f일  %s" % (key[0], key[1], key[2], n, 100 * r, 100 * m, m / sd * n ** .5 if sd else 0, win, hd, ys))
