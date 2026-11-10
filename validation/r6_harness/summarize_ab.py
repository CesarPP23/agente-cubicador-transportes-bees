"""Resume las corridas de `ab_repair_probe.py --mode timing` de un directorio: por bloque (caso, N) y repetición, y agregado (media, mín., máx., desviación)."""
import glob, json, statistics as st, sys
from collections import defaultdict

d = sys.argv[1]; total_cpu = {"SJ97": float(sys.argv[2]), "SJ87": float(sys.argv[3])} if len(sys.argv) > 3 else {}
blk = defaultdict(list)
for f in sorted(glob.glob(f"{d}/ab_*_timing_*.json")):
    r = json.load(open(f)); blk[(r["case"], r["n"])].append((f, r))
for (c, n), runs in sorted(blk.items()):
    print(f"\n### {c} N={n}  ({len(runs)} repeticiones, {runs[0][1]['calls']} llamadas por repetición)")
    print("| rep | orden inicial | ref µs/llamada | rápida µs/llamada | ahorro por llamada | ahorro (s) | ref primero: ahorro | rápida primero: ahorro | % llamadas donde la rápida gana |")
    print("|---|---|---|---|---|---|---|---|---|")
    for f, r in runs:
        print(f"| {f.rsplit('_', 1)[-1][:-5]} | {'ref' if r['parity_start'] == 0 else 'rápida'} | {r['ref_us_per_call']:.0f} | {r['fast_us_per_call']:.0f} | {r['saving_pct']:.1f} % | {r['saving_s']:.2f} | "
              f"{r['ref_first']['saving_pct']:.1f} % | {r['fast_first']['saving_pct']:.1f} % | {100 * r['fast_faster_fraction']:.0f} % |")
    sp = [r["saving_pct"] for _, r in runs]; ss = [r["saving_s"] for _, r in runs]
    print(f"\nAhorro por llamada: media {st.mean(sp):.1f} %, mín. {min(sp):.1f} %, máx. {max(sp):.1f} %; **amplitud (máx.−mín.) {max(sp) - min(sp):.2f} pp**; desviación estándar POBLACIONAL (pstdev, n={len(sp)}) {st.pstdev(sp):.2f} pp. "
          f"Ahorro del bloque: media {st.mean(ss):.2f} s (mín. {min(ss):.2f}, máx. {max(ss):.2f}; amplitud {max(ss) - min(ss):.3f} s).")
    # «ref primero» y «rápida primero» comparan llamadas DISTINTAS (pares/impares); el efecto del orden es el promedio de las dos fases de alternancia (el efecto de subconjunto cambia de signo)
    d0 = [r["ref_first"]["saving_pct"] - r["fast_first"]["saving_pct"] for _, r in runs if r["parity_start"] == 0]
    d1 = [r["ref_first"]["saving_pct"] - r["fast_first"]["saving_pct"] for _, r in runs if r["parity_start"] == 1]
    if d0 and d1:
        print(f"Efecto del orden de ejecución (promedio de las dos fases de alternancia): {(st.mean(d0) + st.mean(d1)) / 2:+.2f} pp (efecto de subconjunto par/impar: {(st.mean(d0) - st.mean(d1)) / 2:+.2f} pp).")
    if c in total_cpu: print(f"Sobre el CPU de armado del caso ({total_cpu[c]:.1f} s): {100 * st.mean(ss) / total_cpu[c]:.2f} %.")
    qs = [[x["saving_pct"] for x in r["by_ref_cost_quartile"]] for _, r in runs]
    print("Ahorro por cuartil de costo de la llamada (Q1 = más baratas … Q4 = más caras), media de repeticiones: " + ", ".join(f"Q{i + 1} {st.mean(q[i] for q in qs):.1f} %" for i in range(4)))
