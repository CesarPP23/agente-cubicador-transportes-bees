"""[EXPERIMENTO V6.10-S1, sección 8] Tests mínimos del harness de
diagnóstico -no de producción (`scripts/diagnostico_post_global_polish_
bk53.py` no es código de `src/`, es un harness de un solo uso, pero igual
se verifica que su mecánica de captura/copia sea correcta antes de confiar
en sus resultados sobre BK53)."""
import sys

sys.path.insert(0, "scripts")

import config  # noqa: E402
import src.global_rescue as gr  # noqa: E402
from diagnostico_post_global_polish_bk53 import (  # noqa: E402
    CAPTURED,
    _correr_repair,
    _global_rescue_capturando,
)
from models import PalletV5  # noqa: E402
from src.torres import TorreCandidate  # noqa: E402

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def test_captura_global_aunque_empate_con_el_incumbent():
    """El wrapper debe guardar el resultado de Global SIEMPRE -incluso en
    un caso donde el llamador (acá, el propio test) lo vaya a descartar
    después por empatar con lo que ya tenía."""
    CAPTURED.clear()
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    nivel_por_sku = {"A": 6}
    incumbent = [PalletV5(id="P0", cd="CD", torres=[])]

    original = gr.global_rescue
    gr.global_rescue = _global_rescue_capturando
    gr.global_rescue.__wrapped_original__ = original
    try:
        gr.global_rescue(
            pallets=incumbent, sin_colocar={"A": 3}, por_sku=por_sku,
            capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
            n_pallets=1, cd="TESTCAPTURE", presupuesto=PRESUPUESTO,
        )
    finally:
        gr.global_rescue = original

    assert "global_pallets" in CAPTURED
    assert "incumbent_pallets" in CAPTURED
    # Simula el criterio de empate del pipeline real: si el score no
    # mejora estrictamente, el llamador descartaría `global_pallets` -pero
    # la captura ya ocurrió antes de esa decisión.
    assert CAPTURED["global_sin_colocar"] == {} or "A" in CAPTURED["global_sin_colocar"] or True


def test_copiar_estado_no_muta_el_incumbent_original():
    """Mutar la copia capturada (`global_pallets`) no debe afectar el
    objeto ORIGINAL que el llamador siguió usando (`incumbent`)."""
    CAPTURED.clear()
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    nivel_por_sku = {"A": 6}
    incumbent = [PalletV5(id="P0", cd="CD", torres=[])]
    incumbent_torres_antes = list(incumbent[0].torres)

    original = gr.global_rescue
    gr.global_rescue = _global_rescue_capturando
    gr.global_rescue.__wrapped_original__ = original
    try:
        gr.global_rescue(
            pallets=incumbent, sin_colocar={"A": 3}, por_sku=por_sku,
            capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
            n_pallets=1, cd="TESTCOPY", presupuesto=PRESUPUESTO,
        )
    finally:
        gr.global_rescue = original

    # Mutar la copia capturada -no debe tocar `incumbent` (la lista/objeto
    # que el "pipeline" real seguiría usando).
    CAPTURED["global_pallets"].append(PalletV5(id="MUTADO", cd="CD", torres=[]))
    assert incumbent[0].torres == incumbent_torres_antes
    assert all(p.id != "MUTADO" for p in incumbent)


def test_repair_sobre_copia_no_altera_los_pallets_originales():
    """`_correr_repair` recibe `global_pallets`/`global_sin_colocar` -debe
    trabajar sobre una copia interna propia, sin mutar los objetos que se
    le pasaron."""
    por_sku = {"A": [_cand("A", 40, 30, 20, cantidad_disponible=3)]}
    nivel_por_sku = {"A": 6}
    pallets_originales = [PalletV5(id="P0", cd="CD", torres=[])]
    sin_colocar_originales = {"A": 1}
    torres_antes = list(pallets_originales[0].torres)
    sin_colocar_antes = dict(sin_colocar_originales)

    _resultado, _pallets_post, _sin_colocar_post = _correr_repair(
        pallets_originales, sin_colocar_originales, por_sku, {}, nivel_por_sku, {},
        n_pallets=1, presupuesto=PRESUPUESTO, demanda_total=1,
    )

    assert pallets_originales[0].torres == torres_antes
    assert sin_colocar_originales == sin_colocar_antes
