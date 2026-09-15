# Diseño: reparto de área conjunto (treemap/strip-packing) para "grandes primero"

**Target de éxito concreto:** `ejemplo_manual_bk31/` (misma carpeta) tiene
el pallet BK31 armado a MANO, caja por caja, con la demanda real completa
(98/98) -prueba de que es geométricamente posible, y referencia de las
decisiones de armado que el algoritmo nuevo debería poder reproducir. Leer
su README antes de diseñar el squarify.

## Por qué esto, y no otro ajuste de `_reservar_skus_grandes`

Documentado en detalle en `PATCH_LOG.md` ("Grandes primero (Pallets_Objetivo)
-investigación seria, resultado parcial"): 7 iteraciones seguidas, cada una
con un criterio de orden distinto (SKU por SKU, ronda-robin por caja, por
columna, por estante con distintos criterios de prioridad -ancho de caja,
área total demandada-), y en TODAS el patrón se repite: el SKU que compite
PRIMERO por el piso compartido le quita espacio al que compite último, sin
importar el criterio de orden usado. Con BK31 (`Pallets_Objetivo=1`, 14
SKUs, 98 cajas) el mejor resultado alcanzado fue 77/98 (Vino corto por 21
cajas) -mejor que el greedy actual (87/98, pero con 3 SKUs de Picaras
enteros en cero), pero lejos de las 98/98 que sí se lograron armando el
pallet a mano.

**Diagnóstico de fondo:** cualquier heurística SECUENCIAL (reservar SKU A
del todo, después SKU B, ronda-robin de a 1 unidad, ronda-robin de a 1
columna, con cualquier orden de prioridad) sigue siendo, en esencia, un
proceso donde el primero en llegar consume recursos sin saber cuánto van a
necesitar los que vienen después. Lo que se hizo a mano fue distinto en
esencia: se decidió CUÁNTO ESPACIO le tocaba a Picaras Y a Vino
considerando a ambos a la vez ("necesitamos llenar todo el fondo, pero
empecemos por la banda que más entra" -una decisión de reparto, no una
cola de servicio). El equivalente algorítmico real de "repartir área entre
varios ocupantes a la vez, proporcional a lo que cada uno necesita" es la
familia de algoritmos de **treemap cuadrado (squarified treemap, Bruls/
Huizing/van Wijk 1999)** o, equivalentemente, **2D strip/guillotine packing
con reparto de área proporcional** -bien documentados, no es un algoritmo
que haya que inventar desde cero.

## Diseño propuesto

**Paso 1 -selección de orientación y área necesaria por SKU** (ya existe,
reusar tal cual de `_reservar_skus_grandes` actual): para cada SKU
pendiente, elegir la orientación que minimiza `columnas_necesarias x largo
x ancho`, con `columnas_necesarias = ceil(unidades / floor(presupuesto_
altura / alto_caja))`. Esto da, por SKU: `(orientacion_elegida,
capas_por_columna, columnas_necesarias, area_total_necesaria)`.

**Paso 2 -partición cuadrada del piso del pallet (120x100) por área
proporcional (NUEVO):** en vez de una cola ordenada, calcular una partición
rectangular del piso completo donde cada SKU recibe un sub-rectángulo de
área proporcional a `area_total_necesaria / suma_de_todas_las_areas`
-algoritmo "squarify" clásico:
1. Ordenar los SKUs por área necesaria (descendente) -el orden acá NO
   decide quién gana territorio (eso ya no es secuencial), solo mejora la
   calidad visual/geométrica de la partición (evita franjas
   desproporcionadamente angostas).
2. Particionar recursivamente el rectángulo disponible: tomar el lado más
   corto del rectángulo actual como la dirección de corte, ir agregando
   SKUs a la "fila" actual mientras el aspect ratio resultante mejore (el
   criterio "worst aspect ratio" clásico del algoritmo squarify), cortar
   una franja perpendicular al lado corto del ancho que le corresponda a
   esa fila, y repetir con el rectángulo restante.
3. Redondear las fronteras de cada sub-rectángulo a coordenadas
   compatibles con el footprint real de caja de cada SKU (un sub-
   rectángulo "ideal" de 43.7cm no sirve si la caja mide 31cm -ajustar
   cada frontera al múltiplo de `largo`/`ancho` más cercano que no le quite
   área a los vecinos, o dejar que el Paso 3 use lo que realmente entra
   dentro del rectángulo asignado, cediendo el resto como "sobra" que
   vuelve al pool general del Paso 4).

**Paso 3 -llenado column-por-columna DENTRO de cada sub-rectángulo (reusa
código real):** exactamente la lógica "cama por cama" que YA existe y está
probada en `_reservar_skus_grandes` (reutilizar columnas antes de abrir
nuevas, respetar `Cajas_Cama_Efectivo` por capa Z, `_cuboide_admite_
candidato` para soporte/nivel/altura) -pero acotada al sub-rectángulo
asignado en vez de a estantes compartidos con otros SKUs. Esto significa
que el SKU nunca "invade" el territorio de otro, eliminando por
construcción el problema de "quién llega primero".

**Paso 4 -sobras y ajuste fino (reusa código real):** el área que un SKU no
usó de su sub-rectángulo asignado (porque su footprint no encaja
perfectamente, o porque terminó su demanda antes de agotar el espacio)
vuelve como territorio libre. `_actualizar_libres_maxrects` ya lo registra
correctamente (se sigue usando tal cual). El `_resolver_pallets_
backtracking` normal corre DESPUÉS de este reparto, igual que hoy, para
combinar cualquier resto -su fortaleza de "tapizar hueco por hueco" sigue
intacta para lo que el treemap no haya usado perfectamente.

## Riesgos/decisiones a validar con datos reales (no asumir)

1. **Redondeo de fronteras** (paso 2.3) es la parte más delicada -un
   partición "ideal" por área rara vez cae en un múltiplo exacto del
   footprint real de cada SKU. Probar empezando por el criterio más simple
   (redondear hacia abajo al múltiplo de footprint más cercano, ceder el
   resto) y medir cuánta área se pierde así contra BK31 antes de complicar.
2. **SKUs con demanda muy chica** (ej. Vodka, 1 caja) no necesitan un
   sub-rectángulo propio -aplicar el treemap solo a SKUs por encima de
   algún umbral de área (recuperar `config.PRIORIZAR_GRANDES_FRACCION_
   AREA_PALLET`, ya existe sin uso) y dejar los chicos para el
   backtracking normal del Paso 4, que ya los maneja bien hoy.
3. **Interacción con `skus_protegidos`/LNS** -mismo mecanismo ya construido
   y probado esta sesión, se reusa tal cual: los SKUs que pasaron por el
   treemap quedan protegidos de que el LNS los deshaga.
4. **Métrica de éxito de `_empacar_n_pallets`** -aunque el treemap debería
   acercarse mucho más a 98/98 que cualquier intento secuencial, si aun así
   no llega al 100%, sigue pendiente la pregunta de la sesión anterior:
   ¿la comparación final debe seguir siendo "más cajas gana", o priorizar
   "menos SKUs en cero" cuando `priorizar_grandes=True`? Decidir con datos
   reales de esta nueva implementación, no antes.

## Plan de verificación (mismo método que ya funcionó esta sesión: TDD con
## tests sintéticos ANTES del caso real)

1. Tests unitarios del squarify solo (sin geometría de cajas): dado un
   rectángulo y una lista de áreas relativas, confirmar que la partición
   resultante (a) cubre el 100% del rectángulo sin solapes, (b) da a cada
   SKU un área proporcional dentro de una tolerancia razonable, (c) nunca
   produce un sub-rectángulo con aspect ratio absurdo (ej. 1cm x 100cm)
   cuando hay alternativas mejores.
2. Tests sintéticos de 2-4 SKUs inventados (mismo patrón que `test_
   grandes_primero_*` de esta sesión, `tests/test_packing_bloques.py`)
   reproduciendo en miniatura los 3 casos reales que ya se usaron: alturas
   de caja incompatibles, tope de capa compartido bajo, footprints sin
   múltiplos comunes -deben seguir en verde con la implementación nueva
   (son los mismos requisitos, ahora resueltos por partición en vez de por
   orden).
3. Recién con todo eso en verde, correr BK31 real (`Plantilla_Ejemplo_
   Agente_Cubicador (1) (3).xlsx`, `Pallets_Objetivo=1`) -objetivo: 98/98.
   Si no se llega, medir exactamente cuánto y por qué (mismo nivel de
   evidencia que esta sesión, no conformarse con "está mejor").
4. Los otros 4 CDs del mismo archivo (`BK50=14, BK52=1, BK49=9, BK53=2`) y
   la suite completa (177 tests + los nuevos) -sin regresión en el camino
   abierto (sigue sin tocarse, `priorizar_grandes` solo en `Pallets_
   Objetivo`).

## Recomendación sobre cómo continuar

Esto es una implementación nueva (el algoritmo squarify en sí, más su
integración con el resto del motor), no un ajuste de lo que ya existe -en
la línea de "varias horas de trabajo enfocado con tests", como ya se
conversó. Dado que esta sesión ya acumuló un historial largo (7 iteraciones
previas + 2 refinamientos anteriores), conviene arrancar la implementación
en una sesión nueva, con este documento como punto de partida -evita cargar
con todo el contexto ya explorado y deja más presupuesto para escribir e
iterar el algoritmo con tests. El código y los tests de esta sesión
(`_reservar_skus_grandes` con sus fixes, `skus_protegidos`, los 4 tests
`test_grandes_primero_*`) quedan en el repo, probados y sin afectar
producción -reutilizables como referencia o como fallback si el treemap no
alcanza a superarlos.
