# Documentación lógica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `d7051a9` (2026-08-21) — único motor activo: **SKU_BLOQUE, armado por camas (pisos)**. V4, V5 multi-start puro, AUTO, AUTO_CONSOLIDADO y SKU_CONSOLIDADO siguen borrados (ver sección 15); el modelo de "torres verticales" que reemplazó a esos motores también fue reemplazado, por el mismo motivo que ellos: no reproducía cómo se arma un pallet en la realidad.
**Alcance:** qué reglas de negocio implementa el motor, por qué, y con qué evidencia se calibró cada una.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_LOGICA*.md`. El detalle de código/módulos está en `DOCUMENTACION_TECNICA.md`. El historial completo, patch por patch, vive en `Parches/v5/PATCH_LOG.md` — no se repite acá, solo se resume.

---

## 0. Prioridad de reglas

Cuando dos reglas compiten, en este orden:

1. **La demanda se despacha exacta** (o con la política de redondeo explícita por categoría, sección 7) — nunca se pierde silenciosamente.
2. **Restricciones físicas/operacionales duras**: la altura (~190-215cm, sección 3) y la geometría (una torre no se sale del pallet, dos torres no se solapan) son las únicas que bloquean el armado. Peso, orden de categorías y estabilidad son reportes/preferencias, no bloqueos (ver sección 1).
3. **El pallet se arma cama por cama, nunca por columnas aisladas** (sección 9 — la corrección arquitectónica más reciente, con evidencia visual del Inspector de Pallets). Dentro de una cama, ningún SKU puede dejar un hueco de aire grande respecto al SKU ancla que abrió esa cama.
4. **Minimizar la cantidad de pallets** que hay que armar y mover, llenando cada cama lo más posible antes de abrir la siguiente.
5. Trazabilidad: toda geometría inferida/degradada queda marcada, nunca se inventa en silencio; toda demanda que no logra colocarse queda en `sin_colocar`, nunca desaparece.

---

## 1. Qué es y qué no es una restricción dura

Confirmado con Omar viendo fotos de picking real: los operarios arman pallets con capas horizontales, mezclando categorías libremente dentro de cada capa. La instrucción de negocio fue explícita: restringir solo el tamaño (altura) y la geometría, y armar SIEMPRE por filas/capas — nunca por columnas verticales aisladas de un solo SKU.

| Regla | Estado |
|---|---|
| Altura del pallet (~190-215cm) | **Dura** — el único tope que decide cuándo dejar de apilar (`config.ALTURA_MAX_OBSERVADA`) |
| Geometría (overlap, overflow de la base) | **Dura** — auditada aparte por `src/validacion_v5.py`, no solo confiada al packer |
| El pallet se arma por capas horizontales, no por columnas | **Dura** — corrección arquitectónica explícita, ver sección 9 |
| Dentro de una cama, el hueco entre SKUs distintos es acotado | **Dura**, tolerancia simétrica de 8cm (`TOLERANCIA_HUECO_CAMA_CM`) — ver sección 9 |
| Peso máximo (1430kg) | Blanda — se calcula y alerta (`⚠ ALERTA DE PESO` sobre 1400kg), nunca bloquea el armado |
| Orden por nivel de categoría / estabilidad física | Retirada como restricción de armado — el packer no agrupa ni ordena por categoría. `Nivel_Categoria` sigue viajando como metadata informativa en el plan de picking |
| BAT/Cigarros como caja de consolidación aparte | **Dura**, sin cambios — nunca se despacha por caja completa, ver sección 8 |
| Cajas siempre "de pie" | Dura para todas las categorías salvo Comestibles/Cigarros (pueden acostarse si conviene, sección 6) |

---

## 2. El benchmark real

Fuente original: fotos de picking de operación real (~130 fotos, 42 pallets físicos con categorías mezcladas en casi todos los niveles) y `Plan de Movimientos - Pre Picking 18.08.xlsx` (demanda real de un día, 6 CDs, 48 pallets físicos armados por el hub, 0 dedicados BAT).

- **Benchmark de referencia principal**: 42 pallets físicos, altura media 198.3cm, rango 170-215cm (`src/benchmark.py`: `PALLETS_REALES=42`, `ALTURA_MEDIA_REAL=198.3`).
- **Gate formal** (`benchmark.evaluar_gate_v5`, `GATE_V5_PALLETS_MIN/MAX = 42/45`): rango de pallets + demanda exacta + altura máxima ≤215 + cero violaciones geométricas, los cuatro obligatorios, ninguno se relaja para "hacer pasar" el benchmark.
- **Estado actual** (dataset `Cubicaje18.07.2026.xlsx`): **47 pallets**, 0 violaciones geométricas, demanda exacta, altura media 193.9cm (9 pallets bajo 190cm, 8 bajo 170cm). El gate **no aprueba** — único motivo: `pallets=47, fuera del rango [42, 45]`. Ningún otro criterio falla. La brecha contra el gate bajó de 11 pallets (53 vs 42) a 5 (47 vs 42) con el rediseño de armado por camas (sección 9).
- `PALET=0` en el dato real histórico significa "pendiente de consolidación BAT", no un pallet físico adicional — el benchmark de 42 ya lo excluye. El motor reproduce esto contando `PV5-BAT-*` (pallets dedicados solo a cajas BAT) como pallets físicos normales, nunca se esconden del conteo.

> Ningún motor probado hasta ahora cerró la brecha contra 42-45 en el dataset grande — el mejor resultado del historial completo fue AUTO (V4+V5 combinados) con 48, y el armado por camas actual (47) ya lo iguala/supera sin necesitar dos motores corriendo en paralelo. Ver sección 10 para el detalle de cómo se llegó a esta cifra.

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

`PESO_ALERTA_KG=1400` / `PESO_HARD_KG=1430` existen como umbrales de **reporte** (`validacion_peso.py` marca `⚠ ALERTA DE PESO` sobre 1400kg), pero no bloquean el armado en ningún punto del pipeline actual. No están validados contra capacidad real de montacargas/rack/transporte, y la instrucción de negocio fue explícita en que la única restricción dura de armado es el tamaño (altura + geometría).

---

## 5. Reconciliación geométrica Maestro↔UMA

Regla central: el Maestro (`Cajas por cama`) es la capacidad OPERACIONAL declarada; UMA (dimensiones medidas) valida la geometría. Si UMA contradice al Maestro, el sistema **no** reduce `Cajas por cama` automáticamente — el Maestro resultó más confiable que una grilla simple en la validación contra pallets reales. El resultado reconciliado (`Cajas_Cama_Efectivo`, `derivados.py`) es hoy el único número que el armado por camas usa como objetivo por capa (sección 9) — el packer ya no recalcula su propia grilla.

### 5.1 Estados posibles por SKU (`Fuente_Geometria`)

| Estado | Significado |
|---|---|
| `UMA_VALIDADA` | La geometría medida (parada o acostada) explica exactamente la capacidad del Maestro, o no hay techo declarado |
| `UMA_SOBRECAPACIDAD` | La geometría permite más de lo que el Maestro declara — se respeta el Maestro como techo |
| `UMA_VALIDADA_CON_SOBRESALIENTE` | La geometría medida (sin cambiar largo/ancho) explica al Maestro solo si se permite el sobresaliente de negocio (2.5cm/lado) — se usa la medida real tal cual, no un footprint inventado |
| `MAESTRO_IMPOSIBLE_DEGRADADO` | El Maestro declara algo geométricamente imposible incluso con sobresaliente — se degrada al techo geométrico real en vez de inventar una geometría ficticia |
| `DATO_INSUFICIENTE` | Sin Alto de caja, o sin Largo/Ancho — el SKU no se puede empacar de forma segura, queda "Requiere Revisión" |

### 5.2 Sobresaliente (2.5cm/lado) — hoy solo para validar datos, no para planificar

Cuánto puede volar la caja del borde del pallet antes de perder resistencia a la compresión (>20% más allá de ese margen). Medido sobre 458 SKUs remedidos: 0cm→73% del dato del Maestro alcanzable, 2.5cm→82% (elegido), 5cm→86% (fuera del estándar seguro).

**Estado actual, honesto**: el sobresaliente solo se usa para **validar** si un "Cajas por cama" del Maestro es creíble (`reconciliacion_geometrica.capacidad_xy_max_con_sobresaliente`). En el packing real, todas las camas usan hoy la base ESTRICTA 120×100 — se probó (durante el rediseño de sección 9) un criterio para que el sobresaliente aplicara solo cuando una cama termina dominada por un único SKU, pero la heurística para detectar ese caso resultó frágil (un SKU con demanda que coincide justo con su propia capacidad de grilla activaba el modo extendido aunque después hubiera quedado lugar de sobra para un SKU chico distinto compartiendo la cama). Se descartó por ahora en vez de forzar una regla no validada — el sobresaliente en packing real queda como mejora futura pendiente de un criterio más robusto (ver sección 10.3, "queda abierto").

---

## 6. Rotación acostada (Comestibles / Cigarros)

Confirmado con fotos reales: Comestibles y Cigarros se acuestan para ahorrar espacio (una cara lateral como huella, no la base). Medido contra la demanda real: 94% de SKUs de Comestibles y ~21% de Cigarros caben más cajas por cama acostados que parados. El resto de las categorías (Licores, vidrio, Lácteos) se mantiene siempre parada — riesgo de derrame/quiebre (`config.CATEGORIAS_ROTACION_LIBRE`).

---

## 7. Redondeo de demanda por categoría

`ceil(Cajas Teóricas)` por línea puede sobre-despachar respecto de la demanda equivalente real — con Cigarros, donde 96% de las líneas son fraccionarias, redondear cada una hacia arriba inflaba la demanda ~3.8x. Política explícita por categoría (`src/demanda.py`):

- **BAT (Cigarros/vapes)**: `UNIDADES_EXACTAS` — se despacha en unidades reales vía la caja de consolidación (sección 8), sin redondeo a caja completa.
- **Resto de categorías**: `CAJA_COMPLETA` — sigue redondeando hacia arriba, pero el exceso que ese redondeo produce queda cuantificado (`Unidades_Exceso_Redondeo`) en vez de perderse en silencio.

---

## 8. BAT (Cigarros/vapes) — consolidación integrada

Cigarros/vapes nunca se despachan por caja completa. El personal los consolida en una caja física fija (52.5×34×49cm, hasta 1000 unidades) separada del cubicaje normal.

Diseño ("BAT integrado"): la demanda BAT de cada CD se agrega como **una fila más de demanda** (pseudo-SKU `__BAT__`, `bat.construir_filas_bat_pseudo_sku`) al mismo `df_cd` que arma `packing_bloques.armar_pallets_bloques` — compite por espacio en el MISMO pase que cualquier otro SKU, dentro de la lógica de camas. Después de armar, `asignar_cajas_bat_a_torres` mapea la cantidad colocada de vuelta a objetos `CajaBAT` reales (son fungibles entre sí — mismo footprint fijo, el mapeo es por orden estable). Un pallet cuyas torres son TODAS BAT se renombra a `PV5-BAT-{cd}-NNN` y cuenta como pallet físico normal en el benchmark, nunca se excluye.

**Nota sobre el estado actual**: con el armado por torres (arquitectura anterior a sección 9), BAT integrado llegó a dar `bat_dedicados=0` en el dataset real. Con el rediseño a camas, el dataset real vuelve a mostrar **2 pallets BAT dedicados** (los dos pallets de menor altura del resultado actual, ~64cm). No se investigó a fondo si es un efecto esperable de que el armado por camas deja menos aire "suelto" en posiciones intermedias para que BAT encuentre host natural, o si hay margen de mejora — queda como observación abierta, no bloquea nada (BAT nunca deja de despacharse, solo puede terminar en su propio pallet en vez de compartir uno existente).

---

## 9. El pallet se arma por CAMAS, no por torres verticales

### 9.1 Por qué se rediseñó (corrección arquitectónica del usuario)

La arquitectura anterior armaba el pallet por **torres**: cada SKU ocupaba una posición XY fija, apilado de piso a techo con su propia altura, independiente de las torres vecinas. Con capturas reales del Inspector de Pallets, se detectó el problema: una torre baja al lado de una torre alta que comparte huella deja un hueco de aire enorme por encima de la baja — nadie más podía usar ese espacio, porque el modelo de torres no permitía que otro SKU "se subiera" ahí sin abrir su propia columna aislada.

Instrucción textual del usuario: *"nunca pero nunca se empieza haciendo columnas, siempre primero se van llenando las filas de abajo hacia arriba construyendo un bloque de 120x100"* — y sobre qué tan parecidos tienen que ser los SKUs que comparten una capa: *"no puede haber huecos tan grandes entre ellos, máximo huecos que te permitan poner una cama encima y que sea estable"*.

### 9.2 Diseño actual

El pallet se arma **cama por cama** (piso por piso), de abajo hacia arriba:

1. **Ancla de la cama**: entre los SKUs con demanda pendiente cuya altura de caja todavía entra en lo que resta de altura del pallet, se elige el de **mayor demanda pendiente**. La altura de esa cama queda fijada por la altura de caja del ancla.
2. **El ancla llena la huella 120×100 fila por fila**, con una única orientación fija para toda la cama (nunca mezclada — mezclar orientaciones caja a caja fragmentaba el espacio de una forma que después ninguna orientación podía volver a aprovechar bien). El objetivo de cuántas cajas entran por cama **no lo recalcula el packer**: es `Cajas_Cama_Efectivo` (sección 5), ya reconciliado contra el Maestro y la geometría UMA.
3. **El resto de esa MISMA cama** se completa con otros SKUs pendientes cuya altura de caja esté dentro de `TOLERANCIA_HUECO_CAMA_CM` (8cm, heredado de la calibración V4 contra `Cubicaje18.07.2026.xlsx`: con 3cm el motor daba 91% de pallets parciales, con 8cm 76%, retorno decreciente después) de la altura de la cama — **en ambas direcciones** (ver bug en sección 10.2).
4. Cuando la cama no admite más SKUs compatibles, se sube a la siguiente cama (nuevo `z`), repitiendo el proceso, hasta agotar la altura del pallet o la demanda.

Reusa el motor 3D de `packing_columnar.py` (MaxRects) sin tocarlo — la única diferencia frente al modelo de torres es que el cuboide libre inicial de cada cama tiene profundidad Z = **solo la altura de esa cama**, no el presupuesto de altura completo del pallet. El mismo best-fit que antes producía columnas de piso a techo ahora llena en el plano XY antes de subir.

### 9.3 Qué reemplaza

El diseño anterior ("SKU_BLOQUE" por torres) tenía dos fases: (1) dedicar pallets 100% completos usando `Cajas por PH` cuando la demanda de un SKU superaba la capacidad de un pallet entero, y (2) armar el resto combinando "bloques" enteros de distintos SKUs, partiendo uno solo como último recurso. **Esa distinción de fases ya no existe**: `Cajas por PH` no se usa en ningún punto del armado actual — el único número relevante es `Cajas_Cama_Efectivo` (capacidad de UNA cama, no de un pallet completo), y un SKU con mucha demanda simplemente ocupa varias camas apiladas del mismo pallet (o de varios pallets) de forma natural, sin una fase de "dedicación" separada.

---

## 10. Hallazgos y correcciones

### 10.1 Pérdida de demanda silenciosa en pallets dedicados (arquitectura anterior, ya no aplica)

En la arquitectura por torres, `_dedicar_por_sku` asumía que la capacidad declarada por el Maestro siempre entraba completa en un pallet fresco; cuando el packer real no lograba completarla, el faltante se perdía en silencio. Corregido en su momento (bajó el total de 60 a 53 pallets); la función entera dejó de existir con el rediseño de sección 9, pero se documenta acá porque fue el bug que motivó, en cadena, revisar a fondo cómo se estaba armando cada pallet.

### 10.2 Tolerancia de hueco asimétrica (bug real, corregido en el rediseño por camas)

Primera versión del filtro de compatibilidad dentro de una cama: `alto_caja_secundario <= altura_cama + tolerancia` — asimétrico, solo evitaba que un SKU **más alto** se saliera de la cama. Un SKU **mucho más bajo** pasaba el filtro igual (ej. una caja de 20cm compartiendo una cama de 100cm: físicamente sí entra en la profundidad disponible) pero dejaba exactamente el hueco de 80cm que se estaba tratando de eliminar. Atrapado por un test escrito a propósito para reproducir el caso de una captura real que mandó el usuario. Corregido a un chequeo **simétrico**: `abs(alto_caja_secundario - altura_cama) <= tolerancia`.

### 10.3 Sobresaliente por cama dominada — probado y descartado

Se probó una versión donde, si el SKU ancla llenaba la cama entera él solo, se le permitía usar la base extendida con sobresaliente (125×105). La heurística para decidir "esta cama va a quedar sola" resultó frágil: un SKU con demanda que coincidía justo con su propia capacidad de grilla activaba el modo extendido aunque después hubiera quedado lugar de sobra para que un SKU chico distinto se sumara a esa misma cama con la base estricta. Se descartó — queda como mejora futura pendiente de un criterio más robusto (por ejemplo, intentar la versión extendida y confirmar que de verdad no hay ningún otro SKU pendiente compatible antes de comprometerse a esa base).

### 10.4 Resultado medido del rediseño

| | Antes (torres) | Después (camas) |
|---|---|---|
| Dataset grande (`Cubicaje18.07.2026.xlsx`) | 53 pallets | **47 pallets** |
| Dataset real 18.08 | 60 pallets | **52 pallets** |

0 violaciones geométricas, demanda exacta, y — el invariante central que motivó el rediseño — **0 camas con hueco mayor a `TOLERANCIA_HUECO_CAMA_CM` en todo el dataset real** (no solo en los tests sintéticos, verificado explícitamente contra ambos datasets).

---

## 11. Estabilidad — informativa, nunca bloquea

`src/estabilidad.py` calcula, sobre cada pallet ya armado: centro de masa XY (ponderado por peso de cada torre) y su desviación del centro geométrico, peso por cuadrante, torres "esbeltas" (altura / lado más corto > 4), y fracción de peso en la mitad superior (centro de masa vertical ponderado, normalizado contra la altura de producto real). Estados `OK` / `WARN_COG` / `WARN_TORRE_ESBELTA` / `WARN_PESO_SUPERIOR` — nunca bloquea el armado, es un reporte para que operación audite manualmente un pallet específico si hace falta. Umbrales sin validar contra operación real: un punto de partida razonable, no una norma.

---

## 12. Validación geométrica dura

`src/validacion_v5.py` audita, sobre el resultado YA armado (no es una segunda implementación del packer, es una verificación independiente):

- **Overflow**: ninguna torre se sale de la base del pallet. El chequeo permite hasta la base extendida (125×105) por si algún camino la usara, pero en la práctica hoy el armado por camas siempre usa la base estricta 120×100 (sección 5.2) — el margen extra queda sin uso.
- **Overlap 3D**: ninguna pareja de torres del mismo pallet se superpone en X, Y y Z simultáneamente — dos torres pueden compartir el mismo (x,y) si sus rangos de altura no se cruzan (apilado válido, una cama encima de otra).
- **Altura**: ningún pallet supera `ALTURA_TOPE_DURO` (215cm).

Estas violaciones son las que evalúa el gate del benchmark (sección 2) junto con el rango de pallets y la demanda exacta.

---

## 13. Estado actual (dataset real `Cubicaje18.07.2026.xlsx`)

```
pallets totales:          47
por CD:                     BK31=4, BK41=4, BK43=4, BK65=5, BK68=4,
                             SJ86=6, SJ87=7, SJ95=4, SJ97=9
altura media:              193.9 cm  (rango 63.9 – 214.9)
pallets bajo 190cm:         9
pallets bajo 170cm:         8
bat_dedicados:               2
demanda_unidades_error:     0.0
violaciones geométricas:    0
peor hueco dentro de una cama: 8.0 cm (= tolerancia exacta, nunca la supera)
gate 42-45:                  NO aprobado (único motivo: pallets fuera de rango)
```

---

## 14. Invariantes

1. La demanda nunca se pierde en silencio — se despacha, o queda explícitamente en `sin_colocar` / "Requiere Revisión".
2. Ningún pallet supera `ALTURA_TOPE_DURO` (215cm).
3. Ninguna torre se sale de su base permitida ni se superpone con otra en 3D.
4. El pallet se arma cama por cama — nunca una columna aislada de piso a techo que le quite aire disponible a otro SKU.
5. Dentro de una misma cama, la diferencia de altura entre el SKU ancla y cualquier otro SKU que la comparte nunca supera `TOLERANCIA_HUECO_CAMA_CM` (8cm), en ninguna dirección.
6. BAT nunca se despacha por caja completa; se consolida en unidades reales en la caja física fija, compitiendo por espacio junto con el resto de la demanda del CD.
7. Toda geometría inferida/degradada queda trazada (`Fuente_Geometria`) — nunca se inventa una medida en silencio.
8. La corrida es determinística: mismo input, mismo Excel byte a byte (sin aleatoriedad en ningún punto del pipeline actual).

---

## 15. Historial resumido (de V3 a hoy)

El detalle completo, patch por patch, vive en `Parches/v5/PATCH_LOG.md` (no se repite acá). Resumen de las etapas mayores:

- **V3/V4**: motor por "camas" de categoría (capas horizontales uniformes por nivel de estabilidad), reglas duras de altura/peso/orden de categorías. No confundir con el armado por camas actual (sección 9) — aquella agrupaba por categoría, esta agrupa por altura de caja compatible, sin importar la categoría.
- **V4b/V4c**: mezcla libre por geometría en vez de por categoría, peso pasa a blando, rotación acostada para Comestibles/Cigarros.
- **V5 (P0-P14)**: motor columnar por "torres" (posición XY con altura independiente), multi-start, residual search, BAT integrado, gate formal 42-45. Mejor resultado propio: 49 pallets, sin aprobar el gate.
- **AUTO / AUTO_CONSOLIDADO**: correr V4 y V5 y quedarse con el mejor resultado por CD. Mejor resultado medido: 48 pallets.
- **SKU_CONSOLIDADO / SKU_BLOQUE (torres)**: pivote a "un SKU nunca queda repartido en más pallets de los necesarios" como prioridad de negocio, con fase de "dedicar" pallets completos + "bloques" enteros combinados.
- **Limpieza (`1c5f68e`)**: se borró todo motor salvo SKU_BLOQUE (V4 completo, V5 multi-start puro, AUTO, AUTO_CONSOLIDADO, SKU_CONSOLIDADO, `legacy/`) — `src/` -45% líneas. Encontró el bug de pérdida de demanda de sección 10.1.
- **Fix de orientación + sobresaliente en dedicados (`506285c`)**: corrigió una fragmentación de orientación y aplicó sobresaliente a pallets 100% dedicados — superado por el punto siguiente, que eliminó el concepto de "dedicado".
- **Rediseño por camas (`d7051a9`, commit actual)**: reemplaza el modelo de torres por armado cama-por-cama (sección 9), tras detectar con capturas reales que las torres dejaban huecos de aire grandes. Recuperó `src/layout_solver.py` (borrado por error en la limpieza anterior, no cableado todavía — ver `DOCUMENTACION_TECNICA.md`). Bajó el dataset grande de 53 a 47 pallets y el dataset real 18.08 de 60 a 52.

**Decisión de negocio explícita y vigente**: el pallet se arma por capas horizontales con huecos acotados, priorizando estabilidad física real (evidenciada en fotos/capturas) por sobre cualquier heurística de empaque que no reproduzca cómo se arma un pallet en la operación. Cualquier intento futuro de acercarse más al benchmark de 42-45 tiene que respetar esa forma de armado, no relajarla.
