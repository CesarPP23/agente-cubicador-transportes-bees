"""[PATCH V6.11-R3] Tests de la abstracción de reloj para DFS/LNS
(`_search_budget_now`, ver CIERRE V6.11-R1/R2).

[PATCH V6.12-D5 -"Deterministic DFS/LNS Work Budgets"] Confirmado
(V6.12-2A2-D2/D3/D4) que un deadline de reloj real -en CUALQUIER dominio,
CPU-time o wall-clock- podía cortar `_resolver_pallets_backtracking`/
`_lns_mejorar_pallets` en un punto DISTINTO entre corridas con la MISMA
entrada, según el throughput efectivo del proceso en ese instante -nunca
según cuánto trabajo lógico hacía falta (ver `SJ87` en el batch histórico
real: el mismo N=7 a veces completaba solo, a veces necesitaba rescue/
repair, sin ningún cambio de datos). Estas 2 funciones YA NO usan
`limite_tiempo`/`reloj` para decidir ningún corte -acotan ÚNICAMENTE por
`max_nodos`/iteraciones/sin_mejora_max, deterministas. Los tests de acá
abajo que antes probaban "el reloj SÍ gobierna el corte" (puntos 2 y 4 del
docstring original) se invirtieron para probar exactamente lo contrario:
el reloj YA NO gobierna nada acá, pase lo que pase con él. Sigue vigente:
(1) DFS y LNS SECUENCIALES usan `time.process_time()` por default (la
firma no cambió, solo dejó de usarse para cortar), y (3) el worker de LNS
PARALELO (`_lns_una_semilla_worker`) sigue reenviando `time.monotonic`
explícito -ese reenvío en sí no cambió, aunque ya no tenga efecto de corte
dentro de estas 2 funciones."""
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


# --- (2) [PATCH V6.12-D5] El reloj inyectado YA NO gobierna el corte ----

def test_dfs_reloj_ya_vencido_ya_no_corta_nada_coloca_la_demanda_completa():
    """[PATCH V6.12-D5, invierte la aserción original de V6.11-R3] Antes,
    un deadline YA vencido al entrar (`limite_tiempo=0.0, reloj=lambda:
    1000.0`) cortaba el DFS en el nodo raíz, sin colocar nada. Ahora ese
    mismo reloj "vencido" se ignora por completo -el resultado depende
    únicamente de `max_nodos`/solución encontrada, así que coloca la
    demanda completa igual que si no se hubiera pasado ningún reloj."""
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=10)]}
    pendientes = {"A": 10}
    construcciones, colocados = _estado_inicial(1)

    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
        limite_tiempo=0.0, reloj=lambda: 1000.0,
    )
    assert sum(colocados[0].values()) == 10


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


# --- (4) [PATCH V6.12-D5] Invariancia a CUALQUIER demora, en CUALQUIER
# dominio -ya no es "CPU inmune, wall-clock no"; ahora NINGÚN dominio
# afecta nada, porque el reloj dejó de consultarse en absoluto. ---------

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


def test_presupuesto_ya_no_se_ve_afectado_por_ninguna_demora_en_ningun_dominio():
    """[PATCH V6.12-D5, invierte la aserción original de V6.11-R3] Antes,
    un presupuesto de 0.5 en modo reloj-de-pared cortaba la búsqueda casi
    de inmediato (`cajas_wall < cajas_cpu`) -ahora NINGÚN dominio corta
    nada: ambos modos ignoran `limite_tiempo`/`reloj` por completo y
    colocan la demanda completa (12 = A + B), sin importar qué tan grande
    sea la demora simulada por nodo en ninguno de los dos relojes."""
    cajas_cpu = _correr_con_demora_simulada("cpu", presupuesto_reloj=0.5)
    cajas_wall = _correr_con_demora_simulada("wall", presupuesto_reloj=0.5)

    assert cajas_cpu == 12
    assert cajas_wall == 12
