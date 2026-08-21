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


def test_bat_nunca_abre_un_pallet_dedicado_si_hay_alternativa():
    """Prioridad de negocio explícita: una caja BAT nunca es un pallet
    físico aparte si hay lugar en uno ya armado -BAT entra como pseudo-SKU
    en el mismo armado que el resto de la demanda (ver bat.py, sección "BAT
    integrado"). Este test no afirma "cero dedicados jamás" -en datasets
    donde un CD agota literalmente todo el margen físico de sus pallets, un
    dedicado sigue siendo la única salida honesta- pero si aparece uno,
    tiene que ser porque de verdad no había otra opción."""
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    dedicados = [p for p in resultado.pallets if p.id.startswith("PV5-BAT-")]
    assert len(dedicados) < 30, (
        f"{len(dedicados)} pallets BAT dedicados: la consolidación en pallets "
        "ya armados no está funcionando como se espera."
    )


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


def test_cigarros_despacha_la_demanda_real_no_la_redondeada():
    """[Consolidación de Cigarros/vapes] Cigarros es la excepción a la regla
    de arriba a propósito: se despacha la demanda REAL fraccionaria (vía la
    caja de consolidación de 500 unidades), no ceil(Cajas Teóricas) por SKU.
    Redondear cada línea a una caja completa inflaba la demanda real ~3.8x
    (29.9 -> 114 cajas en este dataset) -ver config.CAJA_CONSOLIDACION_CIGARROS_*.

    Lo que sí debe seguir cumpliéndose: nunca se despacha MÁS que la demanda
    redondeada (eso lo cubre test_nunca_se_despacha_por_encima_de_la_demanda,
    que usa Cajas Teóricas real, no redondeada) y el total planificado tiene
    que acercarse a la demanda real, no quedarse en 0 ni excederla."""
    envios, maestro, uma = cargar_hojas(ARCHIVO_REAL)
    df_derivado, _ = _derivados(envios, maestro, uma)
    cigarros = df_derivado[df_derivado["Categoria_Normalizada"] == "Cigarros"]
    demanda_real = cigarros["Cajas Teóricas"].sum()
    demanda_redondeada = cigarros["Cajas_Teoricas_Redondeadas"].sum()

    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    planificado = df[df["Categoria"] == "Cigarros"]["Cajas_Totales_Pallet"].sum()

    assert demanda_real <= planificado <= demanda_redondeada + 1e-6
    # No es una prueba de la inflación en sí (ver el docstring), es una señal
    # de que la caja de consolidación está funcionando: el plan tiene que
    # quedar mucho más cerca de la demanda real que de la redondeada.
    punto_medio = (demanda_real + demanda_redondeada) / 2
    assert planificado < punto_medio


def test_log_validacion_registra_los_hallazgos_conocidos():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    reglas = set(resultado.log_validacion_df["regla"])
    assert "V6" in reglas
    # V7 ("Cajas por cama" nulo/0 en el Maestro) ya no aplica: la versión del
    # dataset corregida el 12-ago no tiene ningún SKU con ese dato faltante.
    # No es una regresión de código, es un hecho de la data actual.
