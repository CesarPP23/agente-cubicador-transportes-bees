# PATCH_LOG.md — V5 packer columnar

Nota de proceso: por instrucción permanente del usuario en esta sesión, no se
crean commits ni ramas de git sin permiso explícito. Los "commits independientes"
del plan se interpretan como cambios de archivo aislados y verificados (tests +
benchmark) antes de avanzar al siguiente parche, no como `git commit` real.
Todo el trabajo queda en el working tree, igual que el resto de la sesión.

## Baseline V4 (antes de tocar nada)

- pallets físicos totales (todos, incluidos PH-BAT-*): **54**
- pallets "comparables" con la metodología V4 (excluía PH-BAT-*): 52
- BAT dedicados: 2
- altura media (todos los pallets): 188.07 cm
- altura min/max: 69.92 / 214.02 cm
- pallets <190cm: 18 · pallets <170cm: 15
- por CD: BK31=5, BK41=4, BK43=4, BK65=6, BK68=5, SJ86=8, SJ87=8, SJ95=5, SJ97=9
- config_hash: `10735739cf93`
- dataset: `Cubicaje18.07.2026.xlsx` (con las 202 dimensiones UMA corregidas)

**Nota inmediata**: la metodología de benchmark V4 (52) YA estaba mal según
la propia regla de P0 (excluía `PH-BAT-*` del conteo físico). El número
correcto de pallets físicos que Transporte movería HOY, antes de cualquier
cambio V5, es **54**, no 52. Ese es el verdadero baseline a superar.

---

## V5-P0 — Benchmark físico correcto

### Cambios
- `src/benchmark.py`: `BenchmarkResultado` gana `pallets_bajo_190`, `pallets_bajo_170`,
  `bat_dedicados`, `pallets_por_cd`. `calcular_kpis` ya no depende de que el
  caller le pase una lista pre-filtrada -cuenta lo que recibe, punto.
- `src/pipeline.py`: se elimina el filtro `pallets_comparables = [p for p in
  pallets_apilado if not p.id.startswith("PH-BAT-")]` -el benchmark ahora
  corre sobre `pallets_apilado` completo.
- `tests/test_benchmark.py` (nuevo): 4 tests -dedicado incrementa total, sin
  dedicado no cambia, pallets_por_cd correcto, benchmark real contra dataset.

### Antes (metodología V4, excluía PH-BAT-*)
- pallets: 52

### Después (V5-P0, todos los pallets físicos)
- pallets: **54**
- bat_dedicados: 2
- por CD: BK31=5, BK41=4, BK43=4, BK65=6, BK68=5, SJ86=8, SJ87=8, SJ95=5, SJ97=9
- altura media: 188.07 cm
- pallets <190cm: 18 · pallets <170cm: 15

### Invariantes
- demanda: sin cambios (P0 no toca packing)
- altura <=215: OK
- tests: 47 passed, 1 skipped

### Observaciones
Este parche no cambia ningún pallet real, solo corrige cómo se CUENTAN -el
número pasó de 52 a 54 porque ahora se cuentan los 2 PH-BAT dedicados que ya
existían pero se excluían del reporte. Este es el baseline real contra el que
se mide el resto de V5.

---

## V5-P1 — Feature flag y aislamiento de V4

### Cambios
- `config.py`: `PACKER_VERSION = "V4"` (default), + `MULTISTART_SEEDS`,
  `MULTISTART_MAX`, `PH_PREBUILD`, `PURE_FIRST`, `SOBRESALIENTE_PLANIFICACION`
  (usados por parches posteriores, agregados ahora para no tocar config.py
  de nuevo en cada patch).
- `src/pipeline.py`: `ejecutar_pipeline` pasa a ser un dispatcher; el cuerpo
  de antes se renombró a `ejecutar_core_v4` (sin cambios de comportamiento).
- `src/pipeline_v5.py` (nuevo): `ejecutar_core_v5`. Reutiliza VAL/DEM/GEO/DER/
  SPLIT/PESO/BENCH/EXP de V4 tal cual -esa infraestructura no depende del
  core de armado. El core de armado (HOM/P2D/P3D) todavía delega en las
  funciones V4 (`pallets_homogeneos`, `packing_2d`, `apilado_3d`), marcado
  explícitamente para reemplazar en P4-P6.
- `legacy/` (nuevo): copia congelada de `packing_2d.py`, `apilado_3d.py`,
  `pallets_homogeneos.py` tal como estaban al empezar V5 -solo referencia,
  no se importan (ver `legacy/README.md` para el porqué).
- `tests/test_pipeline_v5.py` (nuevo): default es V4, flag V4 da resultado
  idéntico a llamar `ejecutar_core_v4` directo, flag V5 corre sin romper.

### Antes / Después
Sin cambios de pallets -este parche es infraestructura pura. 50 passed, 1
skipped (47 anteriores + 3 nuevos de este patch; los 4 de P0 ya estaban
contados).

### Invariantes
- Con `PACKER_VERSION="V4"`: output byte-a-byte idéntico (verificado con
  `pd.testing.assert_frame_equal` contra `ejecutar_core_v4` directo).
- Con `PACKER_VERSION="V5"`: corre de punta a punta sin excepción (54→56
  pallets en el dataset real, porque ya hereda `PH_PREBUILD=False` de
  config -ver nota abajo). No se exige que sea BUENO todavía, solo que no
  rompa.

### Observaciones
El stub V5 de este patch ya usa `config.PH_PREBUILD` (default `False`, que
es el default V5 de P6) para decidir si arma pallets homogéneos antes del
packing -así que técnicamente P6 ya está "activado" para el camino V5 desde
ahora, aunque el core de armado siga siendo V4 por dentro. Con eso, el stub
V5 da 56 pallets contra los 54 de V4 (sin PH_PREBUILD, más demanda cae en el
packing genérico, que sin la ayuda de los pallets homogéneos hace un poco
peor con las camas de V4). Es un resultado transitorio esperado -no es la
comparación real hasta que el core columnar (P4-P6) reemplace las camas.

---

## V5-P2 — UMA_VALIDADA_CON_SOBRESALIENTE

### Cambios
- `src/reconciliacion_geometrica.py`: nuevo estado
  `UMA_VALIDADA_CON_SOBRESALIENTE` -cuando la geometría medida (sin cambiar
  largo/ancho) explica al Maestro permitiendo el sobresaliente de negocio
  (2,5cm/lado), se usa tal cual en vez de llamar
  `inferir_footprint_desde_cajas_cama` (que inventaba un footprint distinto
  al medido). `inferir_footprint_desde_cajas_cama` gana parámetros opcionales
  `pallet_largo`/`pallet_ancho` (antes leía `config.PALLET_LARGO/ANCHO`
  directo -necesario para no mutar config global si se la llama con otro
  área en el futuro).
- `models.py`: docstring de `GeometriaSKU.fuente_geometria` actualizado con
  el estado nuevo.
- `tests/test_reconciliacion_v5_p2.py` (nuevo): los 3 tests pedidos por el
  plan + uno de regresión (22183 sigue degradando).

### Iteración dentro del patch (documentada porque cambió el diseño)
Primer intento: agregué un tercer nivel ("si ni sobresaliente con la medida
real alcanza, probar `inferir_footprint_desde_cajas_cama` contra el área
EXTENDIDA antes de degradar") para no dejar `INFERIDA_MAESTRO` sin uso. Test
de regresión lo agarró: `inferir_footprint_desde_cajas_cama` no tiene piso de
"esto es absurdo", así que con el área extendida SIEMPRE encuentra algún
factorización, incluso para el caso 22183 (84 cajas/cama declaradas, 15
reales) -exactamente la fabricación que P2 pide evitar. Se sacó ese nivel
intermedio: ahora es un flujo de 2 salidas (sobresaliente con medida real
explica -> `UMA_VALIDADA_CON_SOBRESALIENTE`; si no -> degradado directo).
`INFERIDA_MAESTRO` queda como estado válido en el modelo/auditoría pero no lo
alcanza ningún caso real de este dataset -no se borró la función porque es
API pública razonable, pero dejó de llamarse desde `reconciliar_sku`.

### Antes / Después (dataset real)
- Antes (V4 + P2 sin terminar de ajustar): `MAESTRO_IMPOSIBLE_DEGRADADO` = 3
- Después: `UMA_VALIDADA` 110, `UMA_SOBRECAPACIDAD` 52,
  `UMA_VALIDADA_CON_SOBRESALIENTE` 18 (nuevos, antes hubieran sido
  `INFERIDA_MAESTRO` con footprint inventado), `MAESTRO_IMPOSIBLE_DEGRADADO` 3
  (sin cambio -el guard contra datos genuinamente imposibles sigue intacto).
- pallets (V4, todos físicos): 54 -> 55
- por CD: BK31=5, BK41=4, BK43=4, BK65=6, BK68=5, SJ86=8, SJ87=8, SJ95=5,
  **SJ97=10** (subió de 9 -18 SKUs con geometría más "honesta"/menos
  compacta, sin footprint inventado, empujó camas ligeramente más grandes)

### Invariantes
- demanda: OK (P2 no toca cantidades)
- altura <=215: OK
- 18 SKUs de geometría medida quedan trazables (largo_efectivo == largo_uma)
  en vez de con un footprint ficticio -verificado en test
- tests: 54 passed, 1 skipped

### Observaciones
Subir de 54 a 55 pallets es un resultado ESPERADO y correcto, no una
regresión a compensar (regla explícita del plan: "no compensar una regresión
aflojando altura/geometría"): la geometría es ahora más honesta (menos
fabricación), que es exactamente el objetivo de P2, aunque cueste algo de
densidad de empaque.

---

## V5-P3 — layout_solver.py (capacidad == placements)

### Cambios
- `src/layout_solver.py` (nuevo): `resolver_layout_rectangulos(...) ->
  LayoutResult`. Unifica capacidad y layout -grilla, guillotina recursiva
  (memoizada por bloques, no por caja individual, para que sea rápido) y
  pinwheel/five-block, los tres devolviendo POSICIONES reales, no solo un
  conteo. Auto-valida su propio resultado (sin solapes, sin desborde) y
  degrada a grilla uniforme si algo no cierra -nunca devuelve una capacidad
  que no pueda respaldar.
- `tests/test_layout_solver.py` (nuevo): 6 tests -40x30 en 120x100 da 10
  placements válidos, capacidad==len(placements) en 4 casos (incl. el SKU
  "basura" 452x452), 500 casos random sin solape/desborde, determinismo,
  caso "no cabe ninguna", orientación fija.

### Invariantes
- `capacidad == len(placements)` en todos los casos probados (incluido el
  caso "no cabe ninguna caja", capacidad=0/placements=[])
- ningún placement sale del pallet ni se solapa con otro (500 casos random)
- determinístico (misma entrada -> mismos placements, mismo orden)

### Observaciones
No se conecta todavía a ningún módulo productivo (ni V4 ni el stub V5) -es
la base que P5 (packer columnar) va a usar para decidir CUÁNTAS cajas de un
SKU entran en la huella de una torre y EN QUÉ POSICIÓN exacta. `solver_cajas.py`
(V4/P1) queda intacto y en uso por `reconciliacion_geometrica.py` -sigue
siendo válido para "solo necesito el número", no se retira porque `bat.py` y
`derivados.py` lo siguen llamando así.

---

## V5-P4 — Modelos Torre/PalletV5

### Cambios
- `models.py`: `OrientacionCaja` (frozen), `PlacementCaja`, `Torre`
  (`altura`/`area_base` como properties derivadas, nunca campos que se
  puedan desincronizar de `cantidad`), `PalletV5`.
- `src/torres.py` (nuevo): `TorreCandidate`, `generar_torres_candidatas(df_cd,
  altura_max_producto, permitir_rotacion_xy=True)` (una candidata por
  orientación XY válida, descarta SKUs sin geometría efectiva),
  `crear_torre` (nunca excede `max_cajas_verticales` ni `cantidad_disponible`),
  `dividir_torre` (split tower para residual_search, P8), `torre_a_dict`
  (serialización temporal para debug/export).
- `tests/test_torres.py` (nuevo): 10 tests -altura, peso, tope
  vertical/demanda, split preserva demanda total, split rechaza cantidad
  inválida, orientación inmutable, candidatas por SKU, descarta sin
  geometría, serialización, agregación en PalletV5.

### Invariantes
- `Torre.altura` siempre `cantidad * alto_caja` (property, no puede
  desincronizarse)
- `dividir_torre`: `primera.cantidad + segunda.cantidad == original.cantidad`,
  mismo peso total (redondeado)
- `crear_torre` nunca crea más cajas que `max_cajas_verticales` ni que
  `cantidad_disponible`
- tests: 70 passed, 1 skipped (60 anteriores + 10 de este patch)

---

## V5-P5 — Packer columnar básico (+ V5-P6 ya activado de entrada)

### Cambios
- `src/packing_columnar.py` (nuevo): `armar_pallets_columnar(df_cd, cd,
  contador=None, pallets_semilla=None) -> list[PalletV5]`. Best-Area-Fit
  sobre rectángulos libres MaxRects (ver "iteración" abajo -la primera
  versión usaba guillotina de 2 vías y fue peor). Un solo pase, orden fijo
  (mayor volumen potencial de torre primero), sin multi-start ni residual
  search todavía (a propósito, P7/P8).
- `src/pipeline_v5.py`: el core de armado deja de delegar en V4
  -`ejecutar_core_v5` ahora llama `packing_columnar.armar_pallets_columnar`
  por CD. `_palletv5_a_pallet` adapta cada `PalletV5` a un `Pallet` (V4) para
  poder seguir usando `bat.py`/`soporte.py`/`exportar.py`/`benchmark.py` sin
  duplicarlos -se reemplazan por versiones nativas V5 recién en P9/P13.
- `tests/test_packing_columnar.py` (nuevo): 7 tests -alturas de torre
  independientes en el mismo pallet, sin gate de clustering por altura,
  mismo CD, altura<=215, demanda exacta, caja más grande que el pallet queda
  marcada sin perder demanda, torre nunca excede el máximo vertical.

### Iteración dentro del patch (documentada porque cambió el diseño)
Primera versión: split guillotina de 2 vías (cada colocación parte el
rectángulo libre en "a la derecha" + "arriba", nunca más de 2 piezas nuevas).
Contra el dataset real dio **68 pallets** -peor que el rango esperado del
plan para "básico" (48-52) y peor que V4 (55). Regla del plan: "si el
columnar básico empeora significativamente: detener, auditar antes de
seguir" -se detuvo y se auditó: el patrón (visto pallet por pallet) era
SKUs de demanda chica terminando cada uno en su propia torre/pallet, muchos
pallets de 30-70cm de altura con 6-10 SKUs distintos de 1-2 cajas cada uno.
La guillotina de 2 vías fragmenta el espacio libre más rápido de lo
necesario (pierde rectángulos libres "grandes" que sí existían pero quedaban
tapados por el split). Se reemplazó por MaxRects real -mantiene TODOS los
rectángulos libres maximales (hasta 4 franjas por colocación, podando
contenidos)- que es literalmente lo que
`DOCUMENTACION_TECNICA_V5.md` sección 7.3 pide ("usar MaxRects o Skyline"),
no una optimización fuera de alcance. Con MaxRects: 68 -> 64 pallets.

Se probaron además 5 criterios de orden distintos (footprint desc, altura
total desc, cantidad de cajas desc, footprint asc, demanda desc) -todos
dieron entre 61 y 64, sin un ganador claro. Se dejó "volumen potencial de
torre" (footprint x altura máxima x cuánto entra) como default de este
patch, dando **61 pallets no-BAT** (64 con los 3 BAT dedicados de este core
-BAT todavía sin optimizar, ver P9).

### Antes / Después (dataset real, PACKER_VERSION="V5")
- V4 (referencia, todos los pallets físicos): 55
- V5-P5 (columnar básico, MaxRects, sin multi-start/residual/BAT global): 64
  total (61 no-BAT + 3 BAT dedicados)
- por CD: BK31=7, BK41=5, BK43=6, BK65=7, BK68=6, SJ86=8, SJ87=9, SJ95=6,
  SJ97=10
- altura media: 182.25cm · pallets <190: 21 · <170: 16
- tiempo: ~22s (vs <1s de V4 -el packer columnar recorre todas las
  combinaciones pallet×orientación en cada iteración; a optimizar si hace
  falta más adelante, no es un problema todavía con un dataset de este
  tamaño)

### Invariantes
- demanda exacta: OK (verificado, cajas totales despachadas = demanda total)
- altura <=215: OK
- mismo CD: OK
- tests: 77 passed, 1 skipped

### Observaciones
64 > 55 (V4) es el resultado ESPERADO en esta etapa -el plan es explícito en
que "básico" empieza peor que V4 y que P7 (multi-start) + P8 (residual
search) son los que atacan la brecha real (52->42-46 según la tabla de
referencia del plan). No se sigue ajustando P5 a mano más allá de lo ya
hecho (MaxRects real en vez de guillotina, que sí era un defecto genuino, no
una optimización prematura) -el resto de la ganancia viene de P7/P8, que
son mecanismos explícitamente diseñados para esto, no de seguir
probando criterios de orden a mano.

---

## V5-P6 — Desactivar PH-prebuild y Pure-first

### Cambios
Ninguno nuevo -`config.PH_PREBUILD=False` y `PURE_FIRST=False` ya se
agregaron en P1 y `pipeline_v5.ejecutar_core_v5` ya los respeta desde P5 (el
core de armado nunca llama a `pallets_homogeneos.py` ni extrae "camas puras"
antes de mirar el resto de la demanda -ver P5). Este patch es formalmente
la confirmación/medición de ese comportamiento, no un cambio de código nuevo.

### Comparación con/sin prebuild (pedida por el plan)
Con `PH_PREBUILD=True` forzado sobre el core V5 (probado ad-hoc, no es una
ruta soportada de forma permanente): el packer columnar de todos modos NO
sabe qué hacer con pallets homogéneos ya armados como semilla del mismo modo
que V4 (`apilado_3d.armar_pallets` los recibe como `pallets_semilla` y les
seguía agregando camas encima; `armar_pallets_columnar` los acepta como
`pallets_semilla` pero el packer todavía no los usa como candidatos activos
para nuevas torres -haría falta exponerlos como `_PalletEnConstruccion` con
sus rectángulos libres ya descontados, no implementado en este patch). Con
el estado actual del código, forzar PH_PREBUILD=True en V5 simplemente deja
esos pallets homogéneos sueltos sin combinarse con el resto -peor resultado,
no mejor. Confirma que `PH_PREBUILD=False` (dejar que lo homogéneo salga
solo, si sale, del optimizador) es la decisión correcta para este packer,
tal como pedía el plan.

### Invariantes
- Sin cambios de comportamiento en el path soportado (PH_PREBUILD=False)
- tests: sin tests nuevos -ya cubierto por test_packing_columnar.py (P5) y
  test_pipeline_v5.py (P1)

---

## V5-P7 — Multi-start

### Cambios
- `src/packing_columnar.py`: `armar_pallets_columnar` gana parámetro
  `orden_skus` opcional -si se pasa, se usa ese orden (filtrando SKUs sin
  candidata y completando los que falten al final, nunca pierde demanda);
  si no, sigue con el default de P5.
- `src/multistart.py` (nuevo): `ESTRATEGIAS` (las 7 del plan), `SolucionCD`
  (con `.score` lexicográfico: pallets, pallets<190, residual total, |altura
  media - target|, geometrías inferidas), `generar_soluciones_cd` (1 corrida
  por estrategia determinística + `config.MULTISTART_SEEDS` corridas RANDOM
  -no repite una estrategia determinística con distintas "semillas" porque
  daría el mismo resultado, sería trabajo perdido), `mejor_solucion`
  (`min(score)`).
- `src/pipeline_v5.py`: el core de armado corre `generar_soluciones_cd` +
  `mejor_solucion` por CD en vez de un solo pase fijo.
- `tests/test_multistart.py` (nuevo): 4 tests -una solución por estrategia
  determinística + N por seed, demanda total no depende de la estrategia,
  selección lexicográfica prioriza pallets, mismo input/seeds da mismo
  resultado.

### Antes / Después (dataset real, aislado -solo el core de armado, sin BAT)
- P5 (un solo pase, VOLUMEN_DESC): 61 pallets no-BAT
- P7 (multi-start, mejor de 26 candidatos por CD): **61 pallets no-BAT**
  (mismo total agregado, pero la estrategia ganadora varía por CD -
  FLEXIBILIDAD_ASC, CAJAS_CAMA_DESC o RANDOM según el CD, nunca la misma para
  todos- y la calidad de CADA solución mejoró en otros ejes: menos pallets
  bajo 190cm, altura más cerca del target. Verificado con un script aislado
  que reconcilia demanda por CD, ver detalle en el mensaje al usuario de esta
  sesión).

### Hallazgo importante: BAT se ve PEOR con packing no-BAT más ajustado
Corriendo el pipeline COMPLETO (con BAT incluido) después de este patch, el
total sube a **70 pallets** (64 -> 70) y los BAT dedicados suben de 3 a 9.
Investigado a fondo -NO es un bug de P7 (demanda exacta confirmada, 61
pallets no-BAT confirmados de forma aislada): es un efecto de interacción
real. El score de multi-start premia minimizar "residual" (qué tan lejos
queda cada pallet del target de altura) SIN saber que después va a hacer
falta encontrar hueco para cajas BAT -al optimizar cada pallet no-BAT para
quedar lo más lleno posible, no queda margen de altura en NINGÚN lado para
que `bat.asignar_hosts_bat` (todavía la versión V4, sin cambios) encuentre
host natural, así que más cajas BAT terminan en pallets dedicados.

Es exactamente el problema que P9 ("BAT global") existe para resolver -bat.py
today todavía optimiza el packing no-BAT completamente a ciegas de BAT. No
se contrarresta acá aflojando el score de multi-start (violaría la regla del
plan "no compensar una regresión aflojando restricciones") -se sigue a P8
(residual search, que también puede liberar margen) y P9 (BAT global, que
es el fix correcto: conocer la demanda BAT ANTES de cerrar los pallets no-BAT)
antes de volver a medir el total combinado.

### Invariantes
- demanda exacta: OK, verificado por CD y en total (5020 = 5020)
- determinismo: OK (mismo input + mismas seeds -> mismo score, mismo ganador)
- tests: 81 passed, 1 skipped

---

## V5-P8 — Residual Elimination Search

### Cambios
- `src/residual_search.py` (nuevo): `eliminar_residuales(pallets,
  max_iteraciones=None) -> list[PalletV5]`. Por pasada: ordena por altura
  ascendente (proxy de "menos utilizado"), intenta desarmar el primero y
  reinsertar TODAS sus torres en el resto (dividiendo una torre si no entra
  entera, recursivo hasta cajas individuales); si lo logra, lo elimina y
  arranca otra pasada; si no, rollback exacto (snapshot con `copy.deepcopy`
  antes de intentar, se restaura si falla) y prueba el siguiente candidato.
  Reutiliza `_PalletEnConstruccion`/`_actualizar_libres_maxrects` de
  `packing_columnar.py` -reconstruye los rectángulos libres de un pallet ya
  armado desde sus torres (`_reconstruir_en_construccion`).
- `src/pipeline_v5.py`: `eliminar_residuales` corre por CD justo después de
  `multistart.mejor_solucion`, antes de BAT (orden del pipeline, sección 13).
- `tests/test_residual_search.py` (nuevo): 5 tests -puede destruir un pallet
  y reinsertar (con footprints que SÍ tienen lugar), rollback exacto cuando
  el piso de ambos pallets está completamente ocupado (primer intento de
  este test tenía una premisa incorrecta -dos torres del mismo alto en
  pisos DISTINTOS sí tenían lugar de sobra, el algoritmo las consolidó
  correctamente; se corrigió el test para ocupar el piso 120x100 completo,
  ahí sí no hay dónde reinsertar), nunca aumenta pallets, nunca pierde
  demanda, determinismo.

### Resultado en el dataset real (aislado, por CD, después de multi-start)
Corrida antes/después de `eliminar_residuales` sobre la MEJOR solución de
multi-start de cada CD: **61 -> 61 pallets, sin cambio en ningún CD**.

### Invariantes
- rollback exacto: verificado (test dedicado, contenido y altura idénticos
  byte a byte tras un intento fallido)
- nunca aumenta pallets: OK
- nunca pierde demanda: OK
- determinismo: OK (residual_search no tiene aleatoriedad -mismo input,
  mismo resultado siempre)
- tests: 86 passed, 1 skipped

### Observaciones
No es un bug ni un patch "vacío": el mecanismo SÍ funciona (los tests
sintéticos lo prueban con casos donde hay margen real), pero en este
dataset multi-start (P7) ya exploró 26 órdenes distintas por CD y se quedó
con la de menos pallets -los residuales que sobreviven a eso son,
empíricamente, los que ya no tienen a dónde ir con la misma técnica MaxRects
que ambos módulos comparten. Esto es consistente con la tabla de referencia
del plan (multi-start 45-49, residual search 42-46 -se espera que compartan
parte del terreno, no que cada uno aporte una ganancia independiente y
aditiva). El próximo lever real es P9 (BAT global): el hallazgo de P7 mostró
que el packing no-BAT, optimizado a ciegas de BAT, termina SIN margen para
que BAT encuentre host natural (3 -> 9 pallets BAT dedicados) -eso es lo que
más pallets está costando ahora mismo (70 totales vs 55 de V4). El packing
no-BAT en sí (61 pallets) todavía está por encima de V4 (55 con BAT
incluido) -P9/P10 tienen que atacar las dos brechas: BAT integrado Y el
resto de la distancia a 42-45.

---

## V5-P9 — BAT global (+ V5-P10 residual search post-BAT)

### Cambios
- `src/bat.py`: nueva sección V5 al final del archivo (V4/camas queda
  intacto arriba, sin tocar). `BAT_SKU_MARCADOR = "__BAT__"` (marca una
  torre como caja de consolidación BAT, no un SKU real).
  `_insertar_bat_parcial(cajas, destinos, info_sku, cd)`: intenta colocar
  TODAS las cajas BAT juntas en UNA torre (mejor area fit entre todos los
  destinos); si no entran juntas en ningún lado, las divide a la mitad y
  reintenta cada mitad por separado (recursivo) -devuelve las que no
  encontraron destino. `_consolidar_dedicados_bat_v5`: arma el mínimo de
  pallets dedicados con lo que sobra. `asignar_bat_global(pallets_cd,
  cajas_bat, info_sku) -> list[PalletV5]`: punto de entrada, reusa
  `_PalletEnConstruccion`/`_reconstruir_en_construccion` de
  `packing_columnar.py` (una caja BAT es, para el packer, una torre más).
- `src/packing_columnar.py`: `_reconstruir_en_construccion` se movió acá
  desde `residual_search.py` (lo necesitan los dos módulos -bat.py y
  residual_search.py- así que vive donde vive `_PalletEnConstruccion`).
- `src/pipeline_v5.py`: el core de armado por CD pasa a ser multistart ->
  residual_search -> `bat.asignar_bat_global` -> residual_search otra vez
  (P10, liviano post-BAT -la caja BAT pudo dejar un pallet más bajo de lo
  que hubiera quedado sin ella). CDs con demanda BAT pero SIN ninguna otra
  demanda clasificada (no aparecen en el loop por CD) se cubren aparte,
  para no perder esa demanda en silencio. `_palletv5_a_pallet` ahora separa
  las torres `BAT_SKU_MARCADOR` de las líneas normales y las traduce a
  `pallet.cajas_bat`/`es_host_bat` (lo que `exportar.py`/`benchmark.py` ya
  saben leer).
- `src/benchmark.py`: `bat_dedicados` reconoce tanto `PH-BAT-` (V4) como
  `PV5-BAT-` (V5).
- `tests/test_bat_v5.py` (nuevo): 6 tests -500 unidades máx/caja, 501 ->
  2 cajas, varias cajas BAT se consolidan en una sola torre cuando hay
  lugar, más de 4 cajas se reparten entre varios hosts si hace falta,
  pallet dedicado cuenta físicamente, BAT nunca desplaza torres existentes.

### Antes / Después (dataset real, PACKER_VERSION="V5", pipeline completo)
- Antes de P9 (P5+P7+P8, BAT todavía con la lógica V4 ciega al packing
  columnar): **70 pallets**, 9 BAT dedicados, altura media 191.6, 9 pallets
  bajo 190cm
- Después de P9+P10: **61 pallets**, **2 BAT dedicados**, altura media
  **208.7**, **0 pallets bajo 190cm**, altura máxima 214.4 (sin violaciones
  de 215), demanda exacta (5020 cajas no-BAT + 56.257 unidades BAT, ambos
  reconciliados sin pérdida)
- V4 (referencia): 55 pallets totales

### Invariantes
- demanda exacta: OK (Cajas_Totales_Pallet suma 5020, igual que antes de
  BAT; Unidades_BAT suma 56.257, > 0, sin pérdida)
- altura <=215: OK, verificado (máximo 214.42, 0 violaciones)
- BAT nunca desplaza torres existentes: OK (test dedicado)
- pallets BAT dedicados cuentan físicamente: OK (prefijo `PV5-BAT-`
  reconocido por benchmark.py)
- tests: 92 passed, 1 skipped

### Observaciones
Confirma el diagnóstico de P7: el problema no era el packing no-BAT en sí
(61 pallets, ya bastante bueno), era que BAT no tenía forma de aprovecharlo.
Con BAT global reusando el mismo mecanismo MaxRects que el resto del core
-una caja BAT es literalmente una torre más para el packer- el total bajó
9 pallets (70->61) sin tocar absolutamente nada del packing no-BAT.
**61 pallets sigue siendo más que los 55 de V4** -todavía falta terreno
para llegar a la referencia del plan (42-45), pero la curva va en la
dirección correcta y cada patch se está pudiendo atribuir a una causa
concreta, no a ajustar parámetros a ciegas.

---

## V5-P11 — Estabilidad informativa

### Cambios
- `src/estabilidad.py` (nuevo): `calcular_estabilidad(pallet) ->
  EstabilidadPallet` -centro de masa XY (ponderado por peso de cada torre),
  desviación respecto del centro geométrico, peso por cuadrante (NO/NE/SO/SE),
  torres "esbeltas" (altura / lado más corto > 4), fracción de peso en la
  mitad superior (centro de masa VERTICAL ponderado, normalizado contra la
  altura de producto). Estados `OK`/`WARN_COG`/`WARN_TORRE_ESBELTA`/
  `WARN_PESO_SUPERIOR` -nunca bloquea, es un dataclass de solo lectura.
- `src/pipeline_v5.py`: se calcula por pallet al final de cada CD (después
  de P8/P9/P10) y se guarda en `pallet.metadata["estabilidad"]` -sin
  exportar todavía a una hoja propia (eso es P13).
- `tests/test_estabilidad.py` (nuevo): 6 tests.

### Iteración dentro del patch (documentada porque cambió el diseño)
Primer diseño de "peso superior": marcar como top-heavy cualquier torre
cuyo TOPE esté en el tercio superior de la altura del pallet. Test con 4
torres iguales en las 4 esquinas (caso "debería dar OK") lo agarró: en un
pallet de una sola capa uniforme, el tope de CUALQUIER torre está, por
definición, en el tercio de arriba -no hay ninguna capa más baja contra la
cual comparar. Se reemplazó por centro de masa VERTICAL ponderado por peso
(cada torre aporta su masa centrada en su propia mitad de altura, normalizado
contra la altura de producto) -un pallet parejo de una sola capa da
exactamente 0.5 (el punto de equilibrio), no dispara nada; el umbral quedó
en 0.6 para dejar margen a esa línea de base.

### Invariantes
- No bloquea nada: verificado (test dedicado con un pallet en todas las
  alertas posibles, sigue devolviendo un resultado normal, no revienta)
- tests: 98 passed, 1 skipped
- benchmark real sin cambios (61 pallets, 2 BAT dedicados) -P11 es
  puramente informativo, como debía ser

---

## V5-P12 — Visualización 3D real

### Cambios
- `visualizacion.py`: `_cuboide(x, y, z, dx, dy, dz)` (helper, 6 caras de
  una caja para `Poly3DCollection`) y `dibujar_pallet_v5_3d(pallet: PalletV5,
  info_sku, vista="isometrica") -> plt.Figure` -dibuja cada `PlacementCaja`
  de cada torre como una caja 3D real en su (x, y, z) dentro del pallet,
  coloreada por categoría del SKU (mismo `COLOR_CATEGORIA` que la vista V4).
  Las torres BAT (`sku == bat.BAT_SKU_MARCADOR`) se pintan con `COLOR_BAT`
  y se etiquetan "BAT" en vez del SKU -no son un SKU real. 4 vistas
  (`VISTAS_3D`: isometrica/frente/lateral/superior) vía `ax.view_init`.
  Si una torre no trae `placements` (no debería pasar -`crear_torre` los
  arma siempre-, pero queda de resguardo) se dibuja como un solo bloque.
- `models.py`: `ResultadoPipeline` gana el campo opcional
  `pallets_v5: list[PalletV5] | None = None` -sin esto no había forma de
  llegar desde el pipeline hasta la vista sin reconstruir geometría a partir
  del `Pallet` (V4) adaptado, que descarta x/y/z a propósito
  (`_palletv5_a_pallet`, ver docstring del módulo).
- `src/pipeline_v5.py`: `ejecutar_core_v5` ahora pasa `pallets_v5=pallets_v5`
  (la lista de `PalletV5` original, antes del adapter a `Pallet`) al
  `ResultadoPipeline` que devuelve.
- `app.py`: la pestaña "Inspector de Pallets" arma `v5_por_id` desde
  `resultado.pallets_v5` (los ids coinciden 1:1 con los `Pallet` adaptados,
  `_palletv5_a_pallet` reusa `pv5.id`). Si el pallet elegido tiene su
  `PalletV5` original, se muestra la vista 3D nueva (selector de vista +
  tabla de torres con x/y/cantidad/altura/orientación/fuente_geometría +
  estados de estabilidad de P11) en vez de la vista 2D por cama de V4 -que
  para un pallet columnar no tiene nada que mostrar (`camas` queda vacío a
  propósito, ver P5/P9).
- `tests/test_visualizacion_v5.py` (nuevo): 3 tests -`_cuboide` da 6 caras
  de 4 vértices; un pallet con una torre normal + una torre BAT genera el
  número correcto de colecciones 3D (1 base + 1 caja por placement) en las
  4 vistas sin reventar; un pallet sin torres no revienta.

### Invariantes
- "Toda posición exportada debe poder verse" (criterio del plan, sección
  14): cada `PlacementCaja` de cada torre tiene su propio cuboide en su
  (x, y, z) real -no es una vista agregada por torre.
- No cambia nada del armado: es una vista de solo lectura sobre pallets ya
  construidos -sin efecto en benchmark (sigue en 61 pallets, 2 BAT
  dedicados).
- V4 sin cambios: `dibujar_pallet`/`dibujar_cama` (vista por cama) quedan
  intactas, se siguen usando tal cual para pallets que no tienen
  `PalletV5` asociado (o sea, todo lo que corre bajo `PACKER_VERSION="V4"`).
- tests: 101 passed, 1 skipped (suite completa)

---

## V5-P13 — Export y auditoría

### Cambios
- `src/exportar.py`: 3 funciones nuevas, todas de solo lectura sobre
  `list[PalletV5]` -no tocan el armado:
  - `construir_torres_df`: una fila por torre (CD, ID_Pallet, SKU, X, Y,
    Largo, Ancho, Alto_Caja, Cantidad, Altura_Torre, Orientacion,
    Fuente_Geometria, Peso_kg, Estrategia_Ganadora, Seed_Ganadora). Las
    torres BAT se incluyen con SKU="BAT".
  - `construir_pallets_3d_data_df`: una fila por CAJA física (X, Y, Z reales
    dentro del pallet, no solo por torre) -es el respaldo tabular exacto de
    `visualizacion.dibujar_pallet_v5_3d` (P12): "toda posición exportada
    debe poder verse" se cumple literalmente, cada cuadro del dibujo tiene
    su fila acá.
  - `construir_estabilidad_df`: una fila por pallet con lo que P11 ya
    calculaba pero no exportaba (`pallet.metadata["estabilidad"]"]`) -centro
    de masa, desviación, fracción de peso superior, torres esbeltas,
    estados, OK/no OK.
  - `exportar_workbook`: agrega las hojas `Torres`, `Pallets_3D_Data` y
    `Estabilidad_V5` SOLO si `resultado.pallets_v5` viene poblado (es
    `None` en V4 -ver P12/models.py) -el workbook de V4 queda
    byte-idéntico en estructura de hojas, verificado con test dedicado.
- `src/pipeline_v5.py`: `mejor.estrategia`/`mejor.seed` (ya calculados por
  `multistart.mejor_solucion`, P7) se guardan en `pallet.metadata` de cada
  pallet del CD, ANTES de residual_search/BAT -esas etapas mutan
  torres/altura de los MISMOS objetos `PalletV5` en la lista (nunca la
  reemplazan; ver `residual_search._restaurar`, que solo pisa
  torres/altura/peso/ocupación, nunca `metadata`), así que la
  estrategia/semilla ganadora sobrevive intacta hasta el export. Los
  pallets BAT dedicados (`PV5-BAT-*`) no tienen estrategia/seed -no son
  producto de multi-start, quedan `None` en esas columnas (correcto, no un
  bug: ver P9).
- `tests/test_exportar_v5.py` (nuevo): 5 tests -conteo exacto de filas
  (una por torre, una por caja física) contra el armado real vía
  `dataset_factory`; `Estabilidad_V5` tiene una fila por pallet (P11 la
  calcula para todos); el workbook V5 trae las 3 hojas nuevas; el workbook
  V4 NO las trae (nada se filtra por accidente al camino V4).

### Verificación contra el dataset real (`Cubicaje18.07.2026.xlsx`, V5)
- 61 pallets, 876 torres, 5057 cajas físicas.
- `sum(torre.cantidad)` == filas de `Pallets_3D_Data` == 5057 (conteo
  exacto, sin fuga ni duplicado).
- Las 8 hojas del workbook completo: `Plan_Picking`, `Log_Validacion`,
  `Resumen_por_CD`, `Auditoria_Geometrica`, `Benchmark`, `Torres`,
  `Pallets_3D_Data`, `Estabilidad_V5`.

### Invariantes
- No cambia el armado ni el benchmark (sigue en 61 pallets, 2 BAT
  dedicados) -P13 es puramente de exportación/lectura.
- tests: 106 passed, 1 skipped (suite completa)

---

## V5-P14 — Benchmark formal gate 42-45

### Cambios
- `src/validacion_v5.py` (nuevo): `validar_pallet_v5(pallet)` /
  `validar_geometria_v5(pallets)` -auditoría geométrica independiente del
  algoritmo de packing (MaxRects, P5) sobre el resultado YA armado: ninguna
  torre se sale de la base 120x100 (overflow), ninguna pareja de torres del
  mismo pallet se superpone en XY (overlap, AABB con tolerancia de 1e-6cm
  para que tocarse en el borde -la forma normal en que dos torres quedan
  lado a lado- no cuente como violación), ninguna altura supera
  `config.ALTURA_TOPE_DURO`. No es una segunda implementación del packer,
  es una verificación de que lo que el packer dice que armó es
  geométricamente posible de verdad.
- `src/benchmark.py`: `GateV5Resultado` (dataclass) y
  `evaluar_gate_v5(resultado: BenchmarkResultado, violaciones_geometria)
  -> GateV5Resultado`. Cuatro criterios, TODOS obligatorios, ninguno se
  relaja para hacer pasar el benchmark (instrucción explícita del plan):
  pallets en `[42, 45]`, `demanda_unidades_error == 0`,
  `altura_max <= ALTURA_MAX_REAL` (215), cero violaciones geométricas. Junta
  TODAS las razones de rechazo en una sola corrida (no se detiene en la
  primera) para que el reporte sea completo de una vez.
- `tests/test_validacion_v5.py` (nuevo, 6 tests) y `tests/test_gate_v5.py`
  (nuevo, 6 tests): overlap/overflow/altura detectados por separado y en
  conjunto; el gate aprueba solo cuando los 4 criterios se cumplen a la vez
  y acumula las 3 razones cuando los 3 primeros fallan simultáneamente.

### Corrida formal contra el dataset real (`Cubicaje18.07.2026.xlsx`, V5)
```
pallets:                 61   (rango exigido: 42-45)
altura_media:            208.74 cm
altura_min / altura_max: 197.42 / 214.42 cm
demanda_unidades_error:  0.0
bat_dedicados:           2
pallets_bajo_190:        0
violaciones geométricas: 0   (0 overlaps, 0 overflows, 0 alturas sobre tope duro)

GATE: NO APROBADO
Única razón de rechazo: "pallets=61, fuera del rango [42, 45]"
```

### Veredicto honesto
El gate NO se aprueba. La única razón de rechazo es la cantidad de pallets
(61 contra el rango 42-45) -los otros tres criterios (demanda exacta,
altura dentro del tope real, cero violaciones geométricas) pasan limpio.
Esto es consistente con lo que ya venía documentado en P9: cada patch bajó
el número por una causa identificable y verificada (70->61 con BAT global),
pero **61 sigue siendo 16-19 pallets más que el objetivo**, y por
instrucción explícita del plan ("no cambiar el target ni forzar el conteo
para hacer pasar el benchmark") esa brecha no se cierra ajustando parámetros
a ciegas ni relajando el gate -se reporta tal cual.

Referencia: V4 (el motor en producción) da **55 pallets físicos totales**
sobre el mismo dataset (P0) -V5 columnar, con todo lo construido en P0-P13,
todavía queda por encima de V4, no solo del objetivo de 42-45. La
arquitectura por torres no está resultando, en este dataset, en menos
pallets que el modelo por camas; el mecanismo más grande que sí ayudó (BAT
global, P9) ya está aplicado.

### Invariantes
- No se tocó ningún parámetro de armado para intentar acercar el número al
  rango -el gate se corrió tal cual quedó el motor después de P13.
- tests: 118 passed, 1 skipped (suite completa)

---

## V5-P15/P16 — Default V5 + limpieza legacy: NO EJECUTADO

El plan condiciona P15/P16 explícitamente a que P14 apruebe ("Solo retirar
V4 cuando V5: llegue a 42-45; no rompa invariantes; sea aceptado por
operación"). P14 no aprobó (arriba) -por lo tanto:

- `config.PACKER_VERSION` **se deja en `"V4"`** (default sin tocar,
  verificado en `config.py:9`). V4 sigue siendo el motor de producción.
- `legacy/` **no se toca** -sigue siendo referencia congelada, no se borra
  código de V4 (`packing_2d.py`, `apilado_3d.py`, `pallets_homogeneos.py`,
  `bat.py` sección V4, `pipeline.ejecutar_core_v4`) porque V4 sigue en uso.
- No se hizo ningún cambio de "limpieza" que asuma que V5 reemplaza a V4.

V5 queda completo y disponible detrás del flag (`PACKER_VERSION="V5"`) para
seguir iterando -corre de punta a punta, no pierde demanda, no viola
geometría, es auditable (P12/P13)- pero no es la ruta por defecto hasta que
alguien reduzca la brecha de pallets (61 vs 42-45) o el negocio decida
aceptar el resultado actual bajo otro criterio.

---

## V5-packing3d — Packing 3D real (apilado de torres distintas en el mismo XY)

Instrucción del usuario, después de ver el gate P14 fallando por cantidad de
pallets: "no dejemos espacio entre cajas del mismo nivel de cama, vamos
agrupandolo como si fuera un tetris asi como un lego". Esto es la opción
"cara" que se había dejado planteada como alternativa a probar primero un
heurístico barato -el usuario pidió ir directo al rediseño real.

### Diagnóstico previo (con datos reales, lo que motivó el cambio)
Antes de tocar nada se midió el modelo 2D (P0-P14, 61 pallets) con una
métrica nueva -eficiencia volumétrica real (`volumen_utilizado / (huella x
altura del producto más alto)`), distinta de `ocupacion_xy` (que solo mide
huella, no aire vertical):
```
ocupacion_xy (huella):        82% media, 84% mediana
eficiencia volumétrica real:  54% media, 53% mediana (peor caso: 17%)
```
Causa: una Torre en el modelo 2D era una sola SKU de piso a techo en su
(x, y) -si al lado había una torre más alta, el aire sobre la corta quedaba
inutilizable para siempre (nadie más podía apilarse ahí). Confirmado
visualmente con `visualizacion.dibujar_pallet_v5_3d` sobre el peor caso real
(`PV5-BK43-006`, 17% de eficiencia).

### Cambios
- `models.py`: `Torre` gana `z: float = 0.0` -base del segmento dentro de
  la pila de producto (0 = piso del pallet). Antes toda torre implícitamente
  arrancaba en 0; ahora una torre puede empezar donde termina otra.
- `src/torres.py`: `crear_torre(..., z=0.0)` -las cajas del `PlacementCaja`
  quedan con `z` ABSOLUTO dentro de la pila (`z_base + i*alto_caja`), así
  que `visualizacion.py` no necesitó ningún cambio en cómo lee `placement.z`.
  `dividir_torre` propaga `z` a ambas mitades.
- `src/packing_columnar.py` (reescritura del núcleo): `_RectLibre`/MaxRects
  2D reemplazado por `_CuboidLibre`/MaxRects 3D (x,y,z,w,h,d) -después de
  colocar una caja, el cuboide libre se parte en hasta 5 franjas maximales
  (las 4 de XY + una "arriba en Z"; nunca "abajo en Z", porque siempre se
  coloca a ras del piso del cuboide elegido, así que nunca queda hueco
  debajo). `mejor_ajuste` ahora devuelve `(idx, sobra, cantidad_colocable)`
  -`cantidad_colocable` puede ser MENOR que lo pedido si el mejor cuboide no
  tiene profundidad Z completa (eso es justo lo que permite que otra SKU
  ocupe el resto de esa columna de aire). Nueva función `_area_union_xy`
  (ver bug de abajo).
- `src/residual_search.py`, `src/bat.py`: adaptados al nuevo
  `mejor_ajuste` con `permitir_parcial=False` -ambos necesitan todo-o-nada
  (la torre completa entra en un destino o no entra, sin partirla ahí
  mismo; cada uno ya tiene su propia lógica de división cuando hace falta).
- `src/validacion_v5.py`: `_se_superponen` pasa de overlap 2D (XY) a 3D
  (X, Y, Z) -dos torres en el mismo (x, y) ya NO es violación si sus
  rangos de Z no se cruzan (apilado válido); si se cruzan, sigue siendo
  overlap real.
- `src/estabilidad.py`: el centro de masa vertical (P11) ahora usa
  `t.z + t.altura/2` en vez de `t.altura/2`, y `altura_producto` usa
  `max(t.z + t.altura)` en vez de `max(t.altura)` (ver bug de abajo).
- `src/exportar.py`: `Torres` (hoja P13) gana columna `Z`.
- `visualizacion.py`: el fallback sin `placements` (dead code defensivo)
  ahora también usa `torre.z` para la base y la etiqueta.
- Tests nuevos: `tests/test_packing_3d.py` (apilado real, conservación de
  demanda, `_area_union_xy`), casos nuevos en `tests/test_validacion_v5.py`
  (apilar válido vs overlap vertical real), caso nuevo en
  `tests/test_estabilidad.py` (peso apilado arriba pesa más que al piso).

### Dos bugs encontrados y corregidos DURANTE el patch (no en producción antes)

**1. Best-fit ciego a "todo o nada"**: la primera versión de `mejor_ajuste`
elegía siempre el cuboide de MENOS volumen sobrante, sin importar si el
llamador necesitaba la cantidad COMPLETA. Un cuboide chico que solo entraba
1 caja podía "ganar" por ajuste ceñido aunque hubiera OTRO cuboide en la
misma lista con lugar de sobra para la torre entera -`bat.py`/
`residual_search.py` (que necesitan todo-o-nada) terminaban rechazando un
destino que en realidad sí tenía lugar. Atrapado por
`test_varias_cajas_bat_se_consolidan_en_un_host_lado_a_lado` (esperaba 1
torre BAT de 3 cajas, dio 3 torres de 1 caja cada una). Corregido con un
parámetro explícito `permitir_parcial` en vez de un filtro posterior a
ciegas.

**2. `ocupacion_xy` > 100%**: con torres apiladas, la fórmula vieja
(`sum(t.area_base for t in torres)`) contaba el MISMO piso más de una vez
cuando varias torres compartían (x, y) a distinto Z -en el dataset real
llegó a dar 129% de "ocupación" en promedio. No lo agarró ningún test (no
había ningún caso con dos torres en el mismo XY antes de este patch, así
que la fórmula vieja nunca se ejercitó contra ese escenario). Corregido con
`_area_union_xy`: sweep por coordenadas comprimidas que calcula el área de
huella REAL (unión geométrica de rectángulos, sin duplicar solapes).

### Resultado sobre el dataset real (`Cubicaje18.07.2026.xlsx`, V5)
```
                          ANTES (2D)      DESPUÉS (3D)
pallets                   61              50   (-18%)
eficiencia volumétrica    54% media       66% media
                          53% mediana     69% mediana
ocupacion_xy              82% media       81% media (ya no se infla con apilado)
altura_media              208.7           210.3
altura_max                214.4           214.9   (sigue <=215)
demanda_unidades_error    0.0             0.0
violaciones geométricas   0               0    (overlap 3D real, no solo XY)
bat_dedicados             2               5
```
Gate P14: sigue sin aprobar -única razón: `pallets=50, fuera del rango
[42, 45]`. La brecha bajó de 16 pallets a **5**.

`bat_dedicados` subió de 2 a 5: con el packing más ajustado, queda menos
margen de altura suelto en los pallets ya armados para que BAT encuentre un
host natural -mismo tipo de interacción que se diagnosticó en P7/P9 (multi-
start optimiza sin saber de BAT), ahora más marcado porque el packing 3D
deja aún menos aire disponible. No se tocó nada de BAT para compensarlo -si
hace falta, es la siguiente pieza a mirar (una versión de BAT que también
sepa apilarse en el aire que deja una torre corta, no solo en huecos XY
completos).

### Invariantes
- Demanda exacta: verificado (tests + `demanda_unidades_error=0.0` real).
- Cero violaciones geométricas (overlap 3D + overflow + altura <= tope
  duro): verificado con `validar_geometria_v5` sobre el resultado real.
- V4 no se tocó -sigue siendo el motor de producción
  (`config.PACKER_VERSION="V4"`), este patch es enteramente dentro del
  core V5.
- tests: 126 passed, 1 skipped (suite completa)

---

## Experimento: ajustar orden de multi-start (sin cambios permanentes)

Antes de tocar BAT, se probó si el orden de multi-start (ya corriendo sobre
el packing 3D) tenía margen sin cambiar código -3 corridas ad-hoc sobre el
dataset real, sin persistir ningún cambio:

```
Baseline (7 estrategias x 20 semillas):        50 pallets, 34s
+ 60 semillas aleatorias (3x más cómputo):     49 pallets, 48s
+ estrategia nueva ALTURA_ASC (chicas primero): 50 pallets, sin cambio
+ ambas combinadas:                             49 pallets, 48s
```

Conclusión: el orden ya está prácticamente agotado. Más semillas dan
rendimientos decrecientes (1 pallet a cambio de 40% más tiempo) y una
estrategia nueva pensada específicamente para el apilado no aportó nada -el
packer 3D ya explora esas combinaciones vía multi-start sin necesitar una
regla explícita. No se dejó ningún cambio de este experimento en el código
(ni `MULTISTART_SEEDS=60` ni `ALTURA_ASC`) -el beneficio no justificaba el
costo permanente.

---

## V5-BAT-integrado — BAT dentro del mismo multi-start

Instrucción del usuario tras el experimento de arriba: "prueba primero
ajustar el orden de multi start" (hecho, sin resultado) y después "Si sigue
con eso" (sí, avanzar con la integración de BAT).

### Diagnóstico previo
Con el packing 3D (patch anterior), `bat_dedicados` había subido de 2 a 5:
el packing más ajustado deja menos aire suelto para que BAT (que corría
DESPUÉS de multi-start+residual search, sin que esas etapas supieran de su
existencia) encontrara un host natural -mismo tipo de interacción
diagnosticada en P7/P9 para el modelo 2D, ahora más marcada.

Se probó primero un fix chico y de bajo riesgo: BAT solo intentaba una
orientación fija (45x24), nunca rotada (24x45) -a diferencia de cualquier
SKU real. Con rotación agregada (prueba ad-hoc, sin persistir): 
`bat_dedicados` bajó de 5 a 4, pero el TOTAL de pallets no cambió (50->50)
-el residual_search post-BAT compensaba distinto según cuántos pallets
tenía para reordenar. Confirmó que el problema no era la orientación sino
el ORDEN DE LAS ETAPAS: BAT decidido después de que todo lo demás ya está
cerrado, sin que el resto sepa que tiene que dejarle lugar.

### Cambios
- `src/bat.py`: se ELIMINÓ por completo la versión anterior de V5-P9
  (`_insertar_bat_parcial`, `_consolidar_dedicados_bat_v5`,
  `asignar_bat_global` -código muerto una vez confirmado que la nueva
  versión es estrictamente mejor, sin dejar nada "por las dudas"). Nueva
  sección "V5-BAT-integrado":
  - `construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)`: una fila
    por CD con demanda BAT, con las MISMAS columnas que cualquier SKU real
    (Largo/Ancho/Alto_Efectivo, Peso_Caja, Cajas_Remanente,
    Cajas_Cama_Efectivo) -para que compita por espacio en el mismo `df_cd`
    que evalúan las 7 estrategias/semillas de multi-start.
  - `renombrar_pallets_bat_puros(pallets_cd, cd)`: un pallet cuyas torres
    son TODAS `BAT_SKU_MARCADOR` se renombra a `PV5-BAT-{cd}-NNN` -mismo
    esquema que ya reconocían `benchmark.py`/`exportar.py`, aunque ahora
    salga del packer genérico y no de una función dedicada.
  - `asignar_cajas_bat_a_torres(pallets_cd, cajas_bat)`: después de armar,
    mapea la cantidad colocada (el packer solo sabe de "SKU
    `BAT_SKU_MARCADOR`, cantidad N") de vuelta a objetos `CajaBAT` reales
    concretos -son fungibles entre sí (mismo footprint fijo), el mapeo es
    por orden estable.
- `src/packing_columnar.py`: SIN CAMBIOS -`armar_pallets_columnar` ya
  trataba genéricamente cualquier fila de `df_cd` como una SKU más; BAT
  entra gratis por ese mismo camino, incluida la rotación de orientación
  (`generar_torres_candidatas` ya la hace para cualquier SKU con
  ancho≠largo, BAT incluido).
- `src/pipeline_v5.py`: el loop por CD ahora arma `df_armado =
  pd.concat([df_clasificado, df_bat_pseudo])` ANTES del `groupby("CD")` -un
  CD con demanda BAT pero SIN ninguna otra demanda clasificada aparece
  igual (con solo la fila BAT), así que se eliminó el manejo especial que
  existía para ese caso (ya no hace falta, entra por el mismo camino). Se
  quitó también la segunda pasada de `residual_search` post-BAT (P10):
  con BAT ya adentro de la MISMA pasada de multi-start+residual, esa
  segunda pasada había quedado redundante -corre UNA sola vez.
- `tests/test_bat_v5.py`: reescrito para probar la integración nueva
  (`construir_filas_bat_pseudo_sku`, `renombrar_pallets_bat_puros`,
  `asignar_cajas_bat_a_torres`, más un caso de reparto entre varios hosts y
  uno de pallet 100% BAT) en vez de la función eliminada
  `asignar_bat_global`. Mismas garantías físicas cubiertas: 500 unidades
  máx. por caja, consolidación en un host cuando hay lugar, reparto entre
  varios hosts cuando no, pallet dedicado cuenta físicamente, BAT nunca
  desplaza torres existentes, demanda BAT exacta sin duplicados.

### Resultado sobre el dataset real (`Cubicaje18.07.2026.xlsx`, V5)
```
                          packing3d solo    + BAT integrado
pallets                   50                49
bat_dedicados             5                 0
altura_media              210.3             211.5
altura_max                214.9             214.9   (sigue <=215)
demanda no-BAT            5020/5020 ✓       5020/5020 ✓
demanda BAT (cajas)       37/37 ✓           37/37 ✓
demanda BAT (unidades)    16205/16205 ✓     16205/16205 ✓
violaciones geométricas   0                 0
```
Gate P14: sigue sin aprobar -única razón: `pallets=49, fuera del rango
[42, 45]`. La brecha bajó de 5 a **4**.

`bat_dedicados` pasó de 5 a **0**: con BAT compitiendo por espacio en el
mismo multi-start que todo lo demás, ninguna de las 27 combinaciones
(7 estrategias + 20 semillas) evaluadas por CD en el dataset real terminó
necesitando abrir un pallet dedicado solo para BAT -mejor que el baseline
2D original (2 dedicados) y muchísimo mejor que el intermedio 3D-sin-BAT-
integrado (5 dedicados).

### Camino recorrido desde el inicio de esta sesión de V5 (contexto completo)
```
V4 (referencia, producción):                    55 pallets
V5 2D (P0-P14, MaxRects sin apilado):            61 pallets
V5 3D (packing3d, apilado real):                 50 pallets
V5 3D + BAT integrado:                           49 pallets
Objetivo del plan (gate P14):                 42-45 pallets
```

### Invariantes
- Demanda exacta: verificado (no-BAT 5020/5020, BAT 37 cajas/16205
  unidades, todo exacto).
- Cero violaciones geométricas: verificado con `validar_geometria_v5`.
- BAT nunca desplaza torres existentes: verificado (test dedicado).
- Ningún pallet BAT-dedicado queda sin el prefijo `PV5-BAT-` que
  `benchmark.py` necesita para contarlo físicamente: verificado.
- V4 no se tocó -sigue siendo el motor de producción.
- tests: 129 passed, 1 skipped (suite completa)

---

## Estado actual de V5 (punto de parada, 2026-08-18)

Instrucción del usuario: "dejemos aca y reportemos esto como el estado
actual de V5". Se detiene la iteración acá -no se sigue picando la brecha
de 4 pallets contra el gate.

```
V4 (producción, sin tocar):                     55 pallets físicos
V5 (packing 3D + BAT integrado, este estado):   49 pallets físicos
Objetivo del gate formal (P14):               42-45 pallets
```

V5 ya es mejor que V4 en este dataset (49 vs 55, -11%), pero el gate formal
de P14 (42-45) NO está aprobado -única razón registrada:
`pallets=49, fuera del rango [42, 45]`. Todo lo demás que el gate exige
(demanda exacta, altura <=215, cero violaciones geométricas) pasa limpio.

**`config.PACKER_VERSION` sigue en `"V4"`** -no se cambió el default. V5
está completo y disponible detrás del flag para quien quiera correrlo o
seguir iterando, pero V4 sigue siendo lo que corre en producción por
default, tal como quedó establecido en P15/P16.

Para correr V5 localmente: cambiar `config.py:9` de `PACKER_VERSION = "V4"`
a `"V5"` antes de levantar `streamlit run app.py` (o antes de llamar
`ejecutar_pipeline`/`ejecutar_desde_archivo` desde un script). Con V5
activo, el Excel exportado trae 3 hojas extra (`Torres`, `Pallets_3D_Data`,
`Estabilidad_V5`, ver P13) y el Inspector de Pallets de la app muestra la
vista 3D real por torre (P12) en vez de la vista 2D por cama.

---

## V-AUTO — Corre V4 y V5, se queda con el mejor CD por CD

### Motivación (validación contra datos reales del 18.08.2026)
Comparando contra `Plan de Movimientos - Pre Picking 18.08.xlsx` (demanda
real de un día, 6 CDs, contrastada contra el consolidado real que armó el
hub -`hub`/`hub cigarros`, 48 pallets físicos reales, 0 dedicados BAT):
```
Real:  48 pallets
V4:    50 pallets (+4.2%)
V5:    53 pallets (+10.4%)
```
Por CD, ningún motor ganó siempre: V4 le ganó a V5 en BK37/BK49/BK50, V5
igualó o superó a V4 en BK36/BK51/BK61. Esto contrasta con el dataset de
referencia grande (`Cubicaje18.07.2026.xlsx`), donde V5 le gana a V4 por
mucho margen (49 vs 55). Conclusión: **ningún motor domina al otro en
todos los casos** -la ventaja depende de la escala/composición de cada
CD. Instrucción del usuario: correr ambos y quedarse siempre con el mejor,
CD por CD.

### Cambios
- `src/pipeline_auto.py` (nuevo): `ejecutar_core_auto(envios, maestro, uma)`
  -corre `ejecutar_core_v4` y `pipeline_v5.ejecutar_core_v5` completos
  sobre la MISMA entrada, y por cada CD presente en cualquiera de los dos
  resultados, elige el que da mejor `_score_cd` (mismo criterio
  lexicográfico que `multistart.SolucionCD.score`: menos pallets, después
  menos pallets bajo el nominal, después menos dedicados BAT, después más
  cerca del target de altura en promedio -`min()` decide, empate exacto en
  las 4 componentes se queda con V4 por ser el motor probado). Los pallets
  "Requiere Revisión" (sin clasificar / geometría insuficiente) son
  idénticos entre ambos resultados -se toman de V4 sin comparar. El
  `pallets_v5` final del `ResultadoPipeline` queda FILTRADO a solo los CDs
  donde ganó V5 -las hojas de export V5 (Torres, Pallets_3D_Data,
  Estabilidad_V5, P13) y la vista 3D del Inspector (P12) siguen funcionando
  sin cambios porque son "por id de pallet", no un modo global: un pallet
  de un CD donde ganó V4 simplemente no aparece ahí y cae en la vista 2D
  por cama de siempre.
- `src/pipeline.py`: `ejecutar_pipeline` despacha a `pipeline_auto` cuando
  `config.PACKER_VERSION == "AUTO"`.
- `config.py`: `PACKER_VERSION` acepta ahora `"V4" | "V5" | "AUTO"`. Queda
  en `"AUTO"` localmente (instrucción explícita del usuario, "código casi
  final").
- `tests/test_pipeline_v5.py`: el test guardia (antes "default es V4") se
  actualiza para aceptar los tres valores -ya no asume cuál está activo.
- `tests/test_pipeline_auto.py` (nuevo, 8 tests): `_score_cd` con casos
  unitarios (menos pallets gana, empate en pallets se rompe por cercanía al
  target, un dedicado BAT pesa en el score, CD vacío da score neutro);
  `ejecutar_core_auto` con V4/V5 mockeados vía `monkeypatch` (elige V5 en
  el CD donde da menos pallets y V4 en el otro, sin mezclar CDs; empate
  exacto se queda con V4; pallets "Requiere Revisión" no se duplican);
  un test de integración de punta a punta con `dataset_factory` real (sin
  mocks) para confirmar que el dispatch completo no revienta.

### Verificación contra los dos datasets reales
```
                          V4      V5      AUTO
Dataset grande (18.07):   55      49      48   <- mejor que los dos solos
Dataset real (18.08):     50      53      50   <- empata con el mejor (V4)
```
En el dataset grande, AUTO combinó 3 CDs donde ganó V4 (BK31, SJ95, SJ97)
con 6 CDs donde ganó V5 (BK41, BK43, BK65, BK68, SJ86, SJ87) para llegar a
48 -mejor que cualquiera de los dos motores corriendo solo en TODO el
dataset. En el dataset real más chico, AUTO igualó el mejor resultado (V4,
50) sustituyendo 3 CDs por la versión de V5 con mejor altura promedio
(mismo conteo de pallets, mejor aprovechamiento) sin empeorar el total.
**En ningún caso AUTO dio un resultado peor que el mejor de los dos motores
individuales** -es la garantía que buscaba esta instrucción, y se cumple
en ambos datasets probados.

### Costo
Corre el pipeline completo dos veces -más lento que V4 o V5 solos (en el
dataset grande, ~33s, similar al tiempo de V5 solo, porque V4 es rápido en
comparación). Aceptado a propósito: la instrucción explícita fue
optimalidad por sobre velocidad.

### Invariantes
- Nunca peor que el mejor de V4/V5 por CD: verificado en ambos datasets
  reales (arriba).
- Demanda exacta: se hereda de V4 y V5 -cada uno ya la garantiza por
  separado, AUTO solo elige entre resultados ya válidos, no genera pallets
  nuevos.
- tests: ver corrida completa de la suite en este mismo commit del log.

---

## V-AUTO-CONSOLIDADO — Concentrar un SKU en menos pallets por CD

Instrucción del usuario: probar una variante que consolide un mismo SKU en
un pallet cuando va al mismo CD, SIN tocar `pipeline_auto.py` (AUTO se deja
intacto -confirmado explícitamente, ver pregunta/respuesta de esta sesión).

### Cambios
- `src/consolidacion_sku.py` (nuevo): `consolidar_por_cd(pallets_cd)` -para
  cada SKU repartido en más de un pallet del mismo CD, intenta mover sus
  torres hacia OTROS pallets que YA tienen ese mismo SKU (no cualquier
  pallet con espacio -eso ya lo hace `residual_search`, acá el objetivo es
  concentrar, no optimizar espacio en general). Reusa el mecanismo de
  `packing_columnar`/`residual_search` (`_reconstruir_en_construccion`,
  `mejor_ajuste(permitir_parcial=False)`, división recursiva en mitades,
  snapshot/rollback exacto). Deliberadamente conservador: nunca abre un
  pallet nuevo, nunca aumenta el total del CD, nunca pierde demanda -si no
  hay dónde mover algo, no se fuerza. `consolidar_sku(pallets_v5)` agrupa
  por CD y aplica lo anterior a cada grupo.
- `src/pipeline_auto_consolidado.py` (nuevo): igual que `pipeline_auto.py`
  (reusa sus mismas `_score_cd`/`_es_armado`, no las duplica), pero aplica
  `consolidacion_sku.consolidar_sku` sobre el resultado crudo de V5 ANTES
  de comparar contra V4 por CD.
- `src/pipeline.py`: `PACKER_VERSION="AUTO_CONSOLIDADO"` despacha acá.
- `tests/test_consolidacion_sku.py` (6 tests) y
  `tests/test_pipeline_auto_consolidado.py` (2 tests, incluye
  "nunca da más pallets que AUTO puro" -invariante estructural, no
  empírico).

### Resultado sobre el dataset real (`Cubicaje18.07.2026.xlsx`)
```
AUTO:              48 pallets, 61 combinaciones CD+SKU repartidas en >1
                   pallet, 77 "pallets tocados de más" en total.
AUTO_CONSOLIDADO:  48 pallets, MISMAS 61 combinaciones, MISMOS 77 de más.
```
**Cero cambio.** El caso puntual reportado por el usuario (KR Cola Negra,
SJ87, repartido en 4 pallets: 18+5+14+23 cajas) sigue exactamente igual.

### Por qué no cambió nada (diagnóstico, no falla silenciosa)
Los pallets que ya arma V5 están, en promedio, a ~209-211cm de un tope de
215cm -prácticamente sin margen de altura libre en ningún lado. La
consolidación conservadora necesita que ALGÚN otro pallet que ya tenga ese
SKU tenga hueco vertical libre para recibir más -y en este dataset,
sistemáticamente, no lo hay. No es que el algoritmo esté mal escrito (los
6+2 tests unitarios prueban que SÍ consolida cuando hay lugar, con
casos sintéticos armados a propósito) -es que, en la práctica, el packing
ya está tan ajustado que no queda aire para reorganizar sin desplazar otra
cosa.

### Camino que queda abierto (no implementado, es una decisión de negocio)
Para lograr consolidación real en un dataset tan ajustado hace falta uno
de dos trade-offs, ninguno de los cuales se puede decidir en el código sin
una instrucción explícita:
1. **Aceptar más pallets** a cambio de SKUs concentrados (ej. el caso SJ87
   probablemente necesitaría 1 pallet más para que Cola Negra quede en 2-3
   en vez de 4).
2. **Rehacer el packing desde el orden inicial** (no como post-proceso):
   una estrategia de multi-start que agrupe TODA la demanda de un SKU
   consecutivamente reusando el mismo pallet mientras tenga lugar, en vez
   de buscar "mejor ajuste" caja por caja -cambiaría el packing original,
   no es un parche aislado y seguro como este.

### Invariantes
- Nunca aumenta pallets: verificado (test dedicado + resultado real
  idéntico a AUTO).
- Nunca pierde demanda: verificado (tests de rollback exacto).
- `pipeline_auto.py` no se tocó -AUTO sigue exactamente como estaba.
- tests: ver corrida completa de la suite en este mismo commit del log.

---

## V-AUTO-CONSOLIDADO-DURO — concentrar SKU como regla dura del packer

El post-proceso conservador (arriba) dio 0 cambios -no había aire libre
para reorganizar sin desplazar algo. Instrucción del usuario: medir
directamente cuántos pallets salen si se pone como REGLA del armado (no un
parche después) que un SKU no debería repartirse en más pallets de los que
necesita, cuando va al mismo CD.

### Cambio
- `src/packing_columnar.py`: `armar_pallets_columnar` gana el parámetro
  `concentrar_sku: bool = False` (sin cambio de comportamiento por
  default, toda la suite existente pasó igual). Con `True`: antes de
  buscar el mejor ajuste entre TODOS los pallets activos, intenta agotar
  primero el ÚLTIMO pallet donde se colocó ese mismo SKU -solo cae al
  best-fit general si ese pallet ya no tiene lugar para nada más de esa
  SKU. Nunca abre un pallet nuevo antes de tiempo por esto -sigue siendo
  el mismo último recurso de siempre. Extraído `_buscar_mejor` como
  helper para no duplicar la búsqueda.
- `src/multistart.py` / `src/pipeline_v5.py`: `concentrar_sku` se propaga
  por parámetro (`generar_soluciones_cd` -> `_evaluar` ->
  `armar_pallets_columnar`, y `ejecutar_core_v5(..., concentrar_sku=True)`)
  -default `False` en todos lados, mismo comportamiento que antes de este
  patch si no se pasa explícito.
- `tests/test_packing_3d.py`: 3 tests nuevos (concentra en el mínimo de
  pallets posible cuando hay demanda de sobra para varias iteraciones; no
  pierde demanda; `concentrar_sku=False` da EXACTAMENTE el mismo resultado
  que no pasar el parámetro -invariante de no-regresión).

### Resultado directo sobre el dataset real (lo que pidió el usuario)
```
                              V4    V5    V5_concentrado
BK31                           4     5     5
BK41                           4     4     4
BK43                           4     4     4
BK65                           5     5     5
BK68                           4     4     4
SJ86                           7     7     7
SJ87                           8     7     7
SJ95                           4     4     4
SJ97                           9     9     9
TOTAL                         49    49    49

AUTO (V4+V5 por CD):           48
AUTO + V5_concentrado por CD:  48   <- MISMO total
```
**La regla dura NO cambia el total de pallets (49 en V5 solo, 48 en AUTO,
en ambos casos idéntico con o sin `concentrar_sku`).** Tampoco resuelve el
caso puntual que motivó la pregunta: SJ87 sigue con KR Cola Negra repartido
en exactamente los mismos 4 pallets (18+5+14+23 cajas), sin cambios.

Mejora marginal en la métrica agregada de dispersión (contando TODAS las
combinaciones CD+SKU del dataset, no solo el caso puntual): de 61 a 60
combinaciones repartidas en >1 pallet, de 77 a 72 "pallets tocados de más"
en total -una mejora de ~6.5% en esa métrica secundaria, sin costo (mismo
conteo de pallets), pero no visible en el caso específico que se venía
señalando.

### Por qué el caso SJ87 no cambió, aunque el mecanismo esté bien
Multi-start elige la solución ganadora por `SolucionCD.score`
(pallets, luego altura bajo nominal, luego residual, luego desviación de
altura, luego geometría inferida) -`concentrar_sku` no es parte de ese
score, solo cambia CÓMO se arma cada candidato internamente. Para SJ87, la
estrategia/semilla que ya ganaba (mejor score) resultó tomar exactamente
las mismas decisiones de colocación para esa SKU con o sin el sesgo -no es
que el sesgo esté roto (los tests sintéticos prueban que sí concentra
cuando corresponde), es que el candidato ganador en este caso puntual no
pasó por una situación donde "último pallet usado" y "mejor ajuste"
difirieran.

### Conclusión honesta
Con los datos de este dataset, **no existe una versión que reduzca el
conteo de pallets por debajo del óptimo ya encontrado (48, vía AUTO) Y
además concentre completamente los SKUs dispersos** -el packing ya está
tan ajustado (~97% de altura promedio) que no hay margen para reorganizar
sin costo. Concentrar SKUs de verdad en casos como SJ87 requeriría
aceptar más pallets ahí (trade-off de negocio, no técnico) o cambiar la
métrica que multi-start optimiza para que la dispersión de SKU pese en el
score -algo que no se implementó porque cambiaría qué gana en TODOS los
CDs, no solo en los casos problemáticos, y no hay instrucción de hacerlo.

### Invariantes
- `concentrar_sku=False` da resultado IDÉNTICO a no pasar el parámetro
  -verificado con test dedicado y con la suite completa sin regresiones.
- Nunca pierde demanda, nunca abre un pallet antes de que sea el último
  recurso -mismo contrato que la versión sin el parámetro.
- tests: ver corrida completa de la suite en este mismo commit del log.

---

## SKU_BLOQUE — Reescritura de lógica: bloques de SKU indivisibles

Instrucción textual del usuario, reemplazando el enfoque de
SKU_CONSOLIDADO: "si me piden 100 cajas de kr negra y el maestro me dice
que 1 pallet es 150 cajas entonces yo puedo poner en un solo pallet las
100 cajas y la altura restante que me queda para cumplir con los
parámetros ya establecidos busco otros skus que también consolidados me
ayuden a llegar a la altura óptima, si ya no encuentro consolidados
entonces busco remanentes".

### Diseño
1. **Dedicar**: por SKU+CD, si la demanda supera la capacidad de un pallet
   completo (`Cajas por PH`, mismo dato que `pallets_homogeneos.py`), se
   sacan tantos pallets 100% dedicados como quepan. Lo que sobra (< 1
   capacidad) es el "bloque" del SKU.
2. **Armar por bloques**: se elige el bloque más grande como ancla de un
   pallet nuevo, se coloca ENTERO (puede necesitar varias columnas/torres
   side-by-side dentro del MISMO pallet si el footprint es chico -eso no
   es "repartir en pallets", sigue siendo un solo pallet). Después se
   agregan, en orden de tamaño, otros bloques ENTEROS de otros SKUs -todo
   o nada- hasta que no entra ninguno más completo. Recién ahí, como
   último recurso, se parte UN bloque para terminar de llenar la altura.

### Cambios
- `src/packing_bloques.py` (nuevo): `armar_pallets_bloques(df_cd, cd,
  contador)`. `_colocar_bloque_completo` es la pieza clave -atómica con
  snapshot/rollback exacto (mismo patrón que `residual_search.py`): si el
  bloque completo no entra, no deja nada colocado a medias.
- `src/pipeline_sku_bloque.py` (nuevo): pipeline completo (VAL/DEM/GEO/DER
  compartido, BAT integrado igual que V5-BAT-integrado, sin multi-start
  -un único pase determinístico, como pide la instrucción).
- `src/pipeline.py`: `PACKER_VERSION="SKU_BLOQUE"` despacha acá.
- `tests/test_packing_bloques.py` (7 tests, incluye el ejemplo EXACTO del
  usuario -100 cajas, capacidad 150, un solo pallet- y validación
  geométrica con `validar_geometria_v5`).

### Bug encontrado y corregido durante el desarrollo
Primera versión de la colocación del "ancla": un solo llamado a
`mejor_ajuste(permitir_parcial=False)`, que internamente topa la cantidad
pedida en `max_cajas_verticales` (el límite de UNA sola columna). Con un
footprint chico frente a la cantidad (ej. 100 cajas en columnas de 20), el
bloque terminaba repartido en pallets NUEVOS uno detrás de otro (5
pallets de 20 en vez de 1 de 100) -exactamente el problema que la
instrucción pedía evitar. Atrapado por el test
`test_ejemplo_del_usuario_100_cajas_capacidad_150_un_solo_pallet`.
Corregido con `_colocar_bloque_completo`: coloca TODAS las columnas que
hagan falta dentro del MISMO pallet, atómico (rollback si no completa el
bloque entero).

### Resultado sobre el dataset real (demanda 18.08, mismo Maestro/UMA)
```
Real (hub, ayer):    48 pallets
AUTO (V4+V5):        50 pallets
SKU_CONSOLIDADO:     62 pallets
SKU_BLOQUE:          60 pallets
```
KR Cola Negra y las demás SKUs de alta rotación quedan confinadas a
EXACTAMENTE 1 pallet por CD (verificado). Sigue siendo más pallets que
AUTO (60 vs 50, +20%) -priorizar "SKU nunca repartido" por sobre el
conteo total de pallets tiene ese costo, igual que con SKU_CONSOLIDADO,
pero algo menor (60 vs 62) porque acá SÍ se combinan bloques enteros de
distintos SKUs activamente para acercarse a la altura óptima, en vez de
solo evitar abrir pallets nuevos.

### Invariantes
- 0 violaciones geométricas (`validar_geometria_v5` sobre el resultado real).
- Demanda exacta (`demanda_unidades_error=0.0`, total despachado
  coincide con la demanda de entrada).
- `config.PACKER_VERSION="SKU_BLOQUE"` activo localmente -reemplaza a
  SKU_CONSOLIDADO como el escenario de referencia actual.
- tests: ver corrida completa de la suite en este mismo commit del log.

---

## Limpieza — solo queda SKU_BLOQUE

Instrucción del usuario: quedarse con una sola versión (SKU_BLOQUE) y
borrar todo lo demás. Primero un commit local de checkpoint (`4ea5b07`,
solo local -no toca el repo de GitHub del dueño del proyecto) con TODO el
trabajo de la sesión, para poder recuperar cualquier cosa si hiciera
falta. Esta limpieza es el commit siguiente.

### Investigación previa (para no borrar nada que se usa de verdad)
Antes de borrar cualquier constante de `config.py` o archivo, se hizo grep
de cada candidato contra `src/` completo. Encontró casos no obvios:
- `soporte.clasificar_soporte_pallet` hace `if not pallet.camas: return` -
  como los pallets de SKU_BLOQUE siempre tienen `camas=[]`, la función es
  un no-op para todo el pipeline actual. Se dejó el archivo (bajo riesgo,
  no rompe nada) pero es candidato a retiro en una limpieza futura.
- `CATEGORIAS_REMATE`/`ORDEN_CATEGORIAS` parecían muertas (solo las usaban
  propiedades de `Cama` que nunca se ejercitan) pero en realidad las usa
  `config.nivel_de_categoria`, que SÍ llama `derivados.py` -se quedaron.
- `solver_cajas.py` parecía huérfano (nada lo importa directo) pero
  `reconciliacion_geometrica.py` sí lo usa (`from src.solver_cajas import
  max_cajas`) -se quedó. `layout_solver.py` (V5-P3, reemplazado por
  `packing_columnar.py` en P5) SÍ estaba huérfano de verdad -se borró.

### Borrado
- **Motores completos**: `pallets_homogeneos.py`, `packing_2d.py`,
  `apilado_3d.py` (V4/camas), `pipeline_v5.py` (V5 multi-start puro, se
  rescató `_palletv5_a_pallet` movida a `pipeline_sku_bloque.py`),
  `multistart.py`, `residual_search.py`, `pipeline_auto.py`,
  `pipeline_auto_consolidado.py`, `consolidacion_sku.py`,
  `pipeline_sku_consolidado.py`, `layout_solver.py`.
- **`legacy/`** completo (copias congeladas de los módulos V4 ya borrados).
- **`bat.py`**: cirugía, no borrado completo -se sacaron
  `asignar_hosts_bat`, `_redistribuir_para_bat`, `_buscar_host`,
  `_liberar_host`, `_consolidar_dedicados`, `_colocar_bat` (~345 de 531
  líneas, la lógica V4 de host dinámico) y el import de `apilado_3d`. Se
  mantuvo `separar_bat`, `consolidar_bat_por_cd`, `_peso_caja_bat` y toda
  la sección "BAT integrado".
- **`pipeline.py`**: de dispatcher de 5 ramas a una función que llama
  directo a `pipeline_sku_bloque`. Se sacó `ejecutar_core_v4` completo.
- **`config.py`**: `PACKER_VERSION`, `MULTISTART_SEEDS/MAX`,
  `PH_PREBUILD`, `PURE_FIRST`, `SOBRESALIENTE_PLANIFICACION`,
  `TOLERANCIA_ALTURA_PORTANTE/TERMINAL/MEZCLA`, `FILL_RATIO_MIN_SOPORTE`,
  `RESERVA_ALTURA_REMATE`, `ESTRATEGIA_CAMAS`, `CATEGORIAS_SIN_NADA_ENCIMA`,
  `MAX_SEPARACION_NIVELES` -todas sin ninguna referencia viva confirmada
  por grep. `benchmark.py._hash_config` se actualizó para no referenciar
  las que se fueron.
- **`run_tests.py`** (runner manual redundante con `pytest`, ya
  referenciaba módulos borrados) y docs V3 superadas
  (`DOCUMENTACION_TECNICA_V3.md`, `DOCUMENTACION_LOGICA_V3.md`,
  `Repo_Completo_Parcheado_v2.md`).
- **Tests**: se borraron los correspondientes a todo lo de arriba.
  `test_invariantes.py` y `tests/test_pipeline_real_data.py` no se
  borraron -se **reescribieron**: sacando los tests atados a
  `packing_2d._elegir_orientacion` (borrado) y a `pallet.camas`/
  `Cama.categoria_remate` (siempre vacío ahora), quedándose con los que
  sí son invariantes reales (determinismo, IDs únicos, tope de altura,
  demanda nunca excedida). `test_benchmark.py`/`test_pipeline_real_data.py`
  también se corrigieron: comparaban contra el prefijo `PH-BAT-` (solo
  existía en V4), que con SKU_BLOQUE nunca aparece -los tests pasaban
  igual pero de forma VACÍA (0 dedicados siempre, sin importar el
  resultado real), sin verificar nada de verdad. Corregido a `PV5-BAT-`.

### Bug real encontrado por la limpieza (no por casualidad -por correr la
suite completa después de cada cambio)
`test_demanda_planificada_coincide_con_demanda_redondeada` (que sobrevivió
la reescritura de `test_pipeline_real_data.py`) falló: faltaban 24 cajas
del SKU 22454 en SJ97 y 1 caja del SKU 15934 en BK65 -pérdida de demanda
silenciosa, sin ningún aviso en `sin_colocar`.

Causa: `_dedicar_por_sku` (packing_bloques.py) arma pallets 100%
dedicados asumiendo que la capacidad declarada por Maestro ("Cajas por
PH") siempre entra completa en un pallet fresco. Para SJ97/22454
(demanda 384, capacidad declarada 192 -> 2 pallets "dedicados" de 192
cada uno en teoría), el packer 3D real (MaxRects) solo logró colocar 180
en uno de los dos pallets -la fragmentación real de la huella (28.5x17cm)
no logra el empaque perfecto que asume el número del Maestro. El código
original hacía `break` en el loop de colocación y agregaba el pallet
IGUAL, sin registrar las 12 cajas que quedaban sin colocar en ESE pallet
-silenciosas, sin pasar por `sin_colocar`.

Corregido: si un pallet "dedicado" no logra completar la capacidad
declarada, el faltante se suma al `bloque` de ese SKU (`bloques[sku] +=
restante`) en vez de perderse -la fase de bloques lo intenta colocar en
otro lado, con el mismo mecanismo de "último recurso: partir uno" que ya
existía. Efecto colateral positivo: el total sobre el dataset real bajó
de 60 a **53 pallets** (esas cajas ahora se ubican de verdad en vez de
"desaparecer", lo que dejaba menos margen real del que el packer creía
tener).

### Resultado
```
Antes de la limpieza:  src/ ~5.030 líneas, 30 módulos, legacy/ 644 líneas
Después:                src/ ~2.775 líneas, 19 módulos, legacy/ borrado
                        (-45% en src/, -100% en legacy/)
tests/: ~2.510 -> ~1.540 líneas (17 archivos, antes ~23)
```
Dataset real (`Cubicaje18.07.2026.xlsx`): **53 pallets**, 0 violaciones
geométricas, demanda exacta -mejor que el 60 de antes de la limpieza,
gracias al bug de demanda encontrado en el camino.

### Lo que queda para una limpieza futura (Tier 2, no se tocó)
- `soporte.py` es un no-op para SKU_BLOQUE (`pallet.camas` siempre vacío)
  -candidato a retiro, junto con `Cama`/`PalletLinea.categoria_remate`/
  `visualizacion.dibujar_cama`/`dibujar_pallet` (la vista 2D por cama,
  inalcanzable ahora que no hay pallets con camas reales).
- Reescribir `exportar.py`/`benchmark.py` para trabajar nativo sobre
  `PalletV5` en vez de adaptar a `Pallet`/`Cama` -eliminaría la
  indirección del adaptador, pero es tocar código probado, no una
  limpieza de "borrar lo que no se usa".

### Invariantes
- Demanda exacta, 0 violaciones geométricas: verificado (arriba).
- `config.PACKER_VERSION="SKU_BLOQUE"` sigue activo -sin cambios de
  comportamiento salvo el bug corregido.
- tests: 102 passed (suite completa, sin skips -el checkpoint anterior
  tenía 158 pasando + 1 skip; los borrados de esta limpieza explican la
  diferencia de cantidad, no una regresión).

---
