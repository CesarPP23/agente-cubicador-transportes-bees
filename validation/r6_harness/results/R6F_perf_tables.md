# R6-F — rendimiento antes/después (salida de `summarize_perf.py`; base R6-D `15ba0c7`, un proceso por árbol y repetición, orden alternado, sin otra carga)


### SJ97  (repeticiones: 3; orden: r1: antes→después, r2: después→antes, r3: antes→después)
| rep | árbol | CPU de armado (s) | Repair N6 (s) | Repair N7 (s) | `_candidatos_lote` en Repair (s) | pico RSS (MB) |
|---|---|---|---|---|---|---|
| 1 | before | 340.8 | 18.1 | 13.7 | 27.6 | 1676.2 |
| 1 | after | 335.7 | 10.0 | 9.0 | 14.4 | 1677.7 |
| 2 | before | 347.8 | 18.1 | 14.0 | 27.9 | 1676.5 |
| 2 | after | 332.4 | 9.6 | 8.8 | 14.0 | 1676.6 |
| 3 | before | 345.1 | 18.5 | 14.1 | 28.2 | 1676.1 |
| 3 | after | 323.9 | 9.5 | 8.6 | 13.9 | 1677.0 |

Media CPU de armado: antes 344.5 s → después 330.7 s (**+13.9 s**, -4.0 %); por repetición: r1: 5.1 s, r2: 15.4 s, r3: 21.1 s
  probe/N6/repair: 18.2 → 9.7 s (+8.5 s, -46.9 %)
  probe/N7/repair: 13.9 → 8.8 s (+5.1 s, -36.7 %)
  Ahorro total de Repair de sondeo (suma de N): 13.7 s
  Pico RSS medio: 1676.3 → 1677.1 MB

### SJ87  (repeticiones: 3; orden: r1: antes→después, r2: después→antes, r3: antes→después)
| rep | árbol | CPU de armado (s) | Repair N5 (s) | Repair N6 (s) | `_candidatos_lote` en Repair (s) | pico RSS (MB) |
|---|---|---|---|---|---|---|
| 1 | before | 508.4 | 31.3 | 13.4 | 35.5 | 1712.9 |
| 1 | after | 485.3 | 14.8 | 10.3 | 15.8 | 1713.0 |
| 2 | before | 510.8 | 30.7 | 13.4 | 35.1 | 1713.6 |
| 2 | after | 488.8 | 15.1 | 10.8 | 16.4 | 1712.9 |
| 3 | before | 501.5 | 30.4 | 13.0 | 34.6 | 1712.5 |
| 3 | after | 483.8 | 14.2 | 10.0 | 15.2 | 1712.8 |

Media CPU de armado: antes 506.9 s → después 486.0 s (**+21.0 s**, -4.1 %); por repetición: r1: 23.1 s, r2: 22.1 s, r3: 17.7 s
  probe/N5/repair: 30.8 → 14.7 s (+16.1 s, -52.3 %)
  probe/N6/repair: 13.2 → 10.4 s (+2.8 s, -21.5 %)
  Ahorro total de Repair de sondeo (suma de N): 19.0 s
  Pico RSS medio: 1713.0 → 1712.9 MB

### BK68  (repeticiones: 2; orden: r1: antes→después, r2: después→antes)
| rep | árbol | CPU de armado (s) |  | `_candidatos_lote` en Repair (s) | pico RSS (MB) |
|---|---|---|---|---|
| 1 | before | 4.5 |  | 0.0 | 189.5 |
| 1 | after | 4.5 |  | 0.0 | 189.5 |
| 2 | before | 4.5 |  | 0.0 | 190.1 |
| 2 | after | 4.5 |  | 0.0 | 190.2 |

Media CPU de armado: antes 4.5 s → después 4.5 s (**-0.0 s**, +0.9 %); por repetición: r1: -0.0 s, r2: -0.1 s
  Ahorro total de Repair de sondeo (suma de N): 0.0 s
  Pico RSS medio: 189.8 → 189.8 MB

### BK46  (repeticiones: 2; orden: r1: antes→después, r2: después→antes)
| rep | árbol | CPU de armado (s) |  | `_candidatos_lote` en Repair (s) | pico RSS (MB) |
|---|---|---|---|---|
| 1 | before | 29.1 |  | 0.0 | 142.0 |
| 1 | after | 29.7 |  | 0.0 | 142.5 |
| 2 | before | 29.0 |  | 0.0 | 142.0 |
| 2 | after | 30.2 |  | 0.0 | 142.6 |

Media CPU de armado: antes 29.1 s → después 29.9 s (**-0.8 s**, +2.9 %); por repetición: r1: -0.5 s, r2: -1.1 s
  Ahorro total de Repair de sondeo (suma de N): 0.0 s
  Pico RSS medio: 142.0 → 142.6 MB
