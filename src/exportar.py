import io

import pandas as pd

from models import Pallet, PalletV5, ResultadoPipeline


def construir_plan_picking_df(
    pallets: list[Pallet], info_sku: dict[str, dict] | None = None, nombres_cd: dict[str, str] | None = None
) -> pd.DataFrame:
    """[V3 / sección 20] Agrega columnas de geometría (Fuente_Geometria,
    *_Efectivo, Geometria_Inferida) y de BAT/soporte a nivel de pallet
    (Altura_Pre_BAT, Cajas_BAT, Unidades_BAT, Support_Ratio_Min,
    Delta_Target_198_3) sobre el output de V2. `info_sku` es opcional para no
    romper llamadas viejas -sin él, las columnas de geometría quedan vacías.

    [feedback picking] `nombres_cd` (CD -> nombre legible, ej. "BK31" ->
    "CD Cañete") es opcional -si el Excel de entrada no trae esa columna en
    `Envios_Julio`, `Nombre_CD` queda vacío en vez de inventar un nombre."""
    info_sku = info_sku or {}
    nombres_cd = nombres_cd or {}

    # [feedback picking] "Falta el detalle de número de parihuelas" -numera
    # los pallets 1, 2, 3... POR CD, en el orden en que aparecen (no el ID
    # técnico PV5-BK31-001, que mezcla el motor de armado con el número).
    numero_parihuela: dict[tuple, int] = {}
    contador_por_cd: dict[str, int] = {}
    for pallet in pallets:
        clave = (pallet.cd, pallet.id)
        if clave in numero_parihuela:
            continue
        contador_por_cd[pallet.cd] = contador_por_cd.get(pallet.cd, 0) + 1
        numero_parihuela[clave] = contador_por_cd[pallet.cd]

    filas = []
    for pallet in pallets:
        cajas_bat = sum(1 for c in pallet.cajas_bat) if pallet.cajas_bat else 0
        unidades_bat = sum(c.unidades for c in pallet.cajas_bat) if pallet.cajas_bat else 0
        for linea in pallet.lineas:
            meta = info_sku.get(linea.sku, {})
            cajas_totales = linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            unidades_por_caja = meta.get("unidades_por_caja") or 0
            filas.append(
                {
                    "CD": pallet.cd,
                    "Nombre_CD": nombres_cd.get(pallet.cd),
                    "N_Parihuela": numero_parihuela[(pallet.cd, pallet.id)],
                    "ID_Pallet": pallet.id,
                    "Tipo_Pallet": pallet.tipo,
                    "Nivel_Categoria": linea.nivel_categoria,
                    "SKU": linea.sku,
                    "Descripcion": linea.descripcion,
                    "Categoria": linea.categoria,
                    "Cajas_Demanda_Oficial": linea.cajas_demanda_oficial,
                    "Cajas_Extra_Consolidacion": linea.cajas_extra_consolidacion,
                    "Cajas_Totales_Pallet": cajas_totales,
                    "Unidades_Por_Caja": unidades_por_caja or None,
                    "Cajas_Por_PH": meta.get("cajas_por_ph"),
                    "Cantidad_Unidades": round(cajas_totales * unidades_por_caja, 2) if unidades_por_caja else None,
                    "Fuente_Geometria": meta.get("fuente_geometria"),
                    "Largo_Efectivo": meta.get("largo_efectivo"),
                    "Ancho_Efectivo": meta.get("ancho_efectivo"),
                    "Alto_Efectivo": meta.get("alto_efectivo"),
                    "Geometria_Inferida": meta.get("geometria_inferida", False),
                    "Altura_Final_Pallet_cm": round(pallet.altura_final, 2),
                    "Altura_Pre_BAT_cm": round(pallet.altura_pre_bat, 2) if pallet.altura_pre_bat is not None else None,
                    "Cajas_BAT": cajas_bat,
                    "Unidades_BAT": unidades_bat,
                    "Peso_Estimado_Pallet_kg": round(pallet.peso_estimado, 2),
                    "Support_Ratio_Min": round(pallet.support_ratio_min, 3) if pallet.support_ratio_min is not None else None,
                    "Delta_Target_198_3": pallet.altura_target_delta,
                    "Estado": pallet.estado,
                }
            )
    columnas = [
        "CD", "Nombre_CD", "N_Parihuela", "ID_Pallet", "Tipo_Pallet", "Nivel_Categoria", "SKU", "Descripcion",
        "Categoria", "Cajas_Demanda_Oficial", "Cajas_Extra_Consolidacion", "Cajas_Totales_Pallet",
        "Unidades_Por_Caja", "Cajas_Por_PH", "Cantidad_Unidades",
        "Fuente_Geometria", "Largo_Efectivo", "Ancho_Efectivo", "Alto_Efectivo", "Geometria_Inferida",
        "Altura_Final_Pallet_cm", "Altura_Pre_BAT_cm", "Cajas_BAT", "Unidades_BAT",
        "Peso_Estimado_Pallet_kg", "Support_Ratio_Min", "Delta_Target_198_3", "Estado",
    ]
    return pd.DataFrame(filas, columns=columnas)


def construir_resumen_cd_df(pallets: list[Pallet]) -> pd.DataFrame:
    filas = []
    for cd in sorted({p.cd for p in pallets}):
        pallets_cd = [p for p in pallets if p.cd == cd]
        homogeneos = [p for p in pallets_cd if p.tipo.startswith("Homogéneo")]
        mixtos = [p for p in pallets_cd if p.tipo == "Mixto"]
        cajas_totales = sum(
            linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            for p in pallets_cd
            for linea in p.lineas
        )
        cajas_extra = sum(linea.cajas_extra_consolidacion for p in pallets_cd for linea in p.lineas)
        peso_total = sum(p.peso_estimado for p in pallets_cd)
        alertas_peso = sum(1 for p in pallets_cd if "ALERTA DE PESO" in p.estado)
        hosts_bat = sum(1 for p in pallets_cd if p.es_host_bat)

        filas.append(
            {
                "CD": cd,
                "N_Pallets": len(pallets_cd),
                "N_Pallets_Homogeneos": len(homogeneos),
                "N_Pallets_Mixtos": len(mixtos),
                "N_Hosts_BAT": hosts_bat,
                "Cajas_Totales_Despachadas": cajas_totales,
                "Cajas_Extra_Consolidacion": cajas_extra,
                "Peso_Total_kg": round(peso_total, 2),
                "N_Alertas_Peso": alertas_peso,
            }
        )
    return pd.DataFrame(filas)


def construir_torres_df(pallets_v5: list[PalletV5]) -> pd.DataFrame:
    """[V5-P13] Una fila por torre -detalle que `Plan_Picking` no tiene
    (posición XY, orientación, semilla/estrategia ganadora de multi-start).
    Las torres BAT (`sku == "__BAT__"`) se incluyen igual, marcadas como tal
    -son una posición física real dentro del pallet."""
    filas = []
    for pallet in pallets_v5:
        estrategia = pallet.metadata.get("estrategia")
        seed = pallet.metadata.get("seed")
        for torre in pallet.torres:
            filas.append(
                {
                    "CD": pallet.cd,
                    "ID_Pallet": pallet.id,
                    "SKU": "BAT" if torre.sku == "__BAT__" else torre.sku,
                    "X": torre.x,
                    "Y": torre.y,
                    "Z": torre.z,
                    "Largo": torre.largo,
                    "Ancho": torre.ancho,
                    "Alto_Caja": torre.alto_caja,
                    "Cantidad": torre.cantidad,
                    "Altura_Torre": round(torre.altura, 2),
                    "Orientacion": torre.orientacion,
                    "Fuente_Geometria": torre.fuente_geometria,
                    "Peso_kg": round(torre.peso, 2),
                    "Estrategia_Ganadora": estrategia,
                    "Seed_Ganadora": seed,
                }
            )
    columnas = [
        "CD", "ID_Pallet", "SKU", "X", "Y", "Z", "Largo", "Ancho", "Alto_Caja", "Cantidad",
        "Altura_Torre", "Orientacion", "Fuente_Geometria", "Peso_kg", "Estrategia_Ganadora", "Seed_Ganadora",
    ]
    return pd.DataFrame(filas, columns=columnas)


def construir_pallets_3d_data_df(pallets_v5: list[PalletV5]) -> pd.DataFrame:
    """[V5-P13] Una fila por caja física (x, y, z reales dentro del pallet)
    -el detalle que respalda la vista 3D de `visualizacion.dibujar_pallet_v5_3d`.
    Criterio del plan: "toda posición exportada debe poder verse"."""
    filas = []
    for pallet in pallets_v5:
        for torre in pallet.torres:
            sku = "BAT" if torre.sku == "__BAT__" else torre.sku
            for placement in torre.placements:
                filas.append(
                    {
                        "CD": pallet.cd,
                        "ID_Pallet": pallet.id,
                        "SKU": sku,
                        "X": placement.x,
                        "Y": placement.y,
                        "Z": placement.z,
                        "Largo": placement.largo,
                        "Ancho": placement.ancho,
                        "Alto": placement.alto,
                        "Orientacion": placement.orientacion,
                        "Indice_En_Torre": placement.indice,
                        "Fuente_Geometria": torre.fuente_geometria,
                    }
                )
    columnas = [
        "CD", "ID_Pallet", "SKU", "X", "Y", "Z", "Largo", "Ancho", "Alto",
        "Orientacion", "Indice_En_Torre", "Fuente_Geometria",
    ]
    return pd.DataFrame(filas, columns=columnas)


def construir_estabilidad_df(pallets_v5: list[PalletV5]) -> pd.DataFrame:
    """[V5-P13] Exporta lo que P11 calculaba pero todavía no exportaba
    (informativo, nunca bloquea -ver src/estabilidad.py)."""
    filas = []
    for pallet in pallets_v5:
        est = pallet.metadata.get("estabilidad")
        if est is None:
            continue
        filas.append(
            {
                "CD": pallet.cd,
                "ID_Pallet": pallet.id,
                "Centro_Masa_X": est.centro_masa_x,
                "Centro_Masa_Y": est.centro_masa_y,
                "Desviacion_Centro_Masa_cm": est.desviacion_centro_masa,
                "Fraccion_Peso_Superior": est.fraccion_peso_superior,
                "Torres_Esbeltas": ", ".join(est.torres_esbeltas),
                "Estados": ", ".join(est.estados),
                "OK": est.ok,
            }
        )
    columnas = [
        "CD", "ID_Pallet", "Centro_Masa_X", "Centro_Masa_Y", "Desviacion_Centro_Masa_cm",
        "Fraccion_Peso_Superior", "Torres_Esbeltas", "Estados", "OK",
    ]
    return pd.DataFrame(filas, columns=columnas)


def exportar_workbook(resultado: ResultadoPipeline, ruta_o_buffer=None):
    destino = ruta_o_buffer if ruta_o_buffer is not None else io.BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        resultado.plan_picking_df.to_excel(writer, sheet_name="Plan_Picking", index=False)
        resultado.log_validacion_df.to_excel(writer, sheet_name="Log_Validacion", index=False)
        resultado.resumen_cd_df.to_excel(writer, sheet_name="Resumen_por_CD", index=False)
        # [V3 / sección 20] Hoja de auditoría geométrica y hoja benchmark.
        if resultado.auditoria_geometrica_df is not None:
            resultado.auditoria_geometrica_df.to_excel(writer, sheet_name="Auditoria_Geometrica", index=False)
        if resultado.benchmark_df is not None:
            resultado.benchmark_df.to_excel(writer, sheet_name="Benchmark", index=False)
        # [V5-P13] Hojas propias del core columnar -solo existen cuando el
        # pipeline corrió con PACKER_VERSION="V5" (`pallets_v5` viene None
        # en V4, ver models.ResultadoPipeline).
        if resultado.pallets_v5:
            construir_torres_df(resultado.pallets_v5).to_excel(writer, sheet_name="Torres", index=False)
            construir_pallets_3d_data_df(resultado.pallets_v5).to_excel(writer, sheet_name="Pallets_3D_Data", index=False)
            construir_estabilidad_df(resultado.pallets_v5).to_excel(writer, sheet_name="Estabilidad_V5", index=False)
    if ruta_o_buffer is None:
        destino.seek(0)
    return destino
