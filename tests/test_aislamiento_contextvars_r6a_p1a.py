"""Aislamiento por ejecución de los dos contextos más antiguos del motor: la poda rápida de R6-A (`_geometria_rapida`) y el memo de `_area_union_xy` de P1-A
(`_area_union_memoizada`). Ambos viven en `ContextVar`s: cada hilo parte de su propio contexto vacío, así que lo que activa un hilo no se filtra a otro, un
contexto anidado reutiliza el estado del externo y todo se restablece ante una excepción. Misma estructura que las pruebas de `_candidatos_rapido` (R6-B)."""
import threading

import pytest

import src.packing_columnar as pcol
from models import PalletV5
from src.torres import TorreCandidate, crear_torre


def _torres():
    return [crear_torre(TorreCandidate("A", "CD", "L×A", 40.0, 30.0, 20.0, 20, 10, 1.0), x=0.0, y=0.0, z=0.0, cantidad=1),
            crear_torre(TorreCandidate("B", "CD", "L×A", 20.0, 30.0, 10.0, 20, 10, 1.0), x=40.0, y=0.0, z=0.0, cantidad=1)]


def _colocar_un_par():
    pc = pcol._PalletEnConstruccion(pallet=PalletV5(id="P", cd="CD"))
    cand = TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 10, 1.0)
    pc.colocar(cand, 1, 0)
    pc.colocar(cand, 1, 0)


class _VarGlobal:
    """Mutante: la interfaz de `ContextVar` con estado de PROCESO (lo que eran las globales)."""

    def __init__(self, valor):
        self.valor = valor

    def get(self):
        return self.valor

    def set(self, v):
        anterior, self.valor = self.valor, v
        return anterior

    def reset(self, token):
        self.valor = token


def _dos_hilos(monkeypatch, abrir, leer, usar):
    """A abre el contexto y espera; B (mientras A está dentro) lee su propio estado, usa la funcionalidad, abre el suyo -y falla dentro-, y A comprueba que
    no se enteró. `abrir()` -> contexto; `leer()` -> estado visible; `usar()` -> qué variante/uso hizo la llamada."""
    a_dentro, b_termino = threading.Event(), threading.Event()
    visto, errores = {}, []

    def hilo_a():
        try:
            with abrir():
                visto["a_estado"] = leer()
                visto["a_uso_inicial"] = usar()
                a_dentro.set()
                assert b_termino.wait(30)
                visto["a_estado_final"] = leer()
                visto["a_uso_final"] = usar()
        except BaseException as e:  # noqa: BLE001
            errores.append(("A", e))
            a_dentro.set()

    def hilo_b():
        try:
            assert a_dentro.wait(30)
            visto["b_fuera"] = leer()
            visto["b_uso_fuera"] = usar()
            with pytest.raises(RuntimeError):
                with abrir():
                    visto["b_dentro"] = leer()
                    visto["b_uso_dentro"] = usar()
                    raise RuntimeError("b")
            visto["b_despues"] = leer()
            visto["b_uso_despues"] = usar()
        except BaseException as e:  # noqa: BLE001
            errores.append(("B", e))
        finally:
            b_termino.set()

    ta, tb = threading.Thread(target=hilo_a), threading.Thread(target=hilo_b)
    ta.start()
    tb.start()
    ta.join(60)
    tb.join(60)
    assert not ta.is_alive() and not tb.is_alive()
    return errores, visto


# ------------------------------------------------------------------------------------------------------------------------------ R6-A: poda rápida


def _espia_poda(monkeypatch):
    uso = {}
    ref, rapido = pcol._podar_libres_referencia, pcol._podar_libres_rapido

    def r(c):
        uso[threading.current_thread().ident] = "ref"
        return ref(c)

    def f(c, previos=None):
        uso[threading.current_thread().ident] = "rapido"
        return rapido(c, previos)

    monkeypatch.setattr(pcol, "_podar_libres_referencia", r)
    monkeypatch.setattr(pcol, "_podar_libres_rapido", f)

    def usar():
        _colocar_un_par()
        return uso[threading.current_thread().ident]

    return usar


def test_dos_hilos_la_poda_rapida_de_uno_no_se_activa_en_el_otro(monkeypatch):
    usar = _espia_poda(monkeypatch)
    errores, v = _dos_hilos(monkeypatch, pcol._geometria_rapida, lambda: pcol._GEOM_PROFUNDIDAD.get(), usar)
    assert errores == [], errores
    assert v["b_fuera"] == 0 and v["b_uso_fuera"] == "ref"             # B no ve el contexto de A y usa la referencia
    assert v["b_dentro"] == 1 and v["b_uso_dentro"] == "rapido"        # dentro de SU contexto: rápida
    assert v["b_despues"] == 0 and v["b_uso_despues"] == "ref"         # tras cerrar el suyo con una excepción: referencia otra vez
    assert v["a_estado"] == v["a_estado_final"] == 1                   # A no se enteró de nada de lo que hizo B
    assert v["a_uso_inicial"] == v["a_uso_final"] == "rapido"
    assert pcol._GEOM_PROFUNDIDAD.get() == 0                           # y el hilo principal nunca lo vio


def test_mutante_con_estado_de_proceso_en_la_poda_rapida_se_detecta_con_los_dos_hilos(monkeypatch):
    monkeypatch.setattr(pcol, "_GEOM_PROFUNDIDAD", _VarGlobal(0))
    usar = _espia_poda(monkeypatch)
    errores, v = _dos_hilos(monkeypatch, pcol._geometria_rapida, lambda: pcol._GEOM_PROFUNDIDAD.get(), usar)
    assert errores or v.get("b_fuera") != 0 or v.get("b_uso_fuera") != "ref"


def test_la_poda_rapida_reentrante_se_restablece_ante_una_excepcion_interna_y_externa():
    with pytest.raises(RuntimeError):
        with pcol._geometria_rapida():
            raise RuntimeError("x")
    assert pcol._GEOM_PROFUNDIDAD.get() == 0
    with pcol._geometria_rapida():
        with pytest.raises(RuntimeError):
            with pcol._geometria_rapida():
                assert pcol._GEOM_PROFUNDIDAD.get() == 2
                raise RuntimeError("y")
        assert pcol._GEOM_PROFUNDIDAD.get() == 1                       # el externo sigue activo
    assert pcol._GEOM_PROFUNDIDAD.get() == 0


# ------------------------------------------------------------------------------------------------------------------------------ P1-A: memo de área


def _espia_memo(monkeypatch):
    visto = {}
    original = pcol._area_union_xy_calcular

    def calcular(torres):
        visto.setdefault(threading.current_thread().ident, []).append(pcol._AREA_UNION_MEMO_VAR.get())
        return original(torres)

    monkeypatch.setattr(pcol, "_area_union_xy_calcular", calcular)

    def usar():
        torres = _torres()
        visto[threading.current_thread().ident] = []
        pcol._area_union_xy(torres)
        pcol._area_union_xy(torres)
        # cuántas veces se calculó de verdad: con memo activo, 1; sin memo, 2
        return len(visto[threading.current_thread().ident])

    return usar


def test_dos_hilos_el_memo_de_area_de_uno_no_se_filtra_al_otro_ni_se_comparte(monkeypatch):
    usar = _espia_memo(monkeypatch)
    def abrir():
        return pcol._area_union_memoizada()

    errores, v = _dos_hilos(monkeypatch, abrir, lambda: pcol._AREA_UNION_MEMO_VAR.get(), usar)
    assert errores == [], errores
    assert v["b_fuera"] is None and v["b_uso_fuera"] == 2             # B sin memo: calcula las dos veces
    assert v["b_dentro"] is not None and v["b_uso_dentro"] == 1       # B con SU memo: calcula una vez
    assert v["b_dentro"] is not v["a_estado"]                          # memo propio, distinto del de A
    assert v["b_despues"] is None and v["b_uso_despues"] == 2          # cerró el suyo (con excepción): vuelve a no tener
    assert v["a_estado_final"] is v["a_estado"] and v["a_estado"] is not None   # A conserva EL MISMO memo
    assert v["a_uso_inicial"] == 1 and v["a_uso_final"] == 0           # A: primera vez calcula; después de todo lo de B, su memo sigue lleno (acierto)
    assert pcol._AREA_UNION_MEMO_VAR.get() is None


def test_mutante_con_estado_de_proceso_en_el_memo_se_detecta_con_los_dos_hilos(monkeypatch):
    monkeypatch.setattr(pcol, "_AREA_UNION_MEMO_VAR", _VarGlobal(None))
    usar = _espia_memo(monkeypatch)
    errores, v = _dos_hilos(monkeypatch, pcol._area_union_memoizada, lambda: pcol._AREA_UNION_MEMO_VAR.get(), usar)
    assert errores or v.get("b_fuera") is not None or v.get("b_uso_fuera") != 2


def test_el_memo_anidado_reusa_el_externo_y_se_restablece_ante_una_excepcion():
    with pytest.raises(RuntimeError):
        with pcol._area_union_memoizada():
            raise RuntimeError("x")
    assert pcol._AREA_UNION_MEMO_VAR.get() is None
    with pcol._area_union_memoizada():
        externo = pcol._AREA_UNION_MEMO_VAR.get()
        pcol._area_union_xy(_torres())
        with pytest.raises(RuntimeError):
            with pcol._area_union_memoizada():
                assert pcol._AREA_UNION_MEMO_VAR.get() is externo and len(externo) == 1   # reutiliza el del externo, con lo ya calculado
                raise RuntimeError("y")
        assert pcol._AREA_UNION_MEMO_VAR.get() is externo and len(externo) == 1            # la excepción interna no lo descarta
    assert pcol._AREA_UNION_MEMO_VAR.get() is None
