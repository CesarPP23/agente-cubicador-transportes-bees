"""[PATCH V6.05, Fase 2.1] Auditoría de completitud del espacio de
búsqueda de Global Rescue -pedida explícitamente por el usuario DESPUÉS de
ver que BK52 (Fase 2) se quedó en 105/114, para distinguir:

    A. la solución existe dentro del espacio que Global Rescue puede
       representar, pero Beam Search la está perdiendo;
    vs
    B. Global Rescue directamente no puede representar determinadas
       colocaciones válidas, independientemente del ancho del Beam.

Cubre, en orden: (1) sanidad de la instrumentación por profundidad
agregada a `_beam_search` (aditiva, no cambia ningún resultado -ver
`tests/test_global_rescue.py` para la cobertura de comportamiento, que
sigue en 25/25 verde sin tocar); (2) completitud de los tamaños de lote
`{1, ceil(max/2), max}`; (3)/(4) el oráculo de candidatos independiente de
MaxRects (`src/global_rescue_oracle.py`) contra el generador real; (5) el
caso explícito de soporte por unión de 2+ cajas."""
import config
import src.global_rescue as gr
from models import PalletV5
from src.global_rescue_oracle import enumerar_candidatos_oraculo
from src.packing_bloques import _cuboide_admite_candidato
from src.packing_columnar import _CuboidLibre, _PalletEnConstruccion, _actualizar_libres_maxrects
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_pallet_v5

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


# --- (1) Sanidad de la instrumentación por profundidad --------------------

def test_depth_log_se_llena_sin_cambiar_el_resultado():
    """[punto 1 del pedido] La instrumentación agregada a `_beam_search`
    (`depth_log_por_reinicio`, `first_depth_zero_candidates_por_reinicio`,
    `first_depth_frontier_zero_por_reinicio`) debe aparecer poblada, con
    los conteos por etapa (`children_raw` >= `children_after_candidate_
    filter` >= `children_after_pruning` >= `children_after_transposition`
    >= `beam_kept`, y `beam_kept + beam_dropped == children_after_
    transposition`) -y el resultado final (`faltantes`, `motivo_stop`)
    debe ser IDÉNTICO al que ya devolvía la Fase 1.2 (ver `test_global_
    rescue.py::test_global_rescue_resuelve_caso_sintetico_simple_al_100_
    por_ciento`, mismo escenario)."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=2)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=3)],
    }
    nivel_por_sku = {"A": 6, "B": 6}
    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"A": 2, "B": 3}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="DEPTHLOG", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}  # comportamiento sin cambios respecto a Fase 1.2
    assert stats["motivo_stop"] == "completo"
    assert len(pallets) == 1
    assert validar_pallet_v5(pallets[0]) == []

    logs = stats["depth_log_por_reinicio"]
    assert len(logs) == 1  # un solo reinicio, se completó en el primero
    assert len(logs[0]) >= 1
    for entrada in logs[0]:
        assert entrada["children_raw"] >= entrada["children_after_candidate_filter"]
        assert entrada["children_after_pruning"] >= entrada["children_after_transposition"]
        assert entrada["beam_kept"] + entrada["beam_dropped"] == entrada["children_after_transposition"]
        assert entrada["cajas_colocadas_best"] >= 0
        assert entrada["deuda_best"] >= 0


def test_prune_by_sku_atribuye_la_poda_al_sku_correcto():
    """[punto 1 del pedido, "prune_by_sku"] Escenario determinista con un
    SKU permanentemente estancado (BLOQUEADO) -toda poda de esta corrida
    tiene que atribuirse a "BLOQUEADO" en `depth_log[...]["prune_by_sku"]",
    nunca a DISPONIBLE (que sí puede moverse)."""
    por_sku = {
        "DISPONIBLE": [_cand("DISPONIBLE", 40, 30, 20, cantidad_disponible=2)],
        "BLOQUEADO": [_cand("BLOQUEADO", 500, 500, 20, cantidad_disponible=1)],
    }
    nivel_por_sku = {"DISPONIBLE": 6, "BLOQUEADO": 6}
    _pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"DISPONIBLE": 2, "BLOQUEADO": 1}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="PRUNEBYSKU", presupuesto=PRESUPUESTO,
    )

    assert faltantes.get("BLOQUEADO") == 1
    podas_totales: dict[str, int] = {}
    for log in stats["depth_log_por_reinicio"]:
        for entrada in log:
            for sku, cantidad in entrada["prune_by_sku"].items():
                podas_totales[sku] = podas_totales.get(sku, 0) + cantidad
    assert podas_totales.get("BLOQUEADO", 0) > 0
    assert "DISPONIBLE" not in podas_totales


# --- (2) Completitud de tamaños de lote ------------------------------------

def _pc_franja(w=40, h=40, d=70):
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    return _PalletEnConstruccion(pallet=pallet, libres=[_CuboidLibre(0, 0, 0, w, h, d)])


def _d_admitido(pc, cand_d, nivel):
    return any(_cuboide_admite_candidato(pc.pallet, c, cand_d, None, 6, nivel) for c in pc.libres)


def test_batch_1_ceil_mitad_max_SI_alcanza_el_100_si_nada_se_interpone():
    """[punto 2 del pedido] Primero, la premisa positiva: con lote máximo
    7 (batch set {1,4,7}) para SKU A (alto=10) sobre un cuboide de
    profundidad 70, colocar EXACTAMENTE 3 unidades de A (cantidad que NO
    está en {1,4,7}) SÍ es alcanzable descomponiéndola en tres pasos de
    batch=1 consecutivos, SIN que nada se interponga -el resultado final
    (deja 40 de profundidad libre) es geométricamente IDÉNTICO a haber
    podido pedir batch=3 directamente. Esto prueba que el conjunto {1,
    mitad, máximo} no es, por sí solo, una limitación de REPRESENTACIÓN
    -"1" siempre está disponible y repetirlo alcanza cualquier cantidad
    intermedia, en MÚLTIPLES niveles del árbol."""
    cand_a = _cand("A", 40, 40, 10, cantidad_disponible=10, max_verticales=10)
    cand_d = _cand("D", 40, 40, 40, cantidad_disponible=1, max_verticales=10)
    nivel = {"A": 6, "D": 6}

    # Caso atómico: si pudiéramos pedir batch=3 directo.
    pc_atomico = _pc_franja()
    opciones = gr._generar_candidatos_multi_pallet(
        [pc_atomico], [{}], {"A": 3}, "A", {"A": [cand_a]}, {}, nivel, {},
    )
    _sobra, _pidx, idx_libre, *_resto, _cand_ret, _max_lote = opciones[0]
    pc_atomico.colocar(cand_a, 3, idx_libre)
    assert _d_admitido(pc_atomico, cand_d, nivel) is True  # premisa: 3 es la cantidad "correcta"

    # Caso incremental, SIN interrupción: 1, luego 1, luego 1.
    pc_incremental = _pc_franja()
    restante = 3
    while restante > 0:
        opciones = gr._generar_candidatos_multi_pallet(
            [pc_incremental], [{}], {"A": restante}, "A", {"A": [cand_a]}, {}, nivel, {},
        )
        _sobra, _pidx, idx_libre, *_resto, _cand_ret, _max_lote = opciones[0]
        pc_incremental.colocar(cand_a, 1, idx_libre)
        restante -= 1
    assert _d_admitido(pc_incremental, cand_d, nivel) is True


def test_batch_incremental_SI_puede_perder_el_100_si_otro_sku_se_interpone():
    """[punto 2 del pedido, hallazgo real] Mismo escenario, pero con un
    SKU competidor (C, mismo footprint/alto que A) que se INTERCALA entre
    los pasos de batch=1 de A -algo perfectamente legal en el árbol de
    búsqueda real (MRV puede elegir a C en el medio si en ese momento es
    más restringido que A; Beam Search mantiene múltiples ramas y no
    "reserva" nada para A). El resultado final (A=0,C=10,A=20,A=30) deja
    solo 30 de profundidad libre -D (necesita 40) YA NO entra, aunque la
    cantidad final de A colocada (3) sea la MISMA que en el caso limpio.

    [Conclusión honesta, alcance de esta prueba] Esto NO prueba que {1,
    mitad, máximo} sea representacionalmente incompleto (categoría B) -la
    secuencia completa (A,C,A,A) es una trayectoria perfectamente
    alcanzable en el árbol de estados, cada paso es una transición legal.
    Prueba que alcanzar una cantidad intermedia fuera de {1,mitad,máximo}
    depende de que la búsqueda NO intercale otra SKU en el medio -un
    problema de qué rama sobrevive el score/MRV/beam (categoría A), no de
    qué se puede representar. Se reporta así, sin corregir nada todavía
    (pedido explícito del usuario)."""
    cand_a = _cand("A", 40, 40, 10, cantidad_disponible=10, max_verticales=10)
    cand_c = _cand("C", 40, 40, 10, cantidad_disponible=10, max_verticales=10)
    cand_d = _cand("D", 40, 40, 40, cantidad_disponible=1, max_verticales=10)
    nivel = {"A": 6, "C": 6, "D": 6}

    pc = _pc_franja()
    # A(1)
    opciones = gr._generar_candidatos_multi_pallet([pc], [{}], {"A": 3}, "A", {"A": [cand_a]}, {}, nivel, {})
    _sobra, _pidx, idx_libre, *_resto = opciones[0]
    pc.colocar(cand_a, 1, idx_libre)
    # C(1) -se intercala en el cuboide que A hubiera usado a continuación.
    opciones = gr._generar_candidatos_multi_pallet([pc], [{}], {"C": 1}, "C", {"C": [cand_c]}, {}, nivel, {})
    _sobra, _pidx, idx_libre, *_resto = opciones[0]
    pc.colocar(cand_c, 1, idx_libre)
    # A(1), A(1) -termina de completar su demanda de 3.
    for _ in range(2):
        opciones = gr._generar_candidatos_multi_pallet([pc], [{}], {"A": 2}, "A", {"A": [cand_a]}, {}, nivel, {})
        _sobra, _pidx, idx_libre, *_resto = opciones[0]
        pc.colocar(cand_a, 1, idx_libre)

    assert sum(t.cantidad for t in pc.pallet.torres if t.sku == "A") == 3  # A completó su demanda igual
    assert _d_admitido(pc, cand_d, nivel) is False  # pero D ya no entra -C se comió la altura que faltaba
    assert validar_pallet_v5(pc.pallet) == []  # sigue siendo geometría válida, solo que subóptima


def test_fix_cajas_fantasma_usa_cantidad_real_no_el_batch_solicitado():
    """[PATCH V6.06, sección 11 -corrección del hallazgo de Fase 2.1]
    `_generar_candidatos_multi_pallet` calcula `max_lote` SOLO a partir de
    la altura del cuboide libre -nunca mira `cand.max_cajas_verticales`.
    `crear_torre` (torres.py) SÍ lo aplica, silenciosamente: `cantidad =
    min(cantidad, max_cajas_verticales, cantidad_disponible)`. Con
    `max_cajas_verticales=3` y un cuboide que geométricamente permitiría
    hasta 7 (batch set {1,4,7}), los batches 4 y 7 pedidos a `crear_torre`
    terminan colocando solo 3 cajas reales.

    Antes de este fix (Fase 2.1, `test_bug_estructural_max_cajas_
    verticales_no_se_refleja_en_cajas_colocadas`, ahora reemplazado):
    `hijo.cajas_colocadas` quedaba en 4 o 7 -cajas fantasma que nunca se
    colocaron. Con el fix (sección 11: "la fuente de verdad debe ser
    cantidad_real_colocada"), `_expandir_estado` lee `torre.cantidad`
    (lo que `crear_torre` REALMENTE puso) en vez del `batch` pedido -los
    batches 4 y 7 ahora colapsan en el MISMO resultado real (3 cajas), así
    que solo aparecen 2 valores distintos de `cajas_colocadas` (1 y 3),
    nunca 4 ni 7, y `torre.cantidad` coincide EXACTO con `hijo.cajas_
    colocadas` en todos los casos."""
    cand_a = _cand("A", 40, 40, 10, cantidad_disponible=10, max_verticales=3)  # tope < lo que la altura permite
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet, libres=[_CuboidLibre(0, 0, 0, 40, 40, 70)])  # max_lote geométrico = 7
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 10})

    hijos = gr._expandir_estado(estado, {"A": [cand_a]}, {}, {"A": 6}, {}, "footprint", stats=None)
    cajas_colocadas_vistas = sorted({h.cajas_colocadas for h in hijos})
    assert cajas_colocadas_vistas == [1, 3]  # nunca 4 ni 7 -el batch pedido ya no se cuenta a ciegas

    for hijo in hijos:
        torre = hijo.construcciones[0].pallet.torres[-1]
        assert torre.cantidad == hijo.cajas_colocadas  # fuente de verdad = cantidad REAL, siempre consistente
        assert hijo.pendientes["A"] == 10 - hijo.cajas_colocadas  # pendientes tampoco se descuenta de más


# --- (3)/(4) Oráculo de candidatos independiente de MaxRects ---------------

def test_oraculo_coincide_con_maxrects_en_un_caso_simple():
    """[sanidad del oráculo] En un caso simple sin ambigüedad (pallet
    vacío, un SKU que cabe cómodo), el oráculo y MaxRects deben coincidir
    en que SÍ hay candidato -el oráculo no es una fuente de falsos
    negativos en el caso trivial."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet, libres=[_CuboidLibre(0, 0, 0, 100, 100, 100)])
    cand_a = _cand("A", 40, 30, 20, cantidad_disponible=1)
    nivel = {"A": 6}

    admite_maxrects = any(_cuboide_admite_candidato(pc.pallet, c, cand_a, None, 6, nivel) for c in pc.libres)
    posiciones = enumerar_candidatos_oraculo(
        pallet, "A", [cand_a], tope_capa=None, nivel_sku=6, nivel_por_sku=nivel,
        tope_pallet=float("inf"), ya_en_pallet=0, presupuesto=100.0,
    )
    assert admite_maxrects is True
    assert len(posiciones) > 0


def test_oraculo_respeta_overlap_altura_y_jerarquia():
    """[sanidad del oráculo -no debe ser un falso positivo] El oráculo
    debe seguir rechazando: (a) una posición que se solaparía con una
    torre ya puesta, (b) una altura que excede el presupuesto, (c) una
    violación de jerarquía (algo pesado encima de algo liviano)."""
    cand_pesado = _cand("PESADO", 40, 40, 20, cantidad_disponible=1)
    cand_liviano = _cand("LIVIANO", 40, 40, 20, cantidad_disponible=1)
    torre_liviano = crear_torre(cand_liviano, x=0, y=0, z=0, cantidad=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[torre_liviano], altura_final=20 + config.ALTURA_PALLET_VACIO)
    nivel = {"PESADO": 1, "LIVIANO": 6}  # PESADO = nivel 1 (más pesado) -no puede ir sobre LIVIANO (nivel 6)

    # (a) overlap: pedir la MISMA posición que ya ocupa LIVIANO, a z=0.
    posiciones_overlap = enumerar_candidatos_oraculo(
        pallet, "LIVIANO", [cand_liviano], tope_capa=None, nivel_sku=6, nivel_por_sku=nivel,
        tope_pallet=float("inf"), ya_en_pallet=1, presupuesto=200.0,
    )
    assert not any(p.x == 0 and p.y == 0 and p.z == 0 for p in posiciones_overlap)

    # (b) altura: presupuesto muy chico, nada debe caber elevado.
    posiciones_altura = enumerar_candidatos_oraculo(
        pallet, "PESADO", [cand_pesado], tope_capa=None, nivel_sku=1, nivel_por_sku=nivel,
        tope_pallet=float("inf"), ya_en_pallet=0, presupuesto=25.0,
    )
    assert not any(p.z > 0 for p in posiciones_altura)

    # (c) jerarquía: PESADO (nivel 1) no puede apoyarse sobre LIVIANO (nivel 6).
    posiciones_jerarquia = enumerar_candidatos_oraculo(
        pallet, "PESADO", [cand_pesado], tope_capa=None, nivel_sku=1, nivel_por_sku=nivel,
        tope_pallet=float("inf"), ya_en_pallet=0, presupuesto=200.0,
    )
    assert not any(p.z > 0 for p in posiciones_jerarquia)  # ninguna posición ELEVADA es válida para PESADO acá


# --- (5) Soporte por unión de 2+ cajas --------------------------------------

def test_soporte_por_union_de_dos_cajas_validator_maxrects_oraculo():
    """[punto 5 del pedido, EXPLÍCITO] Una caja superior (TOP, 80x40)
    queda 100% soportada por la UNIÓN de dos cajas inferiores (A y B, cada
    una 40x40) -ninguna de las dos por sí sola cubre la huella completa de
    TOP, pero juntas sí.

    Respuestas (no se asume que las 3 coincidan, y de hecho NO coinciden):
    - validar_pallet_v5 lo acepta: SÍ -`_area_cubierta_por_soporte` suma
      la unión de TODAS las torres de soporte, no una sola.
    - generador MaxRects puede producirlo: NO -cada cuboide libre viene de
      la fragmentación de UNA sola caja (A o B), nunca de la unión de dos;
      ningún cuboide libre individual cubre los 80 de ancho que TOP
      necesita, así que `_cuboide_admite_candidato` nunca lo admite en
      NINGÚN cuboide de la lista.
    - oráculo independiente puede encontrarlo: SÍ -sus posiciones salen de
      los bordes de las cajas YA puestas (no de una lista de cuboides), y
      valida soporte contra la unión real de `pallet.torres`."""
    cand_a = _cand("A", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_b = _cand("B", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}

    torre_a = crear_torre(cand_a, x=0, y=0, z=0, cantidad=1)
    torre_b = crear_torre(cand_b, x=40, y=0, z=0, cantidad=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[torre_a, torre_b], altura_final=20 + config.ALTURA_PALLET_VACIO)

    # --- validador ---
    torre_top = crear_torre(cand_top, x=0, y=0, z=20, cantidad=1)
    pallet_con_top = PalletV5(
        id="P0", cd="CD", torres=[torre_a, torre_b, torre_top],
        altura_final=20 + 15 + config.ALTURA_PALLET_VACIO,
    )
    assert validar_pallet_v5(pallet_con_top) == []  # SÍ lo acepta

    # --- generador MaxRects (cuboide inicial ACOTADO a la región de A+B,
    # para que no haya piso de sobra en otro lado que le dé a TOP una
    # salida trivial y sin relación con el soporte por unión) ---
    libres = [_CuboidLibre(0, 0, 0, 80, 40, 185.08)]
    libres = _actualizar_libres_maxrects(libres, 0, 0, 0, 40, 40, 20)
    libres = _actualizar_libres_maxrects(libres, 40, 0, 0, 40, 40, 20)
    admite_maxrects = any(_cuboide_admite_candidato(pallet, c, cand_top, None, 6, nivel) for c in libres)
    assert admite_maxrects is False  # NO puede producirlo

    # --- oráculo independiente ---
    posiciones = enumerar_candidatos_oraculo(
        pallet, "TOP", [cand_top], tope_capa=None, nivel_sku=6, nivel_por_sku=nivel,
        tope_pallet=float("inf"), ya_en_pallet=0, presupuesto=200.0,
    )
    assert any(p.x == 0 and p.y == 0 and p.z == 20 for p in posiciones)  # SÍ lo encuentra
