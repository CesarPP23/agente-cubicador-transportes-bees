# Documentación técnica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `d7051a9` (2026-08-21) — único motor activo: **SKU_BLOQUE, armado por camas**. `src/` 19 módulos (se recuperó `layout_solver.py`, disponible pero no cableado — ver sección 4.9).
**Alcance:** arquitectura de código, contratos entre módulos, estructuras de datos y cómo operar el proyecto.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_TECNICA*.md`. La lógica de negocio (invariantes, prioridades, benchmark) está en `DOCUMENTACION_LOGICA.md`. El historial completo de cómo se llegó a este estado vive en `Parches/v5/PATCH_LOG.md`.

---

## 1. Qué hace el sistema

A partir de tres hojas de un Excel (`Envios_Julio`, `Maestro_SKUs`, `UMA`), calcula cómo armar pallets físicos (base 120×100cm) por centro de distribución (CD): qué SKUs van en cada pallet, en qué cantidad y posición, y con qué altura/peso resultante. El pallet se arma **capa por capa (cama por cama)**, de piso a techo — nunca por columnas verticales aisladas de un solo SKU (ver `DOCUMENTACION_LOGICA.md` sección 9).

Input: `envios, maestro, uma` (DataFrames) → `src.pipeline.ejecutar_pipeline(...)` → `ResultadoPipeline` (plan de picking, log de validación, resumen por CD, auditoría geométrica, benchmark, lista de `PalletV5` para inspección/export detallado).

## 2. Entorno

- Python 3.11 (via `uv`, venv en `env/`)
- Dependencias (`requirements.txt`): `pandas>=2.0`, `openpyxl>=3.1`, `streamlit>=1.35`, `matplotlib>=3.8`, `pytest>=8.0`
- Dataset real de referencia: `Cubicaje18.07.2026.xlsx` (raíz del repo)

```bash
source env/bin/activate
python -m pytest -q
streamlit run app.py
```

Nota de compatibilidad: el código usa sintaxis de tipos `X | None` (PEP 604, válida desde Python 3.10) y no depende de nada exclusivo de 3.11 en el código propio — el requisito de 3.11 es por el venv del proyecto, no por una dependencia dura del lenguaje.

## 3. Flujo del pipeline

Un solo camino — `pipeline.ejecutar_pipeline` llama directo a `pipeline_sku_bloque.ejecutar_core_sku_bloque`:

```
VAL     validacion.validar_y_limpiar(envios, maestro, uma)         -> df_validado, log_df
DEM     demanda.normalizar_demanda(df_validado)                     -> df_demanda
GEO     reconciliacion_geometrica.reconciliar(df_demanda)           -> df_geo, auditoria_geometrica_df
DER     derivados.calcular_derivados(df_geo)                        -> df_derivado   (acá nace Cajas_Cama_Efectivo)
        _construir_info_sku(df_derivado)                            -> info_sku (dict por SKU)
SPLIT   bat.separar_bat(df_derivado)                                -> df_no_bat, df_bat
        clasificación: df_clasificado / df_no_clasificado / df_geometria_insuficiente
BATPOOL bat.consolidar_bat_por_cd(df_bat)                           -> cajas_bat_por_cd
        bat.construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku) -> df_bat_pseudo
        df_armado = concat(df_clasificado, df_bat_pseudo)
CAMAS   por cada CD: packing_bloques.armar_pallets_bloques(grupo, cd, contador) -> list[PalletV5]
        bat.renombrar_pallets_bat_puros / bat.asignar_cajas_bat_a_torres        (in-place)
        estabilidad.calcular_estabilidad(p)  guardado en p.metadata["estabilidad"]
ADAPT   _palletv5_a_pallet(pv5, info_sku)  por cada PalletV5          -> Pallet (modelo legado, para reusar soporte/export/benchmark)
SOP     soporte.clasificar_soporte_pallet(pallet)  por cada pallet    (no-op actual, ver sección 8)
PESO    validacion_peso.validar_pesos(todos_pallets, info_sku)       (in-place, solo reporte)
BENCH   benchmark.calcular_kpis(...) / benchmark_df(...)
EXP     exportar.construir_plan_picking_df / construir_resumen_cd_df
```

`GEO` corre sobre **toda** la demanda (BAT incluido) antes del `SPLIT`: no porque BAT necesite geometría (usa una caja fija), sino para que `info_sku` quede completo para todos los SKUs antes de separar BAT.

`CAMAS` corre por CD; además de los CDs con demanda clasificada normal, hay un segundo loop que cubre CDs que solo tienen demanda BAT (sin ningún otro SKU clasificado) para no perder esa demanda en silencio.

## 4. Módulos

### 4.1 `config.py`

Todas las constantes del sistema, sin lógica de negocio compleja. Grupos:

| Grupo | Constantes clave |
|---|---|
| Pallet | `PALLET_LARGO=120`, `PALLET_ANCHO=100`, `ALTURA_PALLET_VACIO=14.92` |
| Sobresaliente | `SOBRESALIENTE_MAX_CM=2.5`, `PALLET_LARGO_EFECTIVO=125`, `PALLET_ANCHO_EFECTIVO=105` — hoy solo se usan para VALIDAR datos del Maestro, no en el packing real (ver `DOCUMENTACION_LOGICA.md` 5.2) |
| Rotación acostada | `CATEGORIAS_ROTACION_LIBRE=["Comestibles","Cigarros"]` |
| Altura | `ALTURA_TARGET=198.3`, `ALTURA_NOMINAL_MIN=190.0`, `ALTURA_MAX_OBSERVADA=215.0`, `ALTURA_HARD_VALIDADA=None` |
| Peso | `PESO_ALERTA_KG=1400`, `PESO_HARD_KG=1430`, `PESO_PARAMETROS_VALIDADOS=False` |
| BAT | `CATEGORIAS_BAT=["Cigarros"]`, `CAJA_BAT_LARGO=52.5`, `CAJA_BAT_ANCHO=34.0`, `CAJA_BAT_ALTO=49.0`, `CAJA_BAT_CAPACIDAD_UNIDADES=1000` |
| Categorías | `ORDEN_CATEGORIAS`, `CATEGORIAS_REMATE`, `nivel_de_categoria()`, `normalizar_categoria()` — metadata de reporte, ya no gatean el armado |

Funciones: `estado_altura(altura)` (zona de reporte), `estado_pallet_por_altura(altura)` (traduce zona → `ESTADO_*`), `normalizar_categoria(valor)`, `nivel_de_categoria(categoria)`.

Aliases retrocompatibles todavía referenciados por código/tests: `ALTURA_TOTAL_MIN`, `ALTURA_TOTAL_MIN_TOLERADO`, `ALTURA_TOTAL_MAX`, `ALTURA_TOPE_DURO`, `PESO_TOPE_ELASTICO_KG`.

`TOLERANCIA_HUECO_CAMA_CM` (8.0) — la tolerancia de hueco entre SKUs de una misma cama — **vive en `packing_bloques.py`, no en `config.py`** (ver sección 4.9).

### 4.2 `models.py`

Dos generaciones de dataclasses conviven en el archivo — la segunda es la que de verdad produce el armado hoy:

**Modelo legado (`Cama`/`Pallet`)** — sigue existiendo porque `soporte.py`, `exportar.construir_plan_picking_df`, `benchmark.py` y la vista 2D de `app.py`/`visualizacion.py` están escritos contra él. `_palletv5_a_pallet` (en `pipeline_sku_bloque.py`) adapta cada `PalletV5` a un `Pallet` con `camas=[]` siempre — no confundir este `Cama` (legado, capas por categoría de V3/V4) con el concepto de "cama" del armado actual, que vive enteramente en `Torre`/`PalletV5` agrupadas por `z` (sección 4.9), sin usar esta dataclass.

- `GeometriaSKU`: resultado de reconciliar un SKU (`fuente_geometria`, `acostada`, etc.)
- `CajaBAT`: caja física fija de consolidación de Cigarros
- `Placement` / `Cama` (legado): modelo por capas de V3/V4 — properties (`nivel_efectivo`, `categoria_remate`, `es_flexible`, `fill_ratio`) que ya no se ejercitan en el pipeline actual
- `PalletLinea` / `Pallet`: unidad de salida del plan de picking — `camas` queda vacío, `lineas` sí se llena

**Modelo columnar (`Torre`/`PalletV5`)** — el que arma `packing_bloques.py` de verdad. Una "cama" del armado actual **no es una dataclass propia**: es, implícitamente, el conjunto de `Torre`s de un mismo `PalletV5` que comparten el mismo `z` (ver `_torres_por_z` en los tests, sección 7).

- `OrientacionCaja` (frozen): una orientación válida de una caja.
- `PlacementCaja`: una caja física concreta (x, y, z, orientación) dentro de una torre.
- `Torre`: cajas del mismo SKU apiladas verticalmente en una posición XY fija. `altura` (`cantidad × alto_caja`) y `area_base` son properties derivadas. `z` es la base del segmento dentro de la pila de producto — con el armado por camas, todas las torres de la MISMA cama comparten el mismo `z` (nunca crecen más alto que la altura de esa cama, porque el cuboide libre que las contiene tiene esa profundidad como techo).
- `PalletV5`: `torres`, `cajas_bat`, `altura_final`, `peso_estimado`, `ocupacion_xy`, `volumen_utilizado`, `estado`, `metadata`.
- `ResultadoPipeline`: además de los campos del modelo legado, trae `pallets_v5: list[PalletV5]`.

### 4.3 `src/validacion.py` — Paso 0

`cargar_hojas(ruta_o_buffer)` lee las 3 hojas del Excel. `validar_y_limpiar(envios, maestro, uma)` aplica las reglas V1-V9 (normalización de SKU, duplicados CD+SKU sumados, exclusión de Cajas Teóricas ≤0, SKU sin Maestro/UMA excluido, "Cajas por PH"/"Camas por PH" fuera de rango marcados no-confiables, "Cajas por cama" nulo/0 marcado para fallback geométrico, dimensión imposible para el pallet excluida, alto de caja sobre el máximo excluido, peso fuera de rango sano marcado `Peso_No_Validable`, categoría no reconocida excluida del apilado automático) y devuelve `(df, log_df)` con cada exclusión trazada.

Nota: la validación V3 sigue marcando "Cajas por PH" como no-confiable si excede el umbral, y esa columna sigue viajando en el DataFrame — pero el armado actual (`packing_bloques.py`) **no la lee en ningún punto** (ver sección 4.9). Es un remanente inofensivo de la arquitectura anterior, no un bug.

### 4.4 `src/demanda.py`

`normalizar_demanda(df)`: calcula demanda en unidades y la política de redondeo por categoría. Agrega `Demanda_Unidades_Oficial`, `Cajas_Completas`, `Unidades_Fraccionarias`, `Politica_Redondeo`, `Unidades_Exceso_Redondeo`.

### 4.5 `src/reconciliacion_geometrica.py`

Responsabilidad: decidir `Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo` por SKU reconciliando Maestro (`Cajas por cama`, capacidad declarada) contra UMA (dimensiones medidas). Ver `DOCUMENTACION_LOGICA.md` sección 5.

- `capacidad_orientacion_unica(...)`: grilla uniforme simple, una orientación.
- `capacidad_xy_max(largo, ancho)` / `capacidad_xy_max_con_sobresaliente(largo, ancho)`: mejor capacidad entre grillas uniformes, patrones mixtos por cortes rectos recursivos y molinete/pinwheel (`src.solver_cajas.max_cajas`) — `lru_cache`.
- `mejor_orientacion_3d(...)`: evalúa hasta 3 caras como huella (parada + 2 acostadas si la categoría lo permite).
- `inferir_footprint_desde_cajas_cama(...)`: busca un footprint que reproduzca exacto un `Cajas por cama` declarado — ningún SKU del dataset real llega a necesitarla hoy.
- `reconciliar_sku(row)` / `reconciliar(df)`: punto de entrada, una vez por SKU. Devuelve `(df con columnas nuevas, df de auditoría)`.

### 4.6 `src/derivados.py`

`calcular_peso_caja(peso_bruto_por_unidad, unidades_por_caja)`: función compartida con `validacion.py` para que ambos calculen el mismo `Peso_Caja`. Respeta `config.PESO_UMA_ES_POR_UNIDAD` (hoy `False`).

`calcular_derivados(df)`: agrega `Peso_Caja`, `Cajas_Teoricas_Redondeadas`, `Cajas_Extra_Redondeo`, **`Cajas_Cama_Efectivo`** (Maestro reconciliado si es válido, si no cae a la capacidad geométrica efectiva — es el número que hoy usa `packing_bloques.py` como objetivo de cada cama, sección 4.9), `Nivel_Categoria`, `Es_Categoria_Remate`.

### 4.7 `src/torres.py`

`TorreCandidate` (frozen): combinación (SKU, orientación) posible, sin posición ni cantidad decidida. `generar_torres_candidatas(df_cd, altura_max_producto, permitir_rotacion_xy=True)`: una candidata por SKU y orientación XY válida — `max_cajas_verticales = floor(altura_max_producto / alto_caja)` es el techo físico. `crear_torre(candidata, x, y, cantidad, z=0.0)`: instancia una `Torre` concreta. `dividir_torre(torre, cantidad_primera)`: parte una torre en dos preservando demanda total. `torre_a_dict`: serialización plana para debug.

### 4.8 `src/packing_columnar.py` — mecanismo de colocación 3D (MaxRects)

Provee el motor geométrico de bajo nivel que usa `packing_bloques.py` — no arma pallets de punta a punta por sí solo en el pipeline actual, pero toda la colocación real pasa por acá, **sin haber sido modificado** por el rediseño de camas (sección 9): lo único que cambió es cómo lo llama `packing_bloques.py` (con un cuboide libre inicial de profundidad limitada a una cama, en vez de al pallet completo).

- `_CuboidLibre(x, y, z, w, h, d)`: un cuboide de espacio libre dentro del pallet.
- `_actualizar_libres_maxrects(...)`: después de colocar una caja, parte cada cuboide libre solapado en hasta 5 franjas maximales (4 en XY + 1 hacia arriba en Z) y poda los que quedan contenidos en otro.
- `_PalletEnConstruccion`: envuelve un `PalletV5` con su lista de cuboides libres. `mejor_ajuste(candidata, cantidad, permitir_parcial)`: Best-Volume-Fit. `colocar(...)` materializa la torre y actualiza libres/altura/peso/ocupación.
- `_area_union_xy(torres)`: huella realmente ocupada en XY (sweep por coordenadas comprimidas).
- `_reconstruir_en_construccion(pallet)`: recalcula los cuboides libres de un pallet ya armado a partir de sus torres.
- `_altura_presupuesto()`: techo de altura de producto disponible (`ALTURA_MAX_OBSERVADA - ALTURA_PALLET_VACIO`) — usado por `packing_bloques.armar_pallets_bloques` como presupuesto total del pallet (la suma de las profundidades de las camas que se van abriendo).
- `armar_pallets_columnar(...)`: función de armado genérico de un CD completo con soporte para `orden_skus`/`concentrar_sku` — **no es la que llama el pipeline actual**, se mantiene porque expone las piezas (`_CuboidLibre`, `_altura_presupuesto`, `_PalletEnConstruccion`) que `packing_bloques.py` importa y reutiliza.

### 4.9 `src/packing_bloques.py` — armado por camas (el core actual)

Ver `DOCUMENTACION_LOGICA.md` sección 9 para la regla de negocio completa. Reescrito de punta a punta en el commit `d7051a9` — ya no tiene fase de "dedicar pallets completos" ni de "bloques enteros" de la versión anterior; el concepto que reemplazó a ambos es la **cama**.

- `TOLERANCIA_HUECO_CAMA_CM = 8.0`: cuánta diferencia de altura se tolera entre el SKU ancla de una cama y otro SKU que se le agrega — heredada de la calibración V4 contra `Cubicaje18.07.2026.xlsx`.
- `_mejor_ajuste_para_sku(pc, candidatas, cantidad, permitir_parcial)`: prueba todas las orientaciones de un SKU contra un pallet en construcción, se queda con la de menos sobra.
- `_mejor_orientacion_grilla(candidatas)`: fija UNA sola orientación por cama (base ESTRICTA 120×100 — el sobresaliente por cama dominada se probó y se descartó, ver `DOCUMENTACION_LOGICA.md` 10.3), calculando la grilla columnas×filas de mayor capacidad directo, sin mezclar orientaciones caja a caja.
- `_armar_cama(pallet, z, altura_cama, pendientes, por_sku, capacidad_cama_por_sku, ancla_sku)`: arma UNA cama a la altura `z`, con un `_CuboidLibre` inicial cuya profundidad es exactamente `altura_cama` — así ninguna torre puede crecer más alto que esa cama. Coloca el ancla hasta `min(pendiente, Cajas_Cama_Efectivo)`, y después rellena con otros SKUs pendientes cuya altura esté dentro de `TOLERANCIA_HUECO_CAMA_CM` de `altura_cama`, **en ambas direcciones** (chequeo simétrico — ver el bug documentado en `DOCUMENTACION_LOGICA.md` 10.2). Devuelve si logró colocar algo.
- `armar_pallets_bloques(df_cd, cd, contador=None)`: punto de entrada. Mientras haya demanda pendiente: abre un pallet nuevo, y dentro de él sube de cama en cama (`z` acumulado) mientras quede presupuesto de altura y algún SKU pendiente quepa — en cada cama, el ancla es el SKU de mayor demanda pendiente entre los que entran en la altura restante del pallet. Si el ancla elegido no logra colocar ni una caja, se marca `sin_colocar` y se descarta (evita loops infinitos); si ningún SKU avanza en todo un pallet nuevo, se corta el loop general (misma protección).

`df_cd` debe traer demanda pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría efectiva reconciliada (`Largo/Ancho/Alto_Efectivo`) y, si está disponible, `Cajas_Cama_Efectivo` — sin esa columna, una cama no tiene más tope que la huella/orientación elegida (`tests/test_packing_bloques.py::test_sin_cajas_cama_efectivo_igual_arma_algo`).

### 4.10 `src/layout_solver.py` — disponible, no cableado

Se había borrado en la limpieza de la sección 9 (`DOCUMENTACION_LOGICA.md`) pensando que estaba huérfano; se recuperó en el rediseño de camas porque es la pieza correcta para "dado un objetivo de cajas, dar posiciones reales" (a diferencia de `solver_cajas.py`, que solo devuelve un conteo). `resolver_layout_rectangulos(pallet_largo, pallet_ancho, caja_largo, caja_ancho, cantidad_objetivo=None, permitir_rotacion_xy=True, con_pinwheel=True) -> LayoutResult`: máximo de cajas idénticas con placements reales, probando grilla uniforme, guillotina recursiva (patrones mixtos) y pinwheel/five-block — se auto-valida (sin solapes, sin desborde) y degrada a grilla uniforme si algo no cierra.

**No se llama desde ningún punto del pipeline actual** (confirmado por grep — solo lo importa su propio test). El armado por filas simple (`_mejor_orientacion_grilla` + MaxRects de una sola profundidad, sección 4.9) ya resuelve el caso principal sin necesitarlo. Queda disponible para si en algún dataset real el armado fila por fila no alcanza a cumplir `Cajas_Cama_Efectivo` — ahí es donde entraría como intento adicional antes de aceptar el faltante (todavía no se vio ese caso en los datasets probados).

### 4.11 `src/bat.py`

Ver `DOCUMENTACION_LOGICA.md` sección 8. `separar_bat(df)`: separa demanda BAT usando `Categoria_Normalizada`. `consolidar_bat_por_cd(df_bat)`: arma `CajaBAT` de tamaño fijo por CD usando demanda real en unidades. `construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)`: una fila de pseudo-demanda por CD (SKU `__BAT__`). `renombrar_pallets_bat_puros(pallets_cd, cd)`: renombra a `PV5-BAT-{cd}-NNN` cualquier pallet cuyas torres sean todas BAT. `asignar_cajas_bat_a_torres(pallets_cd, cajas_bat)`: mapea las torres BAT colocadas de vuelta a objetos `CajaBAT` concretos.

### 4.12 `src/soporte.py` — no-op en el pipeline actual

`clasificar_soporte_pallet(pallet)`: hace `if not pallet.camas: return` — como todo `Pallet` que produce el pipeline actual llega con `camas=[]` (el modelo columnar/por-camas no genera la dataclass `Cama` legada), **esta función es un no-op para el 100% de los pallets reales hoy**. Candidata a retiro en una limpieza futura.

### 4.13 `src/estabilidad.py`

Ver `DOCUMENTACION_LOGICA.md` sección 11. `calcular_estabilidad(pallet: PalletV5) -> EstabilidadPallet`: centro de masa XY y su desviación, peso por cuadrante, torres esbeltas, fracción de peso superior. Puramente informativo, nunca bloquea.

### 4.14 `src/validacion_peso.py`

`validar_pesos(pallets, info_sku)`: recalcula `peso_estimado`, marca `⚠ PESO NO VALIDABLE`/`⚠ ALERTA DE PESO`. Nunca bloquea ni modifica el armado.

### 4.15 `src/validacion_v5.py` — auditoría geométrica dura

Ver `DOCUMENTACION_LOGICA.md` sección 12. `validar_pallet_v5(pallet)`: overflow contra la base extendida (125×105 — el tope permitido, aunque el armado actual siempre use la base estricta), overlap 3D entre cualquier par de torres, altura sobre `ALTURA_TOPE_DURO`. `validar_geometria_v5(pallets)`: agrega violaciones de una lista completa.

### 4.16 `src/benchmark.py`

Ver `DOCUMENTACION_LOGICA.md` secciones 2 y 12. `BenchmarkResultado`, `calcular_kpis(pallets, ...)` (recibe la lista COMPLETA, sin filtrar), `comparar_contra_real(resultado)`, `GateV5Resultado` / `evaluar_gate_v5(...)` (4 criterios obligatorios), `benchmark_df(resultados)`.

Nota: `auditar_pallet(pallet)` todavía lee `pallet.camas` (modelo legado) — con `camas` siempre vacío hoy, sus campos quedan vacíos/en 0. No se usa en el flujo del pipeline.

### 4.17 `src/exportar.py`

`construir_plan_picking_df(pallets, info_sku)`, `construir_resumen_cd_df(pallets)`, `construir_torres_df(pallets_v5)`, `construir_pallets_3d_data_df(pallets_v5)`, `construir_estabilidad_df(pallets_v5)`, `exportar_workbook(resultado, ruta_o_buffer=None)`.

Nota: `Altura_Pre_BAT_cm`/`Delta_Target_198_3` en `construir_plan_picking_df` nunca se pueblan en el pipeline actual — quedan siempre vacíos en el Excel exportado.

### 4.18 `src/solver_cajas.py`

Solver de cubicaje 2D puro (solo conteo, sin posiciones — para eso está `layout_solver.py`, sección 4.10). `max_cajas(W, H, largo, ancho, con_pinwheel=True) -> (n, metodo)`. Usado por `reconciliacion_geometrica.capacidad_xy_max`.

### 4.19 `src/template.py` / `app.py` / `visualizacion.py`

`template.py`: genera la plantilla Excel de ejemplo descargable. `app.py`: interfaz Streamlit — carga de archivos, métricas resumen, tabs (Plan de Picking / Log de Validación / Resumen por CD / Inspector de Pallets), descarga del Excel final. El "Inspector de Pallets" usa `resultado.pallets_v5` para mostrar la vista 3D real por torre (`visualizacion.dibujar_pallet_v5_3d`) — el `else` que cae a la vista 2D por cama legada es código muerto en la práctica.

## 5. Estructuras de datos — resumen de contratos

| Objeto | Quién lo produce | Quién lo consume |
|---|---|---|
| `GeometriaSKU` | `reconciliacion_geometrica.reconciliar_sku` | `reconciliacion_geometrica.reconciliar` |
| `TorreCandidate` | `torres.generar_torres_candidatas` | `packing_columnar`/`packing_bloques` |
| `Torre` / `PlacementCaja` | `torres.crear_torre` (vía `_PalletEnConstruccion.colocar`) | `estabilidad`, `exportar`, `visualizacion` |
| `PalletV5` | `packing_bloques.armar_pallets_bloques` (una cama = torres que comparten `z`) | `bat.*`, `estabilidad.calcular_estabilidad`, `_palletv5_a_pallet`, `exportar.*`, `app.py` |
| `Pallet` / `PalletLinea` (modelo legado, `camas=[]`) | `pipeline_sku_bloque._palletv5_a_pallet` | `soporte` (no-op), `validacion_peso`, `benchmark.calcular_kpis`, `exportar` |
| `CajaBAT` | `bat.consolidar_bat_por_cd` | `bat.asignar_cajas_bat_a_torres`, `pallet.cajas_bat` |
| `EstabilidadPallet` | `estabilidad.calcular_estabilidad` | `pallet.metadata["estabilidad"]`, `exportar.construir_estabilidad_df` |
| `BenchmarkResultado` / `GateV5Resultado` | `benchmark.calcular_kpis` / `evaluar_gate_v5` | `benchmark.benchmark_df`, inspección manual |
| `LayoutResult` | `layout_solver.resolver_layout_rectangulos` | Nadie hoy — módulo disponible, no cableado (sección 4.10) |

## 6. Notas de implementación

- **Peso de caja, fuente única**: `derivados.calcular_peso_caja` es la única fórmula, compartida entre `validacion.py` y `derivados.py`.
- **Determinismo**: sin aleatoriedad en ningún punto del pipeline actual — mismo input siempre produce el mismo Excel byte a byte.
- **`Cajas_Extra_Consolidacion` siempre 0**: cada línea despacha exactamente su demanda oficial (o queda en `sin_colocar`).
- **Nunca se descarta demanda en silencio**: `packing_bloques.armar_pallets_bloques` registra cualquier resto sin colocar en `metadata["sin_colocar"]`.
- **Sobresaliente sin usar en packing real**: `PALLET_LARGO_EFECTIVO`/`ANCHO_EFECTIVO` (125×105) solo se usan hoy en `reconciliacion_geometrica.py` (validar datos del Maestro) y como tope permitido en `validacion_v5.py` — el armado real (`packing_bloques.py`) siempre usa la base estricta 120×100 desde el rediseño de camas. No es un bug: se probó extenderla para camas dominadas por un solo SKU y se descartó por fragilidad de la heurística (`DOCUMENTACION_LOGICA.md` 10.3).
- **`soporte.py` es no-op hoy**: documentado como tal, no asumir que es un bug si no se ve ningún efecto.
- **Una "cama" no es una clase**: es un patrón emergente — todas las `Torre` de un `PalletV5` con el mismo `z` fueron colocadas por la misma llamada a `_armar_cama`. Para inspeccionar camas desde fuera de `packing_bloques.py`, agrupar `pallet.torres` por `round(t.z, 3)` (mismo patrón que usan los tests, ver sección 7).

## 7. Tests

112 tests en 18 archivos (`tests/`):

| Archivo | Qué cubre |
|---|---|
| `conftest.py` | Fixture `dataset_factory` |
| `test_validacion.py` (10) | Reglas V1-V9 del Paso 0 |
| `test_derivados.py` (4) | `Peso_Caja`, `Nivel_Categoria`, `Cajas_Cama_Efectivo` |
| `test_reconciliacion_v5_p2.py` (4) | Estados de `Fuente_Geometria`, sobresaliente en reconciliación |
| `test_torres.py` (10) | `TorreCandidate`, `crear_torre`, `dividir_torre`, límites |
| `test_packing_columnar.py` (7) | Mecanismo MaxRects 2D genérico |
| `test_packing_3d.py` (8) | Apilado real en Z, `_area_union_xy`, conservación de demanda |
| `test_packing_bloques.py` (9) | El armado por camas — SKU ancla no repartido en columnas, hueco simétrico, tolerancia respetada, ejemplo textual del usuario |
| `test_layout_solver.py` (6, nuevo) | `resolver_layout_rectangulos` — capacidad==len(placements), sin solapes/desborde, degradación a grilla |
| `test_bat_v5.py` (9) | Consolidación BAT integrada |
| `test_estabilidad.py` (7) | Centro de masa, torres esbeltas, peso superior |
| `test_validacion_v5.py` (9) | Overlap 3D, overflow, altura |
| `test_gate_v5.py` (6) | Los 4 criterios del gate |
| `test_benchmark.py` (4) | KPIs, conteo de BAT dedicados |
| `test_exportar_v5.py` (4) | Conteo exacto de filas por hoja |
| `test_visualizacion_v5.py` (3) | Vista 3D no revienta |
| `test_invariantes.py` (6) | Propiedades que deben cumplirse SIEMPRE |
| `test_pipeline_real_data.py` (5) | Corrida completa contra `Cubicaje18.07.2026.xlsx` |

Correr todo: `pytest -q` desde la raíz (requiere el venv de `env/`, Python 3.11).

## 8. Cómo correr una demanda real sin la UI

```python
import pandas as pd
from src.pipeline import ejecutar_pipeline

envios = pd.read_excel("Cubicaje18.07.2026.xlsx", sheet_name="Envios_Julio")
maestro = pd.read_excel("Cubicaje18.07.2026.xlsx", sheet_name="Maestro_SKUs")
uma = pd.read_excel("Cubicaje18.07.2026.xlsx", sheet_name="UMA")

resultado = ejecutar_pipeline(envios, maestro, uma)
print(len(resultado.pallets), "pallets")
```

O `src.pipeline.ejecutar_desde_archivo(ruta_o_buffer)`. `src.exportar.exportar_workbook(resultado)` arma el `.xlsx` final.

## 9. Historial de arquitectura (resumen)

Detalle completo en `Parches/v5/PATCH_LOG.md`. El repo pasó por: motor V4 por camas de categoría → motor V5 columnar (torres) con multi-start/residual-search/packing 3D → AUTO (V4+V5, mejor por CD) → SKU_CONSOLIDADO/SKU_BLOQUE por torres (dedicar + bloques enteros) → limpieza (`1c5f68e`, retira todo motor salvo SKU_BLOQUE) → fix de orientación + sobresaliente en dedicados (`506285c`) → **rediseño por camas** (`d7051a9`, commit actual): reemplaza el modelo de torres por armado cama-por-cama tras detectar con capturas reales del Inspector de Pallets que las torres dejaban huecos de aire grandes entre SKUs de altura muy distinta compartiendo huella. Recuperó `layout_solver.py`. Bajó el dataset grande de 53 a 47 pallets.

## 10. Dónde tocar para...

| Quiero cambiar... | Tocar |
|---|---|
| La ventana de altura permitida | `config.py` (`ALTURA_*`) |
| El umbral de peso de alerta | `config.py` (`PESO_ALERTA_KG`/`PESO_HARD_KG`) — sigue sin bloquear el armado |
| Qué tan parecidos tienen que ser dos SKUs para compartir cama | `packing_bloques.TOLERANCIA_HUECO_CAMA_CM` |
| Cómo se elige el SKU ancla de cada cama | `packing_bloques.armar_pallets_bloques` (hoy: mayor demanda pendiente entre los que quepan) |
| El objetivo de cajas por cama | No tocar `packing_bloques.py` — viene de `derivados.calcular_derivados` (`Cajas_Cama_Efectivo`) |
| El tamaño/capacidad de la caja BAT | `config.py` (`CAJA_BAT_*`) |
| Cómo se integra BAT al armado | `src/bat.py` (sección "BAT integrado") + `pipeline_sku_bloque.py` |
| Activar el sobresaliente en packing real | `packing_bloques._mejor_orientacion_grilla`/`_armar_cama` (hoy fijo en base estricta — ver `DOCUMENTACION_LOGICA.md` 10.3 antes de reintentarlo) |
| Los criterios del gate de benchmark | `benchmark.py` (`GATE_V5_PALLETS_MIN/MAX`, `evaluar_gate_v5`) |
| Qué cuenta como violación geométrica | `src/validacion_v5.py` |
| Cablear `layout_solver.py` para casos donde el armado fila-por-fila no alcanza | `packing_bloques._armar_cama` (llamar `layout_solver.resolver_layout_rectangulos` como intento adicional antes de aceptar el faltante) |
| Las columnas del Excel de salida | `src/exportar.py` |
