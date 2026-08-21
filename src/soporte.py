"""[V3 / sección 10, 14, 15] Soporte geométrico real.

`FILL_RATIO_MIN_SOPORTE=0` no debe interpretarse como "seguridad validada":
que dé un conteo de pallets más parecido al real no prueba estabilidad
física. Este módulo calcula el soporte GEOMÉTRICO real (intersección de área
entre la caja de arriba y las de abajo) a partir de los `Placement` ya
existentes, como KPI/alerta -sección 10.2: inicialmente se guarda y se
alerta, no bloquea, hasta que se valide con operación.
"""
from models import Cama, Pallet, Placement


def support_ratio(caja_superior: Placement, placements_inferiores: list[Placement]) -> float:
    """[sección 15.1] Fracción del área de la base de `caja_superior` que
    queda soportada por la unión de `placements_inferiores` (misma cama
    inferior). 1.0 = totalmente apoyada, 0.0 = ningún solape (voladizo
    completo)."""
    area_caja = caja_superior.w * caja_superior.d
    if area_caja <= 0:
        return 0.0

    area_soportada = 0.0
    for inferior in placements_inferiores:
        ix = max(
            0.0,
            min(caja_superior.x + caja_superior.w, inferior.x + inferior.w) - max(caja_superior.x, inferior.x),
        )
        iy = max(
            0.0,
            min(caja_superior.y + caja_superior.d, inferior.y + inferior.d) - max(caja_superior.y, inferior.y),
        )
        area_soportada += ix * iy

    # Clamp: si los placements inferiores se solapan entre sí (no debería
    # pasar en un packing bien formado), no se cuenta el área de más de una
    # vez sobre la misma caja superior.
    return min(area_soportada, area_caja) / area_caja


def support_ratio_cama(cama_superior: Cama, cama_inferior: Cama) -> float | None:
    """[sección 15.2] Menor support_ratio entre todas las cajas de
    `cama_superior` contra `cama_inferior`. None si alguna de las dos no
    tiene geometría (PH/BAT: sin placements, no hay como medirlas -se asumen
    sólidas, ver Cama.fill_ratio)."""
    if not cama_superior.placements or not cama_inferior.placements:
        return None
    ratios = [support_ratio(caja, cama_inferior.placements) for caja in cama_superior.placements]
    return min(ratios) if ratios else None


def clasificar_soporte_pallet(pallet: Pallet) -> None:
    """[sección 14.2] Post-procesa un pallet YA ARMADO (orden final de
    camas ya decidido): marca la última cama como TERMINAL (nada se apoya
    encima -tolerancia de altura más laxa, config.TOLERANCIA_ALTURA_TERMINAL)
    y el resto como PORTANTE, y calcula support_ratio_min de cada cama
    portante contra la que tiene inmediatamente encima. Puramente informativo
    -sección 10.2, no bloquea el armado."""
    camas = pallet.camas
    if not camas:
        return

    for i, cama in enumerate(camas):
        es_ultima = i == len(camas) - 1
        cama.tipo_soporte = "TERMINAL" if es_ultima else "PORTANTE"
        if not es_ultima:
            cama.support_ratio_min = support_ratio_cama(camas[i + 1], cama)

    ratios = [c.support_ratio_min for c in camas if c.support_ratio_min is not None]
    pallet.support_ratio_min = min(ratios) if ratios else None
