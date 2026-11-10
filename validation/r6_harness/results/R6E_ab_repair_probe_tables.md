# R6E — A/B por llamada del Repair de sondeo: tablas por repetición

Base `15ba0c7`. Salidas de `validation/r6_harness/summarize_ab.py` (5 repeticiones por bloque; orden inicial alternado). Solo agregados.

## Primeros bloques (SJ97 N=6, SJ87 N=5)

### SJ87 N=5  (5 repeticiones, 24208 llamadas por repetición)
| rep | orden inicial | ref µs/llamada | rápida µs/llamada | ahorro por llamada | ahorro (s) | ref primero: ahorro | rápida primero: ahorro | % llamadas donde la rápida gana |
|---|---|---|---|---|---|---|---|---|
| r0 | ref | 1033 | 390 | 62.2 % | 15.57 | 61.9 % | 62.6 % | 99 % |
| r2 | ref | 1031 | 388 | 62.4 % | 15.56 | 62.0 % | 62.7 % | 99 % |
| r4 | ref | 1020 | 377 | 63.0 % | 15.56 | 62.9 % | 63.2 % | 100 % |
| r1 | rápida | 1048 | 403 | 61.5 % | 15.60 | 61.4 % | 61.6 % | 99 % |
| r3 | rápida | 1031 | 385 | 62.6 % | 15.62 | 62.6 % | 62.6 % | 100 % |

Ahorro por llamada: media 62.3 %, mín. 61.5 %, máx. 63.0 %; **amplitud (máx.−mín.) 1.54 pp**; desviación estándar POBLACIONAL (pstdev, n=5) 0.51 pp. Ahorro del bloque: media 15.58 s (mín. 15.56, máx. 15.62; amplitud 0.064 s).
Efecto del orden de ejecución (promedio de las dos fases de alternancia): -0.34 pp (efecto de subconjunto par/impar: -0.19 pp).
Sobre el CPU de armado del caso (502.5 s): 3.10 %.
Ahorro por cuartil de costo de la llamada (Q1 = más baratas … Q4 = más caras), media de repeticiones: Q1 58.3 %, Q2 61.1 %, Q3 62.2 %, Q4 65.2 %

### SJ97 N=6  (5 repeticiones, 24713 llamadas por repetición)
| rep | orden inicial | ref µs/llamada | rápida µs/llamada | ahorro por llamada | ahorro (s) | ref primero: ahorro | rápida primero: ahorro | % llamadas donde la rápida gana |
|---|---|---|---|---|---|---|---|---|
| r0 | ref | 663 | 306 | 53.8 % | 8.82 | 54.0 % | 53.6 % | 99 % |
| r2 | ref | 661 | 306 | 53.7 % | 8.78 | 54.0 % | 53.5 % | 99 % |
| r4 | ref | 661 | 306 | 53.7 % | 8.77 | 53.9 % | 53.5 % | 99 % |
| r1 | rápida | 668 | 313 | 53.2 % | 8.78 | 53.0 % | 53.4 % | 99 % |
| r3 | rápida | 663 | 307 | 53.7 % | 8.81 | 53.6 % | 53.9 % | 99 % |

Ahorro por llamada: media 53.6 %, mín. 53.2 %, máx. 53.8 %; **amplitud (máx.−mín.) 0.65 pp**; desviación estándar POBLACIONAL (pstdev, n=5) 0.23 pp. Ahorro del bloque: media 8.79 s (mín. 8.77, máx. 8.82; amplitud 0.050 s).
Efecto del orden de ejecución (promedio de las dos fases de alternancia): +0.06 pp (efecto de subconjunto par/impar: +0.37 pp).
Sobre el CPU de armado del caso (337.0 s): 2.61 %.
Ahorro por cuartil de costo de la llamada (Q1 = más baratas … Q4 = más caras), media de repeticiones: Q1 53.2 %, Q2 51.2 %, Q3 50.7 %, Q4 57.2 %

## Bloques de confirmación (SJ97 N=7, SJ87 N=6)

### SJ87 N=6  (5 repeticiones, 26355 llamadas por repetición)
| rep | orden inicial | ref µs/llamada | rápida µs/llamada | ahorro por llamada | ahorro (s) | ref primero: ahorro | rápida primero: ahorro | % llamadas donde la rápida gana |
|---|---|---|---|---|---|---|---|---|
| r0 | ref | 348 | 233 | 33.2 % | 3.05 | 33.7 % | 32.7 % | 96 % |
| r2 | ref | 356 | 240 | 32.5 % | 3.05 | 33.0 % | 32.0 % | 96 % |
| r4 | ref | 367 | 252 | 31.3 % | 3.03 | 31.9 % | 30.7 % | 94 % |
| r1 | rápida | 356 | 239 | 32.9 % | 3.09 | 33.1 % | 32.6 % | 96 % |
| r3 | rápida | 361 | 248 | 31.3 % | 2.98 | 31.5 % | 31.0 % | 94 % |

Ahorro por llamada: media 32.2 %, mín. 31.3 %, máx. 33.2 %; **amplitud (máx.−mín.) 1.94 pp**; desviación estándar POBLACIONAL (pstdev, n=5) 0.80 pp. Ahorro del bloque: media 3.04 s (mín. 2.98, máx. 3.09; amplitud 0.110 s).
Efecto del orden de ejecución (promedio de las dos fases de alternancia): +0.79 pp (efecto de subconjunto par/impar: +0.29 pp).
Sobre el CPU de armado del caso (502.5 s): 0.60 %.
Ahorro por cuartil de costo de la llamada (Q1 = más baratas … Q4 = más caras), media de repeticiones: Q1 -0.4 %, Q2 2.3 %, Q3 43.8 %, Q4 44.7 %

### SJ97 N=7  (5 repeticiones, 24015 llamadas por repetición)
| rep | orden inicial | ref µs/llamada | rápida µs/llamada | ahorro por llamada | ahorro (s) | ref primero: ahorro | rápida primero: ahorro | % llamadas donde la rápida gana |
|---|---|---|---|---|---|---|---|---|
| r0 | ref | 488 | 271 | 44.5 % | 5.21 | 45.6 % | 43.3 % | 99 % |
| r2 | ref | 492 | 275 | 44.1 % | 5.22 | 45.3 % | 43.0 % | 99 % |
| r4 | ref | 501 | 287 | 42.7 % | 5.14 | 44.1 % | 41.4 % | 99 % |
| r1 | rápida | 491 | 274 | 44.3 % | 5.22 | 43.6 % | 44.9 % | 99 % |
| r3 | rápida | 491 | 275 | 44.0 % | 5.19 | 43.4 % | 44.6 % | 99 % |

Ahorro por llamada: media 43.9 %, mín. 42.7 %, máx. 44.5 %; **amplitud (máx.−mín.) 1.73 pp**; desviación estándar POBLACIONAL (pstdev, n=5) 0.61 pp. Ahorro del bloque: media 5.20 s (mín. 5.14, máx. 5.22; amplitud 0.083 s).
Efecto del orden de ejecución (promedio de las dos fases de alternancia): +0.59 pp (efecto de subconjunto par/impar: +1.84 pp).
Sobre el CPU de armado del caso (337.0 s): 1.54 %.
Ahorro por cuartil de costo de la llamada (Q1 = más baratas … Q4 = más caras), media de repeticiones: Q1 37.8 %, Q2 46.3 %, Q3 46.9 %, Q4 43.1 %
