"""PATCH V6.02 -Rescue Solver BK31 (Most-Constrained-First, branching
adaptativo, Conflict-Directed LNS). Tests de la sección 13."""
import config
from models import PalletV5
from src.diagnostico_no_colocadas import (
    EDGE_OVERHANG,
    NO_FREE_RECT_FIT,
    diagnosticar,
)
from src.packing_bloques import COMBINACION_PALLETS_OPCIONES_POR_SKU, _resolver_pallets_backtracking
from src.packing_columnar import _reconstruir_en_construccion
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_pallet_v5
from src.rescue_solver import (
    RESCUE_OPCIONES_SKU_CRITICO,
    RESCUE_OPCIONES_SKU_NORMAL,
    _aplicar_ruina_dirigida,
    _blockers_para_posicion,
    _colocar_critico_backtracking,
    _generar_batch_sizes,
    _opciones_directas_para_sku,
    _rankear_conflictos,
    rescue_solver,
)


def _cand(sku="X", largo=30, ancho=30, alto=20, cantidad_disponible=10):
    return TorreCandidate(sku, "BK31", "L×A", largo, ancho, alto, 10, cantidad_disponible, 1.0)


def _pallet_con_hueco_chico() -> PalletV5:
    """Pallet casi lleno: solo queda un hueco de 20x20 (esquina superior
    derecha) -mucho más chico que el envelope extendido (124x104), pero
    también mucho más chico que una caja de 30x30."""
    grande = _cand(sku="RELLENO", largo=100, ancho=80, alto=20)
    torre = crear_torre(grande, x=0, y=0, cantidad=1)
    return PalletV5(id="P1", cd="BK31", torres=[torre], altura_final=config.ALTURA_PALLET_VACIO + 20)


# --- 13.1: diagnóstico correcto -----------------------------------------

def test_diagnostico_no_free_rect_fit_no_edge_overhang():
    """Caja de 30x30 (bien dentro del envelope 124x104) que no cabe en
    ningún free rectangle disponible -debe clasificarse NO_FREE_RECT_FIT,
    nunca EDGE_OVERHANG."""
    pallet = _pallet_con_hueco_chico()
    cand = _cand(sku="PICARA", largo=30, ancho=30)
    por_sku = {"PICARA": [cand]}

    diag = diagnosticar(
        pallets=[pallet], sin_colocar={"PICARA": 1}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku={"PICARA": 6, "RELLENO": 6}, tope_pallet_por_sku={},
    )
    assert diag["PICARA"][NO_FREE_RECT_FIT] > 0
    assert diag["PICARA"][EDGE_OVERHANG] == 0


def test_diagnostico_edge_overhang_cuando_la_caja_excede_el_envelope():
    """Caja de 130cm de largo -excede el envelope extendido (124) sea cual
    sea el estado del layout -eso SÍ es EDGE_OVERHANG, incluso en un
    pallet completamente vacío."""
    pallet = PalletV5(id="P1", cd="BK31", torres=[])
    cand = _cand(sku="GIGANTE", largo=130, ancho=30)
    por_sku = {"GIGANTE": [cand]}

    diag = diagnosticar(
        pallets=[pallet], sin_colocar={"GIGANTE": 1}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku={"GIGANTE": 6}, tope_pallet_por_sku={},
    )
    assert diag["GIGANTE"][EDGE_OVERHANG] > 0


# --- 13.2: branching normal intacto --------------------------------------

def test_branching_normal_no_cambio():
    """Fuera de rescue, `COMBINACION_PALLETS_OPCIONES_POR_SKU` sigue en 1
    -el rescue nunca la toca (constantes separadas, `RESCUE_OPCIONES_SKU_
    CRITICO`/`RESCUE_OPCIONES_SKU_NORMAL`)."""
    assert COMBINACION_PALLETS_OPCIONES_POR_SKU == 1
    assert RESCUE_OPCIONES_SKU_CRITICO == 3
    assert RESCUE_OPCIONES_SKU_NORMAL == 1


# --- 13.3: SKU crítico obtiene alternativas -------------------------------

def _pallet_con_tres_huecos_para(sku_footprint_largo, sku_footprint_ancho):
    """3 cuboides libres DISTINTOS, cada uno capaz de admitir una caja de
    ese footprint (separados por paredes finas de un SKU inerte)."""
    torres = []
    pared = _cand(sku="PARED", largo=1, ancho=100, alto=200)
    for i, x0 in enumerate([0, sku_footprint_largo + 2, 2 * (sku_footprint_largo + 2)]):
        if i > 0:
            torres.append(crear_torre(pared, x=x0 - 1, y=0, cantidad=1))
    pallet = PalletV5(id="P1", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 200)
    return pallet


def test_sku_critico_explora_mas_de_una_ubicacion():
    """En rescue, un SKU con varios cuboides libres distintos obtiene
    hasta `RESCUE_OPCIONES_SKU_CRITICO` opciones -con `RESCUE_OPCIONES_SKU_
    NORMAL` (1) solo se conserva la mejor."""
    pallet = _pallet_con_tres_huecos_para(20, 20)
    cand = _cand(sku="CRIT", largo=20, ancho=20, alto=10)
    por_sku = {"CRIT": [cand]}
    construcciones = [_reconstruir_en_construccion(pallet)]
    colocados_por_pallet = [{}]
    pendientes = {"CRIT": 5}

    opciones_criticas = _opciones_directas_para_sku(
        construcciones, colocados_por_pallet, pendientes, "CRIT", por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku={"CRIT": 6, "PARED": 6}, tope_pallet_por_sku={},
        opciones_max=RESCUE_OPCIONES_SKU_CRITICO,
    )
    opciones_normales = _opciones_directas_para_sku(
        construcciones, colocados_por_pallet, pendientes, "CRIT", por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku={"CRIT": 6, "PARED": 6}, tope_pallet_por_sku={},
        opciones_max=RESCUE_OPCIONES_SKU_NORMAL,
    )
    assert len(opciones_criticas) == 3
    assert len(opciones_normales) == 1


# --- 13.4: batch parcial ---------------------------------------------------

def _escenario_columna_completa_bloquea():
    """WALL divide el pallet en dos franjas: IZQUIERDA (ancha, admite a
    BLOCKER, footprint 60x80) y DERECHA (angosta, 59cm -no admite a
    BLOCKER, solo a CRIT en su orientación chica 50x50). CRIT (alto=68,
    pendiente=3) cabe HOLGADO en altura (presupuesto ~205cm) -si toma
    TODO lo que le entra de una vez en la franja izquierda (3, la llena
    casi entera), no queda lugar ahí para BLOCKER (alto=100). Si toma
    SOLO 1 ahí (lote parcial) y el resto en la franja derecha, BLOCKER sí
    entra encima."""
    wall_cand = TorreCandidate("WALL", "BK31", "L×A", 3.0, 100.0, 1.0, 1, 1, 1.0)
    wall = crear_torre(wall_cand, x=60, y=0, z=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="BK31", torres=[wall], altura_final=config.ALTURA_PALLET_VACIO + 1)
    construcciones = [_reconstruir_en_construccion(pallet)]
    colocados_por_pallet = [{}]

    crit_a = TorreCandidate("CRIT", "BK31", "A", 60.0, 80.0, 68.0, 10, 3, 1.0)
    crit_b = TorreCandidate("CRIT", "BK31", "B", 50.0, 50.0, 68.0, 10, 3, 1.0)
    blocker_cand = TorreCandidate("BLOCKER", "BK31", "L×A", 60.0, 80.0, 100.0, 10, 1, 1.0)
    por_sku = {"CRIT": [crit_a, crit_b], "BLOCKER": [blocker_cand]}
    nivel_por_sku = {"CRIT": 6, "BLOCKER": 6, "WALL": 6}
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO
    return construcciones, colocados_por_pallet, por_sku, nivel_por_sku, presupuesto


def test_generar_batch_sizes():
    assert _generar_batch_sizes(0) == []
    assert _generar_batch_sizes(1) == [1]
    assert _generar_batch_sizes(2) == [1, 2]
    assert _generar_batch_sizes(5) == [1, 3, 5]
    assert 1 <= min(_generar_batch_sizes(9)) and max(_generar_batch_sizes(9)) == 9


def test_lote_completo_sin_exploracion_parcial_no_llega_a_100_por_ciento():
    """Control: sin explorar lotes parciales (siempre el máximo), esta
    demanda NO se completa -confirma que el escenario realmente necesita
    la sección 6, no es un caso que igual resolvería la reconstrucción
    general por otra vía."""
    construcciones, colocados_por_pallet, por_sku, nivel_por_sku, presupuesto = _escenario_columna_completa_bloquea()
    pendientes = {"CRIT": 3, "BLOCKER": 1}
    opciones = _opciones_directas_para_sku(
        construcciones, colocados_por_pallet, pendientes, "CRIT", por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={}, opciones_max=1,
    )
    _, pidx, idx_libre, cand, max_lote = opciones[0]
    construcciones[pidx].colocar(cand, max_lote, idx_libre)
    pendientes["CRIT"] -= max_lote
    colocados_por_pallet[pidx]["CRIT"] = colocados_por_pallet[pidx].get("CRIT", 0) + max_lote

    _resolver_pallets_backtracking(
        construcciones, colocados_por_pallet, pendientes, por_sku, {}, nivel_por_sku, {}, presupuesto, 1,
    )
    assert sum(pendientes.values()) > 0  # se queda corto


def test_rescue_batch_parcial_resuelve_columna_completa_bloqueada():
    """PATCH V6.02, sección 13.4: el rescue (que sí explora lotes
    parciales, sección 6) resuelve al 100% el mismo escenario donde
    comprometer siempre la columna completa se queda corto."""
    construcciones, colocados_por_pallet, por_sku, nivel_por_sku, presupuesto = _escenario_columna_completa_bloquea()
    pendientes = {"CRIT": 3, "BLOCKER": 1}
    total = _aplicar_ruina_dirigida(
        construcciones, colocados_por_pallet, pendientes, por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        presupuesto=presupuesto, n_pallets=1, sku_critico="CRIT", blocker_skus=set(), limite_tiempo=None,
    )
    assert total == 4
    assert sum(pendientes.values()) == 0
    pallet = construcciones[0].pallet
    assert validar_pallet_v5(pallet) == []  # sin flotación ni overlap (13.6)


# --- 13.5: conflict-directed ruin ------------------------------------------

def _escenario_grande_bloqueado_por_dos_chicos():
    """GRANDE (40x30) solo cabe en la esquina x:[0,40],y:[0,30] -el resto
    del pallet está tapado por dos "paredes" (WALL1/WALL2, SKUs normales,
    con su propio candidato -pueden ser retiradas y repuestas como
    cualquier otra) que cubren TODO lo demás. Esa esquina ya está ocupada
    por A (0-20) y B (20-40) -son los únicos blockers posibles."""
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


def test_conflictos_identifican_blockers_espaciales():
    """SKU grande crítico bloqueado por SKUs ya colocados -el ranking de
    conflictos debe identificar, entre las posiciones objetivo, el
    conjunto exacto de blockers {A, B} (además de otras posiciones más
    baratas que involucran a WALL2, con menos cajas a retirar -sección
    9.3, "menor cantidad de cajas a retirar" primero: WALL2 sola, 1 torre,
    ranquea antes que A+B, 2 torres, aunque WALL2 sea mucho más grande en
    volumen)."""
    pallet, por_sku, nivel_por_sku, presupuesto, grande = _escenario_grande_bloqueado_por_dos_chicos()
    construcciones = [_reconstruir_en_construccion(pallet)]

    conflictos = _rankear_conflictos(construcciones, "GRANDE", [grande], presupuesto=presupuesto)

    assert conflictos
    assert all(len(c[-1]) >= 1 and "GRANDE" not in c[-1] for c in conflictos)
    assert any(c[-1] == {"A", "B"} for c in conflictos)


def test_rescue_resuelve_con_ruina_dirigida():
    """Escenario completo: SKU grande (GRANDE, único lugar posible
    ocupado por A+B) más pequeño para colocar -el rescue debe identificar
    los blockers, retirarlos, colocar GRANDE, y recolocar A/B -terminando
    100% sin flotación."""
    pallet, por_sku, nivel_por_sku, presupuesto, _grande = _escenario_grande_bloqueado_por_dos_chicos()
    sin_colocar = {"GRANDE": 1}

    pallets_final, sin_colocar_final, stats = rescue_solver(
        [pallet], sin_colocar, por_sku, capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku,
        tope_pallet_por_sku={}, n_pallets=1, presupuesto=presupuesto,
    )

    assert sin_colocar_final == {}
    assert stats["activado"] is True
    assert stats["conflictos_evaluados"] > 0
    assert stats["blockers_retirados"] >= 2
    torres = pallets_final[0].torres
    assert {t.sku for t in torres} == {"GRANDE", "A", "B", "WALL1", "WALL2"}
    # 13.6: ninguna solución rescue puede introducir torres flotantes.
    assert validar_pallet_v5(pallets_final[0]) == []
