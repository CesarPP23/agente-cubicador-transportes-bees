"""[V5-P8] Residual Elimination Search.

Ataca específicamente la brecha entre lo que deja el packer/multi-start y el
benchmark real: desarma el pallet MENOS utilizado, intenta reinsertar todo su
contenido (torre por torre, dividiendo si hace falta) en los pallets que
quedan, y si lo logra por completo, elimina el pallet de origen. Repite hasta
que una pasada completa no logre eliminar ninguno.

DOCUMENTACION_TECNICA_V5.md sección 9.
"""
import copy

from models import PalletV5, Torre
from src.packing_columnar import _PalletEnConstruccion, _reconstruir_en_construccion
from src.torres import TorreCandidate, dividir_torre


def _reinsertar_torre(torre: Torre, destinos: list[_PalletEnConstruccion]) -> bool:
    """Intenta insertar `torre` completa (best area fit entre TODOS los
    destinos); si no entra en ningún lado, la divide a la mitad y reintenta
    cada mitad por separado -recursivo, hasta cajas individuales si hace
    falta. Nunca hace crecer la torre más allá de lo que ya tenía."""
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
        # [packing3d] permitir_parcial=False: todo-o-nada acá, la torre se
        # divide explícitamente más abajo si no entra completa en ningún lado.
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
        return False  # no se puede dividir más -no hay destino para ni una sola caja

    mitad = torre.cantidad // 2
    primera, segunda = dividir_torre(torre, mitad)
    return _reinsertar_torre(primera, destinos) and _reinsertar_torre(segunda, destinos)


def _snapshot(pallets: list[PalletV5]) -> list[PalletV5]:
    return [copy.deepcopy(p) for p in pallets]


def _restaurar(pallets: list[PalletV5], snapshot: list[PalletV5]) -> None:
    for p, snap in zip(pallets, snapshot):
        p.torres = snap.torres
        p.altura_final = snap.altura_final
        p.peso_estimado = snap.peso_estimado
        p.ocupacion_xy = snap.ocupacion_xy
        p.volumen_utilizado = snap.volumen_utilizado


def eliminar_residuales(pallets: list[PalletV5], max_iteraciones: int | None = None) -> list[PalletV5]:
    """[sección 9] `pallets` debe ser de UN solo CD (no se valida acá, igual
    que `packing_columnar.armar_pallets_columnar`). Nunca aumenta la
    cantidad de pallets, nunca pierde demanda (cada intento fallido hace
    rollback exacto al estado anterior), determinístico (mismo input -> mismo
    resultado, no hay aleatoriedad acá)."""
    pallets = list(pallets)
    max_iteraciones = max_iteraciones if max_iteraciones is not None else len(pallets) + 1
    iteraciones = 0

    while iteraciones < max_iteraciones:
        iteraciones += 1
        orden = sorted(pallets, key=lambda p: p.altura_final)
        mejora = False

        for origen in orden:
            resto = [p for p in pallets if p is not origen]
            if not resto:
                continue

            snap = _snapshot(resto)
            destinos = [_reconstruir_en_construccion(p) for p in resto]
            exito = all(_reinsertar_torre(t, destinos) for t in origen.torres)

            if exito:
                pallets = resto
                mejora = True
                break

            _restaurar(resto, snap)

        if not mejora:
            break

    return pallets
