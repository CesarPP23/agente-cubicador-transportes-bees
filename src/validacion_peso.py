import config
from models import Pallet


def validar_pesos(pallets: list[Pallet], info_sku: dict[str, dict]) -> None:
    for pallet in pallets:
        peso_total = 0.0
        peso_no_validable = False
        for linea in pallet.lineas:
            meta = info_sku[linea.sku]
            peso_caja = meta["peso_caja"] or 0.0
            cajas_totales = linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            peso_total += cajas_totales * peso_caja
            peso_no_validable = peso_no_validable or linea.peso_no_validable

        pallet.peso_estimado = peso_total

        estados = []
        if peso_no_validable:
            estados.append(config.ESTADO_PESO_NO_VALIDABLE)
        if peso_total > config.PESO_ALERTA_KG:
            estados.append(config.ESTADO_ALERTA_PESO)
        if pallet.estado != config.ESTADO_OK:
            estados.append(pallet.estado)

        pallet.estado = " + ".join(dict.fromkeys(estados)) if estados else config.ESTADO_OK
