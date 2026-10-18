# ======================================
# KRX 종목별 투자자 거래대금 수집 테스트 (GitHub Actions 에서 실행)
#   · pykrx 가 환경 변수 KRX_ID · KRX_PW 로 KRX 정보데이터시스템에 로그인
#   · 계정 정보는 출력하지 않고, 받아진 행 수와 일부 값만 출력
# ======================================
import os, sys, warnings
warnings.filterwarnings("ignore")

print("계정 환경 변수:", "있음" if os.environ.get("KRX_ID") and os.environ.get("KRX_PW") else "없음")
from pykrx import stock

ok = True
tests = [
    ("투자자별 순매수 거래대금 (일자별, 삼성전자)",
     lambda: stock.get_market_trading_value_by_date("20261001", "20261016", "005930")),
    ("투자자별 매수 거래대금 상세 (일자별, 삼성전자)",
     lambda: stock.get_market_trading_value_by_date("20261001", "20261016", "005930", on="매수", detail=True)),
    ("투자자별 순매수 거래대금 (일자별, 에코프로 · 코스닥)",
     lambda: stock.get_market_trading_value_by_date("20261001", "20261016", "086520")),
]
for name, fn in tests:
    try:
        df = fn()
        print(f"[{name}] 행 {len(df)} · 열 {list(df.columns)}")
        if len(df):
            print(df.tail(3).to_string())
        else:
            ok = False
    except Exception as e:
        ok = False
        print(f"[{name}] 실패: {type(e).__name__}: {str(e)[:300]}")
    print("-" * 60)
print("결과:", "성공" if ok else "실패")
sys.exit(0 if ok else 1)
