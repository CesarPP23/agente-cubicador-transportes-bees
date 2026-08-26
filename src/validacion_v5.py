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


def _area_cubierta_por_soporte(t: Torre, soportes: list[Torre]) -> float:
    """[anti-flotación] Área de la huella de `t` que está cubierta por la
    unión de las huellas de `soportes` (torres cuyo tope de Z coincide con
    la base de `t`) -si es menor al área total de `t`, existe una región de
    su huella sin nada real debajo (caja flotando). Mismo sweep por
    coordenadas comprimidas que `_area_union_xy` de packing_columnar.py."""
    if not soportes:
        return 0.0
    xs = sorted({t.x, t.x + t.largo} | {s.x for s in soportes} | {s.x + s.largo for s in soportes})
    ys = sorted({t.y, t.y + t.ancho} | {s.y for s in soportes} | {s.y + s.ancho for s in soportes})
    area = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x1 - x0 <= TOLERANCIA_CM or x0 < t.x - TOLERANCIA_CM or x1 > t.x + t.largo + TOLERANCIA_CM:
            continue
        mx = (x0 + x1) / 2
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            if y1 - y0 <= TOLERANCIA_CM or y0 < t.y - TOLERANCIA_CM or y1 > t.y + t.ancho + TOLERANCIA_CM:
                continue
            my = (y0 + y1) / 2
            if any(
                s.x - TOLERANCIA_CM <= mx <= s.x + s.largo + TOLERANCIA_CM
                and s.y - TOLERANCIA_CM <= my <= s.y + s.ancho + TOLERANCIA_CM
                for s in soportes
            ):
                area += (x1 - x0) * (y1 - y0)
    return area


def validar_pallet_v5(pallet: PalletV5) -> list[str]:
    """Devuelve una lista de violaciones legibles (vacía si el pallet es
    geométricamente válido). No corrige nada -solo reporta, para que quien
    llame decida qué hacer (el gate P14 las trata como bloqueantes)."""
    violaciones: list[str] = []
    torres = pallet.torres

    for t in torres:
        # [anti-flotación, reporte real del usuario con foto del Inspector:
        # "hay cajas que estan flotandoen el vacio, toda caja debe esta
        # puesta sobre otra caja"] Toda torre que no arranca en el piso del
        # pallet (z=0) tiene que tener, debajo de TODA su huella, torres
        # reales cuyo tope quede exactamente en su z -no solo parcialmente.
        if t.z > TOLERANCIA_CM:
            soportes = [o for o in torres if o is not t and abs((o.z + o.altura) - t.z) <= TOLERANCIA_CM]
            area_total = t.largo * t.ancho
            area_cubierta = _area_cubierta_por_soporte(t, soportes)
            if area_cubierta < area_total - TOLERANCIA_CM:
                violaciones.append(
                    f"{pallet.id}: torre {t.sku}@({t.x:.1f},{t.y:.1f},z={t.z:.1f}) no tiene soporte "
                    f"real en toda su huella ({area_cubierta:.1f}/{area_total:.1f} cm² cubiertos) -caja flotando"
                )
        # [sobresaliente] El tope real es la base EXTENDIDA
        # (PALLET_LARGO_EFECTIVO/ANCHO_EFECTIVO, +2.5cm por lado -estándar
        # logístico ya confirmado), no la base estricta 120x100 -pallets
        # dedicados a un solo SKU (ver packing_bloques._dedicar_por_sku)
        # pueden usar ese margen a propósito.
        if (
            t.x < -TOLERANCIA_CM or t.y < -TOLERANCIA_CM
            or t.x + t.largo > config.PALLET_LARGO_EFECTIVO + TOLERANCIA_CM
            or t.y + t.ancho > config.PALLET_ANCHO_EFECTIVO + TOLERANCIA_CM
        ):
            violaciones.append(
                f"{pallet.id}: torre {t.sku}@({t.x:.1f},{t.y:.1f}) "
                f"{t.largo:.1f}x{t.ancho:.1f} se sale de la base extendida "
                f"{config.PALLET_LARGO_EFECTIVO}x{config.PALLET_ANCHO_EFECTIVO}"
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
