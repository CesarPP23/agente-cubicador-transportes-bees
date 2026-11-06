"""[V6.13-R6A -"Bit-identical geometry performance: `_podar_libres`"] `_podar_libres_rapido` debe devolver EXACTAMENTE lo mismo que la implementación de
siempre (`_podar_libres_referencia`): misma cantidad, mismo orden, mismos objetos, mismos floats bit a bit -no solo el mismo conjunto-. Y solo debe
usarse en las búsquedas acotadas por trabajo; las etapas gobernadas por deadline de CPU (Repair, Exact, Rescue/Global sin gobernador, sondeo de OPEN)
tienen que seguir en la referencia. Tests sintéticos y rápidos (la validación con casos reales vive en el informe)."""
import copy
import pickle
import random
import struct

import pytest

import config
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.packing_columnar as pcol
import src.repair_solver as rp
import src.rescue_solver as rs
from src.medidor_trabajo import MedidorTrabajo
from src.packing_columnar import TOL, _CuboidLibre
from src.torres import TorreCandidate

# ---------------------------------------------------------------------------------------------------------------- generadores

_GRILLA = [0.0, 5.0, 10.0, 20.0, 30.0, 40.0, 60.0, 80.0, 100.0, 120.0]
_JITTER = [0.0, 0.0, 0.0, 1e-7, -1e-7, 5e-7, -5e-7, TOL, -TOL, 1.5 * TOL, -1.5 * TOL, 3 * TOL]  # justo alrededor de la tolerancia


def _numero(rng):
    return rng.choice(_GRILLA) + rng.choice(_JITTER)


def _cuboide(rng):
    x, y, z = _numero(rng), _numero(rng), rng.choice(_GRILLA[:6]) + rng.choice(_JITTER)
    return _CuboidLibre(x, y, z, rng.choice(_GRILLA[1:]) + rng.choice(_JITTER), rng.choice(_GRILLA[1:]) + rng.choice(_JITTER),
                        rng.choice(_GRILLA[1:7]) + rng.choice(_JITTER))


def _lista_aleatoria(rng):
    n = rng.randint(0, 36)
    base = [_cuboide(rng) for _ in range(n)]
    extra = []
    for c in base:
        r = rng.random()
        if r < 0.15:  # duplicado exacto (otro objeto)
            extra.append(_CuboidLibre(c.x, c.y, c.z, c.w, c.h, c.d))
        elif r < 0.25:  # duplicado por tolerancia
            extra.append(_CuboidLibre(c.x + rng.choice(_JITTER), c.y + rng.choice(_JITTER), c.z, c.w + rng.choice(_JITTER), c.h, c.d))
        elif r < 0.33:  # el MISMO objeto dos veces
            extra.append(c)
        elif r < 0.50:  # contenido en `c`
            extra.append(_CuboidLibre(c.x + rng.choice([0.0, 1.0, 3.0]), c.y + rng.choice([0.0, 2.0]), c.z, c.w / 2, c.h / 2, c.d / 2))
    todos = base + extra
    rng.shuffle(todos)
    return todos


def _bits(lista):
    return [struct.pack("<6d", c.x, c.y, c.z, c.w, c.h, c.d) for c in lista]


def _igual_exacto(esperada, obtenida):
    """Misma longitud, mismo orden, MISMOS OBJETOS y mismos floats bit a bit."""
    return (len(esperada) == len(obtenida) and [id(c) for c in esperada] == [id(c) for c in obtenida]
            and _bits(esperada) == _bits(obtenida))


def _corpus(n=1500, semilla=20260611):
    rng = random.Random(semilla)
    return [_lista_aleatoria(rng) for _ in range(n)]


def _cadena_actualizaciones(rng, pasos=14):
    """Secuencia de colocaciones reales sobre un pallet (como las hace `colocar`): cada paso elige un cuboide libre y pone una caja a ras de su esquina."""
    libres = [pcol._cuboide_inicial()]
    colocaciones = []
    for _ in range(pasos):
        c = rng.choice(libres)
        w = min(c.w, rng.choice([10.0, 20.0, 25.0, 30.0, 40.0, 60.0])) + rng.choice([0.0, 0.0, 1e-7, -1e-7, TOL])
        h = min(c.h, rng.choice([10.0, 15.0, 20.0, 30.0, 50.0])) + rng.choice([0.0, 0.0, 1e-7, -TOL])
        d = min(c.d, rng.choice([10.0, 12.0, 20.0, 25.0, 40.0]))
        # a veces en la esquina del cuboide, a veces desplazada (también solapa a otros cuboides libres)
        x = c.x + rng.choice([0.0, 0.0, 5.0, 10.0]) * (1 if c.w - w >= 10.0 else 0)
        y = c.y + rng.choice([0.0, 0.0, 5.0]) * (1 if c.h - h >= 5.0 else 0)
        colocaciones.append((x, y, c.z, w, h, d))
        libres = pcol._actualizar_libres_maxrects(libres, x, y, c.z, w, h, d)
        if not libres:
            break
    return colocaciones


# ---------------------------------------------------------------------------------------------------------------- equivalencia


def test_rapido_igual_a_referencia_en_miles_de_listas_aleatorias_incluidas_las_de_borde_de_tolerancia():
    for lista in _corpus():
        esperado = pcol._podar_libres_referencia(list(lista))
        assert _igual_exacto(esperado, pcol._podar_libres_rapido(list(lista)))
        assert _igual_exacto(esperado, pcol._podar_libres_rapido(list(lista), None))


def test_el_corpus_ejercita_de_verdad_duplicados_podas_y_casos_de_borde():
    podados = duplicados = 0
    for lista in _corpus():
        unicos = []
        for c in lista:
            if any(pcol._es_igual(c, u) for u in unicos):
                duplicados += 1
            else:
                unicos.append(c)
        podados += len(unicos) - len(pcol._podar_libres_referencia(list(lista)))
    assert duplicados > 1000 and podados > 1000


def test_cadenas_de_colocaciones_reales_identicas_paso_a_paso_con_y_sin_la_poda_incremental():
    rng = random.Random(7)
    for _ in range(120):
        colocaciones = _cadena_actualizaciones(rng)
        ref = [pcol._cuboide_inicial()]
        rapida = [pcol._cuboide_inicial()]
        for (x, y, z, w, h, d) in colocaciones:
            ref = pcol._actualizar_libres_maxrects(ref, x, y, z, w, h, d)  # fuera del contexto: referencia
            with pcol._geometria_rapida():
                rapida = pcol._actualizar_libres_maxrects(rapida, x, y, z, w, h, d)
            assert len(ref) == len(rapida) and _bits(ref) == _bits(rapida)  # mismos valores y orden (objetos distintos: cada cadena tiene los suyos)
        assert type(rapida) is pcol._LibresPodados  # y la cadena rápida SÍ usó la marca de procedencia


def test_la_poda_incremental_se_usa_y_da_lo_mismo_que_la_general():
    rng = random.Random(11)
    usadas = 0
    for _ in range(60):
        libres = pcol._podar_libres_rapido([pcol._cuboide_inicial()])
        for (x, y, z, w, h, d) in _cadena_actualizaciones(rng, 10):
            solapa = [pcol._se_solapan(c, x, y, z, w, h, d) for c in libres]
            nuevos = []
            for c, s in zip(libres, solapa):
                if not s:
                    nuevos.append(c)
            # reutiliza el generador oficial para los fragmentos: se arma la lista de entrada de la poda tal como la arma `_actualizar_libres_maxrects`
            entrada = []
            for libre in libres:
                if not pcol._se_solapan(libre, x, y, z, w, h, d):
                    entrada.append(libre)
                    continue
                if x > libre.x + TOL:
                    entrada.append(_CuboidLibre(libre.x, libre.y, libre.z, x - libre.x, libre.h, libre.d))
                if x + w < libre.right - TOL:
                    entrada.append(_CuboidLibre(x + w, libre.y, libre.z, libre.right - (x + w), libre.h, libre.d))
                if y > libre.y + TOL:
                    entrada.append(_CuboidLibre(libre.x, libre.y, libre.z, libre.w, y - libre.y, libre.d))
                if y + h < libre.top - TOL:
                    entrada.append(_CuboidLibre(libre.x, y + h, libre.z, libre.w, libre.top - (y + h), libre.d))
            entrada = [c for c in entrada if c.w > TOL and c.h > TOL and c.d > TOL]
            esperado = pcol._podar_libres_referencia(list(entrada))
            general = pcol._podar_libres_rapido(list(entrada))
            incremental = pcol._podar_libres_rapido(list(entrada), libres)
            assert _igual_exacto(esperado, general) and _igual_exacto(esperado, incremental)
            usadas += 1
            libres = incremental
    assert usadas > 400


# ---------------------------------------------------------------------------------------------------------------- marca de procedencia


def test_una_lista_mutada_o_copiada_deja_de_ser_de_confianza_y_el_resultado_sigue_siendo_exacto():
    rng = random.Random(3)
    for _ in range(300):
        lista = _lista_aleatoria(rng)
        previos = pcol._podar_libres_rapido(list(lista))
        entrada = list(previos) + [_cuboide(rng) for _ in range(rng.randint(0, 6))]
        esperado = pcol._podar_libres_referencia(list(entrada))

        mutada = pcol._podar_libres_rapido(list(lista))
        mutada.append(_CuboidLibre(*(_numero(rng) for _ in range(6))))  # mutación en el mismo objeto lista
        sustituida = pcol._podar_libres_rapido(list(lista))
        if sustituida:
            sustituida[0] = _cuboide(rng)
        for previos_x in (None, [], list(previos), mutada, sustituida, copy.deepcopy(previos), pickle.loads(pickle.dumps(previos))):
            assert _igual_exacto(esperado, pcol._podar_libres_rapido(list(entrada), previos_x))


def test_confiar_a_ciegas_en_una_lista_falsa_SI_cambiaria_el_resultado_la_marca_es_necesaria():
    # mutante: una lista que NO salió de la poda pero lleva una marca forjada (ids coherentes) -el caso que la validación de `_ids` evita
    a = _CuboidLibre(0, 0, 0, 10, 10, 10)
    b = _CuboidLibre(0, 0, 0, 5, 5, 5)  # contenido en `a`
    falsa = pcol._LibresPodados([a, b])
    falsa._ids = tuple(map(id, falsa))
    assert not _igual_exacto(pcol._podar_libres_referencia([a, b]), pcol._podar_libres_rapido([a, b], falsa))
    # la lista real que sale de la poda no tiene ese problema
    assert _igual_exacto(pcol._podar_libres_referencia([a, b]), pcol._podar_libres_rapido([a, b], pcol._podar_libres_rapido([a, b])))


def test_la_marca_es_una_lista_normal_para_el_resto_del_codigo():
    r = pcol._podar_libres_rapido([_CuboidLibre(0, 0, 0, 10, 10, 10)])
    assert isinstance(r, list) and r == list(r) and len(list(r)) == 1 and type(list(r)) is list
    assert type(r[:]) is list and type(r + r) is list


# ---------------------------------------------------------------------------------------------------------------- mutantes: el chequeo detecta cambios


def _detecta(candidata, n=800):
    return any(not _igual_exacto(pcol._podar_libres_referencia(list(lista)), candidata(list(lista))) for lista in _corpus(n, 99))


def _con_referencia(es_igual=None, contenido=None, orden=None):
    def f(cuboides):
        eq = es_igual or pcol._es_igual
        ct = contenido or pcol._contenido
        unicos = []
        for c in cuboides:
            if not any(eq(c, u) for u in unicos):
                unicos.append(c)
        salida = [c for c in unicos if not any(c is not otro and ct(c, otro) for otro in unicos)]
        return orden(salida) if orden else salida
    return f


def test_el_chequeo_acepta_la_implementacion_rapida_y_la_referencia():
    assert not _detecta(pcol._podar_libres_rapido)
    assert not _detecta(_con_referencia())


def test_mutante_cambio_de_orden_se_detecta():
    assert _detecta(_con_referencia(orden=lambda s: list(reversed(s))))
    assert _detecta(lambda c: sorted(pcol._podar_libres_referencia(c), key=lambda k: (k.x, k.y, k.z)))


def test_mutante_cambio_de_poda_se_detecta():
    sin_contenidos = _con_referencia(contenido=lambda a, b: False)
    assert _detecta(sin_contenidos)  # no poda nada
    estricto = _con_referencia(contenido=lambda a, b: (a.x > b.x and a.y > b.y and a.z > b.z and a.right < b.right and a.top < b.top and a.ceil < b.ceil))
    assert _detecta(estricto)
    assert _detecta(lambda c: pcol._podar_libres_referencia(c)[:-1])  # pierde un cuboide


def test_mutante_cambio_de_igualdad_de_floats_se_detecta():
    exacta = _con_referencia(es_igual=lambda a, b: (a.x, a.y, a.z, a.w, a.h, a.d) == (b.x, b.y, b.z, b.w, b.h, b.d))
    assert _detecta(exacta)
    tolerancia_doble = _con_referencia(es_igual=lambda a, b: all(abs(p - q) < 2 * TOL for p, q in zip((a.x, a.y, a.z, a.w, a.h, a.d), (b.x, b.y, b.z, b.w, b.h, b.d))))
    assert _detecta(tolerancia_doble)
    contenido_sin_tol = _con_referencia(contenido=lambda a, b: (a.x >= b.x and a.y >= b.y and a.z >= b.z and a.right <= b.right and a.top <= b.top and a.ceil <= b.ceil))
    assert _detecta(contenido_sin_tol)


def test_mutante_de_float_a_un_ulp_se_detecta_por_la_comparacion_bit_a_bit():
    a = _CuboidLibre(0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
    b = _CuboidLibre(0.0, 0.0, 0.0, 10.0 + 1e-15, 10.0, 10.0)
    assert not _igual_exacto([a], [b])  # igual como valor aproximado, distinto en bits: el chequeo lo distingue


# ---------------------------------------------------------------------------------------------------------------- despacho: qué etapa usa qué implementación


class _Espia:
    def __init__(self, monkeypatch):
        self.ref = self.rapido = 0
        ref, rapido = pcol._podar_libres_referencia, pcol._podar_libres_rapido

        def r(c):
            self.ref += 1
            return ref(c)

        def f(c, previos=None):
            self.rapido += 1
            return rapido(c, previos)

        monkeypatch.setattr(pcol, "_podar_libres_referencia", r)
        monkeypatch.setattr(pcol, "_podar_libres_rapido", f)


def _colocar_un_par():
    pc = pcol._PalletEnConstruccion(pallet=__import__("models").PalletV5(id="P", cd="CD"))
    cand = TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 10, 1.0)
    pc.colocar(cand, 1, 0)
    pc.colocar(cand, 1, 0)
    return pc


def test_por_defecto_se_usa_la_referencia(monkeypatch):
    esp = _Espia(monkeypatch)
    assert pcol._GEOM_RAPIDA == 0
    _colocar_un_par()
    assert esp.ref >= 2 and esp.rapido == 0


def test_dentro_del_contexto_se_usa_la_rapida_y_el_contexto_es_reentrante_y_seguro_ante_excepciones(monkeypatch):
    esp = _Espia(monkeypatch)
    with pcol._geometria_rapida():
        assert pcol._GEOM_RAPIDA == 1
        with pcol._geometria_rapida():
            assert pcol._GEOM_RAPIDA == 2
        assert pcol._GEOM_RAPIDA == 1
        _colocar_un_par()
    assert pcol._GEOM_RAPIDA == 0 and esp.rapido >= 2 and esp.ref == 0
    with pytest.raises(RuntimeError):
        with pcol._geometria_rapida():
            raise RuntimeError("x")
    assert pcol._GEOM_RAPIDA == 0
    with pb._busqueda_acotada_por_trabajo():
        assert pcol._GEOM_RAPIDA == 1 and pcol._AREA_UNION_MEMO is not None
    assert pcol._GEOM_RAPIDA == 0 and pcol._AREA_UNION_MEMO is None


def _dfs_chico(reloj, **kw):
    cand = TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)
    pallets = [__import__("models").PalletV5(id=f"P{i}", cd="CD") for i in range(2)]
    cons = [pcol._PalletEnConstruccion(pallet=p) for p in pallets]
    colocados = [{} for _ in cons]
    pendientes = {"A": 12}
    return pb._resolver_pallets_backtracking(
        cons, colocados, pendientes, {"A": [cand]}, {"A": 4}, {"A": 1}, {}, config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO, 2,
        max_nodos=60, reloj=reloj, **kw,
    )


def test_el_dfs_acotado_por_trabajo_usa_la_rapida_y_el_gobernado_por_cpu_la_referencia(monkeypatch):
    esp = _Espia(monkeypatch)
    _dfs_chico(__import__("time").process_time)  # deadline de CPU (Repair/Exact/Rescue sin gobernador): referencia
    assert esp.ref > 0 and esp.rapido == 0
    esp.ref = 0
    _dfs_chico(MedidorTrabajo())  # budget de trabajo (probe/final, Rescue profundo): rápida
    assert esp.rapido > 0 and esp.ref == 0
    esp.rapido = 0
    _dfs_chico(__import__("time").process_time, metricas_perezosas=True)  # front-end acotado por nodos: rápida
    assert esp.rapido > 0 and esp.ref == 0


def test_el_resultado_del_dfs_es_el_mismo_con_la_referencia_y_con_la_rapida(monkeypatch):
    def correr(reloj, **kw):
        cand = TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)
        cons = [pcol._PalletEnConstruccion(pallet=__import__("models").PalletV5(id=f"P{i}", cd="CD")) for i in range(2)]
        colocados, pend = [{} for _ in cons], {"A": 14}
        info = {}
        total = pb._resolver_pallets_backtracking(
            cons, colocados, pend, {"A": [cand]}, {"A": 4}, {"A": 1}, {}, config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO, 2,
            max_nodos=200, reloj=reloj, info_salida=info, **kw,
        )
        return total, info["nodos"], info["motivo_parada"], [(t.x, t.y, t.z, t.cantidad) for c in cons for t in c.pallet.torres], [_bits(c.libres) for c in cons]
    con_referencia = correr(__import__("time").process_time)
    con_rapida = correr(__import__("time").process_time, metricas_perezosas=True)
    assert con_referencia == con_rapida


# ---------------------------------------------------------------------------------------------------------------- cableado en _empacar_n_pallets (Global)


def _stub_cascada(monkeypatch, visto):
    def _etapa(nombre):
        def f(pallets, sin_colocar, *a, **k):
            visto[nombre] = pcol._GEOM_RAPIDA
            return pallets, sin_colocar, {"presupuesto": {"modo": "terminacion_natural", "expansiones_trabajo": 1, "watchdog_disparado": False,
                                                          "motivo_stop": "completo", "cota_estructural_observada": 1}} if nombre == "global" else {}
        return f

    def _exact(pallet, por_sku, sin_colocar, *a, **k):
        visto["exact"] = pcol._GEOM_RAPIDA
        return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

    monkeypatch.setattr(rs, "rescue_solver", _etapa("rescue"))
    monkeypatch.setattr(rp, "repair_solver", _etapa("repair"))
    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
    monkeypatch.setattr(gr, "global_rescue", _etapa("global"))


def _empacar_n(**kw):
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)]}
    return pb._empacar_n_pallets({"A": 400, "B": 400}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw)


def test_global_del_camino_profundo_usa_la_rapida_y_repair_exact_rescue_quedan_en_la_referencia(monkeypatch):
    visto = {}
    _stub_cascada(monkeypatch, visto)
    _empacar_n(gobernador_profundo=True)
    assert visto["global"] == 1  # terminación natural: trabajo independiente del reloj
    assert visto["repair"] == 0 and visto["exact"] == 0 and visto["rescue"] == 0  # deadlines de CPU: sin tocar


def test_global_final_con_presupuesto_de_expansiones_usa_la_rapida_y_global_del_sondeo_open_no(monkeypatch):
    visto = {}
    _stub_cascada(monkeypatch, visto)
    _empacar_n(presupuesto_global_expansiones=9)
    assert visto["global"] == 1 and visto["repair"] == 0 and visto["exact"] == 0
    visto.clear()
    _empacar_n()  # sondeo/camino sin presupuesto: Global por deadline de CPU (180 s)
    assert visto["global"] == 0 and visto["repair"] == 0 and visto["exact"] == 0
    visto.clear()
    _empacar_n(gobernador_profundo=True, presupuesto_rescue_nodos=777, presupuesto_repair_nodos=5, presupuesto_exact_intentos=3)
    assert visto["global"] == 0  # sondeo OPEN: conserva su política (deadline de CPU)
    assert pcol._GEOM_RAPIDA == 0


# ------------------------------------------------------------------------ Repair REAL: la variante dentro de su DFS de reconstrucción
# Un espía en la ENTRADA de `repair_solver` no ve el cambio de contexto: la poda rápida se activa DENTRO del DFS de reconstrucción (`diferir_metricas`
# cuando el `reloj` es un `MedidorTrabajo`). Acá se corre el `repair_solver` real y se cuenta, por variante, qué `_podar_libres` corrió dentro de cada DFS.


def _repair_real_con_conteo(monkeypatch, **kw):
    from tests.test_repair_probe_work_budget import _correr_repair, _escenario_ejection

    dentro = {"ref": 0, "rapido": 0, "dfs": 0}
    fuera = {"ref": 0, "rapido": 0}
    profundidad = [0]
    ref, rapido, dfs = pcol._podar_libres_referencia, pcol._podar_libres_rapido, pb._resolver_pallets_backtracking

    def r(c):
        (dentro if profundidad[0] else fuera)["ref"] += 1
        return ref(c)

    def f(c, previos=None):
        (dentro if profundidad[0] else fuera)["rapido"] += 1
        return rapido(c, previos)

    def d(*a, **k):
        dentro["dfs"] += 1
        profundidad[0] += 1
        try:
            return dfs(*a, **k)
        finally:
            profundidad[0] -= 1

    monkeypatch.setattr(pcol, "_podar_libres_referencia", r)
    monkeypatch.setattr(pcol, "_podar_libres_rapido", f)
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", d)
    sin_colocar, stats, firma = _correr_repair(_escenario_ejection, **kw)
    assert pcol._GEOM_RAPIDA == 0  # el contexto se cierra siempre
    return dentro, fuera, sin_colocar, stats, firma


def test_repair_real_con_reloj_de_cpu_usa_la_referencia_dentro_de_su_dfs(monkeypatch):
    monkeypatch.setattr(rp, "REPAIR_TIME_MAX_SECONDS", 5.0)
    dentro, fuera, sin_colocar, stats, _ = _repair_real_con_conteo(monkeypatch)
    assert stats["presupuesto"] == {"modo": "tiempo"}
    assert dentro["dfs"] >= 1  # el DFS de reconstrucción de verdad corrió
    assert dentro["ref"] >= 1 and dentro["rapido"] == 0
    assert fuera["rapido"] == 0
    assert sin_colocar == {}


def test_repair_real_con_presupuesto_por_nodos_de_open_activa_la_rapida_dentro_de_su_dfs_y_solo_ahi(monkeypatch):
    dentro, fuera, sin_colocar, stats, _ = _repair_real_con_conteo(monkeypatch, presupuesto_nodos=1500)
    assert stats["presupuesto"]["modo"] == "nodos"
    assert dentro["dfs"] >= 1
    assert dentro["rapido"] >= 1 and dentro["ref"] == 0  # todo lo que ocurre dentro del DFS usa la rápida
    assert fuera["rapido"] == 0 and fuera["ref"] >= 1  # fuera del DFS (reconstrucción de estado, etc.) sigue la referencia
    assert sin_colocar == {}


def test_repair_real_da_el_mismo_resultado_en_ambos_modos_y_con_la_referencia_forzada(monkeypatch):
    from tests.test_repair_probe_work_budget import _correr_repair, _escenario_ejection

    monkeypatch.setattr(rp, "REPAIR_TIME_MAX_SECONDS", 5.0)
    sc_t, _, firma_t = _correr_repair(_escenario_ejection)
    sc_n, _, firma_n = _correr_repair(_escenario_ejection, presupuesto_nodos=1500)
    # misma corrida con la rápida desactivada aun en modo nodos: el resultado no depende de la variante
    monkeypatch.setattr(pcol, "_podar_libres_rapido", lambda c, previos=None: pcol._podar_libres_referencia(c))
    sc_r, _, firma_r = _correr_repair(_escenario_ejection, presupuesto_nodos=1500)
    assert sc_t == sc_n == sc_r == {}
    assert firma_t == firma_n == firma_r
