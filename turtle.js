/* 터틀 트레이딩 · 터틀 수프 백테스트 엔진 — 퀀트 페이지(quant.html)가 '터틀' 전략을 누를 때 불러옴
   데이터: turtle.bin (tools/closebet/export_turtle.py · 상장폐지 포함 코스피·코스닥 전 종목 일봉, 20일 평균 거래대금 30억↑ 구간)
   계산만 함(화면 없음) — 노드에서도 require 해서 시험할 수 있음

   하루 안의 가격 순서(일봉이라 모름)는 '시가에서 가까운 쪽 극단 먼저': 고가가 더 가까우면 시가→고가→저가→종가, 아니면 시가→저가→고가→종가
   상한가 근처(+28.5%↑, 2015-06-15 전 +13.5%↑)에서는 사지 못함 · 하한가 근처에 종일 묶이면(고가 ≤ −28.5%) 그날 팔지 못하고 다음 날로 */
(function(root){
  "use strict";
  var LIMD = 20150615, NOH = -32768, NOL = 32767;

  // ---------------------------------------------------------------- 데이터 풀기
  function decode(u8){
    var hl = u8[0] + u8[1] * 256 + u8[2] * 65536 + u8[3] * 16777216;
    var head = JSON.parse(new TextDecoder("utf-8").decode(u8.subarray(4, 4 + hl)));
    var D = head.days, off = 4 + hl, buf = u8.buffer, bo = u8.byteOffset;
    var G = new Int8Array(buf, bo + off, D); off += D;
    var B = new Int8Array(buf, bo + off, D); off += D;
    var H8 = new Int8Array(buf, bo + off, D); off += D;
    var L8 = new Int8Array(buf, bo + off, D); off += D;
    var V8 = u8.subarray(off, off + D); off += D;
    var F8 = u8.subarray(off, off + D);
    var S = head.seg.length, sj = new Int32Array(S), ss = new Int32Array(S), sn = new Int32Array(S), sp = new Int32Array(S);
    var C = new Int16Array(D), O = new Int16Array(D), H = new Int16Array(D), L = new Int16Array(D), V = new Uint8Array(D), F = new Uint8Array(D);
    var E = head.esc, eg = 0, eb = 0, eh = 0, el = 0, pos = 0, qmin = 32767, qmax = -32768;
    for (var k = 0; k < S; k++) {
      var sg = head.seg[k], prev = sg[3], cls = 0;
      sj[k] = sg[0]; ss[k] = sg[1]; sn[k] = sg[2]; sp[k] = pos;
      for (var i = 0; i < sg[2]; i++, pos++) {
        var g = G[pos]; if (g === -128) g = E.g[eg++];
        var b = B[pos]; if (b === -128) b = E.b[eb++];
        var h = H8[pos]; if (h === -128) h = E.h[eh++];
        var l = L8[pos]; if (l === -128) l = E.l[el++];
        var qo = prev + g, qc = qo + b, hi = (qo > qc ? qo : qc) + h, lo = (qo < qc ? qo : qc) - l;
        O[pos] = qo; C[pos] = qc; H[pos] = hi; L[pos] = lo;
        cls = (cls + V8[pos]) & 255; V[pos] = cls; F[pos] = F8[pos];
        if (lo < qmin) qmin = lo;
        if (hi > qmax) qmax = hi;
        prev = qc;
      }
    }
    var PX = new Float64Array(qmax - qmin + 1);
    for (var q = qmin; q <= qmax; q++) PX[q - qmin] = Math.exp(q * head.step);
    var nan = function(a){ return Float64Array.from(a, function(v){ return v === null ? NaN : v; }); };
    var last = {};                                       // 종목별 마지막 구간 (상폐 판정)
    for (k = 0; k < S; k++) last[sj[k]] = k;
    return { asof: head.asof, dates: Int32Array.from(head.dates), T: head.dates.length, st: head.stocks, tvcls: head.tvcls,
             S: S, sj: sj, ss: ss, sn: sn, sp: sp, D: D, C: C, O: O, H: H, L: L, V: V, F: F, PX: PX, qmin: qmin,
             ks: nan(head.ks), kq: nan(head.kq), lastSeg: last, cache: {} };
  }
  function px(DT, q){ return DT.PX[q - DT.qmin]; }

  // ---------------------------------------------------------------- 지표 (구간마다, 거래정지 날은 건너뜀)
  // 직전 W봉(오늘 제외)의 최고/최저 수준 + 그 봉이 몇 봉 전인지
  function rollPrior(DT, key, W, isMax){
    var ck = key + W + (isMax ? "x" : "n");
    if (DT.cache[ck]) return DT.cache[ck];
    var A = DT[key], F = DT.F, R = new Int16Array(DT.D), AG = new Int16Array(DT.D), NA = isMax ? NOH : NOL;
    for (var k = 0; k < DT.S; k++) {
      var p0 = DT.sp[k], n = DT.sn[k], qi = [], qo = [], hd = 0, ord = 0;
      for (var i = 0; i < n; i++) {
        var x = p0 + i;
        while (hd < qi.length && qo[hd] < ord - W) hd++;
        if (ord >= W && hd < qi.length) { R[x] = A[qi[hd]]; AG[x] = ord - qo[hd]; } else { R[x] = NA; AG[x] = 0; }
        if (F[x] & 1) continue;
        var v = A[x];
        if (isMax) { while (qi.length > hd && A[qi[qi.length - 1]] <= v) { qi.pop(); qo.pop(); } }
        else { while (qi.length > hd && A[qi[qi.length - 1]] >= v) { qi.pop(); qo.pop(); } }
        qi.push(x); qo.push(ord); ord++;
      }
    }
    return (DT.cache[ck] = { v: R, age: AG });
  }
  // N = 최근 20봉 평균 진폭(TR) — nc: 그날 봉까지 · np: 앞 봉까지(장중 판단용)
  function atr(DT){
    if (DT.cache.atr) return DT.cache.atr;
    var nc = new Float32Array(DT.D).fill(NaN), np = new Float32Array(DT.D).fill(NaN), F = DT.F;
    for (var k = 0; k < DT.S; k++) {
      var p0 = DT.sp[k], n = DT.sn[k], ring = new Float64Array(20), cnt = 0, sum = 0, pc = NaN, cur = NaN;
      for (var i = 0; i < n; i++) {
        var x = p0 + i;
        np[x] = cur;
        if (F[x] & 1) { nc[x] = cur; continue; }
        var h = px(DT, DT.H[x]), l = px(DT, DT.L[x]), c = px(DT, DT.C[x]);
        if (pc === pc) {
          var tr = (h > pc ? h : pc) - (l < pc ? l : pc), slot = cnt % 20;
          if (cnt >= 20) sum -= ring[slot];
          ring[slot] = tr; sum += tr; cnt++;
          if (cnt >= 20) cur = sum / 20;
        }
        nc[x] = cur; pc = c;
      }
    }
    return (DT.cache.atr = { nc: nc, np: np });
  }
  // 시장 필터: 코스피·코스닥 둘 다 n일선 위인 날 1
  function mktOK(DT, kind){
    if (!kind || kind === "none") return null;
    var n = kind === "b120" ? 120 : 60, ck = "mk" + n;
    if (DT.cache[ck]) return DT.cache[ck];
    var T = DT.T, out = new Uint8Array(T);
    var above = function(a){
      var r = new Uint8Array(T), s = 0, q = [];
      for (var t = 0; t < T; t++) {
        var v = a[t]; if (!(v === v)) continue;
        q.push(v); s += v; if (q.length > n) s -= q.shift();
        if (q.length === n && v > s / n) r[t] = 1;
      }
      return r;
    };
    var a = above(DT.ks), b = above(DT.kq);
    for (var t = 0; t < T; t++) out[t] = a[t] & b[t];
    return (DT.cache[ck] = out);
  }
  function segOrder(DT){
    if (DT.cache.order) return DT.cache.order;
    var o = Array.from({ length: DT.S }, function(_, i){ return i; });
    o.sort(function(a, b){ return DT.ss[a] - DT.ss[b] || a - b; });
    return (DT.cache.order = o);
  }
  function hsh(j, t){ var x = (Math.imul(j + 1, 2654435761) ^ Math.imul(t + 7, 40503)) >>> 0; x ^= x >>> 15; x = Math.imul(x, 2246822519) >>> 0; x ^= x >>> 13; return x >>> 0; }
  function range(DT, c){
    var T = DT.T, t0 = 0, t1 = T - 1;
    while (t0 < T - 1 && DT.dates[t0] < c.from) t0++;
    while (t1 > 0 && DT.dates[t1] > c.to) t1--;
    return [t0, t1];
  }

  // ---------------------------------------------------------------- 공통 계좌
  //   cash · 보유(종목당 하나) · 비용은 사고팔 때 절반씩 · 한도: 전체 capT · 종목당 capS (계좌 대비, 전날 종가 평가 기준)
  function Book(c){
    this.c = c; this.ch = c.cost / 2; this.cash = 1; this.expo = 0; this.units = 0; this.pos = []; this.byJ = {};
    this.trades = []; this.eqPrev = 1; this.peak = 1;
  }
  Book.prototype.room = function(curVal){
    var c = this.c;
    return Math.min(c.capT * this.eqPrev - this.expo, c.capS * this.eqPrev - (curVal || 0), this.cash / (1 + this.ch));
  };
  Book.prototype.buy = function(p, V){ var ch = this.ch; this.cash -= V * (1 + ch); p.cost += V * (1 + ch); p.val += V; this.expo += V; };
  Book.prototype.close = function(p, price, kind, te){
    var proceeds = p.shares * price * (1 - this.ch);
    this.cash += proceeds; this.expo -= p.val; this.units -= p.units || 0; p.done = true;
    delete this.byJ[p.j];
    var pnl = proceeds - p.cost;
    var tr = { j: p.j, k: p.k, t: p.t, te: te, e: p.e0, avg: p.cost / (1 + this.ch) / p.shares, px: price, u: p.units || 1,
               r: pnl / p.cost, R: p.risk0 > 0 ? pnl / p.risk0 : NaN, kind: kind, via: p.via, w: p.cost };
    this.trades.push(tr);
    return tr;
  };
  Book.prototype.mark = function(){            // 장 마감 평가
    var e = 0;
    this.pos = this.pos.filter(function(p){ return !p.done; });
    for (var q = 0; q < this.pos.length; q++) { var p = this.pos[q]; p.val = p.shares * p.lc; e += p.val; }
    this.expo = e;
    return this.cash + e;
  };

  // ---------------------------------------------------------------- 터틀
  //  c: E 돌파 기간 · skip 시스템1 건너뛰기(+55일 안전장치) · X 청산 기간 · stop 손절 N배(0 = 없음) · U 최대 유닛 · add 불타기 간격(N배)
  //     fill 'i' 장중 / 'c' 종가 · tvc 거래대금 등급 · mkt none/b60/b120 · trend none/ema/ma200 · near 깊은 눌림 제외
  //     size risk/eq · szv (1N 움직일 때 계좌 비율 / 계좌 비율) · capS · capT · maxU · ddr 낙폭 축소 · cost 왕복 · from · to · bench
  function runTurtle(DT, c){
    var tr0 = range(DT, c), t0 = tr0[0], t1 = tr0[1], T = DT.T, dates = DT.dates;
    var intra = c.fill !== "c", skip = !!c.skip && c.E < 55;
    var HE = rollPrior(DT, "H", c.E, true).v, LX = rollPrior(DT, "L", c.X, false).v, H55 = skip ? rollPrior(DT, "H", 55, true).v : null;
    var A = atr(DT), NP = A.np, NC = A.nc, MK = mktOK(DT, c.mkt);
    var need = (c.trend === "ema" ? 2 : c.trend === "ma200" ? 4 : 0) | (c.near ? 8 : 0);
    var Hq = DT.H, Cq = DT.C, Oq = DT.O, Lq = DT.L, Fq = DT.F, Vq = DT.V;
    var S = DT.S, order = segOrder(DT), ap = 0, act = [];
    var shOpen = new Uint8Array(S), shE = new Float64Array(S), shS = new Float64Array(S), shW = new Int8Array(S).fill(-1), fresh = new Uint8Array(S);
    var bk = new Book(c), BI = c.bench === "kq" ? DT.kq : DT.ks, b0 = NaN, eq = [], bq = [], invS = 0;
    var st = { sig: 0, skip: 0, lock: 0, add: 0, addSkip: 0, shSkip: 0, via55: 0 };
    var stepN = c.add || 0.5, U = Math.max(1, c.U | 0), X = DT;
    var exited = {}, t, ddf = 1;

    function chanLow(x){ var q = LX[x]; return q === NOL ? -Infinity : px(X, q); }
    function exitLevel(p, x){ var cl = chanLow(x); return p.stop > cl ? p.stop : cl; }
    function kindOf(p, x){ return p.stop > -Infinity && p.stop >= chanLow(x) ? "손절" : "청산"; }
    function exitPos(p, price, kind){ bk.close(p, price, kind, t); exited[p.j] = 1; }
    function addUnit(p, price){
      var V = p.sh * price, room = bk.room(p.val);
      if (bk.units >= c.maxU || room < V * 0.3) { st.addSkip++; p.add = price + stepN * p.n0; return; }
      if (V > room) V = room;
      bk.buy(p, V); p.shares += V / price; p.units++; bk.units++;
      p.last = price; p.add = price + stepN * p.n0; if (c.stop > 0) p.stop = price - c.stop * p.n0; st.add++;
    }
    // 장중: 시가(fromLeg < 0)부터 또는 진입 지점(leg, 가격)부터 남은 경로를 따라 불타기·손절·청산
    function stepI(p, x, o, h, l, cl, lockDn, fromLeg, fromPx){
      var hiFirst = (h - o) < (o - l), pts = [o, hiFirst ? h : l, hiFirst ? l : h, cl], lg = fromLeg, a = fromPx;
      if (fromLeg < 0) {
        var el = exitLevel(p, x);
        if (o <= el && !lockDn) { exitPos(p, o, kindOf(p, x)); return; }
        if (p.units < U && o >= p.add) addUnit(p, o);
        lg = 0; a = o;
      }
      for (; lg < 3; lg++) {
        var b = pts[lg + 1];
        if (b > a) { while (p.units < U && p.add <= b) addUnit(p, p.add > a ? p.add : a); }
        else if (b < a && !lockDn) {
          var el2 = exitLevel(p, x);
          if (el2 >= b) { exitPos(p, el2 < a ? el2 : a, kindOf(p, x)); return; }
        }
        a = b;
      }
    }
    function stepC(p, x, cl, lockDn){
      var el = exitLevel(p, x);
      if (cl <= el) { if (!lockDn) exitPos(p, cl, kindOf(p, x)); return; }
      if (p.units < U && cl >= p.add) addUnit(p, cl);
    }
    function endSeg(k, tEnd){
      for (var q = 0; q < bk.pos.length; q++) {
        var p = bk.pos[q];
        if (p.k === k && !p.done) { var keep = t; t = tEnd; exitPos(p, p.lc, X.st[p.j].x && X.lastSeg[p.j] === k ? "상폐 청산" : "데이터 끝"); t = keep; }
      }
    }

    for (t = 0; t <= t1; t++) {
      while (ap < S && DT.ss[order[ap]] <= t) act.push(order[ap++]);
      var keepAct = [];
      for (var a = 0; a < act.length; a++) { var k0 = act[a]; if (DT.ss[k0] + DT.sn[k0] <= t) { if (t > t0) endSeg(k0, DT.ss[k0] + DT.sn[k0] - 1); } else keepAct.push(k0); }
      act = keepAct;
      var lim = dates[t] >= LIMD ? 0.30 : 0.15, trading = t >= t0, k, x, i, o, h, l, cl, p, q;
      exited = {};
      if (trading) {
        bk.peak = Math.max(bk.peak, bk.eqPrev);
        ddf = c.ddr ? Math.pow(0.8, Math.floor((1 - bk.eqPrev / bk.peak) / 0.1 + 1e-9)) : 1;
        // 1) 보유 종목
        for (q = 0; q < bk.pos.length; q++) {
          p = bk.pos[q]; if (p.done) continue;
          x = DT.sp[p.k] + (t - DT.ss[p.k]);
          if (Fq[x] & 1) continue;
          o = px(X, Oq[x]); h = px(X, Hq[x]); l = px(X, Lq[x]); cl = px(X, Cq[x]);
          var lockDn = h <= p.lc * (1 - lim + 0.015);
          if (intra) stepI(p, x, o, h, l, cl, lockDn, -1, o); else stepC(p, x, cl, lockDn);
          if (!p.done) p.lc = cl;
        }
      }
      // 2) 시스템 1 그림자 매매 (실제로 샀든 안 샀든 모든 20일 돌파의 결과를 기억)
      if (skip) {
        for (a = 0; a < act.length; a++) {
          k = act[a]; i = t - DT.ss[k]; x = DT.sp[k] + i; fresh[k] = 0;
          if (Fq[x] & 1) continue;
          var wasOpen = shOpen[k], prevW = shW[k];
          o = px(X, Oq[x]); l = px(X, Lq[x]); cl = px(X, Cq[x]);
          if (wasOpen) {
            var lv = Math.max(shS[k], chanLow(x)), ex = intra ? (o <= lv ? o : l <= lv ? lv : NaN) : (cl <= lv ? cl : NaN);
            if (ex === ex) { shOpen[k] = 0; shW[k] = ex > shE[k] ? 1 : 0; }
          }
          var nn = intra ? NP[x] : NC[x];
          if (!wasOpen && HE[x] !== NOH && (intra ? Hq[x] > HE[x] : Cq[x] > HE[x]) && nn > 0) {
            var f0 = intra ? Math.max(px(X, HE[x]), o) : cl;
            shOpen[k] = 1; shE[k] = f0; shS[k] = f0 - 2 * nn; fresh[k] = prevW === 1 ? 2 : 1;
          }
        }
      }
      // 3) 새 매수
      if (trading && (!MK || MK[intra ? Math.max(0, t - 1) : t])) {
        var cands = [];
        for (a = 0; a < act.length; a++) {
          k = act[a]; i = t - DT.ss[k];
          if (i < 1) continue;
          x = DT.sp[k] + i;
          if (Fq[x] & 1) continue;
          var j = DT.sj[k];
          if (bk.byJ[j] || exited[j]) continue;
          var y = intra ? x - 1 : x;
          if (Vq[y] < c.tvc || (Fq[y] & need) !== need) continue;
          var lvl = NOH, via = c.E;
          if (skip) {
            if (fresh[k] === 1) lvl = HE[x];
            else {
              if (fresh[k] === 2) st.shSkip++;
              if (H55[x] !== NOH && (intra ? Hq[x] > H55[x] : Cq[x] > H55[x])) { lvl = H55[x]; via = 55; }
            }
          } else if (HE[x] !== NOH && (intra ? Hq[x] > HE[x] : Cq[x] > HE[x])) lvl = HE[x];
          if (lvl === NOH) continue;
          cands.push({ k: k, j: j, x: x, lvl: lvl, via: via, r: Vq[y] * 4294967296 + hsh(j, t) });
        }
        cands.sort(function(u, v){ return v.r - u.r; });
        for (q = 0; q < cands.length; q++) {
          var cd = cands[q]; x = cd.x; st.sig++;
          var n = intra ? NP[x] : NC[x];
          if (!(n > 0)) continue;
          o = px(X, Oq[x]); h = px(X, Hq[x]); l = px(X, Lq[x]); cl = px(X, Cq[x]);
          var pc = px(X, Cq[x - 1]), L0 = px(X, cd.lvl), fill = intra ? (o >= L0 ? o : L0) : cl;
          if (fill >= pc * (1 + lim - 0.015)) { st.lock++; continue; }
          var notional = bk.eqPrev * ddf, sh = c.size === "eq" ? c.szv * notional / fill : c.szv * notional / n;
          var V = sh * fill, room = bk.room(0);
          if (bk.units >= c.maxU || room < V * 0.3) { st.skip++; continue; }
          if (V > room) V = room;
          p = { j: cd.j, k: cd.k, t: t, x0: x, e0: fill, sh: sh, shares: V / fill, cost: 0, val: 0, units: 1, last: fill,
                add: fill + stepN * n, stop: c.stop > 0 ? fill - c.stop * n : -Infinity, n0: n, via: cd.via, lc: fill, done: false };
          p.risk0 = p.shares * (c.stop > 0 ? c.stop : 2) * n;
          bk.buy(p, V); bk.units++; bk.pos.push(p); bk.byJ[cd.j] = p;
          if (cd.via === 55 && skip) st.via55++;
          if (intra) {
            var hiFirst = (h - o) < (o - l), lockD = h <= pc * (1 - lim + 0.015);
            if (o >= L0) stepI(p, x, o, h, l, cl, lockD, 0, o);
            else stepI(p, x, o, h, l, cl, lockD, hiFirst ? 0 : 1, L0);
          }
          if (!p.done) p.lc = cl;
        }
      }
      if (!trading) continue;
      var e = bk.mark();
      if (b0 !== b0 && BI[t] === BI[t]) b0 = BI[t];
      eq.push(e); bq.push(BI[t] === BI[t] && b0 === b0 ? BI[t] / b0 : NaN);
      invS += e > 0 ? bk.expo / e : 0;
      bk.eqPrev = e;
    }
    var open = bk.pos.filter(function(p){ return !p.done; }).map(function(p){
      return { p: p, x: DT.sp[p.k] + (t1 - DT.ss[p.k]) };
    });
    open.forEach(function(o){ t = t1; var tr = bk.close(o.p, o.p.lc, t1 === T - 1 ? "보유 중" : "기간 끝", t1); tr.open = true; o.tr = tr; });
    return { c: c, t0: t0, t1: t1, eq: eq, bq: bq, dts: Array.prototype.slice.call(dates, t0, t1 + 1), trades: bk.trades, st: st,
             inv: invS / Math.max(1, eq.length), open: open, sh: { open: shOpen, win: shW } };
  }

  // 내일 돌파 가격 (데이터 마지막 날 기준) — 보유 안 한 종목 중 조건 통과, 돌파 가격까지 maxGap 이내
  function turtleNext(DT, c, R, maxGap){
    var T = DT.T, t = T - 1, out = [], need = (c.trend === "ema" ? 2 : c.trend === "ma200" ? 4 : 0) | (c.near ? 8 : 0);
    var MK = mktOK(DT, c.mkt), skip = !!c.skip && c.E < 55, held = {};
    R.open.forEach(function(o){ held[o.p.j] = 1; });
    var A = atr(DT);
    for (var k = 0; k < DT.S; k++) {
      if (!(DT.ss[k] <= t && DT.ss[k] + DT.sn[k] > t)) continue;
      var x = DT.sp[k] + (t - DT.ss[k]), j = DT.sj[k];
      if ((DT.F[x] & 1) || held[j] || DT.V[x] < c.tvc || (DT.F[x] & need) !== need) continue;
      var useE = c.E, note = "";
      if (skip && (R.sh.open[k] || R.sh.win[k] === 1)) { useE = 55; note = R.sh.open[k] ? "20일 돌파 진행 중 → 55일만" : "직전 20일 돌파 수익 → 건너뛰고 55일만"; }
      var hi = -32768, cnt = 0;
      for (var z = x; z >= DT.sp[k] && cnt < useE; z--) { if (DT.F[z] & 1) continue; if (DT.H[z] > hi) hi = DT.H[z]; cnt++; }
      if (cnt < useE) continue;
      var lvl = px(DT, hi), cl = px(DT, DT.C[x]), gap = lvl / cl - 1, n = A.nc[x];
      if (!(n > 0) || gap > maxGap) continue;
      out.push({ j: j, lvl: lvl, cl: cl, gap: gap, n: n, note: note, E: useE, tv: DT.V[x] });
    }
    out.sort(function(a, b){ return a.gap - b.gap; });
    return { list: out, mkt: !MK || MK[t] === 1 };
  }
  // 보유 종목의 내일 기준 가격: 청산(X일 최저가) · 손절 · 다음 불타기
  function turtleHold(DT, c, R){
    var t = DT.T - 1;
    return R.open.map(function(o){
      var p = o.p, k = p.k, x = DT.sp[k] + (t - DT.ss[k]), lo = 32767, cnt = 0;
      for (var z = x; z >= DT.sp[k] && cnt < c.X; z--) { if (DT.F[z] & 1) continue; if (DT.L[z] < lo) lo = DT.L[z]; cnt++; }
      var chan = cnt >= c.X ? px(DT, lo) : NaN, stop = p.stop > -Infinity ? p.stop : NaN;
      return { j: p.j, t: p.t, e0: p.e0, avg: o.tr.avg, cl: p.lc, u: p.units, chan: chan, stop: stop,
               next: p.units < Math.max(1, c.U | 0) ? p.add : NaN, r: o.tr.r, n0: p.n0 };
    });
  }

  // ---------------------------------------------------------------- 터틀 수프 (매수만)
  //  c: mode 'a' 종가 회복(그날 종가 매수) / 'b' 플러스 원(다음 날 직전 저가 회복 시 매수) · tvc · mkt · trend · vol 거래량 2배
  //     k 익절 R(0 없음) · hold 보유 봉 수(0 = 다음 날 시가) · size risk/eq · szv · capS · capT · cost · from · to · bench
  //  신호: 오늘 20일 신저가(저가 < 직전 20일 최저가) · 직전 최저가는 4봉 이상 전
  //  손절: 'a' 신호 날 저가 · 'b' 신호 날·매수 날 저가 중 낮은 쪽 (다음 날부터) · R = 매수가 − 손절가
  function runSoup(DT, c){
    var tr0 = range(DT, c), t0 = tr0[0], t1 = tr0[1], T = DT.T, dates = DT.dates;
    var LSr = rollPrior(DT, "L", 20, false), LS = LSr.v, AG = LSr.age, MK = mktOK(DT, c.mkt);
    var need = (c.trend === "ema" ? 2 : c.trend === "ma200" ? 4 : 0) | (c.vol ? 16 : 0);
    var Hq = DT.H, Cq = DT.C, Oq = DT.O, Lq = DT.L, Fq = DT.F, Vq = DT.V, X = DT;
    var S = DT.S, order = segOrder(DT), ap = 0, act = [];
    var pend = new Float64Array(S).fill(NaN), pendLow = new Float64Array(S), pendT = new Int32Array(S).fill(-9);
    var bk = new Book(c), BI = c.bench === "kq" ? DT.kq : DT.ks, b0 = NaN, eq = [], bq = [], invS = 0;
    var st = { sig: 0, skip: 0, lock: 0, miss: 0 }, exited = {}, t;
    function exitPos(p, price, kind){ bk.close(p, price, kind, t); exited[p.j] = 1; }
    function endSeg(k, tEnd){
      for (var q = 0; q < bk.pos.length; q++) {
        var p = bk.pos[q];
        if (p.k === k && !p.done) { var keep = t; t = tEnd; exitPos(p, p.lc, X.st[p.j].x && X.lastSeg[p.j] === k ? "상폐 청산" : "데이터 끝"); t = keep; }
      }
    }
    function open(k, j, x, fill, stop){
      var R = fill - stop;
      if (!(R > fill * 0.002)) return null;
      var sh = c.size === "eq" ? c.szv * bk.eqPrev / fill : c.szv * bk.eqPrev / R, V = sh * fill, room = bk.room(0);
      if (room < V * 0.3) { st.skip++; return null; }
      if (V > room) V = room;
      var p = { j: j, k: k, t: t, x0: x, e0: fill, shares: V / fill, cost: 0, val: 0, units: 1, stop: stop, tgt: c.k ? fill + c.k * R : Infinity,
                nb: 0, lc: fill, risk0: V / fill * R, done: false, via: c.mode };
      bk.buy(p, V); bk.pos.push(p); bk.byJ[j] = p;
      return p;
    }
    for (t = 0; t <= t1; t++) {
      while (ap < S && DT.ss[order[ap]] <= t) act.push(order[ap++]);
      var keepAct = [];
      for (var a = 0; a < act.length; a++) { var k0 = act[a]; if (DT.ss[k0] + DT.sn[k0] <= t) { if (t > t0) endSeg(k0, DT.ss[k0] + DT.sn[k0] - 1); } else keepAct.push(k0); }
      act = keepAct;
      var lim = dates[t] >= LIMD ? 0.30 : 0.15, trading = t >= t0, k, x, i, o, h, l, cl, p, q;
      exited = {};
      if (!trading) continue;
      // 1) 보유 종목
      for (q = 0; q < bk.pos.length; q++) {
        p = bk.pos[q]; if (p.done) continue;
        x = DT.sp[p.k] + (t - DT.ss[p.k]);
        if (Fq[x] & 1) continue;
        o = px(X, Oq[x]); h = px(X, Hq[x]); l = px(X, Lq[x]); cl = px(X, Cq[x]);
        var lockDn = h <= p.lc * (1 - lim + 0.015);
        p.nb++;
        if (!c.hold) { if (!lockDn) exitPos(p, o, "다음날 시가"); if (!p.done) p.lc = cl; continue; }
        if (o <= p.stop && !lockDn) { exitPos(p, o, "손절"); continue; }
        if (o >= p.tgt) { exitPos(p, o, "익절"); continue; }
        var hiFirst = (h - o) < (o - l), pts = [o, hiFirst ? h : l, hiFirst ? l : h, cl], aa = o, done = false;
        for (var lg = 0; lg < 3 && !done; lg++) {
          var b = pts[lg + 1];
          if (b > aa && p.tgt <= b) { exitPos(p, p.tgt > aa ? p.tgt : aa, "익절"); done = true; }
          else if (b < aa && p.stop >= b && !lockDn) { exitPos(p, p.stop < aa ? p.stop : aa, "손절"); done = true; }
          aa = b;
        }
        if (!done && p.nb >= c.hold && !lockDn) { exitPos(p, cl, "기간"); done = true; }
        if (!p.done) p.lc = cl;
      }
      // 2) 매수
      var mkOn = !MK || MK[t] === 1, cands = [];
      for (a = 0; a < act.length; a++) {
        k = act[a]; i = t - DT.ss[k]; x = DT.sp[k] + i;
        if (Fq[x] & 1) { pend[k] = NaN; continue; }
        var j = DT.sj[k];
        if (c.mode === "b" && pend[k] === pend[k]) {           // 어제 신호 → 오늘 직전 저가 회복 시 매수
          var lv = pend[k], plo = pendLow[k]; pend[k] = NaN;
          if (pendT[k] === t - 1 && !bk.byJ[j] && !exited[j]) {
            o = px(X, Oq[x]); h = px(X, Hq[x]);
            if (h >= lv) cands.push({ k: k, j: j, x: x, b: true, lv: lv, plo: plo, r: Vq[x - 1] * 4294967296 + hsh(j, t) });
            else st.miss++;
          }
        }
        if (i < 1 || LS[x] === NOL || AG[x] < 4 || !(Lq[x] < LS[x])) continue;
        if (!mkOn || Vq[x] < c.tvc || (Fq[x] & need) !== need) continue;
        if (c.mode === "a") {
          if (Cq[x] > LS[x] && !bk.byJ[j] && !exited[j]) cands.push({ k: k, j: j, x: x, b: false, r: Vq[x] * 4294967296 + hsh(j, t) });
        } else if (Cq[x] <= LS[x]) { pend[k] = px(X, LS[x]); pendLow[k] = px(X, Lq[x]); pendT[k] = t; }
      }
      cands.sort(function(u, v){ return v.r - u.r; });
      for (q = 0; q < cands.length; q++) {
        var cd = cands[q]; x = cd.x; st.sig++;
        if (bk.byJ[cd.j]) continue;
        var pc = px(X, Cq[x - 1]);
        o = px(X, Oq[x]); h = px(X, Hq[x]); l = px(X, Lq[x]); cl = px(X, Cq[x]);
        if (!cd.b) {
          if (cl >= pc * (1 + lim - 0.015)) { st.lock++; continue; }
          p = open(cd.k, cd.j, x, cl, l);
          continue;
        }
        var fill = o >= cd.lv ? o : cd.lv;
        if (fill >= pc * (1 + lim - 0.015)) { st.lock++; continue; }
        p = open(cd.k, cd.j, x, fill, Math.min(cd.plo, l));
        if (!p) continue;
        if (h >= p.tgt) exitPos(p, Math.max(p.tgt, fill), "익절");        // 매수 뒤 같은 날 목표가 (매수 다리 끝이 고가)
        else p.lc = cl;
      }
      var e = bk.mark();
      if (b0 !== b0 && BI[t] === BI[t]) b0 = BI[t];
      eq.push(e); bq.push(BI[t] === BI[t] && b0 === b0 ? BI[t] / b0 : NaN);
      invS += e > 0 ? bk.expo / e : 0;
      bk.eqPrev = e;
    }
    var openPos = bk.pos.filter(function(p){ return !p.done; }).map(function(p){ return { p: p }; });
    openPos.forEach(function(o){ t = t1; var tr = bk.close(o.p, o.p.lc, t1 === T - 1 ? "보유 중" : "기간 끝", t1); tr.open = true; o.tr = tr; });
    var pending = [];
    if (c.mode === "b" && t1 === T - 1) for (var kk = 0; kk < S; kk++) if (pend[kk] === pend[kk] && pendT[kk] === T - 1) pending.push({ j: DT.sj[kk], lv: pend[kk], lo: pendLow[kk], cl: px(DT, DT.C[DT.sp[kk] + (T - 1 - DT.ss[kk])]) });
    return { c: c, t0: t0, t1: t1, eq: eq, bq: bq, dts: Array.prototype.slice.call(dates, t0, t1 + 1), trades: bk.trades, st: st,
             inv: invS / Math.max(1, eq.length), open: openPos, pending: pending };
  }

  var API = { decode: decode, runTurtle: runTurtle, runSoup: runSoup, turtleNext: turtleNext, turtleHold: turtleHold, mktOK: mktOK, px: px };
  if (typeof module !== "undefined" && module.exports) module.exports = API; else root.TTE = API;
})(typeof window !== "undefined" ? window : this);
