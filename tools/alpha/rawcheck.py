"""수정주가 권리락일 시가 갭 검증: KRX 원주가(로그인 필요)로 시가÷(전일종가÷비율)−1 을 계산해 수정주가 갭과 비교.
GitHub Actions(alpha-check.yml)에서 실행. 입력 tools/alpha/rawcheck.csv"""
import time
from pathlib import Path
import pandas as pd
from pykrx import stock

df = pd.read_csv(Path(__file__).with_name("rawcheck.csv"), dtype={"ticker": str, "exdate": str})
rows = []
for r in df.itertuples():
    e = pd.Timestamp(r.exdate)
    try:
        a = stock.get_market_ohlcv((e - pd.Timedelta(days=10)).strftime("%Y%m%d"), r.exdate, r.ticker, adjusted=False)
    except Exception as ex:  # noqa: BLE001
        print(r.name, "EXC", ex); continue
    time.sleep(0.5)
    if a is None or len(a) < 2:
        print(r.name, "없음"); continue
    pc, op = a["종가"].iloc[-2], a["시가"].iloc[-1]
    raw_gap = op / (pc / r.ratio) - 1
    rows.append((r.name, r.exdate, r.ratio, r.adj_gap, raw_gap))
    print(f"{r.name} {r.exdate} 비율 {r.ratio:.2f} 수정갭 {r.adj_gap:+.2%} 원주가갭 {raw_gap:+.2%} 원 전일종가 {pc} 권리락시가 {op}")
t = pd.DataFrame(rows, columns=["name", "ex", "ratio", "adj", "raw"])
print(f"표본 {len(t)} · 평균 수정갭 {t.adj.mean():+.2%} 원주가갭 {t.raw.mean():+.2%} · |차|>1%p {((t.adj-t.raw).abs()>0.01).sum()}건")
