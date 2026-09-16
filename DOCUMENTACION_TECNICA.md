# Documentación técnica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `7f174ee` (2026-09-14, HEAD), 44 commits totales. Único motor activo: **SKU_BLOQUE, armado cama por cama** (`src/packing_bloques.py`, 2138 líneas).
**Alcance:** arquitectura de código, contratos entre módulos, estructuras de datos y cómo operar el proyecto.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_TECNICA*.md`. La lógica de negocio (invariantes, prioridades, benchmark) está en `DOCUMENTACION_LOGICA.md`. El historial completo de cómo se llegó a este estado vive en `Parches/v5/PATCH_LOG.md` (~3925 líneas).

---

> **Actualización operativa — 2026-09-15:** BK31 manual es la referencia de negocio. El usuario confirmó **220 cm de altura total (incluye parihuela)** y **2 cm máximos por cada lado**, tanto sobre el borde exterior como sobre el apoyo. Las métricas de corridas anteriores que aparecen abajo son históricas; estos cambios no demuestran todavía que el solver coloque automáticamente las 98 cajas.

## Configuración operativa vigente

- `ALTURA_MAX_OBSERVADA = 220.0`: total con parihuela; producto disponible **205.08 cm**.
- `SOBRESALIENTE_MAX_CM = 2.0`: dominio XY **[-2, 122] × [-2, 102]**.
- `TOLERANCIA_OVERHANG_CM = 2.0`: vuelo sobre soporte por cada borde, en ambos ejes.
- `_tiene_soporte_admisible` verifica apoyo real en el interior de la huella; `_cantidad_sin_solape` limita el lote antes de un obstáculo superior.
- `tests/test_reglas_bk31.py` comprueba altura total, los cuatro límites exteriores, apoyo, huecos y colisiones del lote.

## 1. Qué hace el sistema

A partir de tres hojas de un Excel (`Envios_Julio`, `Maestro_SKUs`, `UMA`) más una hoja opcional (`Pallets_Objetivo`), calcula cómo armar pallets físicos (base 120×100cm) por centro de distribución (CD): qué SKUs van en cada pallet, en qué cantidad y posición, y con qué altura/peso resultante. El pallet se arma **cama por cama** (piso a techo), nunca por columnas verticales aisladas de un solo SKU. Cigarros/vapes se excluyen del armado por completo y se reportan aparte (sección 6).

Input: `envios, maestro, uma` (DataFrames) + `pallets_objetivo_por_cd` opcional → `src.pipeline.ejecutar_pipeline(...)` → `ResultadoPipeline` (plan de picking, log de validación, resumen por CD, auditoría geométrica, benchmark, cajas no colocadas, demanda de Cigarros, lista de `PalletV5` para inspección/export detallado).

## 2. Entorno

- Python 3.11 nominal (venv `env/`); el código propio solo usa sintaxis `X | None` (PEP 604, válida desde 3.10) — no depende de nada exclusivo de 3.11.
- Dependencias (`requirements.txt`): `pandas`, `openpyxl`, `streamlit`, `matplotlib`, `pytest`.
- Dataset real de referencia: `Cubicaje18.07.2026.xlsx` (raíz del repo). También hay `Cubicaje_B_corregido.xlsx`, `Cubicaje_C_optimizado.xlsx`, `Cubicaje_remedido.xlsx` de iteraciones anteriores.

```bash
source env/bin/activate
python -m pytest -q          # 181 tests en 22 archivos bajo tests/
streamlit run app.py
```

## 3. Flujo del pipeline

`pipeline.ejecutar_pipeline` delega directo en `pipeline_sku_bloque.ejecutar_core_sku_bloque` (único camino, sin selector de motor):

```
VAL     validacion.validar_y_limpiar(envios, maestro, uma)          -> df_validado, log_df
DEM     demanda.normalizar_demanda(df_validado)                     -> df_demanda
GEO     reconciliacion_geometrica.reconciliar(df_demanda)           -> df_geo, auditoria_geometrica_df
DER     derivados.calcular_derivados(df_geo)                        -> df_derivado  (nace Cajas_Cama_Efectivo)
        _construir_info_sku(df_derivado)                            -> info_sku (dict por SKU)
SPLIT   bat.separar_bat(df_derivado)                                -> df_no_bat, df_bat
        clasificación: df_clasificado / df_no_clasificado / df_geometria_insuficiente
BATPOOL bat.consolidar_bat_por_cd(df_bat)                            -> cajas_bat_por_cd (solo para reporte, sección 6)
CAMAS   por cada CD (en paralelo si hay 2+, ver sección 5.6):
          packing_bloques.armar_pallets_bloques(grupo, cd, contador, pallets_objetivo, paralelo_lns) -> list[PalletV5]
          estabilidad.calcular_estabilidad(p)  -> p.metadata["estabilidad"]
ADAPT   _palletv5_a_pallet(pv5, info_sku)  por cada PalletV5          -> Pallet (modelo legado, reusa soporte/export/benchmark)
SOP     soporte.clasificar_soporte_pallet(pallet)  (no-op real: PalletV5 no llena `.camas`, ver sección 9)
PESO    validacion_peso.validar_pesos(todos_pallets, info_sku)       -> pallet.peso_estimado / pallet.estado
BENCH   benchmark.calcular_kpis(...) -> benchmark.benchmark_df([...])
EXP     exportar.construir_plan_picking_df / construir_resumen_cd_df /
        construir_cajas_no_colocadas_df / construir_demanda_cigarros_df
```

`df_no_bat` es la demanda que SÍ compite por espacio (todo excepto Cigarros/vapes). Ya no se concatena ningún pseudo-SKU BAT antes de armar (a diferencia de versiones anteriores) — Cigarros no toca `armar_pallets_bloques` en ningún punto.

## 4. Modelos de datos (`models.py`)

Dos familias de dataclasses conviven en el mismo archivo:

- **Legado (`Pallet`, `Cama`, `Placement`, `PalletLinea`, `GeometriaSKU`, `CajaBAT`)**: modelo por camas horizontales de V3/V4. Sigue siendo el formato que consumen `soporte.py`, `exportar.py` y `benchmark.py` — el adaptador `_palletv5_a_pallet` traduce hacia acá.
- **Columnar V5 (`Torre`, `PlacementCaja`, `PalletV5`, `OrientacionCaja`)**: el modelo real del motor de armado. Un `PalletV5.torres` es una lista de `Torre` (mismo SKU apilado en una posición XY fija); `Torre.z` es la base de ESE segmento dentro de la pila, no siempre 0 — permite que un SKU distinto ocupe el mismo (x,y) por encima de otro, con `z >= z_anterior + altura_anterior` ("lego real", no columnas aisladas).
- `ResultadoPipeline`: agrega `cajas_no_colocadas_df` y `demanda_cigarros_df` (nuevos desde la versión anterior de este documento) a los campos ya existentes (`plan_picking_df`, `pallets_v5`, `benchmark_df`, `auditoria_geometrica_df`).

`Cama`/`Pallet` conservan properties de la época de camas puras (`nivel_efectivo`, `categoria_remate`, `es_flexible`, `fill_ratio`) que hoy no se llenan desde el camino real (`PalletV5.camas` nunca se puebla) — se mantienen por compatibilidad con `soporte.py`/tests antiguos, no por uso activo.

## 5. `src/packing_bloques.py` — el motor (2138 líneas)

### 5.1 Punto de entrada y despacho

```python
armar_pallets_bloques(df_cd, cd, contador, pallets_objetivo=None, paralelo_lns=True) -> list[PalletV5]
```

- **Si `pallets_objetivo` está seteado** → `_empacar_n_pallets(..., priorizar_grandes=True)`. No corre consolidación de remanentes ni redistribución (podrían bajar la cantidad de pallets por debajo del objetivo fijo).
- **Si no** → `_empacar_optimizado(...)`, seguido de una consolidación de remanentes (reintentos acotados vía `_empacar`) y `_redistribuir_dispersos` (fusiona pallets casi vacíos con espacio libre de otros).

### 5.2 Cadena de llamadas

```
_empacar_optimizado
  ├─ _empacar                         (barrido voraz puro, da n_greedy)
  ├─ búsqueda binaria de N < n_greedy vía _empacar_n_pallets(con_lns=False)   [sondeos baratos, solo DFS]
  └─ corrida final en la N ganadora, con LNS completo

_empacar_n_pallets (wrapper)
  ├─ _empacar_n_pallets_greedy         (baseline, sin backtracking)
  ├─ _resolver_pallets_backtracking    (DFS con poda, desde cero)
  └─ _lns_mejorar_pallets              (ruina y reconstrucción, si queda demanda sin colocar)
       ├─ _romper_skus_con_cascada     ("ruina": saca SKUs al azar + cascada de lo que queda flotando)
       ├─ _candidatos_lote             (candidatos de colocación por lote, reusa _resolver_pallets_backtracking)
       └─ _lns_una_semilla_worker      (paraleliza semillas vía ProcessPoolExecutor si paralelo_lns=True)
  y se queda con el resultado (greedy vs DFS vs DFS+LNS) que coloque MÁS cajas.
```

### 5.3 Funciones principales (una línea cada una)

| Función | Rol |
|---|---|
| `_capacidad_instalada` / `_necesita_columna_nueva` | Cuánto más cabe en columnas ya existentes de un SKU vs. si genuinamente necesita abrir una nueva |
| `_soporte_viola_nivel` | Bloquea que una caja se apoye directo sobre una categoría más pesada (jerarquía de nivel, no bandas) |
| `_altura_compatible_con_cama` | Tolerancia simétrica de 8cm (`TOLERANCIA_ALTURA_CAMA_CM`) para compartir cama entre alturas de caja distintas |
| `_solapa_con_torres` / `_fit_directo_o_con_tolerancia` | Chequeo de solape y fallback de tolerancia de sobresaliente sobre soporte (`TOLERANCIA_OVERHANG_CM`) |
| `_cuboide_admite_candidato` | Admisión combinada (tope de capa, nivel, compatibilidad de altura) para un cuboide libre |
| `_hay_torre_mismo_sku_en_xy` | Desempate "seguir la misma torre" (sección 9.4 de la lógica) |
| `_mejor_cuboide_para_sku` | Elige el cuboide admisible de menor Z para un candidato |
| `_empacar` | Barrido voraz clásico, una caja a la vez, sin backtracking |
| `_reservar_skus_grandes` | Pre-pasada tipo Shelf-FFDH que reserva territorio para SKUs de footprint grande (solo si `priorizar_grandes=True`) |
| `_empacar_n_pallets_greedy` | Baseline voraz para N pallets fijos |
| `_snapshot_estado_pallets` / `_restaurar_estado_pallets` | Undo/redo barato para el backtracking (sin `deepcopy`) |
| `_candidatos_lote` | Arma candidatos de colocación por lote (columna entera de una vez, no caja por caja) para el DFS |
| `_resolver_pallets_backtracking` | DFS con poda, cota superior admisible, presupuesto de nodos y de reloj |
| `_romper_skus_con_cascada` | Paso de "ruina" del LNS, con cascada anti-flotación |
| `_lns_mejorar_pallets` / `_lns_una_semilla_worker` | Ruina y reconstrucción, multi-semilla, paralelizable |
| `_empacar_optimizado` | Búsqueda binaria de la N mínima de pallets que sigue colocando el 100% de la demanda (camino abierto) |
| `_redistribuir_dispersos` | Post-proceso: fusiona pallets con baja ocupación en el espacio libre de otros |

**Confirmado por grep**: no existe ninguna función `_banda_de_sku` en el archivo — el esquema de bandas estrictas fue completamente revertido, solo queda como comentario histórico y en el nombre de un test (`test_four_loko_queda_en_banda_remanente_no_en_licores`, donde "banda" ya significa "zona remanente", no exclusividad).

### 5.4 Constantes de ajuste (`packing_bloques.py`)

```python
CATEGORIAS_ORIENTACION_FLEXIBLE = {"Comestibles", "Aseo", "Cigarros"}   # Cigarros es vestigial: nunca llega a esta función (sección 6)
TOLERANCIA_ALTURA_CAMA_CM = 8.0
COMBINACION_PALLETS_SHORTLIST_K = 8
COMBINACION_PALLETS_MAX_NODOS = 30_000
COMBINACION_PALLETS_OPCIONES_POR_SKU = 1        # subirlo a 2-3 se probó y EMPEORÓ el resultado; no repetir
COMBINACION_PALLETS_LNS_ITERACIONES = 200
COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX = 40
COMBINACION_PALLETS_LNS_SKUS_A_ROMPER = 2
COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION = 3_000
COMBINACION_PALLETS_LNS_REINICIOS = 5
COMBINACION_PALLETS_TIEMPO_MAX_DFS_SEGUNDOS = 45.0
COMBINACION_PALLETS_TIEMPO_MAX_LNS_SEGUNDOS = 90.0
COMBINACION_ABIERTO_MAX_INTENTOS_BUSQUEDA = 5
UMBRAL_OCUPACION_DISPERSO = 0.5
UMBRAL_CONSOLIDACION_FRACCION = 0.6
MAX_INTENTOS_CONSOLIDACION = 3
```

En `config.py`: `PRIORIZAR_GRANDES_FRACCION_AREA_PALLET = 0.05` (umbral de "SKU grande" como fracción del área del pallet, solo usado por `_reservar_skus_grandes`) y `TOLERANCIA_OVERHANG_CM = 2.0` (activo, por lado).

### 5.5 `src/packing_columnar.py` — motor geométrico compartido

MaxRects 3D (`_PalletEnConstruccion`, `_CuboidLibre`, `_actualizar_libres_maxrects`, `_reconstruir_en_construccion`). Es el único lugar donde se calcula qué cuboides libres quedan tras colocar una caja — tanto `_empacar` como el DFS/LNS lo reusan tal cual, sin reimplementar geometría por su cuenta.

### 5.6 Paralelización (`pipeline_sku_bloque.py`)

Dos niveles, nunca anidados a la vez:

- **Por CD**: si hay 2+ CDs, `ProcessPoolExecutor` (contexto `fork`) manda hasta `PIPELINE_MAX_PROCESOS_CD = os.cpu_count()` CDs a la vez a `_procesar_cd` (worker de nivel de módulo, necesario para que se pueda "picklear"). Cada CD trae su propio contador de IDs local (`PV5-{cd}-NNN`, nunca global) — confirmado seguro por grep, ningún otro lugar asume un contador compartido.
- **Por semilla LNS**: solo cuando hay un único CD (`paralelo_lns=True`), las semillas del LNS se mandan a otro `ProcessPoolExecutor`.
- Riesgo conocido, no resuelto en un entorno distinto: `fork` en macOS puede chocar con librerías que ya inicializaron hilos nativos antes del fork; no se vio ningún crash en las corridas de referencia, pero si aparece en producción la mitigación estándar es forzar `spawn` a costa de velocidad.

## 6. Cigarros/vapes (`src/bat.py`)

```python
separar_bat(df) -> (df_no_bat, df_bat)          # por Categoria_Normalizada in config.CATEGORIAS_BAT (=["Cigarros"]) o Subcategoría in {"vapes"}
consolidar_bat_por_cd(df_bat) -> dict[CD, list[CajaBAT]]   # cajas físicas fijas (CAJA_BAT_*), nunca mezcla CDs
```

`df_bat` (toda la categoría Cigarros, no solo un subconjunto marcado) se separa ANTES de `armar_pallets_bloques` y nunca vuelve a entrar al armado. `consolidar_bat_por_cd` calcula cuántas cajas físicas de consolidación (hasta 1000 unidades c/u) hacen falta por CD, usando unidades reales (no la redondeada a caja completa, que infla ~3.8x). Esto alimenta únicamente `exportar.construir_demanda_cigarros_df` → hoja "Cigarros" del Excel.

La segunda mitad del archivo ("BAT integrado": `construir_filas_bat_pseudo_sku`, `renombrar_pallets_bat_puros`, `asignar_cajas_bat_a_torres`) implementa el mecanismo ANTERIOR, donde Cigarros competía por espacio como pseudo-SKU `__BAT__` y terminaba de remate sobre un pallet host. **No lo llama ningún camino de producción actual** (confirmado: `pipeline_sku_bloque.py` no importa `construir_filas_bat_pseudo_sku`) — se conserva probado por si se decide volver a ese modelo.

## 7. Reconciliación geométrica (`src/reconciliacion_geometrica.py`)

Sin cambios de arquitectura respecto a la versión anterior. Punto de entrada: `reconciliar(df) -> (df con columnas *_Efectivo, auditoria_df)`, que llama a `reconciliar_sku(row)` una vez por SKU único (no por fila CD+SKU). Cascada de `reconciliar_sku`, en orden:

1. Sin `Alto de caja` o sin `Largo`/`Ancho` en UMA → `DATO_INSUFICIENTE` (dimensión `<= 0` cuenta como faltante, no solo `NaN` — fix real, sección 12 de la lógica).
2. Sin `Cajas por cama` en el Maestro → se usa la geometría UMA tal cual (`UMA_VALIDADA`), vía `mejor_orientacion_3d` (evalúa acostada si la categoría está en `CATEGORIAS_ROTACION_LIBRE`).
3. La geometría UMA (mejor orientación) ya explica o supera el Maestro → `UMA_VALIDADA` / `UMA_SOBRECAPACIDAD`, sin tocar nada.
4. La geometría estricta no alcanza, pero SÍ alcanza con el sobresaliente de negocio (2cm/lado, `capacidad_xy_max_con_sobresaliente`) → `UMA_VALIDADA_CON_SOBRESALIENTE`, sin cambiar ninguna medida real de packing.
5. Ni con sobresaliente alcanza → se degrada el techo declarado del Maestro al techo geométrico real (`MAESTRO_IMPOSIBLE_DEGRADADO`) — nunca se llama a `inferir_footprint_desde_cajas_cama` para inventar un footprint ficticio que "cierre" matemáticamente (esa función sigue en el archivo, pero `reconciliar_sku` ya no la usa; ver su docstring para el motivo: siempre encuentra "algo", sea o no representativo de la caja real).

`capacidad_xy_max` prueba grillas uniformes en las 2 orientaciones **y** patrones mixtos/molinete vía `src/solver_cajas.max_cajas` (con `lru_cache`, porque se llama por fila de demanda, no por SKU único).

## 8. `src/derivados.py`

`calcular_derivados(df)` (asume que `df` ya pasó por reconciliación):

- `Peso_Caja` = `calcular_peso_caja(...)`, compartida con `validacion.py` para que ambos usen el mismo número (antes divergían en silencio).
- `Cajas_Cama_Efectivo`: `Cajas_Cama_Maestro_Reconciliado` (ya degradado si hacía falta) si es válido (`> 0`), si no, cae a la capacidad geométrica de la geometría EFECTIVA.
- `Nivel_Categoria`: `config.nivel_de_categoria(categoria)` — Comestibles/Cigarros ya no quedan en `None`, tienen nivel propio (7 y 8 respectivamente, aunque Cigarros no llega a competir por espacio, sección 6).
- SKUs frágiles (`Subcategoría` en {"rtd", "energizante"}, case-insensitive) se fuerzan a `NIVEL_REMATE` — reemplaza por completo el matching anterior por texto en la Descripción ("Four Loko").

## 9. Validación y soporte

- **`src/validacion_v5.py`**: auditoría geométrica dura e independiente del packer. `validar_pallet_v5(pallet) -> list[str]` chequea, en este orden: anti-flotación (área de huella cubierta por soportes reales, sweep de coordenadas comprimidas — mismo patrón que `packing_columnar._area_union_xy`), overflow contra el margen simétrico por lado (X [-2, 122], Y [-2, 102]), overlap AABB en 3D (X, Y, Z — dos torres pueden compartir X,Y si sus rangos de Z no se cruzan, eso es apilado válido) y tope duro de altura.
- **`src/soporte.py`**: `clasificar_soporte_pallet(pallet)` calcula `support_ratio` entre camas — hoy es esencialmente un no-op sobre el camino real, porque `_palletv5_a_pallet` nunca puebla `Pallet.camas` (el modelo columnar no arma `Cama` explícitas). Se mantiene por compatibilidad con tests/exportación antigua.
- **`src/estabilidad.py`**: KPIs informativos por pallet (nunca bloquean): desviación del centro de masa XY respecto al centro geométrico (`COG_MAX_DESVIACION_CM=15`), torres "esbeltas" (`altura/lado_corto > RATIO_ESBELTEZ_MAX=4.0`), fracción de peso en la mitad superior del pallet (`PESO_SUPERIOR_FRACCION_MAX=0.6`, medido con el centro real de cada segmento de torre, no solo `altura/2`). Se guarda en `pallet.metadata["estabilidad"]` y se exporta en la hoja `Estabilidad_V5`.
- **`src/validacion_peso.py`**: calcula `peso_estimado` por pallet y marca `⚠ ALERTA DE PESO` sobre `PESO_ALERTA_KG=1400` — nunca bloquea (`config.PESO_ES_RESTRICCION_DURA=False`).
- **`src/benchmark.py`**: KPIs agregados contra el benchmark de 42 pallets reales; `evaluar_gate_v5` (rango 42-45 pallets + demanda exacta + altura ≤220 + 0 violaciones) sigue existiendo mecánicamente igual que antes.

## 10. `src/validacion.py` — carga y validación de entrada

```python
cargar_hojas(ruta_o_buffer) -> envios, maestro, uma
cargar_pallets_objetivo(ruta_o_buffer) -> dict[CD, int] | None
```

`cargar_pallets_objetivo` (nuevo desde la versión anterior de este documento) lee la hoja opcional "Pallets_Objetivo" — si no existe o viene vacía, devuelve `None` y el comportamiento es idéntico al de siempre. Reutiliza el mismo buffer/archivo que `cargar_hojas` sin necesitar `seek` manual (confirmado: `pandas`/`openpyxl` hacen sus propios seeks absolutos).

`validar_y_limpiar` conserva la regla V4 (dimensión de caja imposible para el pallet en ninguna orientación → excluye la fila ANTES de reconciliar) — esa demanda excluida se reconstruye en `pipeline_sku_bloque._demanda_excluida_geometria` para que llegue igual a la hoja `Cajas_No_Colocadas` (antes solo quedaba en `Log_Validacion`, invisible en el reporte de negocio).

## 11. `src/exportar.py` — hojas del Excel final

| Función | Hoja | Contenido nuevo desde la versión anterior |
|---|---|---|
| `construir_plan_picking_df` | `Plan_Picking` | `N_Parihuela` (número secuencial de pallet por CD, para picking), `Cajas_Por_PH`, `Unidades_Por_Caja`, `Nombre_CD` |
| `construir_resumen_cd_df` | `Resumen_por_CD` | Sin cambios de esquema |
| `construir_torres_df` | `Torres` | Sin cambios de esquema |
| `construir_pallets_3d_data_df` | `Pallets_3D_Data` | Sin cambios de esquema |
| `construir_cajas_no_colocadas_df` | `Cajas_No_Colocadas` (**nueva**) | CD/SKU/Descripcion/Categoria/Cajas_No_Colocadas/Unidades_No_Colocadas — une lo que `armar_pallets_bloques` marca como `sin_colocar` con la demanda excluida antes del armado (sección 10). Solo se agrega si hay algo que reportar. |
| `construir_demanda_cigarros_df` | `Cigarros` (**nueva**) | CD/Nombre_CD/SKU/Descripcion/Unidades_Demanda/Unidades_Por_Caja/Cajas_Teoricas/Total_Unidades_CD/Cajas_Consolidacion_Necesarias_CD. Solo se agrega si hay demanda de Cigarros. |
| `construir_estabilidad_df` | `Estabilidad_V5` | Sin cambios de esquema |
| `exportar_workbook` | (orquesta todas) | Agrega `Cajas_No_Colocadas` y `Cigarros` condicionalmente |

## 12. `src/template.py` — plantilla de ejemplo

`construir_template()` genera un Excel con 5 hojas: `Instrucciones`, `Envios_Julio`, `Maestro_SKUs`, `UMA` (con datos de muestra, incluye un SKU de ejemplo "Four Loko" con `Subcategoría="RTD"`) y **`Pallets_Objetivo`** (hoja opcional, con un ejemplo de un CD). La hoja `Instrucciones` documenta cada columna, incluyendo cuándo usar `Subcategoría` (RTD/Energizante para frágiles) y el costo real de usar `Pallets_Objetivo` ("puede tardar varios minutos por pallet listado").

## 13. `app.py` — interfaz Streamlit

Título: "Agente Cubicador — Motor de Optimización de Pallets". Acepta un Excel combinado (3-4 hojas) o 3 archivos separados. Detecta automáticamente la hoja `Pallets_Objetivo` si está presente. Tabs del resultado: `tab_plan`, `tab_log`, `tab_resumen`, **`tab_no_colocadas`** (nueva — `st.success` si no hay faltantes, `st.warning` + tabla si los hay), **`tab_cigarros`** (nueva), `tab_inspector` (visualización 3D).

## 14. Módulos sin llamador de producción (código muerto/archivado, confirmado por grep)

| Archivo | Estado |
|---|---|
| `src/packing_ph_fraccion.py` (684 líneas) | Motor aproximado por fracción de PH — construido, calibrado, conectado, debuggeado, y finalmente revertido (sección 15 de `DOCUMENTACION_LOGICA.md`). Solo se menciona en comentarios/docstrings de `pipeline_sku_bloque.py`, ningún `import` real lo usa en producción. Sigue con sus propios tests (`tests/test_packing_ph_fraccion.py`). |
| `src/layout_solver.py` | Revivido en un patch anterior, nunca conectado a ningún pipeline. Confirmado por grep: el único archivo que lo importa es su propio test (`tests/test_layout_solver.py`). |
| `src/bat.py`, sección "BAT integrado" (`construir_filas_bat_pseudo_sku`, `renombrar_pallets_bat_puros`, `asignar_cajas_bat_a_torres`) | Mecanismo anterior de Cigarros-como-pseudo-SKU-competitivo, reemplazado por la exclusión total de la sección 6. Probado, no llamado. |

## 15. Tests (`tests/`, 22 archivos, 181 `def test_` encontrados)

Archivos nuevos desde la versión anterior de este documento: `test_cajas_no_colocadas.py`, `test_exportar_plan_picking.py`, `test_pallets_objetivo.py`, `test_packing_ph_fraccion.py`. El archivo más grande, `test_packing_bloques.py` (40 tests), cubre entre otras cosas:

- Capacidad/no pérdida de demanda, geometría fila-por-fila sin columnas aisladas, camas de altura mixta compartida.
- Jerarquía de nivel post-reversión de bandas (`test_licores_nunca_queda_arriba_de_nabs`, `test_licores_lacteos_nabs_pueden_compartir_piso_del_pallet`, `test_four_loko_queda_en_banda_remanente_no_en_licores`).
- Solver de N pallets fijos: `test_n_pallets_backtracking_nunca_peor_que_el_greedy`, `test_pallets_objetivo_respeta_cantidad_exacta_y_reporta_sin_colocar`, `test_snapshot_restaurar_estado_pallets_es_identidad`, `test_romper_skus_con_cascada_saca_tambien_lo_que_queda_flotando`.
- Tolerancia de sobresaliente (tests actualizados para 2 cm por lado y opción de desactivar la tolerancia).
- "Grandes primero" (4 tests sintéticos que protegen `_reservar_skus_grandes` de regresiones, aunque el mecanismo no está activo en producción — sección 10 de la lógica).

`tests/test_invariantes.py` corre el pipeline completo contra un archivo real de 12 CDs (fixture interna `ARCHIVO_REAL`, no `Cubicaje18.07.2026.xlsx`) y es la referencia de regresión de más alto nivel del proyecto.

## 16. Verificación en vivo hecha en esta revisión

Se corrió `armar_pallets_bloques` directamente (saltando el prep de validación/reconciliación, ya verificado por separado) contra 2 de los 9 CDs de `Cubicaje18.07.2026.xlsx`:

```
BK41: demanda=280  colocado=280  pallets=4  violaciones=0   alturas=[207.6, 212.9, 214.4, 210.9]  ocupacion_xy=[0.81, 0.89, 0.88, 0.75]
BK65: demanda=347  colocado=347  pallets=5  violaciones=0   alturas=[212.9, 212.9, 214.5, 212.9, 212.9]  ocupacion_xy=[0.94, 0.94, 0.81, 0.87, 0.87]
```

No se pudo completar una corrida de los 9 CDs completos en una sola invocación por el costo real de tiempo del solver (el sandbox de esta sesión tiene un límite práctico de ~180s por comando; el pipeline completo con LNS puede tardar de 1 a 15 minutos según cuánta compresión exige la demanda, ver sección 9.3/10 de la lógica). El número agregado más reciente confiable, verificado y registrado en `Parches/v5/PATCH_LOG.md` (fixture interna de 12 CDs, tras excluir Cigarros): **49 pallets totales, 4 parciales (8%), 94% de aprovechamiento de altura**, con la suite completa (177 tests en ese momento, 181 hoy) en verde.

## 17. Cómo correr una verificación completa (para la próxima sesión)

```bash
source env/bin/activate
python -m pytest -q                                   # suite completa
python -c "
from src.pipeline import ejecutar_desde_archivo
r = ejecutar_desde_archivo('Cubicaje18.07.2026.xlsx')
print(len(r.pallets), 'pallets')
"
```
En un entorno sin límite de tiempo por comando, esta segunda corrida da el número agregado real de los 9 CDs — no se pudo obtener en esta sesión por la restricción de tiempo del sandbox usado para escribir este documento, no por una limitación del código.
