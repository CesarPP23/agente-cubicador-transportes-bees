# Documentación lógica — Agente Cubicador V3

**Repo:** `agente-cubicador-transportes-bees`  
**Versión lógica propuesta:** `v3`  
**Base:** revisión crítica de `DOCUMENTACION_LOGICA.md`, `DOCUMENTACION_TECNICA.md`, benchmark operacional de `Cubicado Real` y reglas físicas validadas por operación.

---

## 0. Principio rector de V3

El motor no debe “optimizar” sacrificando realidad física u operacional.

La prioridad es:

1. Cumplir exactamente la demanda oficial.
2. Respetar las restricciones físicas y operativas.
3. Reproducir razonablemente cómo se cubica en operación real.
4. Minimizar pallets.
5. Minimizar pallets bajos/residuales.
6. Maximizar utilización de altura y base.
7. Mantener trazabilidad de todas las excepciones y datos inferidos.

### Regla central de datos

**El Maestro define la capacidad operacional declarada (`Cajas por cama`). UMA valida la geometría.**

Si UMA contradice una capacidad operacional conocida y físicamente utilizada, el sistema no debe reducir automáticamente `Cajas por cama`. Debe:

- marcar la inconsistencia;
- intentar validar las dos orientaciones XY;
- mantener el alto;
- inferir un `Largo/Ancho efectivo` compatible con el Maestro;
- dejar trazabilidad de que la geometría fue inferida.

---

# 1. Qué problema resuelve

Dada la demanda por Centro de Distribución (CD), construir un plan de picking que use la menor cantidad **razonable** de pallets, sujeto a reglas físicas y operativas.

El motor debe:

1. Trabajar sobre pallet EAN de **120 × 100 cm**.
2. Mantener la caja en posición natural: solo se permite giro de **90° sobre el eje vertical (XY)**.
3. Mantener el **alto físico del SKU fijo**.
4. Buscar alturas finales cercanas al comportamiento real de operación.
5. Respetar estabilidad, secuencia de categorías y reglas BAT.
6. No mezclar CDs.
7. No perder ni inventar demanda en silencio.
8. Identificar cualquier dato inferido o no validable.

---

# 2. Benchmark operacional real

El benchmark operativo disponible es la hoja `Cubicado Real`.

## 2.1 Pallets físicos

- **42 pallets físicos reales**, excluyendo registros con `PALLET = 0`.
- Los registros con `PALLET = 0` corresponden a cigarros/vapes pendientes de consolidación BAT.
- La categoría BAT se consolida después de haber armado los demás pallets.

## 2.2 Alturas observadas

- **Promedio real:** 198.3 cm
- **Mínimo real:** 170 cm
- **Máximo real:** 215 cm

Estos valores son benchmark, no necesariamente límites normativos.

### Interpretación

- El objetivo de altura **195–200 cm** queda bien respaldado por la operación.
- Un pallet bajo 185 cm puede existir físicamente; debe marcarse como parcial, no necesariamente descartarse.
- El valor de 210 cm no debe llamarse “techo físico absoluto” mientras exista evidencia real de pallets de 215 cm.
- Debe distinguirse entre:
  - objetivo operativo,
  - alerta,
  - máximo observado,
  - límite normativo validado.

---

# 3. Vocabulario

| Término | Significado |
|---|---|
| **CD** | Centro de Distribución destino |
| **Cama** | Una capa horizontal de cajas |
| **Cama pura** | Cama de un solo SKU |
| **Cama mixta** | Cama con más de un SKU |
| **Cama portante** | Puede recibir otra cama encima |
| **Cama terminal** | Última cama; nada se apoya encima |
| **PH** | Pallet homogéneo |
| **BAT** | Cigarros/vapes sujetos a consolidación especial |
| **Caja BAT** | Caja física de consolidación de 45 × 24 × 55 cm y hasta 500 unidades |
| **Host BAT** | Pallet que recibe una caja BAT en la cima |
| **Footprint** | Huella horizontal Largo × Ancho de una caja |
| **Geometría UMA** | Largo/Ancho/Alto provenientes de UMA |
| **Geometría efectiva** | Geometría que utiliza el cubicador después de validación/inferencia |
| **Techo de densidad** | Máximo operacional de cajas por cama según Maestro |

---

# 4. Fuentes de datos y jerarquía

## 4.1 Demanda

Fuente de verdad de cantidades:

- CD
- SKU
- Descripción
- Cajas teóricas / unidades

La conciliación final debe ser a nivel de **unidades**, para evitar sobre-despacho silencioso por redondeos.

## 4.2 Maestro SKU

Fuente de verdad operacional para:

- Categoría
- Unidades por caja
- Cajas por cama
- Camas por PH
- Cajas por PH

### Regla

`Cajas por cama` válida del Maestro **no se reduce automáticamente** porque UMA calcule una menor capacidad geométrica.

## 4.3 UMA

Fuente para:

- Largo
- Ancho
- Alto
- Peso

UMA es una fuente geométrica que debe ser validada antes de usarse como restricción.

---

# 5. Reconciliación geométrica Maestro ↔ UMA

Este es un nuevo paso obligatorio de V3.

Para cada SKU con `Cajas por cama = N`:

## 5.1 Orientaciones permitidas

Solo:

- Orientación A: `Largo × Ancho × Alto`
- Orientación B: `Ancho × Largo × Alto`

No se permite que Alto pase a ser Largo o Ancho.

## 5.2 Capacidad geométrica simple

Para cada orientación:

`floor(120 / dimensión_X) × floor(100 / dimensión_Y)`

Se toma la mejor de las dos orientaciones únicas.

## 5.3 Estados geométricos

### A. `UMA_VALIDADA`

La capacidad UMA permite exactamente o al menos la capacidad operacional y no existe señal de inconsistencia relevante.

### B. `UMA_SOBRECAPACIDAD`

UMA permite más cajas que el Maestro.

Interpretación:

- UMA puede estar correcta.
- Maestro sigue siendo el techo operacional.
- No aumentar automáticamente la densidad.

### C. `INFERIDA_MAESTRO`

UMA permite menos cajas que el Maestro.

Interpretación:

- hay una inconsistencia entre datos;
- se mantiene `Cajas por cama` del Maestro;
- se busca una huella efectiva compatible con N cajas;
- el alto permanece fijo;
- se elige la solución que requiera el menor cambio posible respecto a UMA y use una sola orientación.

### D. `DATO_INSUFICIENTE`

No existe información suficiente para validar ni inferir de forma razonable.

El SKU debe quedar marcado para revisión.

## 5.4 Campos recomendados

- `Largo_UMA`
- `Ancho_UMA`
- `Alto_UMA`
- `Largo_Efectivo`
- `Ancho_Efectivo`
- `Alto_Efectivo`
- `Capacidad_Geometrica_UMA`
- `Cajas_Cama_Maestro`
- `Fuente_Geometria`
- `Delta_Largo`
- `Delta_Ancho`
- `Requiere_Revision_Geometria`

---

# 6. Altura

## 6.1 Altura del pallet vacío

Operativamente puede redondearse a **15 cm** salvo que se decida mantener la medida exacta de 14.92 cm.

La fórmula debe ser única en todo el sistema:

`Altura_Final = Altura_Pallet + suma(Altura_Cama)`

Nunca debe calcularse un PH solo como:

`Camas × Alto_Caja`

sin sumar la tarima.

## 6.2 Zonas de altura propuestas

| Rango | Estado |
|---|---|
| 195–200 cm | ÓPTIMO |
| 190–195 cm | NOMINAL |
| 185–190 cm | TOLERADO |
| 170–185 cm | PARCIAL OPERATIVO |
| <170 cm | RESIDUAL / REVISAR |
| 200–210 cm | ALTO PERO OPERATIVO |
| 210–215 cm | EXCEPCIÓN / VALIDAR |
| >215 cm | NO PERMITIDO hasta validación adicional |

### Importante

El máximo real observado de 215 cm **no convierte automáticamente 215 en límite normativo**.

Hasta tener validación formal, V3 debe separar:

- `ALTURA_OBJETIVO`
- `ALTURA_ALERTA`
- `ALTURA_MAX_OBSERVADA`
- `ALTURA_HARD_VALIDADA`

---

# 7. Peso

Los valores de peso deben clasificarse por evidencia.

## 7.1 Reglas actuales a revisar

Los antiguos:

- 1,400 kg alerta
- 1,430 kg bloqueo

no deben considerarse validados solo porque funcionen mejor en el modelo.

Debe confirmarse con:

- capacidad del pallet;
- montacarga;
- rack/infrastructura;
- política SST;
- límite de transporte.

## 7.2 Diseño recomendado

- `PESO_ALERTA_KG`
- `PESO_HARD_KG`

`PESO_HARD_KG` solo debe bloquear si existe evidencia operacional/formal.

## 7.3 Contrato del peso UMA

Eliminar la ambigüedad de un booleano global como única defensa.

Idealmente almacenar:

- `Peso_Valor`
- `Tipo_Peso = CAJA | UNIDAD`

Y derivar:

- si `CAJA`: `Peso_Caja = Peso_Valor`
- si `UNIDAD`: `Peso_Caja = Peso_Valor × Unidades_Caja`

---

# 8. Orden y estabilidad

Se mantiene la idea de ordenar de pesado/resistente a liviano/frágil, pero V3 debe evitar depender únicamente de una escala ordinal.

## 8.1 Recomendación

Sustituir progresivamente `MAX_SEPARACION_NIVELES` por una **matriz explícita de compatibilidad** para apilado y otra para mezcla en cama.

Esto refleja mejor reglas físicas reales que “distancia de nivel ≤ 2”.

---

# 9. Camas puras y mixtas

## 9.1 No asumir que “puras primero” es globalmente óptimo

La lógica actual extrae todas las camas puras posibles antes de mezclar remanentes.

Esto puede ser una buena heurística, pero debe tratarse como hipótesis, no como verdad.

V3 debería comparar al menos:

- `PURE_FIRST`
- `GLOBAL_MIX`
- `HYBRID_LOOKAHEAD`

contra el benchmark de 42 pallets.

## 9.2 Cama portante vs cama terminal

Una tolerancia única de ±8 cm entre alturas no es suficiente.

### Cama portante

Debe dejar una superficie razonablemente nivelada para soportar otra cama.

### Cama terminal

Puede tolerar una diferencia de altura mayor porque nada se coloca encima.

Por tanto:

- `TOLERANCIA_ALTURA_PORTANTE`
- `TOLERANCIA_ALTURA_TERMINAL`

deben ser parámetros separados.

---

# 10. Soporte

Eliminar `FILL_RATIO_MIN_SOPORTE = 0` como equivalente a “seguro”.

El hecho de que 0% produzca un resultado más parecido al número de pallets reales no valida estabilidad física.

## 10.1 Nueva métrica

Para una caja superior:

`Support Ratio = Área de su base soportada / Área total de su base`

Los `Placement(x, y, w, d)` permiten calcular esta intersección.

## 10.2 Uso recomendado

Inicialmente:

- KPI/alerta;
- no necesariamente bloqueo.

Después de validar con operación, puede convertirse en restricción.

---

# 11. BAT — cigarros y vapes

Esta regla queda validada.

## 11.1 Caja de consolidación

- Largo: **45 cm**
- Ancho: **24 cm**
- Alto: **55 cm**
- Capacidad: **500 unidades**
- Contenido: cigarros + vapes del mismo CD

## 11.2 Secuencia operacional

1. Separar BAT de la demanda normal.
2. Cubicar todos los SKUs no BAT.
3. Consolidar BAT por CD en unidades.
4. Calcular:

`N_Cajas_BAT = ceil(Unidades_BAT_CD / 500)`

5. Esperar a que todos los pallets normales estén armados.
6. Seleccionar `N_Cajas_BAT` pallets host del mismo CD.
7. Colocar una caja BAT como remate en cada host.
8. Recalcular altura y peso final.

## 11.3 `PALLET = 0`

En `Cubicado Real`, `PALLET = 0` significa:

**pendiente de consolidación BAT**, no un pallet físico adicional.

El benchmark real sigue siendo **42 pallets**.

## 11.4 Eliminar reserva global de 55 cm

La regla anterior:

> “si el CD tiene BAT pendiente, restar 55 cm a todos los pallets”

no reproduce la operación real.

Debe reemplazarse por **host BAT dinámico**.

## 11.5 Selección del host BAT

Para cada caja BAT, elegir un pallet del mismo CD que minimice una función como:

`|Altura_Actual + 55 - Altura_Target|`

sujeto a compatibilidad y límites.

Con target cercano a 198.3 cm, pallets de aproximadamente 140–160 cm antes de BAT pueden ser hosts excelentes.

---

# 12. Función objetivo V3

La optimización debe ser lexicográfica:

1. **Demanda exacta**
2. **Restricciones físicas**
3. **Compatibilidad/estabilidad**
4. **Minimizar cantidad de pallets**
5. **Minimizar pallets residuales**
6. **Acercar altura final a ~198.3 cm**
7. **Maximizar utilización de base**
8. **Reducir complejidad de picking**
9. **Minimizar uso de geometrías inferidas**

No afirmar “mínimo matemático” mientras se utilice una heurística.

Usar:

> “minimiza heurísticamente el número de pallets”

hasta incorporar un solver exacto/MI(L)P/CP-SAT.

---

# 13. Benchmark y calibración

Toda corrida de benchmark debe registrar:

- dataset;
- fecha;
- hash del archivo;
- commit;
- configuración;
- cantidad de pallets;
- pallets parciales;
- altura media;
- altura mínima;
- altura máxima;
- peso medio/máximo;
- demanda reconciliada;
- geometrías inferidas.

## Benchmark principal actual

- Pallets reales: **42**
- Altura promedio: **198.3 cm**
- Mínimo: **170 cm**
- Máximo: **215 cm**

El objetivo de V3 no es solo “bajar de 64”.

Es:

> **reproducir razonablemente los 42 pallets reales, explicar por qué cada pallet es físicamente posible y después buscar mejoras adicionales.**

---

# 14. Diagnóstico de la brecha 64 vs 42

No asumir una causa única.

Prioridad de investigación:

1. **Geometría Maestro vs UMA**
2. **Reserva global BAT de 55 cm**
3. **Formación de camas mixtas**
4. **Estrategia pure-first**
5. **Restricciones categóricas**
6. **Peso**
7. **Asignación best-fit**

Cada pallet real debería poder someterse a una auditoría:

- ¿lo bloquea geometría?
- ¿peso?
- ¿compatibilidad?
- ¿altura?
- ¿BAT?
- ¿mezcla?
- ¿restricción artificial?

---

# 15. Invariantes V3

1. Nunca mezclar CDs.
2. Nunca perder demanda en silencio.
3. Conciliar demanda a nivel unidades.
4. Nunca inventar unidades sin una regla explícita.
5. Ninguna caja sobresale de 120 × 100.
6. Ninguna caja se solapa con otra.
7. Solo rotación XY.
8. El alto físico del SKU nunca cambia.
9. `Cajas por cama` válida del Maestro sigue siendo capacidad operacional.
10. Si UMA contradice Maestro, se activa validación/inferencia.
11. Toda geometría inferida queda identificada.
12. Altura final siempre = pallet + suma de camas/remates.
13. BAT se consolida por CD en cajas de máximo 500 unidades.
14. `PALLET = 0` BAT no cuenta como pallet físico.
15. BAT siempre va al final.
16. Ninguna cama irregular soporta otra sin una regla explícita de soporte.
17. Todo pallet inviable queda como `REQUIERE REVISIÓN`.
18. Mismo input + misma configuración = mismo output.

---

# 16. Estados recomendados

- `OK`
- `ÓPTIMO`
- `TOLERADO`
- `⚠ PALLET PARCIAL`
- `⚠ ALTURA EXCEPCIONAL`
- `⚠ ALERTA DE PESO`
- `⚠ PESO NO VALIDABLE`
- `⚠ GEOMETRÍA INFERIDA`
- `⚠ GEOMETRÍA INCONSISTENTE`
- `⚠ CATEGORÍA NO CLASIFICADA`
- `⚠ SOPORTE BAJO`
- `⚠ DATO INSUFICIENTE`
- `⚠ REQUIERE REVISIÓN`

Los estados pueden acumularse.

---

# 17. Parámetros V3 — estado de validación

| Parámetro | Valor actual/propuesto | Estado |
|---|---:|---|
| Pallet | 120 × 100 cm | Validado |
| Alto pallet | 15 cm aprox. | Validar precisión final |
| Target altura | 198.3 cm aprox. | Respaldado por benchmark |
| Zona óptima | 195–200 cm | Respaldada |
| Mínimo nominal | 190 cm | Mantener |
| Parcial operativo | 170–185 cm | Respaldado por benchmark |
| Máximo observado | 215 cm | Observado, no necesariamente normativo |
| Peso alerta | Por validar | No congelar |
| Peso hard | Por validar | No congelar |
| Tolerancia mezcla portante | Por calibrar | Pendiente |
| Tolerancia mezcla terminal | Por calibrar | Pendiente |
| Reserva BAT global | 0 cm | Eliminar |
| Caja BAT | 45 × 24 × 55 cm | Validada |
| Capacidad BAT | 500 unidades | Validada |
| Rotación acostada | Desactivada | Mantener fuera de producción |
| Rotación XY | Habilitada | Validada |

---

# 18. Roadmap de desarrollo recomendado

## V3.1 — Verdad física

- Reconciliar Maestro vs UMA.
- Crear geometría efectiva.
- Mantener alto fijo.
- Eliminar rotaciones acostadas del flujo productivo.

## V3.2 — BAT correcto

- Separar BAT.
- Eliminar reserva global de 55.
- Generar cajas BAT por 500 unidades.
- Seleccionar hosts dinámicamente.

## V3.3 — Camas y soporte

- Portante vs terminal.
- Support Ratio.
- Revisión de ±8 cm.

## V3.4 — Heurística global

- Benchmark pure-first vs híbrida.
- Reducir residuales.
- Optimizar respecto a los 42 pallets reales.

## V3.5 — Validación operativa

- Reproducir pallets reales.
- Explicar divergencias.
- Aceptación de Picking/Transporte.
- Recién después intentar superar el benchmark humano.

---

# 19. Criterio de éxito V3

V3 no se considera exitosa solamente porque produzca menos pallets.

Debe demostrar simultáneamente:

- demanda conciliada;
- geometría explicable;
- reglas BAT correctas;
- estabilidad razonable;
- alturas comparables a operación;
- número de pallets cercano al benchmark real;
- trazabilidad total de inferencias y excepciones.

**Meta de calibración inicial:** aproximarse a **42 pallets** con altura media alrededor de **198 cm**, sin violaciones físicas no explicadas.
