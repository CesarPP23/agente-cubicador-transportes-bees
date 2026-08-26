# Parches v2 — Altura elástica, peso, peso-UMA y camas por dimensión

**Repo:** `agente-cubicador-transportes-bees`
**Rama de trabajo sugerida:** `feat/parametros-altura-peso-v2` (ya creada, con los cambios de la sección 1 aplicados)
**Para:** desarrollador / Claude Code que va a ejecutar el resto de los cambios directo en el código
**Origen:** 6 cambios de negocio pedidos por Omar sobre `Diseno_Motor_Optimizacion_Pallets.md` v1.1

Este documento no reemplaza el doc de diseño — lo actualiza en los puntos que cambian. Está pensado para ejecutarse de arriba hacia abajo: la sección 1 ya está aplicada (verificar), las secciones 2-6 son las que faltan, en el orden en que conviene aplicarlas (cada una depende de la anterior).

---

## 0. Los 6 cambios pedidos, tal cual los dio Omar

1. Altura total del pallet: mínimo 190 cm, máximo 205 cm (solo casos extremos), recomendado 195–200 cm por seguridad del trabajador.
2. Lo mismo para altura de producto: 180–190 cm.
3. Peso máximo 1.400 kg, con elasticidad hasta 1.430 kg.
4. "NABs" y "Nabs" son la misma categoría — estandarizar.
5. La columna `Peso bruto por unidad` de la hoja UMA es el peso de la **caja** del SKU, no de la unidad — usarla así en el cálculo del peso del pallet.
6. El agrupamiento de camas mixtas no debe restringirse a la misma categoría normalizada — debe ser por medidas de la caja. Siguen siendo remanentes para llegar a la altura máxima.

Más una corrección transversal: arreglar toda inconsistencia de altura en el código a **mínimo 190 cm (margen ±5 cm para cajas altas → 185 cm tolerado) y máximo 205 cm**, con la regla explícita: si un pallet está en ~185 cm y agregar una cama de remanente más lo lleva a 208–210, está bien agregarla; si lo haría superar 210, no se agrega y el pallet queda en 185.

### Decisiones ya tomadas con Omar (no volver a preguntar)

| Pregunta | Decisión |
|---|---|
| `Peso bruto por unidad` de UMA, ¿es de la unidad o de la caja? | **Es el peso de la caja.** Verificado con el Excel vigente en el repo (`Cubicaje18.07.2026.xlsx`, actualizado 12-ago): tratarla como peso de caja da densidades de 130–855 kg/m³ por categoría (físicamente correctas); multiplicarla por `Unidades por caja` da 7.700–65.000 kg/m³ (imposible). **Nota:** el archivo que Omar subió al chat el 11-ago tenía valores de peso distintos (peso por unidad real) — el repo ya tiene la versión corregida del 12-ago. Si en algún momento vuelve a aparecer un Excel con la columna en peso-por-unidad, usar `config.PESO_UMA_ES_POR_UNIDAD = True` (ver sección 2) en vez de tocar código. |
| Cama mixta con SKUs de niveles distintos (ej. Licores + Merch), ¿qué nivel de apilado le corresponde? | **El más restrictivo (el más alto).** Una cama Licores+Merch se trata como Merch: no recibe nada encima. Ver sección 5.3 para el caso límite (mezclar nivel 1 con NABs/remate), que quedó como decisión abierta. |
| Tope de altura: ¿205 es el techo duro o hay un techo mayor? | **210 es el techo absoluto (`ALTURA_TOPE_DURO`), 205 es el máximo normal (`ALTURA_TOTAL_MAX`).** Un pallet que ya superó el mínimo (190) se corta en 205. Uno que todavía no llega al mínimo puede estirarse hasta 210 con tal de cerrar. Nunca se supera 210. |

---

## 1. YA APLICADO — verificar contra el repo, no reaplicar

Rama `feat/parametros-altura-peso-v2`, 3 archivos tocados. Esto es lo que ya quedó en el código:

### 1.1 `config.py`

- Ventana de altura reescrita con 5 constantes en vez de 2:
  `ALTURA_TOTAL_MIN=190`, `ALTURA_OBJETIVO_MIN=195`, `ALTURA_OBJETIVO_MAX=200`, `ALTURA_TOTAL_MAX=205`, `ALTURA_TOPE_DURO=210`.
- `ALTURA_TOLERANCIA_MIN = 5` (el margen para cajas altas) — **agregada pero todavía no consumida en ningún lado** (ver sección 3, falta `ALTURA_TOTAL_MIN_TOLERADO` y su uso).
- `ALTURA_PRODUCTO_MIN` / `ALTURA_PRODUCTO_MAX` ahora se derivan de las constantes de arriba en vez de estar hardcodeadas (`= ALTURA_TOTAL_MIN - ALTURA_PALLET_VACIO` y `= ALTURA_TOPE_DURO - ALTURA_PALLET_VACIO`). Esto sube el máximo de altura de **caja individual** aceptada de 180,08 a 195,08 cm — deliberado: V5 (validación de altura de caja) no debería excluir un SKU que sí podría entrar en el caso extremo de 210 cm total. Si se prefiere que V5 sea más estricta y use el máximo normal (205) en vez del tope duro, cambiar `ALTURA_PRODUCTO_MAX = ALTURA_TOTAL_MAX - ALTURA_PALLET_VACIO` — es una sola línea, marcada con comentario en el archivo.
- Peso: `PESO_ALERTA_KG = 1400`, `PESO_MAX_PALLET_KG = 1400`, `PESO_TOPE_ELASTICO_KG = 1430` (constante nueva, **todavía no consumida** — ver sección 3, bug importante).
- `PESO_UMA_ES_POR_UNIDAD = False` (flag nuevo, con el comentario de la evidencia).
- `NIVEL_REMATE = 7` y función `nivel_de_categoria(categoria)` nuevos — dan un nivel numérico único (1–7) a **cualquier** categoría, incluido el remate (antes el remate no tenía nivel, era `None`, y se manejaba por una rama de código aparte). Esto es lo que permite comparar niveles cuando una cama mezcla categorías (punto 6).
- Punto 4 (NABs/Nabs): **ya estaba resuelto**, no hizo falta tocar nada. `normalizar_categoria` saca acentos, hace `strip().lower()` y busca contra un mapa armado desde `CATEGORIAS_CONOCIDAS` — "Nabs", "NABS", "nabs " todos normalizan a `"NABs"`. Confirmado corriendo el validador contra el Excel real: la única fila con casing distinto pasa V1 sin generar log de "categoría no clasificada".

### 1.2 `models.py` (`Cama`)

Se agregaron 4 properties nuevas a `Cama`, pensadas para reemplazar los usos de `cama.categoria` (que ahora **falla a propósito** si la cama tiene más de una categoría — antes asumía en silencio `categorias[0]`):

- `nivel_efectivo` → nivel MÁS ALTO (más restrictivo) entre los SKUs de la cama. Es el nivel que se usa para decidir en qué pasada del Paso 4 se coloca la cama.
- `nivel_minimo` → nivel más bajo (menos restrictivo) — usado por `es_flexible`.
- `categoria_remate` → la categoría de remate presente en la cama (`"Comestibles"`, `"Cigarros"` o `None`). Revienta si encuentra ambas a la vez (no debería pasar nunca, ver regla 9.3 y sección 4.2).
- `es_flexible` → True solo si **todos** los SKUs de la cama son NABs o remate (nivel ≥ 6). Reemplaza al viejo `_es_flexible(cama)` de `apilado_3d.py`, que asumía `cama.categoria in (...)`.

### 1.3 `src/derivados.py`

- `Peso_Caja` ahora respeta `config.PESO_UMA_ES_POR_UNIDAD`: si es `False` (default), `Peso_Caja = "Peso bruto por unidad"` directo; si es `True`, `Peso_Caja = "Peso bruto por unidad" × "Unidades por caja"` (comportamiento viejo).
- `Nivel_Categoria` ahora sale de `config.nivel_de_categoria(...)` en vez de buscar el índice en `ORDEN_CATEGORIAS` a mano — el remate ya no queda en `None`.

**Verificación rápida de que esto está aplicado:**
```bash
git diff main -- config.py models.py src/derivados.py | head -5   # no debe estar vacío
python3 -c "import config; print(config.ALTURA_TOTAL_MAX, config.PESO_TOPE_ELASTICO_KG)"  # 205 1430
```

---

## 2. Bug encontrado — `validacion.py` duplica el cálculo de `Peso_Caja` con la fórmula VIEJA

**Severidad: alta. Sin este fix, el punto 5 queda aplicado a medias.**

`derivados.py` ya respeta `PESO_UMA_ES_POR_UNIDAD`, pero `src/validacion.py` (V6, "peso por caja dentro de un rango sano") calcula el peso **por su cuenta**, con la fórmula vieja, sin mirar el flag:

```python
# src/validacion.py, línea ~97 — TAL CUAL ESTÁ HOY
peso_caja = df["Peso bruto por unidad"] * df["Unidades por caja"]
fuera_rango = peso_caja.isna() | (peso_caja < config.PESO_CAJA_MIN) | (peso_caja > config.PESO_CAJA_MAX)
```

Esto significa que V6 va a marcar `⚠ PESO NO VALIDABLE` en SKUs completamente normales (porque su cálculo interno los infla igual que antes), mientras que el peso que realmente se usa en el Paso 4/5 (vía `derivados.Peso_Caja`) es el correcto. Los dos números divergen silenciosamente.

**Fix — extraer un helper compartido en `derivados.py` y usarlo en los dos lugares:**

```python
# src/derivados.py — agregar, exportado para que validacion.py lo importe
def calcular_peso_caja(peso_bruto_por_unidad: pd.Series, unidades_por_caja: pd.Series) -> pd.Series:
    if config.PESO_UMA_ES_POR_UNIDAD:
        return peso_bruto_por_unidad * unidades_por_caja
    return peso_bruto_por_unidad
```

```python
# src/derivados.py — dentro de calcular_derivados(), reemplazar el if/else por:
df["Peso_Caja"] = calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])
```

```python
# src/validacion.py — reemplazar la línea de peso_caja por:
from src import derivados  # cuidado con import circular: validacion no debería importar derivados
                             # si lo hay, mover calcular_peso_caja a config.py en su lugar
peso_caja = derivados.calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])
```

Revisar el orden de imports en `pipeline.py` (`validacion` se llama antes que `derivados`) — si mover la función a `derivados.py` genera import circular, la alternativa más simple es moverla directo a `config.py` como función pura (no depende de nada más que del flag) y que ambos módulos la importen desde ahí.

---

## 3. Bug encontrado — la elasticidad de peso (1.430) y el margen de altura (185) existen en `config.py` pero no se usan en ningún lado

**Severidad: alta. Es la causa principal de por qué el pipeline hoy da 157 pallets, todos parciales (ver sección 6, baseline medido).**

### 3.1 Peso — `apilado_3d._cabe` bloquea en 1.400, no en 1.430

```python
# src/apilado_3d.py, línea 92 — TAL CUAL ESTÁ HOY
if pallet.peso_estimado + _peso_cama(cama, info_sku) > config.PESO_MAX_PALLET_KG + 1e-9:
    return False
```

Con `PESO_MAX_PALLET_KG = 1400` esto es un techo duro en 1.400, sin usar nunca la elasticidad de 1.430 que pidió Omar. El patrón correcto (igual al de altura): **1.400 es el umbral de alerta** (Paso 5, ya funciona bien en `validacion_peso.py`), **1.430 es el techo real que bloquea** en el Paso 4.

**Fix:**
```python
# src/apilado_3d.py — _cabe(), cambiar la constante usada
if pallet.peso_estimado + _peso_cama(cama, info_sku) > config.PESO_TOPE_ELASTICO_KG + 1e-9:
    return False
```

`config.PESO_MAX_PALLET_KG` queda sin uso después de este cambio — o se elimina, o se deja como alias de `PESO_TOPE_ELASTICO_KG` para no romper imports externos. Revisar `tests/test_invariantes.py` línea 177, que lo referencia.

### 3.2 Altura — falta la constante `ALTURA_TOTAL_MIN_TOLERADO` y su uso

`ALTURA_TOLERANCIA_MIN = 5` está en `config.py` pero nada la usa todavía. Agregar la constante derivada:

```python
# config.py — agregar junto a ALTURA_TOLERANCIA_MIN
ALTURA_TOTAL_MIN_TOLERADO = ALTURA_TOTAL_MIN - ALTURA_TOLERANCIA_MIN  # 185
```

Y reemplazar **todos** los usos de `config.ALTURA_TOTAL_MIN` que deciden si un pallet es `⚠ PALLET PARCIAL` o si entra al proceso de consolidación (sección 5.4) por `config.ALTURA_TOTAL_MIN_TOLERADO`. Un pallet que quedó en 187 cm (por ejemplo, porque su última cama fue de una caja muy alta y no había forma de llegar exacto a 190) **no** debe marcarse parcial ni intentar vaciarse — 187 ≥ 185 es tolerable. Ubicaciones exactas en la sección 5.

### 3.3 Regla de cierre elástico (185 → hasta 210, nunca más)

Esto todavía no existe en ningún lado del código — es la regla nueva que pidió Omar explícitamente ("si estoy en 185 y agregar una cama implica llegar a 208-210 está bien, pero si supera eso no se agrega"). Va en `apilado_3d._cabe`, reemplazando el chequeo de altura actual:

```python
# src/apilado_3d.py — TAL CUAL ESTÁ HOY (línea 89)
if cama.altura_cama > config.ALTURA_TOTAL_MAX - pallet.altura_final + 1e-9:
    return False
```

```python
# PROPUESTA — nueva función + cambio en _cabe
def _limite_altura(pallet: Pallet) -> float:
    """Tope de altura para la PRÓXIMA cama que se intente colocar sobre `pallet`.

    Si el pallet YA alcanzó el mínimo tolerado (185), se corta en el máximo
    normal (205) — no seguir apilando solo porque "cabe hasta 210".
    Si el pallet TODAVÍA no llegó a 185, se le da margen hasta el tope duro
    (210) para que una última cama de remanente pueda cerrarlo, en vez de
    dejarlo parcial por 2-3 cm.
    """
    if pallet.altura_final >= config.ALTURA_TOTAL_MIN_TOLERADO:
        return config.ALTURA_TOTAL_MAX       # 205
    return config.ALTURA_TOPE_DURO           # 210


def _cabe(pallet: Pallet, cama: Cama, info_sku: dict[str, dict]) -> bool:
    if cama.altura_cama > _limite_altura(pallet) - pallet.altura_final + 1e-9:
        return False
    if pallet.peso_estimado + _peso_cama(cama, info_sku) > config.PESO_TOPE_ELASTICO_KG + 1e-9:
        return False
    return _puede_soportar(pallet)
```

Con esto: un pallet en 185 puede recibir una cama de hasta 25 cm (185+25=210); un pallet en 192 (ya sobre el mínimo tolerado) solo puede recibir hasta 13 cm más (192+13=205). Exactamente la regla que pidió Omar.

---

## 4. Punto 6 — Agrupar camas por dimensión, no por categoría (`src/packing_2d.py`)

### 4.1 Qué cambia

`generar_camas` hoy agrupa primero por `Categoria_Normalizada` y recién dentro de cada categoría clusteriza por altura:

```python
# src/packing_2d.py, línea 234 — TAL CUAL ESTÁ HOY
def generar_camas(df_remanente: pd.DataFrame) -> dict[str, list[Cama]]:
    camas_por_cd: dict[str, list[Cama]] = {}
    for cd, df_cd in df_remanente.groupby("CD"):
        camas_por_cd[cd] = []
        for _categoria, df_categoria in df_cd.groupby("Categoria_Normalizada"):
            rows = df_categoria.to_dict("records")
            for cluster in _clusterizar_por_altura(rows):
                camas_por_cd[cd].extend(_procesar_cluster(cluster))
    return camas_por_cd
```

Hay que sacar el `groupby("Categoria_Normalizada")` — el clustering por altura (`_clusterizar_por_altura`, tolerancia ±3 cm) pasa a correr sobre **todo el remanente del CD**, cruzando categorías. `_procesar_cluster` y `_capacidad_real_cama` no necesitan cambios: ya operan por SKU individual (el techo de densidad y la fase de "camas puras primero" son por SKU, no por categoría), así que siguen funcionando igual.

### 4.2 Guard obligatorio — Comestibles y Cigarros no pueden terminar en la misma cama

Sacar el agrupamiento por categoría no puede romper la regla 9.3 (remate mutuamente excluyente — ni siquiera pueden compartir cama, mucho menos pallet). En la práctica esto casi no debería activarse nunca: la altura promedio de caja de Cigarros es 55,5 cm contra 20,5 cm de Comestibles, muy por fuera de la tolerancia de clustering de 3 cm — pero es un guard de seguridad, no algo para omitir.

```python
# src/packing_2d.py — función nueva, se llama después de _clusterizar_por_altura
def _separar_por_remate(cluster_rows: list) -> list[list]:
    """Evita que Comestibles y Cigarros terminen en la misma cama (regla 9.3).
    Estructuralmente casi no debería ocurrir (ver alturas promedio en el doc de
    diseño, sección 9.3) porque el cluster de altura ya las separa solo. Esto es
    la red de seguridad explícita, no el camino esperado."""
    comestibles = [r for r in cluster_rows if r["Categoria_Normalizada"] == "Comestibles"]
    cigarros = [r for r in cluster_rows if r["Categoria_Normalizada"] == "Cigarros"]
    resto = [r for r in cluster_rows if r["Categoria_Normalizada"] not in ("Comestibles", "Cigarros")]

    if not (comestibles and cigarros):
        return [cluster_rows]

    # No pueden convivir. El "resto" (categorías no-remate) no se puede duplicar
    # entre dos sub-clusters sin fabricar cajas de más, así que se ancla al grupo
    # de remate con más cajas remanentes pendientes.
    pend_comestibles = sum(r["Cajas_Remanente"] for r in comestibles)
    pend_cigarros = sum(r["Cajas_Remanente"] for r in cigarros)
    if pend_comestibles >= pend_cigarros:
        return [resto + comestibles, cigarros]
    return [resto + cigarros, comestibles]
```

```python
# src/packing_2d.py — generar_camas reescrita
def generar_camas(df_remanente: pd.DataFrame) -> dict[str, list[Cama]]:
    camas_por_cd: dict[str, list[Cama]] = {}
    for cd, df_cd in df_remanente.groupby("CD"):
        camas_por_cd[cd] = []
        rows = df_cd.to_dict("records")
        for cluster in _clusterizar_por_altura(rows):
            for subcluster in _separar_por_remate(cluster):
                camas_por_cd[cd].extend(_procesar_cluster(subcluster))
    return camas_por_cd
```

### 4.3 `_cama_desde_colocacion` — el nivel de la cama debe ser el más restrictivo, no "el del primer SKU"

```python
# src/packing_2d.py, línea 120 — TAL CUAL ESTÁ HOY (bug latente: nivel arbitrario)
nivel = info[next(iter(colocadas_positivas))]["Nivel_Categoria"]
```

`next(iter(...))` toma el nivel de un SKU cualquiera de la cama — con camas de una sola categoría esto era inofensivo (todos tenían el mismo nivel), pero con camas mixtas es un bug: hay que tomar el más alto (más restrictivo), coherente con la decisión de la sección 0 y con `Cama.nivel_efectivo` ya definida en `models.py`.

```python
# FIX
nivel = max(info[sku]["Nivel_Categoria"] for sku in colocadas_positivas)
```

(Esto deja `Cama.nivel_efectivo`, calculada desde `categorias`, y el campo guardado `Cama.nivel_categoria`, calculado acá, diciendo lo mismo — es intencional, son dos caminos al mismo número, sirve como chequeo cruzado en tests.)

---

## 5. `src/apilado_3d.py` — dejar de asumir una sola categoría por cama

Todo este módulo asume hoy `cama.categoria` (singular, revienta con camas mixtas desde que se aplicó `[PARCHE P7]`). Con el punto 6 aplicado, las camas mixtas van a ser el caso común, no la excepción. Cambios función por función:

### 5.1 `_agrupar_camas`

```python
# TAL CUAL ESTÁ HOY (línea 28) — usa cama.nivel_categoria (0-6) y cama.categoria (revienta si es mixta)
def _agrupar_camas(lista_camas: list[Cama]) -> tuple[dict[int, list[Cama]], dict[str, list[Cama]]]:
    camas_por_nivel: dict[int, list[Cama]] = {n: [] for n in range(1, 7)}
    camas_remate: dict[str, list[Cama]] = {cat: [] for cat in config.CATEGORIAS_REMATE}
    for cama in lista_camas:
        if cama.nivel_categoria is not None:
            camas_por_nivel[cama.nivel_categoria].append(cama)
        else:
            camas_remate.setdefault(cama.categoria, []).append(cama)  # [P7]
    return camas_por_nivel, camas_remate
```

```python
# PROPUESTA
def _agrupar_camas(lista_camas: list[Cama]) -> tuple[dict[int, list[Cama]], dict[str, list[Cama]]]:
    n_niveles_base = len(config.ORDEN_CATEGORIAS)  # 6: incluye NABs
    camas_por_nivel: dict[int, list[Cama]] = {n: [] for n in range(1, n_niveles_base + 1)}
    camas_remate: dict[str, list[Cama]] = {cat: [] for cat in config.CATEGORIAS_REMATE}
    for cama in lista_camas:
        nivel = cama.nivel_efectivo
        if nivel == config.NIVEL_REMATE:
            camas_remate.setdefault(cama.categoria_remate, []).append(cama)
        elif nivel is not None:
            camas_por_nivel[nivel].append(cama)
        # nivel is None no debería pasar: toda cama viene de SKUs ya
        # clasificados por Paso 0/9.1; si pasa, es un bug upstream, no silenciarlo
    return camas_por_nivel, camas_remate
```

### 5.2 `_es_flexible`, `_remate_de`, `_remate_compatible`, `_peso_cama` (sin cambios)

```python
# _es_flexible — delegar al model en vez de asumir cama.categoria
def _es_flexible(cama: Cama) -> bool:
    return cama.es_flexible


# _remate_de — usar cama.categoria_remate (funciona en camas puras y mixtas)
def _remate_de(pallet: Pallet) -> str | None:
    for cama in pallet.camas:
        cr = cama.categoria_remate
        if cr is not None:
            return cr
    return None


# _remate_compatible — cambia de firma: recibe la CAMA en vez de un string suelto,
# porque ahora necesita cama.categoria_remate (que puede ser None en una cama
# mixta NABs + nivel bajo, y eso también es información válida)
def _remate_compatible(pallet: Pallet, cama: Cama) -> bool:
    cr = cama.categoria_remate
    if cr is not None:
        actual = _remate_de(pallet)
        return actual is None or actual == cr
    return _remate_de(pallet) is None
```

`_peso_cama` no cambia (ya opera por SKU vía `cama.cantidades`, es agnóstico a categoría).

### 5.3 ⚠ DECISIÓN ABIERTA — mezclar niveles muy separados (ej. Licores nivel 1 + NABs nivel 6)

Esto es nuevo respecto a lo que se le preguntó a Omar. La pregunta que se le hizo (Licores + Merch, niveles 1 y 5) ya la resolvió con "nivel más restrictivo". Pero el agrupamiento por dimensiones puede producir, en teoría, una cama que combine **Licores (nivel 1, la base, la más pesada) con NABs (nivel 6, casi la cima)** si sus cajas coinciden en altura ±3 cm. Con la regla "nivel más restrictivo", esa cama sube a la posición de NABs — es decir, cajas de vidrio pesadas terminan cerca de la cima del pallet en vez de en la base, que es exactamente lo que la sección 9 del doc de diseño quiere evitar (el orden Licores→Merch existe *por peso*, no solo por fragilidad).

No se implementó una regla para esto porque es una decisión de negocio, no un bug. Tres formas de resolverlo, de más simple a más precisa — recomiendo la B:

- **A — no limitar nada.** Dejar que "nivel más restrictivo" aplique siempre, sin importar cuán separados estén los niveles. Más densidad, riesgo real de cajas pesadas mal ubicadas si la geometría lo permite.
- **B (recomendada) — tope de separación de niveles dentro de un mismo cluster de altura.** Si dos categorías del cluster están a más de N niveles de distancia (ej. `abs(nivel_a - nivel_b) > 2`), no se mezclan en la misma cama — se procesan como sub-clusters separados (mismo patrón que `_separar_por_remate`, sección 4.2, generalizado). Con N=2 se permite Licores+Lácteos+Aseo entre sí, o Importados+Merch+NABs entre sí, pero no Licores+NABs.
- **C — excluir NABs y remate de la mezcla con niveles 1–5 directamente**, conservando el punto 6 solo para los niveles 1-5 entre sí (que es donde vive casi toda la demanda de julio: 174 SKUs, ninguno NABs en cantidad relevante). Es lo más conservador y lo que menos se aleja del comportamiento ya validado.

Pedirle a Omar que elija A/B/C (o un N distinto si elige B) antes de tocar `packing_2d._clusterizar_por_altura` o `_separar_por_remate`. Mientras tanto, implementar el punto 6 tal cual está en la sección 4 (sin este límite) es razonable para un primer corte, pero **hay que loguearlo como pendiente**, no como resuelto.

### 5.4 `_cabe`, `_limite_altura` → ya cubierto en sección 3.3

### 5.5 `_consolidar_pallets` y el resto de los usos de `ALTURA_TOTAL_MIN`

Todos estos deben pasar de `config.ALTURA_TOTAL_MIN` a `config.ALTURA_TOTAL_MIN_TOLERADO` (185), porque están decidiendo "¿este pallet quedó corto?", que es exactamente donde aplica el margen de ±5 cm:

| Archivo:línea | Qué hace hoy | Cambiar a |
|---|---|---|
| `apilado_3d.py:164` | `pequenos = [p for p in pallets_cd if p.altura_final < config.ALTURA_TOTAL_MIN]` | `< config.ALTURA_TOTAL_MIN_TOLERADO` |
| `apilado_3d.py:171` | `if origen.altura_final >= config.ALTURA_TOTAL_MIN: continue` | `>= config.ALTURA_TOTAL_MIN_TOLERADO` |
| `apilado_3d.py:211` | estado `PARCIAL` si `origen.altura_final < config.ALTURA_TOTAL_MIN` | `< config.ALTURA_TOTAL_MIN_TOLERADO` |
| `apilado_3d.py:266` | estado `PARCIAL` si `pallet.altura_final < config.ALTURA_TOTAL_MIN` | `< config.ALTURA_TOTAL_MIN_TOLERADO` |
| `apilado_3d.py:194` (`candidato.altura_final >= altura_referencia`) | sin cambio — esto compara pallets entre sí, no contra el mínimo global | — |

También reemplazar los dos usos de `categoria = cama.categoria` en `_consolidar_pallets` (línea 188) por el nuevo patrón de la sección 5.2: llamar directo `_remate_compatible(candidato, cama)` sin extraer la categoría antes.

---

## 6. `src/pallets_homogeneos.py` y `src/validacion.py` — no necesitan cambios de lógica, solo heredan las constantes nuevas

- `pallets_homogeneos.py` línea 39 (`if altura_final > config.ALTURA_TOTAL_MAX: continue`) ya lee `config.ALTURA_TOTAL_MAX`, que ahora vale 205 en vez de 195 — sube automáticamente el umbral para armar un pallet homogéneo sin tocar código. **Decisión implícita a confirmar con Omar:** un pallet homogéneo se construye de una sola vez desde `Camas por PH × Alto de caja`, no incrementalmente — ¿debería poder usar el tope duro (210) como los pallets mixtos, o quedarse en el máximo normal (205)? Se dejó en 205 (hereda `ALTURA_TOTAL_MAX` sin cambios) porque la elasticidad de 210 está pensada para "cerrar un pallet que quedó corto", y un homogéneo nunca queda corto — se arma completo o no se arma (ver la nota `[PARCHE P9]` en el archivo). Si Omar quiere que también use el tope duro, es una sola línea.
- `validacion.py` V5 (altura de caja) ya lee `config.ALTURA_PRODUCTO_MAX`, que ahora deriva de `ALTURA_TOPE_DURO` (205,08 → 195,08 cm) — sube automáticamente el límite de altura de caja individual aceptada. Sin cambios de código, salvo el fix de V6 de la sección 2.

---

## 7. Tests que van a romper — y por qué eso está bien

Correr `pytest -x` después de cada sección (2 a 5) para verlos caer uno por uno, no todos juntos:

| Test | Por qué rompe | Qué hacer |
|---|---|---|
| `tests/test_topado_homogeneos.py:32` — `assert altura_base < 185` | El literal `185` quedó de la ventana vieja (185-195). Con la ventana nueva, un pallet homogéneo puede legítimamente superar 185. | Cambiar el literal por `config.ALTURA_TOTAL_MAX` o el valor concreto que corresponda al caso de test — revisar qué caso arma el fixture antes de tocar el assert a ciegas. |
| `tests/test_apilado_3d.py:58` — `assert pallets[0].altura_final < config.ALTURA_TOTAL_MIN` | Ya usa la constante (bien), pero el *fixture* del test probablemente arma un pallet pensado para quedar "parcial" bajo la ventana vieja (185-195); con 190 de mínimo puede que ahora sí llegue a cerrar. | Revisar el fixture, no solo el assert. |
| `tests/test_invariantes.py:109-113` — docstring dice "195 cm" y compara contra `ALTURA_TOTAL_MAX + 1e-6` | El docstring queda desactualizado (205, no 195) pero el assert en sí sigue siendo válido porque usa la constante. | Actualizar el docstring nomás. |
| `tests/test_invariantes.py:177` — compara contra `config.PESO_MAX_PALLET_KG` | Si en la sección 3.1 se elimina `PESO_MAX_PALLET_KG` en vez de dejarlo como alias, este test no compila. | Decidir alias vs. eliminar antes de tocar este archivo; si se elimina, el test debe pasar a comparar contra `PESO_TOPE_ELASTICO_KG`. |
| `tests/test_pipeline_real_data.py:19` — `assert (alturas <= config.ALTURA_TOTAL_MAX).all()` | Sigue siendo válido (la restricción dura del Paso 4 nunca debe superar el máximo normal salvo el caso de cierre elástico) — **pero** con el cambio de la sección 3.3, un pallet SÍ puede terminar por encima de 205 (hasta 210) si se cerró en modo elástico. Este assert hoy asume que 205 es un techo absoluto. | Cambiar el assert a `<= config.ALTURA_TOPE_DURO` y, ojalá, agregar un segundo assert que cuente cuántos pallets superaron `ALTURA_TOTAL_MAX` (debería ser un número chico — son los cierres forzados, no la mayoría). |

Ningún test de estos debe "arreglarse" bajando el assert a lo que da el código roto — son señales de que la ventana de altura vieja estaba cableada en los tests, no en el diseño.

---

## 8. Plan de validación — antes/después

El pipeline hoy (commit `4798daa`, sin ninguno de estos cambios) corre así contra `Cubicaje18.07.2026.xlsx` — **guardar estos números como baseline, correr la misma medición después de cada sección**:

```
Pallets: 157
Altura   min 23.7 | prom 40.7 | max 106.4 cm
Peso     min 0.0  | prom 2942.4 | max 31000.0 kg
Parciales (<190 viejo): 157 de 157  (100%)
Estados: 9 solo-parcial, 109 parcial+peso-no-validable+alerta-peso,
         38 parcial+peso-no-validable, 1 parcial+alerta-peso
Cajas esperadas 1464 | en el plan 1460 | perdidas 4 (revisar V4/V5 antes de asumir que está bien)
```

**Diagnóstico de por qué el baseline es tan malo — confirma que las secciones 2 y 3 son las que más impacto tienen:** con la fórmula vieja de peso (peso unitario × unidades), el peso mediano por **cama** ya da 1.646 kg — 110 de 167 camas superaban el tope de 1.350/1.400 kg **solas**, antes de intentar combinarlas con nada más. Resultado: 148 de 157 pallets tienen una sola cama, porque casi ninguna segunda cama entraba bajo el tope de peso. Arreglar la sección 2 (peso real de UMA) debería tirar el peso mediano por cama a ~180 kg y dejar que el Paso 4 empiece a combinar camas de verdad.

```bash
cd agente-cubicador-transportes-bees
python3 -c "
import sys; sys.path.insert(0, '.')
import config
from src import pipeline
r = pipeline.ejecutar_desde_archivo('Cubicaje18.07.2026.xlsx')
pl = [p for p in r.pallets if not p.id.startswith('SIN-ASIGNAR')]
alt = [p.altura_final for p in pl]; pes = [p.peso_estimado for p in pl]
print(f'Pallets: {len(pl)}')
print(f'Altura  min {min(alt):.1f} | prom {sum(alt)/len(alt):.1f} | max {max(alt):.1f}')
print(f'Peso    min {min(pes):.1f} | prom {sum(pes)/len(pes):.1f} | max {max(pes):.1f}')
print(f'Parciales (<{config.ALTURA_TOTAL_MIN_TOLERADO}): {sum(1 for a in alt if a < config.ALTURA_TOTAL_MIN_TOLERADO)}')
print(f'Sobre tope duro (>{config.ALTURA_TOPE_DURO}): {sum(1 for a in alt if a > config.ALTURA_TOPE_DURO + 1e-6)}')
print(f'Camas por pallet, mediana: {sorted(len(p.camas) for p in pl)[len(pl)//2]}')
"
pytest -q
```

Métricas a comparar baseline vs. final: número de pallets totales (debería bajar bastante — más densidad por pallet), % de pallets parciales (debería bajar mucho), altura promedio (debería subir hacia la zona 195-200), pallets con una sola cama (debería bajar), cajas perdidas (debe seguir en 0 o el mismo número explicado por V4/V5, nunca subir).

---

## 9. Checklist de aceptación

- [ ] Sección 1 verificada (ya aplicada) — `config.py`, `models.py`, `src/derivados.py`
- [ ] Sección 2 — `Peso_Caja` calculado una sola vez, mismo resultado en `validacion.py` y `derivados.py`
- [ ] Sección 3.1 — `_cabe` bloquea en 1.430, no en 1.400
- [ ] Sección 3.2 — `ALTURA_TOTAL_MIN_TOLERADO` (185) agregada y usada en vez de `ALTURA_TOTAL_MIN` donde corresponde (tabla de la sección 5.5)
- [ ] Sección 3.3 — `_limite_altura` implementada; un pallet bajo 185 puede cerrar hasta 210, uno sobre 185 tope 205
- [ ] Sección 4 — `packing_2d.generar_camas` agrupa por altura cruzando categorías; `_separar_por_remate` evita Comestibles+Cigarros en la misma cama; nivel de cama = el más restrictivo
- [ ] Sección 5.3 — decisión A/B/C tomada con Omar y aplicada (o explícitamente diferida con un TODO visible, no silenciada)
- [ ] Sección 5 — `apilado_3d.py` no usa `cama.categoria` en ningún lado salvo camas garantizadas puras
- [ ] Sección 7 — tests actualizados (no solo pasando, sino verificando lo correcto — ver columna "qué hacer")
- [ ] Sección 8 — benchmark corrido antes/después, números documentados en el PR
- [ ] Punto 4 (NABs/Nabs) — confirmado que ya estaba resuelto, sin cambios de código necesarios
