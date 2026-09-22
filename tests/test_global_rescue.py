"""[PATCH V6.05, Fase 1] Global Rescue -tests SINTÉTICOS (no dependen de
BK52/BK53 reales, eso es Fase 2). Cubren cada pieza de la arquitectura
pedida: Beam Search end-to-end, MRV global, candidatos multi-pallet, lotes
parciales, simetría/transposition table, poda segura, multi-start
determinista y timeout -y, transversal a todas, que el resultado sea
SIEMPRE geométricamente válido (`validar_pallet_v5 == []`)."""
import time

import config
import src.global_rescue as gr
from models import PalletV5
from src.packing_columnar import _PalletEnConstruccion, _reconstruir_en_construccion
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_pallet_v5

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


# --- Beam Search end-to-end -------------------------------------------------

def test_global_rescue_resuelve_caso_sintetico_simple_al_100_por_ciento():
    """Caso trivial: 1 pallet vacío, 2 SKUs que entran cómodos -Global
    Rescue debe llegar a demanda completa, con geometría válida, y
    detenerse por "completo" (sección 18: nunca seguir "optimizando" tras
    el 100%)."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=2)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=3)],
    }
    nivel_por_sku = {"A": 6, "B": 6}
    sin_colocar = {"A": 2, "B": 3}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar=sin_colocar, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="SINTETICO1", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}
    assert stats["motivo_stop"] == "completo"
    assert stats["errores_geometricos"] == 0
    assert len(pallets) == 1
    assert sum(t.cantidad for t in pallets[0].torres) == 5
    assert validar_pallet_v5(pallets[0]) == []


def test_global_rescue_reconstruye_demanda_total_no_solo_lo_pendiente():
    """[sección 5] Recibe un `pallets` con ALGO ya puesto (resultado
    fragmentado de las capas anteriores) + `sin_colocar` -debe reconstruir
    la demanda TOTAL (lo puesto + lo pendiente) y arrancar de pallets
    vacíos nuevos, no seguir sobre el layout parcial recibido."""
    cand_a = _cand("A", 30, 30, 20, cantidad_disponible=4)
    torre_previa = crear_torre(cand_a, x=0, y=0, cantidad=1)
    pallet_parcial = PalletV5(
        id="PV5-VIEJO-001", cd="SINTETICO2", torres=[torre_previa],
        altura_final=config.ALTURA_PALLET_VACIO + 20.0,
    )
    por_sku = {"A": [cand_a]}
    nivel_por_sku = {"A": 6}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[pallet_parcial], sin_colocar={"A": 3}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="SINTETICO2", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}
    assert len(pallets) == 1
    assert pallets[0].id != "PV5-VIEJO-001"  # pallet NUEVO, no el heredado
    assert sum(t.cantidad for t in pallets[0].torres) == 4  # 1 ya puesta + 3 pendientes = demanda total
    assert validar_pallet_v5(pallets[0]) == []


def test_global_rescue_geometria_siempre_valida_con_varios_skus_y_pallets():
    """Stress sintético con más SKUs/pallets -no exige llegar al 100% (no
    es el gate real de BK52/BK53, eso es Fase 2), pero SIEMPRE debe
    devolver pallets geométricamente válidos, sea cual sea el resultado."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=3)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=5)],
        "C": [_cand("C", 25, 25, 10, cantidad_disponible=8)],
        "D": [_cand("D", 80, 90, 25, cantidad_disponible=2)],
    }
    nivel_por_sku = {"A": 6, "B": 6, "C": 6, "D": 6}
    sin_colocar = {"A": 3, "B": 5, "C": 8, "D": 2}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar=sin_colocar, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=2, cd="SINTETICO3", presupuesto=PRESUPUESTO, deadline=time.time() + 20.0,
    )

    assert stats["errores_geometricos"] == 0
    for pallet in pallets:
        assert validar_pallet_v5(pallet) == []


# --- MRV / Most-Constrained global -------------------------------------------

def test_ordenar_mrv_prioriza_menor_escasez_sobre_cualquier_estrategia():
    """[sección 7] "Menor cantidad de candidatos" es SIEMPRE el criterio
    dominante -las 3 estrategias de desempate (sección 17) solo reordenan
    los criterios 2-4, nunca pasan por encima del 1."""
    relleno_cand = _cand("RELLENO", 124, 50, 30, cantidad_disponible=1)
    relleno = crear_torre(relleno_cand, x=-2, y=-2, z=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="CD", torres=[relleno], altura_final=config.ALTURA_PALLET_VACIO + 30.0)
    pc = _reconstruir_en_construccion(pallet)
    # Deja exactamente 2 cuboides libres de distinto footprint: la franja
    # Y=48..102 (124x54) al lado del relleno, y el cuboide arriba del
    # relleno (124x50, mismo footprint que RELLENO) desde z=30.
    assert len(pc.libres) == 2

    por_sku = {
        "ESCASO": [_cand("ESCASO", 60, 52, 20)],  # 52 > 50 -no entra en el cuboide de arriba, solo en la franja
        "ABUNDANTE": [_cand("ABUNDANTE", 20, 20, 20)],  # entra en AMBOS cuboides
    }
    nivel_por_sku = {"ESCASO": 6, "ABUNDANTE": 6, "RELLENO": 6}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"RELLENO": 1}],
        pendientes={"ESCASO": 3, "ABUNDANTE": 3},
    )

    for estrategia in gr.GLOBAL_MULTI_START_ESTRATEGIAS:
        orden = gr._ordenar_mrv(
            ["ABUNDANTE", "ESCASO"], estado, por_sku, {}, nivel_por_sku, {}, estrategia, stats=None,
        )
        assert orden[0] == "ESCASO", f"estrategia={estrategia} no priorizó el SKU más escaso"


def test_ordenar_mrv_nunca_elige_un_sku_en_0_candidatos_deferred_al_final():
    """[Fase 1.1, punto 2 -corrección del usuario] Un SKU con 0 candidatos
    HOY (BLOQUEADO, footprint mayor al pallet entero) NUNCA debe elegirse
    -queda "deferred" al final del orden, aunque tenga "menos candidatos"
    que cualquier otro (0 < cualquier cosa) -eso era exactamente el bug: la
    vieja regla trataba 0 candidatos como "el más restringido, elegilo
    primero" en vez de "no puede moverse, no lo elijas todavía"."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {
        "DISPONIBLE": [_cand("DISPONIBLE", 40, 30, 20)],
        "BLOQUEADO": [_cand("BLOQUEADO", 500, 500, 20)],
    }
    nivel_por_sku = {"DISPONIBLE": 6, "BLOQUEADO": 6}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{}], pendientes={"DISPONIBLE": 3, "BLOQUEADO": 1},
    )

    for estrategia in gr.GLOBAL_MULTI_START_ESTRATEGIAS:
        orden = gr._ordenar_mrv(
            ["BLOQUEADO", "DISPONIBLE"], estado, por_sku, {}, nivel_por_sku, {}, estrategia, stats=None,
        )
        assert orden[0] == "DISPONIBLE", f"estrategia={estrategia} eligió el SKU bloqueado primero"
        assert orden[-1] == "BLOQUEADO"


# --- Aislamiento de estados (clones) --------------------------------------------

def test_clonar_estado_aisla_hijos_del_padre_y_entre_hermanos():
    """[Fase 1.1, punto 5 -pedido explícito del usuario] Los clones copian
    las LISTAS de torres/cuboides (no cada elemento individual, que nunca
    se muta in-place en el motor) -expandir/modificar un hijo NO debe tocar
    el padre del que se clonó, ni a otro hermano clonado del MISMO padre.
    Si hubiera aliasing mutable acá, un solo `.colocar()` en un hijo
    contaminaría silenciosamente todas las demás ramas del beam search."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    padre = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 5})

    hijo1 = gr._clonar_estado(padre)
    hijo2 = gr._clonar_estado(padre)

    cand_a = _cand("A", 40, 30, 20, cantidad_disponible=5)
    opciones = gr._generar_candidatos_multi_pallet(
        hijo1.construcciones, hijo1.colocados_por_pallet, hijo1.pendientes, "A",
        {"A": [cand_a]}, {}, {"A": 6}, {},
    )
    assert opciones
    _sobra, pidx, idx_libre, _z, _x, _y, cand, _max_lote = opciones[0]
    hijo1.construcciones[pidx].colocar(cand, 1, idx_libre)
    hijo1.pendientes["A"] -= 1
    hijo1.cajas_colocadas += 1

    # El padre no cambió -ni sus torres ni sus cuboides libres ni pendientes.
    assert len(padre.construcciones[0].pallet.torres) == 0
    assert padre.pendientes["A"] == 5
    assert len(padre.construcciones[0].libres) == 1

    # El hermano (otro clon del MISMO padre, tomado ANTES de tocar hijo1) tampoco cambió.
    assert len(hijo2.construcciones[0].pallet.torres) == 0
    assert hijo2.pendientes["A"] == 5
    assert len(hijo2.construcciones[0].libres) == 1

    # Solo hijo1 refleja el cambio.
    assert len(hijo1.construcciones[0].pallet.torres) == 1
    assert hijo1.pendientes["A"] == 4
    assert validar_pallet_v5(hijo1.construcciones[0].pallet) == []


# --- Candidatos multi-pallet --------------------------------------------------

def test_candidatos_multi_pallet_compiten_en_todos_los_pallets_a_la_vez():
    """[sección 8] "Para BK53, ambos pallets compiten simultáneamente; no
    repartir primero la demanda entre pallet 1 y pallet 2" -con 2 pallets
    vacíos, un SKU que entra en cualquiera de los dos debe aparecer con
    candidatos en AMBOS índices de pallet, no solo el primero."""
    pallet_0 = PalletV5(id="P0", cd="CD", torres=[])
    pallet_1 = PalletV5(id="P1", cd="CD", torres=[])
    construcciones = [_PalletEnConstruccion(pallet=pallet_0), _PalletEnConstruccion(pallet=pallet_1)]
    colocados_por_pallet = [{}, {}]
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=10)]}

    opciones = gr._generar_candidatos_multi_pallet(
        construcciones, colocados_por_pallet, {"A": 10}, "A", por_sku, {}, {"A": 6}, {},
    )

    pallets_representados = {pidx for _sobra, pidx, *_resto in opciones}
    assert pallets_representados == {0, 1}


# --- Lotes parciales -----------------------------------------------------------

def test_expandir_estado_prueba_lotes_parciales_no_solo_la_columna_completa():
    """[sección 10] "No comprometer siempre una columna completa" -con un
    lote máximo de 7, deben aparecer hijos con 1, 4 (ceil(7/2)) y 7 cajas
    colocadas, no solo el lote máximo."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=7, max_verticales=7)]}
    nivel_por_sku = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 7})

    hijos = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "footprint", stats=None)

    lotes_vistos = sorted({hijo.cajas_colocadas for hijo in hijos})
    assert lotes_vistos == [1, 4, 7]
    for hijo in hijos:
        assert validar_pallet_v5(hijo.construcciones[0].pallet) == []


# --- Simetría entre pallets ----------------------------------------------------

def test_clave_estado_es_invariante_al_orden_de_los_pallets():
    """[sección 15] "Intercambiar pallet 1 y pallet 2 no debe crear dos
    estados diferentes"."""
    cand_a = _cand("A", 40, 30, 20, cantidad_disponible=5)
    torre = crear_torre(cand_a, x=0, y=0, cantidad=2)
    pallet_con_torre = PalletV5(
        id="PX", cd="CD", torres=[torre], altura_final=config.ALTURA_PALLET_VACIO + 40.0,
    )
    pallet_vacio = PalletV5(id="PY", cd="CD", torres=[])

    estado_orden_1 = gr._EstadoGlobal(
        construcciones=[_reconstruir_en_construccion(pallet_con_torre), _PalletEnConstruccion(pallet=pallet_vacio)],
        colocados_por_pallet=[{"A": 2}, {}], pendientes={"A": 1},
    )
    estado_orden_2 = gr._EstadoGlobal(
        construcciones=[_PalletEnConstruccion(pallet=pallet_vacio), _reconstruir_en_construccion(pallet_con_torre)],
        colocados_por_pallet=[{}, {"A": 2}], pendientes={"A": 1},
    )

    assert gr._clave_estado(estado_orden_1) == gr._clave_estado(estado_orden_2)


def test_clave_estado_distingue_layouts_realmente_distintos():
    cand_a = _cand("A", 40, 30, 20, cantidad_disponible=5)
    torre_2 = crear_torre(cand_a, x=0, y=0, cantidad=2)
    torre_3 = crear_torre(cand_a, x=0, y=0, cantidad=3)
    pallet_a = PalletV5(id="PA", cd="CD", torres=[torre_2])
    pallet_b = PalletV5(id="PB", cd="CD", torres=[torre_3])

    estado_a = gr._EstadoGlobal(construcciones=[_PalletEnConstruccion(pallet=pallet_a)], colocados_por_pallet=[{"A": 2}], pendientes={})
    estado_b = gr._EstadoGlobal(construcciones=[_PalletEnConstruccion(pallet=pallet_b)], colocados_por_pallet=[{"A": 3}], pendientes={})

    assert gr._clave_estado(estado_a) != gr._clave_estado(estado_b)


# --- Transposition table -------------------------------------------------------

def test_beam_search_detecta_duplicados_simetricos_entre_pallets_gemelos():
    """[secciones 15, 16] 2 pallets vacíos IDÉNTICOS -colocar el primer
    lote de un SKU en el pallet 0 o en el pallet 1 produce estados
    estructuralmente iguales (mismo contenido, distinto índice de pallet).
    La transposition table debe reconocerlos como duplicados."""
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=6, max_verticales=2)]}
    nivel_por_sku = {"A": 6}
    sin_colocar = {"A": 6}

    _pallets, _faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar=sin_colocar, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=2, cd="SIMETRICO", presupuesto=PRESUPUESTO, deadline=time.time() + 20.0,
    )

    assert stats["duplicados"] >= 1
    assert stats["transposition_hits"] == stats["duplicados"]


def test_transposition_libres_dependen_del_orden_de_colocacion():
    """[Fase 1.2, punto 3 -pregunta explícita del usuario, verificada
    directamente sobre `packing_columnar`, no solo argumentada]:

    "¿dos estados con exactamente las mismas torres, pero generados por
    órdenes distintos, pueden tener conjuntos distintos de cuboides
    libres?"

    Respuesta: SÍ. 4 cajas fijas (mismas posiciones/tamaños en ambos
    órdenes) colocadas en dos secuencias distintas producen el MISMO
    conjunto de torres pero conjuntos de `libres` DIFERENTES -encontrado
    por búsqueda exhaustiva sobre las 24 permutaciones posibles: 12
    órdenes terminan con 10 cuboides libres, los otros 12 con 9. Este test
    fija un representante de cada grupo (orden A y orden B) y compara los
    3 elementos que pidió el usuario: torres finales, cuboides libres
    finales, y candidatos siguientes para un SKU sonda."""
    from src.packing_columnar import _CuboidLibre, _actualizar_libres_maxrects

    cajas = [
        (40, 30, 20, 20, 30, 10),
        (0, 60, 0, 40, 15, 10),
        (60, 30, 20, 15, 20, 20),
        (0, 60, 20, 40, 20, 30),
    ]
    orden_a = (0, 1, 2, 3)
    orden_b = (0, 2, 3, 1)

    def _construir(orden):
        pallet = PalletV5(id="P0", cd="CD", torres=[])
        pc = _PalletEnConstruccion(pallet=pallet, libres=[_CuboidLibre(0, 0, 0, 100, 100, 60)])
        for i in orden:
            x, y, z, w, h, d = cajas[i]
            cand = _cand(f"SKU{i}", w, h, d, cantidad_disponible=1)
            torre = crear_torre(cand, x=x, y=y, z=z, cantidad=1)
            pc.pallet.torres.append(torre)
            pc.libres = _actualizar_libres_maxrects(pc.libres, x, y, z, w, h, d)
        return pc

    def _firma_torres(pc):
        return sorted(
            (t.sku, round(t.x, 2), round(t.y, 2), round(t.z, 2), round(t.largo, 2), round(t.ancho, 2))
            for t in pc.pallet.torres
        )

    def _firma_libres(pc):
        return sorted(
            (round(c.x, 2), round(c.y, 2), round(c.z, 2), round(c.w, 2), round(c.h, 2), round(c.d, 2))
            for c in pc.libres
        )

    pc_a = _construir(orden_a)
    pc_b = _construir(orden_b)

    # Mismas torres finales en ambos órdenes -las 4 cajas quedaron en las
    # MISMAS posiciones, solo cambió la secuencia en la que se avisaron.
    assert _firma_torres(pc_a) == _firma_torres(pc_b)

    # Cuboides libres finales: DISTINTOS -la región (0,60,50,40,20,10) quedó
    # como UN cuboide en el orden B y PARTIDA en dos (40,15,10)+(40,5,10)
    # en el orden A.
    assert _firma_libres(pc_a) != _firma_libres(pc_b)
    assert len(pc_a.libres) != len(pc_b.libres)

    # Candidatos siguientes: un SKU sonda que necesita ancho=20 en la
    # franja (x=0,y=60,z=50, largo=40, alto<=10) -en el orden B esa región
    # sobrevive como UN cuboide (40x20) y la admite; en el orden A quedó
    # partida en dos (40x15 y 40x5), ninguno con h>=20 (ni siquiera con la
    # tolerancia de 2cm de `_fit_directo_o_con_tolerancia`), así que ahí NO
    # la admite. (Se prueba el cuboide EXACTO, no el conteo agregado del
    # pallet completo -el resto del piso, sin relación con esta franja,
    # también admitiría la sonda y no aportaría nada a la comparación.)
    from src.packing_bloques import _cuboide_admite_candidato
    sonda = _cand("SONDA", 40, 20, 10, cantidad_disponible=1)
    nivel_sonda = {"SONDA": 6}

    cuboide_franja_a = [c for c in pc_a.libres if abs(c.x) < 0.01 and c.y >= 59.99 and abs(c.z - 50) < 0.01]
    cuboide_franja_b = [c for c in pc_b.libres if abs(c.x) < 0.01 and c.y >= 59.99 and abs(c.z - 50) < 0.01]
    assert len(cuboide_franja_a) == 2  # partida en dos (y=60,h=15 / y=75,h=5) en el orden A
    assert len(cuboide_franja_b) == 1  # UN solo cuboide (y=60,h=20) en el orden B

    admite_a = any(_cuboide_admite_candidato(pc_a.pallet, c, sonda, None, 6, nivel_sonda) for c in cuboide_franja_a)
    admite_b = any(_cuboide_admite_candidato(pc_b.pallet, c, sonda, None, 6, nivel_sonda) for c in cuboide_franja_b)
    assert admite_a is False
    assert admite_b is True

    # Consecuencia directa (lo que este fix corrige): antes de incluir
    # `libres` en la firma, `_clave_estado` habría tratado pc_a y pc_b
    # como el MISMO estado (mismas torres); ahora las claves difieren.
    estado_a = gr._EstadoGlobal(construcciones=[pc_a], colocados_por_pallet=[{}], pendientes={"SONDA": 1})
    estado_b = gr._EstadoGlobal(construcciones=[pc_b], colocados_por_pallet=[{}], pendientes={"SONDA": 1})
    assert gr._clave_estado(estado_a) != gr._clave_estado(estado_b)


def test_transposition_misma_geometria_distinta_demanda_no_es_equivalente():
    """[Fase 1.2, punto 4 -pedido explícito del usuario: "prefiero
    redundancia segura a una equivalencia incorrecta"] Misma geometría
    (mismas torres, mismos libres) pero `pendientes` distinto NO debe
    producir la misma `_clave_estado` -aunque hoy sea derivable de la
    demanda total fija de la corrida, se incluye explícito por seguridad
    redundante en vez de depender de esa invariante implícita."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc_1 = _PalletEnConstruccion(pallet=pallet)
    pc_2 = _PalletEnConstruccion(pallet=PalletV5(id="P0", cd="CD", torres=[]))

    estado_1 = gr._EstadoGlobal(construcciones=[pc_1], colocados_por_pallet=[{}], pendientes={"A": 3, "B": 1})
    estado_2 = gr._EstadoGlobal(construcciones=[pc_2], colocados_por_pallet=[{}], pendientes={"A": 2, "B": 2})

    assert gr._clave_estado(estado_1) != gr._clave_estado(estado_2)


# --- Poda segura ----------------------------------------------------------------

def test_es_estado_inviable_poda_sku_sin_candidatos_ni_capacidad_residual():
    """[sección 14] Un SKU cuyo footprint no cabe en NINGUNA orientación
    (más grande que el pallet entero) y que tampoco tiene ninguna columna
    propia ya instalada -estado genuinamente estancado para ese SKU, se
    debe podar."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {"IMPOSIBLE": [_cand("IMPOSIBLE", 500, 500, 20)]}
    nivel_por_sku = {"IMPOSIBLE": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"IMPOSIBLE": 1})

    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is True


def test_es_estado_inviable_no_poda_un_estado_sano():
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=5)]}
    nivel_por_sku = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 5})

    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is False


def test_es_estado_inviable_no_poda_si_hay_capacidad_instalada_residual():
    """Un SKU con 0 candidatos NUEVOS puede seguir subiendo en una columna
    propia que ya tiene -no está genuinamente estancado."""
    cand_a = _cand("A", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=10, max_verticales=10)
    torre = crear_torre(cand_a, x=0, y=0, z=0, cantidad=1)  # ocupa TODA la base -sin cuboides libres nuevos en XY
    pallet = PalletV5(id="P0", cd="CD", torres=[torre], altura_final=config.ALTURA_PALLET_VACIO + 20.0)
    pc = _reconstruir_en_construccion(pallet)
    por_sku = {"A": [cand_a]}
    nivel_por_sku = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A": 1}], pendientes={"A": 3})

    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is False


def test_es_estado_inviable_poda_apenas_UN_sku_esta_permanentemente_estancado():
    """[Fase 1.2, RESTAURACIÓN de la poda por SKU individual] Fase 1.1
    había relajado esto a "requiere que TODOS estén estancados a la vez",
    por la preocupación de que otro SKU pudiera crearle soporte/espacio a
    BLOQUEADO más adelante. `test_monotonicidad_candidatos_no_aumentan_al_
    colocar_otro_sku` formaliza -sobre el motor real- que eso no puede
    pasar con las reglas de hoy: un SKU nunca gana candidatos por la
    colocación de otro en un pallet que arrancó vacío. Con esa propiedad
    confirmada, basta UN SOLO SKU permanentemente estancado (BLOQUEADO,
    0 candidatos y 0 capacidad instalada) para podar TODO el estado -aunque
    DISPONIBLE todavía tenga movimientos válidos- porque ninguna
    continuación de esta rama puede llegar al 100% de BLOQUEADO."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {
        "DISPONIBLE": [_cand("DISPONIBLE", 40, 30, 20)],
        "BLOQUEADO": [_cand("BLOQUEADO", 500, 500, 20)],  # nunca cabe en ningún pallet
    }
    nivel_por_sku = {"DISPONIBLE": 6, "BLOQUEADO": 6}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{}], pendientes={"DISPONIBLE": 3, "BLOQUEADO": 1},
    )

    # Confirmación explícita de la premisa: BLOQUEADO, aislado, SÍ está
    # estancado (0 candidatos, 0 capacidad instalada) -si no fuera así el
    # test no probaría nada.
    assert gr._contar_candidatos_y_registrar(estado, "BLOQUEADO", por_sku, {}, nivel_por_sku, {}, None, max_count=1) == 0

    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is True


def test_monotonicidad_candidatos_no_aumentan_al_colocar_otro_sku():
    """[Fase 1.2, punto 1 -formalización pedida por el usuario ANTES de
    restaurar la poda por SKU individual]

    HALLAZGO IMPORTANTE, encontrado corriendo la primera versión de este
    test contra el motor real (no fue un supuesto): el CONTEO crudo de
    `_contar_candidatos_factibles` (combos admisibles de (cuboide,
    orientación), tope 0..4) NO es monótono no-creciente en general -
    fragmentar UN cuboide grande en varios chicos puede hacer que MÁS
    combos individuales admitan a un SKU chico, aunque el volumen libre
    total solo haya bajado (ver `_contar_candidatos_y_registrar`: cuenta
    combos, no "cabe sí/no"). Ese conteo crudo es una señal heurística
    para MRV/score (sección 7/12, más fino que un booleano), nunca la
    base de la poda.

    La propiedad que SÍ es cierta, verificada, y la única que
    `_es_estado_inviable` necesita para ser segura: si un SKU tiene 0
    candidatos HOY (ningún cuboide libre actual lo admite, con
    `max_count=1`), seguirá teniendo 0 después de colocar OTRO SKU en el
    mismo pallet -"0 nunca vuelve a subir". Motivo estructural (confirmado
    sobre `packing_columnar._actualizar_libres_maxrects`, no solo
    argumentado): cada cuboide libre nuevo que puede aparecer tras una
    colocación es, en w/h/d, un SUBCONJUNTO de aquel del que salió (los 5
    tipos de split de `_actualizar_libres_maxrects` -izquierda/derecha/
    abajo/arriba en XY, arriba en Z- nunca producen una dimensión MAYOR a
    la del cuboide original). Si el footprint de B no entraba en NINGÚN
    cuboide de la lista actual, tampoco va a entrar en ningún fragmento
    futuro de esos mismos cuboides, sea cual sea el orden en que se sigan
    colocando otros SKUs.

    Este test construye el caso "difícil" real -B no cabe por
    FRAGMENTACIÓN previa (un SKU ya ocupó la mayor parte del pallet),
    no porque su footprint exceda el pallet entero (eso ya lo cubre
    `test_es_estado_inviable_poda_sku_sin_candidatos_ni_capacidad_
    residual`)- y confirma que sigue en 0 después de colocar un TERCER
    SKU más."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    from src.packing_columnar import _CuboidLibre
    pc = _PalletEnConstruccion(pallet=pallet, libres=[_CuboidLibre(0, 0, 0, 100, 60, 500)])

    por_sku = {
        "YA_PUESTO": [_cand("YA_PUESTO", 80, 60, 20, cantidad_disponible=1)],
        "B": [_cand("B", 100, 20, 20, cantidad_disponible=1)],
        "C": [_cand("C", 15, 15, 20, cantidad_disponible=3)],
    }
    nivel_por_sku = {"YA_PUESTO": 6, "B": 6, "C": 6}

    opciones_ya = gr._generar_candidatos_multi_pallet(
        [pc], [{}], {"YA_PUESTO": 1}, "YA_PUESTO", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones_ya
    _sobra, pidx, idx_libre, _z, _x, _y, cand, max_lote = opciones_ya[0]
    pc.colocar(cand, max_lote, idx_libre)

    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"YA_PUESTO": 1}], pendientes={"B": 1, "C": 3},
    )
    candidatos_b_antes = gr._contar_candidatos_y_registrar(estado, "B", por_sku, {}, nivel_por_sku, {}, None, max_count=1)
    assert candidatos_b_antes == 0  # B ya está estancado por la fragmentación de YA_PUESTO

    opciones_c = gr._generar_candidatos_multi_pallet(
        estado.construcciones, estado.colocados_por_pallet, estado.pendientes, "C", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones_c
    _sobra, pidx_c, idx_libre_c, _z, _x, _y, cand_c, max_lote_c = opciones_c[0]
    estado.construcciones[pidx_c].colocar(cand_c, max_lote_c, idx_libre_c)
    estado.pendientes["C"] -= max_lote_c

    candidatos_b_despues = gr._contar_candidatos_y_registrar(estado, "B", por_sku, {}, nivel_por_sku, {}, None, max_count=1)
    assert candidatos_b_despues == 0  # sigue en 0 -nunca "resucita" por colocar C


def test_poda_A_mala_decision_deja_sku_estancado_y_se_poda():
    """[Fase 1.2, punto 1 -TEST A pedido explícitamente por el usuario]
    "Una mala decisión previa deja SKU B en candidatos=0 AND capacidad
    residual=0 -> esa rama se poda."

    Pallet REAL (120x100, cuboide inicial default -no uno sintético
    recortado, ver nota V6.06 abajo). La decisión "mala" -colocar A
    ocupando 100x104 (todo el ANCHO efectivo, la mayor parte del LARGO)-
    deja un remanente que NINGUNA orientación de B (que necesita el LARGO
    efectivo completo, 124) puede ocupar: ni la franja lateral (24x104) ni
    el cuboide arriba de A (100x104) llegan a 124 de ancho. B queda con 0
    candidatos y sin columna propia -> 0 capacidad instalada.

    [Nota V6.06] Hasta V6.05 este test usaba un `_CuboidLibre` SINTÉTICO
    de 100x60 -mucho más chico que el pallet real- para acotar lo que
    MaxRects podía "ver". Con el Structural Fallback (V6.06) eso ya NO
    alcanza: el fallback genera posiciones contra los límites FÍSICOS
    reales del pallet (`config.PALLET_LARGO`/`ANCHO`), no contra `pc.
    libres` -si el pallet sintético fuera más chico que el real, el
    fallback encontraría espacio "fuera" del cuboide sintético que en
    realidad SÍ existe en el pallet físico (correcto -eso es justo lo que
    V6.06 corrige), y el test dejaría de probar lo que dice probar. Por
    eso ahora la geometría usa las dimensiones REALES del pallet, para que
    la poda siga siendo válida bajo MaxRects Y bajo el híbrido."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)  # cuboide inicial REAL del pallet (124x104 efectivo)

    por_sku = {
        "A_MALA": [_cand("A_MALA", 100, 104, 20, cantidad_disponible=1)],
        "B": [_cand("B", 124, 20, 20, cantidad_disponible=1)],
        "C": [_cand("C", 15, 15, 20, cantidad_disponible=5)],
    }
    nivel_por_sku = {"A_MALA": 6, "B": 6, "C": 6}

    opciones = gr._generar_candidatos_multi_pallet(
        [pc], [{}], {"A_MALA": 1}, "A_MALA", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones
    _sobra, pidx, idx_libre, _z, _x, _y, cand, max_lote = opciones[0]
    assert (cand.largo, cand.ancho) == (100, 104)  # confirma que ESTE es el ajuste que el motor elegiría
    pc.colocar(cand, max_lote, idx_libre)

    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A_MALA": 1}], pendientes={"B": 1, "C": 3})

    # Premisa explícita: B queda genuinamente estancado en ESTA rama -bajo
    # MaxRects Y bajo el híbrido (Structural Fallback incluido).
    assert gr._contar_candidatos_y_registrar(estado, "B", por_sku, {}, nivel_por_sku, {}, None, max_count=1) == 0
    assert gr._contar_candidatos_y_registrar(
        estado, "B", por_sku, {}, nivel_por_sku, {}, None, max_count=1, presupuesto=PRESUPUESTO,
    ) == 0
    # Premisa explícita: C, en cambio, SÍ conserva candidatos -si la poda
    # todavía exigiera que TODOS estén estancados, este estado NO se
    # podaría (esa era la regla de Fase 1.1).
    assert gr._contar_candidatos_y_registrar(estado, "C", por_sku, {}, nivel_por_sku, {}, None, max_count=1) > 0

    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is True


def test_poda_B_otra_rama_preserva_espacio_y_llega_al_100():
    """[Fase 1.2, punto 1 -TEST B pedido explícitamente por el usuario]
    "Otra rama del mismo problema preserva espacio para B -> llega al
    100%."

    Mismo pallet REAL, mismos SKUs A/B/C (ver nota V6.06 en TEST A sobre
    por qué la geometría usa dimensiones reales) -pero la decisión "buena"
    es colocar A con la orientación 124x50 (ocupa todo el LARGO efectivo,
    la mitad del ancho): la franja que queda (124x54) es suficiente para
    B. Ambas decisiones son alternativas reales para A (mismo SKU, misma
    demanda) -la búsqueda necesita explorar más de una para no quedarse
    con la trampa greedy de TEST A."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)

    por_sku = {
        "A_BUENA": [_cand("A_BUENA", 124, 50, 20, cantidad_disponible=1)],
        "B": [_cand("B", 124, 20, 20, cantidad_disponible=1)],
        "C": [_cand("C", 15, 15, 20, cantidad_disponible=5)],
    }
    nivel_por_sku = {"A_BUENA": 6, "B": 6, "C": 6}

    opciones_a = gr._generar_candidatos_multi_pallet(
        [pc], [{}], {"A_BUENA": 1}, "A_BUENA", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones_a
    _sobra, pidx, idx_libre, _z, _x, _y, cand_a, max_lote_a = opciones_a[0]
    assert (cand_a.largo, cand_a.ancho) == (124, 50)
    pc.colocar(cand_a, max_lote_a, idx_libre)

    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A_BUENA": 1}], pendientes={"B": 1, "C": 3})

    # Con esta decisión, B YA tiene candidato -el estado no se poda.
    assert gr._contar_candidatos_y_registrar(estado, "B", por_sku, {}, nivel_por_sku, {}, None, max_count=1) > 0
    assert gr._es_estado_inviable(estado, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, stats=None) is False

    opciones_b = gr._generar_candidatos_multi_pallet(
        estado.construcciones, estado.colocados_por_pallet, estado.pendientes, "B", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones_b
    _sobra, pidx_b, idx_libre_b, _z, _x, _y, cand_b, max_lote_b = opciones_b[0]
    estado.construcciones[pidx_b].colocar(cand_b, max_lote_b, idx_libre_b)
    estado.pendientes["B"] -= max_lote_b
    estado.colocados_por_pallet[pidx_b]["B"] = estado.colocados_por_pallet[pidx_b].get("B", 0) + max_lote_b

    opciones_c = gr._generar_candidatos_multi_pallet(
        estado.construcciones, estado.colocados_por_pallet, estado.pendientes, "C", por_sku, {}, nivel_por_sku, {},
    )
    assert opciones_c
    _sobra, pidx_c, idx_libre_c, _z, _x, _y, cand_c, max_lote_c = opciones_c[0]
    estado.construcciones[pidx_c].colocar(cand_c, max_lote_c, idx_libre_c)
    estado.pendientes["C"] -= max_lote_c

    assert estado.pendientes.get("B", 0) == 0  # B llegó al 100% en ESTA rama
    assert validar_pallet_v5(estado.construcciones[0].pallet) == []


# --- Score: preservar escasez vs. cajas colocadas --------------------------------

def test_score_prioriza_preservar_escasez_sobre_mas_cajas_colocadas_temprano():
    """[Fase 1.2, punto 2 -test sintético pedido explícitamente por el
    usuario] "Estado A coloca más cajas temprano pero termina bloqueando
    un SKU. Estado B coloca temporalmente menos cajas pero preserva
    espacio y llega a 100%. El Beam debe conservar B."

    ESCASO necesita un cuboide de 90x50. Estado A ya colocó 5 cajas de
    ABUNDANTE (greedy) pero solo le queda 1 cuboide que admite a ESCASO
    -deuda de escasez alta ((4-1)*1=3, sección 13). Estado B colocó menos
    (2 cajas de ABUNDANTE) pero preservó 4 cuboides distintos que admiten
    a ESCASO -deuda de escasez 0 ((4-4)*1=0). Con el score de Fase 1.2
    (deuda de escasez DOMINANTE sobre cajas colocadas), B debe ganarle a A
    pese a tener MENOS cajas colocadas -exactamente lo que evita repetir
    el comportamiento de Rescue V6.02/Repair V6.04 que motivó crear Global
    Rescue (colocar rápido y fragmentar el espacio de las SKUs difíciles)."""
    from src.packing_columnar import _CuboidLibre

    por_sku = {"ESCASO": [_cand("ESCASO", 90, 50, 20, cantidad_disponible=1)]}
    nivel_por_sku = {"ESCASO": 6}

    pallet_a = PalletV5(id="PA", cd="CD", torres=[])
    pc_a = _PalletEnConstruccion(pallet=pallet_a, libres=[_CuboidLibre(0, 0, 0, 90, 50, 100)])
    estado_a = gr._EstadoGlobal(
        construcciones=[pc_a], colocados_por_pallet=[{"ABUNDANTE": 5}], pendientes={"ESCASO": 1}, cajas_colocadas=5,
    )

    # [x,y iguales en las 4 -_fit_directo_o_con_tolerancia valida contra
    # los límites ABSOLUTOS del pallet físico (config.PALLET_LARGO/ANCHO),
    # no solo contra el tamaño del propio cuboide- así que 4 posiciones a
    # lo ancho de X se saldrían del pallet real y se rechazarían todas
    # menos 1. Se simulan 4 capas Z distintas en su lugar (mismo x=0,y=0):
    # con `pallet.torres=[]`, las reglas que dependen de lo ya puesto
    # (`_soporte_viola_nivel`, `_altura_compatible_con_cama`) no encuentran
    # ningún conflicto en z>0 y admiten las 4 por igual -sigue siendo un
    # conteo válido de "4 combos (cuboide, orientación) distintos".
    pallet_b = PalletV5(id="PB", cd="CD", torres=[])
    pc_b = _PalletEnConstruccion(pallet=pallet_b, libres=[
        _CuboidLibre(0, 0, 0, 90, 50, 100),
        _CuboidLibre(0, 0, 110, 90, 50, 100),
        _CuboidLibre(0, 0, 220, 90, 50, 100),
        _CuboidLibre(0, 0, 330, 90, 50, 100),
    ])
    estado_b = gr._EstadoGlobal(
        construcciones=[pc_b], colocados_por_pallet=[{"ABUNDANTE": 2}], pendientes={"ESCASO": 1}, cajas_colocadas=2,
    )

    # Premisas explícitas de escasez: A con 1 candidato, B con 4 (tope de corte).
    assert gr._contar_candidatos_y_registrar(estado_a, "ESCASO", por_sku, {}, nivel_por_sku, {}, None) == 1
    assert gr._contar_candidatos_y_registrar(estado_b, "ESCASO", por_sku, {}, nivel_por_sku, {}, None) == 4

    score_a = gr._score_estado(estado_a, por_sku, {}, nivel_por_sku, {}, stats=None)
    score_b = gr._score_estado(estado_b, por_sku, {}, nivel_por_sku, {}, stats=None)

    assert estado_a.cajas_colocadas > estado_b.cajas_colocadas  # A "parece" mejor si solo se mirara esto
    assert score_b > score_a  # pero B gana: preserva más futuro para ESCASO


# --- Multi-start determinista ---------------------------------------------------

def test_multi_start_se_detiene_apenas_llega_al_100_por_ciento():
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    nivel_por_sku = {"A": 6}

    _pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"A": 3}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="MULTISTART_FACIL", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}
    assert len(stats["reinicios"]) == 1
    assert stats["reinicios"][0]["estrategia"] == gr.GLOBAL_MULTI_START_ESTRATEGIAS[0]


def test_multi_start_agota_los_3_reinicios_con_estrategias_distintas_si_no_hay_salida():
    """SKU cuyo footprint nunca cabe -cada reinicio queda "estancado" en 1
    iteración; deben agotarse los 3 reinicios, cada uno con la estrategia
    declarada en orden (sección 17: "no usar aleatoriedad irreproducible")."""
    por_sku = {"IMPOSIBLE": [_cand("IMPOSIBLE", 500, 500, 20)]}
    nivel_por_sku = {"IMPOSIBLE": 6}

    _pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"IMPOSIBLE": 1}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="IMPOSIBLE_CD", presupuesto=PRESUPUESTO, deadline=time.time() + 5.0,
    )

    assert faltantes == {"IMPOSIBLE": 1}
    assert len(stats["reinicios"]) == gr.GLOBAL_MULTI_START_MAX
    assert [r["estrategia"] for r in stats["reinicios"]] == list(gr.GLOBAL_MULTI_START_ESTRATEGIAS)
    assert all(r["motivo_stop"] == "estancado" for r in stats["reinicios"])


# --- "SKU deferred no mata el estado" -test obligatorio end-to-end -------------

def test_sku_permanentemente_bloqueado_no_impide_completar_otro_sku_disponible():
    """[Fase 1.1, punto 4 -test obligatorio pedido por el usuario]

    HALLAZGO IMPORTANTE, documentado acá en vez de fabricar un test
    engañoso: se intentó construir el caso EXACTO que pide el punto 4
    ("SKU B en 0 candidatos, colocar A crea una superficie válida, B pasa
    a tener candidato") usando SOLO las reglas que Global Rescue reutiliza
    hoy de `_cuboide_admite_candidato` (fit/overhang + tope de cama +
    jerarquía de nivel + altura de cama). Resultado del análisis: es
    IMPOSIBLE de construir hoy, por una propiedad estructural real de este
    subconjunto de reglas, no por falta de un ejemplo bien elegido:

    1. MaxRects (`packing_columnar.py`) solo FRAGMENTA -cada cuboide libre
       nuevo es un subconjunto geométrico (w/h/d) de aquel del que salió.
       El PRIMER cuboide de un pallet vacío (124x104xpresupuesto) es
       siempre un SUPERCONJUNTO de cualquier cuboide que pueda existir
       después. Si un SKU cabe en algún cuboide futuro, YA cabía en ese
       primer cuboide, desde el turno 1.
    2. Las únicas reglas de `_cuboide_admite_candidato` que dependen de lo
       YA puesto (`_soporte_viola_nivel`, `_altura_compatible_con_cama`)
       son estrictamente MÁS permisivas en el piso (z=0, sin restricción
       ninguna) que en cualquier posición elevada -nunca al revés. Nunca
       "desbloquean" nada que el piso ya no ofreciera.
    3. La jerarquía de nivel es transitiva: algo más pesado que TODO lo
       que hay alrededor no puede apoyarse ni directa ni indirectamente
       en nada más liviano, sin importar cuántos SKUs intermedios se
       coloquen -y el piso (sin restricción de nivel) sigue siendo su
       única salida real, disponible desde el inicio.

    Conclusión: con las reglas de HOY, un SKU nunca pasa de 0 a >0
    candidatos por la colocación de OTRO SKU en un pallet que arrancó
    vacío -el riesgo que señala el usuario es válido en general para bin
    packing 3D con soporte, pero se vuelve alcanzable en este motor recién
    si Fase 2 porta una regla asimétrica que HOY Global Rescue no usa
    (ej. "una categoría de remate no puede competir por el piso mientras
    Licores no decida", `_necesita_columna_nueva` en `packing_bloques.py`,
    que el camino normal SÍ usa pero Global Rescue todavía no).

    Lo que SÍ es 100% real y se corrige en Fase 1.1 (puntos 1-3 de esa
    fase) es un bug DISTINTO pero relacionado: la poda/MRV de ANTES de
    Fase 1.1 mataban el estado o descartaban un SKU disponible por culpa
    de OTRO SKU que nunca en su vida va a poder colocarse (0 candidatos
    PERMANENTE, no "deferred temporal"). Este test demuestra exactamente
    ESO extremo a extremo: un SKU imposible (BLOQUEADO, footprint mayor
    que el pallet entero) NO debe impedir que otro SKU perfectamente
    colocable (DISPONIBLE) llegue al 100%.

    [Actualización Fase 1.2] La propiedad de monotonicidad de los puntos
    1-3 de ARRIBA es justo la que, formalizada con test
    (`test_monotonicidad_candidatos_no_aumentan_al_colocar_otro_sku`),
    permitió restaurar la poda por SKU individual en `_es_estado_inviable`
    -BLOQUEADO está estancado (0 candidatos, 0 capacidad) desde el primer
    turno, así que con la poda de Fase 1.2 CUALQUIER estado de esta
    búsqueda se declara inviable de inmediato (ya no hace falta esperar a
    que DISPONIBLE también se estanque). Este test SIGUE pasando -y sigue
    siendo la prueba correcta del mecanismo que de verdad importa acá- no
    porque el estado deje de podarse, sino por el fix que Fase 1.1 dejó en
    `_beam_search`: podar solo significa "no seguir expandiendo esta
    rama", nunca "descartar su valor" -cada estado (podado o no) compite
    por `mejor_estado` ANTES de decidir si entra a la siguiente frontera.
    Por eso el mejor estado encontrado (DISPONIBLE 3/3, BLOQUEADO sin
    colocar) sigue siendo el resultado final, aunque la rama se declare
    muerta en la primera ronda -la búsqueda simplemente termina mucho más
    rápido (`motivo_stop="estancado"` casi de inmediato) en vez de seguir
    explorando lotes parciales de DISPONIBLE sin necesidad."""
    por_sku = {
        "DISPONIBLE": [_cand("DISPONIBLE", 40, 30, 20, cantidad_disponible=3)],
        "BLOQUEADO": [_cand("BLOQUEADO", 500, 500, 20, cantidad_disponible=1)],
    }
    nivel_por_sku = {"DISPONIBLE": 6, "BLOQUEADO": 6}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"DISPONIBLE": 3, "BLOQUEADO": 1}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="BLOQUEO_PARCIAL", presupuesto=PRESUPUESTO, deadline=time.time() + 10.0,
    )

    assert faltantes == {"BLOQUEADO": 1}  # nunca se pierde en silencio, ni se declara colocado
    assert sum(t.cantidad for t in pallets[0].torres if t.sku == "DISPONIBLE") == 3
    assert validar_pallet_v5(pallets[0]) == []


# --- Timeout ---------------------------------------------------------------------

def test_global_rescue_respeta_deadline_ya_vencido_sin_crashear():
    """Un `deadline` ya vencido al momento de la llamada debe cortar la
    búsqueda de inmediato -sin colgarse, sin crashear, devolviendo pallets
    vacíos pero geométricamente válidos (nada se llegó a colocar)."""
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    nivel_por_sku = {"A": 6}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"A": 3}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="TIMEOUT_CD", presupuesto=PRESUPUESTO, deadline=time.time() - 1.0,
    )

    assert faltantes == {"A": 3}
    assert stats["motivo_stop"] == "timeout"
    assert len(stats["reinicios"]) == 1
    for pallet in pallets:
        assert validar_pallet_v5(pallet) == []
