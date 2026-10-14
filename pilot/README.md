# Piloto controlado V6.12-RC1

Harness de **medición y reporte**. No es una versión del solver y **no recalibra RC1** con datos del piloto.

- Versión congelada: `v6.12-rc1` (`f038694`). El runner se **niega a correr** si `src/`, `config.py` o `models.py` difieren del tag o tienen cambios sin commitear (`--allow-solver-mismatch` existe solo para diagnóstico y marca la corrida).
- Solo se instrumenta un cronómetro por CD alrededor de `armar_pallets_bloques`. No cambia resultados (en V6.12 F4 vs F2 los hashes fueron idénticos).

## Cómo cargar un caso real

1. **Input**: un `.xlsx` con las hojas `Envios_Julio`, `Maestro_SKUs` y `UMA` (mismo formato que `Cubicaje18.07.2026.xlsx`). Puede estar en cualquier ruta; se recomienda `pilot/cases/<caso>/input.xlsx` (`pilot/cases/` no se versiona).
2. **Plan real/manual (opcional)**: un CSV con columnas `case_id,cd,n_pallets_operacion,resultado_fisico,observaciones` (ver `operacion_template.csv`). `case_id` es opcional; las filas sin `case_id` aplican a cualquier caso. Solo se usa para **comparar y reportar**, nunca para alterar el solver.
3. **Correr**:

```bash
.venv/bin/python pilot/pilot_runner.py --input pilot/cases/semana_42/input.xlsx \
    --case-id semana_42 --operacion pilot/cases/semana_42/operacion.csv --repeat 2 --nota "texto libre"
```

   - `--cds BK31,SJ97` limita a un subconjunto de CDs.
   - `--repeat N` repite la corrida N veces y compara N, cajas, COMP, LAYOUT, IDs y salida pública; cualquier diferencia se marca `PILOT_EXCEPTION`.
   - Cada corrida guarda `pilot/runs/<run_id>/run.json` con, por CD: demanda de cajas, SKUs, N pallets, cajas colocadas, faltantes, errores, peso máximo, altura máxima, pallets parciales (< `ALTURA_TOLERADO_MIN`), altura media, ocupación media (área XY / área de pallet), origen del resultado (`FINAL_MATERIALIZATION` / `WITNESS_FALLBACK` / `GREEDY_O_PALLETS_OBJETIVO`), wall, CPU, COMP, LAYOUT, versión, e `input hash` (sha256 del archivo), `run_id` y fecha.
4. **Reporte consolidado**:

```bash
.venv/bin/python pilot/pilot_report.py          # usa la última corrida por (caso, input, CD); --all-runs para todas
```

   Genera `pilot/report/pilot_report.md` y `pilot/report/pilot_table.csv`.

## Clasificación (por CD, solo por cantidad de pallets; menos es mejor)

| clase | criterio |
|---|---|
| `BETTER` / `EQUIVALENT` / `WORSE` | N del cubicador `<` / `=` / `>` N de operación (con `n_pallets_operacion` cargado) |
| `INVALID` | excepción del pipeline, errores de validación geométrica, demanda sin colocar o sin resultado |
| `NO_OPERATION_DATA` | resultado válido sin plan real con que comparar (se cuenta aparte) |

## `PILOT_EXCEPTION`

Se marca (y se guarda el **input exacto** en `pilot/exceptions/<run_id>/`, más el extracto de envíos del CD y `motivos.json`) cuando hay: excepción del pipeline o input ilegible, CD `INVALID` o `WORSE`, divergencia entre repeticiones, o solver distinto de RC1. Se analiza después; **no se recalibra RC1**.

## Resumen del reporte

Total de casos, % con 100 % de demanda, % con cero violaciones, BETTER/EQUIVALENT/WORSE/INVALID, pallets cubicador vs operación (suma y diferencia), runtime p50/p90/max por CD y wall del batch, fallbacks al witness y excepciones.

## Notas

- El camino es el **abierto** (el cubicador elige N). Wall/CPU dependen de la máquina y la carga: el primer batch de un proceso incluye arranque en frío; usar `--repeat` para ver ambos.
- `pilot/runs/`, `pilot/exceptions/`, `pilot/cases/` y `pilot/report/` están en `pilot/.gitignore` (datos reales).
