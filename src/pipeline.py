import pandas as pd

import config
from models import Pallet, PalletLinea, ResultadoPipeline
from src import validacion


def _construir_info_sku(df: pd.DataFrame) -> dict[str, dict]:
    info: dict[str, dict] = {}
    for _, fila in df.drop_duplicates(subset="SKU").iterrows():
        categoria = fila["Categoria_Normalizada"] if pd.notna(fila["Categoria_Normalizada"]) else fila["Categoría"]
        info[fila["SKU"]] = {
            "descripcion": fila["Descripción"],
            "categoria": categoria,
            "nivel_categoria": fila["Nivel_Categoria"],
            "peso_no_validable": bool(fila["Peso_No_Validable"]),
            "peso_caja": fila["Peso_Caja"] if pd.notna(fila["Peso_Caja"]) else 0.0,
            # [V3 / sección 20] Trazabilidad de geometría, para la hoja de
            # auditoría y las columnas Fuente_Geometria/*_Efectivo del output.
            "fuente_geometria": fila.get("Fuente_Geometria"),
            "largo_efectivo": fila.get("Largo_Efectivo"),
            "ancho_efectivo": fila.get("Ancho_Efectivo"),
            "alto_efectivo": fila.get("Alto_Efectivo"),
            "geometria_inferida": bool(fila.get("Geometria_Inferida", False)),
            "unidades_por_caja": fila.get("Unidades_por_Caja", fila.get("Unidades por caja")),
        }
    return info


def _construir_pallets_sin_clasificar(df_no_clasificado: pd.DataFrame) -> list[Pallet]:
    pallets = []
    for cd, grupo in df_no_clasificado.groupby("CD"):
        lineas = [
            PalletLinea(
                sku=fila["SKU"],
                descripcion=fila["Descripción"],
                categoria=fila["Categoría"],
                nivel_categoria=None,
                cajas_demanda_oficial=int(fila["Cajas_Teoricas_Redondeadas"]),
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(fila["Peso_No_Validable"]),
            )
            for _, fila in grupo.iterrows()
        ]
        pallet = Pallet(
            id=f"SIN-ASIGNAR-{cd}",
            cd=cd,
            tipo="Requiere Revisión",
            estado=config.ESTADO_CATEGORIA_NO_CLASIFICADA,
        )
        pallet.lineas = lineas
        pallets.append(pallet)
    return pallets


def _construir_pallets_geometria_insuficiente(df_insuficiente: pd.DataFrame) -> list[Pallet]:
    """[V3 / sección 5.3.D, 17] SKUs sin geometría utilizable (sin Alto de
    caja, o sin Largo/Ancho y sin techo del Maestro para inferir): no se
    pueden empacar de forma segura, quedan como REQUIERE REVISIÓN en vez de
    forzar una geometría inventada (invariante 17: "todo pallet inviable
    queda como REQUIERE REVISIÓN")."""
    pallets = []
    for cd, grupo in df_insuficiente.groupby("CD"):
        lineas = [
            PalletLinea(
                sku=fila["SKU"],
                descripcion=fila["Descripción"],
                categoria=fila["Categoria_Normalizada"],
                nivel_categoria=fila["Nivel_Categoria"],
                cajas_demanda_oficial=int(fila["Cajas_Teoricas_Redondeadas"]),
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(fila["Peso_No_Validable"]),
            )
            for _, fila in grupo.iterrows()
        ]
        pallet = Pallet(
            id=f"REQUIERE-REVISION-{cd}",
            cd=cd,
            tipo="Requiere Revisión",
            estado=config.ESTADO_DATO_INSUFICIENTE,
        )
        pallet.lineas = lineas
        pallets.append(pallet)
    return pallets


def ejecutar_pipeline(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    """Punto de entrada único: arma pallets con la lógica de bloques por SKU
    (ver src/packing_bloques.py -cada SKU se coloca entero en el menor
    número de pallets posible, combinando bloques enteros de otros SKUs
    para llegar a la altura objetivo, y partiendo uno solo como último
    recurso). Ver Parches/v5/PATCH_LOG.md para el historial de cómo se
    llegó a esta versión."""
    from src import pipeline_sku_bloque

    return pipeline_sku_bloque.ejecutar_core_sku_bloque(envios, maestro, uma)


def ejecutar_desde_archivo(ruta_o_buffer) -> ResultadoPipeline:
    envios, maestro, uma = validacion.cargar_hojas(ruta_o_buffer)
    return ejecutar_pipeline(envios, maestro, uma)
