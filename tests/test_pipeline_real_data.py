from pathlib import Path

import config
from src.derivados import calcular_derivados
from src.pipeline import ejecutar_desde_archivo
from src.reconciliacion_geometrica import reconciliar
from src.validacion import cargar_hojas, validar_y_limpiar

ARCHIVO_REAL = Path(__file__).resolve().parent.parent / "Cubicaje18.07.2026.xlsx"


def _derivados(envios, maestro, uma):
    df, log = validar_y_limpiar(envios, maestro, uma)
    df, _auditoria = reconciliar(df)
    return calcular_derivados(df), log


def test_alturas_nunca_exceden_el_tope_duro():
    """[Sección 3.3 / v2] El techo real no es ALTURA_TOTAL_MAX (205, el máximo
    NORMAL): un pallet que todavía no llegó al mínimo tolerado (185) puede
    estirarse hasta ALTURA_TOPE_DURO (210) para cerrar -ver
    apilado_3d._limite_altura. Comparar contra 205 quedó dormido mientras
    ningún pallet entraba a esa franja; con FILL_RATIO_MIN_SOPORTE en 0 (ver
    config.py) más pallets llegan a cerrar ahí, y el assert viejo empezó a
    fallar contra un comportamiento correcto."""
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    alturas = resultado.plan_picking_df.drop_duplicates("ID_Pallet")["Altura_Final_Pallet_cm"]
    assert (alturas <= config.ALTURA_TOPE_DURO).all()


def test_cigarros_nunca_entran_al_cubicaje():
    """[regla explícita del usuario, sept-2026] Cigarros/vapes ya no compiten
    por espacio ni abren pallet propio -ni compartido ni dedicado: se separan
    de la demanda ANTES del armado (ver bat.separar_bat) y se reportan aparte
    en la hoja "Cigarros" (`resultado.demanda_cigarros_df`), nunca dentro de
    `resultado.pallets`/`Plan_Picking`."""
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    dedicados = [p for p in resultado.pallets if p.id.startswith("PV5-BAT-")]
    assert dedicados == []
    for pallet in resultado.pallets:
        assert all(linea.categoria != "Cigarros" for linea in pallet.lineas)
    assert not (resultado.plan_picking_df["Categoria"] == "Cigarros").any()


def test_demanda_planificada_coincide_con_demanda_redondeada():
    """Para todas las categorías salvo Cigarros, el plan debe coincidir EXACTO
    con la demanda redondeada hacia arriba (Cajas_Teoricas_Redondeadas)."""
    envios, maestro, uma = cargar_hojas(ARCHIVO_REAL)
    df_derivado, _ = _derivados(envios, maestro, uma)
    df_derivado = df_derivado[df_derivado["Categoria_Normalizada"] != "Cigarros"]

    demanda_esperada = df_derivado.groupby(["CD", "SKU"])["Cajas_Teoricas_Redondeadas"].sum()

    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    df["SKU"] = df["SKU"].astype(str)
    df_sin_cigarros = df[df["Categoria"] != "Cigarros"]
    demanda_planificada = df_sin_cigarros.groupby(["CD", "SKU"])["Cajas_Totales_Pallet"].sum()

    assert demanda_esperada.index.difference(demanda_planificada.index).empty
    assert demanda_planificada.index.difference(demanda_esperada.index).empty
    diferencias = (demanda_planificada - demanda_esperada).dropna()
    assert (diferencias == 0).all()


def test_cigarros_se_reporta_aparte_con_la_demanda_real():
    """[Consolidación de Cigarros/vapes, regla explícita del usuario,
    sept-2026] Cigarros/vapes ya no se despachan dentro de ningún pallet -se
    reportan en `demanda_cigarros_df` (hoja "Cigarros" del Excel final) con
    la demanda REAL en unidades, no ceil(Cajas Teóricas) por SKU (redondear
    cada línea a caja completa infla la demanda real ~3.8x en este
    dataset -ver config.CAJA_BAT_*)."""
    envios, maestro, uma = cargar_hojas(ARCHIVO_REAL)
    df_derivado, _ = _derivados(envios, maestro, uma)
    cigarros = df_derivado[df_derivado["Categoria_Normalizada"] == "Cigarros"]
    unidades_reales_esperadas = cigarros["Unidades"].sum()

    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    assert resultado.demanda_cigarros_df is not None and not resultado.demanda_cigarros_df.empty
    unidades_reportadas = resultado.demanda_cigarros_df["Unidades_Demanda"].sum()

    assert unidades_reportadas == unidades_reales_esperadas
    # Cero cajas de consolidación reportadas sería tan raro como demanda 0
    # -confirma que consolidar_bat_por_cd corrió sobre esta demanda real.
    assert (resultado.demanda_cigarros_df["Cajas_Consolidacion_Necesarias_CD"] > 0).all()


def test_log_validacion_registra_los_hallazgos_conocidos():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    reglas = set(resultado.log_validacion_df["regla"])
    assert "V6" in reglas
    # V7 ("Cajas por cama" nulo/0 en el Maestro) ya no aplica: la versión del
    # dataset corregida el 12-ago no tiene ningún SKU con ese dato faltante.
    # No es una regresión de código, es un hecho de la data actual.
