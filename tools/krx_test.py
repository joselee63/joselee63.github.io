# ======================================
# KRX 종목별 투자자 거래대금 수집 테스트 (GitHub Actions 에서 실행)
#   · pykrx 가 환경 변수 KRX_ID · KRX_PW 로 KRX 정보데이터시스템에 로그인
#   · 계정 정보는 출력하지 않고, 받아진 행 수·기간·소요 시간만 출력
# ======================================
import os, sys, time, warnings
warnings.filterwarnings("ignore")

print("계정 환경 변수:", "있음" if os.environ.get("KRX_ID") and os.environ.get("KRX_PW") else "없음")
from pykrx import stock

ok = True
tests = [
    ("5년 한 번에 · 매수 상세 · 삼성전자", lambda: stock.get_market_trading_value_by_date("20211018", "20261016", "005930", on="매수", detail=True)),
    ("5년 한 번에 · 매도 상세 · 삼성전자", lambda: stock.get_market_trading_value_by_date("20211018", "20261016", "005930", on="매도", detail=True)),
    ("5년 한 번에 · 매수 상세 · 에코프로(코스닥)", lambda: stock.get_market_trading_value_by_date("20211018", "20261016", "086520", on="매수", detail=True)),
    ("5년 한 번에 · 매수 상세 · KODEX 200(ETF)", lambda: stock.get_market_trading_value_by_date("20211018", "20261016", "069500", on="매수", detail=True)),
    ("최근 5일 · 매수 상세 · 삼성전자", lambda: stock.get_market_trading_value_by_date("20261012", "20261016", "005930", on="매수", detail=True)),
]
for name, fn in tests:
    t0 = time.time()
    try:
        df = fn()
        dt = time.time() - t0
        rng = f"{df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}" if len(df) else "-"
        print(f"[{name}] 행 {len(df)} · 기간 {rng} · {dt:.1f}초 · 열 {list(df.columns)}")
        if not len(df):
            ok = False
    except Exception as e:
        ok = False
        print(f"[{name}] 실패 ({time.time() - t0:.1f}초): {type(e).__name__}: {str(e)[:300]}")
print("결과:", "성공" if ok else "실패")
sys.exit(0 if ok else 1)
