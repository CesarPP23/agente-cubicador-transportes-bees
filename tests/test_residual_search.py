"""[V5-P8] Residual Elimination Search: puede desarmar un pallet y
reinsertar su contenido, rollback exacto si falla, nunca aumenta pallets,
determinístico."""
import copy

import config
from models import PalletV5
from src.residual_search import eliminar_residuales
from src.torres import TorreCandidate, crear_torre


def _torre(sku, x, y, largo=20.0, ancho=20.0, alto=20.0, cantidad=2, peso=1.0):
    cand = TorreCandidate(
        sku=sku, cd="BK31", orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=cantidad, cantidad_disponible=cantidad, peso_unitario=peso,
    )
    return crear_torre(cand, x=x, y=y, cantidad=cantidad)


def test_puede_destruir_un_pallet_y_reinsertar_su_contenido():
    # Pallet chico (1 torre, footprint 20x20) + pallet grande con mucho lugar libre.
    chico = PalletV5(id="A", cd="BK31", torres=[_torre("X", 0, 0)], altura_final=config.ALTURA_PALLET_VACIO + 40)
    grande = PalletV5(id="B", cd="BK31", torres=[_torre("Y", 0, 0, largo=20, ancho=20, cantidad=2)], altura_final=config.ALTURA_PALLET_VACIO + 40)

    resultado = eliminar_residuales([chico, grande])
    assert len(resultado) == 1  # el chico se desarmó y se sumó al grande
    assert resultado[0].id == "B"
    skus = {t.sku for t in resultado[0].torres}
    assert skus == {"X", "Y"}


def test_nunca_aumenta_la_cantidad_de_pallets():
    pallets = [
        PalletV5(id=f"P{i}", cd="BK31", torres=[_torre(f"S{i}", 0, 0, cantidad=3)], altura_final=config.ALTURA_PALLET_VACIO + 60)
        for i in range(4)
    ]
    resultado = eliminar_residuales(pallets)
    assert len(resultado) <= len(pallets)


def test_rollback_exacto_si_no_hay_donde_reinsertar():
    """Dos pallets, cada uno con su footprint 120x100 COMPLETO ocupado (nada
    de área libre) -no hay margen para mover nada, ni de altura ni de XY. El
    intento debe fallar limpio: mismo contenido, mismo número de pallets,
    nada corrupto a mitad de camino."""
    torre_alta_a = _torre("A", 0, 0, largo=120, ancho=100, alto=100, cantidad=2)  # ocupa TODO el piso
    torre_alta_b = _torre("B", 0, 0, largo=120, ancho=100, alto=100, cantidad=2)
    p1 = PalletV5(id="A", cd="BK31", torres=[torre_alta_a], altura_final=config.ALTURA_PALLET_VACIO + torre_alta_a.altura)
    p2 = PalletV5(id="B", cd="BK31", torres=[torre_alta_b], altura_final=config.ALTURA_PALLET_VACIO + torre_alta_b.altura)

    snapshot = copy.deepcopy([p1, p2])
    resultado = eliminar_residuales([p1, p2])

    assert len(resultado) == 2  # no se pudo eliminar ninguno -ambos pisos están completos
    for original, restaurado in zip(snapshot, sorted(resultado, key=lambda p: p.id)):
        assert original.id == restaurado.id
        assert len(original.torres) == len(restaurado.torres)
        assert original.altura_final == restaurado.altura_final


def test_nunca_pierde_demanda():
    pallets = [
        PalletV5(id="A", cd="BK31", torres=[_torre("X", 0, 0, cantidad=5)], altura_final=config.ALTURA_PALLET_VACIO + 50),
        PalletV5(id="B", cd="BK31", torres=[_torre("Y", 0, 0, cantidad=3)], altura_final=config.ALTURA_PALLET_VACIO + 30),
    ]
    total_antes = sum(t.cantidad for p in pallets for t in p.torres)
    resultado = eliminar_residuales(pallets)
    total_despues = sum(t.cantidad for p in resultado for t in p.torres)
    assert total_antes == total_despues


def test_determinismo():
    def _armar():
        return [
            PalletV5(id="A", cd="BK31", torres=[_torre("X", 0, 0, cantidad=2)], altura_final=config.ALTURA_PALLET_VACIO + 40),
            PalletV5(id="B", cd="BK31", torres=[_torre("Y", 0, 0, cantidad=2)], altura_final=config.ALTURA_PALLET_VACIO + 40),
            PalletV5(id="C", cd="BK31", torres=[_torre("Z", 0, 0, cantidad=2)], altura_final=config.ALTURA_PALLET_VACIO + 40),
        ]

    r1 = eliminar_residuales(_armar())
    r2 = eliminar_residuales(_armar())
    assert [p.id for p in r1] == [p.id for p in r2]
    assert [len(p.torres) for p in r1] == [len(p.torres) for p in r2]
