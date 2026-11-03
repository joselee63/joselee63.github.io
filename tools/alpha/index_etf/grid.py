import sys
from strat import *
mode = sys.argv[1] if len(sys.argv) > 1 else "close"
for nm in ("K", "Q"):
    df = pair(nm); P = df.cL
    print(f"\n===== {'코스피 (KODEX200·인버스)' if nm=='K' else '코스닥 (코스닥150·선물인버스)'}  체결={mode}")
    print(f"{'전략':<28}{'연수익':>7}{'MDD':>7}{'샤프':>6}{'매매/년':>7}{'롱%':>5}{'인%':>5} | {'앞':>6}{'뒤':>6}" + (f"{'03~':>7}" if nm=="K" else "") + f"{'세후':>7}{'+년':>6}")
    for k, f in STRATS.items():
        wl, wi = f(P)
        p = PER[nm]
        s = run(df, wl, wi, mode, *p[0]); st = stats(s)
        sa = stats(run(df, wl, wi, mode, *p[1])); sb = stats(run(df, wl, wi, mode, *p[2]))
        ext = f"{stats(run(df, wl, wi, mode, *p[3]))['cagr']*100:7.1f}" if nm == "K" else ""
        stx = stats(run(df, wl, wi, mode, *p[0], tax=0.154))
        yrp = (st['yr'] > 0).sum(); ny = len(st['yr'])
        print(f"{k:<28}{st['cagr']*100:7.1f}{st['mdd']*100:7.1f}{st['sh']:6.2f}{st['trd']:7.1f}{st['expL']*100:5.0f}{st['expI']*100:5.0f} | {sa['cagr']*100:6.1f}{sb['cagr']*100:6.1f}{ext}{stx['cagr']*100:7.1f}{yrp:>4}/{ny}")
