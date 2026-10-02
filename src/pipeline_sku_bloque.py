"""[SKU_BLOQUE] Pipeline para la lógica de bloques.

[vuelta al motor exacto -ver PATCH_LOG.md] Se probó `packing_ph_fraccion.py`
(armado aproximado por fracción de PH, calibrado contra un cubicaje real)
pero el usuario, viendo el resultado real en la app, encontró camas con
hasta 21% de cobertura de soporte faltante en promedio (742 torres con
menos del 50% de apoyo real, muchas con 0%) -"eso no puede pasar". Se
volvió a `src/packing_bloques.py` (el motor geométrico exacto, MaxRects 3D,
0% de flotación verificado), ahora con 2 agregados que sí demostró
`packing_ph_fraccion.py` que ayudan a recuperar densidad sin sacrificar la
garantía exacta: orientación flexible (Comestibles/Aseo/Cigarros pueden
acostarse, NABs siempre de pie) y el tope real de `Cajas por PH` por
pallet. `packing_ph_fraccion.py` queda en el repo, probado, pero no es el
que usa el pipeline.

Reutiliza VAL/DEM/GEO/DER/SPLIT/PESO/EXP tal cual el resto de los motores
-esa infraestructura no depende de la estrategia de armado."""
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

import config
from models import Pallet, PalletLinea, PalletV5, ResultadoPipeline
from src import (
    bat,
    benchmark,
    demanda,
    derivados,
    estabilidad,
    exportar,
    reconciliacion_geometrica,
    soporte,
    validacion,
    validacion_peso,
)
from src.packing_bloques import armar_pallets_bloques
from src.pipeline import (
    _construir_info_sku,
    _construir_pallets_geometria_insuficiente,
    _construir_pallets_sin_clasificar,
)


# [PATCH V6.12-D6.1 -ID_ASSIGNMENT_NONDETERMINISM, ver V6.12-D6] El
# contador que arma `ID_Pallet` (`PV5-{cd}-NNN`) es compartido y nunca se
# resetea entre sondeos de `politica_a_descenso`/cascada Rescue/Repair/
# Exact/Global -confirmado en D6 que estos sondeos DESCARTADOS, con un
# `time.process_time()` real todavía sin calendarizar de forma
# determinista (fuera de alcance de D5/D6.1), pueden consumir una
# cantidad distinta de números según contención real entre corridas
# "idénticas" -sin cambiar NUNCA el contenido final (demostrado
# empíricamente: `content_diffs` vacío en las 4 corridas de D6, solo
# `id_only_diffs`). Este prefijo excluye del renombrado a los pallets
# dedicados BAT (`bat.renombrar_pallets_bat_puros`, esquema
# `PV5-BAT-{cd}-NNN` que reconoce `benchmark.calcular_kpis` por prefijo)
# -se dejan exactamente como están, nunca se tocan ni reordenan acá.
_PREFIJO_BAT_DEDICADO = "PV5-BAT-"


def _firma_torre_canonica(torre) -> tuple:
    """[PATCH V6.12-D6.1] Firma de UNA torre, independiente de cuándo o en
    qué orden interno se creó -solo lo que físicamente contiene. Misma
    precisión contractual que ya usa `global_rescue._signature_torres`
    (`round(..., 2)` para coordenadas/dimensiones), extendida con
    `alto_caja` para capturar el resto de la geometría que puede
    distinguir dos pallets."""
    return (
        torre.sku, torre.cantidad, round(torre.x, 2), round(torre.y, 2), round(torre.z, 2),
        round(torre.largo, 2), round(torre.ancho, 2), round(torre.alto_caja, 2), torre.orientacion,
    )


def _firma_pallet_canonica(pallet: PalletV5) -> tuple:
    """[PATCH V6.12-D6.1] Firma de UN pallet completo: multiset ordenado de
    firmas de torres -nunca depende de ID, de orden de inserción, ni de
    ninguna prioridad operacional (cajas/peso)."""
    return tuple(sorted(_firma_torre_canonica(t) for t in pallet.torres))


def _canonicalizar_ids_pallets_v5(pallets_v5: list) -> None:
    """[PATCH V6.12-D6.1 -fix de V6.12-D6, ID_ASSIGNMENT_NONDETERMINISM]
    Reasigna `ID_Pallet` de forma determinista, basada SOLO en contenido/
    geometría final -nunca en el orden de inserción ni en cuántos intentos
    internos (probes de `politica_a_descenso`, Rescue, Repair, Exact,
    Global) precedieron a la materialización final de cada CD. Debe
    llamarse en el PRIMER punto donde la solución final de TODOS los CDs
    ya está elegida (después de ensamblar `pallets_v5`) y todavía no se
    produjo ningún output público (antes de `_palletv5_a_pallet`/
    `exportar.construir_*_df`) -nunca antes, para no interferir con el
    contador interno que usan probes/DFS/LNS/Rescue/Repair/Exact/Global
    (esos siguen exactamente igual, con sus huecos cosméticos de siempre).

    Muta `pallets_v5` IN PLACE: reordena el bloque de cada CD (nunca mueve
    un pallet de un CD a otro) según la firma canónica y reescribe `.id`
    a `PV5-{cd}-001..NNN` sobre ESE orden -el mismo orden que
    `exportar.construir_plan_picking_df` recorre para numerar
    `N_Parihuela` (cuenta por posición de aparición), así que ambos
    quedan consistentes entre sí sin tocar `exportar.py`.

    [Empates] Dos pallets con firma canónica IDÉNTICA son, por
    definición, físicamente intercambiables -cualquier asignación entre
    ellos produce EXACTAMENTE las mismas filas exportadas (mismo SKU/
    cantidad/geometría en cada una), solo cambia cuál copia física recibe
    cuál número. El desempate (estable, por orden de aparición pre-sort)
    nunca depende de identidad de objeto ni de ningún valor no
    determinista.

    [Referencial] También re-sella `pallet.metadata["estabilidad"].
    pallet_id` si existe (`src/estabilidad.py`, calculado ANTES de este
    punto con el id viejo) para que no quede una referencia interna
    stale -aunque hoy ningún output lee ese campo (`exportar.
    construir_estabilidad_df` ya usa `pallet.id` directamente, no
    `est.pallet_id`)."""
    posiciones_por_cd: dict[str, list[int]] = {}
    for idx, pallet in enumerate(pallets_v5):
        posiciones_por_cd.setdefault(pallet.cd, []).append(idx)

    for cd, posiciones in posiciones_por_cd.items():
        posiciones_normales = [i for i in posiciones if not pallets_v5[i].id.startswith(_PREFIJO_BAT_DEDICADO)]
        if not posiciones_normales:
            continue
        pallets_ordenados = sorted(
            (pallets_v5[i] for i in posiciones_normales), key=_firma_pallet_canonica,
        )
        for numero, (slot, pallet) in enumerate(zip(posiciones_normales, pallets_ordenados), start=1):
            pallet.id = f"PV5-{cd}-{numero:03d}"
            estab = pallet.metadata.get("estabilidad")
            if estab is not None and hasattr(estab, "pallet_id"):
                estab.pallet_id = pallet.id
            pallets_v5[slot] = pallet


def _palletv5_a_pallet(pv5, info_sku: dict) -> Pallet:
    """Adapta un PalletV5 (torres) a un Pallet (mismo modelo que usan
    soporte.py/exportar.py/benchmark.py) para no duplicar esa
    infraestructura. `camas` queda vacío a propósito -soporte.py no rompe
    con eso (ver docstring de `clasificar_soporte_pallet`).

    Las torres con sku `bat.BAT_SKU_MARCADOR` no son un SKU real -son la
    caja física de consolidación de Cigarros/vapes- así que no aportan una
    `PalletLinea` directamente. Pero el CONTENIDO real de esa caja sí son
    SKUs reales de Cigarros (`CajaBAT.cantidades_cajas`), y tienen que
    aparecer en el picking igual que cualquier otro SKU -sin este paso, un
    pallet 100% BAT (o cualquier pallet con Cigarros) desaparecería del
    `Plan_Picking`: nadie sabría qué SKUs de Cigarros picking real
    contiene. Se agregan acá con el mismo criterio (cantidades reales
    fraccionarias, no la caja física entera)."""
    cantidades: dict[str, float] = {}
    for torre in pv5.torres:
        if torre.sku == bat.BAT_SKU_MARCADOR:
            continue
        cantidades[torre.sku] = cantidades.get(torre.sku, 0) + torre.cantidad
    for caja in pv5.cajas_bat:
        for sku, qty in caja.cantidades_cajas.items():
            cantidades[sku] = cantidades.get(sku, 0) + qty

    lineas = []
    for sku, qty in cantidades.items():
        meta = info_sku.get(sku, {})
        lineas.append(
            PalletLinea(
                sku=sku,
                descripcion=meta.get("descripcion", ""),
                categoria=meta.get("categoria", ""),
                nivel_categoria=meta.get("nivel_categoria"),
                cajas_demanda_oficial=qty,
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(meta.get("peso_no_validable", False)),
            )
        )

    pallet = Pallet(
        id=pv5.id, cd=pv5.cd, tipo="Columnar",
        altura_final=pv5.altura_final, peso_estimado=pv5.peso_estimado,
        estado=config.estado_pallet_por_altura(pv5.altura_final),
    )
    pallet.lineas = lineas
    pallet.cajas_bat = list(pv5.cajas_bat)
    pallet.es_host_bat = bool(pv5.metadata.get("es_host_bat", False)) or bool(pv5.cajas_bat)
    return pallet


_COLUMNAS_NOMBRE_CD = ["Nombre CD", "NOMBRE BK", "Nombre_CD", "Nombre CD Destino"]


def _construir_nombres_cd(envios: pd.DataFrame) -> dict[str, str]:
    """[feedback picking] "Falta nombre de CD" -si `Envios_Julio` trae una
    columna reconocible con el nombre legible del CD (ej. "CD Cañete" para
    "BK31"), se usa para la columna `Nombre_CD` del plan de picking. Si no
    existe ninguna de las variantes conocidas, devuelve vacío -no se
    inventa un nombre que no está en el dato de entrada."""
    columna = next((c for c in _COLUMNAS_NOMBRE_CD if c in envios.columns), None)
    if columna is None:
        return {}
    pares = envios[["CD", columna]].dropna().drop_duplicates(subset="CD")
    return dict(zip(pares["CD"], pares[columna]))


def _demanda_excluida_geometria(envios: pd.DataFrame, maestro: pd.DataFrame, log_df: pd.DataFrame) -> pd.DataFrame:
    """[bug real, corregido acá] La regla V4 de validacion.py (dimensión de
    caja imposible para el pallet, en ninguna orientación) excluye la fila
    de la demanda ANTES de que llegue a reconciliacion_geometrica -por
    diseño, ver test_dimension_imposible_se_excluye: esa demanda nunca debe
    competir por espacio en el motor de armado. Pero antes se perdía del
    todo salvo por una línea en `Log_Validacion` -es tan "no colocada" como
    la que rechaza `armar_pallets_bloques`, así que se reconstruye acá
    (CD/SKU/Descripcion/Categoria/Cajas_No_Colocadas) para sumarla a
    `cajas_no_colocadas_df` en vez de perderla."""
    excluidas = log_df[log_df["regla"] == "V4"][["cd", "sku"]].drop_duplicates()
    columnas = ["CD", "SKU", "Descripcion", "Categoria", "Cajas_No_Colocadas", "Unidades_No_Colocadas"]
    if excluidas.empty:
        return pd.DataFrame(columns=columnas)

    envios = envios.copy()
    envios["SKU"] = envios["SKU"].astype(str).str.strip()
    demanda = envios.groupby(["CD", "SKU"], as_index=False).agg(
        {"Descripción": "first", "Cajas Teóricas": "sum"}
    )

    maestro = maestro.copy()
    maestro["SKU"] = maestro["SKU"].astype(str).str.strip()
    categorias = maestro[["SKU", "Categoría", "Unidades por caja"]].drop_duplicates(subset="SKU")

    demanda = demanda.merge(categorias, on="SKU", how="left")
    demanda = demanda.merge(excluidas.rename(columns={"cd": "CD", "sku": "SKU"}), on=["CD", "SKU"], how="inner")
    demanda["Unidades_No_Colocadas"] = demanda["Cajas Teóricas"] * demanda["Unidades por caja"]
    return demanda.rename(
        columns={"Descripción": "Descripcion", "Categoría": "Categoria", "Cajas Teóricas": "Cajas_No_Colocadas"}
    )[columnas]


# [paralelismo por CD -pedido explícito del usuario: "como podemos hacer
# para que no demore tanto", después de confirmar que paralelizar el LNS
# por semilla ya daba ~2.7x sin perder calidad] Cada CD es independiente
# -ni comparte demanda, ni pallets, ni el contador de IDs (que ya viene
# prefijado por CD, `PV5-{cd}-NNN` -confirmado con grep que ningún otro
# lugar del código asume que el contador es global entre CDs). Con esto,
# en vez de procesar los N CDs uno detrás del otro, se procesan hasta
# `PIPELINE_MAX_PROCESOS_CD` a la vez.
PIPELINE_MAX_PROCESOS_CD = os.cpu_count() or 1


def _procesar_cd(
    cd: str, grupo: pd.DataFrame, pallets_objetivo: int | None, paralelo_lns: bool,
) -> list[PalletV5]:
    """[worker de nivel de módulo -necesario para que `ProcessPoolExecutor`
    pueda picklearlo] Todo el trabajo de UN CD: arma los pallets (con un
    contador LOCAL, no el global de siempre -ver comentario arriba de por
    qué es seguro) y calcula estabilidad. Cigarros/vapes ya no llegan acá
    -se separaron antes de armar, ver bat.separar_bat. `paralelo_lns=False`
    cuando se llama desde acá -si cada uno de los N CDs en paralelo ADEMÁS
    abriera su propio pool de 5 procesos para el LNS, se terminaría con
    N×5 procesos peleando por los mismos núcleos reales (satura en vez de
    acelerar)."""
    pallets_cd = armar_pallets_bloques(
        grupo, cd, contador=[0], pallets_objetivo=pallets_objetivo, paralelo_lns=paralelo_lns,
    )
    for p in pallets_cd:
        p.metadata["estabilidad"] = estabilidad.calcular_estabilidad(p)
    return pallets_cd


def ejecutar_core_sku_bloque(
    envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame,
    pallets_objetivo_por_cd: dict[str, int] | None = None,
) -> ResultadoPipeline:
    nombres_cd = _construir_nombres_cd(envios)
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_demanda = demanda.normalizar_demanda(df_validado)
    df_geo, auditoria_geometrica_df = reconciliacion_geometrica.reconciliar(df_demanda)
    df_derivado = derivados.calcular_derivados(df_geo)
    info_sku = _construir_info_sku(df_derivado)

    df_no_bat, df_bat = bat.separar_bat(df_derivado)
    df_clasificado = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    ].copy()
    df_no_clasificado = df_no_bat[df_no_bat["Categoria_Normalizada"].isna()].copy()
    df_geometria_insuficiente = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & df_no_bat["Requiere_Revision_Geometria"]
    ].copy()

    df_clasificado = df_clasificado.copy()
    df_clasificado["Cajas_Remanente"] = df_clasificado["Cajas_Teoricas_Redondeadas"].astype(int)

    # [regla explícita del usuario] Cigarros/vapes NUNCA entran al cubicaje:
    # no compiten por espacio con el resto de la demanda, no ocupan pallet
    # propio -se arma solo la demanda no-BAT. `cajas_bat_por_cd` (cuántas
    # cajas físicas de consolidación hacen falta por CD) queda solo para la
    # hoja de reporte "Cigarros" (ver exportar.construir_demanda_cigarros_df).
    cajas_bat_por_cd = bat.consolidar_bat_por_cd(df_bat)
    df_armado = df_clasificado

    pallets_v5: list = []
    pallets_objetivo_por_cd = pallets_objetivo_por_cd or {}
    grupos_cd = list(df_armado.groupby("CD"))

    if len(grupos_cd) > 1:
        # [paralelo por CD, ver _procesar_cd/PIPELINE_MAX_PROCESOS_CD
        # arriba] paralelo_lns=False en cada worker -ya estamos
        # paralelizando en este nivel, no anidar otro pool de procesos.
        #
        # [PATCH V6.11-R4, ensamblado determinista] `as_completed()` sigue
        # gobernando CUÁNDO se recoge cada resultado (el paralelismo real
        # no cambia), pero YA NO decide en qué ORDEN queda cada bloque de
        # CD en `pallets_v5` -antes se hacía `pallets_v5.extend(...)`
        # directo dentro del loop de `as_completed`, así que el orden de
        # los bloques de CD en el output final dependía de qué proceso
        # terminaba primero (confirmado: mismo contenido canonicalizado,
        # pero filas en distinto orden entre corridas -ver CIERRE
        # V6.11-R1/R3, `test_determinismo`). Ahora cada resultado se
        # guarda en `resultados_por_cd` apenas termina, y recién DESPUÉS
        # se ensambla siguiendo el orden de `grupos_cd` (el mismo orden,
        # determinista, que ya usa el camino de 1 solo CD más abajo -
        # `groupby("CD")` de pandas ordena las claves, no depende de qué
        # tan rápido corra cada proceso). Esto NO reordena las filas
        # DENTRO de cada CD -esas ya las decide el propio solver
        # (determinista desde V6.11-R3), acá solo se fija el orden de los
        # BLOQUES completos.
        n_procesos = min(PIPELINE_MAX_PROCESOS_CD, len(grupos_cd))
        contexto = multiprocessing.get_context("fork") if hasattr(os, "fork") else None
        resultados_por_cd: dict[str, list[PalletV5]] = {}
        with ProcessPoolExecutor(max_workers=n_procesos, mp_context=contexto) as executor:
            futuro_a_cd = {
                executor.submit(_procesar_cd, cd, grupo, pallets_objetivo_por_cd.get(cd), False): cd
                for cd, grupo in grupos_cd
            }
            for futuro in as_completed(futuro_a_cd):
                resultados_por_cd[futuro_a_cd[futuro]] = futuro.result()
        for cd, _grupo in grupos_cd:
            pallets_v5.extend(resultados_por_cd[cd])
    else:
        # [1 solo CD -sin paralelismo por CD, pero SÍ el del LNS interno
        # (paralelo_lns=True) si ese único CD lo necesita.]
        for cd, grupo in grupos_cd:
            pallets_v5.extend(_procesar_cd(cd, grupo, pallets_objetivo_por_cd.get(cd), True))

    # [PATCH V6.12-D6.1] Primer punto donde la solución final de TODOS los
    # CDs ya está elegida y todavía no se produjo ningún output público
    # -ver `_canonicalizar_ids_pallets_v5`.
    _canonicalizar_ids_pallets_v5(pallets_v5)

    pallets_apilado = [_palletv5_a_pallet(p, info_sku) for p in pallets_v5]
    for pallet in pallets_apilado:
        soporte.clasificar_soporte_pallet(pallet)

    pallets_sin_clasificar = _construir_pallets_sin_clasificar(df_no_clasificado)
    pallets_geometria_insuficiente = _construir_pallets_geometria_insuficiente(df_geometria_insuficiente)
    todos_pallets = pallets_apilado + pallets_sin_clasificar + pallets_geometria_insuficiente

    validacion_peso.validar_pesos(todos_pallets, info_sku)

    geometria_inferida_count = int(
        auditoria_geometrica_df["Fuente_Geometria"].isin(("INFERIDA_MAESTRO", "MAESTRO_IMPOSIBLE_DEGRADADO")).sum()
    )
    demanda_unidades_error = float(df_demanda["Unidades_Exceso_Redondeo"].sum())
    bench_resultado = benchmark.calcular_kpis(
        pallets_apilado,
        demanda_unidades_error=demanda_unidades_error,
        geometria_inferida_count=geometria_inferida_count,
    )
    bench_df = benchmark.benchmark_df([bench_resultado])

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets, info_sku, nombres_cd)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)
    demanda_excluida_geometria_df = _demanda_excluida_geometria(envios, maestro, log_df)
    cajas_no_colocadas_df = exportar.construir_cajas_no_colocadas_df(
        pallets_v5, info_sku, demanda_excluida_geometria_df
    )
    demanda_cigarros_df = exportar.construir_demanda_cigarros_df(df_bat, cajas_bat_por_cd, nombres_cd)

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=log_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=info_sku,
        auditoria_geometrica_df=auditoria_geometrica_df,
        benchmark_df=bench_df,
        pallets_v5=pallets_v5,
        cajas_no_colocadas_df=cajas_no_colocadas_df,
        demanda_cigarros_df=demanda_cigarros_df,
    )
