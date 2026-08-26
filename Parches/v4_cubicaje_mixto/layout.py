"""Igual que solver.py pero reconstruye el PATRON concreto, no solo el conteo,
para que un operario pueda verificar/reproducir la distribucion en el pallet."""
from functools import lru_cache
EPS = 1e-9


def _cands(limite, l, w):
    vals = {0.0}
    i = 0
    while i * l <= limite + EPS:
        j = 0
        while i * l + j * w <= limite + EPS:
            vals.add(round(i * l + j * w, 6))
            j += 1
        i += 1
    return sorted(v for v in vals if EPS < v < limite - EPS)


def resolver(W, H, largo, ancho, prof_max=6):
    """Devuelve (n_cajas, bloques) donde bloques = [(x,y,cols,filas,bw,bh,orient)]."""
    if largo <= 0 or ancho <= 0:
        return 0, []
    corto = min(largo, ancho)

    @lru_cache(maxsize=None)
    def rec(W, H, prof):
        if W < corto - EPS or H < corto - EPS:
            return 0, ()
        mejor, bloques = 0, ()
        for bw, bh, ori in ((largo, ancho, "L×A"), (ancho, largo, "A×L")):
            cols, filas = int((W + EPS) // bw), int((H + EPS) // bh)
            if cols * filas > mejor:
                mejor = cols * filas
                bloques = ((0.0, 0.0, cols, filas, bw, bh, ori),)
        if prof <= 0:
            return mejor, bloques
        for x in _cands(W / 2 + EPS, largo, ancho):
            n1, b1 = rec(round(x, 6), H, prof - 1)
            n2, b2 = rec(round(W - x, 6), H, prof - 1)
            if n1 + n2 > mejor:
                mejor = n1 + n2
                bloques = b1 + tuple((bx + x, by, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b2)
        for y in _cands(H / 2 + EPS, largo, ancho):
            n1, b1 = rec(W, round(y, 6), prof - 1)
            n2, b2 = rec(W, round(H - y, 6), prof - 1)
            if n1 + n2 > mejor:
                mejor = n1 + n2
                bloques = b1 + tuple((bx, by + y, c, f, bw, bh, o) for bx, by, c, f, bw, bh, o in b2)
        return mejor, bloques

    n, b = rec(round(W, 6), round(H, 6), prof_max)
    return n, [x for x in b if x[2] > 0 and x[3] > 0]


def describir(bloques):
    """Texto corto y legible del patron para el Excel."""
    if not bloques:
        return "no cabe ninguna caja"
    partes = []
    for _x, _y, cols, filas, bw, bh, ori in bloques:
        partes.append(f"{cols}x{filas} de {bw:g}x{bh:g}cm ({ori})")
    return " + ".join(partes)
