from pathlib import Path

import config
from src.derivados import calcular_derivados
from src.pipeline import ejecutar_desde_archivo
from src.validacion import cargar_hojas, validar_y_limpiar

ARCHIVO_REAL = Path(__file__).resolve().parent.parent / "Cubicaje18.07.2026.xlsx"


def test_no_genera_pallets_homogeneos_con_demanda_de_julio():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    assert (resultado.plan_picking_df["Tipo_Pallet"] == "Homogéneo").sum() == 0


def test_alturas_nunca_exceden_el_maximo():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    alturas = resultado.plan_picking_df.drop_duplicates("ID_Pallet")["Altura_Final_Pallet_cm"]
    assert (alturas <= config.ALTURA_TOTAL_MAX).all()


def test_ningun_pallet_mezcla_comestibles_y_cigarros_como_remate():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    for _, grupo in df.groupby("ID_Pallet"):
        categorias = set(grupo["Categoria"].dropna())
        assert not ({"Comestibles", "Cigarros"} <= categorias)


def test_demanda_planificada_coincide_con_demanda_redondeada():
    envios, maestro, uma = cargar_hojas(ARCHIVO_REAL)
    df_validado, _ = validar_y_limpiar(envios, maestro, uma)
    df_derivado = calcular_derivados(df_validado)

    demanda_esperada = df_derivado.groupby(["CD", "SKU"])["Cajas_Teoricas_Redondeadas"].sum()

    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    df["SKU"] = df["SKU"].astype(str)
    demanda_planificada = df.groupby(["CD", "SKU"])["Cajas_Totales_Pallet"].sum()

    assert demanda_esperada.index.difference(demanda_planificada.index).empty
    assert demanda_planificada.index.difference(demanda_esperada.index).empty
    diferencias = (demanda_planificada - demanda_esperada).dropna()
    assert (diferencias == 0).all()


def test_log_validacion_registra_los_hallazgos_conocidos():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    reglas = set(resultado.log_validacion_df["regla"])
    assert "V6" in reglas
    assert "V7" in reglas
