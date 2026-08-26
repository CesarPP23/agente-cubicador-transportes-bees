"""[V5-P3] Solver único de capacidad + layout.

Regla obligatoria (DOCUMENTACION_TECNICA_V5.md sección 5): el mismo solver
que afirma que N cajas entran debe poder devolver las N posiciones concretas.
Antes (`src/solver_cajas.py`, V4/P1) el solver de capacidad y el shelf-packer
de `packing_2d.py` eran dos algoritmos DISTINTOS -uno podía decir "entran 10"
sin que el otro supiera cómo acomodarlas. Este módulo reemplaza esa
separación: capacidad y placements salen de la MISMA búsqueda.

Reutiliza las tres familias de patrones de `solver_cajas.py` (grilla,
guillotina recursiva, pinwheel/five-block) pero reconstruye POSICIONES reales
en vez de devolver solo el conteo.
"""
from dataclasses import dataclass, field
from functools import lru_cache

EPS = 1e-9


@dataclass
class LayoutResult:
    capacidad: int
    # (x, y, w, d, orientacion) por caja -orientacion es "L×A" (largo a lo
    # largo del eje X) o "A×L" (ancho a lo largo del eje X).
    placements: list[tuple[float, float, float, float, str]] = field(default_factory=list)
    metodo: str = "grilla uniforme"
    ocupacion_area: float = 0.0
    valido: bool = True


def _candidatos(limite: float, l: float, w: float) -> list[float]:
    """Posiciones de corte canónicas: toda combinación i*l + j*w <= límite."""
    vals = {0.0}
    i = 0
    while i * l <= limite + EPS:
        j = 0
        while i * l + j * w <= limite + EPS:
            vals.add(round(i * l + j * w, 6))
            j += 1
        i += 1
    return sorted(v for v in vals if EPS < v < limite - EPS)


# Bloque = (x, y, columnas, filas, ancho_caja, alto_caja, orientacion) -una
# grilla uniforme rectangular dentro de una sub-región. Se expande a
# placements individuales recién al final (barato: cols*filas por bloque).
Bloque = tuple[float, float, int, int, float, float, str]


def _resolver_bloques(largo: float, ancho: float, prof_max: int = 6):
    """[adaptado de Parches/v4_cubicaje_mixto/layout.py] Guillotina recursiva
    con memoización -devuelve (mejor_cantidad, funcion_rec) para poder
    reusar `rec(W, H, prof)` tanto para la búsqueda de guillotina "pura" como
    para las 5 sub-regiones del pinwheel (misma función, distinta W/H/prof)."""
    corto = min(largo, ancho)

    @lru_cache(maxsize=None)
    def rec(W: float, H: float, prof: int) -> tuple[int, tuple[Bloque, ...]]:
        if W < corto - EPS or H < corto - EPS:
            return 0, ()
        mejor, bloques = 0, ()
        for bw, bh, ori in ((largo, ancho, "L×A"), (ancho, largo, "A×L")):
            if bw <= 0 or bh <= 0:
                continue
            cols, filas = int((W + EPS) // bw), int((H + EPS) // bh)
            if cols * filas > mejor:
                mejor = cols * filas
                bloques = ((0.0, 0.0, cols, filas, bw, bh, ori),)
        if prof <= 0:
            return mejor, bloques
        for x in _candidatos(W / 2 + EPS, largo, ancho):
            n1, b1 = rec(round(x, 6), H, prof - 1)
            n2, b2 = rec(round(W - x, 6), H, prof - 1)
            if n1 + n2 > mejor:
                mejor = n1 + n2
                bloques = b1 + tuple((bx + x, by, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b2)
        for y in _candidatos(H / 2 + EPS, largo, ancho):
            n1, b1 = rec(W, round(y, 6), prof - 1)
            n2, b2 = rec(W, round(H - y, 6), prof - 1)
            if n1 + n2 > mejor:
                mejor = n1 + n2
                bloques = b1 + tuple((bx, by + y, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b2)
        return mejor, bloques

    return rec


def _bloques_a_placements(bloques) -> list[tuple[float, float, float, float, str]]:
    placements = []
    for x, y, cols, filas, bw, bh, ori in bloques:
        if cols <= 0 or filas <= 0:
            continue
        for j in range(filas):
            for i in range(cols):
                placements.append((round(x + i * bw, 6), round(y + j * bh, 6), bw, bh, ori))
    return placements


def _pinwheel_placements(W: float, H: float, largo: float, ancho: float, rec) -> list[tuple[float, float, float, float, str]]:
    """Five-block: cuatro sub-regiones girando alrededor de una quinta
    central -la familia de patrones que la guillotina NO puede generar
    (ver solver_cajas.pinwheel). Reconstruye posiciones probando las mismas
    combinaciones (x1,x2,y1,y2) que la búsqueda de solo-conteo, y expandiendo
    los bloques ganadores de cada una de las 5 sub-regiones."""
    xs = [0.0] + _candidatos(W, largo, ancho) + [W]
    ys = [0.0] + _candidatos(H, largo, ancho) + [H]

    mejor_total = -1
    mejor_bloques: tuple[Bloque, ...] = ()

    for x1 in xs:
        for x2 in xs:
            if x2 < x1 - EPS:
                continue
            for y1 in ys:
                for y2 in ys:
                    if y2 < y1 - EPS:
                        continue
                    if abs(x1 - x2) < EPS and abs(y1 - y2) < EPS:
                        continue  # degenera en guillotina pura

                    n1, b1 = rec(round(x2, 6), round(y1, 6), 2)
                    n2, b2 = rec(round(W - x2, 6), round(y2, 6), 2)
                    n3, b3 = rec(round(W - x1, 6), round(H - y2, 6), 2)
                    n4, b4 = rec(round(x1, 6), round(H - y1, 6), 2)
                    n5, b5 = rec(round(x2 - x1, 6), round(y2 - y1, 6), 2)
                    total = n1 + n2 + n3 + n4 + n5

                    if total > mejor_total:
                        mejor_total = total
                        mejor_bloques = (
                            b1
                            + tuple((bx + x2, by, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b2)
                            + tuple((bx + x1, by + y2, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b3)
                            + tuple((bx, by + y1, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b4)
                            + tuple((bx + x1, by + y1, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b5)
                        )

    return _bloques_a_placements(mejor_bloques)


def _hay_solapes(placements: list[tuple[float, float, float, float, str]]) -> bool:
    for idx, (x1, y1, w1, d1, _o1) in enumerate(placements):
        for x2, y2, w2, d2, _o2 in placements[idx + 1 :]:
            if x1 + w1 <= x2 + EPS or x2 + w2 <= x1 + EPS or y1 + d1 <= y2 + EPS or y2 + d2 <= y1 + EPS:
                continue
            return True
    return False


def resolver_layout_rectangulos(
    pallet_largo: float,
    pallet_ancho: float,
    caja_largo: float,
    caja_ancho: float,
    cantidad_objetivo: int | None = None,
    permitir_rotacion_xy: bool = True,
    con_pinwheel: bool = True,
) -> LayoutResult:
    """[V5-P3] Máximo de cajas `caja_largo x caja_ancho` dentro de
    `pallet_largo x pallet_ancho`, con placements reales. `cantidad_objetivo`
    es informativo (no cambia el resultado -el solver siempre busca el
    máximo; queda para que el caller compare contra lo que necesitaba).

    `permitir_rotacion_xy=False` fija una sola orientación (bw=caja_largo,
    bh=caja_ancho) -para SKUs de categorías que no pueden rotar."""
    if caja_largo <= 0 or caja_ancho <= 0 or pallet_largo <= 0 or pallet_ancho <= 0:
        return LayoutResult(capacidad=0, placements=[], metodo="dimension invalida", ocupacion_area=0.0, valido=False)

    cabe = (caja_largo <= pallet_largo + EPS and caja_ancho <= pallet_ancho + EPS) or (
        caja_ancho <= pallet_largo + EPS and caja_largo <= pallet_ancho + EPS
    )
    if not cabe:
        return LayoutResult(capacidad=0, placements=[], metodo="no cabe ni una caja", ocupacion_area=0.0, valido=True)

    if not permitir_rotacion_xy:
        cols = int((pallet_largo + EPS) // caja_largo)
        filas = int((pallet_ancho + EPS) // caja_ancho)
        placements = _bloques_a_placements(((0.0, 0.0, cols, filas, caja_largo, caja_ancho, "L×A"),))
        area = len(placements) * caja_largo * caja_ancho
        return LayoutResult(
            capacidad=len(placements), placements=placements, metodo="grilla uniforme (sin rotación)",
            ocupacion_area=area, valido=True,
        )

    rec = _resolver_bloques(caja_largo, caja_ancho)
    n_guillotina, bloques_guillotina = rec(round(pallet_largo, 6), round(pallet_ancho, 6), 6)
    placements_guillotina = _bloques_a_placements(bloques_guillotina)
    metodo = "grilla uniforme" if len(bloques_guillotina) <= 1 else "mixto (guillotina)"
    mejor_placements, mejor_metodo = placements_guillotina, metodo

    if con_pinwheel:
        placements_pin = _pinwheel_placements(pallet_largo, pallet_ancho, caja_largo, caja_ancho, rec)
        if len(placements_pin) > len(mejor_placements):
            mejor_placements, mejor_metodo = placements_pin, "mixto (pinwheel)"

    area = len(mejor_placements) * caja_largo * caja_ancho
    resultado = LayoutResult(
        capacidad=len(mejor_placements),
        placements=mejor_placements,
        metodo=mejor_metodo,
        ocupacion_area=round(area, 3),
        valido=True,
    )

    # [V5-P3] Regla obligatoria: nunca afirmar una capacidad que el propio
    # resultado no pueda respaldar con placements reales, sin solapes ni
    # desborde. Si algo no cierra, se degrada a la grilla uniforme (que
    # siempre es válida por construcción) en vez de devolver un resultado
    # optimista pero geométricamente roto.
    fuera_de_rango = any(
        x < -EPS or y < -EPS or x + w > pallet_largo + EPS or y + d > pallet_ancho + EPS
        for x, y, w, d, _o in resultado.placements
    )
    if fuera_de_rango or _hay_solapes(resultado.placements):
        cols = int((pallet_largo + EPS) // caja_largo)
        filas = int((pallet_ancho + EPS) // caja_ancho)
        placements = _bloques_a_placements(((0.0, 0.0, cols, filas, caja_largo, caja_ancho, "L×A"),))
        resultado = LayoutResult(
            capacidad=len(placements), placements=placements, metodo="grilla uniforme (fallback por validación)",
            ocupacion_area=len(placements) * caja_largo * caja_ancho, valido=True,
        )

    return resultado
