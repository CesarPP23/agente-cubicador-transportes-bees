"""[PATCH V6.12-D7B-P2 -"Probe Rescue work budget"] Medidor de TRABAJO
determinista: un `reloj` cuya unidad son NODOS de backtracking, no segundos.

Rescue/Repair/Global ya reciben un callable `reloj` y comparan
`reloj() > limite_tiempo` en puntos de control fijos (entre unidades de
trabajo). Pasarles un `MedidorTrabajo` en lugar de `time.process_time`
convierte esos mismos puntos de control en un presupuesto de nodos, sin tocar
el flujo de control. Los backtracking (`_resolver_pallets_backtracking`,
`_colocar_critico_backtracking`) detectan `registrar_nodos` en el `reloj` que
reciben y le suman sus nodos al terminar; con un `reloj` normal (una función)
no hacen nada.

CONVENCIÓN DE CONTEO (la misma para todos los budgets de trabajo):
  * Unidad: VISITAS de nodo, la métrica real `estado["nodos"]` de
    `_resolver_pallets_backtracking` (contador incrementado al ENTRAR a cada
    nodo; ver tests/test_busqueda_n_pallets_probe_dfs_budget.py). Cuando un DFS
    corta por su tope N reporta N + 1 visitas (la que excede el tope se cuenta
    y retorna sin expandir).
  * El medidor se actualiza al TERMINAR cada backtracking (no durante), y los
    puntos de control son estrictos (`reloj() > limite_tiempo`) y se evalúan
    ENTRE unidades de trabajo (y entre variantes de lote dentro de
    `_aplicar_ruina_dirigida`): la unidad en curso termina, así que el total
    consumido puede superar el tope por, como máximo, esa unidad. Contrato
    explícito: SOFT CAP AT WORK-UNIT BOUNDARY (en P3 un DFS de Repair llegó a
    26365 visitas con tope 24000); el comportamiento es deliberado y no se
    modifica. (El tope de INTENTOS de Exact, P4, en cambio es duro: se chequea
    antes de iniciar cada intento.)
  * [D8B-7.2] Global Rescue usa el mismo medidor con otra unidad: EXPANSIONES
    de estado (cada `_expandir_estado` del beam search suma 1); sus puntos de
    control son el inicio de cada profundidad / reinicio (soft cap at depth
    boundary).
  * Con el mismo input el recorrido es idéntico: ni el reloj de pared ni la
    velocidad de la máquina participan."""


import math
import time


class MedidorTrabajo:
    __slots__ = ("nodos",)
    # [V6.13-P1B2-R1] Los DFS que reciben este reloj activan solos las optimizaciones de V6.13-P1-A (métricas diferidas + memo del área de
    # huella) porque su trabajo está acotado por nodos. Un reloj hijo puede apagarlas poniendo `permite_p1a = False` (ver abajo).
    permite_p1a = True

    def __init__(self) -> None:
        self.nodos = 0

    def __call__(self) -> float:
        return float(self.nodos)

    def registrar_nodos(self, nodos: int) -> None:
        self.nodos += nodos


class RelojTrabajoConWatchdog(MedidorTrabajo):
    """[V6.13-P1B2-R1 -"Rescue natural exhaustion"] Reloj de TRABAJO (nodos) con un watchdog de CPU, para el Rescue del camino profundo de N fijo.

    * NO gobierna: la etapa no tiene presupuesto de trabajo ni de tiempo; termina por sus condiciones naturales (solución / una ronda
      completa sin progreso). El caller usa `SIN_TOPE` como `limite_tiempo`, de modo que mientras el watchdog no dispare `reloj() < limite`
      y `reloj() > limite` nunca cortan. Lo único que este reloj aporta es el CONTEO de trabajo (`nodos`, misma convención que el resto de
      los medidores) y el watchdog.
    * Watchdog: si el CPU del proceso supera `watchdog_deadline` (instante absoluto de `time.process_time()`), `watchdog_disparado` queda
      en `True` y el reloj devuelve `inf` desde ese momento (mayor que `SIN_TOPE`), así que TODOS los chequeos de la etapa cortan en el
      siguiente borde. Nunca decide el resultado normal; el caller debe registrar y avisar si dispara.
    * `permite_p1a = True` [V6.13-P1B2-R2]: como todo reloj de trabajo, activa las optimizaciones de P1-A (métricas diferidas + memo del área de
      huella) en los DFS de la etapa. Es seguro porque Rescue ya no depende del CPU para decidir cuánto trabajo hace: acelerar cada nodo no le
      permite explorar más, solo terminar antes (mismo conteo de trabajo, mismo motivo de parada, mismo resultado). En R1 estaba en `False`
      (se cambiaba solo el gobernador, no la implementación)."""

    __slots__ = ("watchdog_deadline", "watchdog_disparado")
    permite_p1a = True
    SIN_TOPE = 1e30

    def __init__(self, watchdog_deadline: float) -> None:
        super().__init__()
        self.watchdog_deadline = watchdog_deadline
        self.watchdog_disparado = False

    def __call__(self) -> float:
        if not self.watchdog_disparado and time.process_time() > self.watchdog_deadline:
            self.watchdog_disparado = True
        return math.inf if self.watchdog_disparado else float(self.nodos)
