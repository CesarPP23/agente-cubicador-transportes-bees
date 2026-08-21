"""[V-AUTO-CONSOLIDADO] Post-proceso opcional sobre un resultado V5 ya
armado: para cada SKU que queda repartido en más de un pallet del MISMO CD,
intenta juntarlo en el menor número de pallets posible -mueve sus torres
hacia pallets que YA tienen ese mismo SKU (nunca abre un pallet nuevo,
nunca aumenta el total de pallets del CD; en el peor caso no cambia nada).

Motivación (caso real, ver PATCH_LOG.md): con el packing 3D + multi-start,
un SKU de alta demanda podía terminar repartido en 4 pallets distintos del
mismo CD (KR Cola Negra en SJ87: 18+5+14+23 cajas), aunque el TOTAL de
pallets ya fuera óptimo -eso es un costo operativo real para picking (más
movimientos físicos, más superficies donde puede haber un error) que el
conteo de pallets no refleja. Esto es deliberadamente conservador: solo
consolida si NO empeora nada más (no pierde demanda, no aumenta pallets,
no violan geometría) -si no se puede consolidar limpio, no se fuerza."""
import copy

import config
from models import PalletV5, Torre
from src.bat import BAT_SKU_MARCADOR
from src.packing_columnar import _PalletEnConstruccion, _area_union_xy, _reconstruir_en_construccion
from src.torres import TorreCandidate, dividir_torre


def _snapshot(pallets: list[PalletV5]) -> list[PalletV5]:
    return [copy.deepcopy(p) for p in pallets]


def _restaurar(pallets: list[PalletV5], snapshot: list[PalletV5]) -> None:
    for p, snap in zip(pallets, snapshot):
        p.torres = snap.torres
        p.altura_final = snap.altura_final
        p.peso_estimado = snap.peso_estimado
        p.ocupacion_xy = snap.ocupacion_xy
        p.volumen_utilizado = snap.volumen_utilizado


def _reinsertar_en_mismo_sku(torre: Torre, destinos: list[_PalletEnConstruccion]) -> bool:
    """Igual que `residual_search._reinsertar_torre` (best area fit +
    división recursiva en mitades si no entra completa), pero `destinos` ya
    viene filtrado a pallets que YA tienen este SKU -el objetivo es
    concentrar el SKU, no optimizar espacio en general (para eso está
    `residual_search.eliminar_residuales`, que ya corre antes)."""
    if torre.cantidad <= 0:
        return True

    candidata = TorreCandidate(
        sku=torre.sku, cd=torre.cd, orientacion=torre.orientacion,
        largo=torre.largo, ancho=torre.ancho, alto_caja=torre.alto_caja,
        max_cajas_verticales=torre.cantidad, cantidad_disponible=torre.cantidad,
        peso_unitario=(torre.peso / torre.cantidad if torre.cantidad else 0.0),
        fuente_geometria=torre.fuente_geometria,
    )

    mejor = None
    for pc in destinos:
        ajuste = pc.mejor_ajuste(candidata, torre.cantidad, permitir_parcial=False)
        if ajuste is None:
            continue
        idx, sobra, _cantidad_colocable = ajuste
        if mejor is None or sobra < mejor[0]:
            mejor = (sobra, pc, idx)

    if mejor is not None:
        _, pc, idx = mejor
        pc.colocar(candidata, torre.cantidad, idx)
        return True

    if torre.cantidad <= 1:
        return False

    mitad = torre.cantidad // 2
    primera, segunda = dividir_torre(torre, mitad)
    return _reinsertar_en_mismo_sku(primera, destinos) and _reinsertar_en_mismo_sku(segunda, destinos)


def _recalcular_metadata(pallet: PalletV5) -> None:
    """Después de sacarle torres a un pallet por fuera de `colocar` (que ya
    mantiene esto solo), hay que recomputar lo derivado a mano."""
    if not pallet.torres:
        pallet.altura_final = config.ALTURA_PALLET_VACIO
        pallet.ocupacion_xy = 0.0
        pallet.volumen_utilizado = 0.0
        pallet.peso_estimado = 0.0
        return
    pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in pallet.torres)
    pallet.ocupacion_xy = round(_area_union_xy(pallet.torres) / (config.PALLET_LARGO * config.PALLET_ANCHO), 4)
    pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in pallet.torres), 2)
    pallet.peso_estimado = sum(t.peso for t in pallet.torres)


def consolidar_por_cd(pallets_cd: list[PalletV5]) -> list[PalletV5]:
    """`pallets_cd` debe ser de UN solo CD (no se valida acá, mismo
    contrato que `packing_columnar.armar_pallets_columnar`). Determinístico,
    nunca pierde demanda (rollback exacto en cada intento fallido), nunca
    abre un pallet nuevo ni aumenta el total del CD -en el peor caso no
    cambia nada. Las torres BAT (`BAT_SKU_MARCADOR`) no se tocan -no son un
    SKU real, ver bat.py."""
    pallets = list(pallets_cd)
    intentados: set[str] = set()
    cambiado = True

    while cambiado:
        cambiado = False

        sku_a_pallets: dict[str, set[int]] = {}
        for i, p in enumerate(pallets):
            for t in p.torres:
                if t.sku == BAT_SKU_MARCADOR:
                    continue
                sku_a_pallets.setdefault(t.sku, set()).add(i)

        candidatos = {sku: idxs for sku, idxs in sku_a_pallets.items() if len(idxs) > 1 and sku not in intentados}
        if not candidatos:
            break

        # el SKU repartido en MÁS pallets primero -mayor beneficio potencial.
        sku = max(candidatos, key=lambda s: len(candidatos[s]))
        idxs = sorted(candidatos[sku])

        # el pallet con MENOS cajas de este SKU se intenta vaciar primero
        # -más fácil de mover que el que ya tiene la mayor parte.
        idxs_ordenados = sorted(idxs, key=lambda i: sum(t.cantidad for t in pallets[i].torres if t.sku == sku))
        origen_idx = idxs_ordenados[0]
        origen = pallets[origen_idx]
        torres_origen = [t for t in origen.torres if t.sku == sku]
        destinos_idx = [i for i in idxs if i != origen_idx]

        snap = _snapshot([pallets[i] for i in destinos_idx])
        destinos_pc = [_reconstruir_en_construccion(pallets[i]) for i in destinos_idx]
        exito = all(_reinsertar_en_mismo_sku(t, destinos_pc) for t in torres_origen)

        if exito:
            origen.torres = [t for t in origen.torres if t.sku != sku]
            _recalcular_metadata(origen)
            if not origen.torres:
                pallets.pop(origen_idx)
            cambiado = True
        else:
            _restaurar([pallets[i] for i in destinos_idx], snap)
            intentados.add(sku)

    return pallets


def consolidar_sku(pallets_v5: list[PalletV5]) -> list[PalletV5]:
    """Agrupa por CD (preservando el orden de aparición) y aplica
    `consolidar_por_cd` a cada grupo -`pallets_v5` puede venir con varios
    CDs mezclados, como lo devuelve `pipeline_v5.ejecutar_core_v5`."""
    por_cd: dict[str, list[PalletV5]] = {}
    orden_cds: list[str] = []
    for p in pallets_v5:
        if p.cd not in por_cd:
            por_cd[p.cd] = []
            orden_cds.append(p.cd)
        por_cd[p.cd].append(p)

    resultado: list[PalletV5] = []
    for cd in orden_cds:
        resultado.extend(consolidar_por_cd(por_cd[cd]))
    return resultado
