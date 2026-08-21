# Documentación técnica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `506285c` (2026-08-21) — único motor activo: **SKU_BLOQUE**. `src/` ~2.775 líneas, 19 módulos (bajó de ~5.030 líneas / 30 módulos tras la limpieza que retiró V4/V5-multistart/AUTO, ver sección 9).
**Alcance:** arquitectura de código, contratos entre módulos, estructuras de datos y cómo operar el proyecto.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_TECNICA*.md`. La lógica de negocio (invariantes, prioridades, benchmark) está en `DOCUMENTACION_LOGICA.md`. El historial completo de cómo se llegó a este estado vive en `Parches/v5/PATCH_LOG.md`.

---

## 1. Qué hace el sistema

A partir de tres hojas de un Excel (`Envios_Julio`, `Maestro_SKUs`, `UMA`), calcula cómo armar pallets físicos (base 120×100cm) por centro de distribución (CD): qué SKUs van en cada pallet, en qué cantidad y posición, y con qué altura/peso resultante — priorizando que cada SKU quede en el menor número de pallets posible (idealmente uno) antes que minimizar el conteo total de pallets a cualquier costo (ver `DOCUMENTACION_LOGICA.md` sección 9).

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

Un solo camino desde la limpieza de sección 9 — `pipeline.ejecutar_pipeline` ya no despacha por flag, llama directo a `pipeline_sku_bloque.ejecutar_core_sku_bloque`:

```
VAL     validacion.validar_y_limpiar(envios, maestro, uma)         -> df_validado, log_df
DEM     demanda.normalizar_demanda(df_validado)                     -> df_demanda
GEO     reconciliacion_geometrica.reconciliar(df_demanda)           -> df_geo, auditoria_geometrica_df
DER     derivados.calcular_derivados(df_geo)                        -> df_derivado
        _construir_info_sku(df_derivado)                            -> info_sku (dict por SKU)
SPLIT   bat.separar_bat(df_derivado)                                -> df_no_bat, df_bat
        clasificación: df_clasificado / df_no_clasificado / df_geometria_insuficiente
BATPOOL bat.consolidar_bat_por_cd(df_bat)                           -> cajas_bat_por_cd
        bat.construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku) -> df_bat_pseudo
        df_armado = concat(df_clasificado, df_bat_pseudo)
BLOQUE  por cada CD: packing_bloques.armar_pallets_bloques(grupo, cd, contador) -> list[PalletV5]
        bat.renombrar_pallets_bat_puros / bat.asignar_cajas_bat_a_torres        (in-place)
        estabilidad.calcular_estabilidad(p)  guardado en p.metadata["estabilidad"]
ADAPT   _palletv5_a_pallet(pv5, info_sku)  por cada PalletV5          -> Pallet (modelo legado, para reusar soporte/export/benchmark)
SOP     soporte.clasificar_soporte_pallet(pallet)  por cada pallet    (no-op actual, ver sección 8)
PESO    validacion_peso.validar_pesos(todos_pallets, info_sku)       (in-place, solo reporte)
BENCH   benchmark.calcular_kpis(...) / benchmark_df(...)
EXP     exportar.construir_plan_picking_df / construir_resumen_cd_df
```

`GEO` corre sobre **toda** la demanda (BAT incluido) antes del `SPLIT`: no porque BAT necesite geometría (usa una caja fija), sino para que `info_sku` (peso, categoría, nivel) quede completo para todos los SKUs — si se reconciliara después del split, la asignación de BAT fallaría buscando metadata de Cigarros que nunca se calculó.

`BLOQUE` corre por CD; además de los CDs con demanda clasificada normal, hay un segundo loop que cubre CDs que solo tienen demanda BAT (sin ningún otro SKU clasificado) para no perder esa demanda en silencio.

## 4. Módulos

### 4.1 `config.py`

Todas las constantes del sistema, sin lógica de negocio compleja. Grupos:

| Grupo | Constantes clave |
|---|---|
| Pallet | `PALLET_LARGO=120`, `PALLET_ANCHO=100`, `ALTURA_PALLET_VACIO=14.92` |
| Sobresaliente | `SOBRESALIENTE_MAX_CM=2.5`, `PALLET_LARGO_EFECTIVO=125`, `PALLET_ANCHO_EFECTIVO=105` |
| Rotación acostada | `CATEGORIAS_ROTACION_LIBRE=["Comestibles","Cigarros"]` |
| Altura | `ALTURA_TARGET=198.3`, `ALTURA_NOMINAL_MIN=190.0`, `ALTURA_MAX_OBSERVADA=215.0`, `ALTURA_HARD_VALIDADA=None` |
| Peso | `PESO_ALERTA_KG=1400`, `PESO_HARD_KG=1430`, `PESO_PARAMETROS_VALIDADOS=False` |
| BAT | `CATEGORIAS_BAT=["Cigarros"]`, `CAJA_BAT_LARGO=52.5`, `CAJA_BAT_ANCHO=34.0`, `CAJA_BAT_ALTO=49.0`, `CAJA_BAT_CAPACIDAD_UNIDADES=1000` |
| Categorías | `ORDEN_CATEGORIAS`, `CATEGORIAS_REMATE`, `nivel_de_categoria()`, `normalizar_categoria()` — metadata de reporte, ya no gatean el armado |

Funciones: `estado_altura(altura)` (zona de reporte), `estado_pallet_por_altura(altura)` (traduce zona → `ESTADO_*`), `normalizar_categoria(valor)`, `nivel_de_categoria(categoria)`.

Aliases retrocompatibles todavía referenciados por código/tests: `ALTURA_TOTAL_MIN`, `ALTURA_TOTAL_MIN_TOLERADO`, `ALTURA_TOTAL_MAX`, `ALTURA_TOPE_DURO` (los cuatro apuntan a `ALTURA_NOMINAL_MIN`/`ALTURA_TOLERADO_MIN`/`ALTURA_MAX_OBSERVADA`×2), `PESO_TOPE_ELASTICO_KG` (= `PESO_HARD_KG`).

**Retirado en la limpieza de sección 9** (sin ninguna referencia viva confirmada por grep): `PACKER_VERSION`, `MULTISTART_SEEDS/MAX`, `PH_PREBUILD`, `PURE_FIRST`, `SOBRESALIENTE_PLANIFICACION`, `TOLERANCIA_ALTURA_PORTANTE/TERMINAL/MEZCLA`, `FILL_RATIO_MIN_SOPORTE`, `RESERVA_ALTURA_REMATE`, `ESTRATEGIA_CAMAS`, `CATEGORIAS_SIN_NADA_ENCIMA`, `MAX_SEPARACION_NIVELES`.

### 4.2 `models.py`

Dos generaciones de dataclasses conviven en el archivo — la segunda es la que de verdad produce el armado hoy:

**Modelo legado (`Cama`/`Pallet`)** — sigue existiendo porque `soporte.py`, `exportar.construir_plan_picking_df`, `benchmark.py` y la vista 2D de `app.py`/`visualizacion.py` están escritos contra él. `_palletv5_a_pallet` (en `pipeline_sku_bloque.py`) adapta cada `PalletV5` a un `Pallet` con `camas=[]` siempre — ver sección 8 para qué implica eso.

- `GeometriaSKU`: resultado de reconciliar un SKU (`fuente_geometria`, `acostada`, etc.)
- `CajaBAT`: caja física fija de consolidación de Cigarros
- `Placement` / `Cama`: modelo por capas horizontales — `Cama` conserva properties (`nivel_efectivo`, `categoria_remate`, `es_flexible`, `fill_ratio`) que ya no se ejercitan en el pipeline actual (nunca se crea una `Cama` con contenido real)
- `PalletLinea` / `Pallet`: unidad de salida del plan de picking — `camas` queda vacío, `lineas` sí se llena (viene de las torres del `PalletV5` adaptado)

**Modelo columnar (`Torre`/`PalletV5`)** — el que arma `packing_bloques.py` de verdad:

- `OrientacionCaja` (frozen): una orientación válida de una caja.
- `PlacementCaja`: una caja física concreta (x, y, z, orientación) dentro de una torre.
- `Torre`: cajas del mismo SKU apiladas verticalmente en una posición XY fija. `altura` (`cantidad × alto_caja`) y `area_base` son properties derivadas, nunca campos que se puedan desincronizar. `z` es la base del segmento dentro de la pila de producto (0 = piso del pallet) — permite que una torre empiece donde termina otra en el mismo (x,y), habilitando apilado real tipo Tetris/Lego en vez de una sola torre de piso a techo por posición XY.
- `PalletV5`: `torres`, `cajas_bat`, `altura_final`, `peso_estimado`, `ocupacion_xy`, `volumen_utilizado`, `estado`, `metadata` (dict libre — ahí vive `estabilidad`, `sin_colocar`, `es_host_bat`).
- `ResultadoPipeline`: además de los campos del modelo legado, trae `pallets_v5: list[PalletV5]` — la fuente de verdad para inspección/export detallado (Torres, Pallets_3D_Data, Estabilidad).

### 4.3 `src/validacion.py` — Paso 0

`cargar_hojas(ruta_o_buffer)` lee las 3 hojas del Excel. `validar_y_limpiar(envios, maestro, uma)` aplica las reglas V1-V9 (normalización de SKU, duplicados CD+SKU sumados, exclusión de Cajas Teóricas ≤0, SKU sin Maestro/UMA excluido, "Cajas por PH"/"Camas por PH" fuera de rango marcados no-confiables, "Cajas por cama" nulo/0 marcado para fallback geométrico, dimensión imposible para el pallet excluida, alto de caja sobre el máximo excluido, peso fuera de rango sano marcado `Peso_No_Validable`, categoría no reconocida excluida del apilado automático) y devuelve `(df, log_df)` con cada exclusión trazada.

### 4.4 `src/demanda.py`

`normalizar_demanda(df)`: calcula demanda en unidades y la política de redondeo por categoría (ver `DOCUMENTACION_LOGICA.md` sección 7). Agrega `Demanda_Unidades_Oficial`, `Cajas_Completas`, `Unidades_Fraccionarias`, `Politica_Redondeo`, `Unidades_Exceso_Redondeo`.

### 4.5 `src/reconciliacion_geometrica.py`

Responsabilidad: decidir `Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo` por SKU reconciliando Maestro (`Cajas por cama`, capacidad declarada) contra UMA (dimensiones medidas). Ver `DOCUMENTACION_LOGICA.md` sección 5 para la tabla de estados.

- `capacidad_orientacion_unica(pallet_largo, pallet_ancho, caja_largo, caja_ancho)`: grilla uniforme simple, una orientación.
- `capacidad_xy_max(largo, ancho)` / `capacidad_xy_max_con_sobresaliente(largo, ancho)`: mejor capacidad entre grillas uniformes, patrones mixtos por cortes rectos recursivos y molinete/pinwheel (`src.solver_cajas.max_cajas`) — `lru_cache` porque el solver mixto tarda ~70ms por dimensión y se llama por fila de demanda, no por SKU único.
- `mejor_orientacion_3d(largo, ancho, alto, permitir_acostada, cajas_objetivo, con_sobresaliente)`: evalúa hasta 3 caras como huella (parada + 2 acostadas si la categoría lo permite) y elige según si hay un techo del Maestro que cumplir.
- `inferir_footprint_desde_cajas_cama(...)`: busca un footprint que reproduzca exacto un `Cajas por cama` declarado — solo se usaría si ni la geometría medida ni el sobresaliente alcanzan a explicar al Maestro; ningún SKU del dataset real llega a ese punto actualmente (ver `DOCUMENTACION_LOGICA.md` 5.1).
- `reconciliar_sku(row)` / `reconciliar(df)`: punto de entrada, una vez por SKU (no por fila CD+SKU). Devuelve `(df con columnas nuevas, df de auditoría)`.

### 4.6 `src/derivados.py`

`calcular_peso_caja(peso_bruto_por_unidad, unidades_por_caja)`: función compartida con `validacion.py` para que ambos calculen el mismo `Peso_Caja` (evita que diverjan en silencio). Respeta `config.PESO_UMA_ES_POR_UNIDAD` (hoy `False` — la columna "Peso bruto por unidad" de UMA es, en la práctica, el peso de la CAJA, no de la unidad suelta).

`calcular_derivados(df)`: agrega `Peso_Caja`, `Cajas_Teoricas_Redondeadas`, `Cajas_Extra_Redondeo`, `Cajas_Cama_Efectivo` (Maestro reconciliado si es válido, si no cae a la capacidad geométrica efectiva), `Nivel_Categoria`, `Es_Categoria_Remate`. Asume que `df` ya pasó por `reconciliacion_geometrica.reconciliar`.

### 4.7 `src/torres.py`

`TorreCandidate` (frozen): combinación (SKU, orientación) posible, sin posición ni cantidad decidida. `generar_torres_candidatas(df_cd, altura_max_producto, permitir_rotacion_xy=True)`: una candidata por SKU y orientación XY válida — `max_cajas_verticales = floor(altura_max_producto / alto_caja)` es solo el techo físico, el packer decide cuánto usar de verdad. `crear_torre(candidata, x, y, cantidad, z=0.0)`: instancia una `Torre` concreta. `dividir_torre(torre, cantidad_primera)`: parte una torre en dos preservando demanda total (usado por la fase de "partir un bloque como último recurso"). `torre_a_dict`: serialización plana para debug.

### 4.8 `src/packing_columnar.py` — mecanismo de colocación 3D (MaxRects)

Provee el motor geométrico de bajo nivel que usa `packing_bloques.py` — no arma pallets de punta a punta por sí solo en el pipeline actual (esa responsabilidad es de `packing_bloques.armar_pallets_bloques`), pero toda la colocación real pasa por acá.

- `_CuboidLibre(x, y, z, w, h, d)`: un cuboide de espacio libre dentro del pallet.
- `_actualizar_libres_maxrects(...)`: después de colocar una caja, parte cada cuboide libre solapado en hasta 5 franjas maximales (4 en XY + 1 hacia arriba en Z — nunca hacia abajo, porque siempre se coloca a ras del piso del cuboide elegido) y poda los que quedan contenidos en otro.
- `_PalletEnConstruccion`: envuelve un `PalletV5` con su lista de cuboides libres. `mejor_ajuste(candidata, cantidad, permitir_parcial)`: Best-Volume-Fit — busca el cuboide con menos volumen sobrante entre los que reciben al menos 1 caja; `permitir_parcial=True` (default) puede devolver menos cajas de las pedidas si el mejor cuboide no tiene profundidad Z completa (así otra SKU puede ocupar el resto de esa columna de aire); `permitir_parcial=False` (usado cuando hace falta todo-o-nada) ignora cualquier cuboide que no reciba la cantidad completa. `colocar(...)` materializa la torre y actualiza libres/altura/peso/ocupación.
- `_area_union_xy(torres)`: huella realmente ocupada en XY (sweep por coordenadas comprimidas) — evita contar el mismo piso más de una vez cuando varias torres comparten (x,y) apiladas a distinto Z.
- `_reconstruir_en_construccion(pallet)`: recalcula los cuboides libres de un pallet ya armado a partir de sus torres — usado por `packing_bloques.py` para poder seguir agregando bloques a un pallet ya existente (los pallets dedicados, por ejemplo, no reusan este camino porque siembran su propio `_CuboidLibre` inicial extendido).
- `armar_pallets_columnar(...)`: función de armado genérico de un CD completo (best-fit sobre todos los pallets activos, con soporte para `orden_skus` y `concentrar_sku`) — **no es la que llama el pipeline actual** (`packing_bloques.armar_pallets_bloques` no la invoca; construye sus propios `_PalletEnConstruccion` directamente). Se mantiene porque expone las piezas (`_CuboidLibre`, `_altura_presupuesto`, `_PalletEnConstruccion`) que `packing_bloques.py` importa y reutiliza.

### 4.9 `src/packing_bloques.py` — armado por bloques de SKU (el core actual)

Ver `DOCUMENTACION_LOGICA.md` sección 9 para la regla de negocio completa. Piezas:

- `_mejor_ajuste_para_sku(pc, candidatas, cantidad, permitir_parcial)`: prueba todas las orientaciones de un SKU contra un pallet en construcción, se queda con la de menos sobra.
- `_colocar_bloque_completo(pc, sku, cantidad, por_sku)`: coloca TODO `cantidad` en `pc`, en tantas torres como haga falta — atómico, con snapshot/rollback exacto de `torres`, `libres`, `altura_final`, `peso_estimado`, `ocupacion_xy`, `volumen_utilizado` si no logra completar el bloque.
- `_mejor_orientacion_grilla(candidatas)`: para un pallet 100% dedicado, calcula la grilla (columnas × filas × altura) de cada orientación sobre la base extendida y devuelve la de mayor capacidad — una sola orientación fija para todo el pallet (ver `DOCUMENTACION_LOGICA.md` 10.2 para el bug que motivó esto).
- `_altura_potencial(sku, cantidad, por_sku)`: proxy de ordenamiento — altura si el bloque se apilara en una sola columna, no necesita ser exacta, solo consistente.
- `_dedicar_por_sku(df_cd, cd, contador)`: fase 1 — extrae pallets 100% dedicados donde la demanda supera la capacidad de un pallet (`Cajas por PH`), usando `_mejor_orientacion_grilla` y sembrando el pallet con un `_CuboidLibre` extendido (125×105). Si un pallet dedicado no logra completar la capacidad declarada, el faltante se devuelve como parte del bloque restante del SKU (no se pierde). Devuelve `(dedicados, bloques_pendientes, por_sku)`.
- `armar_pallets_bloques(df_cd, cd, contador=None)`: punto de entrada. Fase 2 — mientras haya bloques pendientes: elige el más grande como ancla de un pallet nuevo, lo coloca entero, agrega otros bloques enteros de mayor a menor hasta que ninguno más quepa, y como último recurso parte uno solo para cerrar la altura. Si algún bloque termina sin poder colocarse en absoluto (no debería pasar — la geometría inviable ya la filtra `validacion.py` antes), queda registrado en `metadata["sin_colocar"]` del último pallet, nunca se descarta en silencio.

`df_cd` debe traer demanda pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría efectiva reconciliada (`Largo/Ancho/Alto_Efectivo`) y `Cajas por PH` — sin esta última columna, un SKU nunca se "dedica" de antemano y pasa entero como bloque único (ver `tests/test_packing_bloques.py::test_sin_cajas_por_ph_el_sku_es_un_bloque_unico`).

### 4.10 `src/bat.py`

Ver `DOCUMENTACION_LOGICA.md` sección 8. `separar_bat(df)`: separa demanda BAT usando `Categoria_Normalizada` (categoría logística explícita, `config.CATEGORIAS_BAT`). `consolidar_bat_por_cd(df_bat)`: arma `CajaBAT` de tamaño fijo por CD usando demanda real en unidades (no cajas redondeadas, que inflarían ~3.8x). `construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)`: una fila de pseudo-demanda por CD (SKU `__BAT__`) con las mismas columnas que espera `packing_bloques`/`generar_torres_candidatas`. `renombrar_pallets_bat_puros(pallets_cd, cd)`: renombra a `PV5-BAT-{cd}-NNN` cualquier pallet cuyas torres sean todas BAT. `asignar_cajas_bat_a_torres(pallets_cd, cajas_bat)`: mapea las torres BAT colocadas de vuelta a objetos `CajaBAT` concretos (fungibles, orden estable).

Nota histórica: el módulo tenía ~530 líneas con una sección V4 completa de selección de "host" dinámico post-armado (`asignar_hosts_bat`, `_buscar_host_natural/forzado`, `_liberar_host`, etc.) — se retiró entera en la limpieza de sección 9 porque el mecanismo "BAT integrado" (competir por espacio en el mismo armado, en vez de una pasada aparte) la volvió obsoleta y estrictamente mejor (`bat_dedicados` pasó de hasta 9 a 0 en el dataset real).

### 4.11 `src/soporte.py` — no-op en el pipeline actual

`support_ratio(...)` / `support_ratio_cama(...)`: calculan soporte geométrico real (intersección de área entre una caja y las que tiene debajo) a partir de `Placement`s de `Cama`. `clasificar_soporte_pallet(pallet)`: hace `if not pallet.camas: return` — como todo `Pallet` que produce el pipeline actual llega con `camas=[]` (el modelo columnar no genera `Cama`), **esta función es un no-op para el 100% de los pallets reales hoy**. Se mantuvo en la limpieza de sección 9 por bajo riesgo (no rompe nada), marcada como candidata a retiro en una limpieza futura junto con `Cama`/`PalletLinea.categoria_remate` y la vista 2D por cama de `visualizacion.py` (inalcanzable ahora que no hay pallets con camas reales).

### 4.12 `src/estabilidad.py`

Ver `DOCUMENTACION_LOGICA.md` sección 11. `calcular_estabilidad(pallet: PalletV5) -> EstabilidadPallet`: centro de masa XY y su desviación, peso por cuadrante, torres esbeltas, fracción de peso superior (centro de masa vertical, `t.z + t.altura/2` — no `t.altura/2`, para que dos torres del mismo peso/altura apiladas una sobre otra aporten distinto). Puramente informativo, nunca bloquea.

### 4.13 `src/validacion_peso.py`

`validar_pesos(pallets, info_sku)`: recalcula `peso_estimado` sumando `cajas_totales × peso_caja` por línea, marca `⚠ PESO NO VALIDABLE` si algún SKU tiene peso fuera de rango sano, y `⚠ ALERTA DE PESO` si el total supera `PESO_ALERTA_KG` — nunca bloquea ni modifica el armado.

### 4.14 `src/validacion_v5.py` — auditoría geométrica dura

Ver `DOCUMENTACION_LOGICA.md` sección 12. `_se_superponen(a, b)`: AABB overlap en 3D (X, Y, Z) — tocarse en un borde (mismo `x+largo == x` del otro, o mismo `z+altura == z` del otro) no cuenta como violación. `validar_pallet_v5(pallet)`: overflow contra la base extendida (125×105 — el tope real desde que los pallets dedicados usan sobresaliente), overlap entre cualquier par de torres, altura sobre `ALTURA_TOPE_DURO`. `validar_geometria_v5(pallets)`: agrega violaciones de una lista completa, orden estable.

### 4.15 `src/benchmark.py`

Ver `DOCUMENTACION_LOGICA.md` secciones 2 y 12. `BenchmarkResultado` (dataclass): pallets, alturas, parciales, `pallets_bajo_190/170`, `bat_dedicados` (cuenta prefijo `PV5-BAT-`), `pallets_por_cd`. `calcular_kpis(pallets, ...)`: recibe la lista COMPLETA de pallets armados, sin filtrar nada — un pallet BAT dedicado cuenta como pallet físico igual que cualquier otro. `comparar_contra_real(resultado)`: delta contra `PALLETS_REALES=42`/`ALTURA_MEDIA_REAL=198.3`. `GateV5Resultado` / `evaluar_gate_v5(resultado, violaciones_geometria)`: los 4 criterios obligatorios del gate (rango `[42,45]`, demanda exacta, altura máxima ≤215, cero violaciones geométricas) — acumula TODAS las razones de rechazo en una corrida, no se detiene en la primera. `benchmark_df(resultados)`: hoja de salida real-vs-modelo.

Nota: `auditar_pallet(pallet)` todavía lee `pallet.camas`/`pallet.support_ratio_min` (modelo legado) — con `camas` siempre vacío hoy, los campos `n_camas`/`categorias`/`geometria_inferida_en_alguna_cama` de esa función quedan vacíos/en 0 para cualquier pallet real. No se usa en el flujo del pipeline (`ejecutar_core_sku_bloque` no la llama), solo queda disponible para inspección manual.

### 4.16 `src/exportar.py`

`construir_plan_picking_df(pallets, info_sku)`: una fila por (pallet, SKU) — la hoja principal del Excel de salida. `construir_resumen_cd_df(pallets)`: agregados por CD. `construir_torres_df(pallets_v5)` / `construir_pallets_3d_data_df(pallets_v5)` / `construir_estabilidad_df(pallets_v5)`: detalle por torre, por caja física (x,y,z reales — respaldo tabular exacto de la vista 3D) y por pallet respectivamente. `exportar_workbook(resultado, ruta_o_buffer=None)`: arma el Excel completo — las hojas `Torres`/`Pallets_3D_Data`/`Estabilidad_V5` solo se agregan si `resultado.pallets_v5` viene poblado (siempre lo está en el pipeline actual, ver sección 3).

Nota: `Altura_Pre_BAT_cm` (lee `pallet.altura_pre_bat`) y `Delta_Target_198_3` (lee `pallet.altura_target_delta`) en `construir_plan_picking_df` nunca se pueblan en el pipeline actual (esos campos los llenaba la lógica V4 de host BAT dinámico, retirada) — quedan siempre `None`/vacíos en el Excel exportado hoy. Candidatos a retiro junto con el resto de la limpieza Tier 2 mencionada en `DOCUMENTACION_LOGICA.md` sección 15.

### 4.17 `src/solver_cajas.py`

Solver de cubicaje 2D puro, sin dependencias del resto del repo (`functools.lru_cache` interno). `max_cajas(W, H, largo, ancho, con_pinwheel=True) -> (n, metodo)`: máximo de rectángulos idénticos (con rotación 90°) en una región W×H, probando de menor a mayor poder: grillas uniformes → guillotina recursiva (patrones mixtos, distinta orientación conviviendo) → pinwheel/five-block (no guillotinable). Usado por `reconciliacion_geometrica.capacidad_xy_max`. Validado contra 300 casos aleatorios y casos puntuales documentados en `Parches/v4_cubicaje_mixto/PARCHES_V4.md`.

### 4.18 `src/template.py` / `app.py` / `visualizacion.py`

`template.py`: genera la plantilla Excel de ejemplo descargable desde la UI. `app.py`: interfaz Streamlit — carga de archivos (combinado o 3 separados), métricas resumen, tabs (Plan de Picking / Log de Validación / Resumen por CD / Inspector de Pallets), descarga del Excel final. El "Inspector de Pallets" usa `resultado.pallets_v5` para mostrar la vista 3D real por torre (`visualizacion.dibujar_pallet_v5_3d`, 4 vistas: isométrica/frente/lateral/superior) — el `else` que cae a la vista 2D por cama (`dibujar_pallet`/`dibujar_cama`) es código muerto en la práctica, porque `pallets_v5` siempre viene poblado con el motor actual.

## 5. Estructuras de datos — resumen de contratos

| Objeto | Quién lo produce | Quién lo consume |
|---|---|---|
| `GeometriaSKU` | `reconciliacion_geometrica.reconciliar_sku` | `reconciliacion_geometrica.reconciliar` (arma columnas del df) |
| `TorreCandidate` | `torres.generar_torres_candidatas` | `packing_columnar`/`packing_bloques` (mejor ajuste) |
| `Torre` / `PlacementCaja` | `torres.crear_torre` (vía `_PalletEnConstruccion.colocar`) | `estabilidad`, `exportar` (Torres/Pallets_3D_Data), `visualizacion` |
| `PalletV5` | `packing_bloques.armar_pallets_bloques` | `bat.*`, `estabilidad.calcular_estabilidad`, `_palletv5_a_pallet`, `exportar.*`, `app.py` (Inspector) |
| `Pallet` / `PalletLinea` (modelo legado, `camas=[]`) | `pipeline_sku_bloque._palletv5_a_pallet` | `soporte` (no-op), `validacion_peso`, `benchmark.calcular_kpis`, `exportar.construir_plan_picking_df/construir_resumen_cd_df` |
| `CajaBAT` | `bat.consolidar_bat_por_cd` | `bat.asignar_cajas_bat_a_torres`, `pallet.cajas_bat` |
| `EstabilidadPallet` | `estabilidad.calcular_estabilidad` | `pallet.metadata["estabilidad"]`, `exportar.construir_estabilidad_df` |
| `BenchmarkResultado` / `GateV5Resultado` | `benchmark.calcular_kpis` / `evaluar_gate_v5` | `benchmark.benchmark_df`, inspección manual |

## 6. Notas de implementación

- **Peso de caja, fuente única**: `derivados.calcular_peso_caja` es la única fórmula, compartida entre `validacion.py` (V6) y `derivados.py` — evita que diverjan como pasó antes con dos fórmulas independientes.
- **Determinismo**: la corrida no tiene aleatoriedad en ningún punto (no hay multi-start/semillas en el pipeline actual, a diferencia de V5) — mismo input siempre produce el mismo Excel byte a byte.
- **`Cajas_Extra_Consolidacion` siempre 0**: el modelo actual no genera cajas "de más" para consolidar — cada línea despacha exactamente su demanda oficial (o queda en `sin_colocar`).
- **Nunca se descarta demanda en silencio**: tanto `packing_bloques.armar_pallets_bloques` como `packing_columnar.armar_pallets_columnar` registran cualquier resto sin colocar en `metadata["sin_colocar"]` del último pallet (o crean un pallet vacío para el aviso si no hay ninguno) en vez de perderlo.
- **Sobresaliente asimétrico**: 125×105cm solo aplica a pallets 100% dedicados a un SKU (`packing_bloques._dedicar_por_sku`); los pallets mixtos siguen con la base estricta 120×100. `validacion_v5.py` valida overflow contra la base extendida para ambos casos porque es el tope real más amplio — un pallet mixto que por construcción nunca la usa simplemente no la toca.
- **`soporte.py` es no-op hoy**: no eliminarlo asumiendo que "no hace nada" es intencional bajo el modelo columnar — está documentado como tal (sección 4.11), pero si se reintroduce un modelo con `Cama` real habría que revisar que siga funcionando.

## 7. Tests

103 tests en 17 archivos (`tests/`), sin `pytest.mark.skip` activo en el estado actual del dataset:

| Archivo | Qué cubre |
|---|---|
| `conftest.py` | Fixture `dataset_factory` — construye `(envios, maestro, uma)` sintéticos con overrides |
| `test_validacion.py` (10) | Reglas V1-V9 del Paso 0 |
| `test_derivados.py` (4) | `Peso_Caja`, `Nivel_Categoria`, `Cajas_Cama_Efectivo` |
| `test_reconciliacion_v5_p2.py` (4) | Estados de `Fuente_Geometria`, sobresaliente en reconciliación |
| `test_torres.py` (10) | `TorreCandidate`, `crear_torre`, `dividir_torre`, límites |
| `test_packing_columnar.py` (7) | Mecanismo MaxRects 2D genérico |
| `test_packing_3d.py` (8) | Apilado real en Z, `_area_union_xy`, conservación de demanda |
| `test_packing_bloques.py` (7) | La regla de bloques indivisibles — incluye el ejemplo textual del usuario (100 cajas, capacidad 150, un solo pallet) |
| `test_bat_v5.py` (9) | Consolidación BAT integrada, límites de la caja física, fungibilidad |
| `test_estabilidad.py` (7) | Centro de masa, torres esbeltas, peso superior |
| `test_validacion_v5.py` (9) | Overlap 3D, overflow (base estricta y extendida), altura |
| `test_gate_v5.py` (6) | Los 4 criterios del gate, acumulación de razones |
| `test_benchmark.py` (4) | KPIs, conteo de BAT dedicados |
| `test_exportar_v5.py` (4) | Conteo exacto de filas por hoja nueva, hojas ausentes si `pallets_v5` es `None` |
| `test_visualizacion_v5.py` (3) | Vista 3D no revienta con/sin torres BAT |
| `test_invariantes.py` (6) | Propiedades que deben cumplirse SIEMPRE (determinismo, IDs únicos, tope de altura, demanda nunca excedida) — sobreviven a refactors del algoritmo de armado |
| `test_pipeline_real_data.py` (5) | Corrida completa contra `Cubicaje18.07.2026.xlsx` — demanda exacta, sin violaciones |

Correr todo: `pytest -q` desde la raíz (requiere el venv de `env/`, Python 3.11 — con Python 3.10 del sistema, `pandas`/`openpyxl` funcionan pero `pytest` internamente falla por sintaxis de tipos exclusiva de 3.11 en su propio código, no en el del repo).

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

O `src.pipeline.ejecutar_desde_archivo(ruta_o_buffer)` si se tiene un único Excel con las 3 hojas. `src.exportar.exportar_workbook(resultado)` arma el `.xlsx` final.

## 9. Historial de arquitectura (resumen)

Detalle completo en `Parches/v5/PATCH_LOG.md`. El repo pasó por: motor V4 por camas horizontales → motor V5 columnar con multi-start/residual-search/packing 3D real → AUTO (V4+V5, mejor por CD) → SKU_CONSOLIDADO/SKU_BLOQUE (pivote a "SKU nunca repartido" como prioridad de negocio) → **limpieza** (`1c5f68e`, borra todo motor salvo SKU_BLOQUE: V4 completo, V5 multi-start puro, AUTO, AUTO_CONSOLIDADO, SKU_CONSOLIDADO, `legacy/` — `src/` -45% líneas) → **fix de orientación + sobresaliente real** (`506285c`, commit actual, sección 10.2 de `DOCUMENTACION_LOGICA.md`).

Antes de borrar cualquier módulo o constante en la limpieza se hizo `grep` de cada candidato contra `src/` completo — casos no obvios que se salvaron: `soporte.py` (no-op pero de bajo riesgo, no se tocó), `CATEGORIAS_REMATE`/`ORDEN_CATEGORIAS` (parecían muertas pero las usa `config.nivel_de_categoria`, llamado desde `derivados.py`), `solver_cajas.py` (lo importa `reconciliacion_geometrica.py`). `layout_solver.py` (V5-P3) sí estaba huérfano de verdad y se borró.

## 10. Dónde tocar para...

| Quiero cambiar... | Tocar |
|---|---|
| La ventana de altura permitida | `config.py` (`ALTURA_*`) |
| El umbral de peso de alerta | `config.py` (`PESO_ALERTA_KG`/`PESO_HARD_KG`) — sigue sin bloquear el armado |
| Cuándo un SKU se "dedica" a pallets completos | `packing_bloques._dedicar_por_sku` |
| El orden en que se eligen bloques ancla/complementarios | `packing_bloques._altura_potencial` y los `sorted(...)` de `armar_pallets_bloques` |
| Cuántos bloques se pueden partir por pallet | `packing_bloques.armar_pallets_bloques` (hoy hay un `break` explícito tras el primer split) |
| El tamaño/capacidad de la caja BAT | `config.py` (`CAJA_BAT_*`) |
| Cómo se integra BAT al armado | `src/bat.py` (sección "BAT integrado") + `pipeline_sku_bloque.py` |
| El sobresaliente permitido | `config.py` (`SOBRESALIENTE_MAX_CM`) + `packing_bloques._mejor_orientacion_grilla`/`_dedicar_por_sku` (dedicados) / `reconciliacion_geometrica.py` (validación de datos) |
| Los criterios del gate de benchmark | `benchmark.py` (`GATE_V5_PALLETS_MIN/MAX`, `evaluar_gate_v5`) |
| Qué cuenta como violación geométrica | `src/validacion_v5.py` |
| Las columnas del Excel de salida | `src/exportar.py` |
