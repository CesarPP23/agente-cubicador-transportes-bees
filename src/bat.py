"""[V3 / sección 9, 11] BAT: Cigarros y vapes.

Nunca se despachan por caja completa (96% de sus líneas de demanda son
fraccionarias). El personal los consolida en una caja física FIJA
(52.5x34x49cm, hasta 1000 unidades, ver config.CAJA_BAT_*) separada del
cubicaje normal, y la coloca como remate encima de un pallet "host" ya
armado -después de que todos los pallets normales (no-BAT) están completos,
no durante su armado.

Reemplaza la reserva global de altura de V2 (RESERVA_ALTURA_REMATE=55cm en
TODOS los pallets base de un CD con remate pendiente, que sobre-reservaba
margen en pallets que nunca terminaban recibiendo BAT) por selección de host
dinámica: para cada caja BAT, se busca el pallet cuya altura resultante quede
más cerca de config.ALTURA_TARGET.
"""
import math

import pandas as pd

import config
from models import CajaBAT, Cama, Pallet, PalletV5
from src.apilado_3d import _cabe, _colocar, _construir_lineas, _peso_cama, _puede_soportar
from src.reconciliacion_geometrica import capacidad_xy_max


def separar_bat(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """[sección 9.1] Separa demanda BAT del resto usando la categoría
    logística normalizada explícita (config.CATEGORIAS_BAT), no un valor
    numérico genérico compartido con otros productos. Devuelve
    (demanda_no_bat, demanda_bat)."""
    es_bat = df["Categoria_Normalizada"].isin(config.CATEGORIAS_BAT)
    return df[~es_bat].copy(), df[es_bat].copy()


def consolidar_bat_por_cd(df_bat: pd.DataFrame) -> dict[str, list[CajaBAT]]:
    """[sección 9.2] Arma cajas BAT de tamaño fijo (hasta
    CAJA_BAT_CAPACIDAD_UNIDADES) por CD, usando la demanda REAL en unidades
    -no `Cajas_Teoricas_Redondeadas`, que infla ~3.8x al redondear cada línea
    fraccionaria hacia arriba. Nunca mezcla CDs (invariante 13 de la sección
    lógica)."""
    cajas_por_cd: dict[str, list[CajaBAT]] = {}
    if df_bat.empty:
        return cajas_por_cd

    col_unidades = "Demanda_Unidades_Oficial" if "Demanda_Unidades_Oficial" in df_bat.columns else "Unidades"
    col_uxc = "Unidades_por_Caja" if "Unidades_por_Caja" in df_bat.columns else "Unidades por caja"

    for cd, grupo in df_bat.groupby("CD"):
        pendientes = {r["SKU"]: r[col_unidades] for _, r in grupo.iterrows() if r[col_unidades] > 0}
        unidades_por_caja = {r["SKU"]: r[col_uxc] for _, r in grupo.iterrows()}
        total_unidades = sum(pendientes.values())
        if total_unidades <= 0:
            continue

        n_cajas = math.ceil(total_unidades / config.CAJA_BAT_CAPACIDAD_UNIDADES)
        cajas: list[CajaBAT] = []
        for i in range(n_cajas):
            cupo = config.CAJA_BAT_CAPACIDAD_UNIDADES
            cantidades_cajas: dict[str, float] = {}
            unidades_en_esta_caja = 0.0
            for sku in list(pendientes):
                if cupo <= 0:
                    break
                tomar = min(pendientes[sku], cupo)
                if tomar <= 0:
                    continue
                cantidades_cajas[sku] = tomar / unidades_por_caja[sku]
                pendientes[sku] -= tomar
                cupo -= tomar
                unidades_en_esta_caja += tomar
            cajas.append(
                CajaBAT(
                    cd=cd,
                    id_bat=f"BAT-{cd}-{i + 1:03d}",
                    unidades=int(unidades_en_esta_caja),
                    cantidades_cajas=cantidades_cajas,
                )
            )
        cajas_por_cd[cd] = cajas

    return cajas_por_cd


def _peso_caja_bat(caja: CajaBAT, info_sku: dict) -> float:
    return sum(qty * (info_sku[sku].get("peso_caja") or 0.0) for sku, qty in caja.cantidades_cajas.items())


def asignar_hosts_bat(
    pallets: list[Pallet],
    cajas_bat_por_cd: dict[str, list[CajaBAT]],
    info_sku: dict,
    altura_target: float = config.ALTURA_TARGET,
) -> None:
    """[sección 9.3, 11.2, 11.5 / V4b] Corre DESPUÉS de que todos los pallets
    normales (no-BAT) están armados -es un post-proceso, no una reserva
    anticipada. Para cada caja BAT, elige entre los pallets del mismo CD el
    que minimice |altura_resultante - altura_target|, sujeto a:

    - mismo CD;
    - altura proyectada <= ALTURA_MAX_OBSERVADA;
    - peso proyectado <= PESO_HARD_KG (solo si config.PESO_ES_RESTRICCION_DURA);
    - soporte aceptable (misma regla que el resto del motor, _puede_soportar).

    [V4b / fotos de los 42 pallets reales] Ya no hay chequeo de remate
    (Comestibles ya no es una categoría especial -se mezcla libre con todo lo
    demás, ver apilado_3d.py- así que cualquier pallet del CD es candidato a
    host de BAT en igualdad de condiciones).

    Por defecto se asume una caja BAT por host (sección 9.3): un pallet ya
    usado como host en esta corrida no vuelve a ofrecerse para otra caja BAT
    del mismo CD -evita convertir un pallet operacional normal en el único
    lugar que recibe todo el remanente de cigarros del CD.

    BAT nunca abre un pallet propio si existe CUALQUIER forma de que entre en
    uno ya armado (decisión operativa: una caja BAT no es un pallet físico
    aparte). Se prueba en niveles, cada vez más permisivo:

    1. `_buscar_host`: un pallet que YA tiene margen (altura/peso/soporte),
       sin mover nada.
    2. `_liberar_host`: si ninguno tiene margen, se libera moviendo la(s)
       cama(s) superior(es) de un pallet a otro del mismo CD que sí tenga
       lugar -misma reubicación que ya hace `_consolidar_pallets` para
       pallets chicos.
    3. `_apilar_en_host_existente`: si un CD necesita más cajas BAT que
       pallets disponibles (ej. 4 cajas en un CD de 4 pallets, todos ya
       "gastados" como host de OTRA caja), se apila una segunda capa BAT
       sobre un host que ya tiene una -sigue siendo el mismo pallet físico,
       no uno nuevo.
    4. `_redistribuir_para_bat`: si NINGÚN pallet Mixto del CD tiene margen
       (todos ya están cerca del techo, nada que mover), se rearma el
       contenido de esos pallets Mixto en uno más de los que había -mismas
       cajas, un pallet extra-, repartido PAREJO entre todos (no al tope de
       cada uno) para que quede margen en al menos uno. Si un CD necesita
       varias cajas BAT y una ronda no alcanza, se repite -cada ronda reparte
       TODO el contenido Mixto vigente en un pallet más, así que el margen
       promedio sigue creciendo- acotado a como mucho una redistribución por
       caja BAT pendiente del CD (cota de seguridad, nunca debería hacer
       falta tantas rondas en la práctica).

    Solo si ni siquiera el último nivel encuentra pallet con margen físico
    real en NINGÚN pallet del CD se abre un pallet dedicado (nunca se
    descarta demanda BAT en silencio) -última red de seguridad, no el camino
    esperado."""
    pallets_por_cd: dict[str, list[Pallet]] = {}
    for p in pallets:
        pallets_por_cd.setdefault(p.cd, []).append(p)

    for cd, cajas in cajas_bat_por_cd.items():
        usados: set[int] = set()
        sin_host: list[CajaBAT] = []
        pendientes = list(cajas)
        # Cota de seguridad: como mucho una redistribución por caja BAT del
        # CD -en la práctica un CD real nunca necesita ni de cerca tantas
        # rondas (cada ronda ya reparte TODO el contenido Mixto en un pallet
        # más, así que el margen crece rápido), pero evita un CD patológico
        # donde `_redistribuir_para_bat` reintente sin límite.
        redistribuciones_restantes = len(cajas)

        while pendientes:
            caja = pendientes.pop(0)
            peso_caja = _peso_caja_bat(caja, info_sku)
            todos_cd = pallets_por_cd.get(cd, [])
            candidatos_cd = [p for p in todos_cd if id(p) not in usados and not p.es_host_bat]

            destino = _buscar_host(candidatos_cd, peso_caja, altura_target)
            if destino is None:
                destino = _liberar_host(candidatos_cd, peso_caja, info_sku)
            if destino is None:
                destino = _buscar_host([p for p in todos_cd if p.es_host_bat], peso_caja, altura_target)

            if destino is None and redistribuciones_restantes > 0:
                nuevos = _redistribuir_para_bat(todos_cd, info_sku)
                if nuevos is not None:
                    redistribuciones_restantes -= 1
                    origenes = {
                        id(p) for p in todos_cd if p.tipo == "Mixto" and not p.es_host_bat and p.camas
                    }
                    pallets_por_cd[cd] = [p for p in todos_cd if id(p) not in origenes] + nuevos
                    pallets[:] = [p for p in pallets if id(p) not in origenes] + nuevos
                    pendientes.insert(0, caja)  # reintentar esta misma caja con los pallets nuevos
                    continue
                redistribuciones_restantes = 0  # sin pallets Mixto que redistribuir: no insistir más

            if destino is not None:
                usados.add(id(destino))
                _colocar_bat(destino, [caja], info_sku, altura_target)
            else:
                sin_host.append(caja)

        if sin_host:
            nuevos = _consolidar_dedicados(cd, sin_host, info_sku, altura_target)
            pallets_por_cd.setdefault(cd, []).extend(nuevos)
            pallets.extend(nuevos)


def _redistribuir_para_bat(pallets_cd: list[Pallet], info_sku: dict) -> list[Pallet] | None:
    """[último recurso antes de un pallet dedicado] Ningún pallet Mixto del CD
    tiene margen individual, ni moviendo camas de a uno alcanza -están todos
    parejo cerca del techo. En vez de resignarse a un pallet dedicado, se
    junta el contenido de TODOS los pallets Mixto (no homogéneos, no ya-host-
    BAT) y se reparte de nuevo entre uno MÁS de los que había: mismo
    contenido total, un pallet extra, así que en promedio cada uno queda más
    bajo -con margen real para una caja BAT.

    A diferencia de `armar_pallets` (que llena parejo pero maximizando cada
    pallet antes de abrir el siguiente -"most-full-that-fits"), acá el
    criterio es "least-full-that-fits": en cada paso, la cama va al pallet
    con MENOS altura acumulada entre los que la reciben sin violar altura/
    soporte. Eso reparte parejo en vez de recrear el mismo apilamiento
    ajustado que ya no tenía lugar para BAT. [V4b] Un solo pase sobre TODAS
    las camas (sin separar por nivel de categoría, igual que
    `apilado_3d.armar_pallets`).

    Devuelve None si no hay pallets Mixto para redistribuir, o si -algo que
    no debería pasar, dado que es la MISMA cantidad de contenido en un
    pallet MÁS- alguna cama se queda sin destino."""
    origenes = [p for p in pallets_cd if p.tipo == "Mixto" and not p.es_host_bat and p.camas]
    if not origenes:
        return None

    todas_camas = [c for p in origenes for c in p.camas]
    if not todas_camas:
        return None

    n_nuevos = len(origenes) + 1
    base_id = origenes[0].id
    cd = origenes[0].cd
    nuevos = [
        Pallet(
            id=f"{base_id}-RB{i + 1}",
            cd=cd,
            tipo="Mixto",
            altura_final=config.ALTURA_PALLET_VACIO,
            peso_estimado=0.0,
        )
        for i in range(n_nuevos)
    ]

    for cama in sorted(todas_camas, key=lambda c: -c.altura_cama):
        candidatos = [p for p in nuevos if _cabe(p, cama, info_sku)]
        if not candidatos:
            return None
        destino = min(candidatos, key=lambda p: p.altura_final)
        _colocar(destino, cama, info_sku)

    for p in nuevos:
        p.lineas = _construir_lineas(p.camas, info_sku)
        p.estado = config.estado_pallet_por_altura(p.altura_final)

    return nuevos


def _buscar_host(candidatos_cd: list[Pallet], peso_caja: float, altura_target: float) -> Pallet | None:
    """[V4b] Pallets del CD que YA tienen margen (sin mover nada) para una
    caja BAT: altura/peso proyectados dentro de tope (peso solo si
    config.PESO_ES_RESTRICCION_DURA), soporte aceptable -sin chequeo de
    remate, cualquier pallet es candidato. Elige el que deje la altura
    resultante más cerca de `altura_target`."""
    candidatos = []
    for p in candidatos_cd:
        altura_proyectada = p.altura_final + config.CAJA_BAT_ALTO
        if altura_proyectada > config.ALTURA_MAX_OBSERVADA + 1e-9:
            continue
        if config.PESO_ES_RESTRICCION_DURA and p.peso_estimado + peso_caja > config.PESO_HARD_KG + 1e-9:
            continue
        if not _puede_soportar(p):
            continue
        candidatos.append((abs(altura_proyectada - altura_target), p))

    if not candidatos:
        return None
    candidatos.sort(key=lambda t: t[0])
    return candidatos[0][1]


def _liberar_host(candidatos_cd: list[Pallet], peso_caja: float, info_sku: dict) -> Pallet | None:
    """[fallback antes de abrir un pallet dedicado] Ningún pallet del CD tiene
    margen natural: se intenta liberarlo moviendo las camas superiores de un
    pallet candidato a otro pallet del mismo CD que sí tenga lugar, hasta
    bajar su altura por debajo de `ALTURA_MAX_OBSERVADA - CAJA_BAT_ALTO`.
    Prueba primero los pallets más altos. Simula el plan completo (sin mutar
    nada) antes de ejecutarlo -si alguna cama de la cadena no tiene destino
    real, descarta ese origen entero y prueba el siguiente, en vez de
    dejarlo a medio vaciar sin beneficio."""
    techo = config.ALTURA_MAX_OBSERVADA - config.CAJA_BAT_ALTO

    origenes = sorted((p for p in candidatos_cd if p.camas), key=lambda p: -p.altura_final)

    for origen in origenes:
        camas_a_mover = []
        altura_simulada = origen.altura_final
        idx = len(origen.camas) - 1
        while altura_simulada > techo + 1e-9 and idx >= 0:
            cama = origen.camas[idx]
            camas_a_mover.append(cama)
            altura_simulada -= cama.altura_cama
            idx -= 1

        if altura_simulada > techo + 1e-9:
            continue  # ni vaciando todo el pallet alcanza el margen que hace falta

        peso_liberado = sum(_peso_cama(c, info_sku) for c in camas_a_mover)
        if config.PESO_ES_RESTRICCION_DURA and (
            origen.peso_estimado - peso_liberado + peso_caja > config.PESO_HARD_KG + 1e-9
        ):
            continue

        alturas_proyectadas = {id(p): p.altura_final for p in candidatos_cd}
        pesos_proyectados = {id(p): p.peso_estimado for p in candidatos_cd}
        alturas_proyectadas[id(origen)] = altura_simulada

        plan: list[tuple[Cama, Pallet]] = []
        factible = True
        for cama in camas_a_mover:
            peso_cama = _peso_cama(cama, info_sku)
            mejor = None
            for destino in candidatos_cd:
                if destino is origen:
                    continue
                altura_dest = alturas_proyectadas[id(destino)]
                if altura_dest + cama.altura_cama > config.ALTURA_MAX_OBSERVADA + 1e-9:
                    continue
                if config.PESO_ES_RESTRICCION_DURA and (
                    pesos_proyectados[id(destino)] + peso_cama > config.PESO_HARD_KG + 1e-9
                ):
                    continue
                if mejor is None or altura_dest > alturas_proyectadas[id(mejor)]:
                    mejor = destino
            if mejor is None:
                factible = False
                break
            plan.append((cama, mejor))
            alturas_proyectadas[id(mejor)] += cama.altura_cama
            pesos_proyectados[id(mejor)] += peso_cama

        if not factible:
            continue

        for cama, destino in plan:
            origen.camas.remove(cama)
            origen.altura_final -= cama.altura_cama
            origen.peso_estimado -= _peso_cama(cama, info_sku)
            _colocar(destino, cama, info_sku)
            destino.lineas = _construir_lineas(destino.camas, info_sku)
        origen.lineas = _construir_lineas(origen.camas, info_sku)
        return origen

    return None


def _consolidar_dedicados(
    cd: str, cajas: list[CajaBAT], info_sku: dict, altura_target: float
) -> list[Pallet]:
    """Arma el mínimo de pallets dedicados (`PH-BAT-{cd}-NNN`) necesarios para
    todas las cajas BAT que no encontraron host operacional: varias cajas por
    capa (según cuántas entran físicamente en 120x100cm), varias capas hasta
    ALTURA_MAX_OBSERVADA (y PESO_HARD_KG si config.PESO_ES_RESTRICCION_DURA)."""
    por_capa, _orientacion = capacidad_xy_max(config.CAJA_BAT_LARGO, config.CAJA_BAT_ANCHO)
    por_capa = max(por_capa, 1)

    nuevos: list[Pallet] = []
    pallet_actual: Pallet | None = None
    n_dedicados = 0
    idx = 0
    while idx < len(cajas):
        grupo = cajas[idx : idx + por_capa]
        peso_grupo = sum(_peso_caja_bat(c, info_sku) for c in grupo)

        if pallet_actual is not None:
            altura_proyectada = pallet_actual.altura_final + config.CAJA_BAT_ALTO
            cabe_altura = altura_proyectada <= config.ALTURA_MAX_OBSERVADA + 1e-9
            cabe_peso = (
                not config.PESO_ES_RESTRICCION_DURA
                or pallet_actual.peso_estimado + peso_grupo <= config.PESO_HARD_KG + 1e-9
            )
        else:
            cabe_altura = cabe_peso = False

        if pallet_actual is None or not (cabe_altura and cabe_peso):
            n_dedicados += 1
            pallet_actual = Pallet(
                id=f"PH-BAT-{cd}-{n_dedicados:03d}",
                cd=cd,
                tipo="Mixto",
                altura_final=config.ALTURA_PALLET_VACIO,
                peso_estimado=0.0,
            )
            nuevos.append(pallet_actual)

        _colocar_bat(pallet_actual, grupo, info_sku, altura_target)
        idx += por_capa

    return nuevos


def _colocar_bat(pallet: Pallet, cajas: list[CajaBAT], info_sku: dict, altura_target: float) -> None:
    """BAT siempre va al final (invariante 15): se llama después de que el
    pallet ya está completo, así que un append simple ya lo deja arriba de
    todo -sin necesidad de reordenar por nivel.

    `cajas` puede traer varias cajas BAT (mismo alto fijo, físicamente una al
    lado de la otra en la misma capa) -se consolidan en UNA sola cama, para
    no gastar una capa completa de altura por cada caja cuando varias caben
    lado a lado en 120x100cm (ver `_consolidar_dedicados`)."""
    if pallet.tipo.startswith("Homogéneo") and "Remate" not in pallet.tipo:
        pallet.tipo = "Homogéneo + Remate"

    cantidades: dict[str, float] = {}
    for caja in cajas:
        for sku, qty in caja.cantidades_cajas.items():
            cantidades[sku] = cantidades.get(sku, 0) + qty

    cama = Cama(
        categorias=["Cigarros"],
        altura_cama=cajas[0].alto,
        cantidades=cantidades,
        nivel_categoria=config.NIVEL_REMATE,
        area_ocupada=sum(c.largo * c.ancho for c in cajas),
        tipo_soporte="TERMINAL",
    )
    pallet.altura_pre_bat = pallet.altura_final
    pallet.camas.append(cama)
    pallet.altura_final += cama.altura_cama
    pallet.peso_estimado += _peso_cama(cama, info_sku)
    pallet.cajas_bat.extend(cajas)
    pallet.es_host_bat = True
    pallet.altura_target_delta = round(pallet.altura_final - altura_target, 3)
    for caja in cajas:
        caja.pallet_host_id = pallet.id

    pallet.lineas = _construir_lineas(pallet.camas, info_sku)


# ============================================================================
# [V5-BAT-integrado] BAT DENTRO del mismo multi-start, no una pasada aparte.
#
# La primera versión de esto (V5-P9, ver PATCH_LOG.md e historial de este
# archivo) corría DESPUÉS de que multi-start+residual search ya cerraban los
# pallets no-BAT -para entonces, el score de multi-start (n_pallets, altura
# cerca del target, ...) ya había optimizado cada pallet SIN saber que iba a
# hacer falta lugar para BAT, dejando cada vez menos aire disponible a
# medida que el packing 3D se ajustaba más (medido: bat_dedicados subió de
# 2 a 5 al pasar de 2D a 3D). Reemplazada por completo (no queda código
# muerto de esa versión) porque el resultado con BAT integrado fue
# estrictamente mejor: mismo total de pallets o menos, bat_dedicados a 0 en
# el dataset real, cero violaciones geométricas, demanda exacta -ver
# PATCH_LOG.md, sección "V5-BAT-integrado".
#
# BAT se agrega como una fila más de demanda ANTES de correr multi-start
# (`construir_filas_bat_pseudo_sku`), tratada como una SKU más por
# `armar_pallets_columnar`/`generar_torres_candidatas` (que ya rota ambas
# orientaciones automáticamente -la versión anterior solo probaba 45x24).
# Como el conteo de pallets YA es lo primero que compara el score de
# multi-start, una estrategia/semilla que deja a BAT sin lugar (forzando un
# pallet dedicado más) automáticamente puntúa peor y pierde -sin que haga
# falta ningún criterio nuevo en `multistart.py`.
#
# Las cajas BAT reales (`CajaBAT`) son fungibles entre sí para efectos de
# COLOCACIÓN (mismo footprint fijo 45x24x55) -el packer las trata como
# `Cajas_Remanente` de una sola "SKU" `BAT_SKU_MARCADOR`. Después de armar,
# `asignar_cajas_bat_a_torres` mapea esa cantidad colocada de vuelta a
# objetos `CajaBAT` reales concretos (orden estable, sin que importe cuál
# caja específica terminó en qué torre -son intercambiables).
# ============================================================================

BAT_SKU_MARCADOR = "__BAT__"


def construir_filas_bat_pseudo_sku(cajas_bat_por_cd: dict[str, list[CajaBAT]], info_sku: dict) -> pd.DataFrame:
    """[V5-BAT-integrado] Una fila por CD con demanda BAT, con las mismas
    columnas que `armar_pallets_columnar`/`multistart` esperan de cualquier
    SKU real (Largo/Ancho/Alto_Efectivo, Peso_Caja, Cajas_Remanente,
    Cajas_Cama_Efectivo) -para que BAT compita por espacio en el MISMO
    `df_cd` que el resto de la demanda del CD, en vez de una pasada aparte."""
    filas = []
    for cd, cajas in cajas_bat_por_cd.items():
        if not cajas:
            continue
        peso_total = sum(_peso_caja_bat(c, info_sku) for c in cajas)
        peso_unitario = peso_total / len(cajas)
        capacidad_cama, _orientacion = capacidad_xy_max(config.CAJA_BAT_LARGO, config.CAJA_BAT_ANCHO)
        filas.append(
            {
                "CD": cd,
                "SKU": BAT_SKU_MARCADOR,
                "Cajas_Remanente": len(cajas),
                "Largo_Efectivo": config.CAJA_BAT_LARGO,
                "Ancho_Efectivo": config.CAJA_BAT_ANCHO,
                "Alto_Efectivo": config.CAJA_BAT_ALTO,
                "Peso_Caja": peso_unitario,
                "Fuente_Geometria": "BAT",
                "Cajas_Cama_Efectivo": capacidad_cama,
            }
        )
    return pd.DataFrame(filas)


def renombrar_pallets_bat_puros(pallets_cd: list[PalletV5], cd: str) -> None:
    """[V5-BAT-integrado] Un pallet cuyas torres son TODAS BAT (ninguna otra
    SKU) es, en la práctica, un pallet dedicado -se renombra al esquema
    `PV5-BAT-{cd}-NNN` que ya usan `benchmark.py`/`exportar.py` para
    reconocerlos, aunque haya salido del MISMO packer genérico que todo lo
    demás. Muta `pallet.id` in place -determinístico: recorre `pallets_cd`
    en su orden ya estable."""
    n = 0
    for pallet in pallets_cd:
        if pallet.torres and all(t.sku == BAT_SKU_MARCADOR for t in pallet.torres):
            n += 1
            pallet.id = f"PV5-BAT-{cd}-{n:03d}"


def asignar_cajas_bat_a_torres(pallets_cd: list[PalletV5], cajas_bat: list[CajaBAT]) -> None:
    """[V5-BAT-integrado] Después de que `armar_pallets_columnar` ya colocó
    torres con sku `BAT_SKU_MARCADOR` (tratadas como demanda genérica, sin
    saber de `CajaBAT` reales), mapea esa cantidad de vuelta a objetos
    `CajaBAT` concretos -son fungibles entre sí (mismo footprint fijo), así
    que el mapeo es por orden estable, no por identidad. Llamar DESPUÉS de
    `renombrar_pallets_bat_puros` -así `caja.pallet_host_id` queda con el id
    final, no uno que después se renombra."""
    disponibles = list(cajas_bat)
    idx = 0
    for pallet in pallets_cd:
        for torre in pallet.torres:
            if torre.sku != BAT_SKU_MARCADOR:
                continue
            asignadas = disponibles[idx : idx + torre.cantidad]
            idx += torre.cantidad
            for caja in asignadas:
                caja.pallet_host_id = pallet.id
            pallet.cajas_bat.extend(asignadas)
            pallet.metadata["es_host_bat"] = True
