"""지수 ETF 롱·인버스 비중 백테스트 엔진
- 가격: 네이버 수정주가(분배금 반영 총수익). 신호는 롱 ETF 종가로만 계산(그날까지 정보).
- 체결: 'close' = 신호 낸 날 종가(동시호가) / 'open' = 다음날 시가.
- 목표 비중이 바뀐 날만 매매(같으면 보유 그대로 = 비중 표류 허용).
- 비용(한쪽): 수수료 0.015% + 호가 반 칸(가격 2천원 미만 1원, 이상 5원).
- 현금: 연도별 기준금리 수준 이자.
- 인버스 매매차익은 배당소득세 15.4%(손실 상계 없음) — run(tax=0.154).
실행 순서(이 폴더에서): fetch.py(네이버 일봉 → data-alpha/index_etf/raw.pkl) → grid.py(추세·역추세 40여 규칙) · night.py/night2.py(밤·낮)
  · more.py(상대강도·RSI2) · inv.py(인버스 좁은 조건) · hybrid.py(낮·밤 비중) · oos.py/oos2.py(2003~2009 표본 밖) · final.py(계단식 견고성)
결론(2026-11-03): 인버스로 하락에 거는 규칙은 전부 손해, 롱/현금 계단식(20·40·60·90·120일선 하나당 20%)이 낙폭 절반, 밤 롱은 2010년 이후·저수수료에서만.
"""
import os
import numpy as np, pandas as pd
from pathlib import Path
RAWP = Path(os.environ.get("IETF_RAW", Path(__file__).resolve().parents[3] / "data-alpha" / "index_etf" / "raw.pkl"))
RAW = pd.read_pickle(RAWP)
BASE = {2002:4.2,2003:3.9,2004:3.5,2005:3.4,2006:4.3,2007:4.8,2008:4.7,2009:2.0,2010:2.2,2011:3.1,2012:3.0,2013:2.6,2014:2.3,
        2015:1.6,2016:1.35,2017:1.3,2018:1.55,2019:1.6,2020:0.6,2021:0.65,2022:2.0,2023:3.5,2024:3.45,2025:2.65,2026:2.5}
COM = 0.00015

def pair(name):
    """롱·인버스 쌍 → DataFrame(oL,cL,oI,cI,syn) 롱 ETF 거래일 기준. 인버스 상장 전은 합성(실제 구간 회귀)."""
    L, I = (RAW["069500"], RAW["114800"]) if name == "K" else (RAW["229200"], RAW["251340"])
    df = pd.DataFrame({"oL": L.open, "cL": L.close}).join(pd.DataFrame({"oI": I.open, "cI": I.close}))
    df = df[df.cL > 0]
    rL = df.cL.pct_change(); rI = df.cI.pct_change()
    ok = rI.notna() & rL.notna()
    b, a = np.polyfit(rL[ok], rI[ok], 1)
    gL = df.oL / df.cL.shift()          # 밤 갭
    first = df.cI.first_valid_index()
    df["syn"] = df.index < first
    # 합성: 인버스 종가·시가를 첫 실제 가격에서 거꾸로 만듦
    if df.syn.any():
        idx = np.where(df.syn)[0]
        cI = df.cI.values.copy(); oI = df.oI.values.copy()
        k = idx[-1] + 1
        for i in range(k - 1, -1, -1):
            r = a + b * rL.iloc[i + 1]
            cI[i] = cI[i + 1] / (1 + r)
        for i in idx[1:]:
            g = gL.iloc[i] - 1
            oI[i] = cI[i - 1] * (1 + b * g)
        oI[idx[0]] = cI[idx[0]]
        df["cI"] = cI; df["oI"] = oI
    df.attrs["fit"] = (a * 252, b)
    return df

def tick(p):
    return np.where(p < 2000, 1.0, 5.0)

def run(df, wL, wI, mode="close", start=None, end=None, tax=0.0):
    """wL, wI: 날짜별 목표 비중(그날 종가까지 정보로 결정). 반환: 일별 계좌가치 Series + 매매 횟수."""
    d = df.loc[start:end]
    wL = wL.reindex(d.index).fillna(0).values; wI = wI.reindex(d.index).fillna(0).values
    oL, cL, oI, cI = d.oL.values, d.cL.values, d.oI.values, d.cI.values
    rc = np.array([BASE.get(y, 2.5) / 100 / 252 for y in d.index.year])
    n = len(d); V = np.empty(n)
    vL = vI = 0.0; vC = 1.0; tL = tI = 0.0; trades = 0; turn = 0.0
    bas = [0.0]; taxpaid = [0.0]                      # 인버스 취득가(세금용): 매도분 이익의 tax 만큼 현금에서 뺌
    def trade(vL, vI, vC, nl, ni, pL, pI):
        tot = vL + vI + vC
        dl, di = tot * nl - vL, tot * ni - vI
        cost = abs(dl) * (COM + 0.5 * tick(pL) / pL) + abs(di) * (COM + 0.5 * tick(pI) / pI)
        tx = 0.0
        if di < 0 and vI > 0:
            f = -di / vI; gain = f * (vI - bas[0]); bas[0] *= (1 - f)
            if gain > 0: tx = tax * gain
        elif di > 0:
            bas[0] += di
        taxpaid[0] += tx
        return tot * nl, tot * ni, tot * (1 - nl - ni) - cost - tx, abs(dl) + abs(di)
    for i in range(n):
        if i > 0:
            if mode == "open":
                vL *= oL[i] / cL[i - 1]; vI *= oI[i] / cI[i - 1]
                if (wL[i - 1], wI[i - 1]) != (tL, tI):
                    vL, vI, vC, t = trade(vL, vI, vC, wL[i - 1], wI[i - 1], oL[i], oI[i]); tL, tI = wL[i - 1], wI[i - 1]; trades += 1; turn += t
                vL *= cL[i] / oL[i]; vI *= cI[i] / oI[i]
            else:
                vL *= cL[i] / cL[i - 1]; vI *= cI[i] / cI[i - 1]
            vC *= 1 + rc[i]
        if mode == "close" and (wL[i], wI[i]) != (tL, tI):
            vL, vI, vC, t = trade(vL, vI, vC, wL[i], wI[i], cL[i], cI[i]); tL, tI = wL[i], wI[i]; trades += 1; turn += t
        V[i] = vL + vI + vC
    s = pd.Series(V, d.index)
    s.attrs["trades"] = trades; s.attrs["turn"] = turn
    s.attrs["expL"] = float(np.mean(wL)); s.attrs["expI"] = float(np.mean(wI))
    return s

def stats(s, cash=True):
    r = s.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    rc = np.array([BASE.get(y, 2.5) / 100 / 252 for y in r.index.year])
    ex = r - rc
    sh = ex.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    mdd = (s / s.cummax() - 1).min()
    yr = s.resample("YE").last().pct_change()
    yr.iloc[0] = s.resample("YE").last().iloc[0] / s.iloc[0] - 1
    return dict(cagr=cagr, mdd=mdd, sh=sh, vol=r.std() * np.sqrt(252), trd=s.attrs.get("trades", 0) / yrs,
                expL=s.attrs.get("expL", np.nan), expI=s.attrs.get("expI", np.nan), yr=yr)

# ---------- 신호 도구
def ma(p, n): return p.rolling(n).mean()
def rsi(p, n):
    d = p.diff(); u = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); v = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + u / v)
