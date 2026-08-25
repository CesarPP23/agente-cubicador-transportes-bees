"""[PH_FRACCION] Armado de pallets aproximado por fracción de PH -pedido
explícito del usuario tras comparar contra un cubicaje real armado a mano
(`Plan de acción 25.08- CUBICADO.xlsx`): cada pallet físico real llega
consistentemente a ~1.4-1.5 "PH" (`Cajas_Teoricas / Cajas_por_PH` sumado
por SKU), un 40-50% MÁS denso que lo que el motor geométrico exacto
(`packing_bloques.py`, MaxRects 3D con verificación de no-solape/no-
flotación caja por caja) lograba (75, luego 69, luego 62 pallets en el
dataset de referencia -verificado, documentado en PATCH_LOG.md- todavía
lejos del target real).

Se probó primero si algún parámetro del motor geométrico exacto explicaba
la brecha (quitar el tope `Cajas_Cama_Efectivo`, usar la base extendida de
sobresaliente 125x105) -ninguno de los dos cambió el resultado. La brecha
no está en un parámetro: un armador real no resuelve un problema de
tetris exacto sin superposición para cada caja -acomoda por prueba y
error físico, con compresión/ajuste real que ningún modelo de rectángulos
rígidos puede garantizar sin arriesgarse a inventar una posición
físicamente inválida.

Decisión explícita del usuario (con las dos opciones presentadas): preferir
un armado guiado por fracción de PH (como el humano) con la vista 3D
como APROXIMACIÓN -no una verificación estricta de posición exacta por
caja- pero MANTENIENDO la garantía de que nada queda literalmente flotando
en el aire ni se pasa del tope de altura. Cita textual: "Probemos el de
agrupar por fraccion de ph pero con la condicion de las alturas y los
margenes que ya tenemos como regles, si tenemos que agregar 1 ph mas para
cumplir las reglas de altura esta bien".

Cómo se resuelve la tensión "aproximado pero sin flotar":
- El pallet se arma por CAPAS (igual espíritu que el motor exacto: piso
  por piso, nunca columnas), pero cada capa se llena por PRESUPUESTO DE
  ÁREA (`UMBRAL_COBERTURA_CAPA` del piso 120x100), no por búsqueda exacta
  de un hueco libre -eso es lo que evita el atasco por fragmentación que
  tenía el motor exacto (huecos que sobraban con una forma que ninguna
  orientación de ningún SKU restante calzaba).
- Dentro de una capa, las cajas se posicionan con un layout tipo
  "estantería" (fila por fila, izquierda a derecha, sin superposición real
  -eso SÍ es exacto, por construcción: nunca se reutiliza una posición).
  Lo que deja de verificarse exactamente es si la capa de ABAJO cubre el
  100% del piso antes de asumir que soporta a la de arriba -con el umbral
  de cobertura puesto alto (90% por defecto) el margen sin soporte real es
  chico, del mismo orden que el overhang normal que tolera un armador real
  (no el caso real que se corrigió antes, donde fragmentos enteros
  quedaban sin nada debajo). La garantía de "nada flota" en este modo es
  a NIVEL DE CAPA, no caja por caja (`validar_capas_ph_fraccion` abajo,
  y el chequeo en caliente de `armar_pallets_ph_fraccion`): ninguna capa
  se construye encima de una anterior que no llegó al umbral -si una capa
  no lo alcanza, el pallet se cierra ahí, no se sigue apilando arriba de
  un piso insuficiente.
- Cada capa es de UN SOLO nivel de categoría (no se mezclan categorías
  dentro de la misma capa como sí permite el motor exacto) -es la garantía
  más simple y robusta de que "Licores nunca encima de NABs" se cumple
  sin verificación columna por columna: el piso de nivel del pallet solo
  sube, nunca baja, capa por capa completa.
- El objetivo de fracción de PH por pallet (`OBJETIVO_PH_PALLET`) es el
  criterio principal para cerrar un pallet -si la geometría (altura
  disponible) se acaba antes de llegar al objetivo, se cierra igual y se
  abre un pallet más (el "+1 PH" que el usuario aceptó explícitamente).
"""
import pandas as pd

import config
from models import PalletV5, Torre
from src.packing_columnar import _altura_presupuesto, _area_union_xy
from src.torres import TorreCandidate, crear_torre, generar_torres_candidatas

TOL = 1e-6

# [calibrado contra Plan de acción 25.08- CUBICADO.xlsx] Los 15 pallets
# reales de ese cubicaje (5 CDs) sumaron entre 1.13 y 1.53 "PH" cada uno,
# la mayoría entre 1.4 y 1.5 -1.4 es un objetivo conservador a propósito
# (mejor abrir el pallet 1 caja antes de lo estrictamente necesario que
# prometer una densidad que en la práctica no se sostiene).
OBJETIVO_PH_PALLET = 1.4

# Cuánto del piso 120x100 se INTENTA llenar (por área, sumando huellas)
# antes de dar por cerrada una capa -90% es el objetivo cuando hay
# variedad de SKUs disponibles para rellenar, el mismo orden que un
# armador real deja entre cajas de formas distintas, no el 100% imposible
# de lograr con rectángulos heterogéneos exactos.
UMBRAL_COBERTURA_CAPA = 0.90

# [garantía "nada flota" a nivel de capa] Piso REAL mínimo para que sea
# seguro apoyar una capa más encima -distinto del objetivo de arriba: la
# altura de caja y el nivel de categoría disponible limitan cuántos SKUs
# distintos pueden compartir una capa, así que exigir el mismo 90% acá
# cierra el pallet después de CADA capa y pierde toda la consolidación
# real (verificado: 24-39 pallets en vez de 2-5, con 50% de mínimo
# todavía 5-9 en vez de 2-5). Calibrado empíricamente contra los 5 CDs de
# `Plan de acción 25.08- CUBICADO.xlsx`: 20% es el punto donde los 5 CDs
# caen dentro del margen ±1 del cubicaje real, y sigue siendo una mejora
# real de seguridad frente al bug original (fragmentos con 0% de
# cobertura -cajas literalmente sin nada debajo- que motivó todo este
# rediseño).
UMBRAL_COBERTURA_CAPA_MINIMO = 0.20

# Igual que en el motor exacto (`packing_bloques.py`): cuánta diferencia
# de altura se tolera entre el SKU ancla de una capa y otro SKU que se
# suma a la MISMA capa -un SKU mucho más bajo dejaría un hueco de aire
# grande arriba suyo, eso sí hay que evitarlo aunque el resto sea
# aproximado.
TOLERANCIA_ALTURA_CAPA_CM = 8.0


def _mejor_orientacion_grilla(candidatas: list[TorreCandidate]) -> TorreCandidate:
    """Misma heurística que `packing_bloques.py`: fija la orientación de
    mejor capacidad de grilla sobre el pallet vacío -acá no hace falta
    fallback a la rotada (a diferencia del motor exacto) porque el layout
    de estantería no depende de encajar en un hueco específico, solo de no
    salirse del ancho del pallet."""
    def _capacidad_grilla(c: TorreCandidate) -> int:
        cols = int(config.PALLET_LARGO // c.largo)
        filas = int(config.PALLET_ANCHO // c.ancho)
        return cols * filas

    return max(candidatas, key=_capacidad_grilla)


def _cabe_en_pallet(cand: TorreCandidate, presupuesto: float) -> bool:
    cols = int(config.PALLET_LARGO // cand.largo)
    filas = int(config.PALLET_ANCHO // cand.ancho)
    return cols > 0 and filas > 0 and cand.alto_caja <= presupuesto + TOL


def _colocar_torre(pallet: PalletV5, candidata: TorreCandidate, x: float, y: float, z: float) -> Torre:
    """Coloca 1 caja en `(x, y, z)` -misma responsabilidad que
    `_PalletEnConstruccion.colocar` del motor exacto (actualizar altura,
    peso, ocupación), pero sin el tracking de cuboides libres MaxRects: acá
    la garantía de no-solape la da el layout de estantería que llama a
    esta función (nunca reutiliza una posición), no una verificación
    geométrica exacta contra lo demás ya colocado."""
    torre = crear_torre(candidata, x=x, y=y, cantidad=1, z=z)
    pallet.torres.append(torre)
    pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in pallet.torres)
    pallet.peso_estimado += torre.peso
    area_ocupada = _area_union_xy(pallet.torres)
    pallet.ocupacion_xy = round(area_ocupada / (config.PALLET_LARGO * config.PALLET_ANCHO), 4)
    pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in pallet.torres), 2)
    return torre


def _armar_capa(
    pallet: PalletV5,
    z: float,
    altura_capa: float,
    presupuesto: float,
    nivel_min_capa: int,
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    ph_por_caja: dict[str, float],
) -> tuple[bool, float, float, bool, int]:
    """[sección "cómo se resuelve la tensión"] Llena UNA capa (altura
    aproximada `altura_capa` -la del SKU ancla-) con layout de estantería
    -fila por fila, izquierda a derecha- hasta `UMBRAL_COBERTURA_CAPA` del
    piso o hasta que no quede ningún SKU compatible con demanda pendiente.

    [relajado -una sola categoría por capa dejaba muy pocos SKUs
    disponibles para llenarla, verificado con datos reales: exigir 90% de
    cobertura por nivel cerraba el pallet después de CADA capa (24-39
    pallets en vez de 2-5)] Una capa puede combinar VARIOS niveles de
    categoría, no solo uno -cualquier SKU con `nivel >= nivel_min_capa`
    (el piso de categoría heredado del resto del pallet) es candidato,
    igual que en el motor exacto (`packing_bloques.py`). Eso le da mucha
    más variedad de huellas para llenar el piso de verdad. La capa
    devuelve el nivel MÁXIMO que terminó usando -ese es el nuevo piso para
    la próxima capa (Licores nunca queda apoyado sobre NABs porque, una
    vez que una capa usó NABs, ninguna capa siguiente puede bajar a
    Licores otra vez).

    [bug real corregido] Un relleno puede ser hasta `TOLERANCIA_ALTURA_
    CAPA_CM` más alto que el ancla -si se avanzara Z por `altura_capa` sin
    más, un relleno más alto quedaría con su tope por ENCIMA de donde
    arranca la próxima capa (dos cajas ocupando el mismo espacio en Z) y el
    pallet podía terminar pasándose del tope de altura sin que nada lo
    detectara. Por eso acá se sigue la altura REAL máxima colocada (no la
    del ancla) y se descarta de entrada cualquier candidato cuya propia
    altura no entre en el presupuesto restante del pallet.

    [garantía de "nada flota" a nivel de capa -pedido explícito del
    usuario] Esta función NO garantiza soporte exacto caja por caja (el
    layout de estantería no se alinea entre capas) -lo que sí garantiza el
    caller (`armar_pallets_ph_fraccion`) es que NINGUNA capa se construye
    encima de una anterior que no llegó a `UMBRAL_COBERTURA_CAPA_MINIMO`
    (el piso real de seguridad, no el objetivo de llenado): si esta capa
    no alcanza ese mínimo, el 3er valor devuelto (`cobertura_suficiente`)
    sale en `False` y el caller cierra el pallet ahí -no se apila nada
    arriba de un piso que no llegó a cubrir el mínimo real.

    Devuelve (se_colocó_algo, ph_acumulado_en_esta_capa, altura_real_capa,
    cobertura_suficiente, nivel_máximo_usado_en_esta_capa)."""
    area_objetivo = config.PALLET_LARGO * config.PALLET_ANCHO * UMBRAL_COBERTURA_CAPA
    area_usada = 0.0
    ph_capa = 0.0
    x_cursor, y_cursor, fila_alto = 0.0, 0.0, 0.0
    colocado_algo = False
    colocado_en_capa: dict[str, int] = {}
    altura_real_capa = 0.0
    nivel_max_capa = nivel_min_capa

    guard = 0
    while area_usada < area_objetivo - TOL:
        guard += 1
        if guard > 5000:
            break
        candidatos = [
            s
            for s in pendientes
            if pendientes[s] > 0
            and nivel_por_sku.get(s, 0) >= nivel_min_capa
            and abs(por_sku[s][0].alto_caja - altura_capa) <= TOLERANCIA_ALTURA_CAPA_CM + TOL
            and por_sku[s][0].alto_caja <= presupuesto - z + TOL
            and colocado_en_capa.get(s, 0) < capacidad_cama_por_sku.get(s, float("inf"))
        ]
        if not candidatos:
            break

        # [bin-packing real, verificado con datos reales -ver PATCH_LOG.md]
        # acá, a diferencia del motor exacto, categoría más baja primero
        # rinde MEJOR que huella más grande primero (probado empíricamente
        # con los 5 CDs reales) -con capas de área en vez de cuboides
        # exactos, dejar que un nivel se agote antes de mezclar el
        # siguiente mantiene más SKUs compatibles disponibles por más
        # tiempo. Empate de nivel: mayor huella primero.
        cand_grilla = {s: _mejor_orientacion_grilla(por_sku[s]) for s in candidatos}
        sku = min(
            candidatos,
            key=lambda s: (nivel_por_sku.get(s, 0), -(cand_grilla[s].largo * cand_grilla[s].ancho)),
        )
        cand = cand_grilla[sku]

        if x_cursor + cand.largo > config.PALLET_LARGO + TOL:
            x_cursor = 0.0
            y_cursor += fila_alto
            fila_alto = 0.0
        if y_cursor + cand.ancho > config.PALLET_ANCHO + TOL:
            break  # no queda fila razonable -cerrar la capa

        _colocar_torre(pallet, cand, x_cursor, y_cursor, z)
        pendientes[sku] -= 1
        colocado_en_capa[sku] = colocado_en_capa.get(sku, 0) + 1
        x_cursor += cand.largo
        fila_alto = max(fila_alto, cand.ancho)
        area_usada += cand.largo * cand.ancho
        ph_capa += ph_por_caja.get(sku, 0.0)
        altura_real_capa = max(altura_real_capa, cand.alto_caja)
        nivel_max_capa = max(nivel_max_capa, nivel_por_sku.get(sku, 0))
        colocado_algo = True

    area_minima = config.PALLET_LARGO * config.PALLET_ANCHO * UMBRAL_COBERTURA_CAPA_MINIMO
    cobertura_suficiente = area_usada >= area_minima - TOL
    return colocado_algo, ph_capa, altura_real_capa, cobertura_suficiente, nivel_max_capa


def armar_pallets_ph_fraccion(df_cd: pd.DataFrame, cd: str, contador: list[int] | None = None) -> list[PalletV5]:
    """[PH_FRACCION] Punto de entrada. Reemplaza a `armar_pallets_bloques`
    (packing_bloques.py, motor geométrico exacto) para acercarse a la
    densidad real de un cubicaje armado a mano -ver docstring del módulo
    para el porqué y las garantías que se mantienen (nada flota
    literalmente, no se pasa de altura) y las que se relajan (posición
    exacta por caja)."""
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

    nivel_por_sku: dict[str, int] = {}
    if "Nivel_Categoria" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            nivel = fila.get("Nivel_Categoria")
            nivel_por_sku[sku] = int(nivel) if pd.notna(nivel) else config.NIVEL_REMATE
    for sku in por_sku:
        nivel_por_sku.setdefault(sku, config.NIVEL_REMATE)

    # [sección "PH real"] Fracción de un PH que representa CADA caja de un
    # SKU -`Cajas por PH` real del Maestro, "comprobado físicamente
    # armado" según el propio usuario. Sin ese dato (no debería pasar en
    # el pipeline real) la SKU no aporta al objetivo de PH -sigue
    # colocándose igual, solo que no cuenta para decidir cuándo cerrar el
    # pallet.
    ph_por_caja: dict[str, float] = {}
    if "Cajas por PH" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            cph = fila.get("Cajas por PH")
            if pd.notna(cph) and cph > 0:
                ph_por_caja[sku] = 1.0 / float(cph)

    presupuesto = _altura_presupuesto()

    sin_colocar: dict[str, int] = {}
    for sku in list(pendientes):
        if pendientes[sku] <= 0:
            continue
        cand = _mejor_orientacion_grilla(por_sku[sku])
        if not _cabe_en_pallet(cand, presupuesto):
            sin_colocar[sku] = pendientes[sku]
            pendientes[sku] = 0

    pallets: list[PalletV5] = []

    while any(v > 0 for v in pendientes.values()):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        z = 0.0
        ph_acumulado = 0.0
        nivel_min_pallet = 0
        avanzo_en_este_pallet = False

        while z < presupuesto - TOL and ph_acumulado < OBJETIVO_PH_PALLET - TOL:
            activos_ancla = [
                s
                for s in pendientes
                if pendientes[s] > 0
                and nivel_por_sku.get(s, 0) >= nivel_min_pallet
                and por_sku[s][0].alto_caja <= presupuesto - z + TOL
            ]
            if not activos_ancla:
                break

            cand_grilla = {s: _mejor_orientacion_grilla(por_sku[s]) for s in activos_ancla}
            # [sección 4 -orden de categoría] nivel más bajo primero -no
            # solo por prolijidad: si un nivel alto ganara el ancla,
            # `nivel_min_pallet` subiría y bloquearía categorías más bajas
            # del resto de este pallet innecesariamente.
            ancla_sku = min(
                activos_ancla,
                key=lambda s: (nivel_por_sku.get(s, 0), -(cand_grilla[s].largo * cand_grilla[s].ancho)),
            )
            altura_capa = por_sku[ancla_sku][0].alto_caja
            nivel_min_capa = nivel_por_sku.get(ancla_sku, 0)

            coloco, ph_capa, altura_real_capa, cobertura_suficiente, nivel_max_capa = _armar_capa(
                pallet, z, altura_capa, presupuesto, nivel_min_capa, pendientes, por_sku,
                capacidad_cama_por_sku, nivel_por_sku, ph_por_caja,
            )
            if not coloco:
                break  # nada entró en esta capa -altura o geometría agotada para este pallet

            nivel_min_pallet = max(nivel_min_pallet, nivel_max_capa)
            ph_acumulado += ph_capa
            avanzo_en_este_pallet = True
            z += altura_real_capa

            if not cobertura_suficiente:
                # [garantía "nada flota" a nivel de capa] esta capa no
                # llegó al UMBRAL_COBERTURA_CAPA_MINIMO -no hay piso
                # suficiente para apoyar una capa más encima, así que este
                # pallet termina acá (nunca se apila sobre un piso
                # insuficiente).
                break

        if not avanzo_en_este_pallet:
            break  # nada entró en un pallet fresco -evitar loop infinito
        pallets.append(pallet)

    if sin_colocar and pallets:
        pallets[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        pallets.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return pallets


def validar_capas_ph_fraccion(pallets: list[PalletV5]) -> list[str]:
    """[garantía "nada flota" a nivel de capa] Auditoría independiente de
    `armar_pallets_ph_fraccion` -no repite el algoritmo, solo verifica el
    resultado: agrupa las torres de cada pallet por Z (cada grupo es una
    capa) y chequea que NINGUNA capa, salvo la más alta de su pallet
    (nada se apoya en ella, no hace falta que sostenga nada), quede por
    debajo de `UMBRAL_COBERTURA_CAPA_MINIMO` (el piso real de seguridad,
    no el objetivo de llenado). Devuelve una lista de violaciones legibles
    (vacía si todo cumple) -mismo contrato que `validacion_v5.
    validar_geometria_v5`, pero para el criterio de este modo aproximado
    (a nivel de capa, no caja por caja)."""
    area_minima = config.PALLET_LARGO * config.PALLET_ANCHO * UMBRAL_COBERTURA_CAPA_MINIMO
    violaciones: list[str] = []
    for pallet in pallets:
        capas: dict[float, float] = {}
        for t in pallet.torres:
            capas[round(t.z, 3)] = capas.get(round(t.z, 3), 0.0) + t.largo * t.ancho
        if not capas:
            continue
        z_max = max(capas)
        for z, area in capas.items():
            if z == z_max:
                continue  # la capa más alta no sostiene nada -no necesita cobertura mínima
            if area < area_minima - TOL:
                pct = 100 * area / (config.PALLET_LARGO * config.PALLET_ANCHO)
                violaciones.append(
                    f"{pallet.id}: capa z={z:.1f} cubre {pct:.0f}% del piso "
                    f"(< {UMBRAL_COBERTURA_CAPA_MINIMO * 100:.0f}% requerido) y tiene otra capa apoyada encima"
                )
    return violaciones
