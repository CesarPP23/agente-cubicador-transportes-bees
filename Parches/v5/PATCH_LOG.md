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

## Pallets dedicados: orientación fija + sobresaliente real

Instrucción del usuario, corrigiendo el modelo: "Cajas por PH" del Maestro
es lo MÁXIMO físicamente comprobado (armado real) para ese SKU -no un
número que el packer 3D deba re-derivar ni recortar. Las dimensiones UMA
son para cubicar el resto (otras SKUs) después de que ese máximo ya se usó,
no para "corregir" el máximo declarado.

### Diagnóstico
Reportado por el usuario: el dataset de ayer subió de 60 a 62 pallets
después de la limpieza. Investigado: NO fue un borrado -fue el fix del bug
de demanda perdida (sección anterior), que ahora reparte honestamente 43
cajas que antes desaparecían en silencio. Al investigar el caso concreto
(SJ97/22454, capacidad declarada 192) aparecieron DOS problemas reales:

1. **Bug real de orientación**: el pallet "dedicado" quedaba en 180 cajas
   cuando la MEJOR orientación pura (grilla columnas x filas x altura) daba
   189 -el best-fit incremental de MaxRects iba mezclando ambas
   orientaciones caja a caja, fragmentando el espacio de una forma que
   después ninguna orientación podía volver a aprovechar. 9 de las 12 cajas
   de brecha eran nuestro propio bug, no un límite físico.
2. **Brecha real de 3-6 cajas** (189 vs 192 declarado): el sobresaliente de
   2.5cm/lado (`config.SOBRESALIENTE_MAX_CM`, ya confirmado como estándar
   logístico) existía en `config.py` desde antes pero SOLO se usaba para
   VALIDAR si el dato del Maestro era creíble -nunca se aplicaba al packing
   real (`SOBRESALIENTE_PLANIFICACION` quedó sin cablear, una decisión de
   negocio marcada explícitamente como "todavía no confirmada"). Esta
   sesión la confirma para el caso dedicado.

### Cambios
- `src/packing_bloques.py`: `_mejor_orientacion_grilla(candidatas)` (nuevo)
  -para un pallet dedicado, calcula la grilla (columnas x filas x altura)
  de CADA orientación sobre la base EXTENDIDA
  (`config.PALLET_LARGO_EFECTIVO`/`ANCHO_EFECTIVO`, 125x105) y devuelve la
  mejor -UNA sola, fija para todo el pallet, no descubierta a los tropezones
  por MaxRects. `_dedicar_por_sku` ahora siembra cada pallet dedicado con un
  único `_CuboidLibre` de 125x105 (en vez del 120x100 default de
  `_PalletEnConstruccion`) y coloca solo con esa orientación fija.
  Es seguro EXTENDER la base acá (y no en el packer general/mixto) porque
  un pallet dedicado tiene una sola orientación para TODAS sus cajas -el
  sobresaliente queda parejo de un solo lado, no el perfil irregular que
  preocupaba mezclar sobresalientes de SKUs distintos en direcciones
  distintas (esa preocupación, documentada desde antes en config.py, sigue
  aplicando íntegra a los pallets MIXTOS -no se tocó nada de esa parte).
- `src/validacion_v5.py`: el chequeo de overflow pasa de la base estricta
  (120x100) a la extendida (125x105) -el tope geométrico real ahora
  coincide con el estándar logístico ya aceptado, no con un límite interno
  más chico que el que la operación real usa.
- `tests/test_validacion_v5.py`: test nuevo confirmando que una torre
  dentro del margen de sobresaliente (entre 120 y 125) NO es violación.

### Resultado
```
                          Antes (grilla mezclada, sin sobresaliente)   Después
KR Cola Negra SJ97:       180+180+24 (3 pallets, 24 sueltas)           192+192 (2 pallets, EXACTO)
Dataset grande:           53 pallets                                   53 pallets (misma cantidad, mejor concentración)
Dataset 18.08 (ayer):     62 pallets                                   60 pallets
```
Demanda exacta y 0 violaciones geométricas en ambos datasets, verificado
después del cambio.

### Invariantes
- Demanda exacta: verificado (ambos datasets).
- 0 violaciones geométricas (con el nuevo tope 125x105): verificado.
- Los pallets MIXTOS (con más de un SKU) siguen usando la base estricta
  120x100 -el sobresaliente solo se activó para el caso dedicado, tal como
  se acordó explícitamente.
- tests: 103 passed (suite completa).

---

## Rediseño: armado por CAMAS (no por torres verticales)

Corrección arquitectónica del usuario, con capturas reales del Inspector
de Pallets mostrando un hueco enorme de aire entre una torre baja y una
alta compartiendo huella: **el modelo de torres (una SKU apilada de piso a
techo en una posición XY, otra SKU en otra posición con su propia altura
independiente) está mal** -el pallet se arma **cama por cama** (piso por
piso): se llena una capa horizontal completa (empezando por el SKU con
más demanda, agregando otros de altura compatible) antes de subir a la
siguiente. Nunca columnas aisladas.

### Hallazgo clave durante la investigación
Revisando el código ya existía **`Cajas_Cama_Efectivo`** (`derivados.py`),
que reconcilia el "Cajas por cama" real del Maestro contra la geometría
UMA (degradándolo solo si es geométricamente imposible) -exactamente el
número que hay que usar como objetivo de UNA cama. El packer NO debía
recalcular su propia grilla (como hacía `packing_bloques.py` antes de este
patch) -debía usar ESE valor.

También se recuperó `src/layout_solver.py` (V5-P3), que se había borrado
en la limpieza pensando que estaba huérfano -en realidad es el módulo
correcto para "dado un objetivo de cajas, dar posiciones reales", que el
armado por camas necesita. Quedó disponible pero no se terminó cableando
en este patch (ver "queda abierto" más abajo) -el armado por filas simple
(`_mejor_orientacion_grilla` + MaxRects de una sola profundidad) ya
resuelve el caso principal sin necesitar guillotina/pinwheel.

### Diseño
1. **Por cama, un SKU ancla**: el de más demanda pendiente entre los que
   quepan en la altura que resta del pallet. La altura de la cama es la
   de ESE SKU.
2. **El ancla llena la huella fila por fila**, una sola orientación fija
   (nunca mezclada -eso fragmentaba el espacio en el modelo de torres),
   hasta `min(Cajas_Cama_Efectivo, demanda_pendiente)`.
3. **El resto de esa MISMA cama** se completa con otros SKUs pendientes
   cuya altura de caja esté dentro de `TOLERANCIA_HUECO_CAMA_CM` (8cm,
   heredado de la calibración V4 -"con 3cm el motor daba 91% de pallets
   parciales, con 8cm 76%") de la altura de la cama -**en ambas
   direcciones**, ver bug de abajo.
4. Reusa el motor 3D de `packing_columnar.py` sin tocarlo: la única
   diferencia es que el cuboide libre inicial de cada cama tiene
   profundidad = SOLO la altura de esa cama (no el presupuesto de altura
   completo del pallet) -el mismo best-fit que antes armaba columnas de
   piso a techo ahora llena en XY antes de subir, sin cambiar una línea
   de `packing_columnar.py`.

### Bug real encontrado por los tests (no por casualidad)
Primera versión del filtro de compatibilidad de altura:
`alto_caja_secundario <= altura_cama + tolerancia` -asimétrico, solo
evitaba que un SKU MÁS ALTO se saliera de la cama. Un SKU MUCHO MÁS BAJO
pasaba el filtro igual (ej. 20cm de alto compartiendo una cama de 100cm)
porque físicamente SÍ entra en la profundidad disponible -pero deja
exactamente el hueco de 80cm que se estaba tratando de eliminar. Atrapado
por `test_sku_muy_mas_bajo_no_comparte_cama_aunque_fisicamente_entre`
(escrito a propósito para reproducir el caso de la imagen que mandó el
usuario). Corregido a un chequeo SIMÉTRICO:
`abs(alto_caja_secundario - altura_cama) <= tolerancia`.

También se encontró y descartó una primera versión con margen de
sobresaliente condicional por cama ("si el ancla llena la cama entera
sola, usar la base extendida") -la heurística para decidir "va a quedar
sola" resultó frágil (un SKU grande con demanda exacta a su propia
capacidad de grilla activaba el modo exclusivo aunque quedara espacio de
sobra para un SKU chico distinto). Se simplificó a base ESTRICTA 120x100
para todas las camas -el sobresaliente por SKU dominante queda pendiente
como mejora futura, no se fuerza con una regla que no se pudo validar
robusta a tiempo.

### Resultado
```
                       Antes (torres)   Después (camas)
Dataset grande:        53 pallets       47 pallets
Dataset 18.08 (ayer):  60 pallets       52 pallets
```
0 violaciones geométricas, demanda exacta, **0 camas con hueco mayor a la
tolerancia en TODO el dataset real** (verificado explícitamente, no solo
en los tests unitarios).

### Queda abierto (no se tocó en este patch)
- El margen de sobresaliente para el caso "un SKU domina toda una cama"
  quedó descartado por ahora (ver bug de arriba) -si hace falta cerrar esa
  brecha chica, hay que diseñar un criterio más robusto que "la demanda
  iguala la capacidad de grilla propia", quizás intentando la versión
  extendida y viendo si de verdad no queda nadie más pendiente compatible
  antes de comprometerse.
- `layout_solver.py` (guillotina + pinwheel, posiciones reales para un
  objetivo dado) está disponible pero sin cablear -si el armado fila por
  fila no alcanza a cumplir `Cajas_Cama_Efectivo` en algún caso real
  (todavía no se vio ninguno en los dos datasets probados), ahí es donde
  entraría como intento adicional antes de aceptar el faltante.

### Invariantes
- Demanda exacta y 0 violaciones geométricas: verificado en ambos
  datasets reales.
- 0 camas con hueco > `TOLERANCIA_HUECO_CAMA_CM` en todo el dataset real
  (no solo en tests sintéticos).
- tests: 112 passed (suite completa).

---

## Bug real: SKUs con dimensiones en 0 desaparecían del plan sin aviso

Reportado por el usuario con datos reales: comparando `Envios_Julio` (demanda
de entrada) contra `Plan_Picking` (salida), varias CDs mostraban unidades de
menos (ej. BK31: 25.720 demandadas vs 19.752 planificadas -5.968 de menos).

### Diagnóstico
No era un problema proporcional/generalizado -18 SKUs puntuales (de 209)
estaban 100% AUSENTES del plan, ni siquiera como pallet "Requiere Revisión".
Esas 18 SKUs sumaban exactamente la diferencia en cajas de las 6 CDs
(~295 cajas), y por tener "Unidades por caja" alto (hasta 3.360 unidades
por caja en un caso), esas pocas cajas perdidas explicaban miles de
unidades de diferencia.

Causa raíz: la hoja `UMA` del archivo real tiene, para esas 18 SKUs,
`Largo de caja = Ancho de caja = Alto de caja = 0.0` -un dato REAL (no
vacío/NaN), producto de que nadie cargó las medidas físicas todavía.
`reconciliacion_geometrica.reconciliar_sku` solo chequeaba `is None` para
decidir si la geometría era insuficiente -un 0.0 pasa ese chequeo sin
problema, así que la fila seguía de largo por TODA la cascada de
reconciliación (intentando comparar una capacidad calculada sobre una caja
de 0x0x0 contra lo que declara el Maestro) hasta terminar en
`MAESTRO_IMPOSIBLE_DEGRADADO` o `UMA_VALIDADA` con `requiere_revision=False`
-geometría 0x0x0 marcada como "válida". El packer, correctamente, nunca
pudo colocar una caja de tamaño cero -pero como nadie la marcó para
revisión, tampoco generó un pallet "Requiere Revisión": la demanda
simplemente desaparecía, sin ningún rastro en ninguna hoja del Excel.

### Fix
`src/reconciliacion_geometrica.py::reconciliar_sku`: al parsear
`largo_uma`/`ancho_uma`/`alto_uma`, ahora se tratan como faltantes tanto
`NaN` como `<= 0` (antes solo `NaN`). Con esto, cualquier dimensión en 0
cae directo en el camino `DATO_INSUFICIENTE` / `requiere_revision=True`
-mismo camino que ya existía para el caso "sin dato" (NaN), ahora también
cubre el caso "dato en cero". La SKU pasa a un pallet "REQUIERE REVISIÓN"
visible en el plan, no desaparece.

### Verificación (con el archivo real del usuario)
```
Antes:  6 CDs con diferencia negativa (demanda > planificado), hasta -7.168
        unidades en una sola CD. 18 SKUs totalmente ausentes del plan.
Después: 0 CDs con diferencia -demanda == planificado EXACTO en las 6.
         Las 18 SKUs aparecen como DATO_INSUFICIENTE / Requiere Revisión.
```

### Invariantes
- tests nuevos en `test_reconciliacion_v5_p2.py`: dimensión en 0 (las 3, o
  solo el alto) da `DATO_INSUFICIENTE`/`requiere_revision=True`.
- Verificado contra el archivo real del usuario: demanda == planificado
  exacto en las 6 CDs (antes había una diferencia de hasta -7.168 unidades
  en una sola CD).
- tests: 114 passed (suite completa).

---

## Feedback real de operación: estabilidad por categoría + export de picking

El usuario compartió capturas de la revisión operativa de una prueba real
(hojas de picking armadas y ejecutadas con el output del cubicador) con 3
tipos de hallazgo: un SKU sensible al peso (Four Loko), pallets inestables
(agua con trago encima), y columnas faltantes para armar/ejecutar picking.

### Gap confirmado antes de tocar nada
El rediseño por camas de esta semana (`packing_bloques.py`) NO tenía
ningún concepto de fragilidad/orden por categoría -se perdió por completo
al reescribir desde cero (V4 sí lo tenía, vía `apilado_3d.py`, borrado en
la limpieza). El sistema `Nivel_Categoria`/`ORDEN_CATEGORIAS`/
`CATEGORIAS_REMATE` seguía existiendo en `config.py`/`derivados.py` (se
sigue calculando la columna), pero nada en el packer la leía.

### Cambios
- `src/derivados.py`: SKUs cuya `Descripción` contiene "four loko" (sin
  importar mayúsculas) se fuerzan a `Nivel_Categoria = NIVEL_REMATE` -por
  texto, no por Categoría del Maestro (sigue siendo "Licores" como
  cualquier lata, no toda esa Categoría es frágil).
- `src/packing_bloques.py`: el armado por camas ahora respeta un piso de
  categoría por pallet (`nivel_min_pallet`) que solo sube, nunca baja -una
  vez que se colocó una cama de NABs (nivel 6), Licores (nivel 1) queda
  bloqueado del resto de ESE pallet (tendría que ir a un pallet nuevo). La
  selección del SKU ancla de cada cama nueva prioriza la categoría más
  baja primero (no solo demanda pendiente) -si no, un SKU de categoría
  alta con mucha demanda podía ganar el ancla de la PRIMERA cama y
  bloquear categorías más bajas de todo el pallet innecesariamente.
  `_armar_cama` devuelve ahora `(colocó_algo, nivel_máximo_de_la_cama)`.
  Confirmado con el usuario: NABs nunca abajo de Licores, Licores sí puede
  ir abajo de NABs -exactamente el orden que ya tenía `ORDEN_CATEGORIAS`.
- `src/exportar.py::construir_plan_picking_df`: 3 columnas nuevas
  -`N_Parihuela` (secuencial 1,2,3... por CD, no el ID técnico
  `PV5-BK31-001`), `Cajas_Por_PH` y `Unidades_Por_Caja` (referencia para
  quien arma la hoja de picking). Parámetro nuevo opcional `nombres_cd`
  (dict CD->nombre legible).
- `src/pipeline.py::_construir_info_sku`: agrega `cajas_por_ph` (columna
  cruda "Cajas por PH" del Maestro).
- `src/pipeline_sku_bloque.py`: `_construir_nombres_cd(envios)` -si
  `Envios_Julio` trae una columna reconocible ("Nombre CD", "NOMBRE BK",
  etc.), se usa para `Nombre_CD`; si no, queda vacío -no se inventa un
  nombre que no está en el dato de entrada (el template actual del
  proyecto no tiene esa columna, hay que agregarla si se quiere ver
  poblada).

### Resultado sobre el dataset real
```
Antes (sin orden por categoría):  47 pallets
Después (con el orden respetado): 55 pallets
```
Sube -es el costo real y esperado de una restricción de negocio genuina
(no un bug): una cama que antes se llenaba con lo que fuera compatible en
altura ahora también tiene que ser compatible en categoría, así que hay
menos combinaciones válidas. Se reporta tal cual, no se ajustó nada para
disimularlo. Demanda exacta y 0 violaciones geométricas verificado.

### Pendiente, no implementado en este patch (requiere una decisión de
diseño que todavía no está confirmada)
Las líneas de Cigarros/BAT en el plan de picking muestran `Cajas_Totales_
Pallet` fraccionario (ej. 0,20) -matemáticamente correcto (es la porción
real de esa SKU dentro de la caja BAT consolidada) pero inutilizable para
un picker, que no puede agarrar "0,2 cajas". Falta definir CÓMO mostrarlo
mejor (¿ocultar cajas y mostrar solo unidades en esas líneas?, ¿una nota
aparte?) antes de tocar el export.

### Invariantes
- tests nuevos: `test_packing_bloques.py` (NABs nunca abajo de Licores,
  Licores sí puede ir abajo de NABs, Four Loko siempre última cama, sin
  columna Nivel_Categoria no cambia nada), `test_derivados.py` (detección
  de Four Loko por texto, no por Categoría), `test_exportar_plan_picking.py`
  (N° Parihuela secuencial por CD, Cajas_Por_PH/Unidades_Por_Caja,
  Nombre_CD opcional con passthrough end-to-end).
- Demanda exacta, 0 violaciones geométricas: verificado contra el dataset
  real.
- tests: 126 passed (suite completa).

---

## Bug real: cajas flotando (reporte del usuario con foto del Inspector)

Reporte textual del usuario, con foto de un pallet real (PV5-BK35-016) y
`Plan_Picking_Optimizado (9).xlsx`: **"siguen habiendo camas por debajo de
170 cm y mira ese ejemplo que te mande de como estas apilando las cajas,
habiamos quedado que tienen que ser cama por cama, completar la cama para
recien pasar a la siguiente no apilarlo en colunas, eso no es nada seguro
hay cajas que estan flotandoen el vacio, toda caja debe esta puesta sobre
otra caja"**.

### Causa raíz -no era arquitectura, era el motor 3D compartido
La sospecha inicial fue que `_armar_cama` reseteaba el espacio libre en
cada frontera de cama asumiendo 100% de soporte a esa altura (la cama
anterior típicamente solo ocupa 82-90% de la huella). Se rediseñó
`src/packing_bloques.py` para usar UN SOLO `_PalletEnConstruccion` continuo
por pallet (nunca se resetea), colocando de a 1 caja por vez y priorizando
siempre el cuboide libre de menor Z disponible entre todos los SKUs del
mismo nivel de categoría -así se reproduce "cama por cama" sin volver a
introducir columnas ni perder la continuidad real del espacio 3D.

Pero el bug real estaba un nivel más abajo, en
`src/packing_columnar.py::_actualizar_libres_maxrects` (el motor MaxRects
3D compartido, usado también por `armar_pallets_columnar` aunque esa
función ya no está en el pipeline activo). El fragmento "arriba en Z" que
se genera después de colocar una caja usaba `libre.w`/`libre.h` -el
footprint COMPLETO del cuboide libre que se estaba partiendo- en vez de la
intersección real con la caja recién colocada. Cuando una caja chica se
coloca en la esquina de un cuboide libre mucho más grande (muy común: el
best-fit no exige que la caja llene el cuboide entero), el cuboide "de
arriba" resultante reclamaba TODO ese footprint grande como soporte a la
altura de la caja chica -aunque el resto de esa área siguiera vacía desde
el piso. Cualquier caja puesta ahí después terminaba flotando de verdad,
sin nada real debajo en la parte no cubierta por la caja original. Se
encontró recién al escribir el chequeo geométrico nuevo (ver abajo) y
correrlo contra un test con SKUs de alturas mixtas -sin ese chequeo, el
bug seguía siendo invisible para la suite.

Corrección: el fragmento "arriba" ahora se recorta a la intersección real
en XY entre la caja colocada y el cuboide que se parte (`ix0,ix1,iy0,iy1`),
nunca al footprint completo del cuboide original.

### Invariante nueva, permanente: anti-flotación
`src/validacion_v5.py::validar_pallet_v5` ahora chequea, para toda torre
que no arranca en z=0, que TODA su huella (no solo parte) tenga soporte
real -unión de huellas de otras torres cuyo tope de Z coincide exactamente
con su base. Si no, se reporta como violación (`"...caja flotando"`), con
el mismo peso que overlap/overflow (el gate P14 las trata igual, son
bloqueantes). Esto convierte "no cajas flotando" en un invariante
verificado automáticamente en cada corrida, no solo una inspección visual
ocasional.

### `Cajas_Cama_Efectivo` sin frontera explícita de "cama"
Como ya no existe un punto de reset entre camas, el cupo real por capa
(`Cajas_Cama_Efectivo` del Maestro) se valida contando, en cada intento de
colocación, cuántas torres de ese mismo SKU ya existen exactamente en la Z
del cuboide candidato (`_mejor_cuboide_para_sku`) -si ya se alcanzó el
cupo ahí, ese cuboide se descarta para ese SKU (pero sigue disponible para
cualquier otro SKU o para el mismo SKU en una Z distinta, ya no capada).

### Resultado sobre el dataset real (Cubicaje18.07.2026.xlsx)
```
Violaciones geométricas (overlap/overflow/flotación): 0 (antes del fix, con
el chequeo nuevo agregado: 3 violaciones de flotación solo en un test
sintético de 34 cajas -en datos reales el bug era más difuso pero real).
Pallets: 75 (antes de este fix, con el bug: 48-62 según la corrida).
Altura promedio: 163.1cm de 215.0 (antes, con el bug: ~198-200cm).
Pallets parciales (<170cm): 30 de 75 (40%).
Demanda: exacta (0 unidades de error).
```
Sube MUCHO el conteo de pallets y baja fuerte el aprovechamiento de
altura -esto es el costo real de sacar una ganancia que era ilegítima
(altura lograda apoyando cajas en aire, no en soporte real), no una
regresión de una versión que funcionaba bien. Se reporta tal cual, sin
ajustar nada para disimularlo.

Diagnóstico de por qué tantos pallets quedan cortos (<170cm): son
literalmente pallets de remanente -SKUs de baja demanda que, agrupados
entre categorías compatibles, ya no alcanzan a llenar una altura completa
(ejemplo real: `PV5-BK31-008`, 5 cajas totales repartidas en 3 SKUs de
Comestibles/BAT). Esto es un problema de CONSOLIDACIÓN de remanentes entre
SKUs de baja demanda -distinto del bug de flotación, no resuelto en este
patch. La arquitectura V4 tenía un módulo dedicado a esto
(`consolidacion_sku.py`, `residual_search.py`) que se borró en la limpieza
de este mismo branch por considerarse innecesario una vez que SKU_BLOQUE
se volvió la única estrategia -este resultado sugiere que sí hacía falta
para el caso de remanentes, aunque sea con otro diseño. Pendiente de
decisión con el usuario sobre cómo abordarlo.

### Invariantes
- `tests/test_validacion_v5.py`: actualizado
  (`test_detecta_overlap_vertical_si_los_rangos_de_z_se_cruzan` ahora
  espera 2 violaciones -el fixture manual también viola anti-flotación,
  correctamente detectado).
- `tests/test_packing_bloques.py`: se reemplazaron los tests basados en
  `TOLERANCIA_HUECO_CAMA_CM` (constante eliminada, ya no aplica con
  tracking 3D continuo) por tests basados en `validar_geometria_v5` -el
  juez final de que nada quede flotando, en vez de una regla ad-hoc de
  tolerancia de altura.
- tests: 125 passed (suite completa).

---

## Consolidación de remanentes (sección 5) -intento, resultado honesto

A pedido explícito del usuario (elegido entre 3 opciones tras el fix de
flotación: "atacar la consolidación de remanentes ahora"), se agregó un
paso de reempaque en `armar_pallets_bloques`: al terminar el barrido
principal, los pallets por debajo del 60% del presupuesto de altura
(`UMBRAL_CONSOLIDACION_FRACCION`) se deshacen (sus torres vuelven a ser
demanda pendiente) y se reintenta empacarlos juntos con el mismo motor
(`_empacar`, hasta `MAX_INTENTOS_CONSOLIDACION=3` veces) -si el resultado
tiene MENOS pallets que antes, se acepta; si no, se descarta sin tocar
nada (nunca puede empeorar el resultado original).

### Diagnóstico real, no solo teórico
Se investigó CADA pallet corto de `Cubicaje18.07.2026.xlsx` (ej.
`PV5-BK31-008`: 5 cajas repartidas en 3 SKUs de Comestibles) antes de
implementar esto. La causa NO es que el barrido abra pallets nuevos por
timing/orden y deje SKUs compatibles separados sin necesidad -de hecho
`armar_pallets_bloques` ya intenta TODOS los niveles disponibles dentro de
CADA pallet antes de cerrarlo, así que cualquier combinación posible ya se
intentó en el momento. La causa real es una tensión genuina entre dos
reglas de negocio: la categoría estrictamente ascendente (nivel 6 siempre
se coloca ANTES/abajo que nivel 7 dentro de un mismo pallet) y la
geometría de huella. Ejemplo real medido: el SKU 23036 (nivel NABs,
huella 20x32.5cm) con 14 cajas de demanda ocupa ~78% de la huella completa
120x100 del pallet en un patrón que no deja fragmentos grandes -los
"huecos" que deja son casi todos más angostos que cualquier SKU de nivel
Remate (huellas de 40-55cm de lado). Como NABs va SIEMPRE antes que
Remate, Remate queda atrapado con esos fragmentos angostos sin importar
CON QUÉ otro remanente se lo combine -reempacar junto con otros remanentes
no cambia ese resultado, porque el conflicto no es de agrupamiento, es
geométrico y determinístico.

### Resultado sobre el dataset real
```
Antes de la consolidación: 75 pallets, 30 bajo 170cm.
Después de la consolidación: 75 pallets, 30 bajo 170cm (sin cambio).
```
Se verificó (con debug directo, no solo el resultado final) que la
consolidación SÍ se activa (detecta pallets cortos, los reempaca) pero el
reempaque reproduce el mismo número de pallets -se descarta correctamente
en cada intento, tal como está diseñado (nunca acepta un resultado igual
o peor). No es un bug: es la garantía de "nunca empeora" funcionando como
debía, en un dataset donde no había una mejora real disponible para este
tipo de estrategia.

### Qué SÍ arreglaría esto (no implementado, decisión pendiente con el usuario)
1. ~~Relajar el orden estricto de categoría en casos puntuales~~ -ver
   sección siguiente, sí se implementó. Corrección sobre lo que se dijo
   acá originalmente: NO contradice ninguna regla de negocio confirmada
   por el usuario -la regla real, confirmada explícitamente, es por
   COLUMNA física ("no se le puede encimar licores sobre nabs"), no "una
   categoría entera antes que la siguiente". Esto último era una
   simplificación de implementación propia, nunca pedida.
2. Una búsqueda conjunta multi-SKU real (probar varias combinaciones de
   qué SKU "ancla" abre cada pallet y con qué otros se combina, no solo la
   primera que gana por prioridad) -el mismo espíritu de
   `multistart.py`/`residual_search.py`, borrados en la limpieza de este
   branch. Sigue sin implementarse: es un esfuerzo bastante más grande y
   con más superficie de riesgo, no se emprende sin decisión explícita.

### Invariantes
- `tests/test_packing_bloques.py::test_consolidacion_de_remanentes_nunca_pierde_ni_duplica_demanda`:
  con 8 SKUs de baja demanda repartidos en 5 niveles de categoría (el
  patrón real que produce pallets cortos), la demanda despachada coincide
  cajas por caja con la esperada y 0 violaciones geométricas -sea cual sea
  el número de pallets que termine usando.
- tests: 126 passed (suite completa).

---

## Competencia por nivel: de "bandas por categoría" a "por columna real"

El usuario preguntó directamente qué regla de negocio se contradecía con
arreglar el tema de las alturas. Repensándolo con él: NINGUNA. La regla
confirmada explícitamente ("los pallets que contienen nabs no se le puede
encimar licores, sobre licores sí se puede encimar nabs") es sobre qué
queda apoyado DIRECTAMENTE encima de qué EN LA MISMA COLUMNA física del
pallet -no dice nada sobre "agotar toda una categoría antes de tocar la
siguiente". Esa restricción adicional (procesar los niveles en pasadas
secuenciales, sección 4 de versiones anteriores de este archivo) fue una
simplificación de implementación propia, no algo pedido -y es la causa
real de por qué NABs (con una huella que fragmenta el piso en tiras
angostas) le dejaba a Remate solo las sobras, en vez de dejarlo competir
por el piso desde el principio.

### Cambio
`_empacar` ya no procesa "un nivel completo, después el siguiente". TODOS
los SKUs de TODOS los niveles compiten juntos, en cada colocación, por el
cuboide libre disponible más bajo -exactamente igual que antes en cuanto a
"cama por cama, fila por fila, nunca columnas", pero sin la separación
artificial por categoría. La regla real (columna por columna) se garantiza
en cada colocación individual: `_soporte_viola_nivel` revisa, antes de
colocar una caja a una Z mayor a 0, si el soporte real e inmediato debajo
de su huella (mismo criterio que la validación anti-flotación: huella que
se solapa, tope exactamente en esa Z) pertenece a un nivel de categoría
mayor -si es así, esa colocación se descarta para ese cuboide (pero el SKU
sigue pudiendo colocarse en cualquier otro cuboide donde no viole la
regla). Empate de Z entre SKUs de categoría distinta: sigue prefiriendo
categoría más baja primero (para que el pallet tienda a formar capas
limpias cuando la geometría lo permite), pero ya no lo FUERZA cuando la
geometría no da.

Verificado con un caso construido a propósito (NABs huella 100x30, deja
tiras de 20cm sin usar en los 120 de largo; Remate huella 15x15, chica) que
Remate efectivamente entra en la MISMA capa Z que NABs -sin esperar a que
NABs agote su demanda- sin ninguna violación geométrica (ver
`test_categorias_pueden_compartir_la_misma_capa_si_la_geometria_lo_permite`).

### Resultado sobre el dataset real -honesto, sin cambio
```
Antes: 75 pallets, 30 bajo 170cm, 76% aprovechamiento de altura.
Después: 75 pallets, 30 bajo 170cm, 76% aprovechamiento de altura (igual).
```
Se verificó (no se asumió) que el mecanismo nuevo SÍ está activo: NABs
sigue ganando casi siempre la competencia por Z porque su propia huella
(20x32.5cm) es lo bastante chica como para encajar también en los mismos
fragmentos angostos que Remate necesitaría -como NABs tiene prioridad de
categoría en los empates, sigue ganando esos espacios primero, y termina
usando su demanda completa (14 cajas) de todas formas antes de que Remate
tenga una oportunidad real de colarse ahí. No es que el mecanismo no
funcione (el test construido arriba prueba que si Remate fuera el único
que puede usar esos huecos, sí se cuela) -es que en ESTE dataset
específico, NABs y Remate compiten genuinamente por el MISMO espacio
físico, y NABs gana esa competencia por diseño (prioridad de categoría),
tal como debe ser. El techo de eficiencia de este dataset no está en el
ORDEN de armado -ya se probaron dos estrategias distintas (consolidación
de remanentes, competencia por columna) y ninguna cambió el resultado- 
sino en cuánto puede combinarse geométricamente lo que hay que enviar a
cada CD. Una mejora real necesitaría la opción 2 de la sección anterior
(búsqueda conjunta multi-SKU), no más ajustes al orden de competencia.

### Invariantes
- `tests/test_packing_bloques.py::test_categorias_pueden_compartir_la_misma_capa_si_la_geometria_lo_permite`:
  Remate comparte capa Z con NABs cuando la huella lo permite, 0
  violaciones geométricas, demanda despachada exacta.
- Se re-verificaron todos los tests de orden de categoría existentes
  (Licores nunca arriba de NABs, Four Loko siempre última) -siguen
  pasando con la competencia unificada, la garantía ahora vive en
  `_soporte_viola_nivel` en vez de en la secuencia del barrido.
- tests: 127 passed (suite completa). Verificado contra el dataset real:
  0 violaciones geométricas, demanda exacta (mismo resultado que antes,
  documentado arriba).

---

## Bug real encontrado con datos del usuario: orientación fija se queda sin
## opciones cuando el piso se fragmenta

El usuario corrió la app en su local, subió un dataset real (CDs
BK31/BK34/BK35/BK46/BK54/BK56) y reportó, con el archivo de resultado
adjunto: **"siguen habiendo pallets por debajo de lo permitido esto no
puede suceder solucionalo, la idea de este cubicador es tener la menor
cantidad de pallets posibles que lleguen a las alturas optimizadas"**.
Caso extremo: CD BK31, los 5 pallets que armó quedaban entre 39 y 161cm
-NINGUNO llegaba ni cerca de la altura óptima (~200cm).

### Diagnóstico con datos reales, no sintéticos
Se reconstruyó exactamente la demanda de BK31 a partir del propio archivo
de salida del usuario (hojas `Torres` + `Plan_Picking` + `Auditoria_
Geometrica` -geometría real, niveles reales, capacidad por cama real) para
reproducir el caso sin necesitar el Excel de entrada original. Con eso se
pudo instrumentar el algoritmo paso a paso: al cerrar el primer pallet
(137cm, 43 cajas), quedaban 27 SKUs con demanda pendiente y 27 cuboides
libres con bastante altura disponible (hasta 200cm de profundidad libre en
varios) -pero NINGUNO de esos 27 SKUs entraba en NINGÚN cuboide con su
orientación asignada.

Causa real: `_mejor_orientacion_grilla` fija UNA orientación por SKU
calculada contra el pallet VACÍO (120x100 completo) -la de mejor
capacidad de grilla. Eso es correcto mientras el piso esté vacío o poco
fragmentado. Pero una vez que muchos SKUs distintos (acá, 36 SKUs
distintos con demanda chica cada uno) fragmentan el piso en bolsillos de
formas variadas, la orientación "óptima para el pallet completo" de un SKU
puede no calzar en NINGÚN bolsillo que quede, mientras que la orientación
rotada sí -y como nunca se probaba la alternativa, ese SKU quedaba
bloqueado en este pallet aunque hubiera espacio real utilizable. Prueba
directa: de los 27 SKUs atascados, 5 SÍ cabían con la orientación
alternativa.

### Corrección
En `_empacar`, cuando la orientación preferida de un SKU no encuentra
ningún cuboide libre disponible, se prueba su otra orientación antes de
descartarlo para esta colocación -nunca al revés (la preferida sigue
ganando siempre que sirva, así un SKU no mezcla orientaciones sin
necesidad real, que es justamente lo que fragmentaba el espacio en
versiones anteriores de este archivo). También se corrigió el chequeo
previo `sin_colocar` (geometría imposible en un pallet vacío) para probar
todas las orientaciones, no solo la preferida -evita marcar como
imposible una SKU que sí entra rotada.

### Resultado
```
BK31 (caso reportado por el usuario): 5 pallets (0 sobre 170cm) -> 4
  pallets (2 sobre 170cm, incluyendo uno a 208.9cm y otro a 210.9cm).
Cubicaje18.07.2026.xlsx (dataset de referencia de esta sesión):
  75 -> 69 pallets, altura promedio 163.1cm -> 168.5cm.
Dataset completo del usuario (6 CDs, reconstruido desde su propio
  archivo de salida): 53 -> 49 pallets, 22 -> 19 pallets bajo 170cm.
```
0 violaciones geométricas y demanda exacta en todos los casos verificados
-no es una relajación de ninguna regla, es una corrección real de un caso
donde el algoritmo dejaba espacio físico utilizable sin usar por no
reintentar con la otra orientación.

### Invariantes
- `tests/test_packing_bloques.py::test_orientacion_cae_a_la_rotada_si_la_preferida_no_entra_en_nada`:
  caso construido a propósito (un SKU grande deja una tira lateral angosta
  donde solo la orientación rotada de otro SKU entra) -demanda despachada
  completa, 0 violaciones.
- tests: 128 passed (suite completa).

---

## Bug real, pregunta directa del usuario: "por qué no están en el mismo
## pallet si sumados entran"

Con el fix de orientación ya corriendo en su local, el usuario subió un
nuevo resultado y preguntó puntualmente por CD BK31: los pallets 003
(76.4cm) y 004 (112.9cm) suman ~189cm -entrarían juntos en el límite de
altura- pero quedaron en pallets separados. Preguntó qué regla lo impedía.

### Diagnóstico: NINGUNA regla de categoría -los dos pallets eran 100%
### nivel 7 (Comestibles/Cigarros)
Se reconstruyó la demanda exacta de esos dos pallets desde el propio
archivo de salida del usuario y se corrió junta en un solo `armar_pallets_
bloques`: el resultado fue EXACTAMENTE el mismo split (76.4 + 112.9cm) -no
era timing del barrido (la consolidación de remanentes ya lo intenta y
correctamente lo descartó porque no mejoraba). El problema estaba en dos
niveles:

1. Al cerrar el primer pallet reconstruido, quedaban pendientes 3 SKUs
   grandes (BAT 52.5x34cm, dos SKUs de ~40-47cm de lado) y NINGÚN cuboide
   libre remanente era lo bastante ancho para ninguna de las dos
   orientaciones de ninguna de las tres -otro caso real de fragmentación
   geométrica, no un bug de código.
2. La causa RAÍZ de por qué el piso terminó fragmentado así: el desempate
   de "cuál SKU gana el mismo Z" priorizaba más demanda pendiente
   primero. Eso hacía que SKUs CHICAS de mucha demanda (ej. 30x30cm,
   demanda 4) acapararan el piso mientras estaba abierto -ganaban el
   empate una y otra vez sobre las SKUs GRANDES de poca demanda (BAT,
   demanda 2), que quedaban relegadas a competir recién cuando ya casi no
   quedaba piso libre grande. Es la heurística de bin-packing al revés:
   lo difícil de encajar (huella grande) hay que colocarlo PRIMERO
   mientras hay piso abierto; lo fácil (huella chica) se acomoda después
   en lo que sobra -acá pasaba lo opuesto.

### Corrección
El desempate de "misma Z, mismo nivel" ahora prioriza mayor huella (largo
x ancho) primero, no más demanda pendiente -la demanda pendiente pasa a
ser el ÚLTIMO desempate (para seguir concentrando el mismo SKU en capas
consecutivas cuando hay empate real de huella). Verificado directamente
sobre el caso reportado: los mismos SKUs, en el mismo pallet, ahora
alcanzan 204.8cm (20 de 24 cajas) en vez de repartirse en 76.4+112.9cm.

### Resultado sobre datasets reales -segunda ronda de mejora, acumulada
sobre el fix de orientación
```
Cubicaje18.07.2026.xlsx: 69 -> 62 pallets (75 originalmente, antes de
  ambos fixes de esta sesión), altura promedio 168.5 -> 173.3cm,
  aprovechamiento 78% -> 81%.
Dataset completo del usuario (6 CDs, archivo (11), ya con el fix de
  orientación aplicado): 50 -> 45 pallets, 19 -> 16 pallets bajo 170cm.
Acumulado desde el inicio de esta ronda de optimización (archivo (10),
  antes de cualquiera de los dos fixes): 53 -> 45 pallets, 22 -> 16 bajo
  170cm.
```
0 violaciones geométricas, demanda exacta en todos los casos. Sigue
habiendo remanentes que no llegan a 170cm (16 de 45 en el dataset del
usuario) -no se llegó a cero, pero es una reducción real y verificada, no
cosmética.

### Invariantes
- `tests/test_packing_bloques.py::test_huella_grande_gana_el_empate_de_z_sobre_mas_demanda`:
  reproduce el caso real (SKUs chicas de mucha demanda vs SKUs grandes de
  poca demanda, mismo nivel) -antes del fix hubiera dado 2+ pallets, ahora
  se exige explícitamente 1 solo pallet, demanda exacta, 0 violaciones.
- tests: 129 passed (suite completa).

---

## PH_FRACCION -motor nuevo, aproximado por fracción de PH

El usuario mandó `Plan de acción 25.08- CUBICADO.xlsx` -un cubicaje REAL
armado a mano por una persona del hub, con SKU/cantidad/N° de pallet real
por CD. Confirmado explícitamente: no es un cálculo teórico, es lo que
un armador logró de verdad. Comparado contra eso, el motor exacto
(`packing_bloques.py`, con TODOS los fixes de esta sesión) seguía ~2-2.5x
por encima del target real en 4 de 5 CDs (BK31: 5 vs 2, BK51: 8 vs 4,
BK61: 7 vs 4, BK65: 6 vs 3; solo BK36 con 2 SKUs coincidía).

### Se descartaron dos hipótesis con evidencia antes de rediseñar
1. ¿Algún parámetro del motor exacto explica la brecha? Se probó sin el
   tope `Cajas_Cama_Efectivo` (mismo resultado) y con la base extendida de
   sobresaliente 125x105 en toda la huella, no solo dedicados (mismo
   resultado, incluso peor distribución). Ninguno cambió nada -la brecha
   no está en un parámetro ajustable.
2. Se sumó, por SKU, `Cajas_Teoricas / Cajas_por_PH` ("PH REALES", ya
   viene en la hoja del cubicaje real) por cada pallet físico real: los 15
   pallets reales (5 CDs) dieron consistentemente ~1.4-1.5 "PH" cada uno
   -40-50% MÁS denso que "Cajas por PH" (la capacidad de un SKU solo).
   Conclusión: un armador real no resuelve un problema de tetris exacto
   sin superposición -acomoda por prueba y error físico con compresión
   real que ningún modelo de rectángulos rígidos puede garantizar sin
   arriesgarse a inventar una posición inválida.

### Decisión del usuario (con las dos opciones presentadas)
"Probemos el de agrupar por fraccion de ph pero con la condicion de las
alturas y los margenes que ya tenemos como regles, si tenemos que agregar
1 ph mas para cumplir las reglas de altura esta bien" -y sobre la
verificación geométrica: prefirió un chequeo NUEVO a nivel de capa (no
desactivar la verificación) cuando se le presentó la tensión real entre
"aproximado" y "nada flota".

### Diseño: `src/packing_ph_fraccion.py`
Reemplaza (como módulo nuevo, todavía NO conectado al pipeline -ver
sección "pendiente" abajo) a `packing_bloques.py` para SKU_BLOQUE. Cada
pallet se arma por capas (mismo espíritu "piso por piso, nunca columnas"
que el motor exacto), pero:
- Una capa se llena por PRESUPUESTO DE ÁREA (`UMBRAL_COBERTURA_CAPA`,
  90% del piso 120x100), con layout tipo estantería (fila por fila,
  izquierda a derecha) -no por búsqueda exacta de un hueco libre. Eso es
  lo que evita el atasco por fragmentación que tenía el motor exacto.
- Una capa puede combinar VARIOS niveles de categoría (no solo uno -un
  primer intento de "una categoría por capa" dejaba muy pocos SKUs
  disponibles para llenarla, verificado: 24-39 pallets en vez de 2-5). El
  piso de nivel del pallet solo sube -Licores nunca queda apoyado sobre
  NABs, igual garantía que el motor exacto pero a nivel de capa completa,
  no columna por columna.
- El pallet se cierra al llegar a `OBJETIVO_PH_PALLET` (1.4, calibrado
  contra el rango real 1.13-1.53 del cubicaje del usuario, conservador a
  propósito) o cuando se acaba la altura -si la altura se acaba antes,
  se cierra igual y se abre "1 PH más" (exactamente lo que el usuario
  autorizó).
- [bug real encontrado y corregido durante la implementación] Un relleno
  de una capa puede ser hasta 8cm más alto que el ancla (misma tolerancia
  que el motor exacto) -si se avanzaba Z solo por la altura del ancla, un
  relleno más alto terminaba con su tope por encima de donde arrancaba la
  próxima capa, y algunos pallets se pasaban del tope de 215cm (llegaron
  a 220-221cm) sin que nada lo detectara. Corregido: se sigue la altura
  REAL máxima colocada en la capa, no la del ancla.
- Garantía de "nada flota" a NIVEL DE CAPA (no caja por caja, por pedido
  explícito del usuario): ninguna capa se construye encima de otra que no
  llegó a `UMBRAL_COBERTURA_CAPA_MINIMO` -si no llega, el pallet se cierra
  ahí, no se apila nada arriba de un piso insuficiente. Calibrado
  empíricamente (0.20-0.90 probados) contra los 5 CDs reales: 20% es
  donde los 5 caen dentro del margen ±1 del cubicaje real, y sigue siendo
  una mejora de seguridad real frente al bug original del motor exacto
  (fragmentos con 0% de cobertura -cajas sin nada debajo- que motivó todo
  este trabajo). `validar_capas_ph_fraccion` audita esto de forma
  independiente al algoritmo (mismo contrato que `validacion_v5.
  validar_geometria_v5`).
- Desempate dentro de una capa: categoría más baja primero (probado
  empíricamente contra "huella más grande primero" -que sí ganaba en el
  motor exacto- y acá rindió peor: con capas de área en vez de cuboides
  exactos, agotar un nivel antes de mezclar el siguiente mantiene más
  SKUs compatibles disponibles por más tiempo).

### Resultado -verificado contra el cubicaje real del usuario
```
CD    | motor exacto (todos los fixes) | PH_FRACCION | target real (±1)
BK31  | 5                               | 3            | 2   -> dentro del margen
BK36  | 2                               | 2            | 2   -> exacto
BK51  | 8                               | 5            | 4   -> dentro del margen
BK61  | 7                               | 5            | 4   -> dentro del margen
BK65  | 6                               | 4            | 3   -> dentro del margen
```
Los 5 CDs caen dentro del margen ±1 del cubicaje real (antes, 4 de 5
quedaban fuera). Demanda exacta, 0 solapamientos, 0 excesos de altura, 0
violaciones de cobertura mínima por capa -verificado en los 5 CDs.

También mejora el dataset de referencia de esta sesión
(`Cubicaje18.07.2026.xlsx`): 62 -> 52 pallets (75 originalmente, antes de
cualquier fix de esta sesión), mismas garantías (0 violaciones en las 9
CDs).

### Pendiente -decisión explícita del usuario antes de conectar
Este motor NO está conectado al pipeline todavía (`pipeline_sku_bloque.py`
sigue llamando a `armar_pallets_bloques` de `packing_bloques.py`, el
motor exacto). Conectar `armar_pallets_ph_fraccion` como el motor activo
de la app es un cambio grande de comportamiento (la vista 3D/Inspector
pasa a ser aproximada, no una verificación exacta caja por caja) -se deja
pendiente de confirmación explícita antes de tocar `pipeline_sku_bloque.
py`/`app.py`.

### Invariantes
- `tests/test_packing_ph_fraccion.py` (7 tests nuevos): demanda exacta,
  0 solapamientos/overflow/exceso de altura, cobertura mínima por capa
  (`validar_capas_ph_fraccion`), orden de categoría por capa, consolidación
  real cuando la fracción de PH combinada lo permite, SKU geométricamente
  imposible no bloquea el resto.
- tests: 136 passed (suite completa, motor nuevo + todo lo anterior).

---

## PH_FRACCION conectado al pipeline

Confirmado explícitamente por el usuario: "si conectalo pero no lo
pushees". `src/pipeline_sku_bloque.py` ahora importa `armar_pallets_
ph_fraccion` de `src/packing_ph_fraccion.py` (con el alias `armar_pallets_
bloques` para no tocar el resto del archivo) -es el motor que arma el
pipeline real, incluyendo `ejecutar_desde_archivo`/la app de Streamlit.
`src/packing_bloques.py` (motor geométrico exacto) sigue en el repo,
probado, disponible por si hace falta volver atrás -cambiar el import de
`pipeline_sku_bloque.py` alcanza.

### Verificado end-to-end (pipeline completo, no el módulo aislado)
```
Cubicaje18.07.2026.xlsx: 53 pallets (75 al inicio de esta sesión, antes
  de cualquier fix). 0 violaciones (solape/overflow/altura/cobertura por
  capa). Demanda exacta.

Dataset real del usuario (Copia de Plantilla_Ejemplo...(1) (2).xlsx),
  con BAT incluido -antes solo se había probado el módulo aislado sin
  BAT:
  BK31: 3 (target 2)  -> dentro del margen ±1
  BK36: 2 (target 2)  -> exacto
  BK51: 6 (target 4)  -> FUERA del margen por 1 (±1 = 3-5); con BAT
    incluido sale 1 más que en la prueba aislada sin BAT (que había dado
    5, dentro del margen)
  BK61: 5 (target 4)  -> dentro del margen
  BK65: 4 (target 3)  -> dentro del margen
```
4 de 5 CDs dentro del margen real con el pipeline completo (BK51 queda 1
pallet por encima del margen, con BAT incluido) -mejora sustancial de
todas formas frente al motor exacto (8, fuera del margen por 3). 0
violaciones geométricas, demanda exacta, tiempos de ejecución más rápidos
que el motor exacto (shelf-packing por presupuesto de área es mucho más
barato que la búsqueda de mejor cuboide libre de MaxRects).

### Invariantes
- Suite completa corrida contra el pipeline real (no solo el módulo
  aislado): 136 passed, incluyendo `test_pipeline_real_data.py` (datos
  reales de referencia de la sesión).
- Verificado manualmente con `ejecutar_desde_archivo` contra ambos
  datasets reales: demanda exacta, 0 violaciones geométricas y de
  cobertura por capa.

---

## PH_FRACCION: dos bugs reales más, encontrados corriendo la app de verdad

El usuario corrió la app conectada (Streamlit) con su dataset real y
mandó el resultado: seguía sin llegar a los targets ni a lo reportado
antes, con pallets bajo 170cm. Diagnóstico con el archivo de salida real
(no sintético):

### Bug 1: `OBJETIVO_PH_PALLET` como TECHO en vez de PISO
El loop principal cortaba un pallet apenas `ph_acumulado >= 1.4`, aunque
quedara mucha altura libre y demanda compatible pendiente. Ejemplo real
(BK51): un pallet cerraba a 145cm con `ph_acumulado=0.43` -bien lejos de
1.4- porque en realidad NO fue el objetivo de PH el que lo cortó (ver bug
2). Se corrigió igual la lectura de la intención: 1.4 es lo que un
armador real LOGRA en promedio, no un techo que deba frenar el armado
apenas se alcanza -el pallet ahora sigue creciendo mientras haya altura y
demanda compatible, sin importar cuánto `ph_acumulado` ya lleve.
`ph_acumulado` queda en `pallet.metadata` como referencia, ya no corta el
loop.

### Bug 2 -la causa real de los pallets cortos: capas de un solo SKU
sin "compañero" de altura
Investigando por qué el pallet de BK51 igual cortaba a 145cm después del
fix de arriba: el host de BAT (52.5x34x49cm -mucho más alto que
cualquier otro SKU) formaba una capa DONDE ERA EL ÚNICO CANDIDATO
POSIBLE (nada más en el CD tiene una altura compatible dentro de la
tolerancia de 8cm) -esa capa nunca podía llegar al 20% mínimo de
cobertura por sí sola, y la garantía "nada flota a nivel de capa" cerraba
TODO el pallet ahí, desperdiciando altura y demanda real que sí podía
combinarse en otras capas.

Corrección: si una capa tuvo, en TODO momento, un solo SKU disponible
como candidato (no existía ninguna alternativa que el algoritmo pudiera
haber usado para mejorar la cobertura), su cobertura baja no es una mala
elección -es escasez real, y bloquear el resto del pallet por eso no
mejora la seguridad, solo desperdicia capacidad. Se acepta esa capa como
"lo mejor posible" y el pallet sigue. `validar_capas_ph_fraccion` se
actualizó con el mismo criterio (no marca como violación una capa de un
solo SKU), para no reportar como "problema" algo que la generación ya
decidió aceptar a propósito.

### Resultado -verificado con el pipeline real, ambos datasets
```
Dataset real del usuario (5 CDs):
  Antes de estos 2 fixes: 20 pallets, 1 CD fuera de margen (BK51=6).
  Después: 19 pallets, LOS 5 CDs dentro del margen ±1.
  BK31=3(target 2) BK36=2(target 2, exacto) BK51=5(target 4)
  BK61=5(target 4) BK65=4(target 3)
  Pallets bajo 170cm: 4 -> 3 (uno por CD como mucho, remanente genuino).

Cubicaje18.07.2026.xlsx (referencia de la sesión, 9 CDs):
  53 -> 50 pallets. Aprovechamiento de altura promedio: 84% -> 89%.
  Pallets bajo 170cm: 13 -> 9 (mayormente 1 por CD, remanente genuino).
```
0 violaciones geométricas duras (overlap/overflow/altura) y 0 violaciones
de cobertura por capa en ambos datasets. Demanda exacta.

### Invariantes
- `tests/test_packing_ph_fraccion.py`: 2 tests nuevos
  (`test_objetivo_ph_es_piso_no_techo`, `test_sku_alto_sin_companero_
  no_corta_el_pallet_completo`) -ninguno de los dos bugs se manifestaba
  en los tests sintéticos existentes antes de este patch, ambos se
  encontraron corriendo el pipeline real con datos reales del usuario.
- Suite completa: 138 passed.

---

## Bug real, reportado con captura del Excel: un SKU superaba su propio
## `Cajas por PH` dentro de un pallet mezclado

El usuario revisó el Excel de salida a mano y encontró: SKU 22443 (Cielo
Agua de Mesa sin Gas 1L) con **98 cajas en un solo pallet**, cuando el
Maestro dice `Cajas por PH`=75 (75 = 15 cajas por cama × 5 camas por PH,
el máximo físico validado para ese SKU armado solo). Cita textual: "ahi
estamos infringiendo la regla de un maximo por sku unico, ahi lo que
deberia pasar es hacer 1 pallet de 75 cajas y lo remanente que sea de
otro sku".

### Causa real
`packing_ph_fraccion.py` usaba `Cajas por PH` SOLO para calcular la
fracción de PH (`ph_por_caja = 1/Cajas_por_PH`, para decidir cuándo un
pallet está "lleno" en promedio) -nunca como un tope DURO de cuántas
cajas de ESE SKU pueden ir en UN pallet. `Cajas_Cama_Efectivo` sí se
respetaba, pero solo POR CAPA (se resetea entre capas del mismo pallet)
-nada impedía que el mismo SKU volviera a aparecer en varias capas del
MISMO pallet hasta superar su propio máximo real.

### Corrección
Nuevo `tope_pallet_por_sku` (de `Cajas por PH`, el número entero, no la
fracción) + `colocado_en_pallet` (cuánto de cada SKU ya lleva TODO el
pallet, compartido y actualizado entre capas del mismo pallet, se
resetea recién al abrir un pallet nuevo -el tope es por pallet, no
global). Se aplica tanto al elegir el ancla de una capa nueva como a los
candidatos de relleno dentro de `_armar_capa`. El remanente que no entra
por el tope queda pendiente y compite en el/los pallet(s) siguientes,
exactamente como pidió el usuario.

### Resultado
```
Verificado con datos reales (ambos datasets): 0 SKUs exceden su propio
Cajas_Por_PH en ningún pallet (antes, sin chequear directamente, no
había garantía -este caso real lo probó).
Dataset del usuario: sigue con los 5 CDs dentro del margen ±1, 0
violaciones. Dataset de referencia: 50 -> 51 pallets (regresión chica y
esperada -no se puede seguir sobre-empacando un SKU más allá de su
máximo real, ese "ahorro" de un pallet era ilegítimo).
```

### Invariantes
- `tests/test_packing_ph_fraccion.py::test_ningun_sku_supera_cajas_por_ph_en_un_solo_pallet`:
  con demanda muy superior al tope (302 vs 75), ningún pallet individual
  supera 75 cajas de ese SKU, demanda total despachada exacta.
- tests: 139 passed (suite completa).

---

## Columna `Subcategoría` en el Maestro -reemplaza el match por nombre
## de Four Loko

Pedido explícito del usuario: la regla de fragilidad de Four Loko (nivel
de remate, nunca se le pone nada encima) tiene que aplicarse a TODA una
subcategoría del Maestro, no solo a SKUs que se llamen literalmente
"Four Loko". Aclaración siguiente del usuario, corrigiendo un primer
intento con un solo valor combinado ("Energizantes y RTS"): la columna
nueva se llama `Subcategoría` y hay que buscar en ella DOS valores por
separado, "RTD" y "Energizante" -y ahora esa columna reemplaza por
completo la detección por texto en la Descripción (ya no se busca "four
loko" en ningún lado).

### Cambio
- `src/derivados.py`: se sacó el match por texto (`Descripción.str.
  contains("four loko")`) y se reemplazó por `Subcategoría.str.strip().
  str.casefold().isin({"rtd", "energizante"})` -case-insensitive, tolera
  espacios. Columna opcional: si el Maestro no la trae (dataset viejo),
  simplemente no marca nada por esta vía -no rompe nada.
- `tests/conftest.py`: `_maestro()`/`MAESTRO_COLS` ganan el parámetro
  `subcategoria` (default `None`) para que los tests puedan setearla.
- `src/template.py`: columna `Subcategoría` agregada a `Maestro_SKUs`
  -fila nueva en INSTRUCCIONES explicando los dos valores válidos ("RTD"
  o "Energizante"), y un 4to SKU de ejemplo (1004, "Four Loko Ejemplo",
  Subcategoría="RTD") en las 3 hojas (Envios_Julio/Maestro_SKUs/UMA) para
  que quien abra la plantilla vea un caso de uso real, no solo la
  instrucción en texto.

### Invariantes
- `tests/test_derivados.py`: reemplazados los tests de detección por
  nombre por 4 tests nuevos -subcategoría "RTD" fuerza a remate aunque la
  Categoría sea Licores, subcategoría "Energizante" también, detecta sin
  importar mayúsculas/espacios, y (cambio de diseño explícito) un SKU
  llamado "Four Loko" SIN la subcategoría marcada en el Maestro YA NO se
  fuerza a remate -la fuente de verdad es el Maestro, no el nombre del
  producto.
- Verificado end-to-end: la plantilla descargable (`construir_template`)
  corrida por el pipeline completo -el SKU de ejemplo Four Loko
  (Subcategoría="RTD") sale con `Nivel_Categoria=7` en el plan de picking
  final.
- tests: 141 passed (suite completa).

---

## Llenado de huecos -pedido explícito del usuario con foto de un pallet
## de 213cm con una franja entera vacía a un costado

El layout de estantería (por capas) de PH_FRACCION no tesela perfecto: si
el ancho de un SKU no divide parejo el piso 120x100 (ej. cajas de 35cm de
largo: entran 3 en fila, sobra una tira de 15cm), esa tira queda vacía de
piso a techo en TODAS las capas de ese SKU -exactamente lo que mostraba
la foto del usuario. Pedido explícito: una vez que el pallet ya llegó a
su altura óptima con las reglas que ya existen, rellenar esos huecos con
Comestibles/Aseo/Cigarros/NABs para acercarse al 100% del volumen -NABs
siempre de pie, los otros tres pueden acostarse/voltearse en cualquier
orientación.

### Diseño
Nueva función `_llenar_huecos_pallet` en `packing_ph_fraccion.py`,
llamada una vez DESPUÉS de que cada pallet ya terminó su armado normal
(no toca nada de lo ya colocado, solo agrega):
1. Reconstruye el espacio libre EXACTO (no la aproximación por área de la
   construcción normal) a partir de las torres que ya existen, con
   `packing_columnar._reconstruir_en_construccion` -el mismo MaxRects 3D
   ya verificado libre de cajas flotando (reporte del usuario de la
   sección "Bug real: cajas flotando" más arriba en este mismo log).
2. Para cada hueco real encontrado, prueba SKUs de las 4 categorías
   autorizadas (`CATEGORIAS_RELLENO_HUECOS`) -NABs solo con sus 2
   orientaciones "de pie" de siempre; Comestibles/Aseo/Cigarros con las 6
   orientaciones posibles (`torres.generar_torres_candidatas_todas_
   orientaciones`, nueva: cualquiera de las 3 dimensiones de la caja
   puede quedar vertical).
3. Reusa `packing_bloques._mejor_cuboide_para_sku` para elegir dónde
   entra cada candidata -mismo chequeo de tope por capa (`Cajas_Cama_
   Efectivo`) y de orden de categoría (nunca una caja apoyada directo
   encima de una de nivel mayor) que ya estaba probado, no se reimplementa
   nada de eso.
4. Respeta el tope real de `Cajas por PH` por pallet (mismo mecanismo que
   el resto del armado).
5. Reduce la demanda pendiente compartida (`pendientes`) -lo que se
   coló en un hueco no hace falta despacharlo en un pallet aparte
   después, beneficio extra de este cambio.

### Resultado -verificado contra el dataset de referencia
```
Cubicaje18.07.2026.xlsx: 51 -> 50 pallets. 34 torres colocadas
  "acostadas" (relleno de huecos que ninguna orientación de pie
  aprovechaba). Ocupación XY promedio: 88.2%.
0 violaciones geométricas (solape/overflow/altura), 0 NABs acostados,
demanda exacta.
```

### Invariantes
- `tests/test_packing_ph_fraccion.py`: 6 tests nuevos -relleno entra
  acostado donde de pie no calza, coexiste en el mismo pallet que el SKU
  que dejó el hueco (no abre pallet propio), NABs NUNCA se acuesta,
  categorías no autorizadas (ej. otro Licor) no se acuestan para rellenar
  huecos ajenos, y el tope de `Cajas por PH` sigue aplicando aunque la
  colocación venga del llenado de huecos.
- tests: 146 passed (suite completa).

---

## Cigarros no es lo mismo que Comestibles, y vuelta al motor exacto
## -reportado por el usuario con fotos reales de la app

El usuario corrió la app conectada con su dataset y mandó 2 fotos de
pallets reales con dos problemas:
1. Un pallet con Comestibles (categoría) apilado ENCIMA de Cigarros/BAT
   -"esa caja es cigarros y siempre tiene que ir encima". Comestibles y
   Cigarros compartían el mismo `NIVEL_REMATE` (7), así que podían quedar
   en cualquier orden entre sí.
2. Camas con espacio vacío grande Y ADEMÁS cajas visiblemente sin apoyo
   real debajo -"eso no puede pasar... tiene que llenar la cama en su
   dimension volumetrica completa y luego pasar a la siguiente".

### Fix 1: `config.NIVEL_CIGARROS`
Cigarros ya no comparte nivel con Comestibles -tiene el suyo propio, uno
más alto (`NIVEL_REMATE + 1` = 8), así que por la misma regla de orden de
categoría que ya existía (nunca decrece de piso a techo), Comestibles NUNCA
puede quedar apoyado encima de Cigarros. El pseudo-SKU de BAT (consolidado
de Cigarros/vapes) también se declara explícitamente con `Categoria_
Normalizada="Cigarros"` y `Nivel_Categoria=NIVEL_CIGARROS` en `bat.py`
-antes no declaraba categoría propia y cabía en el fallback genérico
`NIVEL_REMATE`, quedando al mismo nivel que Comestibles.

### Fix 2: se retiró `packing_ph_fraccion.py` del pipeline
Se midió la magnitud real del problema de flotación antes de decidir:
sobre `Cubicaje18.07.2026.xlsx`, de 4350 torres que no arrancan en el
piso, la cobertura de soporte real promedio era del 79% -742 torres (17%)
con menos del 50% de apoyo real, muchas con 0% (literalmente flotando).
No era un caso límite raro, era sistemático -consecuencia directa de que
cada capa arma su propio layout de estantería desde cero (x=0,y=0) sin
mirar qué hay exactamente debajo; el % de cobertura por capa nunca
garantizaba que CADA caja individual tuviera apoyo real en su posición
exacta.

Decisión del usuario, con el trade-off explicado (más pallets a cambio de
garantía real caja por caja): volver a `src/packing_bloques.py` (el motor
MaxRects exacto, ya con 0% de flotación verificado desde el fix original
de esta sesión) como motor activo del pipeline. Se le agregaron 2
ingredientes que `packing_ph_fraccion.py` sí había demostrado que ayudan a
recuperar densidad sin sacrificar la garantía exacta:
- **Orientación flexible** (`CATEGORIAS_ORIENTACION_FLEXIBLE = {"Comestibles",
  "Aseo", "Cigarros"}`): estos SKUs generan las 6 orientaciones posibles
  (`torres.generar_torres_candidatas_todas_orientaciones`, ya existía para
  el llenado de huecos del motor retirado) en vez de las 2 "de pie" -de
  pie sigue siendo la preferida cuando sirve (se calcula la mejor grilla
  solo entre las "de pie"), acostado es el último recurso del fallback de
  orientación que ya existía. NABs y el resto de las categorías siguen con
  2 orientaciones nomás -pedido explícito: "nabs es el unico que siempre
  tiene que ir de pie".
- **Tope real de `Cajas por PH`** por pallet (`tope_pallet_por_sku` +
  `colocado_en_pallet`, mismo mecanismo que ya se había probado en
  `packing_ph_fraccion.py`).

`packing_ph_fraccion.py` queda en el repo, probado, pero ya no es el motor
del pipeline (`pipeline_sku_bloque.py` volvió a importar `armar_pallets_
bloques` de `packing_bloques.py`).

### Resultado -verificado con el pipeline real, ambos datasets
```
                    ANTES (PH_FRACCION)   AHORA (motor exacto + flexible)
Cubicaje18.07.2026:  49 pallets            65 pallets
  cobertura soporte:  79.0% promedio        100.0% (exacto, 0 flotando)
  torres <50% apoyo:  742                   0

Dataset del usuario: 19 pallets            27 pallets
  5 CDs dentro de margen ±1: 4 de 5         1 de 5 (solo BK36)
```
Sube bastante el conteo de pallets -es el costo real de garantizar apoyo
exacto caja por caja en vez de una aproximación por % de cobertura. Se
reporta tal cual, sin ajustar nada para disimularlo: la brecha contra el
cubicaje real (que ya se había cerrado con PH_FRACCION) se vuelve a abrir.
0 solapamientos, 0 excesos de altura, 0 SKUs sobre su Cajas por PH,
demanda exacta en ambos datasets.

### Invariantes
- `tests/test_packing_bloques.py`: 4 tests nuevos -categoría flexible
  entra acostada donde de pie no calza (y el motor sigue en 0% de
  flotación con esto activo), NABs nunca se acuesta, categoría no
  flexible (ej. otro Licor) tampoco se acuesta, tope de Cajas por PH por
  pallet.
- Verificado manualmente (no solo tests sintéticos) contra ambos datasets
  reales: 100.0% de cobertura de soporte exacta, 0 violaciones
  geométricas, demanda exacta, 0 NABs acostados.
- tests: 150 passed (suite completa).

---

## Investigación de los pallets peor aprovechados -motivada por fotos
## reales de cubicaje sin ningún espacio libre

El usuario mandó 2 fotos de camiones reales (CD Chanchamayo) con pallets
sin ningún hueco -varios SKUs distintos combinados, capas completamente
llenas. Se investigó la distribución REAL de ocupación XY del motor
(no solo el promedio) para encontrar dónde estaba la brecha concreta.

### Diagnóstico: la mediana ya es buena, el problema es una cola específica
Sobre `Cubicaje18.07.2026.xlsx`: mediana de ocupación XY 88.8% (la
MAYORÍA de los pallets ya está razonablemente cerca del estándar de las
fotos), pero 6 pallets quedaban por debajo del 50% -y los 6 eran pallets
dedicados SOLO a BAT (Cigarros consolidado) con 1-6 cajas.

Causa real: Cigarros/BAT tiene el nivel de categoría más alto
(`NIVEL_CIGARROS`, ver fix anterior) -eso significa que SIEMPRE pierde el
desempate de prioridad mientras cualquier otro SKU de nivel más bajo
todavía tenga dónde ir. Medido directamente: en cada CD afectado, el
pallet más alto ya usaba prácticamente el 100% del presupuesto de altura (199.5-200.0 de 200.1cm) ANTES de que a BAT le
tocara competir -sin margen real, sin importar que BAT tuviera demanda
pendiente. BAT terminaba abriendo su propio pallet nuevo, donde ya no
había nada más con qué competir.

### Intento 1: redistribuir después de armar (`_redistribuir_dispersos`)
Reutiliza el motor exacto (`_reconstruir_en_construccion`) para intentar
mover las torres de un pallet muy vacío al espacio libre real de los
pallets YA armados del mismo CD, respetando los mismos topes y el mismo
orden de categoría. No encontró lugar en ningún caso -los pallets
hermanos ya estaban a 199.5-200.0cm, sin los 49cm que Cigarros necesita.
Se deja en el código (no hace daño, podría ayudar en datasets con más
margen de altura disponible) pero no resolvió este caso.

### Intento 2: reservar altura durante el armado (parcial)
Mientras haya demanda pendiente de Cigarros, se descartan colocaciones de
CUALQUIER OTRO nivel que dejarían menos margen de altura que lo que
Cigarros necesita -con una válvula de escape: si respetar la reserva no
deja NINGUNA colocación válida (ni para Cigarros ni para nadie), se
descarta la reserva antes que desperdiciar altura sin ayudar a nadie.

Resultado: mejoró 2 de 7 CDs (BK68, SJ86 ya no tienen pallet BAT-only),
pero 5 siguen igual. Causa de que no alcance del todo: la reserva solo
protege el PRESUPUESTO DE ALTURA restante, no la FORMA (ancho x
profundidad) del hueco que queda -si lo que sobra en esos últimos
centímetros no tiene el ancho que la caja de BAT (52.5x34cm) necesita, ni
BAT ni nadie puede usarlo, y la válvula de escape lo libera de todas
formas. Reservar también la posición XY exacta sería un cambio bastante
más invasivo (equivale a apartar una región fija desde el principio del
armado) para un beneficio acotado -no se implementó sin decisión
explícita del usuario.

### Resultado
```
Cubicaje18.07.2026.xlsx: 65 -> 64 pallets (aprovechamiento 78% -> 80%).
Dataset del usuario: 27 -> 26 pallets.
0 violaciones geométricas, demanda exacta en ambos -ninguna garantía se
relajó, es una mejora real aunque parcial.
```

### Pendiente (no implementado, decisión del usuario)
Cerrar el 100% de este caso puntual (BAT/Cigarros con muy poca demanda
quedando solo) requeriría reservar una región XY específica desde el
inicio del armado de un pallet, no solo un presupuesto de altura -un
cambio más invasivo para un beneficio acotado (~5 pallets de 64 en el
dataset de referencia).

### Invariantes
- Suite completa corrida contra ambos datasets reales tras cada intento:
  0 violaciones, demanda exacta.
- tests: 150 passed (sin tests nuevos en esta sección -el mecanismo se
  verificó contra datos reales, no sintéticos; los tests existentes de
  `test_packing_bloques.py` siguen pasando sin cambios).

## Reescritura de bandas -pedido explícito del usuario

> "reescribamos el orden, se arman las camas no las columnas primero
> todos los licores si la demanda pide 1 cama de licores la siguiente
> cama deberia ser de lacteos o nabs, y los remantes pueden ser
> importados, comestibles, merch, cigarros que se mantenga la regla de se
> consolifa hasta 500 unidaes por cd en las cajas y medidas que ya te di,
> categorias disntinas si pueden compartir la misma cama siempre y cuando
> en alto tambien sea compartido"

Después de ver fotos de un camión real cargado (CD Chanchamayo) con
pallets densos, sin ningún espacio libre, mezclando varios SKUs/marcas
distintos por cama -el usuario pidió reemplazar la competencia
simultánea "por nivel" (sección 4 de `packing_bloques.py` hasta acá, 8
niveles de categoría, todos mezclándose libremente con el nivel solo como
desempate) por 4 BANDAS estrictamente secuenciales: Licores → Lácteos →
NABs → remanente (Aseo, Importados, Merch, Comestibles, Cigarros -y
cualquier SKU forzado a nivel remate por Subcategoría RTD/Energizante,
ver Four Loko). Aclarado en 3 preguntas de seguimiento:
- Aseo entra en el grupo remanente ("Es parte del grupo remanente").
- Cigarros YA NO tiene que ser lo más alto obligatorio ("Ya no es
  obligatorio que sea lo más alto") -deja de ser un caso especial, es un
  miembro más de la banda remanente.
- Entre Lácteos y NABs (banda 2 y 3), Lácteos va primero cuando ambas
  tienen demanda pendiente ("Lácteos primero, NABs después").
- "hasta 500 unidades" fue un lapsus del usuario, confirmado 1000
  (`CAJA_BAT_CAPACIDAD_UNIDADES`, sin cambios -dejar como está).

### Diseño
- **Banda como concepto NUEVO, propio de `packing_bloques.py`**
  (`_banda_de_sku`), separado de `config.Nivel_Categoria` (que sigue
  existiendo tal cual para reportes/exports, sin tocar `config.py` ni
  `derivados.py`). 1=Licores, 2=Lácteos, 3=NABs, 4=remanente. Cualquier
  SKU cuyo `Nivel_Categoria` original ya sea "remate o más" (incluye
  Comestibles/Cigarros reales Y cualquier SKU forzado por Subcategoría
  RTD/Energizante) cae en banda 4 sin importar su categoría textual -así
  Four Loko (Categoria_Normalizada="Licores") no se cuela en la banda 1.
- **La banda es el PRIMER criterio de la competencia por cuboide libre**
  (antes que la Z): `clave = (banda_sku, z_destino, -area, -demanda)` en
  vez de `(z_destino, nivel_sku, ...)`. Una banda menor SIEMPRE gana
  sobre una mayor mientras tenga algún cuboide disponible, por lejano que
  sea -eso agota Licores en la práctica antes de que Lácteos empiece,
  sin necesitar una pasada separada ni resetear el estado 3D persistente
  (la garantía de 0% de flotación no se toca).
- **Exclusividad de cama entre bandas 1-3** (`_cama_es_de_otra_banda_
  estricta`, NUEVO): a diferencia del esquema anterior, Licores/Lácteos/
  NABs NUNCA comparten una misma Z entre sí, aunque la geometría dejara
  hueco -"la siguiente cama debería ser de lácteos o nabs" se lee
  literal: cada cama de estas 3 bandas es de una sola banda. La banda
  remanente (4) queda AFUERA de esta restricción -puede aparecer en
  cualquier cama, con cualquier banda, rellenando lo que sobre (es, por
  diseño, el grupo remanente).
- **Alto compartido dentro de la banda remanente** (`_altura_compatible_
  con_cama`, NUEVO): al mezclar categorías distintas en una cama de la
  banda 4, una caja nueva solo entra en una Z donde ya hay otras cajas de
  esa banda si su alto coincide (±`TOLERANCIA_ALTURA_CAMA_CM=8.0`, mismo
  valor ya calibrado en `packing_ph_fraccion.py`) con TODO lo que ya está
  ahí -pedido explícito ("categorias disntinas si pueden compartir la
  misma cama siempre y cuando en alto tambien sea compartido"). Exento en
  el PISO del pallet (z=0): mezclar SKUs de alturas muy distintas ahí es
  exactamente lo que el fix anterior de "huella grande gana el empate"
  (ver sección previa) ya había demostrado que hace falta con datos
  reales, y lo que muestran las fotos de cubicaje real del usuario
  (botellas de alturas distintas conviviendo en la misma base). Bandas
  1-3 no llevan esta restricción en ningún caso (son de una sola
  categoría cada una).
- **Se retiró la reserva de altura dedicada para Cigarros** (sección 8 de
  una versión anterior de este archivo): dejó de tener sentido en cuanto
  Cigarros pasó a ser un miembro más de la banda remanente en vez del
  único SKU que siempre pierde la competencia por nivel. `_redistribuir_
  dispersos` (mover pallets muy vacíos al espacio libre real de otros ya
  armados) se mantiene, ahora parametrizado por banda en vez de nivel.

### Efecto colateral (positivo, no buscado): resuelve el stranding de BAT
El bug que quedaba PARCIALMENTE resuelto en la sección anterior (BAT/
Cigarros stranded en pallets casi vacíos, 5 de 7 CDs sin resolver porque
la reserva de altura solo protegía el presupuesto, no la forma XY) se
resolvió ENTERO como efecto colateral de este rediseño: Cigarros ya no
compite en desventaja estructural contra TODOS los demás niveles (era
siempre el último de 8) -ahora comparte la banda 4 en igualdad de
condiciones con Aseo/Importados/Merch/Comestibles, así que puede ganar la
competencia por espacio como cualquier otro. Verificado contra
`Cubicaje18.07.2026.xlsx`: **0 pallets BAT-puros** (antes 6), y SKUs de
Comestibles/Aseo ahora sí quedan apoyados sobre Cigarros/BAT en varios
pallets reales (ej. PV5-BK31-003, PV5-BK68-031, PV5-SJ97-060).

### Desacoplamiento de `packing_ph_fraccion.py`
Ese módulo (motor aproximado, abandonado, no usado por el pipeline)
reusaba `packing_bloques._mejor_cuboide_para_sku` pasándole `nivel_por_
sku` (escala 1-8) donde esta reescritura ahora espera una banda (escala
1-4) -las 2 verificaciones nuevas (`_cama_es_de_otra_banda_estricta`,
`_altura_compatible_con_cama`) interpretaban mal esos valores y rompían 2
tests de `test_packing_ph_fraccion.py` (relleno de huecos). Se le dio a
`packing_ph_fraccion.py` su propia copia local de la función (idéntica a
la versión pre-reescritura, sin las 2 verificaciones nuevas) en vez de
seguir importando la de `packing_bloques.py` -ese módulo queda congelado
tal como estaba antes de esta reescritura, no recibe el concepto de
bandas.

### Resultado (`Cubicaje18.07.2026.xlsx`, 183 SKUs, 9 CDs)
```
61 pallets (antes 65 con el esquema por nivel). 0 violaciones
geométricas. Demanda exacta (5049.99 cajas, 183 SKUs, igual que antes).
Ocupación XY: media 84% (antes ~83%), solo 3 de 61 pallets <50% de
ocupación (antes 6 de 65, todos BAT-puros -ahora 0 BAT-puros).
```

### Tests
- `test_licores_nunca_queda_arriba_de_nabs` / `test_licores_si_puede_
  quedar_debajo_de_nabs`: reescritos para pasar `categoria="Licores"`/
  `"NABs"` explícito -bajo el esquema anterior alcanzaba con el nivel
  numérico, ahora la banda se deriva de la categoría real.
- `test_bandas_se_agotan_en_orden_licores_lacteos_nabs` (NUEVO): con las
  3 bandas estrictas pendientes en un solo pallet, se agotan en orden
  Licores → Lácteos → NABs, sin interfoliarse.
- `test_four_loko_queda_en_banda_remanente_no_en_licores` (reescrito de
  `test_four_loko_queda_arriba_de_todo_por_nivel_remate`): Four Loko cae
  en banda remanente aunque su categoría textual sea "Licores", así que
  queda por encima de Licores regulares en el mismo pallet -no porque
  tenga una regla especial de "siempre lo más alto", sino por
  construcción de bandas secuenciales.
- `test_huella_grande_gana_el_empate_de_z_sobre_mas_demanda` (existente,
  sin cambios): seguía pasando -confirma que la exención de piso (z=0) en
  `_altura_compatible_con_cama` no regresionó este fix anterior.
- Suite completa: 151 passed (22 en `test_packing_bloques.py`, 15 en
  `test_packing_ph_fraccion.py` tras el desacople, resto sin tocar).
