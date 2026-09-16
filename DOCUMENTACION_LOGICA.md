# Documentación lógica — Agente Cubicador

**Repo:** `agente-cubicador-transportes-bees`
**Estado documentado:** commit `7f174ee` (2026-09-14, HEAD), 44 commits totales. Único motor activo: **SKU_BLOQUE, armado cama por cama** (`src/packing_bloques.py`).
**Alcance:** qué reglas de negocio implementa el motor, por qué, y con qué evidencia se calibró cada una.

> Este documento reemplaza toda versión anterior de `DOCUMENTACION_LOGICA*.md`. El detalle de código/módulos está en `DOCUMENTACION_TECNICA.md`. El historial completo, patch por patch (más de 3900 líneas), vive en `Parches/v5/PATCH_LOG.md` — no se repite acá, solo se resume lo que sigue vigente.

---

> **Actualización operativa — 2026-09-15:** BK31 manual es la referencia de negocio. El usuario confirmó **220 cm de altura total (incluye parihuela)** y **2 cm máximos por cada lado**, tanto sobre el borde exterior como sobre el apoyo. Las métricas de corridas anteriores que aparecen abajo son históricas; estos cambios no demuestran todavía que el solver coloque automáticamente las 98 cajas.

## 0. Qué cambió desde la última versión de este documento

La versión anterior documentaba el rediseño "por camas" recién hecho (commit `d7051a9`). Desde entonces hubo ~30 commits más, con cuatro cambios de fondo que reemplazan partes de lo ya documentado:

1. **Cigarros/vapes salen COMPLETAMENTE del cubicaje** (antes solo competían por espacio como pseudo-SKU BAT). Ahora nunca se arma un pallet con Cigarros — se reportan aparte (sección 8).
2. **Las "bandas estrictas" por categoría se probaron y se revirtieron** con evidencia real (un pallet físico mezclaba Licores/Comestibles/Aseo/NABs libremente). Quedó un esquema de **jerarquía de peso/nivel**, no de exclusividad (sección 5).
3. Apareció (y se conectó de punta a punta) un mecanismo de **`Pallets_Objetivo`**: la cantidad de pallets de un CD puede venir fija desde la planificación externa, en vez de que el motor decida cuántos abrir (sección 10).
4. El camino **sin** `Pallets_Objetivo` (el 99% del uso real de la app) ahora **también** compacta cama por cama con un solver real (antes era un barrido voraz simple que dejaba franjas de aire vacías, sección 9.3).

---

## 1. Prioridad de reglas

Cuando dos reglas compiten, en este orden:

1. **La demanda se despacha exacta** (o queda explícitamente reportada como no colocada, sección 11) — nunca desaparece en silencio.
2. **Restricciones físicas duras**: altura del pallet, geometría (una torre no se sale del pallet, dos torres no se solapan, y desde esta versión, **ninguna caja puede quedar sin apoyo admisible** — sección 7) son las únicas que bloquean el armado.
3. **El pallet se arma cama por cama** (piso a techo), nunca por columnas verticales aisladas de un solo SKU.
4. **Minimizar la cantidad de pallets** — salvo que `Pallets_Objetivo` fije la cantidad exacta para ese CD, en cuyo caso el objetivo pasa a ser colocar la MAYOR cantidad de demanda posible dentro de esa cantidad fija (sección 10).
5. Peso, orden de categoría y estabilidad son **reportes/alertas**, nunca bloqueos.
6. Trazabilidad: toda geometría inferida/degradada queda marcada; toda demanda no colocada queda listada por CD/SKU, nunca se pierde sin dejar rastro.

---

## 2. Qué es y qué no es una restricción dura

| Regla | Estado |
|---|---|
| Altura del pallet (~190-220cm) | **Dura** — único tope que decide cuándo dejar de apilar (`config.ALTURA_MAX_OBSERVADA`) |
| Geometría: overlap, overflow de la base | **Dura** — auditada aparte por `validacion_v5.py`, no solo confiada al packer |
| **Anti-flotación**: soporte real en el interior de la huella; solo los bordes pueden sobresalir hasta 2 cm por lado | **Dura**, invariante permanente desde el bug real reportado con foto (sección 7) |
| El pallet se arma por camas, no por columnas aisladas | **Dura** |
| Cigarros/vapes nunca compiten por espacio en un pallet | **Dura**, sin excepción (sección 8) |
| Peso máximo (1430kg) | Blanda — se calcula y alerta (`⚠ ALERTA DE PESO` sobre 1400kg), nunca bloquea |
| Jerarquía de categoría (qué puede apoyarse sobre qué) | **Dura** para el "quién soporta a quién" columna por columna; **no** exige exclusividad de cama (sección 5) |
| Cajas siempre "de pie" | Dura salvo Comestibles/Aseo, que pueden acostarse para llenar huecos (sección 6) |
| Tope de `Cajas por PH` por pallet, por SKU | **Dura** — ningún SKU supera esa cantidad en un solo pallet |
| Cantidad de pallets por CD (`Pallets_Objetivo`) | **Dura cuando el CD aparece en esa hoja opcional**; si no aparece, el motor decide cuántos abrir (sección 10) |

---

## 3. Altura del pallet

Sin cambios respecto a la versión anterior — sigue siendo la ventana validada contra 42 pallets físicos reales (`ALTURA_TARGET=198.3`, rango observado original 190-215cm; tope operativo actualizado a 220cm):

| Rango | Etiqueta |
|---|---|
| 195-200 | ÓPTIMO |
| 190-195 | NOMINAL |
| 185-190 | TOLERADO |
| 170-185 | PARCIAL OPERATIVO |
| <170 | RESIDUAL |
| 200-210 | ALTO PERO OPERATIVO |
| 210-220 | EXCEPCIÓN |
| >220 | NO PERMITIDO |

`ALTURA_HARD_VALIDADA = None`: ninguno de estos umbrales es una norma de seguridad formal todavía — son el benchmark observado en operación real. 220cm es el tope operacional confirmado por el usuario y usado por el motor para decidir cuándo dejar de apilar.

## 4. Peso

Sin cambios: `PESO_ES_RESTRICCION_DURA = False`. El peso se calcula y se reporta (`⚠ ALERTA DE PESO` sobre 1400kg, `PESO_HARD_KG=1430` como referencia, nunca como bloqueo) pero no impide ninguna combinación geométricamente válida. `PESO_PARAMETROS_VALIDADOS = False`: sigue siendo un valor heredado, no una norma confirmada con el negocio.

## 5. Jerarquía de categorías — bandas estrictas probadas y revertidas

**Historia relevante para no repetir el experimento**: se probó una reescritura completa a "bandas" estrictamente secuenciales (1=Licores, 2=Lácteos, 3=NABs, 4=remanente), donde categorías de bandas distintas nunca podían compartir una misma cama. Al inspeccionar línea por línea un pallet real (`PLAN 24,08,26`, Pallet 1 de BK34), Licores/Comestibles/Aseo/NABs aparecían **todos mezclados en la misma cama**, y 19 de 21 SKUs tenían demanda menor a su propio techo de cama — contradiciendo directamente el esquema de bandas. Se revirtió.

**Lo que quedó, y sigue vigente**: una jerarquía de **peso/nivel** (`config.nivel_de_categoria`, 1=Licores el más pesado/base … hasta NABs, luego remate, luego Cigarros — aunque Cigarros ya no participa del armado, ver sección 8):

- Una caja **nunca** puede apoyarse directamente sobre una categoría más pesada de lo que su propio nivel permite invertido — la restricción real es "qué puede quedar ENCIMA de qué en la misma columna" (`_soporte_viola_nivel`), no "qué categorías pueden compartir piso".
- Categorías distintas **sí** pueden compartir la misma cama, siempre que la altura de sus cajas sea compatible (tolerancia simétrica de 8cm, `TOLERANCIA_ALTURA_CAMA_CM`) — la Z (el nivel del piso) es siempre el primer criterio de la cola de armado, el nivel de categoría solo desempata cuando dos SKUs podrían usar la misma Z.
- SKUs marcados como frágiles (columna `Subcategoría` = "RTD" o "Energizante" en el Maestro, incluye Four Loko) se fuerzan al nivel de remate: nunca reciben nada apoyado encima.

## 6. Orientación de las cajas

Sin cambios de fondo: Licores, Lácteos, NABs y el resto de categorías "rígidas" van siempre de pie (riesgo de derrame/quiebre). **Comestibles y Aseo** pueden acostarse (usar cualquiera de sus 3 caras como huella) cuando eso ayuda a llenar un hueco irregular que de otro modo quedaría vacío — confirmado contra fotos reales. NABs, explícitamente, **nunca** se acuesta, ni siquiera cuando eso resolvería un problema de capacidad conocido (ver hallazgo de Electrolight, sección 12).

Un dato menor pero real, documentado para no perderlo: la degradación de capacidad de Electrolight (nunca pasa de ~18-20 cajas cuando el Maestro declara 24) resultó ser un dato de UMA con Largo/Ancho invertidos (la huella real parada es 26×19cm, no 26×22.5cm) — una corrección de dato fuente pendiente, no un problema de algoritmo.

## 7. Anti-flotación — invariante permanente

**Motivo real, con foto**: "siguen habiendo camas por debajo de 170cm... hay cajas que están flotando en el vacío, toda caja debe estar puesta sobre otra caja." La causa técnica era que el fragmento de cuboide libre "arriba en Z" usaba la huella completa del cuboide padre en vez de la intersección XY real con la caja recién colocada.

Desde entonces, **toda torre que no arranca en el piso del pallet (z=0) debe tener soporte real en el interior de su huella, con sobresaliente de hasta 2 cm por cada borde**, verificado por `validacion_v5.validar_pallet_v5` contra torres cuyo tope de Z coincide exactamente con la base de la torre en cuestión. Esta verificación:

- Es independiente del motor de armado (auditoría, no una segunda implementación del mismo algoritmo).
- Se volvió a violar y se volvió a corregir una vez más durante el diseño del solver LNS (la "ruina" sacaba SKUs elegidos al azar sin sacar en cascada lo que quedaba apoyado encima) — el fix (`_romper_skus_con_cascada`) remueve en cascada cualquier torre que quede sin soporte, y tiene su propio test de regresión.
- Es, junto con overlap/overflow y el tope de altura, uno de los tres chequeos que el gate de geometría trata como bloqueantes.

## 8. Cigarros y vapes — excluidos por completo del cubicaje

**Regla de negocio explícita (sept-2026), la más reciente del proyecto**: Cigarros/vapes nunca se despachan por caja completa (96% de sus líneas de demanda son fraccionarias) **ni entran al cubicaje en absoluto**. No compiten por espacio con el resto de la demanda, no ocupan pallet propio, no aparecen en `Plan_Picking` ni en `Pallets_3D_Data`.

En su lugar: el personal consolida esa demanda tal cual la arma el hub, en una **caja física de tamaño fijo** por CD (52.5×34×49cm, hasta 1000 unidades — `config.CAJA_BAT_*`), y se despacha como un envío adicional aparte. El sistema calcula cuántas cajas físicas de consolidación hacen falta por CD y las reporta en una hoja "Cigarros" propia del Excel final (`Descripcion`, `Unidades_Demanda`, `Cajas_Consolidacion_Necesarias_CD`).

La identificación de qué demanda es Cigarros/vapes es explícita — la categoría logística `Cigarros`, o la Subcategoría del Maestro "Vapes" (si vinieran declarados bajo otra categoría) — nunca un umbral numérico genérico.

> Nota técnica para quien lea el código: `src/bat.py` conserva, sin usar, un mecanismo anterior ("BAT integrado") donde Cigarros competía por espacio como un pseudo-SKU y terminaba de remate encima de un pallet ya armado. Ese mecanismo ya no lo llama el pipeline — se mantiene probado por si alguna vez se decide volver a ese modelo, pero **hoy Cigarros no toca el armado de pallets en ningún punto**.

## 9. El pallet se arma cama por cama

### 9.1 Motivo (sin cambios respecto a la versión anterior)
Confirmado con capturas del propio Inspector de Pallets comparadas contra fotos físicas: la operación real tapiza cada cama de canto a canto mezclando SKUs, y recién sube de nivel cuando la cama está llena — nunca apila una columna de un solo SKU de piso a techo mientras el resto del piso queda vacío.

### 9.2 Motor único, continuo, sin resets
Cada pallet es UN solo `_PalletEnConstruccion` (MaxRects 3D, `packing_columnar.py`) de piso a techo — nunca se resetea a mitad de armado. Esto es lo que garantiza, por construcción, el 0% de flotación de la sección 7 (no hay una "segunda pasada" que pueda perder de vista lo que ya se colocó).

### 9.3 Dos caminos, dos motores, mismo resultado de calidad
Esta es la actualización más importante desde la versión anterior de este documento. El motor tiene dos caminos posibles según si el CD tiene una cantidad de pallets fija (`Pallets_Objetivo`, sección 10) o no:

- **Sin `Pallets_Objetivo` (el 99% del uso real)**: hasta hace poco, este camino corría un barrido voraz puro, caja por caja, sin vuelta atrás — dos SKUs que podrían tapizar la misma cama de forma complementaria casi nunca calzaban, y quedaban franjas de aire vacías en cada cama (confirmado con una captura real al lado de una foto física: la captura mostraba franjas blancas grandes, la foto mostraba cada cama tapizada de canto a canto). **Ahora este camino también compacta**: reutiliza el mismo solver de backtracking + LNS que ya existía para `Pallets_Objetivo` (sección 10), haciendo una búsqueda binaria acotada de la menor cantidad de pallets que sigue colocando el 100% de la demanda original. Nunca puede terminar peor que el barrido voraz (hay un fallback explícito).
- **Con `Pallets_Objetivo`**: reparte la demanda en exactamente esa cantidad de pallets, con el mismo solver.

Verificado contra el archivo real completo de un usuario (12 CDs, sin `Pallets_Objetivo`): 100% de la demanda colocada, **56 pallets** (contra 59 del barrido voraz solo, con MENOS demanda total en la corrida de comparación), ocupación de huella real entre 78% y 95% (la mayoría 85-90%), en 99.7 segundos.

### 9.4 Desempate "seguir la misma torre"
Ajuste puntual pedido tras replicar a mano un pallet real (BK31): el solver no tenía ninguna preferencia por continuar una torre propia — una caja nueva competía en igualdad de condiciones contra cualquier otro SKU incluso cuando caía justo encima de su propia pila. Se agregó como criterio de desempate (nunca antepuesto a la densidad real ya lograda, solo para romper empates genuinos de área).

### 9.5 Sobresaliente sobre soporte — 2 cm por lado

Activo por decisión del usuario al tomar BK31 como referencia: `config.TOLERANCIA_OVERHANG_CM = 2.0`. Se permite hasta 2 cm por cada borde en ambos ejes. Esto no cambia las orientaciones permitidas por categoría. El interior de la huella debe estar apoyado en cajas cuyo tope coincida con la base de la caja superior; no se rellenan huecos interiores con soporte ficticio. El motor, la reconstrucción LNS y la auditoría aplican este criterio. Las colisiones se comprueban para todo el lote colocado.

## 10. `Pallets_Objetivo` — cantidad fija de pallets por CD

**Regla de negocio explícita**: "esa cantidad de pallet total no puede variar, siempre tiene que ser la que dice en la planificación" — los camiones se programan en base a ese número real (validado exacto contra 9 CDs de un cubicaje manual real: Callao=5, Cono Norte=7, Cono Sur=7, Rímac=5, Chanchamayo=5, Huánuco=4, Satipo=3, Tingo María=5, Pucallpa=9).

- Es un **input que sube el usuario** (hoja opcional "Pallets_Objetivo" en el mismo Excel, columnas `CD`/`Pallets_Objetivo`) — nunca algo que el sistema calcule solo.
- Si un CD no aparece en esa hoja, se comporta exactamente igual que siempre (el motor decide cuántos pallets abrir).
- Si aparece, el motor reparte TODA la demanda de ese CD en exactamente esa cantidad de pallets, usando un solver de backtracking real (DFS con poda) más una fase de LNS ("ruina y reconstrucción": rompe algunos SKUs ya colocados al azar y los reconstruye, se queda con lo mejor de varias semillas) cuando el backtracking solo no coloca toda la demanda.
- **Costo real, documentado sin maquillar**: puede tardar minutos por pallet cuando la compresión exigida es alta. El sistema pone un tope de reloj real (no solo de nodos de búsqueda) para evitar corridas de horas — si el tiempo se agota, devuelve el mejor resultado encontrado hasta ese punto, nunca falla ni da un resultado inválido. La app avisa en pantalla, ANTES de procesar, qué CDs quedaron con cantidad fija (por el costo real involucrado).
- **Limitación conocida, no resuelta**: en el caso más exigente probado (BK31, 98 cajas en 1 solo pallet, replicando un armado manual real), el motor coloca 87/98 cajas — 11 cajas de un solo SKU de footprint grande (Picaras) quedan sin ubicar porque SKUs de footprint chico fragmentan el piso antes de que le toque competir. Se investigó a fondo (7 iteraciones de diseño distintas, incluyendo reserva de territorio y empaquetado por estantes) sin encontrar un criterio de orden que no perjudique a algún SKU — es una limitación estructural de cualquier heurística secuencial de asignación de territorio, no un bug puntual. Queda documentada como **pendiente de decisión** (invertir en un solver de reparto de área simultáneo, o cambiar el criterio de éxito para priorizar cobertura de SKUs sobre cantidad cruda de cajas) — el comportamiento de producción hoy sigue siendo el resultado del backtracking+LNS normal (87/98 en ese caso), sin ningún cambio activado.

## 11. Demanda que no se logra colocar

Antes se perdía en silencio (un bug real: el motor la calculaba internamente pero nunca llegaba a ningún reporte). Ahora, toda demanda que no encuentra lugar — sea porque no cabe en ningún pallet abierto, o porque los pallets fijos de `Pallets_Objetivo` genuinamente se llenan, o porque quedó excluida antes de llegar al armado (una caja que no entra en el pallet en ninguna orientación) — se reporta en una hoja **"Cajas_No_Colocadas"** del Excel final: CD, SKU, descripción, categoría, cajas y unidades no colocadas. La hoja solo aparece si hay algo que reportar.

## 12. Reconciliación geométrica Maestro ↔ UMA

Sin cambios de fondo respecto a la versión anterior: el Maestro (`Cajas por cama`) manda si es geométricamente creíble; solo si ni la geometría medida ni la geometría medida + sobresaliente de negocio (2cm/lado) alcanzan a explicarlo, se degrada al techo geométrico real — nunca se inventa un footprint artificial solo para que el número del Maestro "cierre" matemáticamente. El sobresaliente de 2cm/lado se usa tanto para la plausibilidad del Maestro como para el armado real.

Un bug real corregido en esta ventana de trabajo: SKUs con una dimensión declarada en 0.0 en UMA (dato real, no vacío) desaparecían del plan sin ningún aviso — 18 SKUs, ~295 cajas perdidas en silencio en el dataset de producción. Se corrigió tratando cualquier dimensión `<= 0` como insuficiente, igual que un dato faltante.

## 13. Sobresaliente de negocio (borde exterior del pallet)

`SOBRESALIENTE_MAX_CM = 2.0`, confirmado por el usuario. La base física sigue siendo 120×100 cm. El área permitida es 124×104 cm, centrada sobre la parihuela: X de -2 a 122 cm y Y de -2 a 102 cm. No se pueden acumular los 4 cm en un solo extremo. El armado, la validación de entrada, la auditoría y el inspector utilizan estos límites.

## 14. Paralelización — por qué la app ya no tarda lo mismo

Pedido explícito tras ver que un cubicaje real de 12 CDs con `Pallets_Objetivo` iba a tardar horas: cada CD es 100% independiente (ni comparte demanda ni el contador de IDs de pallet), así que ahora se procesan varios CDs a la vez en procesos separados. Cuando un único CD necesita LNS (varias semillas independientes), esas semillas también se paralelizan — pero nunca los dos niveles a la vez (evita saturar los núcleos reales con N×5 procesos peleando por el mismo hardware). Esto bajó una corrida real de 12 CDs de "colgada más de 21 horas" (antes del tope de reloj) a 152 segundos, y una corrida de un solo pallet forzado de 324s a 118.5s.

## 15. El benchmark real y motores descartados (sin cambios de fondo)

Se mantiene todo lo documentado en versiones anteriores: el benchmark de 42 pallets físicos reales (`src/benchmark.py`), los motores V3/V4/V4b/V4c/torres/AUTO/AUTO_CONSOLIDADO/SKU_CONSOLIDADO ya eliminados del repo, y **`packing_ph_fraccion.py`** (motor aproximado por fracción de PH, calibrado contra un cubicaje real) — se probó, se conectó, se debuggeó, y finalmente **se revirtió**: el usuario, viendo el resultado real en la app, encontró camas con hasta 21% de cobertura de soporte faltante en promedio (742 torres con menos del 50% de apoyo real, muchas con 0%) — "eso no puede pasar". El archivo sigue en el repo, probado, pero el pipeline no lo usa; se volvió al motor exacto (`packing_bloques.py`) con 2 ideas rescatadas de `packing_ph_fraccion.py` (orientación flexible y tope real de `Cajas por PH`).

## 16. Verificación en esta revisión

Se corrió el motor en vivo, contra el dataset de referencia (`Cubicaje18.07.2026.xlsx`, 9 CDs reales), sobre 2 de los 9 CDs (BK41: 280 cajas → 4 pallets; BK65: 347 cajas → 5 pallets): **demanda exacta en ambos, 0 violaciones geométricas**, alturas entre 207.6cm y 214.5cm, ocupación de huella (`ocupacion_xy`) entre 75% y 94%. No se pudo completar una corrida de los 9 CDs en una sola sesión por el costo de tiempo real del solver actual (documentado en la sección 9.3 y 10) — el último número agregado verificado en `Parches/v5/PATCH_LOG.md` para el archivo de pruebas interno del proyecto (`ARCHIVO_REAL`, 12 CDs, tras excluir Cigarros y aplicar los refinamientos de la sección 9.4/9.5) es **49 pallets totales, 4 parciales (8%), 94% de aprovechamiento de altura, peso promedio 970.5/1430kg**, con la suite completa de 177 tests en verde.

## 17. Estado abierto / pendiente de decisión

- **"Grandes primero" en `Pallets_Objetivo`** (sección 10): investigación seria, sin cerrar. Tres caminos posibles, ninguno tomado todavía: invertir en un solver de reparto de área real, cambiar el criterio de éxito para priorizar cobertura de SKUs, o dejarlo como está (documentado, sin activar).
- **Mecanismo de carga de `Pallets_Objetivo`**: ya conectado end-to-end (hoja opcional en el Excel); no hay pendiente de diseño acá, solo de uso.
- **Dato fuente de Electrolight y posibles SKUs similares** (sección 6): Largo/Ancho de UMA posiblemente invertidos para más de un SKU del Maestro de este cliente — pendiente de auditoría del dato fuente, fuera del alcance del algoritmo.
- **`layout_solver.py`**: sigue en el repo, probado, sin ningún llamador de producción — disponible si se decide usarlo en el futuro.
