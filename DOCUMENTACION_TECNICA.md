# Documentación técnica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** post V3 + parches V4/V4b/V4c (mezcla libre por geometría, confirmado contra fotos de los 42 pallets reales)
**Alcance:** arquitectura de código, contratos entre módulos, estructuras de datos y cómo operar el proyecto.

> Este documento reemplaza `DOCUMENTACION_TECNICA_V3.md`. La lógica de negocio (invariantes, prioridades, benchmark) está en `DOCUMENTACION_LOGICA.md`.

---

## 1. Qué hace el sistema

A partir de tres hojas de un Excel (`Envios_Julio`, `Maestro_SKUs`, `UMA`), calcula cómo armar pallets físicos (120×100cm) por centro de distribución (CD): qué cajas van en cada pallet, en qué cantidad, y con qué altura/peso resultante — minimizando la cantidad de pallets que hay que armar y mover, dentro de una ventana de altura de ~190-215cm.

Input: `envios, maestro, uma` (DataFrames) → `pipeline.ejecutar_pipeline(...)` → `ResultadoPipeline` (plan de picking, log de validación, resumen por CD, auditoría geométrica, benchmark).

## 2. Entorno

- Python 3.11 (via `uv`, venv en `env/`)
- Dependencias: `pandas`, `openpyxl`, `streamlit` (para `app.py`)
- Tests: `pytest -q` desde la raíz del repo
- Dataset real de referencia: `Cubicaje18.07.2026.xlsx` (raíz del repo)

```bash
source env/bin/activate
python -m pytest -q
streamlit run app.py
```

## 3. Flujo del pipeline (`src/pipeline.py::ejecutar_pipeline`)

```
VAL  validacion.validar_y_limpiar(envios, maestro, uma)      -> df_validado, log_df
DEM  demanda.normalizar_demanda(df_validado)                  -> df_demanda
GEO  reconciliacion_geometrica.reconciliar(df_demanda)         -> df_geo, auditoria_geometrica_df
DER  derivados.calcular_derivados(df_geo)                      -> df_derivado
     _construir_info_sku(df_derivado)                          -> info_sku (dict por SKU)
SPLIT bat.separar_bat(df_derivado)                             -> df_no_bat, df_bat
     clasificación: df_clasificado / df_no_clasificado / df_geometria_insuficiente
HOM  pallets_homogeneos.armar_pallets_homogeneos(df_clasificado) -> remanente_df, pallets_hom
P2D  packing_2d.generar_camas(remanente_df)                    -> camas_por_cd
P3D  apilado_3d.armar_pallets(camas_por_cd, info_sku, pallets_hom) -> pallets_apilado
BATPOOL bat.consolidar_bat_por_cd(df_bat)                       -> cajas_bat_por_cd
HOST bat.asignar_hosts_bat(pallets_apilado, cajas_bat_por_cd, info_sku)  (in-place)
SOP  soporte.clasificar_soporte_pallet(pallet)  por cada pallet  (in-place)
PESO validacion_peso.validar_pesos(todos_pallets, info_sku)     (in-place)
BENCH benchmark.calcular_kpis(...) / benchmark_df(...)
EXP  exportar.construir_plan_picking_df / construir_resumen_cd_df
```

`GEO` corre sobre **toda** la demanda (BAT incluido) antes del `SPLIT`: no porque BAT necesite geometría (usa una caja fija), sino para que `info_sku` (peso, categoría, nivel) quede completo para todos los SKUs — si se reconciliara después del split, `bat._colocar_bat` fallaría buscando metadata de Cigarros que nunca se calculó.

`pallets_comparables` (para el benchmark) excluye los pallets `PH-BAT-*` (dedicados, sin más contenido que cajas BAT) — no cuentan contra el benchmark real de 42, igual que las filas `PALLET=0` del dato real (ver `DOCUMENTACION_LOGICA.md`).

## 4. Módulos

### 4.1 `config.py`

Todas las constantes del sistema. Sin lógica de negocio compleja, solo cálculos derivados triviales. Grupos:

| Grupo | Constantes clave |
|---|---|
| Pallet | `PALLET_LARGO=120`, `PALLET_ANCHO=100`, `ALTURA_PALLET_VACIO=14.92` |
| Sobresaliente | `SOBRESALIENTE_MAX_CM=2.5`, `PALLET_LARGO_EFECTIVO=125`, `PALLET_ANCHO_EFECTIVO=105` |
| Rotación acostada | `CATEGORIAS_ROTACION_LIBRE=["Comestibles","Cigarros"]` |
| Altura | `ALTURA_TARGET=198.3`, `ALTURA_NOMINAL_MIN=190.0`, `ALTURA_MAX_OBSERVADA=215.0`, `ALTURA_HARD_VALIDADA=None` |
| Peso | `PESO_ALERTA_KG=1400`, `PESO_HARD_KG=1430`, `PESO_ES_RESTRICCION_DURA=False` |
| Soporte | `TOLERANCIA_ALTURA_PORTANTE=8`, `TOLERANCIA_ALTURA_TERMINAL=20`, `FILL_RATIO_MIN_SOPORTE=0.0` |
| BAT | `CATEGORIAS_BAT=["Cigarros"]`, `CAJA_BAT_LARGO=45.0`, `CAJA_BAT_ANCHO=24.0`, `CAJA_BAT_ALTO=55.0`, `CAJA_BAT_CAPACIDAD_UNIDADES=500` |
| Categorías | `ORDEN_CATEGORIAS`, `CATEGORIAS_REMATE`, `nivel_de_categoria()`, `normalizar_categoria()` — **ya no gatean el armado**, ver §4.7/§4.8; siguen siendo metadata de reporte |

Funciones: `estado_altura(altura)` (zona de reporte), `estado_pallet_por_altura(altura)` (traduce zona → `ESTADO_*`), `normalizar_categoria(valor)`, `nivel_de_categoria(categoria)`.

**Constantes retiradas de la decisión de armado pero mantenidas por compatibilidad**: `MAX_SEPARACION_NIVELES` (ya no se usa — ver §4.7), `RESERVA_ALTURA_REMATE=0` (BAT usa host dinámico, nunca reserva), aliases V2 (`ALTURA_TOTAL_MIN`, `PESO_TOPE_ELASTICO_KG`, etc.) que varios módulos/tests todavía referencian.

### 4.2 `models.py`

Dataclasses centrales:

- **`GeometriaSKU`**: resultado de reconciliar un SKU. Campos nuevos vs. V3: `acostada: bool` (True si la mejor orientación acuesta la caja).
- **`CajaBAT`**: caja física de consolidación de Cigarros (45×24×55cm, hasta 500 unidades).
- **`Placement`**: una posición concreta de N cajas de un SKU dentro de una cama (`x,y,w,d,h`).
- **`Cama`**: unidad de apilado vertical. `categorias: list[str]` (puede tener varias — mezcla libre), `nivel_categoria`, `tipo_soporte` (PORTANTE/TERMINAL), `support_ratio_min`, `geometria_inferida`. Properties: `nivel_efectivo`, `categoria_remate`, `es_flexible`, `fill_ratio`, `desnivel`.
  - `categoria_remate` sigue reventando (`ValueError`) si una **misma cama** mezcla Comestibles y Cigarros — invariante físico duro (una capa no puede ser dos cosas a la vez). A nivel **pallet** ya no son excluyentes (ver §4.8).
- **`Pallet`**: `camas`, `lineas`, `altura_final`, `peso_estimado`, `estado`, `altura_pre_bat`, `cajas_bat`, `es_host_bat`, `altura_target_delta`, `support_ratio_min`.
- **`ResultadoPipeline`**: output final del pipeline.

### 4.3 `src/solver_cajas.py` — solver de patrones mixtos (P1)

Movido tal cual desde `Parches/v4_cubicaje_mixto/solver.py`. `max_cajas(W, H, largo, ancho, con_pinwheel=True) -> (n, metodo)`: máximo de rectángulos idénticos (con rotación 90°) dentro de una región `W×H`, probando tres familias de patrones, de menor a mayor poder:

1. **Grillas uniformes** (`_grid`): filas × columnas en cada orientación.
2. **Guillotina recursiva** (`crear_solver`): cortes rectos de lado a lado, recursivo, con posiciones candidatas canónicas — encuentra patrones **mixtos** (bloques con distinta orientación conviviendo en la misma cama).
3. **Pinwheel/five-block**: descomposición NO guillotinable (molinete) — patrones que ninguna secuencia de cortes rectos puede producir.

Puro, sin dependencias del resto del repo (usa `functools.lru_cache` internamente por instancia de solver). Validado contra 300 casos aleatorios (nunca supera el límite de área) y casos puntuales documentados en `Parches/v4_cubicaje_mixto/PARCHES_V4.md`.

### 4.4 `src/reconciliacion_geometrica.py` — geometría efectiva por SKU

Responsabilidad: para cada SKU, decidir `Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo` (la geometría que el resto del motor usa) reconciliando dos fuentes que pueden contradecirse:

- **Maestro** (`Cajas por cama`): capacidad OPERACIONAL declarada por el negocio.
- **UMA** (`Largo/Ancho/Alto de caja`): dimensiones medidas.

```python
capacidad_xy_max(largo, ancho) -> (capacidad, orientacion)
```
Capacidad máxima contra el pallet estricto (120×100), probando grilla + mixto + molinete (vía `solver_cajas.max_cajas`). `orientacion` es `'A'`, `'B'` o `'MIXTA'` — ningún consumidor actual usa ese segundo valor para otra cosa que no sea descartarlo. Cacheado (`lru_cache`, clave `(largo, ancho, pallet_largo, pallet_ancho)` redondeados) — sin esto, `derivados.calcular_derivados` (que llama por FILA de demanda, no por SKU único) sería inviablemente lento (~70ms/dimensión con molinete).

```python
capacidad_xy_max_con_sobresaliente(largo, ancho) -> (capacidad, orientacion)
```
Igual pero contra el área EFECTIVA (`PALLET_LARGO_EFECTIVO/ANCHO_EFECTIVO`, 125×105 con 2.5cm de sobresaliente por lado). **Solo** para juzgar si un dato del Maestro es geométricamente creíble (P3, ver abajo) — nunca para la geometría real de packing.

```python
mejor_orientacion_3d(largo, ancho, alto, permitir_acostada, cajas_objetivo=None, con_sobresaliente=False)
    -> (largo_ef, ancho_ef, alto_ef, capacidad, acostada)
```
**(V4c)** Evalúa hasta 3 caras como huella: parada (`largo×ancho`, alto vertical) y, si `permitir_acostada` (categoría en `CATEGORIAS_ROTACION_LIBRE`), las 2 acostadas (`largo×alto` con ancho vertical; `ancho×alto` con largo vertical).

Criterio de selección — **no** es "más capacidad a cualquier costo": el Maestro sigue siendo el techo operacional, así que acostar una caja que YA alcanza ese techo parada solo suma altura de cama sin sumar cajas.

- Con `cajas_objetivo` (Maestro declaró algo): entre las orientaciones que **alcanzan** el objetivo, se elige la de **menor altura de cama**. Si ninguna alcanza, se elige la de **mayor capacidad** (para la rama de inconsistencia/degradado).
- Sin `cajas_objetivo`: se elige la de mayor capacidad sin más (esa capacidad se usa tal cual).

```python
inferir_footprint_desde_cajas_cama(cajas_cama, largo_uma, ancho_uma) -> (largo, ancho, info)
```
Busca `(largo, ancho)` que reproduzcan EXACTO `cajas_cama` en una sola orientación de grilla uniforme, priorizando la solución de menor `score = peso_delta * |cambio| + peso_vacio * espacio_no_usado + peso_aspecto * cambio_aspect_ratio`. Es geometría **inferida**, no medida — se usa solo cuando la medida real (aun acostada) no alcanza el techo del Maestro pero tampoco lo excede de forma imposible.

```python
reconciliar_sku(row) -> GeometriaSKU
```
Lógica completa (`row` debe traer SKU, Largo/Ancho/Alto de caja, Cajas por cama, Categoria_Normalizada):

1. Sin `Alto de caja` o sin `Largo/Ancho` → `DATO_INSUFICIENTE`, `requiere_revision=True`.
2. Calcula `mejor_orientacion_3d(..., cajas_objetivo=cajas_maestro)` → `capacidad_uma`.
3. Sin `Cajas por cama` del Maestro → `UMA_VALIDADA` (UMA es la única fuente).
4. `capacidad_uma >= cajas_maestro` → `UMA_VALIDADA` (exacto) o `UMA_SOBRECAPACIDAD` (UMA da más, pero el Maestro sigue siendo el techo — no se sube la densidad solo porque la geometría de para más).
5. `capacidad_uma < cajas_maestro`: se re-evalúa `mejor_orientacion_3d(..., con_sobresaliente=True)`. Si ni con sobresaliente se alcanza `cajas_maestro` → **`MAESTRO_IMPOSIBLE_DEGRADADO`** (P3): se degrada `cajas_cama_maestro` al techo geométrico real en vez de inventar una geometría ficticia (caso real: SKU 22183 declaraba 84 cajas/cama, el máximo con sobresaliente es 15).
6. Si sí se alcanza con sobresaliente (plausible, solo no exacto en estricto) → `INFERIDA_MAESTRO` vía `inferir_footprint_desde_cajas_cama`.

```python
reconciliar(df) -> (df_con_columnas, auditoria_df)
```
Reconcilia UNA VEZ POR SKU (`drop_duplicates`) y mapea el resultado a todas las filas. Agrega a `df`: `Largo_Efectivo, Ancho_Efectivo, Alto_Efectivo, Fuente_Geometria, Geometria_Inferida, Requiere_Revision_Geometria, Geometria_Acostada, Cajas_Cama_Maestro_Reconciliado`. Esta última es crítica: `derivados.py` la usa (no la columna cruda del Maestro) para que el degradado de P3 realmente proteja el plan, no solo la auditoría.

Estados posibles de `Fuente_Geometria`: `UMA_VALIDADA | UMA_SOBRECAPACIDAD | INFERIDA_MAESTRO | MAESTRO_IMPOSIBLE_DEGRADADO | DATO_INSUFICIENTE`.

### 4.5 `src/derivados.py`

`calcular_derivados(df)` — asume que `df` YA pasó por `reconciliar()`. Calcula:
- `Peso_Caja` (vía `calcular_peso_caja`, compartida con `validacion.py`).
- `Cajas_Teoricas_Redondeadas` / `Cajas_Extra_Redondeo`.
- `Cajas_Cama_Efectivo`: `Cajas_Cama_Maestro_Reconciliado` si es válido (no la columna cruda del Maestro — así el guard de P3 protege el plan real), si no, fallback geométrico vía `capacidad_xy_max(Largo_Efectivo, Ancho_Efectivo)`.
- `Nivel_Categoria`, `Es_Categoria_Remate` (metadata de reporte).

### 4.6 `src/demanda.py`

`normalizar_demanda(df)` — demanda a nivel de UNIDADES, no solo cajas. Agrega `Demanda_Unidades_Oficial, Unidades_por_Caja, Cajas_Completas, Unidades_Fraccionarias, Politica_Redondeo` (`UNIDADES_EXACTAS` para BAT, `CAJA_COMPLETA` para el resto), `Unidades_Exceso_Redondeo` (cuantifica lo que el redondeo hacia arriba infla, en vez de perderlo en silencio).

### 4.7 `src/packing_2d.py` — Paso 2/3: camas puras y mezcla

**(V4b)** Ya NO segrega por nivel de categoría ni aísla NABs/remate — confirmado contra las fotos de los 42 pallets reales, que mezclan categorías libremente en la misma cama según convenga geométricamente.

```python
generar_camas(df_remanente) -> dict[cd, list[Cama]]
```
Por CD: `_extraer_camas_puras(rows)` (camas de un solo SKU hasta su tope real de densidad, sobre TODO el grupo del CD) → el remanente se agrupa por `_clusterizar_por_altura` (tolerancia `TOLERANCIA_ALTURA_PORTANTE`) → `_mezclar_remanentes` arma camas de cierre combinando SKUs de cualquier categoría cuya altura sea similar.

`_empacar_cama(candidatos)`: shelf-packing 2D real — para cada SKU (ordenado por profundidad `d` descendente), intenta primero un shelf existente con suficiente ancho libre, si no abre uno nuevo. `_elegir_orientacion(largo, ancho)` prueba las 2 rotaciones XY (la caja siempre "de pie" desde la perspectiva de este módulo — la posible rotación acostada ya la resolvió `reconciliacion_geometrica` antes, cambiando qué dimensión ES el largo/ancho/alto efectivo).

`_capacidad_real_cama(sku, info)`: tope real de un SKU en cama pura — `Cajas_Cama_Efectivo` verificado empacándolo de verdad contra la geometría efectiva.

Funciones retiradas (existían en V3, ya no se llaman desde `generar_camas`): `_separar_nabs_y_remate`, `_separar_por_nivel` (usaban `config.MAX_SEPARACION_NIVELES`).

### 4.8 `src/apilado_3d.py` — Paso 4: armado de pallets

**(V4b)** Un solo pase de bin-packing sobre TODAS las camas del CD — ya no hay pases separados por nivel de categoría ni remate exclusivo.

```python
calcular_altura_pallet(pallet) -> float
```
Única función de altura de todo el sistema: `ALTURA_PALLET_VACIO + sum(c.altura_cama for c in pallet.camas)`. Una caja BAT es una `Cama` más en `pallet.camas` — no se suma aparte.

```python
_cabe(pallet, cama, info_sku) -> bool
```
Restricciones duras: **altura** (siempre, `cama.altura_cama <= _limite_altura(pallet) - pallet.altura_final`) y **peso** (solo si `config.PESO_ES_RESTRICCION_DURA`, default `False`). `_limite_altura` devuelve el tope operacional único `ALTURA_MAX_OBSERVADA` (215cm) — no hay distinción "techo normal vs. tope duro" ni reserva de altura para remate.

```python
_asignar_camas(camas, cd, contador, pallets_abiertos, info_sku)
```
Bin-packing best-fit: para cada cama (ordenada por `-altura_cama` y luego `-peso`, así las más pesadas se procesan primero y tienden a terminar más abajo — preferencia SUAVE "peso abajo", no una regla dura), busca entre TODOS los pallets ya abiertos del CD (incluidos los homogéneos) el que tenga menos espacio libre y aun así la reciba (`max` por `altura_final`); solo abre un pallet nuevo si ninguno sirve.

```python
_consolidar_pallets(pallets_cd, info_sku)
```
Red de seguridad: vacía, cuando es posible, los pallets bajo `ALTURA_TOLERADO_MIN` moviendo sus camas a otros pallets del CD con espacio — cualquier cama es movible ahora (`_es_flexible` siempre `True`), no solo NABs/remate como en V3. Nunca mueve hacia un pallet que termine peor que el origen (`altura_referencia` congelada).

```python
armar_pallets(camas_por_cd, info_sku, pallets_semilla=None) -> list[Pallet]
```
Orquesta lo anterior por CD (orden determinístico, `sorted(...)` — ver `PARCHE P3`), semillas = pallets homogéneos ya armados (Paso 2).

Funciones retiradas: `_agrupar_camas` (bucketeaba por nivel), `_asignar_remate` (pase separado de remate), `_remate_compatible`/`_remate_de` como GATE (siguen definidas, pero ya no se usan en el flujo principal — `bat.py` sí las usaba, ver §4.10).

### 4.9 `src/pallets_homogeneos.py` — Paso 2

Arma pallets de un solo SKU (`Homogéneo`) cuando `Cajas por PH` (Maestro) cabe un número entero de veces en la demanda. Usa `Alto_Efectivo` (reconciliado, puede venir acostado — **no** la columna cruda `Alto de caja`) para calcular `altura_final = ALTURA_PALLET_VACIO + Camas_por_PH * Alto_Efectivo`. Si esa altura supera `ALTURA_MAX_OBSERVADA`, el PH no se arma y toda la demanda del SKU pasa al remanente (Paso 3/4 la resuelve con geometría real).

### 4.10 `src/bat.py` — Cigarros/vapes

Cigarros/vapes NUNCA se despachan por caja completa (96% de sus líneas de demanda son fraccionarias). Se consolidan en una caja física FIJA (45×24×55cm, hasta 500 unidades) separada del cubicaje normal, que se coloca como remate encima de un pallet "host" ya armado — DESPUÉS de que todos los pallets normales están completos.

```python
separar_bat(df) -> (df_no_bat, df_bat)
consolidar_bat_por_cd(df_bat) -> dict[cd, list[CajaBAT]]
```
Arma cajas BAT de tamaño fijo usando la demanda REAL en unidades (`Demanda_Unidades_Oficial`, no `Cajas_Teoricas_Redondeadas` — evita la inflación ~3.8x del redondeo por línea). `n_cajas = ceil(unidades_totales_cd / 500)`. Nunca mezcla CDs.

```python
asignar_hosts_bat(pallets, cajas_bat_por_cd, info_sku, altura_target=ALTURA_TARGET) -> None
```
Para cada caja BAT del CD, en orden, cuatro niveles de fallback cada vez más permisivos (**V4b**: ya no hay chequeo de remate — Comestibles dejó de ser una categoría especial):

1. **`_buscar_host`**: un pallet que YA tiene margen (altura/peso/soporte), sin mover nada. Elige el que deje la altura resultante más cerca de `altura_target`.
2. **`_liberar_host`**: si ninguno tiene margen, se libera moviendo las camas superiores de un pallet candidato a otro del mismo CD que sí tenga lugar (simula el plan completo antes de ejecutarlo — si alguna cama no tiene destino real, descarta ese origen entero).
3. **`_buscar_host`** otra vez, esta vez sobre pallets que YA son host BAT (apila una segunda capa BAT sobre un host existente en vez de abrir uno nuevo).
4. **`_redistribuir_para_bat`**: si NINGÚN pallet Mixto del CD tiene margen ni moviendo camas de a una, se junta el contenido de TODOS los pallets Mixto y se reparte en uno MÁS de los que había — criterio "least-full-that-fits" (la cama va al pallet con MENOS altura acumulada, al revés del criterio "most-full-that-fits" del armado normal), para que el margen quede parejo. Repetible, acotado a como mucho una redistribución por caja BAT pendiente del CD.

Solo si ni el último nivel encuentra margen físico real se abre un pallet dedicado (`_consolidar_dedicados`, `PH-BAT-{cd}-NNN`): varias cajas BAT por capa (según cuántas entran físicamente en 120×100cm vía `capacidad_xy_max`), varias capas hasta el techo — nunca un pallet dedicado por CADA caja BAT.

Todos los chequeos de peso en este módulo respetan `config.PESO_ES_RESTRICCION_DURA` (soft por default).

`_colocar_bat(pallet, cajas, info_sku, altura_target)`: agrega una `Cama` con `categorias=["Cigarros"]` al final de `pallet.camas` (BAT siempre al final — un `append` simple ya lo deja arriba de todo). Puede recibir varias `CajaBAT` a la vez (consolidadas en una sola cama, físicamente una al lado de la otra en la misma capa).

### 4.11 `src/soporte.py`

`clasificar_soporte_pallet(pallet)`: post-procesa un pallet YA armado — marca la última cama `TERMINAL`, el resto `PORTANTE`, y calcula `support_ratio_min` (intersección geométrica real entre los `Placement` de la cama superior y la inferior, vía `support_ratio`). Puramente informativo/KPI — no bloquea el armado (`FILL_RATIO_MIN_SOPORTE=0.0`).

### 4.12 `src/validacion.py`

`cargar_hojas(ruta) -> (envios, maestro, uma)`. `validar_y_limpiar(envios, maestro, uma) -> (df, log_df)` — reglas V1-V9 (duplicados, cajas ≤0, SKU sin Maestro/UMA, dato no confiable, cajas por cama nulo, dimensión imposible para el pallet, alto excede máximo, peso fuera de rango, categoría no clasificada). Cada regla que excluye o modifica algo queda en `log_df`.

> **Limitación conocida**: la regla V4 (`_cabe_en_pallet`, dimensión imposible) solo prueba `largo×ancho` — no considera que una caja de Comestibles/Cigarros que no entra parada SÍ podría entrar acostada (la rotación se resuelve después, en `reconciliacion_geometrica`). No afecta el dataset actual (0 SKUs excluidos por esto), pero es un caso límite a tener en cuenta si aparece un SKU así.

### 4.13 `src/validacion_peso.py`

`validar_pesos(pallets, info_sku)`: calcula `peso_estimado` real de cada pallet desde sus líneas y marca `ESTADO_ALERTA_PESO` (>1400kg) / `ESTADO_PESO_NO_VALIDABLE` (algún SKU con peso fuera de rango sano) — **reporta, no bloquea** (el bloqueo real, si se activa, vive en `_cabe`/`bat.py` vía `PESO_ES_RESTRICCION_DURA`).

### 4.14 `src/benchmark.py`

`PALLETS_REALES=42, ALTURA_MEDIA_REAL=198.3, ALTURA_MIN_REAL=170.0, ALTURA_MAX_REAL=215.0` (ver `DOCUMENTACION_LOGICA.md` para la procedencia y advertencias sobre este número). `calcular_kpis(pallets, ...) -> BenchmarkResultado` (hashea dataset/commit/config para reproducibilidad). `comparar_contra_real`, `auditar_pallet`, `benchmark_df`.

### 4.15 `src/exportar.py`

`construir_plan_picking_df(pallets, info_sku)`: una fila por (pallet, línea), con columnas de geometría/BAT/soporte. `construir_resumen_cd_df(pallets)`: una fila por CD. `exportar_workbook(resultado)`: hojas `Plan_Picking, Log_Validacion, Resumen_por_CD, Auditoria_Geometrica, Benchmark`.

## 5. Datos de entrada corregidos

Las dimensiones UMA (`Largo/Ancho/Alto de caja`) de 202 SKUs en `Cubicaje18.07.2026.xlsx` fueron actualizadas desde `confirmacio_geometrica (1).xlsx` (medición física confirmada por el equipo del hub) — solo los SKUs presentes en ese archivo, el resto de la hoja UMA quedó intacto. Efecto: `MAESTRO_IMPOSIBLE_DEGRADADO` bajó de decenas de casos a solo 3.

## 6. Testing

```bash
python -m pytest -q
```
46 tests (`tests/test_*.py`), 1 se salta si `Cubicaje18.07.2026.xlsx` no está presente. `tests/conftest.py::dataset_factory` genera DataFrames sintéticos tipo Excel para tests unitarios sin depender del dataset real. `tests/test_pipeline_real_data.py` corre contra el dataset real y valida invariantes de extremo a extremo (altura nunca excede el tope, demanda nunca se despacha de más, BAT no abre pallets dedicados salvo necesidad genuina, etc.).

## 7. Módulos NO conectados al pipeline productivo

- `Parches/v4_cubicaje_mixto/layout.py`: reconstruye el patrón concreto (posiciones, no solo el conteo) del solver mixto — útil para mostrarle a un operario cómo armar una cama, no se llama desde el pipeline.
- `Parches/v4_cubicaje_mixto/exacto.py`: búsqueda EXHAUSTIVA (branch & bound) del máximo real de cajas — lenta (segundos por SKU), solo para auditar casos puntuales.
