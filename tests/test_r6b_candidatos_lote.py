"""[V6.13-R6B -"Bit-identical geometry performance: `_candidatos_lote`"] `_candidatos_lote_rapido` debe devolver EXACTAMENTE lo mismo que la referencia
(`_candidatos_lote_referencia`): mismos candidatos, mismo orden, mismos desempates, mismos objetos `TorreCandidate`, mismos floats. Y solo debe usarse
en las rutas acotadas por trabajo del alcance de R6-B (fallback sin reserva y Rescue profundo de N fijo): el DFS inicial, los sondeos OPEN, Repair
(N fijo y OPEN), Exact y Global conservan la referencia. Tests sintéticos y rápidos (la validación con casos reales vive en el informe)."""
import inspect
import math
import random
import struct
import textwrap
import threading

import pytest

import config
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.packing_columnar as pcol
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.medidor_trabajo import MedidorTrabajo
from src.torres import TorreCandidate, crear_torre
from src.packing_columnar import _CuboidLibre

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO

# ------------------------------------------------------------------------------------------------------------------- comparación exacta


def _bits(x):
    """Representación exacta (floats a 64 bits) de una clave/valor anidado."""
    if isinstance(x, float):
        return struct.pack("<d", x)
    if isinstance(x, (tuple, list)):
        return tuple(_bits(i) for i in x)
    return x


def _diferencia(esperado, obtenido):
    """None si son idénticos en contenido, orden, desempates, bits de floats e IDENTIDAD de los `TorreCandidate`; si no, un texto que dice dónde."""
    if len(esperado) != len(obtenido):
        return f"largo {len(esperado)} != {len(obtenido)}"
    for i, (e, o) in enumerate(zip(esperado, obtenido)):
        if _bits(e[0]) != _bits(o[0]):
            return f"[{i}] clave {e[0]!r} != {o[0]!r}"
        if (e[1], e[2], e[3], e[5], e[6]) != (o[1], o[2], o[3], o[5], o[6]):
            return f"[{i}] campos {e[1:4]}+{e[5:]} != {o[1:4]}+{o[5:]}"
        if type(e[1]) is not type(o[1]) or type(e[6]) is not type(o[6]):
            return f"[{i}] tipos"
        if e[4] is not o[4]:
            return f"[{i}] otro objeto TorreCandidate"
    return None


# ------------------------------------------------------------------------------------------------------------------- escenarios sintéticos

_HUELLAS = [(60.0, 50.0), (40.0, 30.0), (30.0, 20.0), (20.0, 15.0), (41.5, 31.9), (120.0, 100.0), (50.0, 40.0), (60.0, 40.0), (40.0, 30.0)]
_ALTOS = [10.0, 12.0, 15.0, 20.0, 20.0, 25.0, 30.0]
_JITTER = [0.0, 0.0, 0.0, 5e-7, -5e-7, 2e-6]


def _escenario(rng):
    n = rng.randint(1, 4)
    skus = [f"S{i}" for i in range(rng.randint(2, 5))]
    por_sku, pend, cap, niv, tope = {}, {}, {}, {}, {}
    for sku in skus:
        largo, ancho = rng.choice(_HUELLAS)
        largo, ancho = largo + rng.choice(_JITTER), ancho + rng.choice(_JITTER)
        alto = rng.choice(_ALTOS) + rng.choice(_JITTER)
        cands = [TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, 400, 1.0)]
        if rng.random() < 0.7:
            cands.append(TorreCandidate(sku, "CD", "A×L", ancho, largo, alto, 20, 400, 1.0))
        por_sku[sku] = cands
        pend[sku] = rng.randint(3, 40)
        if rng.random() < 0.6:
            cap[sku] = rng.choice([4, 6, 8, 12])
        niv[sku] = rng.choice([1, 1, 2, 6])
        if rng.random() < 0.4:
            tope[sku] = rng.choice([10, 20, 40])
    return n, pend, por_sku, cap, niv, tope


def _armar(rng):
    n, pend, por_sku, cap, niv, tope = _escenario(rng)
    cons = [pcol._PalletEnConstruccion(pallet=PalletV5(id=f"P{i}", cd="CD")) for i in range(n)]
    return cons, [{} for _ in cons], pend, por_sku, cap, niv, tope, n


def _dfs(escenario, nodos=24, **kw):
    cons, colocados, pend, por_sku, cap, niv, tope, n = escenario
    info = {}
    total = pb._resolver_pallets_backtracking(cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n, max_nodos=nodos, info_salida=info, **kw)
    firma = [(t.sku, t.x, t.y, t.z, t.cantidad) for c in cons for t in c.pallet.torres]
    return total, info.get("nodos"), info.get("motivo_parada"), firma


class _Recorrido:
    """Corre el DFS sobre muchos escenarios y, ANTES de cada `_candidatos_lote` real, compara la variante rápida (candidata) con la referencia."""

    def __init__(self, monkeypatch, candidata=None):
        self.llamadas = 0
        self.diferencias = []
        self.con_frontera = self.con_necesita = self.multi_pallet = 0
        candidata = candidata or (lambda *a: pb._candidatos_lote_rapido(*a))

        def comparar(*a):
            self.llamadas += 1
            esperado = pb._candidatos_lote_referencia(*a)
            obtenido = candidata(*a)
            d = _diferencia(esperado, obtenido)
            if d is not None:
                self.diferencias.append(d)
            self.con_necesita += any(c[1] for c in esperado)
            self.con_frontera += len(esperado) > pb.COMBINACION_PALLETS_SHORTLIST_K
            self.multi_pallet += a[8] > 1
            return esperado

        monkeypatch.setattr(pb, "_candidatos_lote", comparar)

    def correr(self, semillas):
        for s in semillas:
            with pb._candidatos_rapido():  # la caché por ejecución solo existe dentro del contexto: así se ejercita en cada comparación
                _dfs(_armar(random.Random(s)))


def _correr(monkeypatch, candidata=None, semillas=range(300), shortlist_k=None, opciones=None):
    if shortlist_k is not None:  # K=1: casi todo el árbol sale por la frontera -> ejercita los desempates de `candidatos_frontera`
        monkeypatch.setattr(pb, "COMBINACION_PALLETS_SHORTLIST_K", shortlist_k)
    if opciones is not None:
        monkeypatch.setattr(pb, "COMBINACION_PALLETS_OPCIONES_POR_SKU", opciones)
    r = _Recorrido(monkeypatch, candidata)
    r.correr(semillas)
    return r


# ------------------------------------------------------------------------------------------------------------------- casos dirigidos (bordes exactos)


def _vacios(n):
    cons = [pcol._PalletEnConstruccion(pallet=PalletV5(id=f"P{i}", cd="CD")) for i in range(n)]
    return cons, [{} for _ in cons]


def _cand(sku, largo, ancho, alto, ori="L×A"):
    return TorreCandidate(sku, "CD", ori, largo, ancho, alto, 20, 400, 1.0)


def _dirigidos():
    """[(nombre, args)] -casos donde una tolerancia, un desempate o la caché por huella deciden el resultado."""
    casos = []
    cons0, _ = _vacios(1)
    c0 = cons0[0].libres[0]
    d = 5e-7  # dentro de TOL (1e-6)
    ovr = config.TOLERANCIA_OVERHANG_CM
    huellas = {
        "ancho_justo_por_TOL": (c0.w, c0.h + d, 10.0),
        "largo_justo_por_TOL": (c0.w + d, c0.h, 10.0),
        "alto_justo_por_TOL": (60.0, 50.0, c0.d + d),
    }
    for nombre, (largo, ancho, alto) in huellas.items():
        for n in (1, 2):
            cons, col = _vacios(n)
            casos.append((f"{nombre}/n={n}", (cons, col, {"A": 5}, {"A": [_cand("A", largo, ancho, alto)]}, {}, {"A": 1}, {}, PRESUPUESTO, n)))

    # misma huella, distinto alto, en varios pallets. A (alto 10) entra en P (d=12, z=0, el de menor clave); B (alto 15) NO entra en P pero sí en Q
    # (z=20). Con un prefiltro viejo reusado para B, P "admitiría" a B, ganaría la clave y su cantidad (0) descartaría la opción: se perdería B.
    cons, col = _vacios(3)
    for pc in cons:
        pc.libres = [_CuboidLibre(0.0, 0.0, 0.0, 60.0, 50.0, 12.0), _CuboidLibre(0.0, 0.0, 20.0, 60.0, 50.0, 100.0)]
    casos.append(("misma_huella_distinto_alto", (cons, col, {"A": 5, "B": 5}, {"A": [_cand("A", 60.0, 50.0, 10.0)], "B": [_cand("B", 60.0, 50.0, 15.0)]},
                  {}, {"A": 6, "B": 6}, {}, PRESUPUESTO, 3)))

    # empate de `sobra` en la frontera entre SKUs de igual huella: gana el que continúa su torre (X); `Y`/`Z` van antes en `pendientes`. Cada SKU
    # tiene una torre con capacidad de sobra (no `necesita` columna nueva) para que el cuboide solo entre por la frontera (con shortlist 0).
    cons, col = _vacios(1)
    pal = cons[0].pallet
    pal.torres.append(crear_torre(_cand("X", 60.0, 50.0, 20.0), x=-2.0, y=-2.0, z=0.0, cantidad=1))
    pal.torres.append(crear_torre(_cand("Y", 60.0, 50.0, 20.0), x=60.0, y=-2.0, z=0.0, cantidad=1))
    pal.torres.append(crear_torre(_cand("Z", 60.0, 50.0, 20.0), x=60.0, y=50.0, z=0.0, cantidad=1))
    cons[0].libres = [_CuboidLibre(-2.0, -2.0, 20.0, 60.0, 50.0, 50.0)]
    casos.append(("empate_de_sobra_en_frontera", (cons, col, {"Y": 1, "Z": 1, "X": 1},
                  {"X": [_cand("X", 60.0, 50.0, 20.0)], "Y": [_cand("Y", 60.0, 50.0, 20.0)], "Z": [_cand("Z", 60.0, 50.0, 20.0)]},
                  {}, {"X": 6, "Y": 6, "Z": 6}, {}, PRESUPUESTO, 1)))

    # soportes: la torre de abajo (L, nivel 6, techo en 10) NO es soporte del cuboide en z=30; el soporte real (M, nivel 1, techo 30) no viola
    cons, col = _vacios(1)
    pal = cons[0].pallet
    pal.torres.append(crear_torre(_cand("L", 40.0, 30.0, 10.0), x=0.0, y=0.0, z=0.0, cantidad=1))
    pal.torres.append(crear_torre(_cand("M", 40.0, 30.0, 20.0), x=0.0, y=0.0, z=10.0, cantidad=1))
    cons[0].libres = [_CuboidLibre(0.0, 0.0, 30.0, 40.0, 30.0, 50.0)]
    casos.append(("soporte_real_vs_torre_de_abajo", (cons, col, {"N1": 3}, {"N1": [_cand("N1", 40.0, 30.0, 10.0)]},
                  {}, {"L": 6, "M": 1, "N1": 1}, {}, PRESUPUESTO, 1)))
    return casos


def _diferencias_dirigidas(candidata=None, shortlist_k=None):
    candidata = candidata or pb._candidatos_lote_rapido
    resultados = []
    k0 = pb.COMBINACION_PALLETS_SHORTLIST_K
    try:
        for k in ((shortlist_k,) if shortlist_k is not None else (k0, 1, 0)):
            pb.COMBINACION_PALLETS_SHORTLIST_K = k
            for nombre, args in _dirigidos():
                esperado = pb._candidatos_lote_referencia(*args)
                with pb._candidatos_rapido():
                    obtenido = candidata(*args)
                d = _diferencia(esperado, obtenido)
                resultados.append((nombre, k, d, len(esperado)))
    finally:
        pb.COMBINACION_PALLETS_SHORTLIST_K = k0
    return resultados


def _admision_dirigida():
    """Terna (cuboide, candidato, torres) en los bordes de TOL / overhang / margen: `_admite_rapido` debe dar lo mismo que `_cuboide_admite_candidato`."""
    d, ovr = 5e-7, config.TOLERANCIA_OVERHANG_CM
    geo = (config.PALLET_LARGO + config.SOBRESALIENTE_MAX_CM + pb.TOL, config.PALLET_ANCHO + config.SOBRESALIENTE_MAX_CM + pb.TOL, pb.TOLERANCIA_ALTURA_CAMA_CM + pb.TOL)
    pal = PalletV5(id="P", cd="CD")
    pal.torres.append(crear_torre(_cand("A", 40.0, 30.0, 20.0), x=0.0, y=0.0, z=0.0, cantidad=1))
    pc = pcol._PalletEnConstruccion(pallet=pal)
    cuboides = [_CuboidLibre(0.0, 0.0, 0.0, 40.0, 30.0, 100.0), _CuboidLibre(0.0, 0.0, 20.0, 40.0, 30.0, 100.0), _CuboidLibre(80.0, 60.0, 0.0, 40.0, 30.0, 100.0),
                _CuboidLibre(-2.0, -2.0, 0.0, 40.0, 30.0, 100.0)]
    dif = []
    for c in cuboides:
        pc.libres = [c]
        ent = pb._EntradaLibres([c])
        ent.cub = pb._cub_de(ent.libres, config.TOLERANCIA_OVERHANG_CM, -config.SOBRESALIENTE_MAX_CM - pb.TOL)
        v = pb._VistaPallet(pc, ent)
        for dl in (0.0, d, -d, 1.5 * pb.TOL, ovr, ovr + d, ovr + 1.5 * pb.TOL, ovr - d):
            for da in (0.0, d, ovr, ovr + d, ovr + 1.5 * pb.TOL):
                for dh in (0.0, d, 80.0, 80.0 + d, 80.0 + 1.5 * pb.TOL):
                    cand = _cand("B", 40.0 + dl, 30.0 + da, 20.0 + dh - 20.0 if dh >= 80.0 else 10.0 + dh)
                    for tope in (None, 1):
                        esperado = pb._cuboide_admite_candidato(pal, c, cand, tope, 1, {"A": 6, "B": 1})
                        obtenido = pb._admite_rapido(v, ent.cub[0], cand, tope, 1, {"A": 6, "B": 1}, geo)
                        if esperado is not obtenido:
                            dif.append((c, cand.largo, cand.ancho, cand.alto_caja, tope, esperado, obtenido))
    return dif


def test_la_admision_rapida_es_igual_en_los_bordes_de_tolerancia_overhang_y_margen():
    assert _admision_dirigida() == []


def test_los_casos_dirigidos_de_borde_son_identicos_y_de_verdad_admiten_candidatos():
    res = _diferencias_dirigidas()
    assert all(d is None for _, _, d, _ in res), [r for r in res if r[2] is not None]
    admitidos = {n.split("/")[0] for n, _, _, largo in res if largo > 0}
    assert {"ancho_justo_por_TOL", "largo_justo_por_TOL", "alto_justo_por_TOL",
            "misma_huella_distinto_alto", "empate_de_sobra_en_frontera", "soporte_real_vs_torre_de_abajo"} <= admitidos


# ------------------------------------------------------------------------------------------------------------------- equivalencia


def test_rapido_igual_a_referencia_en_miles_de_estados_reales_de_dfs(monkeypatch):
    r = _correr(monkeypatch)
    assert r.llamadas > 3000
    assert r.diferencias == [], r.diferencias[:3]


@pytest.mark.parametrize("k,opciones", [(1, 1), (2, 2), (8, 3), (3, 1)])
def test_igual_a_la_referencia_con_otros_topes_de_shortlist_y_de_opciones_por_sku(monkeypatch, k, opciones):
    r = _correr(monkeypatch, semillas=range(120), shortlist_k=k, opciones=opciones)
    assert r.llamadas > 1000 and r.diferencias == [], r.diferencias[:3]


def test_el_corpus_ejercita_de_verdad_varios_pallets_candidatos_de_frontera_y_candidatos_que_necesitan_columna(monkeypatch):
    r = _correr(monkeypatch)
    assert r.multi_pallet > 500 and r.con_frontera > 50 and r.con_necesita > 50


def test_la_admision_rapida_es_igual_a_cuboide_admite_candidato_en_cada_terna(monkeypatch):
    """Cada (pallet, cuboide, candidato) de los estados del DFS: la admisión rápida (prefiltro + resto) == la función original."""
    contadores = {"admitidas": 0, "rechazadas": 0}
    geo = (config.PALLET_LARGO + config.SOBRESALIENTE_MAX_CM + pb.TOL, config.PALLET_ANCHO + config.SOBRESALIENTE_MAX_CM + pb.TOL,
           pb.TOLERANCIA_ALTURA_CAMA_CM + pb.TOL)

    def comparar(cons, colocados, pend, por_sku, cap, niv, tope, presupuesto, n):
        for pc in cons[:n]:
            ent = pb._EntradaLibres(list(pc.libres))
            ent.cub = pb._cub_de(ent.libres, config.TOLERANCIA_OVERHANG_CM, -config.SOBRESALIENTE_MAX_CM - pb.TOL)
            v = pb._VistaPallet(pc, ent)
            for sku, cands in por_sku.items():
                for cand in cands:
                    for c, cv in zip(pc.libres, ent.cub):
                        esperado = pb._cuboide_admite_candidato(pc.pallet, c, cand, cap.get(sku), niv.get(sku, config.NIVEL_REMATE), niv)
                        obtenido = pb._admite_rapido(v, cv, cand, cap.get(sku), niv.get(sku, config.NIVEL_REMATE), niv, geo)
                        assert esperado is obtenido
                        contadores["admitidas" if esperado else "rechazadas"] += 1
        return pb._candidatos_lote_referencia(cons, colocados, pend, por_sku, cap, niv, tope, presupuesto, n)

    monkeypatch.setattr(pb, "_candidatos_lote", comparar)
    for s in range(25):
        _dfs(_armar(random.Random(s)))
    assert contadores["admitidas"] > 200 and contadores["rechazadas"] > 2000


def test_el_dfs_completo_da_el_mismo_resultado_con_la_referencia_y_con_la_rapida():
    """La variante rápida GOBIERNA la búsqueda (no solo se compara): nodos, motivo de parada, colocaciones y orden idénticos."""
    for s in range(40):
        esc_a, esc_b = _armar(random.Random(s)), _armar(random.Random(s))
        referencia = _dfs(esc_a, nodos=40)
        with pb._candidatos_rapido():
            rapida = _dfs(esc_b, nodos=40)
        assert referencia == rapida, s
        assert [_bits([(c.x, c.y, c.z, c.w, c.h, c.d) for c in pc.libres]) for pc in esc_a[0]] == \
               [_bits([(c.x, c.y, c.z, c.w, c.h, c.d) for c in pc.libres]) for pc in esc_b[0]]


def _estado_multi(semilla, pallets_min=2):
    esc = _armar(random.Random(semilla))
    while esc[7] < pallets_min:
        esc = _armar(random.Random(random.random()))
    return esc


def test_la_cache_no_cambia_el_resultado_al_repetir_la_llamada_sobre_el_mismo_estado(monkeypatch):
    """Primera llamada = fallo de caché, segunda = acierto, y tras una colocación (lista nueva en UN pallet) solo ese pallet se recalcula."""
    cons, colocados, pend, por_sku, cap, niv, tope, n = _estado_multi(3)
    args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
    with pb._candidatos_rapido():
        entradas = pb._CAND_ESTADO.get().entradas
        assert entradas == {}
        referencia = pb._candidatos_lote_referencia(*args)
        assert _diferencia(referencia, pb._candidatos_lote_rapido(*args)) is None
        n_entradas = len(entradas)
        assert n_entradas >= 1
        assert _diferencia(referencia, pb._candidatos_lote_rapido(*args)) is None
        assert len(entradas) == n_entradas  # acierto: no crece
        cand = next(iter(por_sku.values()))[0]
        if cons[0].pallet.torres == [] and cand.largo <= config.PALLET_LARGO and cand.ancho <= config.PALLET_ANCHO:
            cons[0].colocar(cand, 1, 0)
            colocados[0][cand.sku] = 1
            pend[cand.sku] = max(0, pend[cand.sku] - 1)
            args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
            assert _diferencia(pb._candidatos_lote_referencia(*args), pb._candidatos_lote_rapido(*args)) is None
            assert len(entradas) == n_entradas + 1  # solo el pallet que cambió suma una entrada


def test_con_un_solo_pallet_no_se_usa_la_cache_y_el_resultado_es_el_mismo(monkeypatch):
    esc = _armar(random.Random(11))
    while esc[7] != 1:
        esc = _armar(random.Random(random.random()))
    cons, colocados, pend, por_sku, cap, niv, tope, n = esc
    args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
    with pb._candidatos_rapido():
        assert _diferencia(pb._candidatos_lote_referencia(*args), pb._candidatos_lote_rapido(*args)) is None
        assert pb._CAND_ESTADO.get().entradas == {}


def test_la_cache_tiene_tope_de_entradas_y_con_el_tope_minimo_el_resultado_no_cambia(monkeypatch):
    """Un tope chico vacía la caché seguido: solo cuesta CPU, nunca cambia el resultado. Y la caché nunca supera el tope + las entradas de UNA llamada."""
    monkeypatch.setattr(pb, "_CAND_CACHE_MAX", 3)
    maximo = [0]
    original = pb._candidatos_lote_rapido

    def medir(*a, **k):
        r = original(*a, **k)
        maximo[0] = max(maximo[0], len(pb._CAND_ESTADO.get().entradas))
        return r

    monkeypatch.setattr(pb, "_candidatos_lote_rapido", medir)
    r = _correr(monkeypatch, candidata=lambda *a: pb._candidatos_lote_rapido(*a), semillas=range(60))
    assert r.llamadas > 300 and r.diferencias == [], r.diferencias[:3]
    assert 0 < maximo[0] <= max(3, 8 * 4) + 4  # N <= 4 en el corpus: tope max(3, 8N) + las entradas que agrega la llamada en curso


def test_fuera_del_contexto_una_llamada_directa_a_la_rapida_no_deja_estado_y_da_lo_mismo():
    cons, colocados, pend, por_sku, cap, niv, tope, n = _estado_multi(5)
    args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
    assert pb._CAND_ESTADO.get() is None
    assert _diferencia(pb._candidatos_lote_referencia(*args), pb._candidatos_lote_rapido(*args)) is None
    assert pb._CAND_ESTADO.get() is None


# ------------------------------------------------------------------------------------------------------------------- mutantes


def _mutante(monkeypatch, nombre, cambios):
    """Reemplaza `pb.<nombre>` por una copia con `cambios` [(viejo, nuevo)] aplicados al código fuente; falla si algún `viejo` no existe."""
    fuente = textwrap.dedent(inspect.getsource(getattr(pb, nombre)))
    for viejo, nuevo in cambios:
        assert viejo in fuente, viejo
        fuente = fuente.replace(viejo, nuevo)
    ns = {}
    exec(compile(fuente, f"<mutante {nombre}>", "exec"), pb.__dict__, ns)
    monkeypatch.setattr(pb, nombre, ns[nombre])


def _detecta(monkeypatch, nombre=None, cambios=(), candidata=None, semillas=range(90), dirigidos=True):
    if nombre is not None:
        _mutante(monkeypatch, nombre, cambios)
    if dirigidos and (any(d is not None for _, _, d, _ in _diferencias_dirigidas(candidata)) or _admision_dirigida()):
        return True
    if _correr(monkeypatch, candidata, semillas).diferencias:
        return True
    return bool(_correr(monkeypatch, candidata, range(120), shortlist_k=1).diferencias)


def test_el_chequeo_acepta_la_implementacion_rapida(monkeypatch):
    assert not _detecta(monkeypatch)


@pytest.mark.parametrize("nombre,cambios", [
    # desempate de la frontera: `>` -> `>=` descarta empates reales de `sobra` que ganaban por `mismo_sku_continua`
    ("_candidatos_lote_rapido", [("sobra > mejor_fit[0][0]", "sobra >= mejor_fit[0][0]")]),
    # orden de candidatos/orientaciones dentro de un cuboide: el primero gana, un empate NO reemplaza
    ("_candidatos_lote_rapido", [("clave_op < actual[0]", "clave_op <= actual[0]")]),
    # orden de pallets
    ("_candidatos_lote_rapido", [("for pidx in range(n_pallets):\n            ya_en_pallet", "for pidx in reversed(range(n_pallets)):\n            ya_en_pallet")]),
    # la caché ignora el alto de la huella -> prefiltro viejo para otro candidato
    ("_candidatos_lote_rapido", [("clave_huella = (cand_op.largo, cand_op.ancho, cand_op.alto_caja)", "clave_huella = (cand_op.largo, cand_op.ancho, 0.0)")]),
    # la caché identifica la lista por su largo en vez de por sus cuboides
    ("_candidatos_lote_rapido", [("firma = tuple(map(id, libres))", "firma = (len(libres),)")]),
    # tolerancia float del FIT directo / con overhang / del alto
    ("_cub_de", [("w + TOL, h + TOL, c.d + TOL", "w, h, c.d")]),
    ("_cub_de", [("c.d + TOL", "c.d")]),
    ("_cub_de", [("w + tolerancia + TOL, h + tolerancia + TOL", "w + tolerancia, h + tolerancia")]),
    # nivel: `>` -> `>=` (una caja sobre otra del MISMO nivel pasa a violar)
    ("_admite_resto_rapido", [("nivel_por_sku.get(t.sku, 0) > nivel_sku", "nivel_por_sku.get(t.sku, 0) >= nivel_sku")]),
    # tolerancia de alto de la cama
    ("_candidatos_lote_rapido", [("lim_altura_cama = TOLERANCIA_ALTURA_CAMA_CM + TOL", "lim_altura_cama = TOLERANCIA_ALTURA_CAMA_CM")]),
    # tope de capa: `>=` -> `>`
    ("_admite_resto_rapido", [("v.ya_en_capa(cand.sku, cz) >= tope_capa", "v.ya_en_capa(cand.sku, cz) > tope_capa")]),
    # soportes: cualquier torre por debajo de `z` cuenta como soporte (sin el `abs`)
    ("_VistaPallet", [("abs(t.z + t.altura - z) <= TOL", "(t.z + t.altura - z) <= TOL")]),
])
def test_mutantes_de_la_implementacion_se_detectan(monkeypatch, nombre, cambios):
    assert _detecta(monkeypatch, nombre, cambios, semillas=range(200)), f"mutante no detectado: {cambios}"


def _con_resultado(transformar):
    def candidata(*a):
        return transformar(pb._candidatos_lote_rapido(*a))
    return candidata


def _intercambiar_empatados(lista):
    lista = list(lista)
    for i in range(len(lista) - 1):
        if lista[i][0] == lista[i + 1][0] and lista[i][3:] != lista[i + 1][3:]:
            lista[i], lista[i + 1] = lista[i + 1], lista[i]
            break
    return lista


def _un_ulp(lista):
    lista = list(lista)
    if lista:
        c = lista[0]
        lista[0] = ((math.nextafter(c[0][0], math.inf),) + tuple(c[0][1:]),) + tuple(c[1:])
    return lista


def _otro_objeto(lista):
    lista = list(lista)
    if lista:
        c = lista[0]
        import dataclasses
        lista[0] = c[:4] + (dataclasses.replace(c[4]),) + c[5:]
    return lista


@pytest.mark.parametrize("transformar", [
    lambda r: list(reversed(r)),                  # orden
    _intercambiar_empatados,                      # desempates
    lambda r: list(r[:-1]),                       # candidato perdido
    lambda r: list(r) + list(r[:1]),              # candidato duplicado
    lambda r: [c[:6] + (c[6] + 1,) for c in r],   # cantidad +1
    lambda r: [c[:1] + (not c[1],) + c[2:] for c in r],  # bandera `necesita`
    _un_ulp,                                      # float a 1 ulp
    _otro_objeto,                                 # mismo valor, otro objeto
])
def test_mutantes_de_la_salida_se_detectan_por_la_comparacion_exacta(monkeypatch, transformar):
    assert _detecta(monkeypatch, candidata=_con_resultado(transformar), semillas=range(30))


# ------------------------------------------------------------------------------------------------------------------- despacho y alcance


class _Espia:
    def __init__(self, monkeypatch):
        self.ref = self.rapido = 0
        ref, rapido = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido

        def r(*a, **k):
            self.ref += 1
            return ref(*a, **k)

        def f(*a, **k):
            self.rapido += 1
            return rapido(*a, **k)

        monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
        monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)


def _una_llamada():
    esc = _armar(random.Random(5))
    cons, colocados, pend, por_sku, cap, niv, tope, n = esc
    return pb._candidatos_lote(cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)


def test_por_defecto_se_usa_la_referencia_y_dentro_del_contexto_la_rapida(monkeypatch):
    esp = _Espia(monkeypatch)
    assert pb._CAND_PROFUNDIDAD.get() == 0
    _una_llamada()
    assert esp.ref == 1 and esp.rapido == 0
    with pb._candidatos_rapido():
        _una_llamada()
    assert esp.ref == 1 and esp.rapido == 1


def test_el_contexto_es_reentrante_y_el_anidado_reusa_la_cache_del_externo(monkeypatch):
    cons, colocados, pend, por_sku, cap, niv, tope, n = _estado_multi(2)
    args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None
    with pb._candidatos_rapido():
        assert pb._CAND_PROFUNDIDAD.get() == 1
        externa = pb._CAND_ESTADO.get()
        assert externa is not None
        pb._candidatos_lote_rapido(*args)
        poblada = dict(externa.entradas)
        assert poblada
        with pb._candidatos_rapido():
            assert pb._CAND_PROFUNDIDAD.get() == 2
            assert pb._CAND_ESTADO.get() is externa                 # misma ejecución: reusa la caché, no crea otra
            assert externa.entradas == poblada                      # y conserva lo ya calculado
        assert pb._CAND_PROFUNDIDAD.get() == 1 and pb._CAND_ESTADO.get() is externa
        assert externa.entradas == poblada                          # salir del anidado no vacía la caché del externo
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None


def test_el_cierre_del_contexto_ante_una_excepcion_restaura_el_estado_externo(monkeypatch):
    with pytest.raises(RuntimeError):
        with pb._candidatos_rapido():
            raise RuntimeError("x")
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None
    with pb._candidatos_rapido():
        externa = pb._CAND_ESTADO.get()
        with pytest.raises(RuntimeError):
            with pb._candidatos_rapido():
                assert pb._CAND_PROFUNDIDAD.get() == 2
                raise RuntimeError("y")
        assert pb._CAND_PROFUNDIDAD.get() == 1 and pb._CAND_ESTADO.get() is externa  # el externo sigue activo y con su caché
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None
    assert pb._candidatos_lote is not None
    esp = _Espia(monkeypatch)
    _una_llamada()                                                                    # tras las excepciones la referencia vuelve a ser la de siempre
    assert esp.ref == 1 and esp.rapido == 0


def _dos_hilos(monkeypatch):
    """Mientras el hilo A tiene `_candidatos_rapido()` activo, el hilo B ve profundidad 0, sin caché, y usa la referencia; cuando B abre SU contexto
    obtiene SU caché (otra) y, al cerrarlo (incluso con una excepción), el de A sigue intacto."""
    llamadas = {"A": [], "B": []}
    ref, rapido = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido
    nombre = lambda: threading.current_thread().name  # noqa: E731

    def r(*a, **k):
        llamadas[nombre()].append("ref")
        return ref(*a, **k)

    def f(*a, **k):
        llamadas[nombre()].append("rapido")
        return rapido(*a, **k)

    monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
    monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)
    a_dentro, b_termino = threading.Event(), threading.Event()
    visto, errores = {}, []

    def hilo_a():
        try:
            with pb._candidatos_rapido():
                visto["a_cache"] = pb._CAND_ESTADO.get()
                _una_llamada()                                       # A: rápida
                a_dentro.set()
                assert b_termino.wait(30)
                visto["a_prof_final"] = pb._CAND_PROFUNDIDAD.get()
                visto["a_cache_final"] = pb._CAND_ESTADO.get()
                _una_llamada()                                       # A sigue en rápida tras todo lo que hizo B
        except BaseException as e:  # noqa: BLE001
            errores.append(("A", e))
            a_dentro.set()

    def hilo_b():
        try:
            assert a_dentro.wait(30)
            visto["b_prof_fuera"] = pb._CAND_PROFUNDIDAD.get()
            visto["b_cache_fuera"] = pb._CAND_ESTADO.get()
            _una_llamada()                                           # B, mientras A está dentro: referencia
            with pytest.raises(RuntimeError):
                with pb._candidatos_rapido():
                    visto["b_cache_propia"] = pb._CAND_ESTADO.get()
                    visto["b_prof_dentro"] = pb._CAND_PROFUNDIDAD.get()
                    _una_llamada()                                   # B dentro de SU contexto: rápida
                    raise RuntimeError("b")
            visto["b_prof_despues"] = pb._CAND_PROFUNDIDAD.get()
            _una_llamada()                                           # B tras cerrar el suyo (con excepción): referencia otra vez
        except BaseException as e:  # noqa: BLE001
            errores.append(("B", e))
        finally:
            b_termino.set()

    ta, tb = threading.Thread(target=hilo_a, name="A"), threading.Thread(target=hilo_b, name="B")
    ta.start()
    tb.start()
    ta.join(60)
    tb.join(60)
    assert not ta.is_alive() and not tb.is_alive()
    return errores, visto, llamadas


def test_dos_hilos_sincronizados_el_camino_rapido_de_uno_no_se_filtra_al_otro_ni_comparten_cache(monkeypatch):
    errores, visto, llamadas = _dos_hilos(monkeypatch)
    assert errores == [], errores
    assert visto["b_prof_fuera"] == 0 and visto["b_cache_fuera"] is None          # B no ve el contexto de A
    assert visto["b_prof_dentro"] == 1 and visto["b_cache_propia"] is not None
    assert visto["b_cache_propia"] is not visto["a_cache"]                         # cada hilo con su caché
    assert visto["b_prof_despues"] == 0
    assert visto["a_prof_final"] == 1 and visto["a_cache_final"] is visto["a_cache"]  # lo de B no tocó el de A
    assert llamadas["A"] == ["rapido", "rapido"]
    assert llamadas["B"] == ["ref", "rapido", "ref"]
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None      # y el hilo principal nunca lo vio




class _VarGlobal:
    """Mutante: la misma interfaz que `ContextVar` pero con estado de PROCESO (lo que hacían las globales)."""

    def __init__(self, valor):
        self.valor = valor

    def get(self):
        return self.valor

    def set(self, v):
        anterior, self.valor = self.valor, v
        return anterior

    def reset(self, token):
        self.valor = token


def test_mutante_con_estado_de_proceso_en_vez_de_contextvar_se_detecta_con_los_dos_hilos(monkeypatch):
    monkeypatch.setattr(pb, "_CAND_PROFUNDIDAD", _VarGlobal(0))
    monkeypatch.setattr(pb, "_CAND_ESTADO", _VarGlobal(None))
    errores, visto, llamadas = _dos_hilos(monkeypatch)
    assert errores or visto.get("b_prof_fuera") != 0 or llamadas["B"][:1] != ["ref"]   # B vería el camino rápido de A


def test_la_geometria_cambiada_en_config_invalida_la_cache(monkeypatch):
    esc = _armar(random.Random(9))
    while esc[7] < 2:
        esc = _armar(random.Random(random.random()))
    cons, colocados, pend, por_sku, cap, niv, tope, n = esc
    args = (cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n)
    pb._candidatos_lote_rapido(*args)
    monkeypatch.setattr(config, "TOLERANCIA_OVERHANG_CM", config.TOLERANCIA_OVERHANG_CM + 5.0)
    assert _diferencia(pb._candidatos_lote_referencia(*args), pb._candidatos_lote_rapido(*args)) is None


# ------------------------------------------------------------------------------------------------------------------- cableado por ruta


def test_fallback_sin_reserva_usa_la_rapida_y_el_front_end_con_reserva_la_referencia(monkeypatch):
    from tests.test_fixed_n_no_reserve_fallback import _args, _espiar_cascada, _front_end_con_reserva_atascado

    _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    esp = _Espia(monkeypatch)
    etapa, visto = [], {True: [0, 0], False: [0, 0]}
    real = pb._empacar_n_pallets

    def _envoltura(*a, **k):
        etapa.append(k.get("priorizar_grandes"))
        try:
            return real(*a, **k)
        finally:
            etapa.pop()

    monkeypatch.setattr(pb, "_empacar_n_pallets", _envoltura)
    ref, rapido = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido
    monkeypatch.setattr(pb, "_candidatos_lote_referencia", lambda *a, **k: (visto[etapa[-1]].__setitem__(0, visto[etapa[-1]][0] + 1), ref(*a, **k))[1])
    monkeypatch.setattr(pb, "_candidatos_lote_rapido", lambda *a, **k: (visto[etapa[-1]].__setitem__(1, visto[etapa[-1]][1] + 1), rapido(*a, **k))[1])
    info = {}
    pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=False, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert info["attempted"] is True
    assert visto[True][0] > 0 and visto[True][1] == 0      # front-end con reserva (DFS inicial del camino profundo): referencia
    assert visto[False][1] > 0 and visto[False][0] == 0    # fallback sin reserva: rápida
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None
    del esp


def _stub_cascada(monkeypatch, visto):
    def _etapa(nombre):
        def f(pallets, sin_colocar, *a, **k):
            visto[nombre] = pb._CAND_PROFUNDIDAD.get()
            return pallets, sin_colocar, {"presupuesto": {"modo": "terminacion_natural", "expansiones_trabajo": 1, "watchdog_disparado": False,
                                                          "motivo_stop": "completo", "cota_estructural_observada": 1}} if nombre == "global" else {}
        return f

    def _exact(pallet, por_sku, sin_colocar, *a, **k):
        visto["exact"] = pb._CAND_PROFUNDIDAD.get()
        return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

    monkeypatch.setattr(rs, "rescue_solver", _etapa("rescue"))
    monkeypatch.setattr(rp, "repair_solver", _etapa("repair"))
    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
    monkeypatch.setattr(gr, "global_rescue", _etapa("global"))


def _empacar_n(**kw):
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)]}
    return pb._empacar_n_pallets({"A": 400, "B": 400}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw)


def test_solo_el_rescue_profundo_de_n_fijo_abre_la_rapida_el_resto_de_etapas_y_los_sondeos_open_no(monkeypatch):
    visto = {}
    _stub_cascada(monkeypatch, visto)
    _empacar_n(gobernador_profundo=True)
    assert visto["rescue"] == 1                                         # Rescue profundo (agotamiento natural + watchdog)
    assert visto["repair"] == 0 and visto["exact"] == 0 and visto["global"] == 0
    visto.clear()
    _empacar_n()                                                        # camino sin gobernador profundo (p. ej. materialización por deadline de CPU)
    assert visto["rescue"] == 0 and visto["repair"] == 0 and visto["exact"] == 0 and visto["global"] == 0
    visto.clear()
    _empacar_n(gobernador_profundo=True, presupuesto_rescue_nodos=777, presupuesto_repair_nodos=5, presupuesto_exact_intentos=3)  # sondeo OPEN
    assert visto["rescue"] == 0 and visto["repair"] == 0 and visto["exact"] == 0 and visto["global"] == 0
    visto.clear()
    _empacar_n(presupuesto_global_expansiones=9)                        # materialización final con presupuestos
    assert visto["rescue"] == 0 and visto["repair"] == 0 and visto["global"] == 0
    assert pb._CAND_PROFUNDIDAD.get() == 0


# ------------------------------------------------------------------------------------------------------------------- Repair REAL (N fijo y OPEN)
# Un espía en la entrada de `repair_solver` no ve el contexto: se cuenta, por variante de `_candidatos_lote`, lo que corre DENTRO de su DFS real.


def _repair_real_con_conteo(monkeypatch, **kw):
    from tests.test_repair_probe_work_budget import _correr_repair, _escenario_ejection

    contado = {"ref": 0, "rapido": 0, "dfs": 0}
    ref, rapido, dfs = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido, pb._resolver_pallets_backtracking

    def r(*a, **k):
        contado["ref"] += 1
        return ref(*a, **k)

    def f(*a, **k):
        contado["rapido"] += 1
        return rapido(*a, **k)

    def d(*a, **k):
        contado["dfs"] += 1
        return dfs(*a, **k)

    monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
    monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", d)
    sin_colocar, stats, _ = _correr_repair(_escenario_ejection, **kw)
    return contado, sin_colocar, stats


def test_repair_real_de_n_fijo_con_reloj_de_cpu_usa_la_referencia_en_su_dfs(monkeypatch):
    monkeypatch.setattr(rp, "REPAIR_TIME_MAX_SECONDS", 5.0)
    contado, sin_colocar, stats = _repair_real_con_conteo(monkeypatch)
    assert stats["presupuesto"] == {"modo": "tiempo"} and sin_colocar == {}
    assert contado["dfs"] >= 1 and contado["ref"] >= 1 and contado["rapido"] == 0


def test_repair_real_del_sondeo_open_con_presupuesto_por_nodos_conserva_la_referencia_de_candidatos_aunque_su_dfs_use_la_poda_rapida(monkeypatch):
    """El DFS de Repair en OPEN SÍ abre `_geometria_rapida()` (R6-A) pero NO `_candidatos_rapido()` (R6-B): variantes independientes."""
    visto = {"geom": 0}
    podar = pcol._podar_libres_rapido

    def p(c, previos=None):
        visto["geom"] += 1
        return podar(c, previos)

    monkeypatch.setattr(pcol, "_podar_libres_rapido", p)
    contado, sin_colocar, stats = _repair_real_con_conteo(monkeypatch, presupuesto_nodos=1500)
    assert stats["presupuesto"]["modo"] == "nodos" and sin_colocar == {}
    assert contado["dfs"] >= 1 and contado["ref"] >= 1 and contado["rapido"] == 0
    assert visto["geom"] >= 1  # la poda rápida de R6-A sigue activa ahí (alcance de R6-A intacto)


def test_dfs_de_rescue_open_con_medidor_de_trabajo_y_dfs_inicial_conservan_la_referencia(monkeypatch):
    esp = _Espia(monkeypatch)
    cons, colocados, pend, por_sku, cap, niv, tope, n = _armar(random.Random(4))
    pb._resolver_pallets_backtracking(cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n, max_nodos=10, reloj=MedidorTrabajo())
    assert esp.ref > 0 and esp.rapido == 0
    esp.ref = 0
    cons, colocados, pend, por_sku, cap, niv, tope, n = _armar(random.Random(4))
    pb._resolver_pallets_backtracking(cons, colocados, pend, por_sku, cap, niv, tope, PRESUPUESTO, n, max_nodos=10, metricas_perezosas=True)
    assert esp.ref > 0 and esp.rapido == 0
