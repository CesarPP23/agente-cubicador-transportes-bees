# Ejemplo de referencia: BK31 armado a mano (target de éxito)

Este pallet se armó caja por caja, a mano, en una sesión de chat completa
-**no lo generó el motor**. Sirve como prueba de que la demanda real de
BK31 (`Plantilla_Ejemplo_Agente_Cubicador (1) (3).xlsx`, CD Cañete,
`Pallets_Objetivo=1`) SÍ entra completa (98/98 cajas) en un solo pallet, y
como referencia de qué decisiones de armado hicieron falta para lograrlo
-el motor real, hoy, llega a 87/98 (ver `../PATCH_LOG.md`, sección "Grandes
primero"). El diseño propuesto para cerrar esa brecha está en
`../DISENO_STRIP_PACKING_GRANDES.md`.

## Archivos

- `armado_manual_bk31.py`: reconstrucción exacta, caja por caja
  (coordenadas x/y/z reales) de todo el pallet. Correrlo regenera las 6
  vistas en `/tmp/`.
- `bk31_estado_isometrica.png`, `bk31_estado_top_completo.png`,
  `bk31_estado_frontal.png`: capturas del estado final (98/98).

## Demanda completa (12 SKUs, 98 cajas -sin contar Cigarros)

| SKU | Producto | Cajas | Dimensiones (LxAxAlto) |
|---|---|---|---|
| 15506 | Vino Borgoña | 57 | 24x31x30.5 |
| 23486 | Altomayo Café | 6 | 25.7x26x17 |
| 22713 | KR Gaseosa Naranja | 4 | 17x28.5x21.5 |
| 20233 | AM Café | 3 | 35x27x13 |
| 22712 | KR Gaseosa Limón | 2 | 17x28.5x21.5 |
| 22354 | Molitalia Sémola | 4 | 47x13x10 |
| 22726 | Vodka Russkaya | 1 | 23.2x31.1x30.2 |
| 22715 | Gaseosa Oro | 5 | 28.5x17x21.5 |
| 22176 | Pringles | 5 | 29x22.5x13 |
| 19685 | Picaras Mini | 5 | 39x30x28.5 |
| 21191 | Picaras Extremas | 4 | 39x30x28.5 |
| 21850 | Picaras Fresa | 2 | 39x30x28.5 |

(Pall Mall Boost/Sunrise, 0.1 cajas teóricas cada uno, van a la caja de
consolidación de Cigarros aparte -ver `src/bat.py`- nunca entran al
cubicaje, así que no están en este ejemplo.)

## Decisiones de armado clave (por qué el motor automático no llega solo)

1. **Camas 1-4 (Z: 0-122cm)**: Vino en grilla regular 4x3 (base) + fila de
   3 rotados (relleno de los 8cm que sobran de ancho), repetida 4 veces
   -ocupa casi toda la huella del pallet. En la última cama (Z=91.5) se
   libera espacio atrás para Vodka + 3 columnas de KR (2 Naranja + 1
   Limón, cada una 2 cajas apiladas).
2. **Picaras (Mini/Extremas/Fresa), Z=122-179cm**: se les reservó el
   bloque grande x:61-100 y:0-90 ANTES de decidir el resto -3 carriles de
   30cm de fondo cada uno, apilados 2 capas (cama5+cama6). Es la decisión
   más importante: si Picaras no reserva ESTE espacio primero, los SKUs
   chicos lo fragmentan y ya no entra (exactamente el bug que el motor
   automático no resuelve todavía).
3. **Gaseosa Oro, Z=122-143.5cm**: franja propia x:32.5-61, corrida
   lo justo para dejar sitio a Picaras a la derecha.
4. **Altomayo, Z=122-190cm**: 4 cajas apiladas sobre el Vino (footprint
   25.7cm sobre una base de 24cm -1.7cm de sobresaliente aceptado, sobre
   aire libre, nunca sobre otra caja) + 2 más giradas (alto como base)
   sobre el resto libre de la repisa de KR.
5. **AM Café, Z=134.5-173.5cm**: apoyada directo sobre la repisa de KR
   (mismo piso que alcanza Altomayo del otro lado).
6. **Fresa (última unidad), Z=143.5-173.5cm**: acostada -su Alto (28.5cm)
   calza EXACTO como base en la franja libre sobre la Gaseosa Oro, corrida
   al fondo hasta chocar con el límite real de soporte (AM Café empieza a
   Z=134.5, invade el rango de altura de la Fresa más allá de y=88).
7. **Pringles (5), Z=143.5-201.5cm**: acostadas (Alto x Ancho como base,
   Largo parado) en grid 2x2 delante de la Fresa -la 5ta apilada sobre una
   de las 4 (mismo SKU, no relleno mixto).
8. **Molitalia (4), Z=121.7-168.7cm**: el Largo (47cm) no entra acostado
   en ningún lado libre -se pararon sobre su base chica (10x13), Largo
   como altura, en grid 2x2 sobre el espacio libre del Vodka (23.2x31).

**Patrón que se repite y que el algoritmo automático todavía no reproduce:**
los SKUs de mayor volumen (Picaras, Vino) reciben su territorio ANTES de
decidir el resto, considerando a ambos a la vez -no una cola secuencial
donde el primero en llegar le quita espacio al que sigue. Ver
`../DISENO_STRIP_PACKING_GRANDES.md` para el diseño que intenta reproducir
esto con un algoritmo de reparto de área conjunto (treemap/strip-packing).
