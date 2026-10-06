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
    consumido puede superar el tope por, como máximo, esa unidad.
  * Con el mismo input el recorrido es idéntico: ni el reloj de pared ni la
    velocidad de la máquina participan."""


class MedidorTrabajo:
    __slots__ = ("nodos",)

    def __init__(self) -> None:
        self.nodos = 0

    def __call__(self) -> float:
        return float(self.nodos)

    def registrar_nodos(self, nodos: int) -> None:
        self.nodos += nodos
