"""[SKU_BLOQUE] Lógica de armado por CAMAS -corrección explícita del usuario
sobre cómo se arma un pallet físicamente:

"nunca pero nunca se empieza haciendo columnas, siempre primero se van
llenando las filas de abajo hacia arriba construyendo un bloque de
120x100" -y por capa, "no puede elegir una sola orientación [nueva, propia],
tiene que buscar la orientación adecuada para cumplir con las cajas por
cama del maestro, y así cumplirla hasta lo que diga la demanda sin
sobrepasar el máximo de cajas por PH que dice el maestro". Y entre SKUs
distintos de la misma cama: "no puede haber huecos tan grandes entre
ellos, máximo huecos que te permitan poner una cama encima y que sea
estable".

Arquitectura:
1. El pallet se arma CAMA POR CAMA, de piso a techo -nunca se abre una
   columna aislada de un SKU que deje aire debajo suyo para otro SKU
   después. Cada cama tiene una altura fija (la del SKU "ancla" que la
   abre) y se completa ANTES de pasar a la siguiente.
2. Dentro de una cama: el SKU ancla (el de más demanda pendiente entre los
   que quepan en lo que resta de altura del pallet) llena la huella
   120x100 fila por fila -no cualquier orden, una sola orientación fija
   por cama (nunca mezclada, eso fragmentaba el espacio en versiones
   anteriores). El objetivo de cuántas cajas entran por cama NO lo inventa
   el packer: es `Cajas_Cama_Efectivo` (`derivados.py`), que ya reconcilia
   el "Cajas por cama" real del Maestro contra la geometría UMA -acá solo
   se USA ese número, no se recalcula.
3. Si el ancla no llena toda la huella de la cama, el resto de esa MISMA
   cama se completa con otros SKUs pendientes cuya altura de caja sea
   compatible (dentro de `TOLERANCIA_HUECO_CAMA_CM`) -para que el hueco que
   quede sea chico y la cama siga siendo una base estable para la próxima.
4. Reusa el motor 3D de `packing_columnar.py` (`_PalletEnConstruccion`,
   MaxRects) -lo que cambia es que cada cama se arma con un cuboide libre
   inicial de profundidad Z = SOLO la altura de esa cama (no el presupuesto
   de altura completo del pallet), así el mismo best-fit que antes producía
   torres de piso a techo ahora llena en el plano XY antes de subir.
"""
import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import _altura_presupuesto, _CuboidLibre, _PalletEnConstruccion
from src.torres import TorreCandidate, generar_torres_candidatas

TOL = 1e-6

# [sección 3] Cuánta diferencia de altura se tolera entre el SKU ancla de
# una cama y otro SKU que se agrega a la MISMA cama -valor heredado de la
# calibración V4 contra datos reales (Cubicaje18.07.2026.xlsx: con 3cm el
# motor daba 91% de pallets parciales, con 8cm 76%, retorno decreciente
# después). Punto de partida razonable, no un número confirmado formalmente
# con operación -ajustar acá si hace falta.
TOLERANCIA_HUECO_CAMA_CM = 8.0


def _mejor_ajuste_para_sku(
    pc: _PalletEnConstruccion, candidatas: list[TorreCandidate], cantidad: int, permitir_parcial: bool
) -> tuple[TorreCandidate, int, float, int] | None:
    """Prueba todas las orientaciones de un SKU contra UN pallet en
    construcción. Devuelve (candidata, idx_libre, sobra, cantidad_colocable)
    o None si ninguna orientación entra."""
    mejor = None
    for cand in candidatas:
        tope = min(cand.max_cajas_verticales, cantidad)
        if tope <= 0:
            continue
        ajuste = pc.mejor_ajuste(cand, tope, permitir_parcial=permitir_parcial)
        if ajuste is None:
            continue
        idx_libre, sobra, cantidad_colocable = ajuste
        if mejor is None or sobra < mejor[2]:
            mejor = (cand, idx_libre, sobra, cantidad_colocable)
    return mejor


def _mejor_orientacion_grilla(candidatas: list[TorreCandidate]) -> TorreCandidate:
    """Fija UNA sola orientación para toda una cama (base estricta
    120x100) -nunca mezclada dentro de la misma cama, eso fragmentaba el
    espacio de formas que después ninguna orientación podía volver a
    aprovechar bien. Base estricta (no la extendida con sobresaliente):
    una cama puede terminar compartida por varios SKUs, y mezclar
    sobresalientes de SKUs distintos en direcciones distintas da un
    perfil irregular -ver PATCH_LOG.md, sección sobresaliente."""
    def _capacidad_grilla(c: TorreCandidate) -> int:
        cols = int(config.PALLET_LARGO // c.largo)
        filas = int(config.PALLET_ANCHO // c.ancho)
        return cols * filas

    return max(candidatas, key=_capacidad_grilla)


def _armar_cama(
    pallet: PalletV5,
    z: float,
    altura_cama: float,
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    ancla_sku: str,
) -> bool:
    """[sección 2-3] Arma UNA cama a la altura `z`, con profundidad fija
    `altura_cama` -el cuboide libre inicial de este `_PalletEnConstruccion`
    SOLO tiene esa profundidad, así que ninguna torre puede crecer más
    alto que esta cama (evita el bug de "columnas de piso a techo").
    Devuelve True si se colocó algo."""
    objetivo_ancla = min(pendientes[ancla_sku], capacidad_cama_por_sku.get(ancla_sku, pendientes[ancla_sku]))

    # [simplificado] Base ESTRICTA (120x100) para todas las camas -el
    # margen de sobresaliente por SKU dominante se maneja aparte (ver
    # PATCH_LOG.md); acá el foco es no dejar huecos grandes entre SKUs
    # que comparten cama, así que se prioriza dejar la huella exacta
    # disponible para que otros SKUs puedan sumarse de verdad.
    cand_ancla = _mejor_orientacion_grilla(por_sku[ancla_sku])

    libre_inicial = _CuboidLibre(0.0, 0.0, z, config.PALLET_LARGO, config.PALLET_ANCHO, altura_cama)
    pc = _PalletEnConstruccion(pallet=pallet, libres=[libre_inicial])

    colocado_total = False
    restante = objetivo_ancla
    guard = 0
    while restante > 0:
        guard += 1
        if guard > 1000:
            break
        ajuste = _mejor_ajuste_para_sku(pc, [cand_ancla], restante, permitir_parcial=True)
        if ajuste is None:
            break
        cand, idx_libre, _sobra, cantidad_colocable = ajuste
        pc.colocar(cand, cantidad_colocable, idx_libre)
        restante -= cantidad_colocable
        colocado_total = True
    pendientes[ancla_sku] -= objetivo_ancla - restante

    # [sección 3] Rellenar lo que sobra de ESTA misma cama con otros SKUs
    # pendientes cuya altura de caja sea compatible -huecos chicos, cama
    # estable para la que sigue. La tolerancia es SIMÉTRICA: un SKU más
    # alto que la cama no entra físicamente (eso ya lo filtra el ajuste de
    # abajo), pero uno MUCHO más bajo que la cama SÍ entraría físicamente
    # -y dejaría exactamente el hueco grande que se quiere evitar. Por eso
    # se descarta también si la diferencia hacia abajo supera la
    # tolerancia, no solo hacia arriba.
    progreso = True
    while progreso:
        progreso = False
        candidatos = sorted(
            (
                s
                for s, v in pendientes.items()
                if v > 0
                and s != ancla_sku
                and abs(por_sku[s][0].alto_caja - altura_cama) <= TOLERANCIA_HUECO_CAMA_CM + TOL
            ),
            key=lambda s: abs(por_sku[s][0].alto_caja - altura_cama),
        )
        for sku in candidatos:
            objetivo = min(pendientes[sku], capacidad_cama_por_sku.get(sku, pendientes[sku]))
            cand_sku = _mejor_orientacion_grilla(por_sku[sku])
            ajuste = _mejor_ajuste_para_sku(pc, [cand_sku], objetivo, permitir_parcial=True)
            if ajuste is None:
                continue
            cand, idx_libre, _sobra, cantidad_colocable = ajuste
            if cantidad_colocable <= 0:
                continue
            pc.colocar(cand, cantidad_colocable, idx_libre)
            pendientes[sku] -= cantidad_colocable
            colocado_total = True
            progreso = True
            break

    return colocado_total


def armar_pallets_bloques(df_cd: pd.DataFrame, cd: str, contador: list[int] | None = None) -> list[PalletV5]:
    """[V-SKU_BLOQUE, camas] Punto de entrada. `df_cd` debe traer demanda
    pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría
    efectiva reconciliada y, si está disponible, `Cajas_Cama_Efectivo`
    (derivados.py) -sin esa columna, una cama no tiene tope propio más que
    la huella/orientación elegida."""
    contador = contador if contador is not None else [0]
    candidatas = generar_torres_candidatas(df_cd, config.ALTURA_PRODUCTO_MAX)
    if not candidatas:
        return []

    por_sku: dict[str, list[TorreCandidate]] = {}
    for c in candidatas:
        por_sku.setdefault(c.sku, []).append(c)

    col_cantidad = "Cajas_Remanente" if "Cajas_Remanente" in df_cd.columns else "Cajas_Teoricas_Redondeadas"
    pendientes: dict[str, int] = {}
    for _, fila in df_cd.iterrows():
        sku = fila["SKU"]
        if sku not in por_sku:
            continue
        cant = int(fila[col_cantidad]) if pd.notna(fila[col_cantidad]) else 0
        pendientes[sku] = pendientes.get(sku, 0) + cant

    capacidad_cama_por_sku: dict[str, int] = {}
    if "Cajas_Cama_Efectivo" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            cap = fila.get("Cajas_Cama_Efectivo")
            if pd.notna(cap) and cap > 0:
                capacidad_cama_por_sku[sku] = int(cap)

    presupuesto = _altura_presupuesto()
    pallets: list[PalletV5] = []
    sin_colocar: dict[str, int] = {}

    while any(v > 0 for v in pendientes.values()):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        z = 0.0
        avanzo_en_este_pallet = False

        while z < presupuesto - TOL:
            activos = [s for s in pendientes if pendientes[s] > 0]
            if not activos:
                break
            # [sección 2] El ancla de esta cama: la mayor demanda pendiente
            # entre los SKUs cuya altura de caja todavía entra en lo que
            # resta del pallet.
            candidatos_ancla = [s for s in activos if por_sku[s][0].alto_caja <= presupuesto - z + TOL]
            if not candidatos_ancla:
                break  # nada más cabe en la altura que queda de este pallet
            ancla_sku = max(candidatos_ancla, key=lambda s: pendientes[s])
            altura_cama = por_sku[ancla_sku][0].alto_caja

            coloco = _armar_cama(pallet, z, altura_cama, pendientes, por_sku, capacidad_cama_por_sku, ancla_sku)
            if not coloco:
                # el ancla no entró ni una caja -geometría inviable para
                # este SKU en este pallet, no reintentar en loop infinito.
                sin_colocar[ancla_sku] = sin_colocar.get(ancla_sku, 0) + pendientes[ancla_sku]
                pendientes[ancla_sku] = 0
                continue
            avanzo_en_este_pallet = True
            z += altura_cama

        if not avanzo_en_este_pallet:
            break  # ningún SKU pendiente entra en un pallet fresco -evitar loop infinito
        pallets.append(pallet)

    if sin_colocar and pallets:
        pallets[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        pallets.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return pallets
