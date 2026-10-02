"""[PATCH V6.12-D7B-0 -"Deterministic LNS restarts"] Tests de la cantidad y
la selección de reinicios LNS en `_empacar_n_pallets`:

- Ruta SECUENCIAL (`paralelo_lns=False`, la del batch multi-CD): exactamente
  `COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL` (=1) reinicios, sin que
  ningún reloj decida cuántos (antes: `reloj_lns() > deadline_lns`).
- Ruta PARALELA (`paralelo_lns=True`): se mantienen 5 semillas, pero el
  ganador ya no depende de qué proceso hijo terminó primero (antes:
  `as_completed` + `>` estricto => en empate ganaba "el primero en
  terminar"). Desempate explícito: índice de semilla ascendente.
"""
import concurrent.futures
from types import SimpleNamespace

import pytest

import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from src.packing_bloques import _seleccionar_mejor_reinicio
from src.torres import TorreCandidate


def _cand(sku, largo, ancho, alto, cantidad_disponible=20, max_verticales=20):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _escenario_inalcanzable():
    """Demanda físicamente imposible en 1 pallet: el DFS nunca completa, así
    que la fase de LNS SIEMPRE corre."""
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=200)],
        "B": [_cand("B", 20, 15, 12, cantidad_disponible=200)],
    }
    return por_sku, {"A": 200, "B": 200}


def _pc_falso():
    return SimpleNamespace(pallet=SimpleNamespace(torres=[]), libres=[])


def _resultado(total, marca):
    """(total, construcciones, colocados, pendientes) con una `marca` visible
    en `pendientes` para identificar QUÉ semilla ganó."""
    return (total, [_pc_falso()], [{}], {"_marca": marca})


# ---------------------------------------------------------------- selección pura


def test_seleccion_empate_entre_semillas_gana_el_menor_indice():
    base_snapshot = ("base", [], {})
    resultados = [_resultado(8, -1), _resultado(10, -2), _resultado(9, -3), _resultado(10, -4), _resultado(10, -5)]

    total, snapshot = _seleccionar_mejor_reinicio(5, base_snapshot, resultados)

    assert total == 10
    assert snapshot[2]["_marca"] == -2  # semilla 1: la primera con 10, no la 3 ni la 4


def test_seleccion_incumbente_de_entrada_gana_empates():
    base_snapshot = ("dfs", [], {"_marca": "dfs"})
    resultados = [_resultado(7, -1), _resultado(7, -2)]

    total, snapshot = _seleccionar_mejor_reinicio(7, base_snapshot, resultados)

    assert total == 7
    assert snapshot is base_snapshot  # criterio de siempre: `>` estricto


def test_seleccion_ninguna_mejora_devuelve_el_incumbente():
    base_snapshot = ("dfs", [], {})
    total, snapshot = _seleccionar_mejor_reinicio(9, base_snapshot, [_resultado(3, -1), _resultado(4, -2)])
    assert (total, snapshot) == (9, base_snapshot)


# ------------------------------------------------------------ ruta paralela real


class _FuturoFalso:
    def __init__(self, idx, valor, registro_lectura):
        self.idx = idx
        self._valor = valor
        self._registro = registro_lectura

    def result(self):
        self._registro.append(self.idx)
        return self._valor


def _ejecutar_paralelo_con_executor_falso(monkeypatch, totales, demanda_total, orden_de_terminacion):
    """Corre `_empacar_n_pallets(paralelo_lns=True)` real con un
    `ProcessPoolExecutor` falso -sin procesos hijos- cuyas 5 semillas
    "terminan" en `orden_de_terminacion` (lo único que cambia entre
    corridas). Devuelve (marca de la semilla ganadora, orden en que se leyeron
    los resultados, orden de terminación simulado)."""
    lecturas: list[int] = []
    terminaciones: list[int] = []
    capturado: dict = {}

    class _ExecutorFalso:
        def __init__(self, *args, **kwargs):
            self._futuros = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            # "terminan" en el orden pedido -nada de esto puede importar.
            for idx in orden_de_terminacion:
                terminaciones.append(idx)
            return False

        def submit(self, fn, *args):
            idx = int(args[9].rsplit("-", 1)[1])  # semilla = f"{cd}-{n}-{intento}"
            total = totales[idx]
            construcciones, colocados, pendientes = args[0], args[1], args[2]
            pendientes_i = {sku: 0 for sku in pendientes}
            pendientes_i["_marca"] = -(idx + 1)  # negativa: nunca cuenta como `sin_colocar`
            futuro = _FuturoFalso(idx, (total, construcciones, colocados, pendientes_i), lecturas)
            self._futuros.append(futuro)
            return futuro

    monkeypatch.setattr(pb, "ProcessPoolExecutor", _ExecutorFalso)

    original = pb._seleccionar_mejor_reinicio

    def _espia(mejor_total, mejor_snapshot, resultados):
        total, snapshot = original(mejor_total, mejor_snapshot, resultados)
        capturado["snapshot"] = snapshot
        capturado["resultados"] = resultados
        return total, snapshot

    monkeypatch.setattr(pb, "_seleccionar_mejor_reinicio", _espia)

    # DFS corto (el escenario es inalcanzable: sin esto gasta 30000 nodos).
    original_dfs = pb._resolver_pallets_backtracking

    def _dfs_corto(*a, **k):
        k["max_nodos"] = 30
        return original_dfs(*a, **k)

    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", _dfs_corto)

    por_sku, pendientes = _escenario_inalcanzable()
    pb._empacar_n_pallets(
        dict(pendientes), por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=True, con_lns=True,
    )
    return capturado["snapshot"][2].get("_marca"), lecturas, terminaciones


@pytest.mark.parametrize("orden", [[0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [2, 4, 0, 3, 1]])
def test_paralelo_mismo_ganador_sin_importar_el_orden_de_terminacion(monkeypatch, orden):
    """Empate entre las semillas 1 y 3 (ambas completan la demanda): gana
    SIEMPRE la de menor índice, cualquiera sea el orden en que 'terminen'."""
    por_sku, pendientes = _escenario_inalcanzable()
    demanda_total = sum(pendientes.values())
    totales = [40, demanda_total, 50, demanda_total, 60]

    marca, lecturas, _ = _ejecutar_paralelo_con_executor_falso(monkeypatch, totales, demanda_total, orden)

    assert marca == -2  # semilla 1
    assert lecturas == [0, 1, 2, 3, 4]  # resultados leídos por índice de semilla, no por terminación


def test_paralelo_ya_no_usa_as_completed():
    """Regresión estructural: el orden de terminación no puede volver a
    decidir nada."""
    assert not hasattr(pb, "as_completed")
    assert pb.COMBINACION_PALLETS_LNS_REINICIOS == 5  # la ruta paralela mantiene sus 5 semillas


def test_paralelo_corre_las_cinco_semillas(monkeypatch):
    por_sku, pendientes = _escenario_inalcanzable()
    demanda_total = sum(pendientes.values())
    _, lecturas, _ = _ejecutar_paralelo_con_executor_falso(
        monkeypatch, [1, 2, 3, 4, demanda_total], demanda_total, [4, 3, 2, 1, 0],
    )
    assert sorted(lecturas) == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------- ruta secuencial


def _preparar_secuencial(monkeypatch, reloj_lns_valor):
    """Cascada stubeada (no es lo que se prueba), LNS contado, DFS corto."""
    monkeypatch.setattr(rs, "rescue_solver", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))
    monkeypatch.setattr(
        er, "exact_repair_orquestado",
        lambda pallet, por_sku, sin_colocar, *a, **k: (pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}),
    )
    monkeypatch.setattr(gr, "global_rescue", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))

    llamadas = []

    def _lns_contado(construcciones, colocados, pendientes, *a, **k):
        llamadas.append(k.get("semilla"))
        return sum(sum(d.values()) for d in colocados)  # nunca mejora ni completa

    monkeypatch.setattr(pb, "_lns_mejorar_pallets", _lns_contado)

    original_dfs = pb._resolver_pallets_backtracking

    def _dfs_corto(*a, **k):
        k["max_nodos"] = 30
        return original_dfs(*a, **k)

    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", _dfs_corto)
    # El reloj NO debe poder decidir cuántos reinicios corren.
    monkeypatch.setattr(pb, "_search_budget_now", reloj_lns_valor)
    monkeypatch.setattr(pb, "_tiempo_max_lns", lambda demanda: 1e12)
    return llamadas


def _correr_secuencial():
    por_sku, pendientes = _escenario_inalcanzable()
    pb._empacar_n_pallets(
        dict(pendientes), por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, con_lns=True,
    )


def test_secuencial_siempre_un_reinicio_con_reloj_congelado(monkeypatch):
    """Reloj congelado + tope de tiempo infinito: el código viejo habría
    corrido los 5 reinicios (`reloj_lns() > deadline_lns` nunca daba True)."""
    llamadas = _preparar_secuencial(monkeypatch, lambda incluye_trabajo_hijos=False: 0.0)
    _correr_secuencial()
    assert len(llamadas) == pb.COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL == 1
    assert llamadas == ["TEST-1-0"]


def test_secuencial_siempre_un_reinicio_con_reloj_que_salta(monkeypatch):
    """Mismo resultado aunque el reloj avance a velocidades absurdas."""
    tick = {"t": 0.0}

    def _reloj_loco(incluye_trabajo_hijos=False):
        tick["t"] += 1e9
        return tick["t"]

    llamadas = _preparar_secuencial(monkeypatch, _reloj_loco)
    _correr_secuencial()
    assert len(llamadas) == 1


def test_secuencial_constante_explicita_y_sin_reloj_en_la_decision():
    assert pb.COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL == 1
    assert pb.COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL <= pb.COMBINACION_PALLETS_LNS_REINICIOS
