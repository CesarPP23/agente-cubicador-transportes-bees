"""[V-AUTO-CONSOLIDADO] Consolidar un SKU repartido en varios pallets del
mismo CD en el menor número posible -sin perder demanda, sin aumentar el
total de pallets, sin violar geometría."""
import config
from models import PalletV5
from src.bat import BAT_SKU_MARCADOR
from src.consolidacion_sku import consolidar_por_cd, consolidar_sku
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_geometria_v5


def _torre(sku, x, y, largo=20.0, ancho=20.0, alto=20.0, cantidad=1, z=0.0, peso=1.0):
    cand = TorreCandidate(
        sku=sku, cd="BK31", orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=cantidad, cantidad_disponible=cantidad, peso_unitario=peso,
    )
    return crear_torre(cand, x=x, y=y, cantidad=cantidad, z=z)


def test_junta_un_sku_repartido_en_dos_pallets_si_hay_lugar():
    """P1 tiene poco de la SKU A (cabe en el hueco de P2) -debería
    terminar TODO en P2, P1 se elimina si eso era lo único que tenía."""
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    # P2 ya tiene A y le sobra mucho lugar (huella grande, torre A chica).
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre("A", 0, 0, largo=20, ancho=20, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)

    resultado = consolidar_por_cd([p1, p2])

    assert len(resultado) == 1  # P1 se vació y desapareció
    torres_a = [t for p in resultado for t in p.torres if t.sku == "A"]
    assert sum(t.cantidad for t in torres_a) == 2  # demanda conservada


def test_no_consolida_si_no_hay_lugar_pero_no_pierde_nada():
    """Dos pallets llenos hasta el tope con la misma SKU -no hay a dónde
    mover nada. El resultado tiene que quedar IGUAL (rollback exacto)."""
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre("A", 0, 0, largo=120, ancho=100, cantidad=10, alto=21)], altura_final=config.ALTURA_PALLET_VACIO + 210)
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre("A", 0, 0, largo=120, ancho=100, cantidad=10, alto=21)], altura_final=config.ALTURA_PALLET_VACIO + 210)

    resultado = consolidar_por_cd([p1, p2])

    assert len(resultado) == 2
    total = sum(t.cantidad for p in resultado for t in p.torres if t.sku == "A")
    assert total == 20  # nada se perdió


def test_nunca_aumenta_el_total_de_pallets():
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1), _torre("B", 40, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)

    resultado = consolidar_por_cd([p1, p2])
    assert len(resultado) <= 2


def test_no_toca_torres_bat():
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre(BAT_SKU_MARCADOR, 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre(BAT_SKU_MARCADOR, 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)

    resultado = consolidar_por_cd([p1, p2])
    assert len(resultado) == 2  # BAT no se consolida acá, queda como estaba


def test_no_viola_geometria_despues_de_consolidar():
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1), _torre("B", 40, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)

    resultado = consolidar_por_cd([p1, p2])
    assert validar_geometria_v5(resultado) == []


def test_consolidar_sku_agrupa_por_cd_sin_mezclarlos():
    p1 = PalletV5(id="P1", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p2 = PalletV5(id="P2", cd="BK31", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p3 = PalletV5(id="P3", cd="BK41", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)
    p4 = PalletV5(id="P4", cd="BK41", torres=[_torre("A", 0, 0, cantidad=1)], altura_final=config.ALTURA_PALLET_VACIO + 20)

    resultado = consolidar_sku([p1, p2, p3, p4])
    cds = {p.cd for p in resultado}
    assert cds == {"BK31", "BK41"}
    total_a = sum(t.cantidad for p in resultado for t in p.torres if t.sku == "A")
    assert total_a == 4
