import io

import pandas as pd

from models import Pallet, ResultadoPipeline


def construir_plan_picking_df(pallets: list[Pallet]) -> pd.DataFrame:
    filas = []
    for pallet in pallets:
        for linea in pallet.lineas:
            filas.append(
                {
                    "CD": pallet.cd,
                    "ID_Pallet": pallet.id,
                    "Tipo_Pallet": pallet.tipo,
                    "Nivel_Categoria": linea.nivel_categoria,
                    "SKU": linea.sku,
                    "Descripcion": linea.descripcion,
                    "Categoria": linea.categoria,
                    "Cajas_Demanda_Oficial": linea.cajas_demanda_oficial,
                    "Cajas_Extra_Consolidacion": linea.cajas_extra_consolidacion,
                    "Cajas_Totales_Pallet": linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion,
                    "Altura_Final_Pallet_cm": round(pallet.altura_final, 2),
                    "Peso_Estimado_Pallet_kg": round(pallet.peso_estimado, 2),
                    "Estado": pallet.estado,
                }
            )
    columnas = [
        "CD", "ID_Pallet", "Tipo_Pallet", "Nivel_Categoria", "SKU", "Descripcion", "Categoria",
        "Cajas_Demanda_Oficial", "Cajas_Extra_Consolidacion", "Cajas_Totales_Pallet",
        "Altura_Final_Pallet_cm", "Peso_Estimado_Pallet_kg", "Estado",
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

        filas.append(
            {
                "CD": cd,
                "N_Pallets": len(pallets_cd),
                "N_Pallets_Homogeneos": len(homogeneos),
                "N_Pallets_Mixtos": len(mixtos),
                "Cajas_Totales_Despachadas": cajas_totales,
                "Cajas_Extra_Consolidacion": cajas_extra,
                "Peso_Total_kg": round(peso_total, 2),
                "N_Alertas_Peso": alertas_peso,
            }
        )
    return pd.DataFrame(filas)


def exportar_workbook(resultado: ResultadoPipeline, ruta_o_buffer=None):
    destino = ruta_o_buffer if ruta_o_buffer is not None else io.BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        resultado.plan_picking_df.to_excel(writer, sheet_name="Plan_Picking", index=False)
        resultado.log_validacion_df.to_excel(writer, sheet_name="Log_Validacion", index=False)
        resultado.resumen_cd_df.to_excel(writer, sheet_name="Resumen_por_CD", index=False)
    if ruta_o_buffer is None:
        destino.seek(0)
    return destino
