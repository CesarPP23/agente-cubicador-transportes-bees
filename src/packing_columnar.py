"""[V5-P5, rediseñado V5-packing3d] Packer columnar: coloca TORRES en la
base 120x100 con Best-Area-Fit sobre espacio libre MaxRects
(DOCUMENTACION_TECNICA_V5.md sección 7.3: "Usar MaxRects o Skyline para
footprints").

[V5-packing3d] El espacio libre ahora es 3D (cuboides x,y,z,w,h,d), no solo
XY. Antes, una torre reservaba su huella XY de piso a techo del pallet
aunque su propia altura fuera mucho menor que la del pallet -el aire por
encima quedaba inutilizable para cualquier otra SKU (auditado con datos
reales: 82% de ocupación de huella pero solo ~54% de eficiencia
volumétrica real, ver PATCH_LOG.md). Con cuboides libres, cuando una torre
de altura h se coloca en un cuboide de altura d > h, queda un cuboide libre
NUEVO en la misma huella XY desde z=h hacia arriba -otra SKU (u otra torre
de la misma) puede apilarse ahí, lego real en vez de columnas aisladas.

La primera versión de este módulo (2D, sin esto) usaba guillotina de 2 vías
y fragmentaba demasiado rápido (68 pallets); MaxRects 2D lo bajó a 64;
BAT global (P9) a 61. El packing 3D es el intento de cerrar la brecha que
quedaba contra el objetivo (42-45), atacando la causa medida (aire
desperdiciado sobre torres cortas), no ajustando parámetros a ciegas.
"""
from dataclasses import dataclass, field

import pandas as pd

import config
from models import PalletV5, Torre
from src.torres import TorreCandidate, crear_torre, generar_torres_candidatas

TOL = 1e-6


@dataclass
class _CuboidLibre:
    x: float
    y: float
    z: float
    w: float  # ancho en X (largo del pallet)
    h: float  # ancho en Y (ancho del pallet)
    d: float  # profundidad en Z (altura disponible)

    @property
    def volumen(self) -> float:
        return self.w * self.h * self.d

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y + self.h

    @property
    def ceil(self) -> float:
        return self.z + self.d


def _se_solapan(a: _CuboidLibre, x: float, y: float, z: float, w: float, h: float, d: float) -> bool:
    return (
        a.x < x + w - TOL and x < a.right - TOL
        and a.y < y + h - TOL and y < a.top - TOL
        and a.z < z + d - TOL and z < a.ceil - TOL
    )


def _contenido(a: _CuboidLibre, b: _CuboidLibre) -> bool:
    """True si `a` está completamente contenido en `b` (a es redundante)."""
    return (
        a.x >= b.x - TOL and a.y >= b.y - TOL and a.z >= b.z - TOL
        and a.right <= b.right + TOL and a.top <= b.top + TOL and a.ceil <= b.ceil + TOL
    )


def _es_igual(a: _CuboidLibre, b: _CuboidLibre) -> bool:
    return (
        abs(a.x - b.x) < TOL and abs(a.y - b.y) < TOL and abs(a.z - b.z) < TOL
        and abs(a.w - b.w) < TOL and abs(a.h - b.h) < TOL and abs(a.d - b.d) < TOL
    )


def _podar_libres(cuboides: list[_CuboidLibre]) -> list[_CuboidLibre]:
    """MaxRects solo necesita quedarse con cuboides MAXIMALES: primero saca
    duplicados exactos, después cualquiera que quede estrictamente
    contenido en otro."""
    unicos: list[_CuboidLibre] = []
    for c in cuboides:
        if not any(_es_igual(c, u) for u in unicos):
            unicos.append(c)
    return [c for c in unicos if not any(c is not otro and _contenido(c, otro) for otro in unicos)]


def _actualizar_libres_maxrects(
    libres: list[_CuboidLibre], x: float, y: float, z: float, w: float, h: float, d: float
) -> list[_CuboidLibre]:
    """[MaxRects 3D] Después de colocar una caja `(x,y,z,w,h,d)`, parte
    cada cuboide libre que la solapaba en hasta 5 franjas maximales
    (izquierda/derecha/abajo/arriba en XY, y arriba en Z -nunca "abajo en
    Z": siempre se coloca a ras del piso del cuboide elegido, así que nunca
    queda un hueco debajo de lo recién puesto). Poda los que quedan
    contenidos en otro.

    [bug real corregido, reporte del usuario con foto del Inspector: "hay
    cajas que estan flotandoen el vacio"] El fragmento "arriba en Z" solo
    es soporte real dentro de la INTERSECCIÓN en XY entre la caja recién
    puesta y el cuboide que se está partiendo -no en todo el ancho/alto del
    cuboide original. Antes usaba `libre.w`/`libre.h` (el footprint
    COMPLETO del cuboide libre, que puede ser mucho más grande que la caja
    que se acaba de colocar dentro de él, p.ej. una caja chica colocada en
    la esquina de un cuboide libre grande): eso hacía que TODO ese
    footprint quedara "elevado" a la altura de la caja, aunque el resto del
    footprint siguiera vacío desde el piso -cualquier caja puesta después
    ahí terminaba flotando, sin nada real debajo en la parte no cubierta
    por la caja original."""
    nuevos: list[_CuboidLibre] = []
    for libre in libres:
        if not _se_solapan(libre, x, y, z, w, h, d):
            nuevos.append(libre)
            continue
        if x > libre.x + TOL:
            nuevos.append(_CuboidLibre(libre.x, libre.y, libre.z, x - libre.x, libre.h, libre.d))
        if x + w < libre.right - TOL:
            nuevos.append(_CuboidLibre(x + w, libre.y, libre.z, libre.right - (x + w), libre.h, libre.d))
        if y > libre.y + TOL:
            nuevos.append(_CuboidLibre(libre.x, libre.y, libre.z, libre.w, y - libre.y, libre.d))
        if y + h < libre.top - TOL:
            nuevos.append(_CuboidLibre(libre.x, y + h, libre.z, libre.w, libre.top - (y + h), libre.d))
        if z + d < libre.ceil - TOL:
            ix0, ix1 = max(libre.x, x), min(libre.right, x + w)
            iy0, iy1 = max(libre.y, y), min(libre.top, y + h)
            if ix1 - ix0 > TOL and iy1 - iy0 > TOL:
                nuevos.append(_CuboidLibre(ix0, iy0, z + d, ix1 - ix0, iy1 - iy0, libre.ceil - (z + d)))

    return _podar_libres([c for c in nuevos if c.w > TOL and c.h > TOL and c.d > TOL])


@dataclass
class _PalletEnConstruccion:
    pallet: PalletV5
    libres: list[_CuboidLibre] = field(
        default_factory=lambda: [
            _CuboidLibre(0.0, 0.0, 0.0, config.PALLET_LARGO, config.PALLET_ANCHO, _altura_presupuesto())
        ]
    )

    def cabe_altura(self, candidata: TorreCandidate, cantidad: int) -> bool:
        """Chequeo rápido: ¿hay AL MENOS un cuboide libre que pueda recibir
        1 caja de esta candidata? (footprint + al menos `alto_caja` de
        profundidad libre). No garantiza que quepan las `cantidad`
        pedidas -eso lo resuelve `mejor_ajuste`, que informa cuántas
        realmente entran."""
        for c in self.libres:
            if candidata.largo <= c.w + TOL and candidata.ancho <= c.h + TOL and candidata.alto_caja <= c.d + TOL:
                return True
        return False

    def mejor_ajuste(
        self, candidata: TorreCandidate, cantidad: int, permitir_parcial: bool = True
    ) -> tuple[int, float, int] | None:
        """Busca el cuboide libre que reciba la torre con MENOS volumen
        sobrante (Best Volume Fit), entre los que puedan recibir al menos 1
        caja. Devuelve (indice_del_libre, volumen_sobrante,
        cantidad_colocable).

        `permitir_parcial=True` (default, usado por `armar_pallets_columnar`):
        `cantidad_colocable` puede ser MENOR que `cantidad` si el mejor
        cuboide no tiene profundidad Z para la torre completa -eso es lo
        que permite apilar otra SKU distinta arriba después: el resto de
        la demanda sigue pendiente y el loop la busca en otro lado. OJO: un
        cuboide chico que solo entra 1 caja puede ganar por "menos volumen
        sobrante" aunque exista OTRO cuboide en la misma lista con lugar de
        sobra para la torre COMPLETA -no es un bug, es la heurística
        buscando el ajuste más ceñido primero.

        `permitir_parcial=False` (usado por `residual_search`/`bat`, que
        necesitan todo-o-nada): ignora cualquier cuboide que no pueda
        recibir la `cantidad` COMPLETA, y elige el de mejor ajuste solo
        entre esos -si el cuboide de "ajuste más ceñido" de arriba solo
        entraba parcial, con este flag se lo salta y busca uno más grande
        que sí entre entero, en vez de reportar que no cabe cuando en
        realidad sí cabía en otro lado."""
        mejor_idx, mejor_sobra, mejor_cantidad = None, float("inf"), 0
        for idx, c in enumerate(self.libres):
            if candidata.largo > c.w + TOL or candidata.ancho > c.h + TOL:
                continue
            cantidad_colocable = min(cantidad, int((c.d + TOL) // candidata.alto_caja))
            if cantidad_colocable <= 0:
                continue
            if permitir_parcial is False and cantidad_colocable < cantidad:
                continue
            usado = candidata.largo * candidata.ancho * cantidad_colocable * candidata.alto_caja
            sobra = c.volumen - usado
            if sobra < mejor_sobra:
                mejor_idx, mejor_sobra, mejor_cantidad = idx, sobra, cantidad_colocable
        if mejor_idx is None:
            return None
        return mejor_idx, mejor_sobra, mejor_cantidad

    def colocar(self, candidata: TorreCandidate, cantidad: int, idx_libre: int) -> Torre:
        """`cantidad` debe ser la `cantidad_colocable` que devolvió
        `mejor_ajuste` para este `idx_libre` -colocar más de lo que ese
        cuboide tiene en Z produciría una torre que se sale del espacio
        libre (violación de overflow, ver validacion_v5.py)."""
        c = self.libres[idx_libre]
        torre = crear_torre(candidata, x=c.x, y=c.y, cantidad=cantidad, z=c.z)
        # [MaxRects] La caja recién puesta puede solapar OTROS cuboides
        # libres además del elegido (están permitidos superponerse entre sí
        # -son "maximales", no una partición) -hay que re-evaluar la lista
        # COMPLETA contra el cuboide colocado, no solo partir el que se usó
        # para elegir la posición.
        self.libres = _actualizar_libres_maxrects(self.libres, c.x, c.y, c.z, torre.largo, torre.ancho, torre.altura)
        self.pallet.torres.append(torre)
        self.pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in self.pallet.torres)
        self.pallet.peso_estimado += torre.peso
        area_ocupada = _area_union_xy(self.pallet.torres)
        self.pallet.ocupacion_xy = round(area_ocupada / (config.PALLET_LARGO * config.PALLET_ANCHO), 4)
        self.pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in self.pallet.torres), 2)
        return torre


def _area_union_xy(torres: list[Torre]) -> float:
    """[packing3d] Área de huella REALMENTE ocupada, proyectada sobre XY
    -no la suma de `area_base` de cada torre, que ahora puede contar el
    mismo piso más de una vez cuando varias torres comparten (x, y) apiladas
    a distinto Z. Sweep por coordenadas comprimidas: divide el plano en
    celdas por los bordes de todas las torres y suma las que caen dentro de
    al menos una."""
    if not torres:
        return 0.0
    xs = sorted({t.x for t in torres} | {t.x + t.largo for t in torres})
    ys = sorted({t.y for t in torres} | {t.y + t.ancho for t in torres})
    area = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x1 - x0 <= TOL:
            continue
        mx = (x0 + x1) / 2
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            if y1 - y0 <= TOL:
                continue
            my = (y0 + y1) / 2
            if any(t.x - TOL <= mx <= t.x + t.largo + TOL and t.y - TOL <= my <= t.y + t.ancho + TOL for t in torres):
                area += (x1 - x0) * (y1 - y0)
    return area


def _altura_presupuesto() -> float:
    """Presupuesto de altura de PRODUCTO (sin contar el pallet vacío) -el
    mismo techo que usaba `cabe_altura` en la versión 2D."""
    return config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _reconstruir_en_construccion(pallet: PalletV5) -> "_PalletEnConstruccion":
    """[usado por residual_search.py y bat.py] Recalcula los cuboides
    libres MaxRects de un pallet YA armado, a partir de las torres que ya
    tiene (incluyendo su `z`) -para poder seguir ofreciéndolo como destino
    de reinserción/host con la misma lógica de este módulo."""
    libres = [_CuboidLibre(0.0, 0.0, 0.0, config.PALLET_LARGO, config.PALLET_ANCHO, _altura_presupuesto())]
    for t in pallet.torres:
        libres = _actualizar_libres_maxrects(libres, t.x, t.y, t.z, t.largo, t.ancho, t.altura)
    return _PalletEnConstruccion(pallet=pallet, libres=libres)


def _buscar_mejor(
    pallets: list["_PalletEnConstruccion"], candidatas_sku: list[TorreCandidate], pendiente: int
) -> tuple[float, "_PalletEnConstruccion", TorreCandidate, int, int] | None:
    """Best-area-fit entre `pallets` (subconjunto o todos los activos) para
    la demanda pendiente de un SKU. Extraído para poder llamarlo dos veces
    con distinto universo de pallets (ver `concentrar_sku`)."""
    mejor = None
    for pc in pallets:
        for cand in candidatas_sku:
            tope = min(cand.max_cajas_verticales, pendiente)
            if tope <= 0:
                continue
            ajuste = pc.mejor_ajuste(cand, tope)
            if ajuste is None:
                continue
            idx_libre, sobra, cantidad_colocable = ajuste
            if mejor is None or sobra < mejor[0]:
                mejor = (sobra, pc, cand, idx_libre, cantidad_colocable)
    return mejor


def armar_pallets_columnar(
    df_cd: pd.DataFrame,
    cd: str,
    contador: list[int] | None = None,
    pallets_semilla: list[PalletV5] | None = None,
    orden_skus: list[str] | None = None,
    concentrar_sku: bool = False,
) -> list[PalletV5]:
    """[V5-P5/P7, packing 3D] Arma los PalletV5 de un CD. `df_cd` debe traer
    demanda pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`) y
    geometría efectiva ya reconciliada (Largo/Ancho/Alto_Efectivo, Peso_Caja).

    `orden_skus` (opcional): en qué orden procesar los SKUs -si no se pasa,
    usa el default "básico" (mayor volumen potencial de torre primero). Con
    `orden_skus` explícito, `multistart.py` (P7) puede correr el MISMO
    packer con las 7 estrategias/semillas sin duplicar la lógica de armado.

    [packing3d] Cada intento de colocar una torre puede recibir MENOS
    cajas de las pedidas si el mejor cuboide disponible no tiene
    profundidad Z completa -el resto de la demanda del SKU sigue en el
    `while pendientes[sku] > 0` y busca otro cuboide (mismo pallet, otro
    XY, apilado arriba de otra torre, u otro pallet). Así es como una SKU
    puede terminar ocupando el aire que dejó una torre más corta de otra
    SKU, en vez de que ese aire quede inutilizable.

    [V-AUTO-CONSOLIDADO] `concentrar_sku=False` (default, sin cambios de
    comportamiento frente a antes de este parámetro): cada colocación busca
    el mejor ajuste entre TODOS los pallets activos, sin memoria de dónde
    fue la colocación anterior del mismo SKU -por eso un SKU puede terminar
    repartido en más pallets de los que necesita (ver PATCH_LOG.md, caso
    real "KR Cola Negra" en SJ87: 4 pallets para 60 cajas). `True`: antes de
    buscar entre TODOS los pallets, intenta agotar primero el ÚLTIMO pallet
    donde se colocó este mismo SKU -solo cae al best-fit general si ese
    pallet ya no tiene lugar para nada más de este SKU. Nunca abre un
    pallet nuevo antes de tiempo por esto: sigue siendo el mismo último
    recurso de siempre.

    Reglas (DOCUMENTACION_LOGICA_V5.md sección 9-10):
    - base 120x100, torres de altura independiente, ahora también con
      base Z independiente (apiladas unas sobre otras si hace falta);
    - <= ALTURA_MAX_OBSERVADA (215cm) de producto total por pallet;
    - mismo CD (df_cd ya viene filtrado a un solo CD -no se valida acá);
    - orientación XY válida (ambas, `generar_torres_candidatas`);
    - demanda exacta -se agota `Cajas_Remanente` por completo o el SKU queda
      marcado en `metadata["sin_colocar"]` del último pallet (nunca se pierde
      en silencio).
    """
    contador = contador if contador is not None else [0]
    candidatas = generar_torres_candidatas(df_cd, config.ALTURA_PRODUCTO_MAX)
    if not candidatas:
        return list(pallets_semilla or [])

    por_sku: dict[str, list[TorreCandidate]] = {}
    pendientes: dict[str, int] = {}
    for c in candidatas:
        por_sku.setdefault(c.sku, []).append(c)
        pendientes[c.sku] = c.cantidad_disponible

    if orden_skus is not None:
        # Puede traer SKUs que no generaron candidatas (sin geometría) -se
        # filtran; y debe cubrir TODOS los pendientes (si al caller se le
        # escapó alguno, se agrega al final en vez de perder demanda).
        orden_skus = [s for s in orden_skus if s in pendientes]
        faltantes = [s for s in pendientes if s not in orden_skus]
        orden_skus = orden_skus + faltantes
    else:
        # [P5 básico] Un solo orden fijo: mayor volumen de torre potencial
        # primero (footprint x altura máxima x cuántas caben) -heurística
        # VOLUMEN_DESC, la primera de las 7 que P7 (multi-start) compara.
        def _volumen_potencial(sku: str) -> float:
            c = por_sku[sku][0]
            return c.largo * c.ancho * min(c.max_cajas_verticales, c.cantidad_disponible) * c.alto_caja

        orden_skus = sorted(pendientes.keys(), key=lambda s: -_volumen_potencial(s))

    pallets_activos: list[_PalletEnConstruccion] = [_PalletEnConstruccion(pallet=p) for p in (pallets_semilla or [])]
    sin_colocar: dict[str, int] = {}
    ultimo_pallet_por_sku: dict[str, _PalletEnConstruccion] = {}

    for sku in orden_skus:
        guard = 0
        while pendientes[sku] > 0:
            guard += 1
            if guard > 10_000:
                sin_colocar[sku] = sin_colocar.get(sku, 0) + pendientes[sku]
                break

            mejor = None
            if concentrar_sku:
                ultimo = ultimo_pallet_por_sku.get(sku)
                if ultimo is not None and ultimo in pallets_activos:
                    mejor = _buscar_mejor([ultimo], por_sku[sku], pendientes[sku])
            if mejor is None:
                mejor = _buscar_mejor(pallets_activos, por_sku[sku], pendientes[sku])

            if mejor is not None:
                _, pc, cand, idx_libre, cantidad_colocable = mejor
                pc.colocar(cand, cantidad_colocable, idx_libre)
                pendientes[sku] -= cantidad_colocable
                if concentrar_sku:
                    ultimo_pallet_por_sku[sku] = pc
                continue

            # Ningún pallet abierto sirve -abrir uno nuevo. Si ni un pallet
            # VACÍO puede recibir ninguna orientación de este SKU, la
            # geometría misma es inviable (caja más grande que el pallet) -no
            # debería pasar (validacion.py ya filtra eso), pero no se
            # descarta demanda en silencio: se marca `sin_colocar`.
            contador[0] += 1
            nuevo_pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
            nuevo_pc = _PalletEnConstruccion(pallet=nuevo_pallet)
            colocado_en_nuevo = False
            for cand in por_sku[sku]:
                tope = min(cand.max_cajas_verticales, pendientes[sku])
                if tope <= 0:
                    continue
                ajuste = nuevo_pc.mejor_ajuste(cand, tope)
                if ajuste is None:
                    continue
                idx_libre, _sobra, cantidad_colocable = ajuste
                nuevo_pc.colocar(cand, cantidad_colocable, idx_libre)
                pendientes[sku] -= cantidad_colocable
                colocado_en_nuevo = True
                if concentrar_sku:
                    ultimo_pallet_por_sku[sku] = nuevo_pc
                break

            if not colocado_en_nuevo:
                sin_colocar[sku] = sin_colocar.get(sku, 0) + pendientes[sku]
                pendientes[sku] = 0
                continue

            pallets_activos.append(nuevo_pc)

    resultado = [pc.pallet for pc in pallets_activos]
    if sin_colocar and resultado:
        resultado[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        # no había ni un pallet -crear uno vacío solo para no perder el aviso
        contador[0] += 1
        vacio = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar})
        resultado.append(vacio)

    return resultado
