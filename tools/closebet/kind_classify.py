"""B2b. 공시 재료 분류 (수익률을 보기 전에 규칙을 고정) → 결합·비교
python tools/closebet/kind_classify.py classify   # 분류만 (수익 미결합) → data-closebet/news_class.csv
python tools/closebet/kind_classify.py            # 분류 + 다음날 시가 수익 결합 비교

시점 구분 (신호일 t, 매수 15:20):
  pre   = t−1일 15:30 ~ t일 15:20  → 매수 판단에 쓸 수 있는 '신선한 재료'
  week  = t−7일 ~ t−1일 15:30      → 최근 재료
  post  = t일 15:20 ~ t+1일 09:00   → 매수 후 공시 (판단엔 못 씀, 갭 설명용)
분류는 아래 키워드 표로만 결정 (제목에서 괄호 안 '자율공시' 등도 포함해 검사). 여러 개면 우선순위 위쪽.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cb import CB  # noqa: E402

# (분류, 키워드들) — 우선순위 순
CATS = [
    ("과열경보·조회공시", ["투자경고", "투자위험", "투자주의", "단기과열", "조회공시요구", "조회공시 요구", "풍문또는보도", "풍문 또는 보도", "가격제한폭 확대요건",
                         "매매거래정지", "시장경보", "공매도과열", "관리종목", "불성실공시"]),
    ("희석(유증·CB)", ["유상증자", "전환사채", "신주인수권부사채", "교환사채", "전환청구권", "신주인수권행사", "전환가액의조정", "추가상장", "자기주식처분", "자기주식 처분"]),
    ("지배구조·M&A", ["최대주주", "경영권", "합병", "분할", "영업양수", "영업양도", "타법인주식", "주식양수도", "공개매수", "주식교환"]),
    ("수주·계약", ["공급계약", "판매ㆍ공급", "판매·공급", "수주"]),
    ("실적", ["영업실적", "잠정실적", "영업(잠정)", "손익구조", "결산실적", "실적 등에 대한 전망", "매출액"]),
    ("주주환원", ["자기주식취득", "자기주식 취득", "신탁계약", "배당", "무상증자", "주식소각", "자기주식소각", "주식배당"]),
    ("기술·허가·특허", ["특허", "임상", "품목허가", "허가", "기술이전", "기술도입", "신제품", "FDA", "승인"]),
    ("기타 경영사항", ["기타 경영사항", "기타경영사항", "투자판단", "주요사항", "기업설명회", "시설투자", "신규시설", "유형자산"]),
]
ROUTINE = "일상공시"   # 대량보유·임원소유·주총·감사보고서·참고서류 등


def cat_of(title):
    for c, kws in CATS:
        if any(k in title for k in kws):
            return c
    return ROUTINE


def classify():
    smp = pd.read_csv(CB / "news_sample.csv", parse_dates=["date"])
    k = pd.read_csv(CB / "news_kind.csv")
    k = k[k["title"] != "(공시 없음)"].copy()
    k["time"] = pd.to_datetime(k["time"])
    k = k.merge(smp[["id", "date"]], on="id")
    dates = sorted(pd.read_pickle(CB / "_R.pkl")["date"].unique())
    nxt = dict(zip(dates[:-1], dates[1:])); prv = dict(zip(dates[1:], dates[:-1]))
    k["t_pre0"] = k["date"].map(prv) + pd.Timedelta(hours=15, minutes=30)
    k["t_buy"] = k["date"] + pd.Timedelta(hours=15, minutes=20)
    k["t_sell"] = k["date"].map(nxt) + pd.Timedelta(hours=9)
    k["win"] = np.select([k["time"] <= k["t_pre0"], k["time"] <= k["t_buy"], k["time"] <= k["t_sell"]],
                         ["week", "pre", "post"], "later")
    k["cat"] = k["title"].map(cat_of)
    order = [c for c, _ in CATS] + [ROUTINE]
    rows = []
    for i, x in smp.iterrows():
        g = k[k["id"] == x["id"]]
        r = {"id": x["id"]}
        for w in ("pre", "week", "post"):
            cs = [c for c in order if c in set(g.loc[g["win"] == w, "cat"])]
            r[f"{w}_cats"] = "|".join(cs)
            mat = [c for c in cs if c != ROUTINE]
            r[f"{w}_main"] = mat[0] if mat else ("일상공시만" if cs else "없음")
        rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv(CB / "news_class.csv", index=False, encoding="utf-8-sig")
    k.to_csv(CB / "news_kind_labeled.csv", index=False, encoding="utf-8-sig")
    print("분류 완료:", len(out), "건 (수익 미결합)")
    for w in ("pre", "week", "post"):
        print(w, out[f"{w}_main"].value_counts().to_dict())
    return out


def compare():
    cl = pd.read_csv(CB / "news_class.csv")
    smp = pd.read_csv(CB / "news_sample.csv", dtype={"ticker": str}, parse_dates=["date"])
    R = pd.read_pickle(CB / "_R.pkl")[["date", "ticker", "on", "oc", "pos", "day", "peer_n3"]]
    th = pd.read_pickle(CB / "_theme.pkl")
    R2 = pd.read_pickle(CB / "_R.pkl")[["i", "j", "date", "ticker"]].merge(th, on=["i", "j"])
    X = smp.merge(cl, on="id").merge(R, on=["date", "ticker"]).merge(R2[["date", "ticker", "theme_run"]], on=["date", "ticker"])
    X["net"] = X["on"] - 0.0025
    print(f"\n표본 {len(X)}건 (최종 규칙 상위3 무작위), 표본 전체 비용후 {X['net'].mean()*100:+.2f}% (중앙 {X['net'].median()*100:+.2f}%)")
    for w, lab in (("pre", "매수 전 신선한 공시 (t−1 15:30~t 15:20)"), ("week", "최근 1주 공시"), ("post", "매수 후~다음날 9시 공시 (판단 불가, 갭 설명)")):
        print(f"\n[{lab}]")
        for c, g in X.groupby(f"{w}_main"):
            se = g["net"].std(ddof=1) / np.sqrt(len(g)) if len(g) > 1 else np.nan
            print(f"   {c:14} n={len(g):4d} 비용후 {g['net'].mean()*100:+6.2f}% ±{se*100:4.2f} 중앙 {g['net'].median()*100:+5.2f}% 승 {(g['net']>0).mean()*100:3.0f}%")
    X["theme"] = np.where(X["theme_run"] >= 1, "테마동반", "단독")
    X["has_pre"] = np.where(X["pre_main"].isin(["없음", "일상공시만"]), "공시재료 없음", "공시재료 있음")
    print("\n[공시 재료 × 테마 동반]")
    for (a, b), g in X.groupby(["has_pre", "theme"]):
        print(f"   {a} · {b}: n={len(g):4d} 비용후 {g['net'].mean()*100:+.2f}% 중앙 {g['net'].median()*100:+.2f}%")
    X.to_csv(CB / "news_result.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    classify()
    if "classify" not in sys.argv:
        compare()
