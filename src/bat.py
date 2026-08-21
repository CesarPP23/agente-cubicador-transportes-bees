"""BAT: Cigarros y vapes.

Nunca se despachan por caja completa (96% de sus líneas de demanda son
fraccionarias). El personal los consolida en una caja física FIJA
(52.5x34x49cm, hasta 1000 unidades, ver config.CAJA_BAT_*) separada del
cubicaje normal. Se agrega como una fila de demanda más (pseudo-SKU
`BAT_SKU_MARCADOR`) al mismo armado que el resto de los SKUs -ver sección
"BAT integrado" más abajo- en vez de una pasada aparte después.
"""
import math

import pandas as pd

import config
from models import CajaBAT, PalletV5
from src.reconciliacion_geometrica import capacidad_xy_max


def separar_bat(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """[sección 9.1] Separa demanda BAT del resto usando la categoría
    logística normalizada explícita (config.CATEGORIAS_BAT), no un valor
    numérico genérico compartido con otros productos. Devuelve
    (demanda_no_bat, demanda_bat)."""
    es_bat = df["Categoria_Normalizada"].isin(config.CATEGORIAS_BAT)
    return df[~es_bat].copy(), df[es_bat].copy()


def consolidar_bat_por_cd(df_bat: pd.DataFrame) -> dict[str, list[CajaBAT]]:
    """[sección 9.2] Arma cajas BAT de tamaño fijo (hasta
    CAJA_BAT_CAPACIDAD_UNIDADES) por CD, usando la demanda REAL en unidades
    -no `Cajas_Teoricas_Redondeadas`, que infla ~3.8x al redondear cada línea
    fraccionaria hacia arriba. Nunca mezcla CDs (invariante 13 de la sección
    lógica)."""
    cajas_por_cd: dict[str, list[CajaBAT]] = {}
    if df_bat.empty:
        return cajas_por_cd

    col_unidades = "Demanda_Unidades_Oficial" if "Demanda_Unidades_Oficial" in df_bat.columns else "Unidades"
    col_uxc = "Unidades_por_Caja" if "Unidades_por_Caja" in df_bat.columns else "Unidades por caja"

    for cd, grupo in df_bat.groupby("CD"):
        pendientes = {r["SKU"]: r[col_unidades] for _, r in grupo.iterrows() if r[col_unidades] > 0}
        unidades_por_caja = {r["SKU"]: r[col_uxc] for _, r in grupo.iterrows()}
        total_unidades = sum(pendientes.values())
        if total_unidades <= 0:
            continue

        n_cajas = math.ceil(total_unidades / config.CAJA_BAT_CAPACIDAD_UNIDADES)
        cajas: list[CajaBAT] = []
        for i in range(n_cajas):
            cupo = config.CAJA_BAT_CAPACIDAD_UNIDADES
            cantidades_cajas: dict[str, float] = {}
            unidades_en_esta_caja = 0.0
            for sku in list(pendientes):
                if cupo <= 0:
                    break
                tomar = min(pendientes[sku], cupo)
                if tomar <= 0:
                    continue
                cantidades_cajas[sku] = tomar / unidades_por_caja[sku]
                pendientes[sku] -= tomar
                cupo -= tomar
                unidades_en_esta_caja += tomar
            cajas.append(
                CajaBAT(
                    cd=cd,
                    id_bat=f"BAT-{cd}-{i + 1:03d}",
                    unidades=int(unidades_en_esta_caja),
                    cantidades_cajas=cantidades_cajas,
                )
            )
        cajas_por_cd[cd] = cajas

    return cajas_por_cd


def _peso_caja_bat(caja: CajaBAT, info_sku: dict) -> float:
    return sum(qty * (info_sku[sku].get("peso_caja") or 0.0) for sku, qty in caja.cantidades_cajas.items())


# ============================================================================
# BAT integrado: entra como una fila de demanda más, dentro del MISMO armado
# que el resto de los SKUs -no una pasada aparte después. Una versión previa
# corría BAT después de que el resto de los pallets ya estaban cerrados, sin
# saber que iba a hacer falta lugar para BAT (dejaba cada vez menos aire
# disponible a medida que el packing se ajustaba más). Integrarlo desde el
# principio dio bat_dedicados=0 en el dataset real, cero violaciones
# geométricas, demanda exacta -ver PATCH_LOG.md.
#
# BAT se agrega como fila de demanda ANTES de armar (`construir_filas_bat_
# pseudo_sku`), tratada como una SKU más por `armar_pallets_columnar`/
# `generar_torres_candidatas` (rota ambas orientaciones automáticamente).
#
# Las cajas BAT reales (`CajaBAT`) son fungibles entre sí para efectos de
# COLOCACIÓN (mismo footprint fijo) -el packer las trata como
# `Cajas_Remanente` de una sola "SKU" `BAT_SKU_MARCADOR`. Después de armar,
# `asignar_cajas_bat_a_torres` mapea esa cantidad colocada de vuelta a
# objetos `CajaBAT` reales concretos (orden estable, sin que importe cuál
# caja específica terminó en qué torre -son intercambiables).
# ============================================================================

BAT_SKU_MARCADOR = "__BAT__"


def construir_filas_bat_pseudo_sku(cajas_bat_por_cd: dict[str, list[CajaBAT]], info_sku: dict) -> pd.DataFrame:
    """[V5-BAT-integrado] Una fila por CD con demanda BAT, con las mismas
    columnas que `armar_pallets_bloques`/`generar_torres_candidatas` esperan de cualquier
    SKU real (Largo/Ancho/Alto_Efectivo, Peso_Caja, Cajas_Remanente,
    Cajas_Cama_Efectivo) -para que BAT compita por espacio en el MISMO
    `df_cd` que el resto de la demanda del CD, en vez de una pasada aparte."""
    filas = []
    for cd, cajas in cajas_bat_por_cd.items():
        if not cajas:
            continue
        peso_total = sum(_peso_caja_bat(c, info_sku) for c in cajas)
        peso_unitario = peso_total / len(cajas)
        capacidad_cama, _orientacion = capacidad_xy_max(config.CAJA_BAT_LARGO, config.CAJA_BAT_ANCHO)
        filas.append(
            {
                "CD": cd,
                "SKU": BAT_SKU_MARCADOR,
                "Cajas_Remanente": len(cajas),
                "Largo_Efectivo": config.CAJA_BAT_LARGO,
                "Ancho_Efectivo": config.CAJA_BAT_ANCHO,
                "Alto_Efectivo": config.CAJA_BAT_ALTO,
                "Peso_Caja": peso_unitario,
                "Fuente_Geometria": "BAT",
                "Cajas_Cama_Efectivo": capacidad_cama,
            }
        )
    return pd.DataFrame(filas)


def renombrar_pallets_bat_puros(pallets_cd: list[PalletV5], cd: str) -> None:
    """[V5-BAT-integrado] Un pallet cuyas torres son TODAS BAT (ninguna otra
    SKU) es, en la práctica, un pallet dedicado -se renombra al esquema
    `PV5-BAT-{cd}-NNN` que ya usan `benchmark.py`/`exportar.py` para
    reconocerlos, aunque haya salido del MISMO packer genérico que todo lo
    demás. Muta `pallet.id` in place -determinístico: recorre `pallets_cd`
    en su orden ya estable."""
    n = 0
    for pallet in pallets_cd:
        if pallet.torres and all(t.sku == BAT_SKU_MARCADOR for t in pallet.torres):
            n += 1
            pallet.id = f"PV5-BAT-{cd}-{n:03d}"


def asignar_cajas_bat_a_torres(pallets_cd: list[PalletV5], cajas_bat: list[CajaBAT]) -> None:
    """[V5-BAT-integrado] Después de que `armar_pallets_columnar` ya colocó
    torres con sku `BAT_SKU_MARCADOR` (tratadas como demanda genérica, sin
    saber de `CajaBAT` reales), mapea esa cantidad de vuelta a objetos
    `CajaBAT` concretos -son fungibles entre sí (mismo footprint fijo), así
    que el mapeo es por orden estable, no por identidad. Llamar DESPUÉS de
    `renombrar_pallets_bat_puros` -así `caja.pallet_host_id` queda con el id
    final, no uno que después se renombra."""
    disponibles = list(cajas_bat)
    idx = 0
    for pallet in pallets_cd:
        for torre in pallet.torres:
            if torre.sku != BAT_SKU_MARCADOR:
                continue
            asignadas = disponibles[idx : idx + torre.cantidad]
            idx += torre.cantidad
            for caja in asignadas:
                caja.pallet_host_id = pallet.id
            pallet.cajas_bat.extend(asignadas)
            pallet.metadata["es_host_bat"] = True
