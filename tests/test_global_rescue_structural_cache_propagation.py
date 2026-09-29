"""[V6.12-2A2 -"Structural Cache Propagation"] Tests obligatorios de la
autorización: reuso correcto de `CacheEstructural` cuando se asocia por
estado exacto (`_cache_estructural_de_estado`/`_asociar_cache_estructural`),
sin cambiar NINGÚN resultado -solo evita re-enumerar desde cero.

Parte A (1-4, 8): unitarios directos sobre `CacheEstructural`, con un
generador FAKE controlado (secuencia fija, cuenta cuántas veces se llama/
avanza) -precisión total sobre "se re-enumeró o no", sin depender de
geometría real.

Parte B (5-7): integración vía `_contar_candidatos_y_registrar` +
`_EstadoGlobal` real (mismo patrón MaxRects=0 que `test_global_rescue_
hybrid.py::_pallet_con_A_B_union`), verificando la asociación por objeto
Python (nunca por geometría "parecida", nunca heredada al clonar)."""
import config
import src.global_rescue as gr
from models import PalletV5
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _fake_factory(secuencia: list, llamadas: list, items_pulled: list):
    """Generador determinista que yields exactamente `secuencia` -
    `llamadas` registra cuántas veces se INVOCÓ la factory (= cuántas
    enumeraciones nuevas se arrancaron); `items_pulled` registra cada
    `next()` real que se ejecutó (= trabajo de enumeración genuino)."""
    def factory():
        llamadas.append(1)

        def _gen():
            for item in secuencia:
                items_pulled.append(item)
                yield item
        return _gen()
    return factory


# --- 1. EXISTS(False) -> COUNT devuelve 0 sin nueva enumeración -----------

def test_1_exists_false_luego_count_no_reenumerar():
    cache = gr.CacheEstructural()
    llamadas, pulled = [], []
    factory = _fake_factory([], llamadas, pulled)
    estado, sku = object(), "A"

    encontrado = cache.existe(estado, sku, factory, stats=None)
    assert encontrado is False
    assert llamadas == [1]

    # COUNT sobre el MISMO (estado, sku) -la factory NUNCA debe volver a
    # invocarse (0 nueva enumeración): EXISTS(False) ya prueba COUNT=0.
    resultado = cache.contar(estado, sku, factory, limite=4, stats=None)
    assert resultado == 0
    assert llamadas == [1]  # sigue siendo 1 -sin nueva enumeración
    assert pulled == []


# --- 2. EXISTS(True) -> COUNT(limit=4) sigue enumerando, no asume count=1 -

def test_2_exists_true_luego_count_continua_enumerando():
    cache = gr.CacheEstructural()
    llamadas, pulled = [], []
    factory = _fake_factory(["p1", "p2", "p3", "p4", "p5"], llamadas, pulled)
    estado, sku = object(), "A"

    encontrado = cache.existe(estado, sku, factory, stats=None)
    assert encontrado is True
    assert pulled == ["p1"]  # EXISTS solo pide 1

    resultado = cache.contar(estado, sku, factory, limite=4, stats=None)
    assert resultado == 4  # NO se queda en 1 -sigue enumerando hasta el límite
    assert pulled == ["p1", "p2", "p3", "p4"]  # continuó el MISMO iterador, no lo reinició
    assert llamadas == [1]  # la factory (arranque del generador) se llamó una sola vez


# --- 3. COUNT exacto -> EXISTS reutiliza el resultado -----------------------

def test_3_count_exacto_luego_exists_reutiliza():
    cache = gr.CacheEstructural()
    llamadas, pulled = [], []
    factory = _fake_factory(["p1", "p2", "p3"], llamadas, pulled)  # se agota en 3
    estado, sku = object(), "A"

    resultado = cache.contar(estado, sku, factory, limite=4, stats=None)
    assert resultado == 3  # agotado antes de llegar a 4
    assert pulled == ["p1", "p2", "p3"]

    encontrado = cache.existe(estado, sku, factory, stats=None)
    assert encontrado is True  # ya hay 3 encontrados -no hace falta enumerar nada más
    assert pulled == ["p1", "p2", "p3"]  # sin cambios
    assert llamadas == [1]


# --- 4. COUNT saturado -> EXISTS sigue siendo correcto ----------------------

def test_4_count_saturado_luego_exists_correcto():
    cache = gr.CacheEstructural()
    llamadas, pulled = [], []
    factory = _fake_factory(["p1", "p2", "p3", "p4", "p5", "p6"], llamadas, pulled)  # 6 disponibles, NO se agota en 4
    estado, sku = object(), "A"

    resultado = cache.contar(estado, sku, factory, limite=4, stats=None)
    assert resultado == 4  # saturado -corta en el límite, quedan más sin pedir
    assert pulled == ["p1", "p2", "p3", "p4"]

    encontrado = cache.existe(estado, sku, factory, stats=None)
    assert encontrado is True  # correcto aunque el generador no esté agotado
    assert pulled == ["p1", "p2", "p3", "p4"]  # EXISTS no pide nada extra -ya hay encontrados
    assert llamadas == [1]


# --- 8. Orden de queries -> mismos resultados que una cache fresca ----------

def test_8_orden_exists_count_vs_count_exists_mismos_resultados_que_fresca():
    secuencia = ["p1", "p2", "p3"]

    # Orden A: EXISTS -> COUNT, con cache COMPARTIDA.
    cache_a = gr.CacheEstructural()
    llamadas_a, pulled_a = [], []
    factory_a = _fake_factory(secuencia, llamadas_a, pulled_a)
    estado_a, sku = object(), "A"
    exists_a = cache_a.existe(estado_a, sku, factory_a, stats=None)
    count_a = cache_a.contar(estado_a, sku, factory_a, limite=4, stats=None)

    # Orden B: COUNT -> EXISTS, con cache COMPARTIDA.
    cache_b = gr.CacheEstructural()
    llamadas_b, pulled_b = [], []
    factory_b = _fake_factory(secuencia, llamadas_b, pulled_b)
    estado_b = object()
    count_b = cache_b.contar(estado_b, sku, factory_b, limite=4, stats=None)
    exists_b = cache_b.existe(estado_b, sku, factory_b, stats=None)

    # Referencia: cada query SOLA, con una cache fresca e independiente.
    cache_ref_exists = gr.CacheEstructural()
    exists_ref = cache_ref_exists.existe(object(), sku, _fake_factory(secuencia, [], []), stats=None)
    cache_ref_count = gr.CacheEstructural()
    count_ref = cache_ref_count.contar(object(), sku, _fake_factory(secuencia, [], []), limite=4, stats=None)

    assert exists_a == exists_b == exists_ref is True
    assert count_a == count_b == count_ref == 3  # se agota en 3, mismo resultado sin importar el orden


# --- 5. Misma geometría + mismo SKU -> reutilización (integración real) ----

def _estado_maxrects_cero(sku="TOP"):
    """MaxRects=0 para `sku` (mismo patrón que test_global_rescue_hybrid.py
    ::_pallet_con_A_B_union) -Structural SIEMPRE se consulta acá."""
    cand_a = _cand("A", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_b = _cand("B", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    gr._colocar_candidato_estructural(pc, cand_a, 0, 0, 0, 1)
    gr._colocar_candidato_estructural(pc, cand_b, 40, 0, 0, 1)
    pc.libres = []  # fuerza MaxRects=0 para cualquier otro sku
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={sku: 1})
    cand_top = _cand(sku, 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    por_sku = {"A": [cand_a], "B": [cand_b], sku: [cand_top]}
    nivel = {"A": 6, "B": 6, sku: 6}
    return estado, por_sku, nivel


def test_5_misma_geometria_mismo_sku_reutiliza():
    estado, por_sku, nivel = _estado_maxrects_cero()
    stats = {"por_sku": {}}

    assert gr._cache_estructural_de_estado(estado) is None  # todavía nada asociado

    gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, stats, max_count=1, presupuesto=PRESUPUESTO,
    )
    cache_tras_1ra = gr._cache_estructural_de_estado(estado)
    assert cache_tras_1ra is not None  # quedó asociada al estado

    hits_antes = stats.get("structural_cache_hits", 0)
    gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, stats, max_count=1, presupuesto=PRESUPUESTO,
    )
    # 2da consulta idéntica -debe ser un cache hit (misma cache reutilizada,
    # nunca una nueva) y la MISMA instancia sigue asociada.
    assert stats.get("structural_cache_hits", 0) > hits_antes
    assert gr._cache_estructural_de_estado(estado) is cache_tras_1ra


# --- 6. Child state / geometría modificada -> cache nueva -------------------

def test_6_child_state_nunca_hereda_cache_del_parent():
    estado, por_sku, nivel = _estado_maxrects_cero()
    stats = {"por_sku": {}}
    gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, stats, max_count=1, presupuesto=PRESUPUESTO,
    )
    assert gr._cache_estructural_de_estado(estado) is not None

    hijo = gr._clonar_estado(estado)
    assert hijo is not estado
    assert gr._cache_estructural_de_estado(hijo) is None  # objeto nuevo -sin cache heredada


# --- 7. Cache de parent nunca responde consultas del child ------------------

def test_7_cache_de_parent_nunca_responde_al_child():
    estado, por_sku, nivel = _estado_maxrects_cero()
    stats_parent = {"por_sku": {}}
    gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, stats_parent, max_count=1, presupuesto=PRESUPUESTO,
    )
    cache_parent = gr._cache_estructural_de_estado(estado)
    assert cache_parent is not None

    hijo = gr._clonar_estado(estado)
    stats_hijo = {"por_sku": {}}
    misses_antes = stats_hijo.get("structural_cache_misses", 0)
    gr._contar_candidatos_y_registrar(
        hijo, "TOP", por_sku, {}, nivel, {}, stats_hijo, max_count=1, presupuesto=PRESUPUESTO,
    )
    # El child hizo su PROPIA enumeración (cache miss real) -no reusó la
    # entrada del parent (que vive bajo `(id(estado_parent), "TOP")`, una
    # clave distinta a `(id(hijo), "TOP")`).
    assert stats_hijo.get("structural_cache_misses", 0) > misses_antes
    cache_hijo = gr._cache_estructural_de_estado(hijo)
    assert cache_hijo is not None
    assert cache_hijo is not cache_parent


# --- Métricas nuevas: started/resumed/avoided --------------------------------

def test_metricas_started_resumed_avoided():
    cache = gr.CacheEstructural()
    stats = {}
    factory = _fake_factory(["p1", "p2", "p3", "p4", "p5"], [], [])
    estado, sku = object(), "A"

    cache.existe(estado, sku, factory, stats)  # primera vez -> started
    assert stats.get("structural_enumerations_started") == 1
    assert stats.get("structural_enumerations_resumed", 0) == 0
    assert stats.get("structural_enumerations_avoided", 0) == 0

    cache.contar(estado, sku, factory, limite=4, stats=stats)  # ya había 1 -> resumed
    assert stats.get("structural_enumerations_started") == 1
    assert stats.get("structural_enumerations_resumed") == 1

    cache.existe(estado, sku, factory, stats)  # ya hay encontrados -> avoided
    assert stats.get("structural_enumerations_avoided") == 1
