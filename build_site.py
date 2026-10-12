# ======================================
# 한국 증시 섹터별 차트 — 웹페이지 빌드 (GitHub Actions 배치용)
#   · 데이터 수신 → 지표·추세선 계산 → 차트 PNG → site/ 폴더에 웹페이지 생성
#   · 데이터: 네이버 fchart(기본) → Yahoo Finance(폴백, 해외 서버에서 네이버가 막힐 때 대비)
#   · 로컬 실행: python build_site.py  →  site/index.html 을 브라우저로 열기
# ======================================
import os, re, io, sys, json, time, html, shutil
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import matplotlib as mpl
mpl.use("Agg")
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from matplotlib.lines import Line2D

from stocks import SECTIONS, ETF_SECTIONS

# --- 설정 ---
ROOT      = os.path.dirname(os.path.abspath(__file__))
SITE_DIR  = os.path.join(ROOT, "site")          # 배포 폴더 (매번 새로 만듦)
WEB_DIR   = os.path.join(ROOT, "web")           # 페이지 원본(index.html)
KST       = dt.timezone(dt.timedelta(hours=9))

DISPLAY_BARS = 150                    # 차트에 보여줄 거래일 수 (약 7개월)
MA_LIST      = [5, 20, 60, 120]       # 이동평균. Finviz처럼 보려면 [20, 50, 200]
TREND_LONG   = dict(lookback=120, recent=5, min_span=20)   # 장기 추세선 (실선)
TREND_SHORT  = dict(lookback=45,  recent=3, min_span=8)    # 단기 추세선 (점선)
SHOW_SHORT_TREND = True
TREND_EXTEND = 8                      # 추세선 오른쪽 연장 봉 수
BREAK_MARGIN = 0.01                   # 종가가 장기 추세선을 1% 넘게 벗어나야 '돌파/이탈'

FIG_SIZE, FIG_DPI = (10, 5.4), 90
MAX_WORKERS   = 6                     # 동시 다운로드 수
RENDER_PROCS  = max(1, min(4, os.cpu_count() or 1))   # 차트 병렬 생성 프로세스 수
MIN_SUCCESS   = 0.6                   # 수신 성공률이 이보다 낮으면 배포하지 않고 실패 처리

UP_COLOR, DOWN_COLOR = "#E5383B", "#1D63D8"
MA_COLORS = {5: "#9B5DE5", 20: "#F4A100", 60: "#2A9D8F", 120: "#7F8C8D",
             50: "#2A9D8F", 200: "#7F8C8D", 10: "#C77DFF"}
SUPPORT_COLOR, RESIST_COLOR = "#00A6C8", "#E0479E"
FETCH_BARS = max(DISPLAY_BARS + max(MA_LIST), 260) + 20

INDEX_YAHOO = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "KPI200": "^KS200"}
INDEX_CODES = set(INDEX_YAHOO)


# --- 한글 폰트 ---
def _setup_korean_font():
    """
    한글 폰트 파일을 matplotlib에 직접 등록.
    koreanize-matplotlib 패키지는 Python 3.12에서 import 자체가 실패하므로(distutils 제거),
    import 하지 않고 패키지 안에 들어 있는 나눔고딕 파일만 찾아서 씀. 없으면 시스템 한글 폰트 사용.
    """
    import importlib.util
    from matplotlib import font_manager as fm
    cands = []
    try:
        spec = importlib.util.find_spec("koreanize_matplotlib")   # 최상위 패키지는 import 없이 위치만 찾음
        for loc in (spec.submodule_search_locations or []) if spec else []:
            cands.append(os.path.join(loc, "fonts", "NanumGothic.ttf"))
    except Exception:
        pass
    cands += [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in cands:
        if not os.path.exists(path):
            continue
        try:
            fm.fontManager.addfont(path)
            name = fm.FontProperties(fname=path).get_name()
            mpl.rcParams["font.family"] = name
            mpl.rcParams["axes.unicode_minus"] = False
            print(f"[폰트] {name} ({path})")
            return True
        except Exception:
            continue
    print("[경고] 한글 폰트를 찾지 못함 → 차트 글자를 영문·숫자로만 표시")
    return False

KFONT = _setup_korean_font()
# 차트 안 글자 (한글 폰트가 없으면 영문으로 대체해 □□ 깨짐 방지)
TXT = ({"ma": "{}일", "sup": "지지 추세선", "res": "저항 추세선", "eok": "억", "man": "만"} if KFONT else
       {"ma": "MA{}", "sup": "Support", "res": "Resistance", "eok": "e8", "man": "e4"})


# --- 데이터 수신 ---
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
FCHART_URL = "https://fchart.stock.naver.com/sise.nhn"
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Referer": "https://finance.naver.com/"})


def _clean_ohlcv(df):
    df = df.copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    for col in ["Open", "High", "Low"]:
        bad = df[col].isna() | (df[col] <= 0)
        df.loc[bad, col] = df.loc[bad, "Close"]
    df["High"] = df[["Open", "High", "Low", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "High", "Low", "Close"]].min(axis=1)
    df["Volume"] = df["Volume"].fillna(0)
    return df


def parse_fchart(raw: bytes):
    """네이버 fchart XML → (DataFrame, 네이버 종목명)"""
    m = re.search(rb'encoding="([^"]+)"', raw[:200])
    enc = m.group(1).decode() if m else "euc-kr"
    text = raw.decode(enc, errors="replace")
    rows = re.findall(r'<item data="([^"]*)"', text)
    if not rows:
        raise ValueError("네이버 응답에 데이터 없음")
    df = pd.DataFrame([r.split("|")[:6] for r in rows],
                      columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    nm = re.search(r'<chartdata[^>]*\bname="([^"]*)"', text)
    return _clean_ohlcv(df), (html.unescape(nm.group(1)).strip() if nm else None)


def fetch_naver(code, count=FETCH_BARS):
    r = _session.get(FCHART_URL, timeout=10,
                     params={"symbol": code, "timeframe": "day", "count": count, "requestType": 0})
    r.raise_for_status()
    return parse_fchart(r.content)


def fetch_yahoo(code, count=FETCH_BARS):
    import yfinance as yf
    start = (dt.date.today() - dt.timedelta(days=int(count * 1.6) + 30)).isoformat()
    cands = [INDEX_YAHOO[code]] if code in INDEX_YAHOO else [f"{code}.KS", f"{code}.KQ"]
    for t in cands:
        try:
            df = yf.Ticker(t).history(start=start, auto_adjust=False, actions=False)
        except Exception:
            continue
        if df is not None and len(df) >= 5:
            idx = pd.DatetimeIndex(df.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            df.index = idx.normalize()
            return _clean_ohlcv(df[["Open", "High", "Low", "Close", "Volume"]]), None
    raise ValueError("Yahoo 데이터 없음")


def fetch_one(code, retries=2):
    errs = []
    for attempt in range(retries + 1):
        try:
            df, nm = fetch_naver(code)
            if len(df) >= 5:
                return dict(df=df, naver_name=nm, source="NAVER")
            errs.append("NAVER 데이터 부족")
        except Exception as e:
            errs.append(f"NAVER {e}")
        time.sleep(0.5 * (attempt + 1))
    try:
        df, nm = fetch_yahoo(code)
        return dict(df=df, naver_name=nm, source="YAHOO")
    except Exception as e:
        errs.append(f"YAHOO {e}")
    raise RuntimeError(" / ".join(errs[-2:]))


# --- 지표 · 자동 추세선 ---
def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull(points, lower):
    h = []
    for p in points:
        while len(h) >= 2 and ((_cross(h[-2], h[-1], p) <= 0) if lower else (_cross(h[-2], h[-1], p) >= 0)):
            h.pop()
        h.append(p)
    return h


def trend_line(high, low, kind, lookback, recent, min_span):
    """
    저가(지지) / 고가(저항)의 볼록껍질에서 두 접점 간격이 min_span 이상인 가장 최근 변을 추세선으로 사용.
    최근 recent봉은 선 계산에서 빼서, 그 봉들이 선을 넘으면 '돌파/이탈'로 보이게 함.
    반환: (x1, y1, 기울기) 또는 None
    """
    n = len(low)
    start, stop = max(0, n - lookback), n - recent
    if stop - start < min_span + 1:
        return None
    arr = low if kind == "support" else high
    pts = [(i, float(arr[i])) for i in range(start, stop) if np.isfinite(arr[i])]
    if len(pts) < 2:
        return None
    hull = _hull(pts, lower=(kind == "support"))
    for a, b in reversed(list(zip(hull[:-1], hull[1:]))):
        if b[0] - a[0] >= min_span:
            return (a[0], a[1], (b[1] - a[1]) / (b[0] - a[0]))
    return None


def _line_at(line, x):
    return None if line is None else line[1] + line[2] * (x - line[0])


def calc_stats(df, is_index=False):
    c, v = df["Close"], df["Volume"]
    last = float(c.iloc[-1])
    pct = lambda k: (last / c.iloc[-1 - k] - 1) * 100 if len(c) > k else np.nan
    ma20 = c.rolling(20).mean().iloc[-1]
    vavg = v.iloc[-21:-1].mean() if len(v) > 21 else np.nan
    disp = df.iloc[-DISPLAY_BARS:]
    hi, lo = disp["High"].values, disp["Low"].values
    sup = trend_line(hi, lo, "support", **TREND_LONG)
    res = trend_line(hi, lo, "resistance", **TREND_LONG)
    xl = len(disp) - 1
    sup_v, res_v = _line_at(sup, xl), _line_at(res, xl)
    if res_v is not None and last > res_v * (1 + BREAK_MARGIN):
        trend = "저항선 돌파"
    elif sup_v is not None and last < sup_v * (1 - BREAK_MARGIN):
        trend = "지지선 이탈"
    else:
        trend = "추세선 안"
    return {
        "종가": last,
        "1일%": pct(1), "5일%": pct(5), "20일%": pct(20),
        "52주고가대비%": (last / df["High"].iloc[-250:].max() - 1) * 100,
        "MA20이격%": (last / ma20 - 1) * 100 if pd.notna(ma20) else np.nan,
        "거래대금(억)": np.nan if is_index else last * float(v.iloc[-1]) / 1e8,
        "거래량배수": float(v.iloc[-1]) / vavg if vavg and vavg > 0 else np.nan,
        "추세선": trend,
        "마지막일": df.index[-1].strftime("%Y-%m-%d"),
    }


# --- 차트 그리기 ---
def _fmt_price(x, is_index):
    return f"{x:,.2f}" if is_index else f"{x:,.0f}"


def _fmt_vol(y, _):
    if y >= 1e8: return f"{y/1e8:.1f}{TXT['eok']}"
    if y >= 1e4: return f"{y/1e4:,.0f}{TXT['man']}"
    return f"{y:,.0f}"


def _compress_png(png):
    """128색 팔레트 PNG로 변환 → 용량 약 1/4"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        q = im.quantize(colors=128, method=0, dither=0)
        out = io.BytesIO()
        q.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return png


def render_chart(code, name, df_full, is_index=False):
    d = df_full.copy()
    for w in MA_LIST:
        d[f"MA{w}"] = d["Close"].rolling(w).mean()
    d = d.iloc[-DISPLAY_BARS:]
    n = len(d)
    x = np.arange(n)
    o, h, l, c, v = (d[k].values for k in ["Open", "High", "Low", "Close", "Volume"])
    colors = np.where(c >= o, UP_COLOR, DOWN_COLOR)

    fig = Figure(figsize=FIG_SIZE, dpi=FIG_DPI, facecolor="white")
    gs = fig.add_gridspec(2, 1, height_ratios=[3.3, 1], hspace=0.04)
    ax = fig.add_subplot(gs[0])
    axv = fig.add_subplot(gs[1], sharex=ax)

    pmin, pmax = float(np.nanmin(l)), float(np.nanmax(h))
    pad = (pmax - pmin) * 0.07 or pmax * 0.02
    ylo, yhi = pmin - pad, pmax + pad

    ax.vlines(x, l, h, colors=colors, linewidth=0.9, zorder=2)
    body_h = np.maximum(np.abs(c - o), (yhi - ylo) * 0.0015)
    ax.bar(x, body_h, bottom=np.minimum(o, c), width=0.62, color=colors,
           edgecolor=colors, linewidth=0.5, zorder=3)

    handles = []
    for w in MA_LIST:
        col = MA_COLORS.get(w, "#555555")
        ax.plot(x, d[f"MA{w}"].values, color=col, linewidth=1.1 if w > 5 else 0.9, zorder=4)
        handles.append(Line2D([0], [0], color=col, lw=1.5, label=TXT["ma"].format(w)))

    x_end = n - 1 + TREND_EXTEND
    sets = [(TREND_LONG, "-", 1.6, 0.95)]
    if SHOW_SHORT_TREND:
        sets.append((TREND_SHORT, "--", 1.1, 0.85))
    drew = set()
    for prm, ls, lw, alpha in sets:
        for kind, col in [("support", SUPPORT_COLOR), ("resistance", RESIST_COLOR)]:
            line = trend_line(h, l, kind, **prm)
            if line is None:
                continue
            ax.plot([line[0], x_end], [line[1], _line_at(line, x_end)], color=col,
                    linestyle=ls, linewidth=lw, alpha=alpha, zorder=5)
            drew.add(kind)
    if "support" in drew:
        handles.append(Line2D([0], [0], color=SUPPORT_COLOR, lw=1.6, label=TXT["sup"]))
    if "resistance" in drew:
        handles.append(Line2D([0], [0], color=RESIST_COLOR, lw=1.6, label=TXT["res"]))

    last, prev = c[-1], (df_full["Close"].iloc[-2] if len(df_full) > 1 else c[-1])
    chg = (last / prev - 1) * 100
    lc = UP_COLOR if chg > 0 else DOWN_COLOR if chg < 0 else "#555555"
    ax.axhline(last, color=lc, linestyle=":", linewidth=0.9, zorder=1)
    ax.annotate(_fmt_price(last, is_index), xy=(1.0, last), xycoords=("axes fraction", "data"),
                xytext=(3, 0), textcoords="offset points", va="center", ha="left",
                fontsize=8.5, color="white", fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.25", fc=lc, ec=lc), annotation_clip=False)

    ax.set_xlim(-1, x_end + 1)
    ax.set_ylim(ylo, yhi)
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}"))
    ax.tick_params(axis="x", labelbottom=False, length=0)
    ax.tick_params(axis="y", labelsize=8.5, length=0, pad=4)
    ax.grid(True, color="#E6E6E6", linewidth=0.6)
    for s in ["top", "left"]:
        ax.spines[s].set_visible(False)
    for s in ["right", "bottom"]:
        ax.spines[s].set_color("#CCCCCC")
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=7.5,
              ncol=len(handles), frameon=False, handlelength=1.6, columnspacing=1.0, borderaxespad=0.1)

    title = f"{name}  {code}" if KFONT else code
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=19)
    ax.set_title(f"{_fmt_price(last, is_index)}  {chg:+.2f}%   ({d.index[-1]:%Y-%m-%d})",
                 loc="right", fontsize=10.5, color=lc, pad=19)

    axv.bar(x, v, width=0.62, color=colors, alpha=0.55, zorder=2)
    if n >= 20:
        axv.plot(x, pd.Series(v).rolling(20).mean().values, color="#555555", linewidth=0.9, zorder=3)
    axv.yaxis.tick_right()
    axv.yaxis.set_major_formatter(FuncFormatter(_fmt_vol))
    axv.tick_params(axis="y", labelsize=7.5, length=0, pad=4)
    axv.tick_params(axis="x", labelsize=8.5, length=0)
    axv.set_ylim(0, max(float(np.nanmax(v)), 1) * 1.15)
    axv.grid(True, axis="x", color="#E6E6E6", linewidth=0.6)
    for s in ["top", "left"]:
        axv.spines[s].set_visible(False)
    for s in ["right", "bottom"]:
        axv.spines[s].set_color("#CCCCCC")

    per = d.index.to_period("M")
    ticks = [i for i in range(n) if i == 0 or per[i] != per[i - 1]]
    if len(ticks) > 1 and ticks[1] - ticks[0] < 8:
        ticks = ticks[1:]
    axv.set_xticks(ticks)
    axv.set_xticklabels([f"{d.index[i]:%y.%m}" for i in ticks])

    fig.subplots_adjust(left=0.015, right=0.905, top=0.875, bottom=0.07)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=FIG_DPI, facecolor="white")
    return _compress_png(buf.getvalue())


def _render_job(args):
    """프로세스 병렬용: 지표 계산 + 차트 저장"""
    code, name, df, out_path = args
    is_index = code in INDEX_CODES
    stats = calc_stats(df, is_index)
    with open(out_path, "wb") as f:
        f.write(render_chart(code, name, df, is_index))
    return code, stats


# --- 섹터 강도 ---
def sector_table(summary):
    stk = summary[~summary["섹션"].isin(ETF_SECTIONS)]
    if not len(stk):
        return []
    sec = (stk.groupby("섹션", sort=False)
              .agg(종목수=("코드", "count"),
                   **{"평균 1일%": ("1일%", "mean"), "평균 5일%": ("5일%", "mean"),
                      "평균 20일%": ("20일%", "mean"), "거래대금 합(억)": ("거래대금(억)", "sum")},
                   MA20위=("MA20이격%", lambda s: int((s > 0).sum())),
                   저항돌파=("추세선", lambda s: int((s == "저항선 돌파").sum())),
                   지지이탈=("추세선", lambda s: int((s == "지지선 이탈").sum())))
              .reset_index()
              .sort_values("평균 5일%", ascending=False))
    return _records(sec)


def _records(df):
    out = []
    for r in df.to_dict("records"):
        rec = {}
        for k, v in r.items():
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (float, np.floating)):
                v = None if pd.isna(v) else round(float(v), 4)
            rec[k] = v
        out.append(rec)
    return out


def _gh_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


# --- 메인 ---
def main():
    trigger = os.environ.get("TRIGGER") or os.environ.get("GITHUB_EVENT_NAME") or "local"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    wf_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    m = re.search(r"\.github/workflows/([^@]+)@", wf_ref)
    workflow = m.group(1) if m else "daily.yml"
    t_start = time.time()

    sections = SECTIONS
    codes = list(dict.fromkeys(c for _, it in sections for c, _, _ in it))
    label = {}
    for _, it in sections:
        for c, nm, _ in it:
            label.setdefault(c, nm)

    print(f"[1/3] 일봉 데이터 수신: {len(codes)}개 (트리거: {trigger})")
    data, failed = {}, {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_one, c): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            try:
                data[c] = f.result()
            except Exception as e:
                failed[c] = str(e)[:200]
    n_yahoo = sum(1 for d in data.values() if d["source"] == "YAHOO")
    print(f"      성공 {len(data)} / 실패 {len(failed)} (야후 폴백 {n_yahoo})")
    for c, e in failed.items():
        print(f"      실패: {c} {label.get(c, '')} -> {e}")
    if len(data) < len(codes) * MIN_SUCCESS:
        print(f"[중단] 수신 성공률이 {MIN_SUCCESS:.0%} 미만입니다. 배포하지 않습니다.")
        sys.exit(1)

    last_dates = pd.Series({c: d["df"].index[-1] for c, d in data.items()})
    ref_date = last_dates.mode().iloc[0]
    today_kst = dt.datetime.now(KST).date()
    if trigger == "schedule" and ref_date.date() != today_kst:
        print(f"[건너뜀] 오늘({today_kst})은 거래일이 아닙니다 (최근 거래일 {ref_date.date()}). 기존 페이지 유지.")
        _gh_output(skip="true", ref_date=str(ref_date.date()))
        return

    norm = lambda s: re.sub(r"[\s\.\-&()·]", "", str(s)).lower()
    mismatch = [{"code": c, "mine": label[c], "naver": d["naver_name"]} for c, d in data.items()
                if d.get("naver_name") and c not in INDEX_CODES and norm(d["naver_name"]) != norm(label[c])]
    for mm in mismatch:
        print(f"      종목명 불일치: {mm['code']} 리스트='{mm['mine']}' / 네이버='{mm['naver']}'")

    # 출력 폴더 새로 만들기
    if os.path.isdir(SITE_DIR):
        shutil.rmtree(SITE_DIR)
    os.makedirs(os.path.join(SITE_DIR, "charts"))
    os.makedirs(os.path.join(SITE_DIR, "data"))

    print(f"[2/3] 차트 생성: {len(data)}개 (프로세스 {RENDER_PROCS}개)")
    jobs = [(c, label[c], data[c]["df"], os.path.join(SITE_DIR, "charts", f"{c}.png"))
            for c in codes if c in data]
    stats = {}
    t0 = time.time()
    try:
        if RENDER_PROCS > 1:
            with ProcessPoolExecutor(max_workers=RENDER_PROCS) as ex:
                for code, st in ex.map(_render_job, jobs, chunksize=4):
                    stats[code] = st
        else:
            raise RuntimeError("single")
    except Exception as e:
        if str(e) != "single":
            print(f"      병렬 생성 실패 → 순차 생성으로 전환 ({e})")
        for job in jobs:
            if job[0] in stats:
                continue
            try:
                code, st = _render_job(job)
                stats[code] = st
            except Exception as e2:
                failed[job[0]] = f"차트 오류: {e2}"[:200]
    print(f"      완료 {len(stats)}개 ({time.time() - t0:.0f}초)")

    rows = []
    for s, it in sections:
        for c, nm, desc in it:
            if c in stats:
                rows.append({"섹션": s, "종목": nm, "코드": c, "설명": desc, **stats[c],
                             "_etf": s in ETF_SECTIONS, "_idx": c in INDEX_CODES})
    summary = pd.DataFrame(rows)

    now = dt.datetime.now(KST)
    meta = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "updated_iso": now.isoformat(timespec="seconds"),
        "build_id": now.strftime("%Y%m%d%H%M%S"),
        "ref_date": ref_date.strftime("%Y-%m-%d"),
        "trigger": trigger,
        "repo": repo, "branch": branch, "workflow": workflow,
        "n_total": len(codes), "n_ok": len(stats), "n_yahoo": n_yahoo,
        "failed": [{"code": c, "name": label.get(c, ""), "error": e} for c, e in failed.items()],
        "mismatch": mismatch,
        "ma": MA_LIST, "display_bars": DISPLAY_BARS,
        "build_seconds": round(time.time() - t_start),
    }
    payload = {
        "meta": meta,
        "sections": [{"name": s, "etf": s in ETF_SECTIONS} for s, _ in sections],
        "sector_table": sector_table(summary) if len(summary) else [],
        "rows": _records(summary) if len(summary) else [],
        "colors": {"up": UP_COLOR, "down": DOWN_COLOR},
    }
    js = json.dumps(payload, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    print("[3/3] 페이지 생성")
    with open(os.path.join(SITE_DIR, "data", "summary.js"), "w", encoding="utf-8") as f:
        f.write("window.__krsc_summary && window.__krsc_summary(" + js + ");\n")
    shutil.copy(os.path.join(WEB_DIR, "index.html"), os.path.join(SITE_DIR, "index.html"))
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()

    size_mb = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(SITE_DIR) for f in fs) / 1e6
    print(f"      site/ {size_mb:.1f}MB · 업데이트 {meta['updated_at']} · 기준일 {meta['ref_date']} "
          f"· 총 {meta['build_seconds']}초")
    _gh_output(skip="false", ref_date=meta["ref_date"])


if __name__ == "__main__":
    main()
