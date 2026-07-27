import pandas as pd

import config
from models import Cama, Pallet, PalletLinea


def armar_pallets_homogeneos(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Pallet]]:
    df = df.copy()
    df["Cajas_Remanente"] = df["Cajas_Teoricas_Redondeadas"].astype(int)

    pallets: list[Pallet] = []
    contador: dict[str, int] = {}

    for idx, fila in df.iterrows():
        cajas_ph = fila["Cajas por PH"]
        if pd.isna(cajas_ph) or cajas_ph <= 0:
            continue

        cajas_ph = int(cajas_ph)
        pallets_completos = int(fila["Cajas_Remanente"] // cajas_ph)
        if pallets_completos < 1:
            continue

        cd = fila["CD"]
        contador[cd] = contador.get(cd, 0)

        camas_ph = fila["Camas por PH"]
        n_camas = int(camas_ph) if pd.notna(camas_ph) and camas_ph > 0 else 1
        alto_caja = fila["Alto de caja"] if pd.notna(fila["Alto de caja"]) else 0
        altura_final = config.ALTURA_PALLET_VACIO + n_camas * alto_caja
        peso_caja = fila["Peso_Caja"] if pd.notna(fila["Peso_Caja"]) else 0

        for _ in range(pallets_completos):
            contador[cd] += 1
            pallet = Pallet(
                id=f"PH-HOM-{cd}-{contador[cd]:03d}",
                cd=cd,
                tipo="Homogéneo",
                altura_final=altura_final,
                peso_estimado=cajas_ph * peso_caja,
                estado=config.ESTADO_OK,
            )
            pallet.lineas.append(
                PalletLinea(
                    sku=fila["SKU"],
                    descripcion=fila["Descripción"],
                    categoria=fila["Categoria_Normalizada"],
                    nivel_categoria=fila["Nivel_Categoria"],
                    cajas_demanda_oficial=cajas_ph,
                    cajas_extra_consolidacion=0,
                    peso_no_validable=bool(fila["Peso_No_Validable"]),
                )
            )
            pallet.camas.append(
                Cama(
                    categorias=[fila["Categoria_Normalizada"]],
                    altura_cama=n_camas * alto_caja,
                    cantidades={fila["SKU"]: cajas_ph},
                    nivel_categoria=fila["Nivel_Categoria"],
                )
            )
            pallets.append(pallet)

        df.loc[idx, "Cajas_Remanente"] -= pallets_completos * cajas_ph

    remanente = df[df["Cajas_Remanente"] > 0].copy()
    return remanente.reset_index(drop=True), pallets
