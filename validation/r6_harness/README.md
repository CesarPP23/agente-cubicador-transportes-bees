# Arnés de validación V6.13-R6 (paridad y CPU por fase)

Reconstruido en la fase R6-D (el directorio temporal de las fases anteriores se perdió; los informes de R6-A…R6-C quedaron en `validation/`). Es **observación pura**:
envuelve funciones para contar, cronometrar y comparar; no cambia lo medido. No contiene datos de clientes; el archivo confidencial del Piloto (`R6_PILOT_XLSX`, solo
BK35/BK46) se lee desde donde esté en la máquina local y **nunca** se copia ni se versiona. Las salidas del arnés (JSON) incluyen metadata aplanada: no se versionan,
solo los resúmenes de hashes y contadores de los informes.

| Archivo | Qué hace |
|---|---|
| `harness.py` | Corre un caso (`BK31/35/43/46/52/53/68`, `SJ87`, `SJ97`) sobre el árbol `R6_ROOT` y guarda JSON: N, cajas, faltantes, errores, COMP, LAYOUT, hash de atributos, fuente, hash de metadata filtrada (sin campos temporales, floats a 6 decimales), `optimality_status` aplanado, **hashes de witness** (cada `registrar_feasible_directo`, `best_feasible_pallets` al cerrar el descenso y el resultado de cada `_empacar_n_pallets` por etapa), contadores, CPU por fase (`process_time`), pico de memoria (RSS), nodos/paradas de DFS, iteraciones de LNS y hash de secuencia por etapa. `--dfs` envuelve DFS/LNS (infla el CPU: no usar para tiempos); `--shadow-cl` recalcula cada llamada a `_candidatos_lote` con la referencia y aborta ante la primera diferencia (contenido, orden, desempates, bits de floats, identidad de `TorreCandidate`); `--shadow-podar` hace lo mismo con `_podar_libres`. |
| `compare_parity.py` | Compara dos juegos de JSON (antes/después) y emite la tabla de paridad en Markdown; sale con código 1 si algo difiere. |
| `run_gate.sh` | Lanza antes/después en paralelo para los casos pedidos y llama a `compare_parity.py`. |
| `golden6.py` | Golden 6 (COMP + LAYOUT + N + cajas contra `validation/v6.12_golden_baseline.json`). |

## Reproducir el gate de R6-D

```bash
git archive 921a409 | tar -x -C "$TMPDIR/base_r6d"          # árbol base (R6-C + aislamiento por ContextVar); R6-D = árbol de trabajo con el commit de R6-D
BASE_TREE="$TMPDIR/base_r6d" AFTER_TREE="$PWD" PY=<python del venv> OUT="$TMPDIR/out_r6d" validation/r6_harness/run_gate.sh BK68 BK46 SJ87 SJ97
```

Tiempos (un proceso por árbol, sin envoltorios, **sin otros procesos pesados en paralelo**, con la laptop enchufada y la tapa abierta):

```bash
R6_ROOT=<árbol> <python> validation/r6_harness/harness.py --case SJ97 --tag t_base --out "$OUT"
```

Shadow de `_candidatos_lote` (una corrida del árbol R6-D por caso): `harness.py --case SJ97 --tag shadow --out "$OUT" --shadow-cl`.
Golden 6: `<python> validation/r6_harness/golden6.py "$OUT/golden6.json"` (necesita el árbol bajo prueba como raíz o `P0_SOLVER_ROOT`).
Batería dirigida: los 31 archivos de pruebas listados en `V6.13_R6D_OPEN_FINAL_LNS_OPTIMIZATION.md` §6.

Convenciones: «antes» = commit base; «después» = árbol bajo prueba. Las etapas con corte por CPU (Repair de N fijo, Global de sondeo, Exact) pueden variar sus contadores
entre corridas aun con el mismo código («variaciones compatibles con cortes por CPU»); el gate las trata como tales y las localiza por etapa.
