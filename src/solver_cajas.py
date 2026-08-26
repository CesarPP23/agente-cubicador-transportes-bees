"""[V4 / Parches/v4_cubicaje_mixto/PARCHES_V4.md, P1] Maximo numero de
rectangulos identicos (con rotacion 90 en el plano) dentro de una region
W x H.

Movido tal cual desde Parches/v4_cubicaje_mixto/solver.py -ya escrito y
probado (300 casos aleatorios sin superar el limite de area, mas los casos
puntuales de la tabla de validacion en PARCHES_V4.md)- para que
reconciliacion_geometrica.py pueda importarlo como src.solver_cajas.

La caja SIEMPRE va parada: la altura es vertical y no participa. La huella es
largo x ancho, y solo puede girar sobre su propio eje -> dos huellas posibles:
(largo, ancho) y (ancho, largo).

Metodo (de menor a mayor poder, se toma el maximo de los tres):
  1. Grillas uniformes: filas x columnas en cada una de las dos orientaciones.
  2. Guillotina recursiva: cortes rectos de lado a lado, recursivo, con
     posiciones candidatas canonicas (i*l + j*w). Encuentra patrones MIXTOS:
     bloques con distinta orientacion conviviendo en la misma cama.
  3. Pinwheel / five-block: descomposicion NO guillotinable (molinete), el
     patron clasico que ninguna secuencia de cortes rectos puede producir.
"""
from functools import lru_cache

EPS = 1e-9


def _candidatos(limite, l, w):
    """Posiciones de corte canonicas: toda combinacion i*l + j*w <= limite."""
    vals = {0.0}
    i = 0
    while i * l <= limite + EPS:
        j = 0
        while i * l + j * w <= limite + EPS:
            vals.add(round(i * l + j * w, 6))
            j += 1
        i += 1
    return sorted(v for v in vals if EPS < v < limite - EPS)


def _grid(W, H, l, w):
    return int((W + EPS) // l) * int((H + EPS) // w)


def crear_solver(l, w, max_profundidad=6):
    """Devuelve (funcion_max, funcion_detalle) para una caja de huella l x w."""
    corto, largo = min(l, w), max(l, w)

    @lru_cache(maxsize=None)
    def guillotina(W, H, prof):
        if W < corto - EPS or H < corto - EPS:
            return 0
        # grillas uniformes en ambas orientaciones
        mejor = max(_grid(W, H, l, w), _grid(W, H, w, l))
        if prof <= 0:
            return mejor
        # cortes verticales (solo hasta la mitad: el resto es simetrico)
        for x in _candidatos(W / 2 + EPS, l, w):
            mejor = max(mejor, guillotina(round(x, 6), H, prof - 1)
                             + guillotina(round(W - x, 6), H, prof - 1))
        # cortes horizontales
        for y in _candidatos(H / 2 + EPS, l, w):
            mejor = max(mejor, guillotina(W, round(y, 6), prof - 1)
                             + guillotina(W, round(H - y, 6), prof - 1))
        return mejor

    def pinwheel(W, H):
        """Five-block: cuatro bloques girando alrededor de un quinto central.
        Es la familia de patrones que la guillotina NO puede generar."""
        mejor = 0
        xs = [0.0] + _candidatos(W, l, w) + [W]
        ys = [0.0] + _candidatos(H, l, w) + [H]
        for x1 in xs:
            for x2 in xs:
                if x2 < x1 - EPS:
                    continue
                for y1 in ys:
                    for y2 in ys:
                        if y2 < y1 - EPS:
                            continue
                        if abs(x1 - x2) < EPS and abs(y1 - y2) < EPS:
                            continue  # degenera en guillotina, ya cubierto
                        total = (
                            guillotina(round(x2, 6),     round(y1, 6),     2)
                            + guillotina(round(W - x2, 6), round(y2, 6),     2)
                            + guillotina(round(W - x1, 6), round(H - y2, 6), 2)
                            + guillotina(round(x1, 6),     round(H - y1, 6), 2)
                            + guillotina(round(x2 - x1, 6), round(y2 - y1, 6), 2)
                        )
                        mejor = max(mejor, total)
        return mejor

    return guillotina, pinwheel


def max_cajas(W, H, largo, ancho, con_pinwheel=True):
    """Maximo de cajas de huella largo x ancho dentro de W x H."""
    if largo <= 0 or ancho <= 0:
        return 0, "dimension invalida"
    cabe = (largo <= W + EPS and ancho <= H + EPS) or (ancho <= W + EPS and largo <= H + EPS)
    if not cabe:
        return 0, "no cabe ni una caja"

    g_a = _grid(W, H, largo, ancho)
    g_b = _grid(W, H, ancho, largo)
    mejor_grilla = max(g_a, g_b)

    guillotina, pinwheel = crear_solver(largo, ancho)
    mejor_guillotina = guillotina(round(W, 6), round(H, 6), 6)

    mejor = max(mejor_grilla, mejor_guillotina)
    metodo = "grilla uniforme" if mejor_guillotina <= mejor_grilla else "mixto (guillotina)"

    if con_pinwheel:
        mejor_pin = pinwheel(round(W, 6), round(H, 6))
        if mejor_pin > mejor:
            mejor, metodo = mejor_pin, "mixto (pinwheel)"

    return mejor, metodo
