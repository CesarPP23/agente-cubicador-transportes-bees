"""[SKU_BLOQUE] Lógica de armado nueva, instrucción explícita del usuario:

"si me piden 100 cajas de kr negra y el maestro me dice que 1 pallet es
150 cajas entonces yo puedo poner en un solo pallet las 100 cajas y la
altura restante que me queda para cumplir con los parámetros ya
establecidos busco otros skus que también consolidados me ayuden a llegar
a la altura óptima, si ya no encuentro consolidados entonces busco
remanentes"

Cada SKU es un BLOQUE indivisible mientras sea posible:
1. Si la demanda total de un SKU en un CD supera lo que entra en UN pallet
   (`Cajas por PH`, el mismo dato que usa `pallets_homogeneos.py`), se
   extraen pallets 100% dedicados hasta dejar como mucho un resto < 1
   pallet. Ese resto (o la demanda entera, si ya cabía en 1 pallet) es el
   "bloque" del SKU -nunca se parte a propósito.
2. Para armar un pallet: se elige el bloque más grande como ancla, se
   coloca ENTERO, y se buscan otros bloques ENTEROS (de otros SKUs) que
   quepan -todo o nada- hasta que no entre ninguno más. Recién cuando ya
   no hay ningún bloque entero que quepa, se PARTE uno (remanente) para
   terminar de llenar la altura -último recurso, no la regla general.

Reusa el mecanismo de colocación 3D de `packing_columnar.py`
(`_PalletEnConstruccion`, MaxRects) -lo que cambia es el ORDEN y el
criterio de qué se coloca entero vs qué se parte, no la geometría."""
import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate, generar_torres_candidatas


def _mejor_ajuste_para_sku(
    pc: _PalletEnConstruccion, candidatas: list[TorreCandidate], cantidad: int, permitir_parcial: bool
) -> tuple[TorreCandidate, int, float, int] | None:
    """Prueba todas las orientaciones de un SKU contra UN pallet en
    construcción. Devuelve (candidata, idx_libre, sobra, cantidad_colocable)
    o None si ninguna orientación entra (completa, si permitir_parcial es
    False; al menos parcial, si es True)."""
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


def _colocar_bloque_completo(
    pc: _PalletEnConstruccion, sku: str, cantidad: int, por_sku: dict[str, list[TorreCandidate]]
) -> bool:
    """Coloca TODO `cantidad` de este SKU en `pc`, usando tantas torres
    (columnas XY distintas dentro del MISMO pallet) como haga falta -un
    footprint chico puede necesitar varias columnas side-by-side para un
    bloque grande, eso no es "repartir en varios pallets", sigue siendo
    UN pallet. Atómico: si no logra colocar el bloque COMPLETO, hace
    rollback exacto (no deja nada a medias) y devuelve False -nunca se
    permite dejar "una parte sí, una parte no" de un bloque que se
    supone entero."""
    snap_torres = list(pc.pallet.torres)
    snap_libres = list(pc.libres)
    snap_altura = pc.pallet.altura_final
    snap_peso = pc.pallet.peso_estimado
    snap_ocup = pc.pallet.ocupacion_xy
    snap_vol = pc.pallet.volumen_utilizado

    restante = cantidad
    guard = 0
    while restante > 0:
        guard += 1
        if guard > 1000:
            break
        ajuste = _mejor_ajuste_para_sku(pc, por_sku[sku], restante, permitir_parcial=True)
        if ajuste is None:
            break
        cand, idx_libre, _sobra, cantidad_colocable = ajuste
        pc.colocar(cand, cantidad_colocable, idx_libre)
        restante -= cantidad_colocable

    if restante > 0:
        pc.pallet.torres = snap_torres
        pc.libres = snap_libres
        pc.pallet.altura_final = snap_altura
        pc.pallet.peso_estimado = snap_peso
        pc.pallet.ocupacion_xy = snap_ocup
        pc.pallet.volumen_utilizado = snap_vol
        return False
    return True


def _altura_potencial(sku: str, cantidad: int, por_sku: dict[str, list[TorreCandidate]]) -> float:
    """Proxy determinístico para ordenar bloques -altura si se apilara en
    UNA sola columna (la más alta posible, sin repartir en huella). No hace
    falta que sea exacta, solo consistente para decidir qué bloque probar
    primero (más grande primero)."""
    alto_caja = por_sku[sku][0].alto_caja
    return cantidad * alto_caja


def _dedicar_por_sku(
    df_cd: pd.DataFrame, cd: str, contador: list[int]
) -> tuple[list[PalletV5], dict[str, int], dict[str, list[TorreCandidate]]]:
    """[sección 1] Por SKU: si la demanda pasa la capacidad de un pallet
    completo (`Cajas por PH`), arma tantos pallets 100% dedicados como
    quepan -reusa el mecanismo 3D real (no un cálculo aparte) para que la
    geometría/orientación quede igual de correcta que en cualquier otro
    pallet. Devuelve los dedicados, el bloque restante por SKU (>0 solo
    donde queda algo) y las candidatas por SKU (para no regenerarlas)."""
    candidatas = generar_torres_candidatas(df_cd, config.ALTURA_PRODUCTO_MAX)
    por_sku: dict[str, list[TorreCandidate]] = {}
    for c in candidatas:
        por_sku.setdefault(c.sku, []).append(c)

    col_cantidad = "Cajas_Remanente" if "Cajas_Remanente" in df_cd.columns else "Cajas_Teoricas_Redondeadas"
    demanda_por_sku: dict[str, int] = {}
    for _, fila in df_cd.iterrows():
        sku = fila["SKU"]
        if sku not in por_sku:
            continue
        cant = int(fila[col_cantidad]) if pd.notna(fila[col_cantidad]) else 0
        demanda_por_sku[sku] = demanda_por_sku.get(sku, 0) + cant

    capacidad_por_sku: dict[str, int] = {}
    if "Cajas por PH" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            cap = fila.get("Cajas por PH")
            capacidad_por_sku[sku] = int(cap) if pd.notna(cap) and cap > 0 else 0

    dedicados: list[PalletV5] = []
    bloques: dict[str, int] = {}

    for sku, demanda in demanda_por_sku.items():
        if demanda <= 0:
            continue
        capacidad = capacidad_por_sku.get(sku, 0)
        if capacidad <= 0:
            # Sin "Cajas por PH" confiable -todo el SKU es un único bloque,
            # el packer decide si cabe entero o no (nunca se pierde demanda).
            bloques[sku] = demanda
            continue

        pallets_completos = demanda // capacidad
        resto = demanda - pallets_completos * capacidad

        for _ in range(int(pallets_completos)):
            contador[0] += 1
            pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
            pc = _PalletEnConstruccion(pallet=pallet)
            restante = capacidad
            guard = 0
            while restante > 0:
                guard += 1
                if guard > 1000:
                    break
                mejor = _mejor_ajuste_para_sku(pc, por_sku[sku], restante, permitir_parcial=True)
                if mejor is None:
                    break
                cand, idx_libre, _sobra, cantidad_colocable = mejor
                pc.colocar(cand, cantidad_colocable, idx_libre)
                restante -= cantidad_colocable
            dedicados.append(pallet)

        if resto > 0:
            bloques[sku] = int(resto)

    return dedicados, bloques, por_sku


def armar_pallets_bloques(df_cd: pd.DataFrame, cd: str, contador: list[int] | None = None) -> list[PalletV5]:
    """[V-SKU_BLOQUE] Punto de entrada. `df_cd` debe traer demanda pendiente
    (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría efectiva
    reconciliada y `Cajas por PH` (de Maestro) -sin esta última columna, un
    SKU nunca se "dedica" de antemano, pasa entero como bloque único."""
    contador = contador if contador is not None else [0]
    dedicados, pendientes, por_sku = _dedicar_por_sku(df_cd, cd, contador)
    if not por_sku:
        return dedicados

    resultado: list[PalletV5] = list(dedicados)
    sin_colocar: dict[str, int] = {}

    while any(v > 0 for v in pendientes.values()):
        activos = sorted(
            (s for s, v in pendientes.items() if v > 0),
            key=lambda s: -_altura_potencial(s, pendientes[s], por_sku),
        )
        ancla_sku = activos[0]

        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        pc = _PalletEnConstruccion(pallet=pallet)

        # [sección 2] El ancla se coloca ENTERA -por construcción, un
        # bloque nunca supera la capacidad de un pallet fresco (viene de
        # `_dedicar_por_sku`, que ya usa esa misma capacidad como tope).
        # Puede necesitar varias columnas (torres) side-by-side si el
        # footprint es chico frente a la cantidad -`_colocar_bloque_completo`
        # ya lo resuelve, atómico.
        if not _colocar_bloque_completo(pc, ancla_sku, pendientes[ancla_sku], por_sku):
            # No debería pasar (geometría inviable ya la filtra validacion.py
            # antes de llegar acá) -pero no se pierde demanda en silencio.
            sin_colocar[ancla_sku] = sin_colocar.get(ancla_sku, 0) + pendientes[ancla_sku]
            pendientes[ancla_sku] = 0
            continue
        pendientes[ancla_sku] = 0

        # Otros bloques ENTEROS, más grande primero, todo-o-nada.
        progreso = True
        while progreso:
            progreso = False
            candidatos = sorted(
                (s for s, v in pendientes.items() if v > 0),
                key=lambda s: -_altura_potencial(s, pendientes[s], por_sku),
            )
            for sku in candidatos:
                if _colocar_bloque_completo(pc, sku, pendientes[sku], por_sku):
                    pendientes[sku] = 0
                    progreso = True
                    break

        # [último recurso] Ya no entra ningún bloque entero -partir UNO
        # (el más grande restante que al menos entre parcial) para
        # terminar de llenar la altura de ESTE pallet.
        candidatos = sorted(
            (s for s, v in pendientes.items() if v > 0),
            key=lambda s: -_altura_potencial(s, pendientes[s], por_sku),
        )
        for sku in candidatos:
            ajuste = _mejor_ajuste_para_sku(pc, por_sku[sku], pendientes[sku], permitir_parcial=True)
            if ajuste is None:
                continue
            cand, idx_libre, _sobra, cantidad_colocable = ajuste
            if cantidad_colocable <= 0:
                continue
            pc.colocar(cand, cantidad_colocable, idx_libre)
            pendientes[sku] -= cantidad_colocable
            break  # un solo bloque partido por pallet -no volver a fragmentar de más

        resultado.append(pallet)

    if sin_colocar and resultado:
        resultado[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        resultado.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return resultado
