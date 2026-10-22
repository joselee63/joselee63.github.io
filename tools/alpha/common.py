"""비가격 알파 연구 공통 모듈 — 무편향 가격 패널, 체결 가능성, 이벤트·포트폴리오 평가, 기준선 전략.

데이터
  data-backtest/ohlcv_all.pkl          수정주가 일봉 (상폐 포함, tools/backtest_data.py)
  data-backtest/listing_periods.csv    code_reused_or_moved=True 는 제외
  data-backtest/universe.csv           '스팩' 제외, 시장 구분
  data-backtest/sectors/index_ohlcv.csv KOSPI(1001)·KOSDAQ(2001) 지수 (시장 필터)
  <alpha>/flows|cap|fund|short          data 브랜치 alpha/ (tools/alpha/krx_collect.py)

시점 규칙 (look-ahead 금지)
  · 신호는 t일 장 마감 후 확정되는 정보만 사용 (수급·공매도 거래량은 t일 저녁 발표)
  · 체결: t+1일 시가 매수 (종가베팅만 t일 종가 매수)
  · t+1 시가가 상한가 근처(전일 대비 +lim-1%p 이상)면 매수 불가로 보고 제외 — 잠김 상황이 수익을 부풀리지 않게
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BT = Path(os.environ.get("BACKTEST_DIR", ROOT / "data-backtest"))   # 매일 갱신(closebet.yml)·시험용으로 바꿀 수 있음
ALPHA = Path(os.environ.get("ALPHA_DIR", ROOT / "data-alpha"))   # data 브랜치 alpha/ 를 받아 둔 곳
COST_KR = 0.0025          # 왕복 (수수료+거래세+슬리피지)
COST_KR_OLD = 0.002       # 기존 종가베팅 연구의 비용 가정 (비교용)


def load_panel(cache=None):
    """Panel 을 만들고 pickle 캐시 (기본: 임시폴더 ALPHA_CACHE)"""
    import pickle
    cache = Path(cache or os.environ.get("ALPHA_CACHE", ROOT / "data-alpha" / "_panel.pkl"))
    if cache.exists():
        return pickle.load(open(cache, "rb"))
    P = Panel()
    cache.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(P, open(cache, "wb"), protocol=4)
    return P


class Panel:
    """dates × tickers 넓은 배열 (float64). idx: date→행, col: ticker→열"""

    def __init__(self, min_bars=300):
        df = pd.read_pickle(BT / "ohlcv_all.pkl")
        uni = pd.read_csv(BT / "universe.csv", dtype=str)
        lp = pd.read_csv(BT / "listing_periods.csv", dtype=str)
        skip = set(lp.loc[lp["code_reused_or_moved"] == "True", "ticker"])
        skip |= set(uni.loc[uni["name"].str.contains("스팩", na=False), "ticker"])
        df["ticker"] = df["ticker"].astype(str)
        nb = df.groupby("ticker").size()
        keep = set(nb[nb >= min_bars].index) - skip
        df = df[df["ticker"].isin(keep)]
        self.market = dict(zip(uni["ticker"], uni["market"]))
        self.name = dict(zip(uni["ticker"], uni["name"]))
        self.delisted = set(lp.loc[lp["delisted_in_data"] == "True", "ticker"])
        piv = {k: df.pivot(index="date", columns="ticker", values=k) for k in
               ("open", "high", "low", "close", "volume")}
        self.dates = piv["close"].index
        self.tickers = piv["close"].columns
        o, h, l, c, v = (piv[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        for a in (o, h, l, c):
            a[a <= 0] = np.nan
        # 거래정지(거래량 0) 날은 가격을 비움
        sus = ~(v > 0)
        for a in (o, h, l, c):
            a[sus] = np.nan
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        self.T, self.N = c.shape
        self.di = {d: i for i, d in enumerate(self.dates)}
        self.ti = {t: j for j, t in enumerate(self.tickers)}
        self.is_kosdaq = np.array([self.market.get(t) == "KOSDAQ" for t in self.tickers])
        self._derive()

    # ---------------------------------------------------------------- 파생 지표
    def _derive(self):
        c, v = self.c, self.v
        prev = np.vstack([np.full((1, self.N), np.nan), c[:-1]])
        self.prev = prev
        with np.errstate(invalid="ignore", divide="ignore"):
            self.day = c / prev - 1
            self.pos = np.where(self.h > self.l, (c - self.l) / (self.h - self.l), 1.0)
        self.amt = c * v                                   # 거래대금 근사 (수정가×수정거래량)
        self.tv20 = roll(self.amt, 20, "mean", minp=15)
        self.v20 = roll(v, 20, "mean", minp=15)
        self.m60 = roll(c, 60, "mean", minp=60)
        self.hi252 = roll(c, 252, "max", minp=252)
        with np.errstate(invalid="ignore", divide="ignore"):
            lr = np.log(c / prev)
        self.sd60 = roll(lr, 60, "std", minp=55)
        # 가격제한폭: 2015-06-15부터 ±30%, 이전 ±15%
        lim = np.where(self.dates >= pd.Timestamp("2015-06-15"), 0.30, 0.15)
        self.lim = lim[:, None]
        # 상장 후 연속 데이터 일수 (추세추종 기준선의 261일 요구)
        ok = np.isfinite(c)
        run = np.zeros_like(c)
        for i in range(1, self.T):
            run[i] = np.where(ok[i], run[i - 1] + 1, 0)
        self.run = run
        # 시장 필터: 해당 종목 시장이 아니라 KOSPI 지수 > 60일선 (기존 연구와 동일)
        ix = pd.read_csv(BT / "sectors/index_ohlcv.csv", dtype={"index_code": str})
        ix["date"] = pd.to_datetime(ix["date"])
        k = ix[ix["index_code"] == "1001"].set_index("date")["close"].reindex(self.dates).ffill()
        self.kospi = k.to_numpy(float)
        km60 = pd.Series(self.kospi).rolling(60).mean().to_numpy()
        self.mkt_ok = self.kospi > km60
        kq = ix[ix["index_code"] == "2001"].set_index("date")["close"].reindex(self.dates).ffill()
        self.kosdaq = kq.to_numpy(float)
        # 다음날 시가 매수 가능 여부: 상한가 근처 갭(잠김 가능)·거래정지 제외
        nxt_o = np.vstack([self.o[1:], np.full((1, self.N), np.nan)])
        with np.errstate(invalid="ignore"):
            self.buyable_next_open = np.isfinite(nxt_o) & (nxt_o < c * (1 + self.lim - 0.01))
        self.liq = self.tv20 >= 1e9

    # ---------------------------------------------------------------- 정렬 도우미
    def align(self, df, col, date_col="date", tk_col="ticker", fill=np.nan):
        """long DataFrame → 패널과 같은 모양의 배열"""
        d = df[[date_col, tk_col, col]].copy()
        d[date_col] = pd.to_datetime(d[date_col].astype(str))
        w = d.pivot_table(index=date_col, columns=tk_col, values=col, aggfunc="last")
        w = w.reindex(index=self.dates, columns=self.tickers)
        a = w.to_numpy(float)
        if not np.isnan(fill):
            a = np.where(np.isnan(a), fill, a)
        return a


def roll(a, n, how="mean", minp=None):
    s = pd.DataFrame(a).rolling(n, min_periods=minp or n)
    return getattr(s, how)().to_numpy() if how != "std" else s.std(ddof=0).to_numpy()


def fwd_open_ret(P, H):
    """t일 신호 → t+1 시가 매수 → t+1+H 시가 매도 수익률 (H거래일 보유). 상폐로 끝나면 마지막 종가로."""
    o, c = P.o, P.c
    T = P.T
    ent = np.full_like(o, np.nan); ent[:-1] = o[1:]
    ext = np.full_like(o, np.nan)
    if H + 1 < T:
        ext[:-(H + 1)] = o[H + 1:]
    # 매도일 시가가 없으면(거래정지·상폐) 그때까지의 마지막 종가로 (상폐 손실 반영)
    lastc = pd.DataFrame(c).ffill().to_numpy()
    fb = np.full_like(o, np.nan)
    if H + 1 < T:
        fb[:-(H + 1)] = lastc[H + 1:]
    ext = np.where(np.isfinite(ext), ext, fb)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = ext / ent - 1
    r[-(H + 1):] = np.nan
    return r


def nw_t(x, lag):
    """Newey-West t값 (겹치는 보유기간 보정)"""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < 20:
        return np.nan
    m = x.mean(); e = x - m
    g0 = (e @ e) / n
    s = g0
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * (e[k:] @ e[:-k]) / n
    return m / np.sqrt(s / n) if s > 0 else np.nan


def summarize_daily(dser, H, cost, label="", nstk=None):
    """dser: 날짜별 포트폴리오(보유 H일) 평균 수익률 Series (비용 전). 반환 dict"""
    s = dser.dropna()
    if len(s) < 30:
        return None
    net = s - cost
    yrs = s.index.year
    med = s.index[len(s) // 2]
    yr_mean = net.groupby(yrs).mean()
    return dict(label=label, H=H, days=len(s), n=nstk, gross=s.mean(), net=net.mean(),
                t=nw_t(s.to_numpy(), H), win=(net > 0).mean(), p1=np.percentile(net, 1),
                first=net[net.index <= med].mean(), second=net[net.index > med].mean(),
                yr_pos=int((yr_mean > 0).sum()), yr_n=len(yr_mean),
                years=" ".join(f"{str(y)[2:]}:{v*100:+.2f}" for y, v in yr_mean.items()))


def fmt(r, excess=False):
    if r is None:
        return "(표본 부족)"
    return (f"{r['label']:38} H={r['H']:>2} 일수 {r['days']:5d} 비용전 {r['gross']*100:+6.2f}% "
            f"후 {r['net']*100:+6.2f}% t={r['t']:5.2f} 승 {r['win']*100:3.0f}% 하위1% {r['p1']*100:+6.1f}% "
            f"앞/뒤 {r['first']*100:+.2f}/{r['second']*100:+.2f} 플러스연도 {r['yr_pos']}/{r['yr_n']}")


# ==================================================================== 기준선 ①: 종가베팅
def overnight_pool(P):
    """기존 연구의 종가베팅 신호 풀: +3%·거래량 2배·고가권(70%+)·시장필터·유동성 10억·상장 261일+
    체결 가능(당일 +28.5% 미만). 반환: (mask, overnight 수익 배열(비용 전))"""
    with np.errstate(invalid="ignore"):
        strong = (P.day >= 0.03) & (P.v > 2 * P.v20)
        core = strong & (P.pos >= 0.7) & P.mkt_ok[:, None] & P.liq & np.isfinite(P.sd60)
        core &= (P.run >= 261) & (P.day < 0.285)
    nxt_o = np.vstack([P.o[1:], np.full((1, P.N), np.nan)])
    on = nxt_o / P.c - 1
    core &= np.isfinite(on)
    return core, on


def overnight_topk(P, mask, on, k=3, extra_key=None):
    """그날 풀에서 고가권 마감 순 → 등락률 순 상위 k. extra_key(배열, 큰 값 우선)를 주면 맨 앞 정렬키로.
    반환: 날짜별 평균 overnight(비용 전) Series, 선택 (i,j) 목록"""
    ii, jj = np.nonzero(mask)
    df = pd.DataFrame({"i": ii, "j": jj, "pos": P.pos[ii, jj], "day": P.day[ii, jj], "on": on[ii, jj]})
    keys, asc = ["pos", "day"], [False, False]
    if extra_key is not None:
        df["x"] = extra_key[ii, jj]
        keys, asc = ["x"] + keys, [False] + asc
    df = df.sort_values(["i"] + keys, ascending=[True] + asc)
    top = df.groupby("i").head(k)
    s = top.groupby("i")["on"].mean()
    s.index = P.dates[s.index]
    return s, top


# ==================================================================== 기준선 ②: 추세추종 (계획 ⑨)
FEE_T = 0.001        # 편도 (기존 연구 entry_scan.py 와 같음 → 왕복 약 0.2%)
HOLD_T = 80


def trend_signals(P):
    """60일선 위·상승 + 52주 신고가 + 거래량 2배 + 시장필터 + 유동성 10억 (기존 '유동성10억+시장필터')"""
    m60p = np.vstack([np.full((10, P.N), np.nan), P.m60[:-10]])
    with np.errstate(invalid="ignore"):
        A = (P.c > P.m60) & (P.m60 > m60p)
        ent = A & (P.c >= P.hi252) & (P.v > 2 * P.v20) & P.mkt_ok[:, None] & P.liq
        ent &= (P.run >= 261) & np.isfinite(P.sd60)
    return ent


def trend_sim_one(c, sd, i, REF, FEE=FEE_T, HOLD=HOLD_T):
    """entry_scan.sim 과 같은 계획 ⑨ 청산 — 진입 t일 종가, 매매당 계좌 수익(2%룰)"""
    s = sd[i]
    if not np.isfinite(s) or s <= 0:
        return None
    E = c[i]; sp = min(0.18, max(0.05, 0.09 * np.sqrt(s / REF))); R = E * sp
    f0 = min(1.0, 0.02 / sp); q0 = f0 / E; lots = [[q0, E]]; cash = 1 - f0; real = 0.0
    tp = min(0.30, max(0.12, 3 * sp)); stop = E - R; top = E; added = False; took = False
    end = min(i + HOLD, len(c) - 1); j = i
    for j in range(i + 1, end + 1):
        p = c[j]
        if not np.isfinite(p) or p <= stop:
            break
        top = max(top, p); stop = max(stop, top * (1 - tp))
        if not took and p >= E + 3 * R:
            for L in lots:
                q = L[0] / 3.0; real += q * (p * (1 - FEE) - L[1] * (1 + FEE)); L[0] -= q
            took = True
        if not added and p >= E + R:
            qa = min(q0, cash / (p * (1 + FEE)))
            if qa > 0:
                lots.append([qa, p]); cash -= qa * p * (1 + FEE); added = True
                n = sum(q for q, _ in lots); avg = sum(q * b for q, b in lots) / n; eq = cash + n * p
                stop = max(stop, avg * (1 - sp), avg - 0.02 * eq / n)
    p = c[j]
    if not np.isfinite(p):
        # 거래정지·상폐로 끊김 → 마지막 유효 종가
        k = j
        while k > i and not np.isfinite(c[k]):
            k -= 1
        p = c[k]
    pnl = real + sum(q * (p * (1 - FEE) - b * (1 + FEE)) for q, b in lots)
    return pnl, j


def trend_run(P, ent, REF=None):
    """종목별로 포지션 겹치지 않게 진행 → DataFrame(i, j, pnl, exit)"""
    if REF is None:
        s = P.sd60[np.isfinite(P.sd60)]
        REF = float(np.median(s[::7]))
    out = []
    for j in range(P.N):
        e = np.nonzero(ent[:, j])[0]
        if not len(e):
            continue
        c = P.c[:, j]; sd = P.sd60[:, j]
        nxt = -1
        for i in e:
            if i <= nxt or i >= P.T - 1:
                continue
            r = trend_sim_one(c, sd, i, REF)
            if r:
                out.append((i, j, r[0], r[1])); nxt = r[1]
    df = pd.DataFrame(out, columns=["i", "j", "pnl", "x"])
    df["date"] = P.dates[df["i"]]
    return df, REF


def trade_stats(r, dates=None, label=""):
    r = np.asarray(r, float)
    if len(r) < 30:
        return f"{label:38} 매매 {len(r)} (표본 부족)"
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    s = f"{label:38} 매매 {len(r):6,} 평균 {r.mean()*100:+6.2f}% t={t:5.2f} 승 {(r>0).mean()*100:3.0f}% 하위1% {np.percentile(r,1)*100:+6.1f}%"
    if dates is not None:
        d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
        med = d.sort_values().iloc[len(d) // 2]
        rr = pd.Series(r)
        s += f" 앞/뒤 {rr[d <= med].mean()*100:+.2f}/{rr[d > med].mean()*100:+.2f}"
        ym = rr.groupby(d.dt.year).mean()
        s += f" 플러스연도 {(ym>0).sum()}/{len(ym)}"
    return s


# ==================================================================== 비가격 데이터 로더
def fetch_alpha_branch():
    """data 브랜치 alpha/ 를 data-alpha/alpha/ 로 풀기 (git archive, 작업트리·인덱스 건드리지 않음)"""
    import subprocess, tarfile, io
    subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "origin", "data"], check=True)
    raw = subprocess.run(["git", "-C", str(ROOT), "archive", "origin/data", "alpha"],
                         check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(ALPHA)


def load_alpha(kind):
    files = sorted((ALPHA / "alpha" / kind).rglob("*.csv.gz"))
    if not files:
        raise FileNotFoundError(f"{ALPHA}/alpha/{kind} 없음 — fetch_alpha_branch() 먼저")
    df = pd.concat((pd.read_csv(f, dtype={"ticker": str, "date": str}) for f in files), ignore_index=True)
    df["ticker"] = df["ticker"].str.zfill(6)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ==================================================================== 횡단면 분위 검정
_FWD = {}


def fwd(P, H):
    if H not in _FWD:
        _FWD[H] = fwd_open_ret(P, H)
    return _FWD[H]


def base_mask(P, liq=True):
    """유니버스: 상장 120일+, 신호일 가격 있음, 다음날 시가 매수 가능, (선택) 20일 평균 거래대금 10억+"""
    m = np.isfinite(P.c) & (P.run >= 120) & P.buyable_next_open
    if liq:
        m &= P.liq
    return m


def quantile_returns(P, F, H, mask, nq=10, minn=5):
    """날짜별 분위 포트폴리오(동일가중) H일 수익률(비용 전). 열 q1..qN(큰 값=qN), uni(유니버스 평균)"""
    R = fwd(P, H)
    M = mask & np.isfinite(F) & np.isfinite(R)
    Fm = pd.DataFrame(np.where(M, F, np.nan))
    rk = Fm.rank(axis=1, pct=True, method="average").to_numpy()
    q = np.ceil(rk * nq)
    Rm = np.where(M, R, np.nan)
    out = {}
    for k in range(1, nq + 1):
        sel = q == k
        cnt = sel.sum(1)
        s = np.where(sel, Rm, 0).sum(1) / np.maximum(cnt, 1)
        out[f"q{k}"] = np.where(cnt >= minn, s, np.nan)
    cnt = M.sum(1)
    out["uni"] = np.where(cnt >= minn * nq, np.nansum(Rm, 1) / np.maximum(cnt, 1), np.nan)
    df = pd.DataFrame(out, index=P.dates)
    return df


def topk_returns(P, F, H, mask, k=20, minval=None):
    """날짜별 F 상위 k종목(minval 이상만) 동일가중 H일 수익률 + 유니버스 평균"""
    R = fwd(P, H)
    M = mask & np.isfinite(F) & np.isfinite(R)
    if minval is not None:
        M &= F >= minval
    Fm = np.where(M, F, -np.inf)
    idx = np.argsort(-Fm, axis=1)[:, :k]
    rows = np.arange(P.T)[:, None]
    sel = np.zeros_like(M)
    sel[rows, idx] = True
    sel &= M
    cnt = sel.sum(1)
    Rm = np.where(M, R, np.nan)
    top = np.where(cnt > 0, np.where(sel, Rm, 0).sum(1) / np.maximum(cnt, 1), np.nan)
    Mu = mask & np.isfinite(R)
    uni = np.nansum(np.where(Mu, R, np.nan), 1) / np.maximum(Mu.sum(1), 1)
    return pd.DataFrame({"top": top, "uni": np.where(Mu.sum(1) > 50, uni, np.nan), "n": cnt}, index=P.dates)


def qline(df, H, cost=COST_KR, label=""):
    """분위표 한 줄: 각 분위 평균(비용 전) + 상위분위 비용 후·초과수익 t"""
    nq = sum(c.startswith("q") for c in df.columns)
    d = df.dropna(subset=[f"q{nq}", "uni"])
    means = [d[f"q{k}"].mean() * 100 for k in range(1, nq + 1)]
    lo = next(k for k in range(1, nq + 1) if d[f"q{k}"].notna().mean() > 0.5)   # 동점(0) 몰림 시 가장 낮은 유효 분위
    ex = d[f"q{nq}"] - d["uni"]
    ls = (d[f"q{nq}"] - d[f"q{lo}"]).dropna()
    s = f"{label:30} H={H:>2} " + " ".join(f"{m:+5.2f}" for m in means)
    s += f" | 유니 {d['uni'].mean()*100:+5.2f} 상위−유니 {ex.mean()*100:+5.2f}(t={nw_t(ex.to_numpy(), H):4.1f})"
    s += f" 상−하 {ls.mean()*100:+5.2f}(t={nw_t(ls.to_numpy(), H):4.1f}) 상위 비용후 {(d[f'q{nq}'].mean()-cost)*100:+5.2f}"
    return s


def robust_q(P, X, H, mask, label="", nq=10, cost=COST_KR):
    """상위 분위 초과수익의 연도별·앞뒤 절반·이웃 분위(q9) — 강건성 한 줄 + 연도별"""
    q = quantile_returns(P, X, H, mask, nq=nq)
    d = q.dropna(subset=[f"q{nq}", "uni"])
    ex = d[f"q{nq}"] - d["uni"]
    ex9 = (d[f"q{nq-1}"] - d["uni"]).dropna()
    med = d.index[len(d) // 2]
    yr = ex.groupby(ex.index.year).mean()
    print(f"  [{label}] H={H} 상위 비용후 {(d[f'q{nq}'].mean()-cost)*100:+.2f}% 초과 {ex.mean()*100:+.2f}%(t={nw_t(ex.to_numpy(), H):.1f}) "
          f"q9 초과 {ex9.mean()*100:+.2f}% 앞/뒤 {ex[ex.index<=med].mean()*100:+.2f}/{ex[ex.index>med].mean()*100:+.2f} "
          f"플러스연도 {(yr>0).sum()}/{len(yr)}")
    print("     연도별 초과: " + " ".join(f"{y%100}:{v*100:+.1f}" for y, v in yr.items()))
    return q


# ==================================================================== 월간 리밸런싱 포트폴리오
def monthly_portfolio(P, score, mask, n=30, cost=COST_KR, label="", hold_months=1, verbose=True):
    """매월 마지막 거래일 종가 기준 score 상위 n종목(mask 안) → 다음 거래일 시가에 동일비중 매수, 다음 리밸런싱까지 보유.
    교체분에만 비용(왕복 cost 를 매수·매도 절반씩). 상폐·거래정지는 마지막 종가로 청산(손실 반영).
    반환: 월별 수익률 Series(비용 후), 같은 기간 유니버스(mask) 동일가중 월 수익률"""
    lastc = pd.DataFrame(P.c).ffill().to_numpy()
    o = np.where(np.isfinite(P.o), P.o, lastc)
    ym = P.dates.to_period("M")
    ends = np.nonzero(np.r_[ym[1:] != ym[:-1], False])[0]          # 월 마지막 거래일 행
    ends = ends[::hold_months]
    rets, unis, idx, held = [], [], [], set()
    for a, b in zip(ends[:-1], ends[1:]):
        ent, ext = a + 1, b + 1
        if ext >= P.T:
            break
        ok = mask[a] & np.isfinite(score[a])
        cand = np.nonzero(ok)[0]
        if len(cand) < n:
            continue
        pick = cand[np.argsort(-score[a, cand])[:n]]
        r = o[ext, pick] / o[ent, pick] - 1
        new = set(pick.tolist())
        turn = len(new - held) / n if held else 1.0
        rets.append(np.nanmean(r) - cost * turn)                     # 교체 비율만큼 왕복 비용
        held = new
        ru = o[ext, cand] / o[ent, cand] - 1
        unis.append(np.nanmean(ru))
        idx.append(P.dates[ent])
    s = pd.Series(rets, index=idx); u = pd.Series(unis, index=idx)
    if verbose:
        perf_line(s, u, label, hold_months)
    return s, u


def perf_line(s, u, label="", hm=1):
    k = 12 / hm
    ex = s - u
    eq = (1 + s).cumprod(); mdd = (eq / eq.cummax() - 1).min()
    cagr = eq.iloc[-1] ** (k / len(s)) - 1
    ucagr = (1 + u).prod() ** (k / len(u)) - 1
    h = len(s) // 2
    yr = ex.groupby(ex.index.year).sum()
    print(f"  [{label}] 연 {cagr*100:+.1f}% (유니 {ucagr*100:+.1f}%) MDD {mdd*100:.0f}% 월초과 {ex.mean()*100:+.2f}% "
          f"t={nw_t(ex.to_numpy(), 1):.2f} 승월 {(ex>0).mean()*100:.0f}% 최악월 {s.min()*100:+.1f}% "
          f"앞/뒤 {ex.iloc[:h].mean()*100:+.2f}/{ex.iloc[h:].mean()*100:+.2f} 플러스연도 {(yr>0).sum()}/{len(yr)}")
    print("     연도별 초과(합): " + " ".join(f"{y%100}:{v*100:+.0f}" for y, v in yr.items()))


def periodic_portfolio(P, score, mask, n=20, K=20, cost=COST_KR, label="", minval=None, verbose=True, offset=0):
    """K거래일마다 리밸런싱: t일 종가까지 정보로 score 상위 n(minval 이상) → t+1 시가 동일비중 매수, 다음 리밸런싱일+1 시가 매도.
    교체분에만 왕복 비용. 반환: 기간 수익 Series(비용 후), 유니버스(mask) 동일가중."""
    lastc = pd.DataFrame(P.c).ffill().to_numpy()
    o = np.where(np.isfinite(P.o), P.o, lastc)
    reb = np.arange(250 + offset, P.T - 1, K)
    rets, unis, idx, nn, held = [], [], [], [], set()
    for a, b in zip(reb[:-1], reb[1:]):
        ent, ext = a + 1, b + 1
        ok = mask[a] & np.isfinite(score[a])
        if minval is not None:
            ok &= score[a] >= minval
        cand = np.nonzero(ok)[0]
        allc = np.nonzero(mask[a])[0]
        ru = o[ext, allc] / o[ent, allc] - 1
        if len(cand) == 0:
            rets.append(0.0); held = set()
        else:
            pick = cand[np.argsort(-score[a, cand])[:n]]
            r = o[ext, pick] / o[ent, pick] - 1
            new = set(pick.tolist())
            turn = len(new - held) / len(new) if held else 1.0
            rets.append(np.nanmean(r) - cost * turn)
            held = new
        unis.append(np.nanmean(ru)); idx.append(P.dates[ent]); nn.append(len(cand))
    s = pd.Series(rets, index=idx); u = pd.Series(unis, index=idx)
    if verbose:
        perf_line(s, u, label, hm=K / 21)
    return s, u
