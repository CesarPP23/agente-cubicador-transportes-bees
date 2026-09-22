"""[PATCH V6.05, Fase 2] Wiring de Global Rescue al pipeline real
(`_empacar_n_pallets`) -pedido explícito del usuario ANTES de correr BK52:
tests de integración que prueben la CONEXIÓN (cuándo se activa, qué pasa
si mejora, qué pasa si empeora) sin depender de si el motor de búsqueda en
sí encuentra o no una solución concreta -eso ya está exhaustivamente
cubierto en `tests/test_global_rescue.py` (Fase 1/1.1/1.2). Estilo y
helpers (`_fila`, `por_sku` vía `generar_torres_candidatas`) tomados de
`tests/test_packing_bloques.py` para no reinventar el patrón."""
import pandas as pd

import config
import src.global_rescue as global_rescue_module
from src.packing_bloques import _empacar_n_pallets
from src.torres import generar_torres_candidatas
from src.validacion_v5 import validar_pallet_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_cama=None, cd="BK31", nivel=None, categoria=None):
    fila = {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }
    if cajas_cama is not None:
        fila["Cajas_Cama_Efectivo"] = cajas_cama
    if nivel is not None:
        fila["Nivel_Categoria"] = nivel
    if categoria is not None:
        fila["Categoria_Normalizada"] = categoria
    return fila


def _por_sku_desde_df(df):
    candidatas = generar_torres_candidatas(df, config.ALTURA_PRODUCTO_MAX)
    por_sku: dict = {}
    for c in candidatas:
        por_sku.setdefault(c.sku, []).append(c)
    return por_sku


def test_global_rescue_no_se_activa_si_capas_anteriores_resuelven_todo(monkeypatch):
    """[TEST 1] Demanda chica y cómoda -el baseline/backtracking normal ya
    coloca el 100% antes de llegar a Rescue V6.02, así que ni siquiera se
    entra al bloque `if sin_colocar_final:` que envuelve TODAS las capas de
    reparación (Rescue/Repair/Exact/Global). Global Rescue NUNCA debe
    invocarse -verificado dos veces: (a) un espía en `global_rescue`
    confirma 0 llamadas, (b) no aparece `global_rescue_stats` en la
    metadata del resultado."""
    llamadas = []

    def _espia(*_args, **_kwargs):
        llamadas.append(1)
        raise AssertionError("global_rescue no debería invocarse si las capas anteriores ya resolvieron el 100%")

    monkeypatch.setattr(global_rescue_module, "global_rescue", _espia)

    df = pd.DataFrame([_fila("FACIL", 20, 20, 20.0, 5, cajas_cama=20, nivel=6, categoria="NABs")])
    por_sku = _por_sku_desde_df(df)
    pendientes = {"FACIL": 5}

    pallets, sin_colocar = _empacar_n_pallets(
        dict(pendientes), por_sku, {"FACIL": 20}, {"FACIL": 6}, {}, "BK31", [0], 1,
    )

    assert llamadas == []
    assert sin_colocar == {}
    assert sum(t.cantidad for p in pallets for t in p.torres) == 5
    assert "global_rescue_stats" not in pallets[-1].metadata
    assert validar_pallet_v5(pallets[-1]) == []


def test_global_rescue_se_activa_si_capas_anteriores_dejan_faltantes():
    """[TEST 2] Mezcla de un SKU perfectamente colocable (DISPONIBLE) con
    uno geométricamente imposible en cualquier pallet (BLOQUEADO,
    footprint mayor que el pallet entero) -baseline, backtracking, LNS,
    Rescue V6.02, Repair V6.04 y Exact Local Repair fallan TODOS en
    BLOQUEADO por construcción (ninguno puede inventar espacio donde no lo
    hay), así que `sin_colocar_final` sigue sin estar vacío al llegar al
    final del pipeline -Global Rescue SÍ debe activarse. No se monkeypatea
    nada acá: es el motor real de punta a punta, la aserción es sobre la
    metadata que el wiring deja (`stats_global["activado"]`), no sobre si
    logra colocar más (eso es responsabilidad del motor de búsqueda, no
    del wiring que este test cubre)."""
    df = pd.DataFrame([
        _fila("DISPONIBLE", 20, 20, 20.0, 5, cajas_cama=20, nivel=6, categoria="NABs"),
        _fila("BLOQUEADO", 500, 500, 20.0, 1, cajas_cama=1, nivel=6, categoria="NABs"),
    ])
    por_sku = _por_sku_desde_df(df)
    pendientes = {"DISPONIBLE": 5, "BLOQUEADO": 1}

    pallets, sin_colocar = _empacar_n_pallets(
        dict(pendientes), por_sku, {"DISPONIBLE": 20, "BLOQUEADO": 1}, {"DISPONIBLE": 6, "BLOQUEADO": 6}, {},
        "BK31", [0], 1,
    )

    stats_global = pallets[-1].metadata.get("global_rescue_stats")
    assert stats_global is not None  # el wiring SÍ llegó a invocar Global Rescue
    assert stats_global["activado"] is True
    assert sin_colocar.get("BLOQUEADO", 0) == 1  # nunca se pierde en silencio, ni se "resuelve" lo imposible
    assert sum(t.cantidad for p in pallets for t in p.torres if t.sku == "DISPONIBLE") == 5
    for p in pallets:
        assert validar_pallet_v5(p) == []


def test_pipeline_conserva_incumbent_si_global_rescue_empeora(monkeypatch):
    """[TEST 3] Mismo escenario DISPONIBLE+BLOQUEADO de TEST 2, pero acá se
    fuerza (monkeypatch) a que Global Rescue devuelva una solución
    deliberadamente PEOR que el incumbent que ya traía el pipeline (0 cajas
    colocadas, TODA la demanda como faltante, en vez de DISPONIBLE 5/5
    completo) -el fallback obligatorio debe rechazarla y devolver el
    incumbent de antes de entrar a Global Rescue, sin tocar nada."""
    df = pd.DataFrame([
        _fila("DISPONIBLE", 20, 20, 20.0, 5, cajas_cama=20, nivel=6, categoria="NABs"),
        _fila("BLOQUEADO", 500, 500, 20.0, 1, cajas_cama=1, nivel=6, categoria="NABs"),
    ])
    por_sku = _por_sku_desde_df(df)
    pendientes = {"DISPONIBLE": 5, "BLOQUEADO": 1}

    def _global_rescue_peor(pallets, sin_colocar, por_sku, *_args, **_kwargs):
        # Devuelve 0 pallets y TODA la demanda como faltante -estrictamente
        # peor que cualquier incumbent que ya haya colocado algo.
        demanda_total = dict(sin_colocar)
        for pallet in pallets:
            for torre in pallet.torres:
                demanda_total[torre.sku] = demanda_total.get(torre.sku, 0) + torre.cantidad
        stats = {"activado": True, "motivo_stop": "estancado", "mejor_colocado": 0, "por_sku": {}}
        return [], demanda_total, stats

    import src.packing_bloques as packing_bloques_module
    monkeypatch.setattr(global_rescue_module, "global_rescue", _global_rescue_peor)

    pallets_antes, sin_colocar_antes = packing_bloques_module._empacar_n_pallets(
        dict(pendientes), por_sku, {"DISPONIBLE": 20, "BLOQUEADO": 1}, {"DISPONIBLE": 6, "BLOQUEADO": 6}, {},
        "BK31", [0], 1,
    )

    ids_esperados = {p.id for p in pallets_antes}
    total_esperado = sum(t.cantidad for p in pallets_antes for t in p.torres)
    assert total_esperado == 5  # confirma la premisa: el incumbent SÍ tenía algo colocado

    stats_global = pallets_antes[-1].metadata.get("global_rescue_stats")
    assert stats_global is not None  # sí se invocó (y se rechazó)
    assert stats_global["mejor_colocado"] == 0  # confirma que lo devuelto por el mock era peor

    assert {p.id for p in pallets_antes} == ids_esperados  # el incumbent NO fue reemplazado por pallets vacíos
    assert sum(t.cantidad for p in pallets_antes for t in p.torres) == total_esperado
    assert sin_colocar_antes.get("BLOQUEADO", 0) == 1
    assert sin_colocar_antes.get("DISPONIBLE", 0) == 0  # sigue completo, no se perdió por el resultado peor
    for p in pallets_antes:
        assert validar_pallet_v5(p) == []
