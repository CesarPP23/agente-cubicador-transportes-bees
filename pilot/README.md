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

## Modo FIXED_N (`--mode FIXED_N`)

`Pallets_Objetivo` = posiciones reales y obligatorias de operación. El runner carga la hoja con el cargador oficial (`src/validacion.py::cargar_pallets_objetivo`), se la pasa al pipeline (`pallets_objetivo_por_cd`) y evalúa gates independientes por CD (el **peso es solo informativo**, ver abajo):

| gate | valores | criterio |
|---|---|---|
| A cubicaje | `PASS_FIXED_N_GEOMETRY` / `FAIL_FIXED_N` | exactamente N objetivo, 100 % de la demanda elegible colocada, 0 faltantes, 0 errores geométricos |
| BAT | `PASS_BAT_ROUTING` / `FAIL_BAT_ROUTING` | ver sección Cigarros/Vapes |
| C determinismo | `REPEAT_MATCH` / `DETERMINISM_DIVERGENCE` / `NOT_CHECKED` | requiere `--repeat >= 2`: N, cajas, COMP, LAYOUT, IDs y salida pública idénticos |

`RESULT` = gate A: `FAIL_FIXED_N` | `PASS_FIXED_N_GEOMETRY`. Cobertura operacional = gate A y gate BAT. Cigarros/BAT separados **no** cuentan como faltantes.

**Peso = `INFORMATIONAL_ONLY`.** La semántica contractual de `Peso bruto por unidad` no está validada, así que el peso no participa en PASS/FAIL, factibilidad, cobertura ni clasificación. El reporte lo muestra solo como `WEIGHT_DATA_STATUS = WEIGHT_DATA_UNVALIDATED` (`peso_calculado`, `cajas_con_peso_0`, `skus_sin_peso_validable`), sin interpretarlo como válido, inválido, sobrepeso ni bajo peso.

### Cigarros / Vapes (BAT): demanda separada, no excluida

Contrato operacional: demanda total → **demanda no BAT → cubicador** (única que consume `Pallets_Objetivo`) + **Cigarros/Vapes → hoja `Cigarros_Vapes`** para que el HUB los consolide por CD y los cargue donde haya espacio. BAT no consume N, no participa en geometría ni ocupación y no es faltante del cubicador; en los reportes se llama *demanda Cigarros/Vapes separada*, nunca "excluida".

Por corrida se genera `pilot/runs/<run_id>/Cigarros_Vapes.xlsx` (hoja `Cigarros_Vapes`: `CD, SKU, Descripción, Categoría, Subcategoría, Unidades, Cajas_Teoricas, Cajas_Consolidacion_CD` por SKU; hoja `Resumen_CD`: subtotales por CD) a partir de lo que el pipeline emite hoy (`demanda_cigarros_df`). Se concilia contra una definición de negocio calculada **directo del input** (Categoría Cigarros o Subcategoría `vape`/`vapes`): por CD, SKUs, unidades y cajas teóricas deben coincidir (pérdida cero), las cajas de consolidación deben ser las de `bat.consolidar_bat_por_cd`, y ningún SKU BAT puede estar en un pallet cubicado.

- Gate BAT: `PASS_BAT_ROUTING` / `FAIL_BAT_ROUTING`.
- `PASS_OPERATIONAL_COVERAGE` solo si pasan el gate A (`PASS_FIXED_N_GEOMETRY`) y el gate BAT. El peso es informativo y no interviene.
- Identidad por CD: `demanda_original = demanda_cubicable + demanda_cigarros_vapes` (en cajas teóricas).
- El exportador productivo no se toca en el piloto; las diferencias con el contrato (nombre de hoja, columnas, `SUBCATEGORIAS_BAT`) se listan en el reporte como requerimientos de producto.

Un `FAIL_FIXED_N` es `PILOT_EXCEPTION`: se guarda el input y no se aumenta N ni se recalibra nada.

## Clasificación (modo OPEN; por CD, solo por cantidad de pallets; menos es mejor)

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
