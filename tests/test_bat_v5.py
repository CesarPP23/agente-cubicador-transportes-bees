"""[V5-BAT-integrado] BAT entra como una fila de demanda más dentro del
MISMO multi-start (no una pasada aparte después): 500 unidades máximo por
caja, host conjunto (varias cajas en una torre, o repartidas entre varios
hosts), pallet 100% BAT cuenta físicamente y se renombra al esquema
dedicado, demanda BAT exacta -sin pérdida ni duplicado."""
import pandas as pd

import config
from models import CajaBAT
from src.bat import (
    BAT_SKU_MARCADOR,
    asignar_cajas_bat_a_torres,
    consolidar_bat_por_cd,
    construir_filas_bat_pseudo_sku,
    renombrar_pallets_bat_puros,
)
from src.packing_columnar import armar_pallets_columnar


def _caja_bat(id_bat, cd="BK31", unidades=500):
    return CajaBAT(cd=cd, id_bat=id_bat, unidades=unidades, cantidades_cajas={"9999": unidades / 10})


def _fila_sku(sku, largo, ancho, alto, cantidad, peso=1.0, cd="BK31"):
    return {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": peso, "Fuente_Geometria": "UMA_VALIDADA",
    }


def test_1000_unidades_maximo_por_caja():
    df_bat = pd.DataFrame(
        [{"CD": "BK31", "SKU": "9999", "Demanda_Unidades_Oficial": 1000, "Unidades_por_Caja": 10}]
    )
    cajas = consolidar_bat_por_cd(df_bat)
    assert len(cajas["BK31"]) == 1
    assert cajas["BK31"][0].unidades == 1000


def test_1001_unidades_da_2_cajas():
    df_bat = pd.DataFrame(
        [{"CD": "BK31", "SKU": "9999", "Demanda_Unidades_Oficial": 1001, "Unidades_por_Caja": 10}]
    )
    cajas = consolidar_bat_por_cd(df_bat)
    assert len(cajas["BK31"]) == 2
    assert sum(c.unidades for c in cajas["BK31"]) == 1001


def test_construir_filas_bat_pseudo_sku_una_fila_por_cd():
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas_por_cd = {"BK31": [_caja_bat("BAT-0"), _caja_bat("BAT-1")], "BK41": [_caja_bat("BAT-2", cd="BK41")]}
    df = construir_filas_bat_pseudo_sku(cajas_por_cd, info_sku)
    assert len(df) == 2
    fila_bk31 = df[df["CD"] == "BK31"].iloc[0]
    assert fila_bk31["SKU"] == BAT_SKU_MARCADOR
    assert fila_bk31["Cajas_Remanente"] == 2
    assert fila_bk31["Largo_Efectivo"] == config.CAJA_BAT_LARGO
    assert fila_bk31["Ancho_Efectivo"] == config.CAJA_BAT_ANCHO
    assert fila_bk31["Alto_Efectivo"] == config.CAJA_BAT_ALTO


def test_cd_sin_cajas_bat_no_genera_fila():
    df = construir_filas_bat_pseudo_sku({"BK31": []}, {})
    assert df.empty


def test_bat_comparte_pallet_con_una_sku_real_si_hay_lugar():
    """[integración] BAT entra al MISMO armar_pallets_columnar que una SKU
    real -termina compartiendo pallet si hay lugar, sin pasada aparte."""
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas = [_caja_bat(f"BAT-{i}") for i in range(3)]
    df_bat_pseudo = construir_filas_bat_pseudo_sku({"BK31": cajas}, info_sku)
    df_sku = pd.DataFrame([_fila_sku("A", 30, 20, 25.0, 2)])  # deja mucho lugar libre
    df_cd = pd.concat([df_sku, df_bat_pseudo], ignore_index=True)

    pallets = armar_pallets_columnar(df_cd, "BK31")
    renombrar_pallets_bat_puros(pallets, "BK31")
    asignar_cajas_bat_a_torres(pallets, cajas)

    assert len(pallets) == 1  # no hizo falta abrir un pallet dedicado
    assert sum(len(p.cajas_bat) for p in pallets) == 3  # ninguna demanda BAT se pierde
    assert not pallets[0].id.startswith("PV5-BAT-")  # comparte, no es dedicado


def test_mucha_demanda_bat_se_reparte_entre_varios_hosts_si_hace_falta():
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas = [_caja_bat(f"BAT-{i}") for i in range(6)]
    df_bat_pseudo = construir_filas_bat_pseudo_sku({"BK31": cajas}, info_sku)
    # Dos SKUs chicas -> dos pallets con poco margen cada uno, ninguno con
    # espacio para las 6 juntas, pero entre los dos sí alcanza repartidas.
    df_sku = pd.DataFrame([_fila_sku("A", 100, 90, 25.0, 1), _fila_sku("B", 100, 90, 25.0, 1)])
    df_cd = pd.concat([df_sku, df_bat_pseudo], ignore_index=True)

    pallets = armar_pallets_columnar(df_cd, "BK31")
    renombrar_pallets_bat_puros(pallets, "BK31")
    asignar_cajas_bat_a_torres(pallets, cajas)

    total_bat_colocadas = sum(len(p.cajas_bat) for p in pallets)
    assert total_bat_colocadas == 6  # ninguna demanda BAT se pierde


def test_pallet_100_por_ciento_bat_se_renombra_al_esquema_dedicado():
    """Mucha demanda BAT, nada de SKU real -> el/los pallets resultantes
    son 100% BAT y cuentan como pallets físicos dedicados de verdad."""
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas = [_caja_bat(f"BAT-{i}") for i in range(20)]
    df_bat_pseudo = construir_filas_bat_pseudo_sku({"BK31": cajas}, info_sku)

    pallets = armar_pallets_columnar(df_bat_pseudo, "BK31")
    renombrar_pallets_bat_puros(pallets, "BK31")
    asignar_cajas_bat_a_torres(pallets, cajas)

    assert pallets  # armó al menos un pallet
    assert all(p.id.startswith("PV5-BAT-BK31-") for p in pallets)
    assert sum(len(p.cajas_bat) for p in pallets) == 20


def test_asignar_cajas_bat_a_torres_nunca_pierde_ni_duplica_cajas():
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas = [_caja_bat(f"BAT-{i}") for i in range(7)]
    df_bat_pseudo = construir_filas_bat_pseudo_sku({"BK31": cajas}, info_sku)
    df_sku = pd.DataFrame([_fila_sku("A", 20, 20, 15.0, 3)])
    df_cd = pd.concat([df_sku, df_bat_pseudo], ignore_index=True)

    pallets = armar_pallets_columnar(df_cd, "BK31")
    renombrar_pallets_bat_puros(pallets, "BK31")
    asignar_cajas_bat_a_torres(pallets, cajas)

    asignadas = [c for p in pallets for c in p.cajas_bat]
    assert len(asignadas) == 7
    assert len({id(c) for c in asignadas}) == 7  # sin duplicados
    assert all(c.pallet_host_id is not None for c in cajas)


def test_bat_nunca_desplaza_torres_existentes():
    info_sku = {"9999": {"peso_caja": 1.0}}
    cajas = [_caja_bat("BAT-0")]
    df_bat_pseudo = construir_filas_bat_pseudo_sku({"BK31": cajas}, info_sku)
    df_sku = pd.DataFrame([_fila_sku("A", 30, 20, 25.0, 2)])
    df_cd = pd.concat([df_sku, df_bat_pseudo], ignore_index=True)

    pallets = armar_pallets_columnar(df_cd, "BK31")
    renombrar_pallets_bat_puros(pallets, "BK31")
    asignar_cajas_bat_a_torres(pallets, cajas)

    torres_no_bat = [t for p in pallets for t in p.torres if t.sku == "A"]
    assert torres_no_bat and sum(t.cantidad for t in torres_no_bat) == 2  # la demanda de A sigue completa
