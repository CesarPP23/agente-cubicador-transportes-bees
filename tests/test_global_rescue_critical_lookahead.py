"""[PATCH V6.09] Critical Precedence Lookahead -tests obligatorios de las
secciones 11-15 del parche. El mecanismo es GENERAL (nunca referencia
SKUs concretos en `src/global_rescue.py`); los nombres de SKU usados acá
(AGGRESSOR/VICTIM/X/Y/S/B/C, y 22351/22353/23510 en la sección 15) son
datos del TEST, no del mecanismo.

Todas las geometrías fueron verificadas empíricamente contra las
funciones reales de producción antes de fijarlas acá (nunca "coordenadas
aproximadas" adivinadas) -dos mecanismos de asimetría, ambos reglas reales
del solver, no trucos del test:

- Jerarquía de nivel (`_soporte_viola_nivel`, packing_bloques.py): una
  caja de nivel ALTO ya puesta bloquea a una de nivel BAJO encima; al
  revés NO -da una asimetría de precedencia limpia (tests 11, 14, 15).
- Presupuesto de altura: dos cajas cuya suma de alturas excede el
  presupuesto no pueden coexistir en la misma columna, sea cual sea el
  orden -da un conflicto genuinamente SIMÉTRICO (test 13)."""
import config
import src.global_rescue as gr
from models import PalletV5
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible, max_verticales=2):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _pallet_vacio():
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    return _PalletEnConstruccion(pallet=pallet)


def _stats_vacio() -> dict:
    return {
        "por_sku": {}, "raw_candidates_generados": 0, "candidates_retenidos_top_k": 0,
        "estados_generados": 0, "duplicados": 0, "transposition_hits": 0, "estados_pruned_no_moves": 0,
    }


# --- 11. Asimetría -sin lookahead incompleto, con lookahead 100% --------------

def _fixture_asimetria():
    """AGGRESSOR (nivel alto, 1 candidato) vs VICTIM (nivel bajo, 1
    candidato) -mismo footprint (todo el pallet), AGGRESSOR elegido por
    MRV (empate en candidatos, desempate por mayor pendiente). AGGRESSOR
    primero: sus 2 únicos hijos (batch=1, batch=2) dejan a VICTIM en 0
    candidatos (bloqueado por jerarquía de nivel, verificado). VICTIM
    primero: AGGRESSOR sigue teniendo su candidato (jerarquía de nivel no
    bloquea en esa dirección)."""
    por_sku = {
        "AGGRESSOR": [_cand("AGGRESSOR", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=2)],
        "VICTIM": [_cand("VICTIM", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=1)],
    }
    nivel_por_sku = {"AGGRESSOR": 6, "VICTIM": 3}
    estado = gr._EstadoGlobal(
        construcciones=[_pallet_vacio()], colocados_por_pallet=[{}], pendientes={"AGGRESSOR": 2, "VICTIM": 1},
    )
    return estado, por_sku, nivel_por_sku


def test_11_asimetria_sin_lookahead_incompleto_con_lookahead_100_por_ciento():
    estado, por_sku, nivel_por_sku = _fixture_asimetria()

    # Premisa: MRV elige AGGRESSOR (menos candidatos, o empate desempatado por pendiente).
    orden = gr._ordenar_mrv(
        ["AGGRESSOR", "VICTIM"], estado, por_sku, {}, nivel_por_sku, {}, "demanda", None, PRESUPUESTO, None,
    )
    assert orden[0] == "AGGRESSOR"

    # Sin lookahead (comportamiento V6.08 puro, vía el helper de bajo
    # nivel): TODOS los hijos normales de AGGRESSOR quedan muertos.
    hijos_sin_lookahead = gr._expandir_sku_en_estado(
        estado, "AGGRESSOR", por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None, gr.CacheEstructural(),
    )
    assert hijos_sin_lookahead
    assert all(
        gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0]
        for h in hijos_sin_lookahead
    )

    # Con lookahead (mecanismo completo, vía `_expandir_estado`): al menos
    # un hijo sobrevive.
    stats = _stats_vacio()
    hijos_con_lookahead = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "demanda", stats, PRESUPUESTO)
    vivos = [h for h in hijos_con_lookahead if not gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0]]
    assert vivos, "el rescate debe dejar al menos un hijo vivo"
    assert all(h.pendientes.get("VICTIM", 0) == 0 for h in vivos), "el hijo vivo debe haber resuelto VICTIM primero"

    assert stats["critical_lookahead_calls"] == 1
    assert stats["precedence_constraints_detected"] == 1
    assert stats["victims_considered"] == 1
    assert stats["victim_first_children_viable"] >= 1
    evento = stats["critical_lookahead_events"][0]
    assert evento["selected_sku"] == "AGGRESSOR"
    assert evento["victim_sku"] == "VICTIM"
    assert evento["normal_children_killing_victim"] == evento["normal_children"]  # 100%


# --- 12. Sin overhead cuando no hace falta -------------------------------------

def test_12_sin_overhead_cuando_al_menos_un_hijo_normal_es_viable():
    """Mismo patrón de `test_10_5` (SKUs independientes, sin conflicto) -
    al menos un hijo normal de A deja a B intacto -> lookahead NUNCA se
    activa."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=2)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=3)],
    }
    nivel_por_sku = {"A": 6, "B": 6}
    estado = gr._EstadoGlobal(
        construcciones=[_pallet_vacio()], colocados_por_pallet=[{}], pendientes={"A": 2, "B": 3},
    )
    stats = _stats_vacio()
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "demanda", stats, PRESUPUESTO)
    assert hijos
    assert stats.get("critical_lookahead_calls", 0) == 0
    assert stats.get("victims_considered", 0) == 0
    # resultado igual al solver previo -ningún hijo es un rescate.
    assert all(not gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0] for h in hijos)


# --- 13. Conflicto simétrico ----------------------------------------------------

def test_13_conflicto_simetrico_no_loopea_no_crashea_mejor_parcial_valido():
    """X y Y compiten por la MISMA columna con presupuesto de altura
    insuficiente para las dos -X primero mata a Y, Y primero mata a X
    (simétrico, verificado). Lookahead no debe loopear ni crashear; debe
    terminar con un mejor parcial válido (mismo criterio que la poda
    actual: los hijos siguen compitiendo por `mejor_estado`, ninguno
    llega al 100%)."""
    alto = 110.0  # 2 * 110 > PRESUPUESTO (~205) -> nunca caben apiladas, sea cual sea el orden
    por_sku = {
        "X": [_cand("X", config.PALLET_LARGO, config.PALLET_ANCHO, alto, cantidad_disponible=1, max_verticales=1)],
        "Y": [_cand("Y", config.PALLET_LARGO, config.PALLET_ANCHO, alto, cantidad_disponible=1, max_verticales=1)],
    }
    nivel_por_sku = {"X": 5, "Y": 5}
    estado = gr._EstadoGlobal(
        construcciones=[_pallet_vacio()], colocados_por_pallet=[{}], pendientes={"X": 1, "Y": 1},
    )
    stats = _stats_vacio()
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "demanda", stats, PRESUPUESTO)
    # No crashea, no cuelga (ya llegamos hasta acá). Se conservan hijos
    # (para mejor_estado parcial) aunque ninguno alcance el 100%.
    assert hijos
    assert all(sum(c for c in h.pendientes.values() if c > 0) > 0 for h in hijos)  # ninguno llega a 100%
    mejor = max(hijos, key=lambda h: h.cajas_colocadas)
    assert mejor.cajas_colocadas > 0  # mejor parcial válido, no vacío
    # No inventa una solución que no existe: el lookahead se activó (S mata
    # a la otra), probó víctima primero, pero la víctima-primero por sí
    # sola sigue sin alcanzar el 100% -consistente con la simetría real.
    assert stats.get("critical_lookahead_calls", 0) >= 1


# --- 14. Múltiples víctimas ------------------------------------------------------

def test_14_multiples_victimas_detectadas_ordenadas_y_probadas():
    """S (nivel más alto) mata a B Y C simultáneamente (mismo mecanismo de
    jerarquía que el test 11, con dos víctimas en vez de una) -debe
    detectar ambas, probarlas (hasta CRITICAL_LOOKAHEAD_MAX_VICTIMS=3,
    acá son solo 2) y preservar cualquier victim-first viable."""
    por_sku = {
        "S": [_cand("S", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=2, max_verticales=2)],
        "B": [_cand("B", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=1)],
        "C": [_cand("C", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=1)],
    }
    nivel_por_sku = {"S": 9, "B": 3, "C": 4}
    estado = gr._EstadoGlobal(
        construcciones=[_pallet_vacio()], colocados_por_pallet=[{}], pendientes={"S": 2, "B": 1, "C": 1},
    )
    orden = gr._ordenar_mrv(["S", "B", "C"], estado, por_sku, {}, nivel_por_sku, {}, "demanda", None, PRESUPUESTO, None)
    assert orden[0] == "S"

    stats = _stats_vacio()
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "demanda", stats, PRESUPUESTO)
    assert hijos
    assert stats["critical_lookahead_calls"] == 1
    assert stats["victims_considered"] == 2  # B y C, ambas detectadas
    victimas_en_eventos = {e["victim_sku"] for e in stats["critical_lookahead_events"]}
    assert victimas_en_eventos == {"B", "C"}
    # Al menos un hijo victim-first (B primero o C primero) sobrevive.
    vivos = [h for h in hijos if not gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0]]
    assert vivos


# --- 15. Regresión S3 -----------------------------------------------------------

def test_15_regresion_s3_22351_selected_22353_victima_rescate_completo():
    """Reconstrucción del hallazgo real de S3 con los mismos 3 SKUs
    (22351/22353/23510) -no depende de coordenadas manuales aproximadas:
    usa el MISMO mecanismo de jerarquía de nivel verificado en el test 11
    (22351 = agresor de nivel alto, 22353 = víctima de nivel bajo), con
    23510 como tercer SKU independiente (mismo patrón que el test 12, no
    debe interferir). Verifica el flujo mínimo pedido por la sección 15:
    selected=22351, dead-end normal, lookahead detecta 22353, rescate
    completo."""
    por_sku = {
        "22351": [_cand("22351", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=2)],
        "22353": [_cand("22353", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=1)],
        "23510": [_cand("23510", config.PALLET_LARGO, config.PALLET_ANCHO, 20, cantidad_disponible=1)],
    }
    # [fiel al hallazgo real -S3 confirmó que la colocación normal de
    # 22351 mataba a LOS DOS, 22353 Y 23510, a la vez] Mismo footprint de
    # todo el pallet para las 3 -22351 (nivel alto) bloquea a AMBAS (nivel
    # bajo) al ir primero; nivel bajo NO bloquea a nivel alto al revés
    # (mismo mecanismo verificado en el test 11).
    nivel_por_sku = {"22351": 6, "22353": 3, "23510": 3}
    estado = gr._EstadoGlobal(
        construcciones=[_pallet_vacio()], colocados_por_pallet=[{}], pendientes={"22351": 2, "22353": 1, "23510": 1},
    )

    orden = gr._ordenar_mrv(
        ["22351", "22353", "23510"], estado, por_sku, {}, nivel_por_sku, {}, "demanda", None, PRESUPUESTO, None,
    )
    assert orden[0] == "22351"  # normal_selected_sku

    # Normal children -> dead-end (sin lookahead).
    hijos_normales = gr._expandir_sku_en_estado(
        estado, "22351", por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None, gr.CacheEstructural(),
    )
    assert hijos_normales
    assert all(
        gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0] for h in hijos_normales
    )

    # Lookahead detecta 22353 como víctima y rescata.
    stats = _stats_vacio()
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel_por_sku, {}, "demanda", stats, PRESUPUESTO)
    assert stats["critical_lookahead_calls"] == 1
    assert any(e["victim_sku"] == "22353" for e in stats["critical_lookahead_events"])
    vivos = [h for h in hijos if not gr._evaluar_viabilidad(h, por_sku, {}, nivel_por_sku, {}, PRESUPUESTO, None)[0]]
    assert vivos
    assert any(h.pendientes.get("22353", 0) == 0 for h in vivos)
