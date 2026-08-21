# Documentación lógica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `506285c` (2026-08-21) — único motor activo: **SKU_BLOQUE**. V4 (camas), V5 multi-start puro, AUTO, AUTO_CONSOLIDADO y SKU_CONSOLIDADO fueron borrados del repo (ver sección 15).
**Alcance:** qué reglas de negocio implementa el motor, por qué, y con qué evidencia se calibró cada una.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_LOGICA*.md`. El detalle de código/módulos está en `DOCUMENTACION_TECNICA.md`. El historial completo, patch por patch (incluidos los motores ya borrados), vive en `Parches/v5/PATCH_LOG.md` — no se repite acá, solo se resume.

---

## 0. Prioridad de reglas

Cuando dos reglas compiten, en este orden:

1. **La demanda se despacha exacta** (o con la política de redondeo explícita por categoría, sección 8) — nunca se pierde silenciosamente.
2. **Restricciones físicas/operacionales duras**: la altura (~190-215cm, sección 3) y la geometría (una torre no se sale del pallet, dos torres no se solapan) son las únicas que bloquean el armado. Peso, orden de categorías y estabilidad son reportes/preferencias, no bloqueos (ver sección 1).
3. **Cada SKU es un bloque indivisible mientras sea posible** (sección 10 — la instrucción de negocio más reciente, y la que le da nombre al motor: SKU_BLOQUE). "Cajas por PH" del Maestro es el máximo físicamente comprobado por operación para un pallet 100% de ese SKU; no es un número que el packer deba re-derivar ni recortar.
4. **Minimizar la cantidad de pallets** que hay que armar y mover, combinando bloques enteros de distintos SKUs para llegar a la altura óptima.
5. Partir un bloque (remanente) es el **último recurso**, no una estrategia general.
6. Trazabilidad: toda geometría inferida/degradada queda marcada, nunca se inventa en silencio; toda demanda que no logra colocarse queda en `sin_colocar`, nunca desaparece.

---

## 1. Qué es y qué no es una restricción dura

Confirmado con Omar viendo fotos de picking real: los operarios arman pallets con columnas de SKUs distintos, de altura independiente, lado a lado, mezclando categorías libremente. La instrucción de negocio fue explícita: restringir solo el tamaño (altura) y la geometría, y priorizar mover la menor cantidad de pallets posible.

| Regla | Estado |
|---|---|
| Altura del pallet (~190-215cm) | **Dura** — el único tope que decide cuándo dejar de apilar (`config.ALTURA_MAX_OBSERVADA`) |
| Geometría (overlap, overflow de la base) | **Dura** — auditada aparte por `src/validacion_v5.py`, no solo confiada al packer |
| Peso máximo (1430kg) | Blanda — se calcula y alerta (`⚠ ALERTA DE PESO` sobre 1400kg), nunca bloquea el armado (`config.PESO_ES_RESTRICCION_DURA` ya no existe como gate; el peso solo entra en `validacion_peso.py` como reporte) |
| Orden por nivel de categoría / estabilidad física | Retirada como restricción de armado — el packer no agrupa ni ordena por categoría. `Nivel_Categoria` sigue viajando como metadata informativa en el plan de picking |
| "SKU nunca repartido en más pallets de los necesarios" | **Dura**, dentro de lo geométricamente posible — ver sección 10 |
| BAT/Cigarros como caja de consolidación aparte | **Dura**, sin cambios — nunca se despacha por caja completa, ver sección 9 |
| Cajas siempre "de pie" | Dura para todas las categorías salvo Comestibles/Cigarros (pueden acostarse si conviene, sección 7) |

---

## 2. El benchmark real

Fuente original: fotos de picking de operación real (~130 fotos, 42 pallets físicos con categorías mezcladas en casi todos los niveles) y, más recientemente, `Plan de Movimientos - Pre Picking 18.08.xlsx` (demanda real de un día, 6 CDs, 48 pallets físicos armados por el hub, 0 dedicados BAT).

- **Benchmark de referencia principal**: 42 pallets físicos, altura media 198.3cm, rango 170-215cm (`src/benchmark.py`: `PALLETS_REALES=42`, `ALTURA_MEDIA_REAL=198.3`).
- **Gate formal** (`benchmark.evaluar_gate_v5`, `GATE_V5_PALLETS_MIN/MAX = 42/45`): para que un resultado se considere "a la par de la operación real" tiene que caer en ese rango de pallets, con demanda exacta, altura máxima dentro del tope real (215cm) y cero violaciones geométricas. Los cuatro criterios son obligatorios, ninguno se relaja para "hacer pasar" el benchmark.
- **Estado actual** (dataset `Cubicaje18.07.2026.xlsx`): **53 pallets**, 0 violaciones geométricas, demanda exacta, altura media 210.9cm. El gate **no aprueba** — única razón: `pallets=53, fuera del rango [42, 45]`. Ningún otro criterio falla.
- `PALET=0` en el dato real histórico significa "pendiente de consolidación BAT", no un pallet físico adicional — el benchmark de 42 ya lo excluye. El motor reproduce esto contando `PV5-BAT-*` (pallets dedicados solo a cajas BAT) como pallets físicos normales — nunca se esconden del conteo (a diferencia de una versión anterior del código que sí los excluía por error, corregido en la limpieza de sección 15).

> Ningún motor probado hasta ahora (V4 por camas, V5 multi-start, AUTO combinando ambos, SKU_CONSOLIDADO, SKU_BLOQUE) cerró la brecha contra 42-45 en el dataset grande — el mejor resultado medido en el historial fue AUTO con 48. SKU_BLOQUE se quedó como único motor **por decisión explícita de negocio** (la regla de "SKU nunca repartido" pesa más que el número puro de pallets), no porque sea el que más se acerca al gate. Ver sección 11 para el trade-off medido.

---

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

`ALTURA_TARGET=198.3` (promedio real) es una referencia de scoring, no un tope. Ninguno de estos números es un límite normativo validado (`config.ALTURA_HARD_VALIDADA=None`) — son el benchmark observado; `ALTURA_MAX_OBSERVADA=215` es el único tope que el motor usa operacionalmente para decidir cuándo dejar de apilar (`config.estado_altura`).

---

## 4. Peso — blando, no validado

`PESO_ALERTA_KG=1400` / `PESO_HARD_KG=1430` existen como umbrales de **reporte** (`validacion_peso.py` marca `⚠ ALERTA DE PESO` sobre 1400kg), pero no bloquean el armado en ningún punto del pipeline actual. Motivo documentado desde V4b y nunca revertido: no están validados contra capacidad real de montacargas/rack/transporte, y la instrucción de negocio fue explícita en que la única restricción dura de armado es el tamaño (altura + geometría).

---

## 5. Reconciliación geométrica Maestro↔UMA

Regla central (sin cambios desde V3): el Maestro (`Cajas por cama`) es la capacidad OPERACIONAL declarada; UMA (dimensiones medidas) valida la geometría. Si UMA contradice al Maestro, el sistema **no** reduce `Cajas por cama` automáticamente — el Maestro resultó más confiable que una grilla simple en la validación contra pallets reales.

### 5.1 Estados posibles por SKU (`Fuente_Geometria`)

| Estado | Significado |
|---|---|
| `UMA_VALIDADA` | La geometría medida (parada o acostada) explica exactamente la capacidad del Maestro, o no hay techo declarado |
| `UMA_SOBRECAPACIDAD` | La geometría permite más de lo que el Maestro declara — se respeta el Maestro como techo |
| `UMA_VALIDADA_CON_SOBRESALIENTE` | La geometría medida (sin cambiar largo/ancho) explica al Maestro solo si se permite el sobresaliente de negocio (2.5cm/lado) — se usa la medida real tal cual, no un footprint inventado |
| `MAESTRO_IMPOSIBLE_DEGRADADO` | El Maestro declara algo geométricamente imposible incluso con sobresaliente — se degrada al techo geométrico real en vez de inventar una geometría ficticia |
| `DATO_INSUFICIENTE` | Sin Alto de caja, o sin Largo/Ancho — el SKU no se puede empacar de forma segura, queda "Requiere Revisión" |

Regla explícita: **no sustituir una medición física por un footprint artificial si el dato operacional puede explicarse con el sobresaliente ya validado.** `inferir_footprint_desde_cajas_cama` (que inventa un largo/ancho distinto al medido) solo se llamaba en una versión anterior del código y quedó sin usar desde que se agregó el paso intermedio "sobresaliente con medida real" — se mantiene en el módulo por si hace falta, pero ningún caso del dataset real la alcanza hoy.

### 5.2 Sobresaliente (2.5cm/lado)

Cuánto puede volar la caja del borde del pallet antes de perder resistencia a la compresión (>20% más allá de ese margen). Medido sobre 458 SKUs remedidos: 0cm→73% del dato del Maestro alcanzable, 2.5cm→82% (elegido), 5cm→86% (fuera del estándar seguro).

Dos usos, con alcance distinto:

- **Validación de datos** (`reconciliacion_geometrica.capacidad_xy_max_con_sobresaliente`): siempre activo, decide si un "Cajas por cama" del Maestro es creíble.
- **Packing real**: por mucho tiempo quedó sin cablear (`SOBRESALIENTE_PLANIFICACION`, "decisión de negocio todavía no confirmada"). Se confirmó y aplicó, pero **solo para pallets 100% dedicados a un SKU** (`packing_bloques._dedicar_por_sku`, base extendida 125x105cm): un pallet dedicado usa una única orientación para todas sus cajas, así que el sobresaliente queda parejo de un solo lado. Los pallets mixtos (con más de un SKU) siguen con la base estricta 120x100 — mezclar sobresalientes de SKUs distintos en direcciones distintas daría un perfil irregular difícil de estibar y envolver, esa preocupación sigue vigente y no se tocó.

---

## 6. Rotación acostada (Comestibles / Cigarros)

Confirmado con fotos reales: Comestibles y Cigarros se acuestan para ahorrar espacio (una cara lateral como huella, no la base). Medido contra la demanda real: 94% de SKUs de Comestibles y ~21% de Cigarros caben más cajas por cama acostados que parados. El resto de las categorías (Licores, vidrio, Lácteos) se mantiene siempre parada — riesgo de derrame/quiebre (`config.CATEGORIAS_ROTACION_LIBRE`).

---

## 7. Redondeo de demanda por categoría

`ceil(Cajas Teóricas)` por línea puede sobre-despachar respecto de la demanda equivalente real — con Cigarros, donde 96% de las líneas son fraccionarias, redondear cada una hacia arriba inflaba la demanda ~3.8x. Política explícita por categoría (`src/demanda.py`):

- **BAT (Cigarros/vapes)**: `UNIDADES_EXACTAS` — se despacha en unidades reales vía la caja de consolidación (sección 9), sin redondeo a caja completa.
- **Resto de categorías**: `CAJA_COMPLETA` — sigue redondeando hacia arriba, pero el exceso que ese redondeo produce queda cuantificado (`Unidades_Exceso_Redondeo`) en vez de perderse en silencio.

---

## 8. BAT (Cigarros/vapes) — consolidación integrada

Cigarros/vapes nunca se despachan por caja completa. El personal los consolida en una caja física fija (52.5×34×49cm, hasta 1000 unidades) separada del cubicaje normal.

Diseño actual ("BAT integrado"): la demanda BAT de cada CD se agrega como **una fila más de demanda** (pseudo-SKU `__BAT__`, `bat.construir_filas_bat_pseudo_sku`) al mismo `df_cd` que arma `packing_bloques.armar_pallets_bloques` — compite por espacio en el MISMO pase que cualquier otro SKU, con ambas orientaciones XY probadas automáticamente. Después de armar, `asignar_cajas_bat_a_torres` mapea la cantidad colocada de vuelta a objetos `CajaBAT` reales (son fungibles entre sí — mismo footprint fijo, el mapeo es por orden estable, no por identidad). Un pallet cuyas torres son TODAS BAT se renombra a `PV5-BAT-{cd}-NNN` y cuenta como pallet físico normal en el benchmark, nunca se excluye.

Una versión anterior corría BAT **después** de cerrar todos los demás pallets, sin que el resto supiera que iba a hacer falta lugar — eso dejaba cada vez menos aire disponible a medida que el packing se ajustaba más (llegó a medirse hasta 9 pallets BAT dedicados en un estado intermedio de V5). Integrar BAT desde el principio dio `bat_dedicados=0` en el dataset real actual, con demanda exacta y cero violaciones geométricas.

---

## 9. La regla SKU_BLOQUE (bloques indivisibles)

Instrucción textual del usuario, la que le da nombre al motor y reemplaza cualquier heurística anterior de bin-packing genérico:

> "si me piden 100 cajas de kr negra y el maestro me dice que 1 pallet es 150 cajas entonces yo puedo poner en un solo pallet las 100 cajas y la altura restante que me queda para cumplir con los parámetros ya establecidos busco otros skus que también consolidados me ayuden a llegar a la altura óptima, si ya no encuentro consolidados entonces busco remanentes"

Diseño (`src/packing_bloques.py`), en dos fases:

1. **Dedicar** (`_dedicar_por_sku`): por SKU y CD, si la demanda total supera lo que entra en un pallet completo (`Cajas por PH` del Maestro — el máximo físicamente comprobado por operación, **no** un número que el packer deba re-derivar ni recortar), se extraen tantos pallets 100% dedicados como quepan, con una única orientación fija por pallet (grilla columnas × filas × altura, calculada directo — no descubierta a los tropezones colocando caja por caja) y usando la base extendida con sobresaliente (125×105cm, sección 5.2). Lo que sobra (o la demanda entera, si ya cabía en un pallet) es el "bloque" del SKU — nunca se parte a propósito.
2. **Armar por bloques**: se elige el bloque pendiente más grande (proxy: altura si se apilara en una sola columna) como ancla de un pallet nuevo, se coloca ENTERO — puede necesitar varias torres side-by-side dentro del mismo pallet si el footprint es chico frente a la cantidad, eso no es "repartir", sigue siendo un pallet. Colocación atómica con snapshot/rollback exacto: si el bloque completo no entra, no queda nada colocado a medias. Después se agregan, de mayor a menor, otros bloques ENTEROS de otros SKUs — todo o nada — hasta que no entra ninguno más completo. Recién ahí, como **último recurso**, se parte UN bloque (uno solo por pallet, para no fragmentar de más) para terminar de llenar la altura de ese pallet.

Reusa el mecanismo de colocación 3D de `packing_columnar.py` (MaxRects con cuboides libres 3D) — lo que cambia frente a un bin-packing genérico es el ORDEN y el criterio de qué se coloca entero vs qué se parte, no la geometría de fondo.

---

## 10. Hallazgos y correcciones sobre la regla de bloques

### 10.1 Pérdida de demanda silenciosa (bug real, encontrado durante la limpieza de sección 15)

`_dedicar_por_sku` asumía que la capacidad declarada por el Maestro siempre entra completa en un pallet fresco. Para un caso real (SJ97, SKU con demanda 384 y capacidad declarada 192 → 2 pallets "dedicados" de 192 cada uno en teoría), el packer 3D real solo lograba colocar 180 en uno de los dos — la fragmentación real de la huella no logra el empaque perfecto que asume el número del Maestro. El código original hacía `break` en el loop de colocación y agregaba el pallet igual, sin registrar las 12 cajas que quedaban sin colocar — silenciosas, sin pasar por `sin_colocar`.

**Corregido**: si un pallet "dedicado" no logra completar la capacidad declarada, el faltante se suma al bloque de ese SKU en vez de perderse — la fase de bloques lo intenta colocar en otro lado. Efecto colateral: el total sobre el dataset real bajó de 60 a 53 pallets (esas cajas ahora se ubican de verdad en vez de "desaparecer", lo que dejaba menos margen real del que el packer creía tener).

### 10.2 Orientación mezclada + sobresaliente no aplicado (bug real, corregido después)

Investigando por qué otro dataset (demanda real del 18.08) subió de 60 a 62 pallets tras el fix anterior, aparecieron dos problemas sobre pallets dedicados:

1. **Bug de orientación**: el pallet dedicado quedaba en 180 cajas cuando la mejor orientación pura (grilla columnas × filas × altura) daba 189 — el best-fit incremental de MaxRects mezclaba orientaciones caja a caja y fragmentaba el espacio de una forma que después ninguna orientación podía volver a aprovechar. 9 de las 12 cajas de brecha eran bug propio, no un límite físico.
2. **Sobresaliente sin cablear al packing real**: el margen de 2.5cm/lado existía en `config.py` desde V4 pero solo se usaba para validar datos del Maestro, nunca para el packing real.

**Corregido**: `_mejor_orientacion_grilla` fija una sola orientación por pallet dedicado sobre la base extendida (125×105). Resultado: el caso puntual (KR Cola Negra, SJ97) pasó de 3 pallets (180+180+24 cajas) a 2 pallets exactos (192+192). Dataset del 18.08: 62 → 60 pallets. El dataset grande se mantuvo en 53 (misma cantidad, mejor concentración interna). Los pallets mixtos no se tocaron — siguen con la base estricta 120×100.

### 10.3 Costo medido de la regla ("SKU nunca repartido")

Contra la demanda real del 18.08 (6 CDs, benchmark real = 48 pallets del hub):

| Motor | Pallets |
|---|---|
| Real (hub) | 48 |
| AUTO (V4+V5, ya borrado) | 50 |
| SKU_CONSOLIDADO (post-proceso conservador, ya borrado) | 62 |
| **SKU_BLOQUE (actual)** | 60 |

SKU_BLOQUE deja SKUs de alta rotación (como KR Cola Negra) confinados a exactamente 1-2 pallets por CD, verificado — pero cuesta más pallets en total que un motor que optimiza sin esa restricción (60 vs 50, +20%). Es un trade-off de negocio aceptado explícitamente, no un defecto a corregir: la instrucción fue priorizar que un SKU no aparezca repartido en más pallets de los necesarios, aunque el conteo total de pallets no sea el mínimo matemático posible.

---

## 11. Estabilidad — informativa, nunca bloquea

`src/estabilidad.py` calcula, sobre cada pallet ya armado: centro de masa XY (ponderado por peso de cada torre) y su desviación del centro geométrico, peso por cuadrante, torres "esbeltas" (altura / lado más corto > 4), y fracción de peso en la mitad superior (centro de masa vertical ponderado, normalizado contra la altura de producto real — con torres que pueden estar apiladas una sobre otra en Z, no solo de piso a techo). Estados `OK` / `WARN_COG` / `WARN_TORRE_ESBELTA` / `WARN_PESO_SUPERIOR` — nunca bloquea el armado, es un reporte para que operación audite manualmente un pallet específico si hace falta. Umbrales sin validar contra operación real (mismo espíritu que el peso, sección 4): un punto de partida razonable, no una norma.

---

## 12. Validación geométrica dura

`src/validacion_v5.py` audita, sobre el resultado YA armado (no es una segunda implementación del packer, es una verificación independiente):

- **Overflow**: ninguna torre se sale de la base del pallet. El tope es la base extendida (125×105) porque los pallets dedicados la usan a propósito (sección 5.2, 9); los mixtos igual respetan la base estricta por construcción.
- **Overlap 3D**: ninguna pareja de torres del mismo pallet se superpone en X, Y y Z simultáneamente — dos torres pueden compartir el mismo (x,y) si sus rangos de altura no se cruzan (apilado válido, una encima de la otra).
- **Altura**: ningún pallet supera `ALTURA_TOPE_DURO` (215cm).

Estas violaciones son las que evalúa el gate del benchmark (sección 2) junto con el rango de pallets y la demanda exacta.

---

## 13. Estado actual (dataset real `Cubicaje18.07.2026.xlsx`)

```
pallets totales:          53
por CD:                    BK31=5, BK41=4, BK43=4, BK65=5, BK68=4,
                            SJ86=8, SJ87=9, SJ95=5, SJ97=9
altura media:              210.9 cm  (rango 197.4 – 214.9)
demanda_unidades_error:    0.0
bat_dedicados:              0
violaciones geométricas:    0
gate 42-45:                 NO aprobado (único motivo: pallets fuera de rango)
```

---

## 14. Invariantes

1. La demanda nunca se pierde en silencio — se despacha, o queda explícitamente en `sin_colocar` / "Requiere Revisión".
2. Ningún pallet supera `ALTURA_TOPE_DURO` (215cm).
3. Ninguna torre se sale de su base permitida (estricta 120×100 en mixtos, extendida 125×105 en dedicados) ni se superpone con otra en 3D.
4. Un SKU con demanda mayor a la capacidad de un pallet se dedica en pallets completos antes de entrar a la fase de bloques — nunca se "adivina" cuántos pallets necesita.
5. Un bloque de SKU se coloca entero o no se coloca — nunca queda "una parte sí, una parte no" a medias (colocación atómica con rollback).
6. Se parte como máximo un bloque por pallet, y solo cuando ya no hay ningún otro bloque entero que quepa.
7. BAT nunca se despacha por caja completa; se consolida en unidades reales en la caja física fija, compitiendo por espacio junto con el resto de la demanda del CD.
8. Toda geometría inferida/degradada queda trazada (`Fuente_Geometria`) — nunca se inventa una medida en silencio.
9. La corrida es determinística: mismo input, mismo Excel byte a byte (sin aleatoriedad en ningún punto del pipeline actual).

---

## 15. Historial resumido (de V3 a hoy)

El detalle completo, patch por patch, vive en `Parches/v5/PATCH_LOG.md` (no se repite acá). Resumen de las etapas mayores:

- **V3/V4**: motor por "camas" (capas horizontales uniformes por categoría/nivel de estabilidad), reglas duras de altura/peso/orden de categorías.
- **V4b/V4c**: mezcla libre por geometría en vez de por categoría, peso pasa a blando, rotación acostada para Comestibles/Cigarros — confirmado contra fotos reales.
- **V5 (P0-P14)**: motor columnar por "torres" (posición XY con altura independiente, más tarde también Z independiente — packing 3D real tipo Tetris/Lego), multi-start (7 estrategias × 20 semillas), residual search, BAT integrado, gate formal 42-45. Mejor resultado propio: 49 pallets (vs 55 de V4) en el dataset grande, sin aprobar el gate.
- **AUTO / AUTO_CONSOLIDADO**: correr V4 y V5 y quedarse con el mejor resultado por CD (nunca peor que el mejor de los dos). Mejor resultado medido: 48 pallets en el dataset grande.
- **SKU_CONSOLIDADO / SKU_BLOQUE**: pivote de objetivo — de "minimizar pallets a cualquier costo" a "un SKU nunca queda repartido en más pallets de los necesarios", instrucción explícita de negocio con el ejemplo textual de la sección 9. SKU_BLOQUE superó a SKU_CONSOLIDADO (60 vs 62 sobre la demanda real del 18.08) porque además de evitar fragmentar combina activamente bloques enteros de distintos SKUs para acercarse a la altura óptima.
- **Limpieza (`1c5f68e`)**: por instrucción explícita, se borró todo motor salvo SKU_BLOQUE (V4 completo, V5 multi-start puro, AUTO, AUTO_CONSOLIDADO, SKU_CONSOLIDADO, `legacy/`) — `src/` pasó de ~5.030 a ~2.775 líneas (-45%). La limpieza, al forzar correr la suite completa después de cada borrado, encontró el bug real de pérdida de demanda de la sección 10.1.
- **Fix de orientación + sobresaliente real (`506285c`, commit actual)**: sección 10.2.

**Decisión de negocio explícita y vigente**: quedarse con un solo motor (SKU_BLOQUE) aunque no sea el que más cerca queda del benchmark de 42-45 pallets — la regla de "SKU nunca repartido" pesa más que el número puro. Cualquier intento futuro de acercarse más al benchmark tiene que respetar esa regla, no relajarla (ver sección 10.3 para el costo ya medido de mantenerla).
