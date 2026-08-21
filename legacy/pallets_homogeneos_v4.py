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
        # [V4c] "Alto_Efectivo" (reconciliado, puede venir acostado para
        # Comestibles/Cigarros -ver reconciliacion_geometrica.py), NO la
        # columna cruda "Alto de caja": un PH homogéneo de un SKU acostado
        # calculado con el alto de pie daría una altura de pallet incorrecta.
        alto_caja = fila["Alto_Efectivo"] if pd.notna(fila["Alto_Efectivo"]) else 0
        # [V3 / sección 10] Misma fórmula que apilado_3d.calcular_altura_pallet
        # (Altura_Pallet_Vacio + suma de alturas de cama) -acá se calcula antes
        # de construir los objetos Cama/Pallet porque decide si el PH se arma
        # o no, pero es la MISMA fórmula, nunca "camas * alto_caja" a secas.
        altura_final = config.ALTURA_PALLET_VACIO + n_camas * alto_caja

        # [PARCHE P9] `Camas por PH` x `Alto de caja` puede dar un pallet fuera de
        # norma y nadie lo verificaba: el Paso 4 controla la altura de lo que se
        # AGREGA encima, pero nunca la altura BASE del pallet homogéneo. Si el dato
        # del Maestro produce un pallet imposible, no se arma el PH y toda la
        # demanda de ese SKU pasa al remanente, donde el packing 2D/3D la resuelve
        # con geometría real.
        if altura_final > config.ALTURA_MAX_OBSERVADA:
            continue

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
