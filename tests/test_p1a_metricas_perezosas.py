"""[V6.13-P1A] `_restaurar_estado_pallets(diferir_metricas=True)` / `_resolver_pallets_backtracking(metricas_perezosas=True)`.

Contrato: el estado que SALE del DFS/LNS con métricas perezosas es idéntico, bit a bit, al del camino ansioso de siempre (torres, libres,
colocados, pendientes, nodos y las cuatro métricas del pallet: `altura_final`, `peso_estimado`, `ocupacion_xy`, `volumen_utilizado`) y
mientras las métricas están diferidas NADA las lee dentro de la búsqueda (pallet "envenenado": leerlas levanta AssertionError)."""
import pytest

import src.packing_bloques as pb
from models import PalletV5
from src.packing_bloques import (
    _altura_presupuesto,
    _lns_mejorar_pallets,
    _recalcular_metricas_pallet,
    _resolver_pallets_backtracking,
    _restaurar_estado_pallets,
    _snapshot_estado_pallets,
)
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate

PRESUPUESTO = _altura_presupuesto()
METRICAS = ("altura_final", "peso_estimado", "ocupacion_xy", "volumen_utilizado")


class _PalletVenenoso(PalletV5):
    """Leer una métrica 'envenenada' levanta; escribirla la desenvenena."""

    def __getattribute__(self, name):
        if name in METRICAS and name in object.__getattribute__(self, "__dict__").get("_veneno", ()):
            raise AssertionError(f"lectura de {name} con métricas diferidas")
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if name in METRICAS:
            self.__dict__.get("_veneno", set()).discard(name)
        super().__setattr__(name, value)


def _cand(sku, largo, ancho, alto, cantidad_disponible, peso):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, cantidad_disponible, peso)


def _estado_inicial(n_pallets, clase=PalletV5):
    construcciones, colocados = [], []
    for i in range(n_pallets):
        construcciones.append(_PalletEnConstruccion(pallet=clase(id=f"PV5-TEST-{i:03d}", cd="TEST")))
        colocados.append({})
    return construcciones, colocados


def _escenario(n_pallets):
    # pesos "feos" para que cualquier diferencia de orden de suma float se note
    por_sku = {
        "A": [_cand("A", 40, 30, 20, 60, 0.1)],
        "B": [_cand("B", 20, 15, 12, 90, 0.37)],
        "C": [_cand("C", 30, 40, 15, 40, 1.13)],
    }
    return por_sku, {"A": 60, "B": 90, "C": 40}


def _foto(construcciones, colocados, pendientes):
    return (
        [
            (
                [repr(t) for t in pc.pallet.torres], [repr(c) for c in pc.libres],
                *(getattr(pc.pallet, m) for m in METRICAS), pc.metricas_pendientes,
            )
            for pc in construcciones
        ],
        [dict(d) for d in colocados], dict(pendientes),
    )


def _envenenar_tras_restore_diferido(monkeypatch):
    original = pb._restaurar_estado_pallets
    vistos = {"diferidos": 0}

    def _espia(construcciones, colocados, pendientes, snapshot, diferir_metricas=False):
        original(construcciones, colocados, pendientes, snapshot, diferir_metricas=diferir_metricas)
        if diferir_metricas:
            vistos["diferidos"] += 1
            for pc in construcciones:
                pc.pallet.__dict__["_veneno"] = set(METRICAS)

    monkeypatch.setattr(pb, "_restaurar_estado_pallets", _espia)
    return vistos


@pytest.mark.parametrize("n_pallets,max_nodos", [(1, 200), (2, 150), (3, 120)])
def test_dfs_perezoso_identico_al_ansioso_y_sin_lecturas_intermedias(monkeypatch, n_pallets, max_nodos):
    por_sku, pendientes_base = _escenario(n_pallets)

    def _correr(perezoso, clase):
        construcciones, colocados = _estado_inicial(n_pallets, clase)
        pendientes = dict(pendientes_base)
        info = {}
        total = _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, n_pallets,
            max_nodos=max_nodos, info_salida=info, metricas_perezosas=perezoso,
        )
        return total, info, _foto(construcciones, colocados, pendientes)

    ansioso = _correr(False, PalletV5)
    vistos = _envenenar_tras_restore_diferido(monkeypatch)
    perezoso = _correr(True, _PalletVenenoso)  # si algo lee una métrica diferida, levanta
    assert vistos["diferidos"] > 0
    assert perezoso == ansioso
    assert all(not pend for *_, pend in perezoso[2][0]) is True  # ningún pallet sale con métricas pendientes


def test_dfs_ansioso_por_defecto_no_difiere_nada(monkeypatch):
    por_sku, pendientes = _escenario(2)
    visto = []
    original = pb._restaurar_estado_pallets
    monkeypatch.setattr(
        pb, "_restaurar_estado_pallets",
        lambda *a, **k: (visto.append(k.get("diferir_metricas", False)), original(*a, **k))[1],
    )
    construcciones, colocados = _estado_inicial(2)
    _resolver_pallets_backtracking(construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 2, max_nodos=40)
    assert visto and not any(visto)


def test_metricas_finales_son_las_de_recalcular_desde_cero(monkeypatch):
    por_sku, pendientes = _escenario(2)
    construcciones, colocados = _estado_inicial(2)
    _resolver_pallets_backtracking(
        construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 2, max_nodos=150, metricas_perezosas=True,
    )
    for pc in construcciones:
        actuales = tuple(getattr(pc.pallet, m) for m in METRICAS)
        _recalcular_metricas_pallet(pc.pallet)
        assert actuales == tuple(getattr(pc.pallet, m) for m in METRICAS)


def test_colocar_sobre_pallet_con_restore_diferido_da_el_mismo_peso_que_tras_restore_ansioso():
    por_sku, pendientes_base = _escenario(1)
    cand = por_sku["B"][0]

    def _correr(diferir):
        construcciones, colocados = _estado_inicial(1)
        pc = construcciones[0]
        for i in range(3):  # 3 torres de pesos distintos para que la suma float dependa del orden
            idx = pc.mejor_ajuste(por_sku["ABC"[i]][0], 2)[0]
            pc.colocar(por_sku["ABC"[i]][0], 2, idx)
        snap = _snapshot_estado_pallets(construcciones, colocados, dict(pendientes_base))
        idx = pc.mejor_ajuste(cand, 3)[0]
        pc.colocar(cand, 3, idx)
        _restaurar_estado_pallets(construcciones, colocados, dict(pendientes_base), snap, diferir_metricas=diferir)
        idx = pc.mejor_ajuste(cand, 4)[0]
        pc.colocar(cand, 4, idx)
        return tuple(getattr(pc.pallet, m) for m in METRICAS), pc.metricas_pendientes

    assert _correr(True) == _correr(False)
    assert _correr(True)[1] is False


def test_restore_diferido_marca_pendiente_y_el_ansioso_lo_limpia():
    por_sku, pendientes = _escenario(1)
    construcciones, colocados = _estado_inicial(1)
    pc = construcciones[0]
    snap = _snapshot_estado_pallets(construcciones, colocados, pendientes)
    pc.colocar(por_sku["A"][0], 2, pc.mejor_ajuste(por_sku["A"][0], 2)[0])
    _restaurar_estado_pallets(construcciones, colocados, pendientes, snap, diferir_metricas=True)
    assert pc.metricas_pendientes is True and pc.pallet.torres == []
    _restaurar_estado_pallets(construcciones, colocados, pendientes, snap)
    assert pc.metricas_pendientes is False
    assert tuple(getattr(pc.pallet, m) for m in METRICAS) == (0.0, 0.0, 0.0, 0.0)


def test_lns_perezoso_identico_al_ansioso(monkeypatch):
    por_sku, pendientes_base = _escenario(2)

    def _correr(perezoso, clase):
        construcciones, colocados = _estado_inicial(2, clase)
        pendientes = dict(pendientes_base)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 2, max_nodos=10,
        )
        info = {}
        total = _lns_mejorar_pallets(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 2, semilla="p1a",
            max_nodos_reconstruccion=60, max_iteraciones=6, info_salida=info, metricas_perezosas=perezoso,
        )
        return total, info, _foto(construcciones, colocados, pendientes)

    ansioso = _correr(False, PalletV5)
    vistos = _envenenar_tras_restore_diferido(monkeypatch)
    perezoso = _correr(True, _PalletVenenoso)
    assert vistos["diferidos"] > 0
    assert perezoso == ansioso


@pytest.mark.parametrize("reloj_trabajo,debe_diferir", [(True, True), (False, False)])
def test_reloj_de_trabajo_activa_el_restore_diferido_y_el_de_cpu_no(monkeypatch, reloj_trabajo, debe_diferir):
    """Rescue/Repair con budget de NODOS (`MedidorTrabajo`) difieren; con `process_time` (deadline de CPU) quedan ansiosos."""
    import time

    from src.medidor_trabajo import MedidorTrabajo

    por_sku, pendientes_base = _escenario(2)
    original = pb._restaurar_estado_pallets
    llamadas = []
    monkeypatch.setattr(
        pb, "_restaurar_estado_pallets",
        lambda *a, **k: (llamadas.append(k.get("diferir_metricas", False)), original(*a, **k))[1],
    )

    def _correr(reloj):
        construcciones, colocados = _estado_inicial(2)
        pendientes = dict(pendientes_base)
        _resolver_pallets_backtracking(
            construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO, 2, max_nodos=80, reloj=reloj,
        )
        return _foto(construcciones, colocados, pendientes)

    foto = _correr(MedidorTrabajo() if reloj_trabajo else time.process_time)
    assert any(llamadas) is debe_diferir
    assert foto == _correr(time.process_time)  # mismo estado de salida en ambos modos


# --- memo exacto de `_area_union_xy` ------------------------------------------------------------------------------------------------

def _torres_al_azar(rng, n):
    from models import Torre

    torres = []
    for _ in range(n):
        x = rng.choice([0, 7.5, 10, 12.25, 20, 31.3, 40, 55.55, 60, 80])
        y = rng.choice([0, 5, 10.1, 25, 33.3, 50, 62.5, 75])
        largo = rng.choice([10, 15.5, 20, 25, 30, 40])
        ancho = rng.choice([8, 12.5, 15, 20, 30])
        torres.append(Torre("S", "CD", x, y, largo, ancho, 10.0, 1, 0.5, "L×A", "t", z=rng.choice([0.0, 10.0, 20.0])))
    return torres


def test_memo_area_union_devuelve_exactamente_el_mismo_float_y_no_depende_del_orden_ni_de_duplicados():
    import random

    import src.packing_columnar as pcol

    rng = random.Random(20261030)
    assert pcol._AREA_UNION_MEMO_VAR.get() is None  # desactivado por defecto
    for _ in range(400):
        torres = _torres_al_azar(rng, rng.randint(0, 14))
        esperado = pcol._area_union_xy_calcular(torres)
        assert pcol._area_union_xy(torres) == esperado
        with pcol._area_union_memoizada():
            assert pcol._area_union_xy(torres) == esperado  # miss
            barajadas = torres[:]
            rng.shuffle(barajadas)
            assert pcol._area_union_xy(barajadas + torres[:2]) == esperado  # hit con otro orden y duplicados
            assert pcol._area_union_xy(torres) == esperado
        assert pcol._AREA_UNION_MEMO_VAR.get() is None  # se descarta al salir


def test_memo_area_union_reentrante_y_con_tope(monkeypatch):
    import src.packing_columnar as pcol

    with pcol._area_union_memoizada():
        memo = pcol._AREA_UNION_MEMO_VAR.get()
        with pcol._area_union_memoizada():
            assert pcol._AREA_UNION_MEMO_VAR.get() is memo  # reutiliza el del contexto externo
        assert pcol._AREA_UNION_MEMO_VAR.get() is memo  # salir del interno no lo descarta
    assert pcol._AREA_UNION_MEMO_VAR.get() is None
    monkeypatch.setattr(pcol, "_AREA_UNION_MEMO_MAX", 3)
    import random

    rng = random.Random(1)
    with pcol._area_union_memoizada():
        for _ in range(50):
            torres = _torres_al_azar(rng, 5)
            assert pcol._area_union_xy(torres) == pcol._area_union_xy_calcular(torres)  # lleno => sigue exacto
        assert len(pcol._AREA_UNION_MEMO_VAR.get()) <= 3


def test_memo_solo_se_activa_en_busquedas_acotadas_por_trabajo(monkeypatch):
    import time

    import src.packing_columnar as pcol
    from src.medidor_trabajo import MedidorTrabajo

    vistos = []
    original = pcol._area_union_xy_calcular
    monkeypatch.setattr(pcol, "_area_union_xy_calcular", lambda torres: (vistos.append(pcol._AREA_UNION_MEMO_VAR.get() is not None), original(torres))[1])
    por_sku, pendientes_base = _escenario(2)

    def _correr(**kw):
        vistos.clear()
        construcciones, colocados = _estado_inicial(2)
        _resolver_pallets_backtracking(construcciones, colocados, dict(pendientes_base), por_sku, {}, {}, {}, PRESUPUESTO, 2, max_nodos=60, **kw)
        return list(vistos)

    assert not any(_correr(reloj=time.process_time))  # deadline de CPU: sin memo (mismo costo de siempre)
    assert any(_correr(reloj=MedidorTrabajo()))       # budget de nodos: con memo
    assert any(_correr(metricas_perezosas=True))
