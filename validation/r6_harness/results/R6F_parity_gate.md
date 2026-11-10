# R6-F — gate de paridad antes/después (Repair de sondeo)

- **Base («antes»):** código de R6-D (`15ba0c7`; `src/` idéntico en `88be54e`), árbol extraído con `git archive 15ba0c7`. **Después:** árbol de trabajo con R6-F (sin commit).
- **Comando:** `BASE_TREE=<git archive 15ba0c7> AFTER_TREE=<árbol R6-F> PY=<python> OUT=<dir> validation/r6_harness/run_gate.sh BK68 BK46 SJ87 SJ97` (8 procesos concurrentes, con `--dfs`; su CPU no es comparable con los
  tiempos del informe) y, aparte, una corrida `--shadow-cl` del árbol R6-F por caso (cada llamada a `_candidatos_lote` se recalcula con la referencia y se compara).
- **Resultado:** `compare_parity.py` salió con código 0: ninguna diferencia en los 4 casos. Solo hashes y contadores.

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



## Repair de sondeo: nodos, paradas y hash de secuencia (antes = después)

| Caso | Etapa | Llamadas DFS | Nodos | Paradas | `seq_hash` antes | `seq_hash` después |
|---|---|---|---|---|---|---|
| SJ97 | probe/N6/repair | 12 | 24721 | {'max_nodos': 8, 'agotado': 4} | 058c7f806c5be01b | 058c7f806c5be01b (OK) |
| SJ97 | probe/N7/repair | 10 | 24023 | {'agotado': 2, 'max_nodos': 8} | 3802f83e7c5db6ff | 3802f83e7c5db6ff (OK) |
| SJ87 | probe/N5/repair | 13 | 24215 | {'max_nodos': 7, 'agotado': 6} | 41e831de598bfd55 | 41e831de598bfd55 (OK) |
| SJ87 | probe/N6/repair | 16 | 26363 | {'max_nodos': 8, 'agotado': 8} | 2de3f576bed9b766 | 2de3f576bed9b766 (OK) |

## Llamadas rápidas por fase y shadow (árbol R6-F)

| Caso | Llamadas rápidas por fase (corrida shadow) | Comparaciones shadow | Diferencias |
|---|---|---|---|
| SJ97 | `final/N8:lns`: 238228/238228, `probe/N6/repair`: 24713/24713, `probe/N7/repair`: 24015/24015; 0 en el resto de fases | 345463 | 0 |
| SJ87 | `final/N7:lns`: 94491/94491, `probe/N5/repair`: 24208/24208, `probe/N6/repair`: 26355/26355; 0 en el resto de fases | 200382 | 0 |
| BK68 | 0 en todas las fases | 170 | 0 |
| BK46 | 0 en todas las fases | 1000 | 0 |

Llamadas rápidas **nuevas** (frente a R6-D): solo las de `probe/N#/repair` (SJ97: 24 713 + 24 015 = 48 728; SJ87: 24 208 + 26 355 = 50 563). Las de `final/N#:lns` ya existían desde R6-D. BK68 y BK46 no pasan por el Repair de
sondeo: 0 llamadas rápidas.
