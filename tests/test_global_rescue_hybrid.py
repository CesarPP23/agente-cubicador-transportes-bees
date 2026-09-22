"""[PATCH V6.06] Candidate Generator Híbrido (MaxRects + Structural
Fallback) + corrección de cajas fantasma -tests obligatorios de la sección
12 del parche, sobre el escenario que motivó todo el parche (Fase 2.1: SKU
15506, MaxRects=0/Oracle>0 confirmado con datos reales de BK52, y el patrón
sintético de soporte por unión de 2+ cajas).

[PATCH V6.07] `_generar_candidatos_estructurales_para_pallet` (lista
completa, V6.06) fue reemplazada por el motor eficiente de `src/global_
rescue_structural.py` (generator streaming + cache) -estos tests se
actualizan para llamar a las nuevas APIs (`generar_candidatos_
estructurales`, `_generar_candidatos_multi_pallet_hibrido` ahora recibe un
`_EstadoGlobal`), sin cambiar QUÉ prueban."""
import config
import src.global_rescue as gr
from models import PalletV5
from src.global_rescue_oracle import enumerar_candidatos_oraculo
from src.packing_bloques import _cuboide_admite_candidato
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate
from src.validacion_v5 import validar_pallet_v5

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _pallet_con_A_B_union():
    """Dos cajas 40x40 lado a lado (A en x=0, B en x=40), sobre el pallet
    REAL -mismo patrón de soporte-por-unión de Fase 2.1/patch sección 0.

    [Nota de diseño] El pallet real (120x100) tiene MUCHO piso libre más
    allá de A+B -si se dejara `pc.libres` tal cual queda de la
    fragmentación real, MaxRects encontraría a TOP en OTRO lado del piso
    (sin relación con el soporte por unión), y estos tests dejarían de
    probar lo que dicen probar. El hecho geométrico en sí -que MaxRects NO
    puede representar una posición de soporte por unión cuando es la
    ÚNICA opción- ya está probado por separado y con la fragmentación
    REAL sin tocar (Fase 2.1, `tests/test_global_rescue_diagnostics.py::
    test_soporte_por_union_de_dos_cajas_validator_maxrects_oraculo`, sigue
    en verde, sin cambios). Acá se fija `pc.libres = []` explícitamente
    para aislar SOLO lo que estos tests de V6.06 quieren probar: el
    WIRING del híbrido (poda/MRV/generador) cuando MaxRects=0, no
    volver a redemostrar el hallazgo geométrico de fondo."""
    cand_a = _cand("A", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_b = _cand("B", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    gr._colocar_candidato_estructural(pc, cand_a, 0, 0, 0, 1)
    gr._colocar_candidato_estructural(pc, cand_b, 40, 0, 0, 1)
    pc.libres = []
    return pc


# --- 12.1 Support union end-to-end ------------------------------------------

def test_12_1_support_union_end_to_end():
    """MaxRects solo: no candidato. Structural fallback: sí candidato.
    Global hybrid generator: sí candidato. placement: válido.
    validar_pallet_v5: []."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()

    # MaxRects solo: no candidato.
    admite_maxrects = any(_cuboide_admite_candidato(pc.pallet, c, cand_top, None, 6, nivel) for c in pc.libres)
    assert admite_maxrects is False

    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1},
    )

    # Structural fallback: sí candidato.
    posiciones_estructurales = gr.generar_candidatos_estructurales(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, PRESUPUESTO, gr.CacheEstructural(), stats=None,
    )
    assert len(posiciones_estructurales) > 0

    # Global hybrid generator: sí candidato.
    opciones = gr._generar_candidatos_multi_pallet_hibrido(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, PRESUPUESTO,
    )
    assert len(opciones) > 0
    opciones_estructurales = [o for o in opciones if o[2] is None]  # idx_libre is None -> estructural
    assert opciones_estructurales

    # placement: válido.
    _sobra, pidx, idx_libre, z, x, y, cand, max_lote = opciones_estructurales[0]
    assert idx_libre is None
    torre = gr._colocar_candidato_estructural(pc, cand, x, y, z, max_lote)
    assert torre.cantidad == max_lote

    # validar_pallet_v5: [].
    assert validar_pallet_v5(pc.pallet) == []


# --- 12.2 False prune SKU 15506-like -----------------------------------------

def test_12_2_false_prune_no_se_poda_cuando_structural_encuentra_candidato():
    """MaxRects=0, Structural>0 -la rama NO debe podarse (antes de V6.06,
    esto era exactamente la poda falsa confirmada en Fase 2.1 para el SKU
    15506 real de BK52)."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1},
    )

    # Premisa: MaxRects=0 para TOP (mismo hallazgo de 12.1).
    candidatos_maxrects = gr._contar_candidatos_y_registrar(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, None, max_count=1,
    )
    assert candidatos_maxrects == 0

    # Con presupuesto (híbrido activo): NO se poda.
    assert gr._es_estado_inviable(estado, {"TOP": [cand_top]}, {}, nivel, {}, PRESUPUESTO, stats=None) is False

    # Y el conteo híbrido de escasez ya refleja >0, no 0.
    candidatos_hibrido = gr._contar_candidatos_y_registrar(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, None, max_count=1, presupuesto=PRESUPUESTO,
    )
    assert candidatos_hibrido > 0


# --- 12.3 Oracle parity sample ------------------------------------------------

def test_12_3_oracle_parity_si_oraculo_encuentra_hybrid_tambien():
    """Sobre varios estados de diagnóstico: si el oráculo encuentra una
    posición válida, el hybrid generator debe encontrar AL MENOS una -no
    se exige que enumeren exactamente las mismas posiciones."""
    casos = []

    # Caso 1: soporte por unión (el motivador de todo el parche).
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel1 = {"A": 6, "B": 6, "TOP": 6}
    pc1 = _pallet_con_A_B_union()
    casos.append((pc1, "TOP", [cand_top], nivel1, {"A": 1, "B": 1}))

    # Caso 2: pallet vacío, SKU que cabe cómodo (sanidad, no solo el caso difícil).
    cand_simple = _cand("SIMPLE", 40, 30, 20, cantidad_disponible=1)
    pallet2 = PalletV5(id="P1", cd="CD", torres=[])
    pc2 = _PalletEnConstruccion(pallet=pallet2)
    casos.append((pc2, "SIMPLE", [cand_simple], {"SIMPLE": 6}, {}))

    for pc, sku, candidatas, nivel, colocados in casos:
        oraculo = enumerar_candidatos_oraculo(
            pc.pallet, sku, candidatas, None, nivel.get(sku, 6), nivel, float("inf"), 0, PRESUPUESTO,
        )
        if not oraculo:
            continue  # este caso no prueba nada de parity si el oráculo tampoco encuentra
        estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[colocados], pendientes={sku: 1})
        opciones = gr._generar_candidatos_multi_pallet_hibrido(
            estado, sku, {sku: candidatas}, {}, nivel, {}, PRESUPUESTO,
        )
        assert len(opciones) > 0, f"oráculo encontró posición para {sku} pero el hybrid generator no encontró ninguna"


# --- 12.5 MRV híbrido ---------------------------------------------------------

def test_12_5_mrv_trata_sku_con_structural_positivo_como_disponible_no_como_0():
    """A: MaxRects=0, Structural>0 (soporte por unión). IMPOSIBLE:
    MaxRects=0 Y Structural=0 (footprint mayor que el pallet entero,
    genuinamente estancado). MRV debe tratar a TOP como DISPONIBLE (no
    "deferred") y ordenarlo ANTES que IMPOSIBLE, que sigue siendo el único
    que se manda al final -exactamente la distinción que pide la sección
    9: "un SKU no puede considerarse en 0 candidatos si MaxRects=0 pero
    Structural>0", sin depender de un conteo exacto (en el pallet REAL,
    con piso abierto de sobra, Structural encuentra MÁS de 1 posición para
    TOP -eso no invalida la propiedad que se está probando: que ya NO se
    lo trata como 0/dead)."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    cand_imposible = _cand("IMPOSIBLE", 500, 500, 15, cantidad_disponible=1)
    nivel = {"A": 6, "B": 6, "TOP": 6, "IMPOSIBLE": 6}
    pc = _pallet_con_A_B_union()
    por_sku = {"TOP": [cand_top], "IMPOSIBLE": [cand_imposible]}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1, "IMPOSIBLE": 1},
    )

    # Premisas: ambos en 0 bajo MaxRects puro (pc.libres=[]).
    assert gr._contar_candidatos_y_registrar(estado, "TOP", por_sku, {}, nivel, {}, None, max_count=1) == 0
    assert gr._contar_candidatos_y_registrar(estado, "IMPOSIBLE", por_sku, {}, nivel, {}, None, max_count=1) == 0
    # Pero bajo el híbrido: TOP SÍ tiene salida (soporte por unión), IMPOSIBLE sigue en 0 (no cabe en ningún lado).
    assert gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, None, max_count=1, presupuesto=PRESUPUESTO,
    ) > 0
    assert gr._contar_candidatos_y_registrar(
        estado, "IMPOSIBLE", por_sku, {}, nivel, {}, None, max_count=1, presupuesto=PRESUPUESTO,
    ) == 0

    orden = gr._ordenar_mrv(
        ["IMPOSIBLE", "TOP"], estado, por_sku, {}, nivel, {}, "footprint", stats=None, presupuesto=PRESUPUESTO,
    )
    assert orden[0] == "TOP"  # disponible -ya no se manda al final solo por tener MaxRects=0
    assert orden[-1] == "IMPOSIBLE"  # el genuinamente estancado (MaxRects=0 Y Structural=0) sigue al final


# --- 12.6 Transposition --------------------------------------------------------

def test_12_6_clave_estado_refleja_placement_estructural_sin_colisionar():
    """Después de un placement estructural, `_clave_estado` debe reflejar
    torres/libres/pendientes correctamente -y NO colisionar con el estado
    anterior (antes del placement) ni con un estado con pendientes
    distintos."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()

    estado_antes = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1},
    )
    clave_antes = gr._clave_estado(estado_antes)

    pc_despues = gr._clonar_construccion(pc)
    torre = gr._colocar_candidato_estructural(pc_despues, cand_top, 0, 0, 20, 1)
    estado_despues = gr._EstadoGlobal(
        construcciones=[pc_despues], colocados_por_pallet=[{"A": 1, "B": 1, "TOP": 1}], pendientes={"TOP": 0},
    )
    clave_despues = gr._clave_estado(estado_despues)

    assert clave_antes != clave_despues  # el placement estructural cambió el estado -la clave debe reflejarlo
    assert torre.sku == "TOP" and torre.z == 20
    assert validar_pallet_v5(pc_despues.pallet) == []

    # Misma geometría que estado_despues, pero pendientes distinto -no debe colisionar (Fase 1.2, punto 4).
    estado_pendientes_distinto = gr._EstadoGlobal(
        construcciones=[pc_despues], colocados_por_pallet=[{"A": 1, "B": 1, "TOP": 1}], pendientes={"TOP": 0, "OTRO": 5},
    )
    assert gr._clave_estado(estado_despues) != gr._clave_estado(estado_pendientes_distinto)

    # El padre (pc) NO fue mutado por el placement en el clon (aislamiento, Fase 1.1 punto 5).
    assert len(pc.pallet.torres) == 2
