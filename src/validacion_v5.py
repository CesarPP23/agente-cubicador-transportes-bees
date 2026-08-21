"""[V5-P14, actualizado para packing3d] Validación geométrica dura sobre
pallets ya armados: overlap y overflow. El packer columnar (MaxRects 3D,
ver packing_columnar.py) NO debería producir nunca estas violaciones -esto
es una auditoría independiente del resultado final, no una segunda
implementación del algoritmo, para que el gate del benchmark (P14) tenga
algo verificable además de los conteos.

[packing3d] Dos torres pueden compartir el mismo (x, y) -eso es apilado
válido, no overlap- siempre que sus rangos de Z (altura) no se crucen.
Overlap real es AABB en 3D (X, Y, Z simultáneamente), no solo en XY como
antes de que las torres pudieran apilarse unas sobre otras."""
import config
from models import PalletV5, Torre

TOLERANCIA_CM = 1e-6


def _se_superponen(a: Torre, b: Torre, tol: float = TOLERANCIA_CM) -> bool:
    """AABB overlap en 3D (X, Y, Z) -tocarse en cualquier borde (mismo
    x+largo == x del otro, o mismo z+altura == z del otro) NO cuenta como
    superposición: es la forma normal en que dos torres quedan pegadas
    lado a lado, o una apilada arriba de otra."""
    return not (
        a.x + a.largo <= b.x + tol
        or b.x + b.largo <= a.x + tol
        or a.y + a.ancho <= b.y + tol
        or b.y + b.ancho <= a.y + tol
        or a.z + a.altura <= b.z + tol
        or b.z + b.altura <= a.z + tol
    )


def validar_pallet_v5(pallet: PalletV5) -> list[str]:
    """Devuelve una lista de violaciones legibles (vacía si el pallet es
    geométricamente válido). No corrige nada -solo reporta, para que quien
    llame decida qué hacer (el gate P14 las trata como bloqueantes)."""
    violaciones: list[str] = []
    torres = pallet.torres

    for t in torres:
        if (
            t.x < -TOLERANCIA_CM or t.y < -TOLERANCIA_CM
            or t.x + t.largo > config.PALLET_LARGO + TOLERANCIA_CM
            or t.y + t.ancho > config.PALLET_ANCHO + TOLERANCIA_CM
        ):
            violaciones.append(
                f"{pallet.id}: torre {t.sku}@({t.x:.1f},{t.y:.1f}) "
                f"{t.largo:.1f}x{t.ancho:.1f} se sale de la base {config.PALLET_LARGO}x{config.PALLET_ANCHO}"
            )

    for i in range(len(torres)):
        for j in range(i + 1, len(torres)):
            a, b = torres[i], torres[j]
            if _se_superponen(a, b):
                violaciones.append(
                    f"{pallet.id}: torre {a.sku}@({a.x:.1f},{a.y:.1f}) se superpone con "
                    f"torre {b.sku}@({b.x:.1f},{b.y:.1f})"
                )

    if pallet.altura_final > config.ALTURA_TOPE_DURO + TOLERANCIA_CM:
        violaciones.append(
            f"{pallet.id}: altura {pallet.altura_final:.2f} supera el tope duro {config.ALTURA_TOPE_DURO}"
        )

    return violaciones


def validar_geometria_v5(pallets: list[PalletV5]) -> list[str]:
    """Une las violaciones de todos los pallets -orden estable (por pallet,
    en el orden recibido) para que el reporte sea reproducible."""
    violaciones: list[str] = []
    for p in pallets:
        violaciones.extend(validar_pallet_v5(p))
    return violaciones
