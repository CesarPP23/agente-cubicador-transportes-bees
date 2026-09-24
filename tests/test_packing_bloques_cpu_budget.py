"""[PATCH V6.11-R3] Tests de la abstracción de reloj para DFS/LNS
(`_search_budget_now`, ver CIERRE V6.11-R1/R2). Confirman: (1) DFS y LNS
SECUENCIALES usan `time.process_time()` por default, (2) el `reloj`
inyectado realmente gobierna el corte de búsqueda -no es un parámetro
decorativo, (3) el worker de LNS PARALELO (`_lns_una_semilla_worker`,
corre en un proceso hijo de `ProcessPoolExecutor`) pasa `time.monotonic`
explícito, nunca CPU-time del padre, y (4) el presupuesto en modo CPU es
invariante a una demora externa que no consume CPU de este proceso
(contención de otros CDs hermanos), mientras el mismo presupuesto en modo
reloj-de-pared SÍ se ve recortado por esa demora -sin dormir de verdad:
todo con relojes falsos inyectados, determinista y rápido."""
import inspect
import time
from unittest.mock import patch

import src.packing_bloques as pb
from models import PalletV5
from src.packing_bloques import (
    _altura_presupuesto,
    _lns_mejorar_pallets,
    _lns_una_semilla_worker,
    _resolver_pallets_backtracking,
)
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate

PRESUPUESTO = _altura_presupuesto()


def _cand(sku, largo, ancho, alto, cantidad_disponible=20, max_verticales=20):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _estado_inicial(n_pallets=1):
    construcciones, colocados = [], []
    for i in range(n_pallets):
        pallet = PalletV5(id=f"PV5-TEST-{i:03d}", cd="TEST")
        construcciones.append(_PalletEnConstruccion(pallet=pallet))
        colocados.append({})
    return construcciones, colocados


# --- (1) Defaults -------------------------------------------------------

def test_dfs_secuencial_default_es_process_time():
    sig = inspect.signature(_resolver_pallets_backtracking)
    assert sig.parameters["reloj"].default is time.process_time


def test_lns_secuencial_default_es_process_time():
    sig = inspect.signature(_lns_mejorar_pallets)
    assert sig.parameters["reloj"].default is time.process_time


# --- (2) El reloj inyectado gobierna el corte, no es decorativo --------

def test_dfs_reloj_ya_vencido_corta_en_el_nodo_raiz_sin_colocar_nada():
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=10)]}
    pendientes = {"A": 10}
    construcciones, colocados = _estado_inicial(1)

    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
        limite_tiempo=0.0, reloj=lambda: 1000.0,
    )
    assert sum(colocados[0].values()) == 0


def test_dfs_reloj_no_vencido_coloca_la_demanda_completa():
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=10)]}
    pendientes = {"A": 10}
    construcciones, colocados = _estado_inicial(1)

    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
        limite_tiempo=1e9, reloj=lambda: 0.0,
    )
    assert sum(colocados[0].values()) == 10


# --- (3) LNS paralelo usa monotonic, nunca CPU-time del padre ----------

def test_lns_una_semilla_worker_pasa_reloj_monotonic_explicito():
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    pendientes = {"A": 3}
    construcciones, colocados = _estado_inicial(1)
    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
        limite_tiempo=1e9, reloj=lambda: 0.0,
    )

    with patch("src.packing_bloques._lns_mejorar_pallets", wraps=_lns_mejorar_pallets) as mock_lns:
        _lns_una_semilla_worker(
            construcciones, colocados, dict(pendientes), por_sku, {}, {}, {}, PRESUPUESTO, 1,
            "semilla-test", limite_tiempo=time.monotonic() + 5,
        )
    assert mock_lns.call_args.kwargs["reloj"] is time.monotonic


# --- (4) Invariancia del presupuesto CPU a una demora externa ----------

class _RelojFalso:
    """Simula, por cada nodo no-terminal visitado (un llamado a
    `_candidatos_lote`), una demora externa: el reloj de PARED avanza
    mucho (como un CD hermano quitándole núcleo a este proceso), el de
    CPU casi nada (el trabajo real de este proceso por nodo)."""

    def __init__(self, avance_wall=5.0, avance_cpu=0.01):
        self.wall = 0.0
        self.cpu = 0.0
        self.avance_wall = avance_wall
        self.avance_cpu = avance_cpu

    def avanzar_por_nodo(self):
        self.wall += self.avance_wall
        self.cpu += self.avance_cpu


def _correr_con_demora_simulada(modo: str, presupuesto_reloj: float):
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=6)],
        "B": [_cand("B", 30, 40, 20, cantidad_disponible=6)],
    }
    pendientes = {"A": 6, "B": 6}
    construcciones, colocados = _estado_inicial(1)
    reloj_falso = _RelojFalso()
    reloj_lectura = (lambda: reloj_falso.cpu) if modo == "cpu" else (lambda: reloj_falso.wall)
    original = pb._candidatos_lote

    def _candidatos_con_demora(*args, **kwargs):
        reloj_falso.avanzar_por_nodo()
        return original(*args, **kwargs)

    with patch("src.packing_bloques._candidatos_lote", side_effect=_candidatos_con_demora):
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
            limite_tiempo=presupuesto_reloj, reloj=reloj_lectura,
        )
    return sum(colocados[0].values())


def test_presupuesto_cpu_es_invariante_a_la_demora_externa_simulada():
    """[sección 9] Mismo input, mismo presupuesto NUMÉRICO (0.5): en modo
    CPU, la demora de reloj de pared inyectada por nodo (5.0 "segundos"
    simulados) NUNCA se consulta -el presupuesto se agota solo por trabajo
    de CPU real (0.01 por nodo), así que alcanza para colocar toda la
    demanda. En modo reloj-de-pared, la MISMA demora corta la búsqueda
    casi de inmediato (0.5 no alcanza ni para 1 nodo de 5.0)."""
    cajas_cpu = _correr_con_demora_simulada("cpu", presupuesto_reloj=0.5)
    cajas_wall = _correr_con_demora_simulada("wall", presupuesto_reloj=0.5)

    assert cajas_cpu == 12  # A + B completos, el presupuesto de CPU nunca se vio afectado
    assert cajas_wall < cajas_cpu  # la misma demora SÍ recorta el presupuesto de pared
