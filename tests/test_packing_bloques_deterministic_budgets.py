"""[PATCH V6.12-D5 -"Deterministic DFS/LNS Work Budgets"] Tests obligatorios
de la autorización: `_resolver_pallets_backtracking`/`_lns_mejorar_pallets`
ya NO usan `limite_tiempo`/`reloj` para decidir ningún corte -acotan
ÚNICAMENTE por `max_nodos`/iteraciones/sin_mejora_max/solución completa,
deterministas. Motivación real (V6.12-2A2-D2/D3/D4): un deadline de
`process_time()` cortaba SJ87 en un punto distinto entre corridas con la
MISMA entrada, según el throughput efectivo del proceso -nunca según
cuánto trabajo lógico hacía falta."""
import time
from unittest.mock import patch

import src.packing_bloques as pb
from models import PalletV5
from src.packing_bloques import (
    _altura_presupuesto,
    _lns_mejorar_pallets,
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


def _escenario_combinatorio():
    """[fixture compartida] Demanda a propósito FÍSICAMENTE IMPOSIBLE de
    completar en 1 pallet (2 SKUs, 200 unidades cada uno -muy por encima de
    lo que cabe) -nunca dispara "solución encontrada", así que el ÚNICO
    modo de terminar es `max_nodos` (DFS) o agotamiento real del espacio de
    búsqueda -exactamente lo que estos tests necesitan para aislar esos dos
    criterios sin depender de cuántos nodos "hacen falta" en un escenario
    que sí complete (frágil de calibrar). Medido empíricamente: con
    max_nodos=5/20/30000 da 5/20/29998 llamadas a `_candidatos_lote` y
    50/148/260 cajas -estrictamente creciente con más presupuesto de
    nodos, nunca completa (jamás llega a 400)."""
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=200)],
        "B": [_cand("B", 20, 15, 12, cantidad_disponible=200)],
    }
    pendientes = {"A": 200, "B": 200}
    return por_sku, pendientes


def _escenario_completable():
    """[fixture compartida, chica] A diferencia de la de arriba, ESTA sí se
    completa con presupuesto de nodos generoso -para los tests que
    necesitan una "solución encontrada" real (no solo agotamiento de
    nodos)."""
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=9)],
        "B": [_cand("B", 30, 40, 20, cantidad_disponible=9)],
        "C": [_cand("C", 40, 25, 15, cantidad_disponible=9)],
        "D": [_cand("D", 25, 40, 15, cantidad_disponible=9)],
    }
    pendientes = {"A": 9, "B": 9, "C": 9, "D": 9}
    return por_sku, pendientes


def _contar_llamadas_candidatos_lote():
    """Monkeypatch de `_candidatos_lote` que cuenta invocaciones -proxy
    fiel de nodos DFS visitados (cada nodo no podado por cota llama a esta
    función exactamente una vez, ver `_resolver_pallets_backtracking`)."""
    llamadas = [0]
    original = pb._candidatos_lote

    def _contado(*args, **kwargs):
        llamadas[0] += 1
        return original(*args, **kwargs)

    return llamadas, _contado


# --- 1. Misma entrada + distinta velocidad artificial del reloj ------------

def test_1_distinta_velocidad_de_reloj_mismos_nodos_mismo_resultado():
    por_sku, pendientes_base = _escenario_combinatorio()

    def _correr(reloj):
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        llamadas, contado = _contar_llamadas_candidatos_lote()
        with patch.object(pb, "_candidatos_lote", side_effect=contado):
            _resolver_pallets_backtracking(
                construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=200,
                limite_tiempo=0.1, reloj=reloj,  # deadline MINUSCULO -- si importara, cortaría de inmediato
            )
        return sum(colocados[0].values()), llamadas[0]

    reloj_lento = lambda: 0.0          # nunca avanza
    reloj_rapido = lambda: 1e12        # "vencido" desde el primer nodo
    cajas_lento, nodos_lento = _correr(reloj_lento)
    cajas_rapido, nodos_rapido = _correr(reloj_rapido)

    assert cajas_lento == cajas_rapido
    assert nodos_lento == nodos_rapido


# --- 2. DFS termina EXACTAMENTE por max_nodos cuando corresponde -----------

def test_2_dfs_termina_exactamente_por_max_nodos():
    """Demanda físicamente imposible (`_escenario_combinatorio`): nunca hay
    "solución encontrada", así que el corte es SIEMPRE `max_nodos` (o
    agotamiento real, que acá no llega a pasar dentro de estos topes) -
    verificado exactamente: `llamadas == max_nodos` en ambos casos, y más
    presupuesto de nodos nunca da MENOS cajas."""
    por_sku, pendientes_base = _escenario_combinatorio()

    def _correr(max_nodos):
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        llamadas, contado = _contar_llamadas_candidatos_lote()
        with patch.object(pb, "_candidatos_lote", side_effect=contado):
            _resolver_pallets_backtracking(
                construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=max_nodos,
            )
        return sum(colocados[0].values()), llamadas[0]

    cajas_chico, nodos_chico = _correr(max_nodos=5)
    cajas_grande, nodos_grande = _correr(max_nodos=20)

    assert nodos_chico == 5  # se detiene EXACTAMENTE en el tope, ni antes ni después
    assert nodos_grande == 20
    assert cajas_chico < 400 and cajas_grande < 400  # nunca completa (demanda imposible)
    assert cajas_chico <= cajas_grande  # más presupuesto de nodos, nunca peor


# --- 3. LNS termina EXACTAMENTE por max_iter o sin_mejora_max --------------

def _contar_llamadas_romper_cascada():
    llamadas = [0]
    original = pb._romper_skus_con_cascada

    def _contado(*args, **kwargs):
        llamadas[0] += 1
        return original(*args, **kwargs)

    return llamadas, _contado


def test_3a_lns_termina_por_max_iteraciones():
    por_sku, pendientes_base = _escenario_combinatorio()
    pendientes = dict(pendientes_base)
    construcciones, colocados = _estado_inicial(1)
    # Incumbente parcial deliberado (demanda imposible -siempre queda algo
    # pendiente, nunca dispara "solución completa").
    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=5,
    )

    llamadas, contado = _contar_llamadas_romper_cascada()
    with patch.object(pb, "_romper_skus_con_cascada", side_effect=contado), \
         patch.object(pb, "COMBINACION_PALLETS_LNS_ITERACIONES", 5), \
         patch.object(pb, "COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX", 1_000_000):
        _lns_mejorar_pallets(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, semilla="t3a",
        )
    assert llamadas[0] == 5  # exactamente COMBINACION_PALLETS_LNS_ITERACIONES, ni una mas ni una menos


def test_3b_lns_termina_por_sin_mejora_max():
    por_sku, pendientes_base = _escenario_combinatorio()
    pendientes = dict(pendientes_base)
    construcciones, colocados = _estado_inicial(1)
    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=5,
    )

    llamadas, contado = _contar_llamadas_romper_cascada()
    with patch.object(pb, "_romper_skus_con_cascada", side_effect=contado), \
         patch.object(pb, "COMBINACION_PALLETS_LNS_ITERACIONES", 1_000_000), \
         patch.object(pb, "COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX", 3), \
         patch.object(pb, "COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION", 0):
        # max_nodos_reconstruccion=0 -> la reconstruccion interna nunca mejora
        # nada -> sin_mejora sube 1 por iteracion, sin excepcion.
        _lns_mejorar_pallets(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, semilla="t3b",
        )
    assert llamadas[0] == 3  # exactamente COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX


def test_3c_lns_termina_por_solucion_completa_sin_agotar_nada_mas():
    """[PATCH V6.12-D5, criterio nuevo] Si ya se coloco el 100% al entrar,
    LNS no gasta ninguna iteracion mas -ni siquiera una."""
    por_sku, pendientes_base = _escenario_completable()
    pendientes = dict(pendientes_base)
    construcciones, colocados = _estado_inicial(1)
    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=30_000,
    )
    assert sum(colocados[0].values()) == 36  # ya completo antes de llamar a LNS

    llamadas, contado = _contar_llamadas_romper_cascada()
    with patch.object(pb, "_romper_skus_con_cascada", side_effect=contado):
        resultado = _lns_mejorar_pallets(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, semilla="t3c",
        )
    assert llamadas[0] == 0  # 0 iteraciones reales -- se detecto "completo" antes de la primera
    assert resultado == 36


# --- 4. Mockear process_time() no cambia el resultado -----------------------

def test_4_mockear_process_time_no_cambia_el_resultado():
    por_sku, pendientes_base = _escenario_completable()

    def _correr():
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1,
            limite_tiempo=0.001,  # reloj real (process_time) por default -- mockeado abajo
        )
        return sum(colocados[0].values())

    cajas_normal = _correr()
    with patch("time.process_time", side_effect=[1e12] * 100_000):  # "reloj" saltando altisimo desde el inicio
        cajas_mockeado = _correr()

    assert cajas_normal == cajas_mockeado == 36


# --- 5. Con limite de nodos menor, el resultado puede cambiar (predecible) -

def test_5_limite_de_nodos_menor_cambia_resultado_de_forma_predecible():
    por_sku, pendientes_base = _escenario_completable()

    def _correr(max_nodos):
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=max_nodos,
        )
        return sum(colocados[0].values())

    cajas_pocos_nodos = _correr(max_nodos=2)
    cajas_muchos_nodos = _correr(max_nodos=30_000)

    assert cajas_pocos_nodos <= cajas_muchos_nodos  # nunca peor con mas presupuesto de nodos
    assert cajas_pocos_nodos < 36  # con pocos nodos, genuinamente no alcanza a completar
    assert cajas_muchos_nodos == 36  # con nodos de sobra, completa


# --- 6. El resultado sigue siendo identico entre ejecuciones ---------------

def test_6_resultado_identico_entre_ejecuciones_repetidas():
    por_sku, pendientes_base = _escenario_combinatorio()

    resultados = []
    for _ in range(5):
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=500,
        )
        resultados.append(dict(colocados[0]))

    assert all(r == resultados[0] for r in resultados)


def test_6b_lns_resultado_identico_entre_ejecuciones_repetidas():
    por_sku, pendientes_base = _escenario_combinatorio()

    resultados = []
    for _ in range(3):
        pendientes = dict(pendientes_base)
        construcciones, colocados = _estado_inicial(1)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, max_nodos=2,
        )
        _lns_mejorar_pallets(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 1, semilla="t6b",
        )
        resultados.append(dict(colocados[0]))

    assert all(r == resultados[0] for r in resultados)
