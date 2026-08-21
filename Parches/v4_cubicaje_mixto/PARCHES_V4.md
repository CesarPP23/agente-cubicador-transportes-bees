# Parches V4 — Cubicaje mixto y confirmación geométrica

**Repo:** `agente-cubicador-transportes-bees`
**Estado del código al escribir esto:** V3 (con `bat.py`, `reconciliacion_geometrica.py`, `soporte.py`, `demanda.py`, `benchmark.py`)
**Para:** Claude Code, a aplicar directo sobre el repo.

Nada de lo que está acá está en el código todavía. Los archivos `.py` de esta carpeta ya están escritos y probados — no hay que reimplementarlos, hay que integrarlos.

---

## Contexto: qué se hizo y qué se encontró

Se validó geométricamente la columna `caja/cama` del Maestro contra 458 SKUs, probando **todas** las disposiciones posibles con la caja siempre parada (gira solo sobre su propio eje): grillas uniformes, patrones mixtos por cortes rectos recursivos, y patrones tipo molinete no guillotinables.

Con el criterio de negocio confirmado por Omar (**se acepta que la caja sobresalga hasta 2,5 cm por lado**, área efectiva 125 × 105 cm):

| Veredicto | SKUs |
|---|---|
| Confirmado sin sobresalir | 234 |
| Cabe más de lo declarado | 143 |
| Confirmado con sobresaliente | 49 |
| Imposible — excede el área | 24 |
| No alcanza | 8 |

**426 de 458 (93%) del dato del operario es geométricamente alcanzable.** El entregable completo está en `Confirmacion_Geometrica_Cajas_por_Cama.xlsx` (raíz del workspace).

### Hallazgo estructural que condiciona todo lo demás

El motor hoy da **56 pallets** contra el benchmark real de **42**. Se midió de dónde viene la diferencia y **no es de las reglas de categoría ni de las restricciones de apilado**:

| Escenario probado | Pallets |
|---|---|
| Base | 56 |
| NABs puede mezclar en cama | 56 |
| Comestibles puede mezclar en cama | 56 |
| Ambos pueden mezclar | 56 |
| `MAX_SEPARACION_NIVELES = 6` (mezcla libre) | 56 |
| Peso a 2.000 kg | 56 |
| Altura tope a 230 cm | 54 |
| Todo relajado a la vez | 53 |

La razón es aritmética: el motor genera **272 camas que suman 9.621 cm** de altura, y cada pallet admite 200 cm útiles → **piso teórico de 48 pallets**. Para llegar a 42 harían falta 229 cm de cama por pallet y solo caben 200.

**Conclusión: el exceso está en la generación de camas (Paso 3), no en el apilado (Paso 4).** 53 de las 272 camas (19%) cubren menos de la mitad de la base; 32 de ellas tienen un solo SKU con mediana de 4 cajas. Mayormente Licores (22) y Comestibles (18).

> ⚠️ **Antes de optimizar contra 42, verificar que el benchmark sea comparable.** No se pudo confirmar que los 42 pallets reales correspondan a la misma demanda del `Envios_Julio` actual — el archivo `Plan de acción 10.08 - CUBICADO.xlsx` no está en el workspace. Si es otro despacho, la meta de 42 es incorrecta y el piso de 48 no es un problema sino el resultado correcto.

---

## P1 — Cubicaje mixto en el cálculo de capacidad geométrica

**Severidad: media-alta. Es el único de los tres parches que cambia el resultado del motor.**

### El problema

`src/reconciliacion_geometrica.py::capacidad_xy_max` calcula la capacidad probando solo **dos grillas uniformes** (toda la cama en orientación A, o toda en B) y quedándose con la mejor:

```python
def capacidad_xy_max(largo: float, ancho: float) -> tuple[int, str]:
    cap_a = capacidad_orientacion_unica(config.PALLET_LARGO, config.PALLET_ANCHO, largo, ancho)
    cap_b = capacidad_orientacion_unica(config.PALLET_LARGO, config.PALLET_ANCHO, ancho, largo)
    if cap_a >= cap_b:
        return cap_a, "A"
    return cap_b, "B"
```

Eso deja fuera los patrones **mixtos**, donde una parte de la cama va en una orientación y otra parte en la otra. No es un caso raro: la operación los usa habitualmente (ver la foto del SKU 16522 que mandó Omar).

Ejemplo verificable a mano — caja de 40 × 30 cm en un pallet de 120 × 100:

- Grilla A (40 de ancho): 3 × 3 = **9 cajas**
- Grilla B (30 de ancho): 4 × 2 = **8 cajas**
- Mixto: franja de 120×60 con 6 cajas horizontales + franja de 120×40 con 4 verticales = **10 cajas**, y llena el pallet al 100% exacto (10 × 1.200 cm² = 12.000 cm²).

El código actual devuelve 9. El óptimo es 10.

### Impacto medido sobre la demanda real

| Métrica | Valor |
|---|---|
| SKUs de la demanda donde el patrón mixto supera a la grilla | 108 de 183 |
| Ganancia media en esos SKUs | +1,5 cajas por cama |
| SKUs donde la capacidad **efectiva** sube (ya acotada por el Maestro) | 74 |
| Reducción estimada de camas | ~12 (3%) |

La ganancia es real pero moderada, porque `Cajas_Cama_Efectivo` está acotado por el dato del Maestro: la geometría solo manda cuando es más restrictiva que el Maestro. Aun así corrige un sesgo sistemático a la baja en el fallback geométrico.

### El fix

Los archivos ya están en esta carpeta:

- **`solver.py`** — `max_cajas(W, H, largo, ancho, con_pinwheel=True) -> (n, metodo)`. Devuelve el máximo de cajas y qué familia de patrón lo logró.
- **`layout.py`** — `resolver(W, H, largo, ancho) -> (n, bloques)` y `describir(bloques)`. Igual que el anterior pero reconstruye el patrón concreto (posiciones, orientación por bloque), para poder mostrárselo al operario.
- **`exacto.py`** — `max_exacto(W, H, dims_huella)`. Búsqueda **exhaustiva** por posiciones canónicas. Es lenta (segundos por SKU) y no va en el pipeline: sirve para auditar casos puntuales y verificar que la heurística no se queda corta.

**Integración sugerida en `reconciliacion_geometrica.py`:**

```python
from Parches.v4_cubicaje_mixto.solver import max_cajas   # mover el archivo a src/ al aplicar

def capacidad_xy_max(largo: float, ancho: float) -> tuple[int, str]:
    """Máxima capacidad de la cama probando TODAS las disposiciones con la caja
    de pie: grillas uniformes, patrones mixtos por cortes rectos recursivos, y
    molinete. Antes solo probaba las dos grillas uniformes, lo que subestimaba
    la capacidad en 108 de los 183 SKUs de la demanda real."""
    cap_a = capacidad_orientacion_unica(config.PALLET_LARGO, config.PALLET_ANCHO, largo, ancho)
    cap_b = capacidad_orientacion_unica(config.PALLET_LARGO, config.PALLET_ANCHO, ancho, largo)
    cap_mix, _metodo = max_cajas(config.PALLET_LARGO, config.PALLET_ANCHO, largo, ancho)
    if cap_mix > max(cap_a, cap_b):
        return cap_mix, "MIXTA"
    return (cap_a, "A") if cap_a >= cap_b else (cap_b, "B")
```

**Cuidado con el valor de retorno `"MIXTA"`.** El segundo elemento de la tupla hoy es `"A"` o `"B"` y se usa aguas abajo para fijar la orientación del SKU. Hay que revisar todos los consumidores (`grep -rn "capacidad_xy_max" src/`) antes de introducir un tercer valor: una cama mixta **no tiene** una orientación única. Dos opciones:

1. Devolver `"MIXTA"` y que los consumidores lo traten como "no hay orientación única" (más correcto, requiere tocar más código).
2. Devolver la orientación dominante del patrón (la del bloque con más cajas) y perder algo de precisión, pero sin romper nada.

Recomiendo la 1, con un test que verifique que ningún consumidor asume que el valor es siempre `"A"` o `"B"`.

**Rendimiento:** ~70 ms por SKU con pinwheel activado, ~0 ms sin él. Para 458 SKUs son unos 33 s. Si molesta en el pipeline, `max_cajas(..., con_pinwheel=False)` baja a milisegundos y solo pierde los 34 casos donde el molinete gana (de 458). Alternativamente, cachear el resultado por `(largo, ancho)` redondeados — hay muchas dimensiones repetidas entre SKUs.

### Validación ya hecha (no hace falta repetirla, sí conservarla como test)

| Caso | Grilla A | Grilla B | Solver | Comentario |
|---|---|---|---|---|
| 30 × 20 | 20 | 18 | 20 | óptimo trivial, 100% del área |
| 40 × 30 | 9 | 8 | **10** | 100% del área, requiere mezcla |
| 35 × 25 | 12 | 8 | **13** | requiere descomposición de 3 niveles |
| 60 × 50 | 4 | 2 | 4 | 2×2 exacto |
| 452 × 452 | 0 | 0 | 0 | no cabe (SKU basura del Maestro) |

Además: 300 casos aleatorios verificando que el solver **nunca** supera el límite de área (300/300 correctos), y verificación exhaustiva del SKU 16522 confirmando que 11 es el máximo real con 35 × 26 en 120 × 100 estricto.

---

## P2 — Sobresaliente del pallet como criterio configurable

**Severidad: media. No cambia el motor por sí solo, pero es la regla de negocio que decide si un dato del Maestro es válido o no.**

Hoy el repo no tiene ningún concepto de sobresaliente: el pallet es 120 × 100 y punto. Pero la operación sí acepta que la caja vuele del borde, y Omar confirmó el criterio: **hasta 2,5 cm por lado**.

Ese número no es arbitrario — es el límite del estándar logístico: más allá, la caja pierde sobre 20% de resistencia a la compresión al quedar su esquina sin apoyo (a 5 cm la pérdida supera el 30%).

```python
# config.py — agregar junto a PALLET_LARGO / PALLET_ANCHO

# [V4] Sobresaliente aceptado: cuánto puede volar la caja del borde del pallet.
# Confirmado con Omar. 2,5 cm por lado es el límite del estándar logístico —
# más allá la caja pierde sobre 20% de resistencia a la compresión porque su
# esquina queda sin apoyo. Poner 0.0 vuelve al criterio estricto de V3.
#
# Medido sobre 458 SKUs, cuánto del dato declarado por la operación resulta
# geométricamente alcanzable según el sobresaliente que se acepte:
#     0,0 cm/lado -> 73%
#     1,0 cm/lado -> 78%
#     2,0 cm/lado -> 81%
#     2,5 cm/lado -> 82%   <- elegido
#     5,0 cm/lado -> 86%   (fuera del estándar seguro)
SOBRESALIENTE_MAX_CM = 2.5
PALLET_LARGO_EFECTIVO = PALLET_LARGO + 2 * SOBRESALIENTE_MAX_CM   # 125
PALLET_ANCHO_EFECTIVO = PALLET_ANCHO + 2 * SOBRESALIENTE_MAX_CM   # 105
```

**Dónde usarlo — y dónde NO.** Esta es la parte delicada:

- **SÍ** en la validación/reconciliación de `caja/cama`: para decidir si el dato del Maestro es creíble, hay que medir contra el área efectiva. Si no, se marcan como imposibles 22 SKUs que la operación sí arma.
- **NO** en el packing real (`packing_2d`) por defecto. Si el motor empieza a planificar asumiendo sobresaliente en todos lados, se acumula: dos camas que sobresalen en direcciones distintas dan un pallet con perfil irregular difícil de estibar y envolver.

Recomiendo dejarlo como criterio de **validación de datos**, no de **planificación**, hasta que la operación confirme que quiere planificar así. Es una decisión de negocio que conviene preguntarle a Omar explícitamente antes de conectarlo al packing.

---

## P3 — Corregir los 32 SKUs con `caja/cama` inalcanzable

**Severidad: alta para la calidad del plan. Es dato, no código.**

El motor confía en `caja/cama` del Maestro como techo de densidad. Si el dato dice que entran más cajas de las que físicamente entran, el motor planifica camas que no se pueden armar en el piso.

El listado completo está en **`skus_caja_cama_a_corregir.csv`** (esta carpeta). Resumen:

| Grupo | SKUs | Qué hacer |
|---|---|---|
| Imposibles **ya remedidos** en piso | 8 | La dimensión está verificada → el error está en `caja/cama`. **Corregir en el Maestro** con el valor de `max_con_sobresaliente`. |
| Imposibles **pendientes de remedir** | 16 | La dimensión sigue siendo la original → es probable que se resuelvan solos al terminar la medición. **Esperar.** |
| "No alcanza" (área da, pero exige empaque perfecto) | 8 | Revisar en piso caso por caso. |

El caso más grave es el SKU **22183 (Ron Hechicera Banano)**: declara **84 cajas por cama** cuando entran 15. Sus dimensiones ya fueron remedidas, así que es error puro del dato.

**Sugerencia de guard en `validacion.py`** (aparte de corregir el dato): agregar una regla que compare `caja/cama` contra la capacidad geométrica con sobresaliente y degrade al valor geométrico cuando el Maestro declare algo imposible, logueándolo. Hoy V3 confía en el Maestro sin ese chequeo. Es coherente con la filosofía de V3 (`ante dato del Maestro no confiable, caer al cálculo geométrico`) y evita que un error de captura se propague al plan de picking.

---

## Orden sugerido de aplicación

| # | Parche | Cambia el resultado | Riesgo |
|---|---|---|---|
| 1 | P3 — corregir los 8 SKUs ya verificados | sí, mejora la fidelidad | bajo, es dato |
| 2 | P2 — constantes de sobresaliente (solo validación) | no por sí solo | nulo |
| 3 | P1 — solver mixto en `capacidad_xy_max` | sí, ~12 camas menos | medio, ver nota de `"MIXTA"` |

Correr el benchmark antes y después de cada uno:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from src import pipeline
r = pipeline.ejecutar_desde_archivo('Cubicaje_remedido.xlsx')
pl = [p for p in r.pallets if not p.id.startswith('SIN-ASIGNAR')]
alt = [p.altura_final for p in pl]
parc = sum(1 for p in pl if 'PARCIAL' in p.estado)
camas = sum(len(p.camas) for p in pl)
print(f'pallets={len(pl)} (real=42) parciales={parc} altura_prom={sum(alt)/len(alt):.1f} camas={camas}')
"
pytest -q
```

**Referencia actual (antes de aplicar nada):** `pallets=56 parciales=28 altura_prom=186.7 camas=272`.

---

## Lo que NO resuelven estos parches

Los tres juntos no cierran la brecha de 56 → 42. El piso teórico con las camas actuales es 48. Para bajar de ahí hay que atacar la **generación de camas**, no el apilado:

- Las 53 camas con menos del 50% de la base cubierta (19% del total) son el objetivo. Aportan 1.265 cm de altura, 13% del total.
- 32 de ellas tienen un solo SKU con mediana de 4 cajas — remanentes que no encontraron con quién combinarse.
- `ESTRATEGIA_CAMAS` en `config.py` ya documenta dos alternativas no implementadas (`GLOBAL_MIX`, `HYBRID_LOOKAHEAD`) pensadas exactamente para esto.

**Pero antes de invertir ahí, conseguir `Plan de acción 10.08 - CUBICADO.xlsx` y verificar que los 42 pallets reales sean de esta misma demanda.** Si no lo son, el objetivo está mal fijado y 48-56 pallets podría ser el resultado correcto. Con ese archivo también se puede comparar pallet por pallet cuántas camas usa la operación real y con cuántas cajas cada una — que es lo que de verdad explicaría la diferencia.
