"""[V5-P12] Visualización 3D real: toda posición exportada debe poder verse."""
import matplotlib

matplotlib.use("Agg")

import config
from models import PalletV5
from src.bat import BAT_SKU_MARCADOR
from src.torres import TorreCandidate, crear_torre
from visualizacion import VISTAS_3D, _cuboide, dibujar_pallet_v5_3d


def _torre(sku, x, y, largo=30.0, ancho=20.0, alto=25.0, cantidad=3, peso=2.0):
    cand = TorreCandidate(
        sku=sku, cd="BK31", orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=cantidad, cantidad_disponible=cantidad, peso_unitario=peso,
    )
    return crear_torre(cand, x=x, y=y, cantidad=cantidad)


def test_cuboide_devuelve_6_caras_de_4_vertices():
    caras = _cuboide(0, 0, 0, 10, 20, 30)
    assert len(caras) == 6
    assert all(len(cara) == 4 for cara in caras)


def test_dibuja_pallet_con_torre_normal_y_torre_bat_en_las_4_vistas():
    torre_normal = _torre("111", x=0, y=0)
    torre_bat = _torre(BAT_SKU_MARCADOR, x=40, y=0, largo=config.CAJA_BAT_LARGO, ancho=config.CAJA_BAT_ANCHO, alto=config.CAJA_BAT_ALTO, cantidad=2)
    pallet = PalletV5(
        id="PV5-BK31-001", cd="BK31", torres=[torre_normal, torre_bat],
        altura_final=config.ALTURA_PALLET_VACIO + max(torre_normal.altura, torre_bat.altura), estado="OK",
    )
    info_sku = {"111": {"categoria": "Licores"}}

    for vista in VISTAS_3D:
        fig = dibujar_pallet_v5_3d(pallet, info_sku, vista=vista)
        assert fig is not None
        ax = fig.axes[0]
        # 1 base del pallet + 3 cajas de la torre normal + 2 cajas BAT = 6 colecciones 3D.
        assert len(ax.collections) == 1 + torre_normal.cantidad + torre_bat.cantidad


def test_dibuja_pallet_sin_torres_no_revienta():
    pallet = PalletV5(id="PV5-BK31-VACIO", cd="BK31", torres=[], altura_final=config.ALTURA_PALLET_VACIO)
    fig = dibujar_pallet_v5_3d(pallet, {}, vista="isometrica")
    assert fig is not None
