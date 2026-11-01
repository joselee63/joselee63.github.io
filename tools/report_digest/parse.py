"""채널 글 → 구조화 리포트 레코드. parse_all(글 목록) → 레코드 목록 (중복 제거)
채널 글 형식: [태그/태그] / 제목: / 작성자: (증권사) / 투자의견: / 목표주가: / [소제목] · 요점 ...  + PDF 파일명 '…_증권사_YYMMDD.pdf'
2026-02 부터 이 형식(구조화 요약)이 붙음. 그 전 글은 파일명뿐이라 쓰지 않음.
"""
import collections, csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------- 증권사 이름 정규화 ----------
BROKERS = [  # (정식 이름, 별칭들)
    ("하나증권", ["하나증권", "하나금융투자", "Hana"]), ("삼성증권", ["삼성증권", "Samsung Securities", "삼성증"]),
    ("대신증권", ["대신증권", "Daishin", "대신증"]), ("키움증권", ["키움증권", "Kiwoom"]),
    ("유진투자증권", ["유진투자증권", "유진증권", "Eugene"]), ("미래에셋증권", ["미래에셋증권", "미래에셋대우", "Mirae Asset"]),
    ("한화투자증권", ["한화투자증권", "한화투자", "Hanwha"]), ("유안타증권", ["유안타증권", "유안타", "Yuanta"]),
    ("SK증권", ["SK증권", "SK 증권"]), ("메리츠증권", ["메리츠증권", "Meritz"]), ("교보증권", ["교보증권"]),
    ("IBK투자증권", ["IBK투자증권", "IBK투자증", "IBK투자"]), ("iM증권", ["iM증권", "IM증권", "하이투자증권", "하이투자"]),
    ("신한투자증권", ["신한투자증권", "신한금융투자", "신한투자"]), ("DS투자증권", ["DS투자증권", "DS투자"]),
    ("현대차증권", ["현대차증권", "현대차증"]), ("다올투자증권", ["다올투자증권", "DAOL"]),
    ("LS증권", ["LS증권", "이베스트투자증권", "이베스트"]), ("신영증권", ["신영증권"]),
    ("상상인증권", ["상상인증권", "상상인"]), ("BNK투자증권", ["BNK투자증권"]), ("NH투자증권", ["NH투자증권", "NH Investment"]),
    ("흥국증권", ["흥국증권"]), ("DB증권", ["DB증권", "DB금융투자"]), ("한국투자증권", ["한국투자증권"]),
    ("KB증권", ["KB증권"]), ("한양증권", ["한양증권"]), ("부국증권", ["부국증권"]), ("리딩투자증권", ["리딩투자증권"]),
    ("케이프투자증권", ["케이프투자증권"]), ("카카오페이증권", ["카카오페이증권"]), ("우리투자증권", ["우리투자증권"]),
    ("한국IR협의회", ["한국IR협의회", "기업리서치센터"]), ("KIS자산평가", ["KIS자산평가"]),
    ("삼성선물", ["삼성선물"]), ("NH선물", ["NH선물"]), ("우리은행", ["우리은행"]), ("KB국민은행", ["KB국민은행", "국민은행"]),
    ("신한은행", ["신한은행"]), ("KDB산업은행", ["KDB산업은행", "산업은행"]), ("iM뱅크", ["iM뱅크"]), ("한국은행", ["한국은행"]),
    ("한국기업평가", ["한국기업평가"]), ("서울평가정보", ["서울평가정보"]), ("NICE평가정보", ["NICE평가정보"]),
    ("통계청", ["통계청"]), ("국제금융센터", ["국제금융센터"]),
]
ALIAS = sorted(((a, n) for n, al in BROKERS for a in al), key=lambda x: -len(x[0]))
GROUP = {n: ("은행·선물" if any(k in n for k in ("은행", "선물", "뱅크")) and n != "한국은행" else
             "평가·기관" if n in ("한국IR협의회", "KIS자산평가", "한국기업평가", "서울평가정보", "NICE평가정보", "한국은행", "통계청", "국제금융센터") else "증권사")
         for n, _ in BROKERS}


def find_broker(*texts):
    for t in texts:
        if not t:
            continue
        for a, n in ALIAS:
            if a in t:
                return n
    return None


# ---------- 상장 종목 사전 (KRX 업종 분류 2026-10-01 스냅샷) ----------
STOCK = {}   # 이름 → (코드, 시장, KRX업종)
_CLS = ROOT / "data-backtest/sectors/classifications.csv"          # 업종 분류 분기 스냅샷 (가장 최근 것)
if _CLS.exists():
    with open(_CLS, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    last = max(r["date"] for r in rows)
    for r in rows:
        if r["date"] == last:
            STOCK[r["name"]] = (r["ticker"], r["market"], r["sector"])
_snaps = sorted((ROOT / "radar-out/snap").glob("*/krx_close.json")) if (ROOT / "radar-out/snap").exists() else []
if _snaps:                                                          # 새로 상장한 종목 보충 (레이더가 저장한 전 종목 종가)
    for code, v in json.loads(_snaps[-1].read_text(encoding="utf-8")).items():
        if v.get("n") and v["n"] not in STOCK:
            STOCK[v["n"]] = (code, "", "")
CODE2NAME = {v[0]: k for k, v in STOCK.items()}
ALIAS_STOCK = {"현대자동차": "현대차", "네이버": "NAVER", "하이닉스": "SK하이닉스", "포스코홀딩스": "POSCO홀딩스", "S-OIL": "S-Oil",
               "에쓰오일": "S-Oil", "KT_G": "KT&G", "LG엔솔": "LG에너지솔루션", "삼바": "삼성바이오로직스", "한전": "한국전력",
               "삼성SDS": "삼성에스디에스", "하이브": "HYBE", "JYP": "JYP Ent.", "SM": "에스엠", "YG": "와이지엔터테인먼트", "HD현대일렉": "HD현대일렉트릭",
               "한국조선해양": "HD한국조선해양", "현대중공업": "HD현대중공업", "LG화학우": "LG화학", "삼성전자우": "삼성전자", "하나금융": "하나금융지주",
               "우리금융": "우리금융지주", "신한금융": "신한지주", "BNK금융": "BNK금융지주", "JB금융": "JB금융지주", "iM금융": "iM금융지주",
               "한국금융": "한국금융지주", "에이피알": "에이피알", "LS일렉트릭": "LS ELECTRIC", "포스코퓨처엠": "포스코퓨처엠"}
for k, v in list(ALIAS_STOCK.items()):
    if v not in STOCK:
        ALIAS_STOCK.pop(k)
AMBIG = {"대상", "태양", "동방", "국보", "서원", "한창", "진도", "대원", "신일", "동양", "세방", "삼영", "대유", "유니온", "이수", "디오", "선진",
         "코리아", "에스엘", "경방", "금양", "흥국", "신영", "한양", "부국", "교보", "다올", "상상인", "유진", "키움", "대신", "메리츠",
         "한국", "현대", "삼성", "미래", "제일", "오리엔트", "에이스", "배럴", "하이텍", "전방", "남선", "동원", "레이", "알톤", "윈스", "나라",
         "이노", "그린", "로보", "대한", "한일", "우진", "HD현대", "코스모", "NH", "DB", "BNK", "iM", "KB", "IBK", "DS", "HL", "E1",
         "SK", "LG", "GS", "CJ", "LS", "KT", "효성", "한화", "롯데", "두산", "OCI", "BGF", "SKC", "대원", "신세계", "현대차증권", "한화투자증권",
         "유안타증권", "SK증권", "교보증권", "다올투자증권", "상상인증권", "부국증권", "한양증권", "유진투자증권", "DB증권", "iM증권", "흥국증권",
         "케이프", "에코", "디앤디", "인터로조", "정상제이엘에스", "AI", "에이아이", "아이엠", "파트론", "원익", "동국", "세아", "풍국", "삼양",
         "모두투어", "하나투어", "이노션", "테스", "피에스케이", "미래산업", "신성이엔지", "일진", "에스에프에이", "씨젠", "엘앤에프"}
AMBIG -= {"이노션", "테스", "피에스케이", "씨젠", "엘앤에프", "하나투어", "모두투어", "파트론", "에스에프에이", "인터로조", "신세계",
          "효성", "한화", "롯데", "두산", "OCI", "SKC", "KT", "LS"}
NAMES = sorted([n for n in STOCK if n not in AMBIG and len(n) >= 2], key=len, reverse=True)
NAME_RE = re.compile("(?<![가-힣A-Za-z])(" + "|".join(re.escape(n) for n in NAMES) + ")(?![가-힣A-Za-z])|(" +
                     "|".join(re.escape(n) for n in NAMES if len(n) >= 4) + ")")


def clean_subj(s):
    s = re.sub(r"\(\s*[A-Z]?\d{6}\s*(?:KS|KQ)?\s*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip(" []")
    return s


def match_stock(s):
    if not s:
        return None
    s = clean_subj(s)
    s2 = s.replace(" ", "")
    for cand in (s, s2, ALIAS_STOCK.get(s), ALIAS_STOCK.get(s2)):
        if cand and cand in STOCK:
            return cand
    return None


# ---------- 산업 정규화 (태그·제목 키워드 → 표준 산업) ----------
IND = [
    ("반도체", ["반도체", "HBM", "메모리", "파운드리", "D램", "DRAM", "낸드", "NAND", "후공정", "OSAT", "Semiconductor"]),
    ("2차전지", ["2차전지", "이차전지", "배터리", "Battery", "양극재", "음극재", "전해질", "리튬", "ESS"]),
    ("조선", ["조선", "Shipbuilding"]), ("방산", ["방산", "방위", "Defense", "우주항공", "우주", "항공우주"]),
    ("자동차", ["자동차", "완성차", "모빌리티", "자동차부품", "타이어", "Auto"]),
    ("전력·원전", ["원전", "원자력", "전력기기", "전력", "변압기", "전선", "SMR", "유틸리티", "가스", "Utilities"]),
    ("기계·로봇", ["로봇", "로보틱스", "Robot", "기계", "건설기계", "공작기계", "피지컬 AI"]),
    ("건설·건자재", ["건설", "건자재", "시멘트", "인프라", "부동산", "리츠", "REITs", "REIT"]),
    ("정유·화학", ["정유", "석유화학", "화학", "에너지", "Oil", "정제마진", "태양광", "폴리실리콘", "수소", "Energy", "Chemical"]),
    ("철강·금속", ["철강", "비철", "금속", "아연", "구리", "Steel", "Metal"]),
    ("바이오·헬스케어", ["바이오", "제약", "헬스케어", "의료", "비만", "Bio", "Pharma", "임상", "신약", "CDMO", "미용", "Healthcare"]),
    ("인터넷·게임", ["인터넷", "플랫폼", "게임", "Game", "Internet", "커머스"]),
    ("미디어·엔터", ["미디어", "엔터", "콘텐츠", "광고", "K-pop", "K-POP", "음악", "레저", "카지노", "여행", "Media"]),
    ("통신", ["통신", "Telecom"]),
    ("소프트웨어·AI", ["소프트웨어", "Software", "AI", "클라우드", "데이터센터", "IT서비스", "SaaS", "Tech", "테크"]),
    ("IT하드웨어·부품", ["전자부품", "IT부품", "디스플레이", "OLED", "PCB", "기판", "MLCC", "카메라모듈", "IT하드웨어", "스마트폰", "전기전자", "가전", "IT"]),
    ("은행", ["은행", "Bank", "금융지주"]), ("보험", ["보험", "손해보험", "생명보험", "손보", "생보", "Insurance"]),
    ("증권·금융", ["증권", "금융", "카드", "캐피탈", "지주", "Financials"]),
    ("유통·소비재", ["유통", "음식료", "식품", "화장품", "의류", "패션", "소비재", "담배", "주류", "편의점", "면세", "홈쇼핑", "Consumer", "생활용품", "Retail"]),
    ("운송·물류", ["운송", "해운", "항공", "물류", "택배", "Shipping", "Airline"]),
]
KRX2IND = {"전기·전자": "IT하드웨어·부품", "화학": "정유·화학", "제약": "바이오·헬스케어", "의료·정밀기기": "바이오·헬스케어", "운송장비·부품": "자동차",
           "기계·장비": "기계·로봇", "금속": "철강·금속", "건설": "건설·건자재", "유통": "유통·소비재", "음식료·담배": "유통·소비재",
           "섬유·의류": "유통·소비재", "운송·창고": "운송·물류", "통신": "통신", "전기·가스": "전력·원전", "보험": "보험", "은행": "은행",
           "증권": "증권·금융", "기타금융": "증권·금융", "IT 서비스": "소프트웨어·AI", "오락·문화": "미디어·엔터", "일반서비스": "미디어·엔터",
           "비금속": "건설·건자재", "종이·목재": "유통·소비재", "출판·매체복제": "미디어·엔터", "기타제조": "유통·소비재", "부동산": "건설·건자재",
           "금융": "증권·금융", "제조": "유통·소비재", "운송장비": "자동차", "섬유": "유통·소비재"}
STOCK_IND_FIX = {"삼성전자": "반도체", "SK하이닉스": "반도체", "한미반도체": "반도체", "LG에너지솔루션": "2차전지", "삼성SDI": "2차전지",
                 "에코프로비엠": "2차전지", "포스코퓨처엠": "2차전지", "에코프로": "2차전지", "엘앤에프": "2차전지", "NAVER": "인터넷·게임", "카카오": "인터넷·게임",
                 "크래프톤": "인터넷·게임", "엔씨소프트": "인터넷·게임", "넷마블": "인터넷·게임", "한화에어로스페이스": "방산", "LIG넥스원": "방산",
                 "한국항공우주": "방산", "현대로템": "방산", "HD현대중공업": "조선", "삼성중공업": "조선", "한화오션": "조선", "HD한국조선해양": "조선",
                 "HD현대미포": "조선", "두산에너빌리티": "전력·원전", "HD현대일렉트릭": "전력·원전", "LS ELECTRIC": "전력·원전", "효성중공업": "전력·원전",
                 "한국전력": "전력·원전", "KB금융": "은행", "신한지주": "은행", "하나금융지주": "은행", "우리금융지주": "은행", "BNK금융지주": "은행",
                 "JB금융지주": "은행", "iM금융지주": "은행", "기업은행": "은행", "카카오뱅크": "은행", "삼성생명": "보험", "삼성화재": "보험",
                 "DB손해보험": "보험", "현대해상": "보험", "한화생명": "보험", "SK텔레콤": "통신", "KT": "통신", "LG유플러스": "통신",
                 "LG전자": "IT하드웨어·부품", "삼성전기": "IT하드웨어·부품", "LG이노텍": "IT하드웨어·부품", "LG디스플레이": "IT하드웨어·부품",
                 "SK이노베이션": "정유·화학", "S-Oil": "정유·화학", "OCI홀딩스": "정유·화학", "한화솔루션": "정유·화학", "LG화학": "정유·화학",
                 "POSCO홀딩스": "철강·금속", "고려아연": "철강·금속", "현대제철": "철강·금속", "삼성바이오로직스": "바이오·헬스케어",
                 "셀트리온": "바이오·헬스케어", "알테오젠": "바이오·헬스케어", "유한양행": "바이오·헬스케어", "한미약품": "바이오·헬스케어",
                 "HYBE": "미디어·엔터", "JYP Ent.": "미디어·엔터", "에스엠": "미디어·엔터", "와이지엔터테인먼트": "미디어·엔터", "CJ ENM": "미디어·엔터",
                 "삼성물산": "건설·건자재", "현대건설": "건설·건자재", "삼성에스디에스": "소프트웨어·AI", "현대오토에버": "소프트웨어·AI",
                 "두산밥캣": "기계·로봇", "레인보우로보틱스": "기계·로봇", "두산로보틱스": "기계·로봇", "로보티즈": "기계·로봇", "HD현대건설기계": "기계·로봇",
                 "대한항공": "운송·물류", "HMM": "운송·물류", "CJ대한통운": "운송·물류", "KT&G": "유통·소비재", "아모레퍼시픽": "유통·소비재",
                 "BGF리테일": "유통·소비재", "이마트": "유통·소비재", "삼성증권": "증권·금융", "미래에셋증권": "증권·금융", "키움증권": "증권·금융",
                 "한국금융지주": "증권·금융", "NH투자증권": "증권·금융", "현대차": "자동차", "기아": "자동차", "현대모비스": "자동차", "HL만도": "자동차",
                 "한온시스템": "자동차", "삼성E&A": "건설·건자재", "GS건설": "건설·건자재", "DL이앤씨": "건설·건자재", "대우건설": "건설·건자재"}


def _kw(k):
    return re.compile(r"(?<![A-Za-z])" + re.escape(k) + r"(?![A-Za-z])") if re.fullmatch(r"[A-Za-z][A-Za-z\- ]*", k) else re.compile(re.escape(k))


IND_RE = [(n, [_kw(k) for k in kws]) for n, kws in IND]


def ind_from_text(t):
    if not t:
        return None
    for name, kws in IND_RE:
        for k in kws:
            if k.search(t):
                return name
    return None


def strip_brokers(t):
    for a, _ in ALIAS:
        t = t.replace(a, " ")
    return t


FOREIGN_HINT = re.compile(r"미국\s*주식|미국주식|해외기업|해외 기업|미국기업|미국 기업|\.US\b|_US_|\bUS\b|NYSE|NASDAQ|Nasdaq|나스닥|홍콩|\.HK\b|"
                          r"일본\s*기업|중국\s*기업|대만\s*기업|글로벌\s*기업|Global Company|해외주식|해외 주식|Issue[_ &]+News|Preview_|ADR")


MACRO_TOPICS = [
    ("금리·채권", ["채권", "금리", "Credit", "크레딧", "국고채", "회사채", "Fixed Income", "FICC", "Bond", "듀레이션", "KIS", "신용", "Rates"]),
    ("통화정책", ["FOMC", "연준", "Fed", "ECB", "BOJ", "통화정책", "금통위", "기준금리", "중앙은행"]),
    ("환율·외환", ["환율", "외환", "FX", "원/달러", "달러", "원화", "Currency", "선물", "은행"]),
    ("원자재·유가", ["원자재", "유가", "Commodity", "금 가격", "금값", "WTI", "OPEC", "농산물", "Oil"]),
    ("경제지표", ["경제", "GDP", "CPI", "물가", "고용", "수출", "PMI", "소비", "매크로", "Macro", "산업활동", "경기", "한국은행", "통계청", "Economy"]),
    ("자산배분·퀀트·ETF", ["자산배분", "퀀트", "Quant", "ETF", "펀드", "포트폴리오", "Allocation", "파생", "옵션"]),
    ("증시 전략·시황", ["시황", "전략", "Strategy", "증시", "주식시장", "KOSPI", "코스피", "코스닥", "Market", "마감", "모닝", "Morning",
                    "Weekly", "위클리", "주간", "수급", "밸류업", "전망", "Outlook", "Daily"]),
]
MACRO_HINT = ["경제", "매크로", "Macro", "채권", "금리", "Credit", "크레딧", "FICC", "환율", "외환", "FX", "통화정책", "FOMC", "연준", "ECB", "BOJ",
              "시황", "전략", "Strategy", "증시", "주식시장", "자산배분", "퀀트", "Quant", "ETF", "원자재", "Commodity", "투자전략",
              "물가", "GDP", "고용", "한국은행", "통계청", "Morning", "모닝", "글로벌 전략", "Global Strategy", "마감 시황", "Economy", "Rates"]


MACRO_RE = [(n, [_kw(k) for k in kws]) for n, kws in MACRO_TOPICS]


def macro_topic(t):
    for name, kws in MACRO_RE:
        for k in kws:
            if k.search(t):
                return name
    return "기타"


# ---------- 투자의견 · 목표주가 ----------
def norm_op(s):
    if not s:
        return None
    t = s.replace(" ", "").lower()
    if re.search(r"sell|매도|reduce|underperform|비중축소|underweight", t):
        return "매도"
    if re.search(r"hold|중립|neutral|marketperform|보유|equal|시장수익률|marketweight", t):
        return "중립"
    if re.search(r"buy|매수|outperform|overweight|비중확대|positive|긍정", t):
        return "매수"
    return None


def op_change(s):
    if not s:
        return None
    if re.search(r"상향|upgrade", s, re.I):
        return "상향"
    if re.search(r"하향|downgrade", s, re.I):
        return "하향"
    if re.search(r"신규|initiat|커버리지\s*개시", s, re.I):
        return "신규"
    return None


NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"


def parse_tp(s):
    """'470,000원 (유지)' → {v:470000, u:'원', ch:'유지'}, '611.9달러', '46만 원' 지원"""
    if not s:
        return None
    m = re.search(NUM + r"\s*(만\s*원|원|달러|USD|\$|엔|위안|HKD|홍콩달러|유로|EUR|대만달러|TWD)", s)
    if m:
        v = float(m.group(1).replace(",", ""))
        u = m.group(2).replace(" ", "")
        if u == "만원":
            v, u = v * 10000, "원"
        if u in ("USD", "$"):
            u = "달러"
    else:
        m2 = re.search(r"(?:\$|US\$)\s*" + NUM, s)
        m3 = re.search(r"KRW\s*" + NUM, s)
        if m3:
            v, u = float(m3.group(1).replace(",", "")), "원"
        elif m2:
            v, u = float(m2.group(1).replace(",", "")), "달러"
        else:
            return None
    if u == "원" and v < 100:
        return None
    ch = None
    mm = re.search(r"상향|하향|유지|신규|Maintain|Upgrade|Downgrade", s)
    if mm:
        ch = {"Maintain": "유지", "Upgrade": "상향", "Downgrade": "하향"}.get(mm.group(0), mm.group(0))
    prev = re.search(r"(?:기존|직전|종전)\s*:?\s*" + NUM + r"\s*(만\s*원|원)?", s)
    pv = None
    if prev:
        pv = float(prev.group(1).replace(",", "")) * (10000 if prev.group(2) and "만" in prev.group(2) else 1)
        if pv < 100:
            pv = None
    up = re.search(r"상승\s*여력\s*:?\s*([+-]?\d+(?:\.\d+)?)\s*%", s)
    return dict(v=v, u=u, ch=ch, prev=pv, up=float(up.group(1)) if up else None)


def parse_multi(op_line):
    """'현대차(매수유지/TP 530,000원), 기아(매수유지/TP 200,000원 하향)' → [{name, op, tp}]"""
    out = []
    for m in re.finditer(r"([가-힣A-Za-z0-9&\.\- ]{2,20})\s*\(([^()]*(?:TP|목표|원|달러)[^()]*)\)", op_line):
        nm = match_stock(m.group(1).strip(" ,/:"))
        if not nm:
            continue
        inner = m.group(2)
        out.append(dict(name=nm, op=norm_op(inner), opch=op_change(inner), tp=parse_tp(inner)))
    return out


# ---------- 본문 파싱 ----------
FIELDS = r"(제목|작성자|투자의견|목표주가|작성일|기준 시점/기간)"


def parse(m):
    t = m["text"].replace("\r", "")
    lines = [l.rstrip() for l in t.split("\n")]
    first = lines[0].strip() if lines else ""
    first = re.sub(r"\[?\s*기업명\s*/\s*산업명\s*/\s*카테고리\s*\]?|\[\s*기업명\s*\]", "", first).strip()
    fld = {}
    for l in lines[:14]:
        mm = re.match(r"\s*" + FIELDS + r"\s*:\s*(.*)", l)
        if mm and mm.group(1) not in fld:
            fld[mm.group(1)] = mm.group(2).strip()
    secs, cur, started = [], None, False
    for l in lines[1:]:
        s = l.strip()
        if not s:
            continue
        if re.match(FIELDS + r"\s*:", s):
            started = True
            continue
        if s.startswith("[") and s.endswith("]") and len(s) < 90:
            cur = dict(h=s.strip("[] "), b=[])
            secs.append(cur)
        elif s[:1] in "·•-":
            if cur is None:
                cur = dict(h="", b=[])
                secs.append(cur)
            cur["b"].append(s.lstrip("·•- ").strip())
        elif started:
            if cur is None or (cur["b"] and len(s) < 60 and not s.endswith(".")):
                cur = dict(h=s, b=[])
                secs.append(cur)
            else:
                cur["b"].append(s)
    secs = [x for x in secs if x["b"]]
    fn = m["file"] if isinstance(m["file"], str) and m["file"] != "F" else ""
    fparts = re.sub(r"\.pdf$", "", fn, flags=re.I).split("_") if fn else []
    rdate = None
    if fparts and re.fullmatch(r"\d{6}|\d{8}", fparts[-1]):
        d = fparts[-1][-6:]
        rdate = "20" + d[:2] + "-" + d[2:4] + "-" + d[4:6]
    broker = find_broker(fparts[-2] if len(fparts) >= 2 else None, fld.get("작성자"), fn, first, t[:400])
    tags = [x.strip() for x in re.split(r"\s*/\s*|\|", first.strip("[] "))] if first else []
    tags = [x for x in tags if x]
    subj = None
    code = re.search(r"\(\s*A?(\d{6})", first + " " + fld.get("제목", ""))
    if code and code.group(1) in CODE2NAME:
        subj = CODE2NAME[code.group(1)]
    for cand in ([tags[0]] if tags else []) + ([fparts[0]] if fparts else []):
        if subj:
            break
        s0 = match_stock(cand)
        if s0 and (s0 in AMBIG or len(s0) < 2) and cand is not (tags[0] if tags else None):
            s0 = None
        subj = s0
    if not subj and not first.startswith("["):
        subj = match_stock(first)
    if subj and broker and (subj == broker or find_broker(subj) == broker or subj in ("SK", "DB") and broker in ("SK증권", "DB증권")):
        subj = None                                               # 증권사가 낸 시황·전략 글 (자기 회사 종목 아님)
    tp = parse_tp(fld.get("목표주가"))
    op = norm_op(fld.get("투자의견"))
    opline = fld.get("투자의견", "")
    multi = parse_multi(opline) if opline.count("(") >= 2 else []
    fn_clean = re.sub(r"_\d{6,8}$", "", strip_brokers(re.sub(r"\.pdf$", "", fn, flags=re.I)))
    head = " ".join([first, fld.get("제목", ""), fn_clean])
    is_ir = "기업설명회" in head or (len(fparts) >= 2 and fparts[-2] in ("개최", "개최안내공시")) or ("IR" in fn and "개최" in fn)
    t0 = tags[0] if tags else ""
    t0_is_ind = bool(ind_from_text(t0)) or any(k in t0 for k in MACRO_HINT) or len(t0) > 25
    t0_market = bool(re.search(r"시장|주식|해외|브리핑|Weekly|위클리|주간|시황|전략|대시보드|인도|일본|중국|미국|글로벌|아시아|유럽|신흥국|"
                               r"Market|Global|Japan|India|China|산업|업종|추천|Top Picks|포트폴리오", t0))
    t0_ticker = bool(re.search(r"\(\s*[A-Z]{1,6}(?:[\.\-\s]?(?:US|HK|CH|JP|TW|O|N))?\s*\)|\d{4,6}\.(?:CH|HK|JP|TW|T)\b", t0))
    company_tag = any(re.search(r"기업\s*분석|기업\s*이슈|기업\s*리포트|해외기업|미국기업|Earnings|Review|Preview|실적", x) for x in tags[1:] + [fld.get("제목", "")])
    foreign = (bool(tp and tp["u"] != "원") or t0_ticker or ((bool(FOREIGN_HINT.search(head)) or company_tag) and not t0_is_ind)) and not t0_market
    if is_ir:
        kind = "IR"
    elif subj and len(multi) < 2:
        kind = "종목"
    elif len(multi) >= 2:
        kind = "산업"
    elif foreign and t0:
        kind = "해외종목"
    elif any(k in head for k in MACRO_HINT) or GROUP.get(broker) == "은행·선물" or broker in ("한국은행", "통계청", "KIS자산평가", "국제금융센터"):
        kind = "매크로"
    else:
        kind = "산업"
    ind = None
    body = " ".join(tags[1:]) + " " + fld.get("제목", "")
    if kind in ("종목", "IR") and subj:
        ind = STOCK_IND_FIX.get(subj) or ind_from_text(body) or KRX2IND.get(STOCK[subj][2], STOCK[subj][2])
    elif kind in ("산업", "해외종목"):
        ind = ind_from_text(" ".join(tags if kind == "산업" else tags[1:]) + " " + fld.get("제목", "")) or ind_from_text(fn_clean) or "기타"
    elif kind == "매크로":
        ind = macro_topic(" ".join(tags) + " " + fld.get("제목", "") + " " + fn_clean + " " + (broker or ""))
    fsubj = re.sub(r"\s*\([^)]*\)\s*", " ", t0).strip() if kind == "해외종목" else None
    if kind == "종목" and tp is None and multi:
        tp = multi[0]["tp"]
        op = op or multi[0]["op"]
    return dict(id=m["id"], date=m["date"], rdate=rdate, file=fn, tags=tags, first=first, title=fld.get("제목", "").strip(),
                author=fld.get("작성자", ""), broker=broker, bgroup=GROUP.get(broker), opraw=opline, op=op, opch=op_change(opline),
                tpraw=fld.get("목표주가", ""), tp=tp, multi=multi, kind=kind, subj=subj, fsubj=fsubj, ind=ind, secs=secs,
                trunc=t.rstrip().endswith("...") or t.rstrip().endswith("…"), n=len(t), text=t)


def parse_all(msgs, since="2026-02-01"):
    """구조화 요약이 붙은 글 → 레코드. 같은 리포트(증권사+제목)가 여러 번 올라오면 하나로 합치고, 번호는 가장 먼저 올라온 글 번호로 고정"""
    S = [m for m in msgs if "제목:" in (m.get("text") or "") and m["date"] >= since]
    R = [parse(m) for m in S]
    # 중복 제거: (증권사, 제목) 같으면 가까운 글 중 PDF 있고 안 잘린 긴 글 하나
    best, out, by_title = {}, [], {}
    for r in R:
        tk = re.sub(r"\W", "", r["title"])[:40]
        k = (r["broker"] or "", tk)
        if not tk:
            out.append(r)
            continue
        if not r["broker"] and tk in by_title and int(r["id"]) - int(best[by_title[tk]]["id"]) <= 3000:
            k = by_title[tk]                                      # 증권사 칸만 빈 같은 리포트 → 같은 글로 합침
        elif r["broker"]:
            by_title[tk] = k
        o = best.get(k)
        if o is None or int(r["id"]) - int(o["id"]) > 3000:
            if o is not None:
                out.append(o)
            best[k] = r
            continue
        score = lambda x: (not x["trunc"], x["n"])
        w = r if score(r) > score(o) else o
        other = o if w is r else r
        if not w["file"] and other["file"]:
            w = dict(w, file=other["file"], rdate=other["rdate"] or w["rdate"], id=min(w["id"], other["id"]), date=min(w["date"], other["date"]))
        if not w["broker"] and other["broker"]:
            w = dict(w, broker=other["broker"], bgroup=other["bgroup"])
        best[k] = dict(w, id=min(w["id"], other["id"]), date=min(w["date"], other["date"]),
                       members=sorted(set(w.get("members", [w["id"]]) + other.get("members", [other["id"]]))))
    out += list(best.values())
    return sorted(out, key=lambda r: r["id"])
