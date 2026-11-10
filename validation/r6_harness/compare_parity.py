"""Compara las salidas JSON de `harness.py` de dos árboles (antes/después) y emite una tabla de paridad en Markdown. Código de salida 1 si algo difiere.

    python compare_parity.py DIR_SALIDAS ETIQUETA_ANTES ETIQUETA_DESPUES CASO [CASO ...]

Compara: N, cajas, faltantes, errores, COMP, LAYOUT, hash de atributos, fuente, hash de metadata filtrada, `optimality_status` completo (N sondeados, estados, fuente del
witness, N elegido), HASHES DE LOS WITNESS (cada `registrar_feasible_directo`, el `best_feasible_pallets` al terminar el descenso y el resultado de cada
`_empacar_n_pallets` por etapa), nodos/paradas del DFS por etapa, iteraciones de LNS y hash de secuencia por etapa. La misma etiqueta de fuente no demuestra por sí
sola que el witness sea el mismo: se compara su COMP/LAYOUT.
"""
import json, sys
from pathlib import Path

d, a, b, *casos = sys.argv[1:]
fallo = False


def cargar(c, t): return json.loads((Path(d) / f"{c}_{t}.json").read_text())


def igual(x, y):
    global fallo
    ok = x == y
    fallo |= not ok
    return "OK" if ok else "DIFIERE"


print(f"| Caso | N / cajas | COMP | LAYOUT | atributos | metadata filtrada | fuente | optimality_status | witness (eventos + al cierre + por etapa) | DFS nodos/paradas | LNS iter. | seq_hash |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in casos:
    x, y = cargar(c, a), cargar(c, b)
    wx, wy = x["witness"], y["witness"]
    print(f"| {c} | {x['n']}/{x['boxes']} {igual((x['n'], x['boxes'], x['missing'], x['errors']), (y['n'], y['boxes'], y['missing'], y['errors']))} | {x['comp']} {igual(x['comp'], y['comp'])} | "
          f"{x['layout']} {igual(x['layout'], y['layout'])} | {x['attrs']} {igual(x['attrs'], y['attrs'])} | {x['meta_hash']} {igual(x['meta_hash'], y['meta_hash'])} | "
          f"{x['source']} {igual(x['source'], y['source'])} | {igual(x['optimality'], y['optimality'])} | "
          f"{igual((wx['witness_events'], wx['witness_at_final']), (wy['witness_events'], wy['witness_at_final']))} / {igual(wx['enp_returns'], wy['enp_returns'])} | "
          f"{igual(x['dfs'], y['dfs'])} | {igual(x['lns'], y['lns'])} | {x['seq_hash']} {igual((x['seq_hash'], x['seq_hash_by_tag']), (y['seq_hash'], y['seq_hash_by_tag']))} |")
    print(f"\n{c}: witness al cierre del descenso (antes) = {wx['witness_at_final']}")
    print(f"{c}: witness al cierre del descenso (después) = {wy['witness_at_final']}")
    print(f"{c}: salida final = comp {x['comp']} / layout {x['layout']}; ¿salida == witness? {x['comp'] == (wx['witness_at_final'] or {}).get('comp') and x['layout'] == (wx['witness_at_final'] or {}).get('layout')}\n")
    for k in sorted(k for k in x["optimality"] if k.endswith((".n", ".estado", ".fuente")) or k in ("optimality_status.status", "optimality_status.fuente", "optimality_status.best_feasible_n", "optimality_status.hard_lower_bound")):
        print(f"    {c} {k} = {x['optimality'][k]}" + ("" if x["optimality"][k] == y["optimality"].get(k) else f"  (después: {y['optimality'].get(k)})"))
    print()
sys.exit(1 if fallo else 0)
