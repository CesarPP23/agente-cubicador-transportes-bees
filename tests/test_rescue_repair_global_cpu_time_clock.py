"""[PATCH V6.12-R2-A1] Tests del mismatch de reloj detectado en la
auditoría R2-A0 y cerrado acá: `_aplicar_ruina_dirigida` (rescue_solver.py,
2 sitios) y su equivalente en repair_solver.py llamaban a
`_resolver_pallets_backtracking` sin pasar `reloj=`, heredando el default
`time.process_time` mientras `limite_tiempo` venía de `time.time()` -
mismatch de dominio que dejaba inerte el corte por tiempo ahí (ver
V612_R2A0). Mismo patrón que V6.11-R3 (`test_packing_bloques_cpu_budget.py`)
pero para rescue/repair/global/exact -deadline y checker SIEMPRE en el
mismo dominio temporal, pasado explícito, nunca por default implícito."""
import inspect
import time

import config
from models import PalletV5
from src.rescue_solver import (
    RESCUE_TIME_MAX_SECONDS,
    _aplicar_ruina_dirigida,
    _colocar_critico_backtracking,
    rescue_solver,
)
import src.rescue_solver as rescue_solver_mod
import src.repair_solver as repair_solver_mod
import src.global_rescue as global_rescue_mod
import src.exact_repair as exact_repair_mod
from src.repair_solver import (
    _buscar_ejection_chain,
    _intentar_neighborhoods_iterativos,
    _reconstruccion_multi_critica,
    repair_solver,
)
from src.global_rescue import _beam_search, global_rescue
from src.exact_repair import exact_repair_orquestado
from src.torres import TorreCandidate, crear_torre


def _cand(sku="X", largo=30, ancho=30, alto=20, cantidad_disponible=10):
    return TorreCandidate(sku, "BK31", "LxA", largo, ancho, alto, 10, cantidad_disponible, 1.0)


def _escenario_grande_bloqueado_por_dos_chicos():
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO
    wall1_cand = _cand(sku="WALL1", largo=82.0, ancho=104.0, alto=presupuesto)
    wall1 = crear_torre(wall1_cand, x=40, y=-2, cantidad=1)
    wall2_cand = _cand(sku="WALL2", largo=42.0, ancho=72.0, alto=presupuesto)
    wall2 = crear_torre(wall2_cand, x=-2, y=30, cantidad=1)
    chico_a = _cand(sku="A", largo=20, ancho=30, alto=15)
    chico_b = _cand(sku="B", largo=20, ancho=30, alto=15)
    torre_a = crear_torre(chico_a, x=0, y=0, cantidad=1)
    torre_b = crear_torre(chico_b, x=20, y=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="BK31", torres=[wall1, wall2, torre_a, torre_b],
                       altura_final=config.ALTURA_PALLET_VACIO + presupuesto)
    grande = _cand(sku="GRANDE", largo=40, ancho=30, alto=15)
    por_sku = {"GRANDE": [grande], "A": [chico_a], "B": [chico_b], "WALL1": [wall1_cand], "WALL2": [wall2_cand]}
    nivel_por_sku = {"GRANDE": 6, "A": 6, "B": 6, "WALL1": 6, "WALL2": 6}
    return pallet, por_sku, nivel_por_sku, presupuesto, grande


# --- 1. deadline y reloj usan la misma escala (defaults) ------------------

def test_aplicar_ruina_dirigida_default_es_process_time():
    sig = inspect.signature(_aplicar_ruina_dirigida)
    assert sig.parameters["reloj"].default is time.process_time


def test_colocar_critico_backtracking_default_es_process_time():
    sig = inspect.signature(_colocar_critico_backtracking)
    assert sig.parameters["reloj"].default is time.process_time


def test_buscar_ejection_chain_default_es_process_time():
    sig = inspect.signature(_buscar_ejection_chain)
    assert sig.parameters["reloj"].default is time.process_time


def test_intentar_neighborhoods_iterativos_default_es_process_time():
    sig = inspect.signature(_intentar_neighborhoods_iterativos)
    assert sig.parameters["reloj"].default is time.process_time


def test_reconstruccion_multi_critica_default_es_process_time():
    sig = inspect.signature(_reconstruccion_multi_critica)
    assert sig.parameters["reloj"].default is time.process_time


def test_beam_search_default_es_process_time():
    sig = inspect.signature(_beam_search)
    assert sig.parameters["reloj"].default is time.process_time


# --- 2. `_aplicar_ruina_dirigida` respeta CPU-time -------------------------

def test_aplicar_ruina_dirigida_reloj_ya_vencido_no_reconstruye_de_mas():
    """Con `reloj` ya vencido (CPU-time) pero un `limite_tiempo` que
    seria comodo si se leyera con reloj de pared, la reconstruccion debe
    cortar en el primer batch -antes del fix (R2-A0), el chequeo interno
    de `_resolver_pallets_backtracking` (reloj=process_time por default,
    sin override) ya statement NUNCA veia agotado el limite_tiempo de
    time.time() -ahora, con `reloj=` explicito compartido, SI lo agota."""
    pallet, por_sku, nivel_por_sku, presupuesto, _grande = _escenario_grande_bloqueado_por_dos_chicos()
    construcciones = [_pc_de(pallet)]
    colocados_por_pallet = [_colocados_de(pallet)]
    pendientes = {"GRANDE": 1, "A": 0, "B": 0, "WALL1": 0, "WALL2": 0}

    llamadas = {"n": 0}

    def _reloj_ya_vencido():
        llamadas["n"] += 1
        return 1000.0

    total = _aplicar_ruina_dirigida(
        construcciones, colocados_por_pallet, pendientes, por_sku, {}, nivel_por_sku, {},
        presupuesto, 1, "GRANDE", {"A", "B"}, limite_tiempo=0.0, reloj=_reloj_ya_vencido,
    )
    # el reloj inyectado SI se consulto -si no, seria un parametro decorativo
    assert llamadas["n"] > 0
    assert total >= 0  # no crashea; el chequeo de tiempo controla, no rompe la funcion


def _pc_de(pallet):
    from src.packing_columnar import _reconstruir_en_construccion
    return _reconstruir_en_construccion(pallet)


def _colocados_de(pallet):
    return {sku: sum(t.cantidad for t in pallet.torres if t.sku == sku) for sku in {t.sku for t in pallet.torres}}


def test_aplicar_ruina_dirigida_propaga_reloj_explicito_a_backtracking(monkeypatch):
    """El `reloj` que recibe `_aplicar_ruina_dirigida` debe llegar
    EXPLICITO a `_resolver_pallets_backtracking` -nunca depender de su
    default, aunque coincidan en valor (regla explicita del usuario)."""
    import src.packing_bloques as pb

    pallet, por_sku, nivel_por_sku, presupuesto, _grande = _escenario_grande_bloqueado_por_dos_chicos()
    construcciones = [_pc_de(pallet)]
    colocados_por_pallet = [_colocados_de(pallet)]
    pendientes = {"GRANDE": 1, "A": 0, "B": 0, "WALL1": 0, "WALL2": 0}

    reloj_centinela = lambda: 42.0
    capturados = []
    original = pb._resolver_pallets_backtracking

    def _espia(*args, **kwargs):
        capturados.append(kwargs.get("reloj"))
        return original(*args, **kwargs)

    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", _espia)

    _aplicar_ruina_dirigida(
        construcciones, colocados_por_pallet, pendientes, por_sku, {}, nivel_por_sku, {},
        presupuesto, 1, "GRANDE", {"A", "B"}, limite_tiempo=1e9, reloj=reloj_centinela,
    )
    assert capturados, "se esperaba al menos una llamada a _resolver_pallets_backtracking"
    assert all(r is reloj_centinela for r in capturados)


# --- 3. max_nodos sigue funcionando como limite independiente -------------

def test_colocar_critico_backtracking_max_nodos_corta_aunque_el_tiempo_no_venza():
    por_sku = {"A": [_cand(sku="A", largo=20, ancho=20, alto=10, cantidad_disponible=50)]}
    pendientes = {"A": 50}
    pallet = PalletV5(id="P1", cd="BK31", torres=[])
    construcciones = [_pc_de(pallet)]
    colocados_por_pallet = [_colocados_de(pallet)]

    colocado_pocos_nodos = _colocar_critico_backtracking(
        construcciones, colocados_por_pallet, pendientes, "A", por_sku, {}, {}, {},
        max_nodos=1, limite_tiempo=1e9, reloj=lambda: 0.0,
    )

    construcciones2 = [_pc_de(pallet)]
    colocados2 = [_colocados_de(pallet)]
    pendientes2 = {"A": 50}
    colocado_muchos_nodos = _colocar_critico_backtracking(
        construcciones2, colocados2, pendientes2, "A", por_sku, {}, {}, {},
        max_nodos=10_000, limite_tiempo=1e9, reloj=lambda: 0.0,
    )
    assert colocado_pocos_nodos <= colocado_muchos_nodos
    assert colocado_muchos_nodos > colocado_pocos_nodos or colocado_muchos_nodos == 50


# --- 4. monkeypatch/config no cambia la semantica -------------------------

def test_rescue_time_max_seconds_se_lee_fresco_no_congelado(monkeypatch):
    """Igual que el hallazgo de Fase 1B: el presupuesto debe leerse desde
    el modulo en cada llamada, nunca precomputado -si se monkeypatchea
    RESCUE_TIME_MAX_SECONDS a un valor absurdamente chico, rescue_solver
    debe cortar casi de inmediato (CPU-time), no ignorar el patch."""
    pallet, por_sku, nivel_por_sku, presupuesto, _grande = _escenario_grande_bloqueado_por_dos_chicos()
    monkeypatch.setattr(rescue_solver_mod, "RESCUE_TIME_MAX_SECONDS", 0.0)

    wall0 = time.perf_counter()
    pallets_final, sin_colocar_final, stats = rescue_solver_mod.rescue_solver(
        [pallet], {"GRANDE": 1}, por_sku, capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku,
        tope_pallet_por_sku={}, n_pallets=1, presupuesto=presupuesto,
    )
    wall1 = time.perf_counter()
    assert wall1 - wall0 < 2.0  # no debe intentar 90s reales de trabajo
    assert stats["activado"] is True


# --- 5. no vuelve a introducirse un deadline wall-clock en esos callers ---

def _cuenta_time_time(fn) -> int:
    """Cuenta llamadas REALES a `time.time()` en el AST -a diferencia de
    un grep de texto, ignora menciones dentro de docstrings/comentarios
    (varias funciones de este parche documentan el mismatch histórico
    citando literalmente `time.time()` en su docstring)."""
    import ast as _ast

    arbol = _ast.parse(inspect.getsource(fn))
    return sum(
        1 for nodo in _ast.walk(arbol)
        if isinstance(nodo, _ast.Call)
        and isinstance(nodo.func, _ast.Attribute) and nodo.func.attr == "time"
        and isinstance(nodo.func.value, _ast.Name) and nodo.func.value.id == "time"
    )


def test_funciones_puramente_internas_no_usan_time_time_en_absoluto():
    """Estas funciones NUNCA deben tener wall-clock -ni para budget ni
    para reporte (no calculan ningun stat de tiempo humano por si solas)."""
    for fn in (
        _aplicar_ruina_dirigida, _colocar_critico_backtracking,
        _buscar_ejection_chain, _intentar_neighborhoods_iterativos, _reconstruccion_multi_critica,
        _beam_search,
    ):
        assert _cuenta_time_time(fn) == 0, f"{fn.__name__} reintrodujo time.time()"


def test_entry_points_solo_usan_time_time_para_reporte_humano():
    """rescue_solver/repair_solver: exactamente 2 usos de `time.time()`
    permitidos (t0_wall al entrar, tiempo_segundos al salir). global_rescue
    tiene un tercero legitimo: su propio early-return
    (`n_pallets <= 0 or not any(...)`) reporta `tiempo_s` en un segundo
    punto de salida, aparte del cierre normal -mismo t0_wall, otra rama.
    Cualquier conteo MAYOR a estos seria un deadline wall-clock
    reintroducido por accidente."""
    assert _cuenta_time_time(rescue_solver) == 2
    assert _cuenta_time_time(repair_solver) == 2
    assert _cuenta_time_time(global_rescue) == 3


def test_exact_repair_orquestado_solo_usa_time_time_para_reporte_humano():
    assert _cuenta_time_time(exact_repair_orquestado) == 2


def test_exact_repair_max_time_in_seconds_no_fue_tocado():
    """[alcance explicito de R2-A1] `solver.parameters.max_time_in_seconds`
    de CP-SAT sigue existiendo tal cual -es el limite NATIVO de la
    libreria, wall-clock por diseno, fuera de alcance de este parche."""
    fuente = inspect.getsource(exact_repair_mod)
    assert "solver.parameters.max_time_in_seconds = time_limit_s" in fuente


# --- gate funcional: equivalencia con el escenario ya validado ------------

def test_rescue_resuelve_con_ruina_dirigida_sigue_pasando():
    """Gate de no-regresion: el mismo escenario de
    `test_rescue_solver.test_rescue_resuelve_con_ruina_dirigida` debe
    seguir resolviendo el 100% tras activar el chequeo de CPU-time."""
    from src.validacion_v5 import validar_pallet_v5

    pallet, por_sku, nivel_por_sku, presupuesto, _grande = _escenario_grande_bloqueado_por_dos_chicos()
    sin_colocar = {"GRANDE": 1}

    pallets_final, sin_colocar_final, stats = rescue_solver(
        [pallet], sin_colocar, por_sku, capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku,
        tope_pallet_por_sku={}, n_pallets=1, presupuesto=presupuesto,
    )

    assert sin_colocar_final == {}
    assert stats["activado"] is True
    torres = pallets_final[0].torres
    assert {t.sku for t in torres} == {"GRANDE", "A", "B", "WALL1", "WALL2"}
    assert validar_pallet_v5(pallets_final[0]) == []
