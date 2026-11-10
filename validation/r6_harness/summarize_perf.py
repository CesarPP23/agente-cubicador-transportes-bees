"""Resume corridas de rendimiento de `harness.py` (sin --dfs/--shadow) por árbol y repetición: CPU de armado, CPU de Repair de sondeo por N, `_candidatos_lote` en Repair y pico de memoria.

    python summarize_perf.py DIR CASO [CASO ...]     (archivos CASO_p<rep>_<before|after>.json)
"""
import glob, json, re, statistics as st, sys
from collections import defaultdict

d, *casos = sys.argv[1:]
for c in casos:
    runs = defaultdict(dict)
    for f in glob.glob(f"{d}/{c}_p*_*.json"):
        m = re.search(r"_p(\d+)_(before|after)\.json$", f)
        runs[int(m.group(1))][m.group(2)] = json.load(open(f))
    reps = sorted(runs)
    keys = sorted({k for r in runs.values() for t in r.values() for k in t["stage_cpu"] if k.endswith("/repair")})
    print(f"\n### {c}  (repeticiones: {len(reps)}; orden: {', '.join(f'r{r}: ' + ('antes→después' if r % 2 else 'después→antes') for r in reps)})")
    print("| rep | árbol | CPU de armado (s) | " + " | ".join(f"Repair {k.split('/')[1]} (s)" for k in keys) + " | `_candidatos_lote` en Repair (s) | pico RSS (MB) |")
    print("|---|---|---|" + "---|" * len(keys) + "---|---|")
    agg = defaultdict(lambda: defaultdict(list))
    for r in reps:
        for t in ("before", "after"):
            x = runs[r].get(t)
            if not x: continue
            rep_cl = sum(v["cpu"] for k, v in x["cl"].items() if k.endswith("/repair"))
            print(f"| {r} | {t} | {x['armar_cpu_s']:.1f} | " + " | ".join(f"{x['stage_cpu'].get(k, 0):.1f}" for k in keys) + f" | {rep_cl:.1f} | {x['peak_rss_mb']:.1f} |")
            agg[t]["cpu"].append(x["armar_cpu_s"]); agg[t]["rss"].append(x["peak_rss_mb"]); agg[t]["cl"].append(rep_cl)
            for k in keys: agg[t][k].append(x["stage_cpu"].get(k, 0))
    if agg["before"]["cpu"] and agg["after"]["cpu"]:
        mb, ma = (lambda t, k: st.mean(agg[t][k]))("before", "cpu"), st.mean(agg["after"]["cpu"])
        print(f"\nMedia CPU de armado: antes {mb:.1f} s → después {ma:.1f} s (**{mb - ma:+.1f} s**, {100 * (ma - mb) / mb:+.1f} %); por repetición: " +
              ", ".join(f"r{r}: {runs[r]['before']['armar_cpu_s'] - runs[r]['after']['armar_cpu_s']:.1f} s" for r in reps if 'before' in runs[r] and 'after' in runs[r]))
        tot = 0.0
        for k in keys:
            b, a = st.mean(agg["before"][k]), st.mean(agg["after"][k]); tot += b - a
            print(f"  {k}: {b:.1f} → {a:.1f} s ({b - a:+.1f} s, {100 * (a - b) / b:+.1f} %)")
        print(f"  Ahorro total de Repair de sondeo (suma de N): {tot:.1f} s")
        print(f"  Pico RSS medio: {st.mean(agg['before']['rss']):.1f} → {st.mean(agg['after']['rss']):.1f} MB")
