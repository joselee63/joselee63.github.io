# ======================================
# 종목별 · 매매주체별 · 일자별 거래대금 수집 (KRX 정보데이터시스템, pykrx)
#   · 대상: stocks.py 의 한국 일반 종목 (ETF·지수 제외 — KRX 투자자 조회가 ETF 를 지원하지 않음)
#   · 저장: <데이터 폴더>/investor/YYYY/YYYY-MM.csv  (월별 파일, 전 종목, 금액 단위 = 원)
#       열: 날짜, 코드, 종목, {주체}_매수, {주체}_매도, {주체}_순매수 …
#       주체: 개인 · 외국인 · 기타외국인 · 기관계 · 금융투자 · 보험 · 투신 · 사모 · 은행 · 기타금융 · 연기금 · 기타법인 · 전체
#       기관계 = 금융투자 + 보험 + 투신 + 사모 + 은행 + 기타금융 + 연기금
#   · 처음: 종목마다 최근 YEARS 년치 / 이후: 마지막 저장일 3일 전부터 다시 받아 덮어씀 (KRX 사후 수정 반영)
#   · 진행 상황: <데이터 폴더>/investor/_state.json (종목별 마지막 저장일) — 실패한 종목은 다음 실행 때 다시
#   · 실행: KRX_ID=… KRX_PW=… python tools/investor_data.py <데이터 폴더>
# ======================================
import os, sys, json, time, warnings
import datetime as dt
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stocks import SECTIONS, ETF_SECTIONS

YEARS = int(os.environ.get("INVESTOR_YEARS", "5"))
OVERLAP_DAYS = 3                                  # 매일 최근 3일은 다시 받아 덮어씀
DELAY = 0.3                                       # 요청 사이 쉬는 시간(초) — KRX 서버 배려
KST = dt.timezone(dt.timedelta(hours=9))
INST = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
ORDER = ["개인", "외국인", "기타외국인", "기관계"] + INST + ["기타법인", "전체"]
SIDES = ["매수", "매도", "순매수"]
COLS = ["날짜", "코드", "종목"] + [f"{p}_{s}" for p in ORDER for s in SIDES]


def universe():
    seen, out = set(), []
    for sec, items in SECTIONS:
        if sec in ETF_SECTIONS:
            continue
        for code, name, _ in items:
            if code.isdigit() and code not in seen:
                seen.add(code)
                out.append((code, name))
    return out


def fetch(code, start, end):
    """한 종목의 기간 데이터 → DataFrame(COLS). 매수·매도 상세를 받아 순매수와 기관계를 계산"""
    from pykrx import stock
    got = {}
    for side in ("매수", "매도"):
        for attempt in range(3):
            try:
                df = stock.get_market_trading_value_by_date(start, end, code, on=side, detail=True)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        time.sleep(DELAY)
        if df is None or df.empty:
            return None
        got[side] = df
    b, s = got["매수"], got["매도"]
    idx = b.index.intersection(s.index)
    b, s = b.loc[idx], s.loc[idx]
    out = pd.DataFrame(index=idx)
    for p in ORDER:
        if p == "기관계":
            bv, sv = b[INST].sum(axis=1), s[INST].sum(axis=1)
        else:
            bv, sv = b[p], s[p]
        out[f"{p}_매수"], out[f"{p}_매도"], out[f"{p}_순매수"] = bv, sv, bv - sv
    out = out.astype("int64")
    out.insert(0, "날짜", [d.strftime("%Y-%m-%d") for d in idx])
    return out.reset_index(drop=True)


def write_months(base, new):
    """새 행을 월별 CSV 에 합침 (같은 날짜·종목은 새 값으로 교체)"""
    new["월"] = new["날짜"].str.slice(0, 7)
    for month, part in new.groupby("월"):
        part = part.drop(columns="월")
        path = os.path.join(base, month[:4], f"{month}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            old = pd.read_csv(path, dtype={"코드": str}, encoding="utf-8-sig")
            key = set(zip(part["날짜"], part["코드"]))
            old = old[[k not in key for k in zip(old["날짜"], old["코드"])]]
            part = pd.concat([old, part], ignore_index=True)
        part = part.sort_values(["날짜", "코드"])[COLS]
        part.to_csv(path, index=False, encoding="utf-8-sig")


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data")
    base = os.path.join(data_dir, "investor")
    os.makedirs(base, exist_ok=True)
    state_path = os.path.join(base, "_state.json")
    state = json.load(open(state_path, encoding="utf-8")) if os.path.exists(state_path) else {}

    today = dt.datetime.now(KST).date()
    first = today.replace(year=today.year - YEARS)
    codes = universe()
    if os.environ.get("INVESTOR_LIMIT"):                 # 시험 실행: 앞쪽 N종목만
        codes = codes[:int(os.environ["INVESTOR_LIMIT"])]
    print(f"[투자자 데이터] 대상 {len(codes)}종목 · 처음 {YEARS}년 · 오늘 {today}")
    from pykrx import stock  # noqa: F401  (import 시 KRX 로그인)

    rows, failed, t0, saved = [], [], time.time(), [0]

    def flush():                                  # 50종목마다 디스크에 저장 → 중간에 끊겨도 받은 만큼은 남음
        if rows:
            new = pd.concat(rows, ignore_index=True)
            write_months(base, new)
            saved[0] += len(new)
            rows.clear()
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(state.items())), f, ensure_ascii=False, indent=0)

    for i, (code, name) in enumerate(codes, 1):
        last = state.get(code)
        start = (dt.date.fromisoformat(last) - dt.timedelta(days=OVERLAP_DAYS)) if last else first
        if start > today:
            continue
        try:
            df = fetch(code, start.strftime("%Y%m%d"), today.strftime("%Y%m%d"))
        except Exception as e:
            failed.append(code)
            print(f"  실패 {code} {name}: {type(e).__name__}: {str(e)[:150]}")
            continue
        if df is None or df.empty:
            continue
        df.insert(1, "코드", code)
        df.insert(2, "종목", name)
        rows.append(df)
        state[code] = df["날짜"].iloc[-1]
        if i % 50 == 0:
            flush()
            print(f"  {i}/{len(codes)} · {time.time() - t0:.0f}초 · 누적 {saved[0]:,}행")

    flush()
    print(f"[완료] {time.time() - t0:.0f}초 · 저장 {saved[0]:,}행 · 실패 {len(failed)}종목" + (f" ({', '.join(failed[:10])})" if failed else ""))
    if len(failed) > len(codes) * 0.3:
        sys.exit(1)


if __name__ == "__main__":
    main()
