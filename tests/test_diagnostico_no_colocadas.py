"""[EXPERIMENTO V6.08-S2, sección 0] Test de regresión para el bug real
encontrado en S1: `_motivo_para_cuboide` referenciaba `config.
TOLERANCIA_ALTURA_CAMA_CM`, que nunca existió en `config.py` -la constante
real vive en `src/packing_bloques.py` (junto a `_altura_compatible_con_
cama`, la función que este chequeo replica). Este test ejerce exactamente
esa rama (`c.z > TOL`, torre existente al mismo nivel con `alto_caja`
distinto más allá de la tolerancia) y confirma que ya no lanza
`AttributeError`, y que clasifica correctamente como `LAYER_HEIGHT`."""
from models import PalletV5
from src.diagnostico_no_colocadas import LAYER_HEIGHT, _motivo_para_cuboide
from src.packing_bloques import TOLERANCIA_ALTURA_CAMA_CM
from src.packing_columnar import _CuboidLibre
from src.torres import TorreCandidate, crear_torre


def _pallet_con_soporte_y_vecino_de_otro_alto(alto_vecino: float) -> PalletV5:
    """Dos torres YA puestas: `BASE` (0->5cm, exactamente debajo de donde se
    evaluará el cuboide libre -da soporte real, para no confundir esto con
    el chequeo SUPPORT) y `VECINO`, que ARRANCA al mismo z=5.0 que el
    cuboide a evaluar (mismo nivel/cama), en otra posición del pallet, con
    `alto_caja=alto_vecino`."""
    cand_base = TorreCandidate("BASE", "CD", "L×A", 30, 30, 5.0, 10, 10, 1.0)
    torre_base = crear_torre(cand_base, x=40, y=0, z=0.0, cantidad=1)
    cand_vecino = TorreCandidate("VECINO", "CD", "L×A", 40, 40, alto_vecino, 10, 10, 1.0)
    torre_vecino = crear_torre(cand_vecino, x=0, y=0, z=5.0, cantidad=1)
    return PalletV5(id="P0", cd="CD", torres=[torre_base, torre_vecino])


def test_motivo_para_cuboide_no_crashea_por_altura_de_cama_y_clasifica_layer_height():
    """Reproduce el crash real de S1 (beam=128, BK52): un cuboide libre en
    el mismo nivel Z que una torre ya puesta (`VECINO`), con una diferencia
    de `alto_caja` mayor a `TOLERANCIA_ALTURA_CAMA_CM` -antes del fix, esta
    rama lanzaba `AttributeError: module 'config' has no attribute
    'TOLERANCIA_ALTURA_CAMA_CM'` en vez de devolver un motivo. `BASE` da
    soporte real al cuboide evaluado, para que la rama SUPPORT no dispare
    antes de llegar a la que este test ejercita."""
    alto_vecino = 20.0
    pallet = _pallet_con_soporte_y_vecino_de_otro_alto(alto_vecino)
    cand_nuevo = TorreCandidate(
        "C", "CD", "L×A", 30, 30, alto_vecino + TOLERANCIA_ALTURA_CAMA_CM + 1, 10, 10, 1.0,
    )
    cuboide = _CuboidLibre(x=40, y=0, z=5.0, w=60, h=40, d=cand_nuevo.alto_caja + 1)

    motivo = _motivo_para_cuboide(pallet, cuboide, cand_nuevo, tope_capa=None, nivel_sku=6, nivel_por_sku={})

    assert motivo == LAYER_HEIGHT


def test_motivo_para_cuboide_dentro_de_tolerancia_no_es_layer_height():
    """Control: misma geometría, pero con `alto_caja` DENTRO de la
    tolerancia -no debe clasificarse LAYER_HEIGHT (confirma que el fix usa
    el valor real de `TOLERANCIA_ALTURA_CAMA_CM`, ocho, no uno inventado ni
    cero)."""
    alto_vecino = 20.0
    pallet = _pallet_con_soporte_y_vecino_de_otro_alto(alto_vecino)
    cand_nuevo = TorreCandidate(
        "C", "CD", "L×A", 30, 30, alto_vecino + TOLERANCIA_ALTURA_CAMA_CM - 1, 10, 10, 1.0,
    )
    cuboide = _CuboidLibre(x=40, y=0, z=5.0, w=60, h=40, d=cand_nuevo.alto_caja + 1)

    motivo = _motivo_para_cuboide(pallet, cuboide, cand_nuevo, tope_capa=None, nivel_sku=6, nivel_por_sku={})

    assert motivo is None
