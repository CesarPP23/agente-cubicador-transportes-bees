"""Busqueda EXACTA del maximo de rectangulos identicos en W x H.

Usa el teorema de posiciones canonicas: en un empaque optimo, toda caja puede
empujarse abajo-izquierda hasta que su coordenada sea una suma de multiplos de
las dimensiones. Se generan todas las colocaciones candidatas y se busca el
subconjunto maximo sin solapamiento (branch and bound exacto).
"""
def _sumas(limite, dims):
    vals = {0}
    pila = [0]
    while pila:
        v = pila.pop()
        for d in dims:
            n = round(v + d, 6)
            if n <= limite + 1e-9 and n not in vals:
                vals.add(n); pila.append(n)
    return sorted(vals)


def max_exacto(W, H, dims_huella):
    """dims_huella: lista de (w, d) permitidas. Devuelve (n, colocaciones)."""
    todos = sorted({x for wd in dims_huella for x in wd})
    cands = []
    for (w, d) in dims_huella:
        for x in _sumas(W - w, todos):
            for y in _sumas(H - d, todos):
                if x + w <= W + 1e-9 and y + d <= H + 1e-9:
                    cands.append((x, y, w, d))
    cands = sorted(set(cands), key=lambda c: (c[1], c[0]))

    n = len(cands)
    solapa = [[False]*n for _ in range(n)]
    for i in range(n):
        xi, yi, wi, di = cands[i]
        for j in range(i+1, n):
            xj, yj, wj, dj = cands[j]
            if not (xi+wi <= xj+1e-9 or xj+wj <= xi+1e-9 or yi+di <= yj+1e-9 or yj+dj <= yi+1e-9):
                solapa[i][j] = solapa[j][i] = True

    area_caja = dims_huella[0][0]*dims_huella[0][1]
    cota_area = int((W*H + 1e-9)//area_caja)
    mejor = [0]; mejor_sol = [[]]

    def bb(idx, elegidos, libres):
        if len(elegidos) > mejor[0]:
            mejor[0] = len(elegidos); mejor_sol[0] = list(elegidos)
        if mejor[0] >= cota_area:
            return
        if len(elegidos) + len(libres) <= mejor[0]:
            return
        for k, i in enumerate(libres):
            if len(elegidos) + len(libres) - k <= mejor[0]:
                return
            nuevos = [j for j in libres[k+1:] if not solapa[i][j]]
            bb(i, elegidos + [i], nuevos)

    bb(-1, [], list(range(n)))
    return mejor[0], [cands[i] for i in mejor_sol[0]], len(cands)
