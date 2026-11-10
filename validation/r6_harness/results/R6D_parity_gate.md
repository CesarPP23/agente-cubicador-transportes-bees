# R6-D — gate de paridad antes/después (resumen reproducible)

- **Base («antes»):** commit `921a409` (R6-C + aislamiento por `ContextVar` de R6-A/P1-A), árbol extraído con `git archive 921a409`.
- **Después:** árbol con R6-D (cambio en `_empacar_n_pallets`: contexto rápido en el LNS secuencial cuando `presupuesto_global_expansiones is not None`).
- **Comando:** `BASE_TREE=<git archive 921a409> AFTER_TREE=<árbol R6-D> PY=<python del venv> OUT=<dir> validation/r6_harness/run_gate.sh BK68 BK46 SJ87 SJ97`
  (8 procesos concurrentes: un proceso por caso y árbol, con `--dfs`; el CPU de esta corrida **no** es comparable con los tiempos del informe).
- **Resultado:** `compare_parity.py` salió con código 0 (ninguna diferencia) en los 4 casos.
- Solo hashes y contadores; sin SKUs ni filas del Piloto.

## Tabla de paridad

| Caso | N / cajas | COMP | LAYOUT | atributos | metadata filtrada | fuente | optimality_status | witness (eventos + al cierre + por etapa) | DFS nodos/paradas | LNS iter. | seq_hash |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BK68 | 3/385 OK | 370b44a56dc2dd49 OK | da51e73679957510 OK | df2d67adeff9c9a6 OK | cd70d7955a117bbd OK | OPEN_LNS_FINAL_MATERIALIZATION OK | OK | OK / OK | OK | OK | a076dad269b84e78 OK |

BK68: witness al cierre del descenso (antes) = {'best_feasible_n': 3, 'n': 3, 'boxes': 385, 'comp': '370b44a56dc2dd49', 'layout': 'da51e73679957510'}
BK68: witness al cierre del descenso (después) = {'best_feasible_n': 3, 'n': 3, 'boxes': 385, 'comp': '370b44a56dc2dd49', 'layout': 'da51e73679957510'}
BK68: salida final = comp 370b44a56dc2dd49 / layout da51e73679957510; ¿salida == witness? True

    BK68 optimality_status.best_feasible_n = 3
    BK68 optimality_status.hard_lower_bound = 3
    BK68 optimality_status.status = PROVEN_MINIMUM
    BK68 optimality_status.trace.0.estado = FEASIBLE
    BK68 optimality_status.trace.0.fuente = greedy_incumbente
    BK68 optimality_status.trace.0.n = 4
    BK68 optimality_status.trace.1.estado = FEASIBLE
    BK68 optimality_status.trace.1.fuente = probe
    BK68 optimality_status.trace.1.n = 3

| BK46 | 16/1891 OK | 258ef7bfa79af35b OK | 56a58012057dc994 OK | 14257c6c226aca94 OK | d2fa82f5df267ed7 OK | EXACT_N_GREEDY_INCUMBENT OK | OK | OK / OK | OK | OK | 51070146441844be OK |

BK46: witness al cierre del descenso (antes) = None
BK46: witness al cierre del descenso (después) = None
BK46: salida final = comp 258ef7bfa79af35b / layout 56a58012057dc994; ¿salida == witness? False


| SJ87 | 7/729 OK | fc63312a9ba70f22 OK | 29941d45ed4ab89d OK | bc26f7249a2bb7f0 OK | 6b61585b4e5c1ba9 OK | OPEN_LNS_FINAL_MATERIALIZATION OK | OK | OK / OK | OK | OK | 77af29206b97513e OK |

SJ87: witness al cierre del descenso (antes) = {'best_feasible_n': 7, 'n': 7, 'boxes': 729, 'comp': '01efdaa0ff407c6e', 'layout': '3eff30192383d544'}
SJ87: witness al cierre del descenso (después) = {'best_feasible_n': 7, 'n': 7, 'boxes': 729, 'comp': '01efdaa0ff407c6e', 'layout': '3eff30192383d544'}
SJ87: salida final = comp fc63312a9ba70f22 / layout 29941d45ed4ab89d; ¿salida == witness? False

    SJ87 optimality_status.best_feasible_n = 7
    SJ87 optimality_status.hard_lower_bound = 5
    SJ87 optimality_status.status = BEST_FEASIBLE_UNPROVEN
    SJ87 optimality_status.trace.0.estado = FEASIBLE
    SJ87 optimality_status.trace.0.fuente = greedy_incumbente
    SJ87 optimality_status.trace.0.n = 7
    SJ87 optimality_status.trace.1.estado = UNKNOWN
    SJ87 optimality_status.trace.1.fuente = probe
    SJ87 optimality_status.trace.1.n = 6
    SJ87 optimality_status.trace.2.estado = UNKNOWN
    SJ87 optimality_status.trace.2.fuente = probe
    SJ87 optimality_status.trace.2.n = 5

| SJ97 | 8/1305 OK | 38d7bbb28bbcd84f OK | 8c4dfe7999645b52 OK | ad201479d09939a2 OK | 98b0d37e365e219a OK | OPEN_witness_probe_no_reproducido_por_LNS_final OK | OK | OK / OK | OK | OK | d2a92ed3009349f8 OK |

SJ97: witness al cierre del descenso (antes) = {'best_feasible_n': 8, 'n': 8, 'boxes': 1305, 'comp': '38d7bbb28bbcd84f', 'layout': '8c4dfe7999645b52'}
SJ97: witness al cierre del descenso (después) = {'best_feasible_n': 8, 'n': 8, 'boxes': 1305, 'comp': '38d7bbb28bbcd84f', 'layout': '8c4dfe7999645b52'}
SJ97: salida final = comp 38d7bbb28bbcd84f / layout 8c4dfe7999645b52; ¿salida == witness? True

    SJ97 optimality_status.best_feasible_n = 8
    SJ97 optimality_status.fuente = witness_probe_no_reproducido_por_LNS_final
    SJ97 optimality_status.hard_lower_bound = 6
    SJ97 optimality_status.status = BEST_FEASIBLE_UNPROVEN
    SJ97 optimality_status.trace.0.estado = FEASIBLE
    SJ97 optimality_status.trace.0.fuente = greedy_incumbente
    SJ97 optimality_status.trace.0.n = 8
    SJ97 optimality_status.trace.1.estado = UNKNOWN
    SJ97 optimality_status.trace.1.fuente = probe
    SJ97 optimality_status.trace.1.n = 7
    SJ97 optimality_status.trace.2.estado = UNKNOWN
    SJ97 optimality_status.trace.2.fuente = probe
    SJ97 optimality_status.trace.2.n = 6



**SJ97: resultado de cada `_empacar_n_pallets` (orden de ejecución: sondeos en el orden del descenso, luego la materialización final); idéntico antes/después: True**

| # | N | cajas colocadas | COMP | LAYOUT | faltantes (hash) |
|---|---|---|---|---|---|
| 1 | 7 | 1144 | fe5ce4ac79c88eac | 5067623590e11493 | 559612867a1bb18e |
| 2 | 6 | 1024 | d30ddbfa2c9a83f2 | eeb7e34dcd4e8b9d | c79f3325bf6aa764 |
| 3 | 8 | 1252 | c7e671bbbe7370b2 | c60c4d980ec85676 | 23ad5853284ceeec |

**SJ87: resultado de cada `_empacar_n_pallets` (orden de ejecución: sondeos en el orden del descenso, luego la materialización final); idéntico antes/después: True**

| # | N | cajas colocadas | COMP | LAYOUT | faltantes (hash) |
|---|---|---|---|---|---|
| 1 | 6 | 664 | 959c54a8103f0006 | 944530ef79e8f731 | 052db10177c42de1 |
| 2 | 5 | 595 | ddd34ed547d5d37b | 49ef90d566264537 | fcc0853d77df57b7 |
| 3 | 7 | 729 | fc63312a9ba70f22 | 29941d45ed4ab89d | 4f53cda18c2baa0c |

## Lectura del witness

- **SJ97:** el witness al cierre del descenso es el greedy de N=8 (COMP `38d7bbb28bbcd84f`, LAYOUT `8c4dfe7999645b52`, 1 305 cajas). La salida final tiene los **mismos** COMP y LAYOUT, así que
  la fuente `witness_probe_no_reproducido_por_LNS_final` corresponde, en ambos árboles, al mismo witness (no solo la misma etiqueta). La materialización final de N=8 devolvió 1 252 cajas
  (COMP `c7e671bbbe7370b2`, LAYOUT `c60c4d980ec85676`, también idéntico antes/después) y no se usó.
- **SJ87:** el witness (greedy de N=7: COMP `01efdaa0ff407c6e`, LAYOUT `3eff30192383d544`) es **distinto** de la salida final, que viene de la materialización final (729 cajas, COMP `fc63312a9ba70f22`,
  LAYOUT `29941d45ed4ab89d`); ambos hashes idénticos antes/después.
- **BK68:** `PROVEN_MINIMUM` N=3: salida == witness del sondeo de N=3 en ambos árboles. **BK46:** camino exact-N incumbent, no pasa por el descenso de OPEN (sin witness).
