# Documentación lógica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** post V3 + parches V4/V4b/V4c
**Alcance:** qué reglas de negocio implementa el motor, por qué, y con qué evidencia se calibró cada una.

> Este documento reemplaza `DOCUMENTACION_LOGICA_V3.md`. El detalle de código/módulos está en `DOCUMENTACION_TECNICA.md`.

---

## 0. Prioridad de reglas

Cuando dos reglas compiten, en este orden:

1. **La demanda se despacha exacta** (o con la política de redondeo explícita por categoría, sección 8) — nunca se pierde silenciosamente.
2. **Restricciones físicas/operacionales duras**: la única que queda como bloqueo real del armado es la **altura** del pallet (~190-215cm). Peso, soporte y orden de categorías son reportes/preferencias, no bloqueos (ver sección 1).
3. **Reproducir la operación real** cuando hay evidencia de cómo la hace (fotos de los 42 pallets reales, sección 2) — mezcla libre por geometría, no por jerarquía de categoría.
4. **Minimizar la cantidad de pallets** que hay que armar y mover, buscando la mejor forma geométrica para la demanda de cada CD.
5. Minimizar residuales (pallets parciales).
6. Maximizar aprovechamiento de altura.
7. Trazabilidad: toda geometría inferida/degradada/acostada queda marcada, nunca se inventa en silencio.

Este orden es explícito porque cambió respecto de V3: **el orden de categorías por nivel de estabilidad (Licores→Lácteos→...→remate) dejó de ser una restricción dura** — ver sección 1.

## 1. Qué es y qué no es una restricción dura (V4b)

Confirmado con Omar viendo las fotos de los 42 pallets reales (sección 2): los operarios arman pallets con **varias columnas de SKUs distintos, de altura independiente, lado a lado**, mezclando categorías (Licores, Comestibles, NABs, Lácteos...) libremente en distintos niveles del mismo pallet — no en capas uniformes ordenadas por "nivel de estabilidad" como asumía V3. La instrucción explícita fue: *"restringir solo el tamaño a un mínimo de 1.9 y un máximo de 2.15, buscando siempre la mejor forma geométrica en que entren las cajas necesarias para esa CD, con el fin de mover la menor cantidad de pallets"*.

| Regla | V3 | V4b (actual) |
|---|---|---|
| Altura del pallet (190-215cm) | Dura | **Dura** (única restricción dura de armado) |
| Peso máximo (1430kg) | Dura | Blanda — se calcula y alerta (`⚠ ALERTA DE PESO`), no bloquea (`config.PESO_ES_RESTRICCION_DURA=False`) |
| Orden por nivel de categoría (Licores antes que Comestibles, etc.) | Dura (3 pases separados) | **Retirada** — un solo pase de bin-packing, cualquier categoría con cualquier otra |
| NABs/remate aislados en su propia cama | Dura | Retirada |
| Un solo "remate" por pallet (Comestibles XOR Cigarros) | Dura | Retirada a nivel pallet (una caja BAT puede convivir con Comestibles en el mismo pallet, en camas distintas) — sigue dura a nivel de una **misma cama** (ver sección 15) |
| "Peso abajo, liviano arriba" | No existía | **Preferencia suave**: a igual altura de cama, la más pesada se procesa primero en el bin-packing y tiende a terminar más abajo — no se garantiza en todos los casos |
| BAT/Cigarros como caja de consolidación aparte, siempre al final | Dura | **Sigue dura**, sin cambios — confirmado explícitamente que esta regla no se toca al soltar el resto |
| Cajas siempre "de pie" | Dura para todas las categorías | Retirada para Comestibles/Cigarros (pueden acostarse si conviene, sección 7) — sigue dura para el resto (Licores, vidrio, Lácteos: riesgo de derrame/quiebre) |

Por qué se soltó el peso también: la instrucción de negocio fue explícita en restringir "solo el tamaño", y el propio parámetro de peso ya estaba marcado como no-validado desde V3 (`PESO_PARAMETROS_VALIDADOS=False`) — no había ninguna razón para tratarlo como más confiable que el orden de categorías, que sí se soltó.

## 2. El benchmark real: 42 pallets

Fuente: fotos de picking de operación real (7 zips de WhatsApp, ~130 fotos) — pallets etiquetados con CD y secuencia (ej. "CD Ate 1/3"), algunos marcados "HÍBRIDO". Patrón observado:

- Columnas de SKUs distintos, alturas independientes, lado a lado en el mismo pallet.
- Categorías mezcladas en casi todos los niveles (Licores, Comestibles, NABs conviviendo).
- Tendencia (no regla estricta) a poner botellas/Licores hacia la base.
- Pallets "HÍBRIDO" explícitos como un tipo reconocido por la operación.

`PALLET=0` en el dato real de referencia significa **pendiente de consolidación BAT**, no un pallet físico adicional — el benchmark de 42 excluye esas filas. El motor reproduce esto excluyendo los `PH-BAT-*` (pallets dedicados solo a cajas BAT) del conteo comparable contra el benchmark (`pipeline.py`, `pallets_comparables`).

> ⚠️ **No se pudo confirmar que los 42 pallets reales correspondan exactamente a la misma demanda de `Envios_Julio`** (ver `Parches/v4_cubicaje_mixto/PARCHES_V4.md`). Si el despacho real fue otro, 42 podría no ser el objetivo correcto para esta demanda específica — usar el número como referencia de forma/altura, no como cifra a igualar a cualquier costo.

## 3. Ventana de altura (190-215cm)

| Zona | Rango | Estado de reporte |
|---|---|---|
| Óptimo | 195-200 | OK |
| Nominal | 190-195 | OK |
| Alto pero operativo | 200-210 | OK |
| Tolerado | 185-190 | TOLERADO |
| Excepción | 210-215 | ⚠ ALTURA EXCEPCIONAL |
| Parcial operativo | 170-185 | ⚠ PALLET PARCIAL |
| Residual | <170 | ⚠ PALLET PARCIAL |
| No permitido | >215 | (el armado no debería dejar llegar hasta acá) |

`ALTURA_TARGET=198.3` (promedio real) se usa como objetivo de scoring al elegir host BAT (minimizar `|altura_resultante - 198.3|`), no como un tope. Ninguno de estos números es un límite normativo validado (`ALTURA_HARD_VALIDADA=None`) — son el benchmark observado; `ALTURA_MAX_OBSERVADA=215` es el único tope que el motor usa operacionalmente para decidir cuándo dejar de apilar.

## 4. Peso — blando, no validado

`PESO_ALERTA_KG=1400` / `PESO_HARD_KG=1430` siguen existiendo como umbrales de **reporte** (`⚠ ALERTA DE PESO` en el estado del pallet), pero desde V4b ya no bloquean el armado (`PESO_ES_RESTRICCION_DURA=False`). Motivo: no están validados contra capacidad real de montacargas/rack/transporte (heredados de un ajuste que daba buenos resultados en el modelo, no de una norma), y la instrucción de negocio fue explícita en que la única restricción dura es el tamaño.

## 5. Reconciliación geométrica Maestro↔UMA

Regla central: el Maestro (`Cajas por cama`) es la capacidad OPERACIONAL declarada; UMA (dimensiones medidas) valida la geometría. Si UMA contradice al Maestro, el sistema **no** reduce `Cajas por cama` automáticamente (eso era V2: `min(Maestro, geometría)` — la validación contra pallets reales mostró que el Maestro es más confiable que una grilla simple en la mayoría de los casos).

### 5.1 Estados posibles por SKU (`Fuente_Geometria`)

| Estado | Significado |
|---|---|
| `UMA_VALIDADA` | La geometría medida (parada o acostada) explica exactamente la capacidad del Maestro, o no hay techo declarado |
| `UMA_SOBRECAPACIDAD` | La geometría permite más de lo que el Maestro declara — se respeta el Maestro como techo, no se sube la densidad |
| `INFERIDA_MAESTRO` | El Maestro declara más de lo que la geometría medida explica, pero es plausible con el sobresaliente de negocio (2.5cm/lado) — se infiere un footprint compatible, geometría NO medida |
| `MAESTRO_IMPOSIBLE_DEGRADADO` | El Maestro declara algo geométricamente imposible incluso con sobresaliente — se degrada al techo geométrico real en vez de inventar una geometría ficticia |
| `DATO_INSUFICIENTE` | Sin Alto de caja, o sin Largo/Ancho — no hay geometría utilizable, el SKU no se puede empacar de forma segura |

### 5.2 Sobresaliente (2.5cm/lado)

La operación acepta que la caja sobresalga hasta 2.5cm por lado del pallet (más allá, pierde >20% de resistencia a la compresión por quedar la esquina sin apoyo). Área efectiva de validación: 125×105cm.

Uso: **solo** para juzgar si un dato del Maestro es creíble (`capacidad_xy_max_con_sobresaliente`, usado en el guard de `MAESTRO_IMPOSIBLE_DEGRADADO`). **Nunca** para la geometría real de packing — si el motor planificara asumiendo sobresaliente en todos lados, dos camas que sobresalen en direcciones distintas darían un pallet con perfil irregular difícil de estibar y envolver. Es una decisión de negocio de *validación de datos*, no de *planificación*, todavía no confirmada para este segundo uso.

### 5.3 Cajas acostadas — Comestibles y Cigarros (V4c)

Confirmado viendo las fotos: la operación acuesta cajas de Comestibles y Cigarros para ahorrar espacio, no las deja siempre "de pie". Medido contra la demanda real: **44 de 47 SKUs de Comestibles (94%)** y 5 de 24 de Cigarros caben más cajas por cama acostados (una cara lateral como huella) que parados.

Regla: para SKUs de `CATEGORIAS_ROTACION_LIBRE = [Comestibles, Cigarros]`, se evalúan las 3 caras posibles como huella y se elige la orientación que **alcance el techo del Maestro con la menor altura de cama** (no la que dé más capacidad a secas — si el Maestro ya cap la densidad, acostar sin necesidad solo suma altura sin sumar cajas). Para el resto de las categorías (Licores, vidrio, Lácteos) se mantiene siempre parada — riesgo de derrame/quiebre.

Esto reemplaza, para estas 2 categorías, la hipótesis "cajas acostadas" que V3 había investigado y confirmado (explicaba 78% de los casos donde la geometría de pie daba menos que el Maestro) pero descartado del flujo productivo por romper el balance del packer viejo (basado en niveles de categoría). Con el packer V4b (mezcla libre, sin niveles) esa razón para no conectarla ya no aplica.

### 5.4 Solver de patrones mixtos (P1)

`capacidad_xy_max` prueba, además de las 2 grillas uniformes, patrones **mixtos** (una parte de la cama en una orientación, otra en la otra, vía cortes rectos recursivos) y **molinete** (patrón no guillotinable). Ejemplo verificable a mano: caja de 40×30cm en pallet de 120×100 — grilla A da 9, grilla B da 8, mixto da **10** (llena el pallet al 100% exacto). Medido contra la demanda real: en 108 de 183 SKUs el patrón mixto supera a la grilla uniforme (ganancia media +1.5 cajas/cama).

## 6. Demanda en unidades y política de redondeo

`ceil(Cajas Teóricas)` por línea puede sobre-despachar respecto de la demanda real. Política explícita por categoría:

- **BAT (Cigarros/vapes)**: `UNIDADES_EXACTAS` — se despacha la demanda real fraccionaria vía la caja de consolidación, nunca `ceil()` por SKU (redondear cada línea a caja completa inflaba la demanda real ~3.8x: 96% de las líneas de Cigarros son fraccionarias).
- **Resto de categorías**: `CAJA_COMPLETA` — sigue redondeando hacia arriba, pero el exceso que ese redondeo produce queda cuantificado (`Unidades_Exceso_Redondeo`), no se pierde en silencio.

## 7. BAT — Cigarros y vapes

Regla confirmada explícitamente como la única que se mantiene intacta al soltar el resto de las restricciones de categoría.

### 7.1 Caja de consolidación

45×24×55cm, hasta 500 unidades, contenido mixto de SKUs de Cigarros/vapes del mismo CD.

### 7.2 Secuencia operacional

1. Separar demanda BAT del resto (categoría logística explícita, `Cigarros`).
2. Cubicar TODOS los SKUs no-BAT primero, con el motor normal (mezcla libre).
3. Consolidar BAT por CD en unidades: `N_Cajas_BAT = ceil(Unidades_BAT_CD / 500)`.
4. Recién ahí, para cada caja BAT, elegir un pallet host del mismo CD ya armado.
5. Colocar la caja BAT como remate (última cama del pallet host).
6. Recalcular altura y peso final del host.

### 7.3 Selección de host — sin exclusividad de categoría (V4b)

Antes (V3): un pallet con Comestibles quedaba excluido de recibir BAT (regla "remate exclusivo"). Ahora: cualquier pallet del CD es candidato, en 4 niveles de esfuerzo creciente (natural → liberar espacio moviendo camas → apilar sobre un host existente → redistribuir el contenido del CD en un pallet más). Solo si NINGÚN nivel encuentra margen físico real se abre un pallet dedicado — y ese dedicado consolida TODAS las cajas BAT sobrantes del CD (varias por capa, varias capas), nunca un pallet nuevo por cada caja individual.

Score de host: minimizar `|altura_resultante - ALTURA_TARGET|` entre los candidatos viables.

## 8. Estados del pallet (`Estado`)

| Estado | Significado |
|---|---|
| `OK` | Altura en zona buena (óptimo/nominal/alto pero operativo), sin alertas |
| `TOLERADO` | Altura en zona tolerada (185-190cm) |
| `⚠ ALERTA DE PESO` | Peso estimado > 1400kg (no bloquea) |
| `⚠ PESO NO VALIDABLE` | Algún SKU del pallet tiene peso fuera de rango sano — el peso del pallet no es confiable |
| `⚠ PALLET PARCIAL` | Altura < 185cm (parcial operativo o residual) |
| `⚠ ALTURA EXCEPCIONAL` | Altura entre 210-215cm |
| `⚠ CATEGORÍA NO CLASIFICADA` | Algún SKU tiene una categoría que no normaliza a ninguna conocida |
| `⚠ DATO INSUFICIENTE` | Geometría insuficiente para empacar con seguridad (sin Alto de caja, o sin Largo/Ancho y sin techo del Maestro) |
| `⚠ REQUIERE REVISIÓN` | Estado de reserva para casos que el armado no debería producir |

Los estados se concatenan con ` + ` cuando aplican varios a la vez.

## 9. Invariantes duros (siguen sin excepción)

1. Nunca se mezcla demanda de dos CDs en el mismo pallet.
2. Nunca se pierde demanda en silencio — todo lo que no se puede clasificar/empacar queda en un pallet `Requiere Revisión` con su motivo, no desaparece.
3. La reconciliación de unidades es exacta: `Cajas_Totales_Pallet` para cualquier categoría no-BAT iguala `Cajas_Teoricas_Redondeadas`; BAT despacha entre la demanda real y la redondeada, nunca por encima de esta última.
4. Ninguna caja se solapa ni sobresale del pallet más allá de lo que la geometría efectiva permite (el sobresaliente de negocio es solo para *validar datos*, no para *planificar*).
5. Solo rotación XY para categorías fuera de `CATEGORIAS_ROTACION_LIBRE`; para Comestibles/Cigarros, además, las 2 orientaciones acostadas — nunca una cuarta orientación arbitraria.
6. La fórmula de altura es una sola (`ALTURA_PALLET_VACIO + suma de alturas de cama`) en todo el sistema, sin excepciones por tipo de pallet.
7. Toda geometría inferida, degradada o acostada queda marcada (`Fuente_Geometria`, `Geometria_Acostada`) — nunca se presenta como medición real sin avisar.
8. BAT consolidado no excede 500 unidades por caja física; nunca mezcla CDs.
9. `PALLET=0` (BAT pendiente) no cuenta como pallet físico en el benchmark.
10. BAT siempre queda como la última cama del pallet que lo recibe.
11. **Dentro de una misma cama**, Comestibles y Cigarros nunca conviven (`Cama.categoria_remate` revienta si pasa) — es un límite físico (una capa no puede ser dos cosas a la vez), distinto de la exclusividad a nivel pallet, que sí se retiró.
12. Un pallet inviable (sin geometría utilizable) queda como `⚠ DATO INSUFICIENTE`, nunca se fuerza una geometría inventada para empacarlo igual.
13. El armado es determinístico: misma demanda + misma config → mismo Excel de salida, corrida tras corrida (orden de iteración por CD explícitamente ordenado, no depende del hash de sets).

## 10. Qué NO resuelven los cambios actuales

Aun con mezcla libre, solver mixto, cajas acostadas y dimensiones corregidas, el modelo puede seguir sin igualar exactamente los 42 pallets reales — motivos conocidos, sin resolver:

- No se pudo confirmar que los 42 pallets reales sean de la misma demanda que `Envios_Julio` (sección 2).
- `ESTRATEGIA_CAMAS` documenta dos heurísticas alternativas no implementadas (`GLOBAL_MIX`, `HYBRID_LOOKAHEAD`) pensadas para reducir camas residuales de menos del 50% de la base — comparar heurísticas completas contra el benchmark real es un proyecto aparte.
- La preferencia "peso abajo" es un desempate suave, no una optimización real de qué va exactamente debajo de qué — no reproduce columnas independientes por SKU como se ve en las fotos, solo capas mixtas por altura similar.
