"""[SKU_BLOQUE] Lógica de armado por CAMAS -corrección explícita del usuario
sobre cómo se arma un pallet físicamente:

"nunca pero nunca se empieza haciendo columnas, siempre primero se van
llenando las filas de abajo hacia arriba construyendo un bloque de
120x100" -y por capa, "no puede elegir una sola orientación [nueva, propia],
tiene que buscar la orientación adecuada para cumplir con las cajas por
cama del maestro, y así cumplirla hasta lo que diga la demanda sin
sobrepasar el máximo de cajas por PH que dice el maestro".

[BUG REAL, corregido acá] La primera versión de este archivo armaba cada
cama con un `_CuboidLibre` NUEVO que asumía toda la huella 120x100
disponible a esa altura Z -pero una cama real casi nunca ocupa el 100% de
la huella (82-90% típico), así que la cama de arriba terminaba con cajas
puestas sobre huecos que NO tenían nada debajo: cajas flotando en el aire
(reporte del usuario con foto del Inspector: "hay cajas que estan
flotandoen el vacio, toda caja debe esta puesta sobre otra caja"). La
causa raíz era resetear el espacio libre en cada frontera de cama en vez
de arrastrar el estado 3D real.

Arquitectura (corregida):
1. UN SOLO `_PalletEnConstruccion` por pallet, de piso a techo, usando el
   motor MaxRects 3D real de `packing_columnar.py` de forma continua -nunca
   se resetea a mitad de armado. Por construcción, MaxRects solo genera
   espacio libre nuevo INMEDIATAMENTE ENCIMA de geometría que de verdad se
   colocó (o al ras del piso del pallet en Z=0) -es geométricamente
   imposible que una caja quede sin soporte real debajo.
2. Cada colocación es de 1 caja a la vez, y siempre se elige el cuboide
   libre disponible de menor Z ("más bajo primero") entre todos los SKUs
   candidatos -eso es lo que reproduce "cama por cama, fila por fila" sin
   reintroducir el modelo antiguo de reset: cualquier hueco a la misma
   altura Z que sigue disponible gana SIEMPRE sobre saltar a una altura
   mayor, así que el armado llena una capa completa (con el SKU ancla y,
   si no alcanza, con SKUs de relleno compatibles) antes de subir.
3. El objetivo de cuántas cajas de un SKU van en UNA capa no lo inventa el
   packer: es `Cajas_Cama_Efectivo` (`derivados.py`), que ya reconcilia el
   "Cajas por cama" real del Maestro contra la geometría UMA. Como ya no
   existe una frontera de "cama" explícita para resetear un contador, el
   cupo se valida contando, en cada intento, cuántas torres de ese mismo
   SKU ya existen a esa misma Z exacta en el pallet -si ya se alcanzó el
   cupo ahí, ese cuboide se descarta para ese SKU (pero sigue disponible
   para cualquier otro).
4. [segunda reescritura -pedido explícito del usuario tras revisar el
   cubicaje real: "primero se tiene que acabar toda la demanda de licor
   por sku luego pasar a las siguientes categorias y que nunca puede ir
   una caja de licor encima de otra categoria porque pesa mucho, pero si
   puede ir 1 caja de nabs o de importados sobre licor"] Se había
   probado, un rato antes en la misma sesión, una versión con 4 BANDAS
   estrictamente secuenciales donde Licores/Lácteos/NABs nunca compartían
   cama entre sí -pero al cruzar esa regla contra un pallet real
   (`Plan de acción 24.08 - CUBICADO - ELIAN.xlsx`, BK34 pallet 1) se
   encontraron Licores, Comestibles, Aseo y NABs todos mezclados en el
   MISMO pallet, y 19 de 21 SKUs con demanda menor a su propio
   `Cajas por cama` (cada SKU ocupa como mucho un par de camas propias,
   compartiendo piso con los demás sin que se agote una categoría antes
   de tocar otra). Eso descartó la exclusividad de cama por banda.
   Lo que SÍ sigue siendo cierto, y es lo que pidió el usuario, es una
   jerarquía de PESO/soporte -no de "quién se coloca primero en el
   tiempo", sino de "quién puede quedar apoyado sobre quién": Licores
   (más pesado) nunca puede quedar apoyado sobre otra categoría, pero
   categorías más livianas (NABs, Importados, etc.) sí pueden apoyarse
   sobre Licores. Esto es exactamente `config.nivel_de_categoria`
   (Licores=1 el más bajo/pesado, subiendo hasta Cigarros=8 -mismo mapa
   que ya usa el resto del sistema para reportes), usado como chequeo de
   soporte por columna (`_soporte_viola_nivel`): una caja nunca puede
   quedar apoyada DIRECTAMENTE encima de soporte de un nivel MAYOR al
   suyo. [corregido -bug real, ver PATCH_LOG.md] El nivel NO es el primer
   criterio de la competencia por cuboide libre -eso le hacía ganar a
   Licores por una Z mucho más alta (su propia columna) en vez de dejar
   que otras categorías usaran una Z más baja real, contradiciendo "cama
   por cama, fila por fila" y, con N pallets fijos, perdiendo hasta 30%
   de la demanda. La Z sigue siendo el primer criterio; el nivel solo
   desempata "por sku" cuando dos SKUs podrían usar la MISMA Z.
   Cigarros/BAT y cualquier SKU forzado a nivel remate por Subcategoría
   RTD/Energizante (ver derivados.py) se recortan a `config.NIVEL_REMATE`
   acá mismo -no
   siguen subiendo hasta `NIVEL_CIGARROS`- para que ya no sea "siempre lo
   más alto obligatorio" (pedido explícito, sigue vigente), sino un
   miembro más del grupo de remate, en igualdad de condiciones con
   Comestibles.
4b. [alto compartido entre categorías distintas -pedido explícito:
   "categorias disntinas si pueden compartir la misma cama siempre y
   cuando en alto tambien sea compartido"] Una caja nueva solo entra en
   una Z donde ya hay cajas de OTRA categoría si su alto coincide (dentro
   de `TOLERANCIA_ALTURA_CAMA_CM`) con el de TODO lo que ya está puesto
   ahí -evita camas con perfiles dispares. Esto NO le exige a una sola
   caja igualar la altura de otra sola caja: el motor exacto arma cada
   columna caja por caja, así que si una SKU de 30cm de alto comparte piso
   con otra de 15cm, la de 15cm sencillamente sigue apilando una segunda
   caja encima de la primera (a su propia Z, no la Z compartida original)
   hasta emparejar los 30cm -son 2 Z distintas, este chequeo nunca las ve
   como "la misma cama" y no se dispara entre ellas.
5. [consolidación de remanentes] El barrido de arriba es voraz: abre un
   pallet nuevo apenas queda algo pendiente, así que SKUs de baja demanda
   que se van agotando de a poco (su tope por capa, o su compatibilidad de
   nivel) pueden terminar esparcidos en varios pallets cortos en vez de
   juntarse en uno solo -no porque falte volumen para combinarlos, sino
   porque el orden en que el barrido los fue abriendo los separó. Después
   del barrido principal, los pallets que quedaron muy por debajo del
   presupuesto de altura se deshacen (vuelven a ser demanda pendiente) y
   se reempacan juntos con el mismo motor -si el reempaque no mejora
   (mismo número de pallets o más), se descarta y se conserva el
   resultado original; nunca se acepta un reempaque peor.

[reconstruido sobre el motor exacto -pedido explícito del usuario tras ver
fotos de un pallet con ~21% de cobertura de soporte faltante en promedio
(motor aproximado PH_FRACCION, retirado): "tiene que llenar la cama en su
dimension volumetrica completa y luego pasar a la siguiente", "toda caja
debe esta puesta sobre otra caja"] Este archivo (el motor 3D exacto,
0% de flotación verificado desde el fix original) vuelve a ser el que usa
el pipeline -ver `pipeline_sku_bloque.py`. Para recuperar la densidad real
que PH_FRACCION perseguía sin sacrificar la garantía exacta, se le agregan
2 ingredientes que esa versión aproximada sí demostró que funcionan:
6. [orientación flexible + elegida por hueco real, no fija por SKU]
   Comestibles/Aseo/Cigarros pueden acostarse o voltearse en cualquiera de
   sus 6 orientaciones (`torres.generar_torres_candidatas_todas_
   orientaciones`) para aprovechar huecos irregulares que ninguna
   orientación "de pie" calza -NABs y el resto de las categorías siguen
   con las 2 orientaciones de siempre (pedido explícito: "nabs es el unico
   que siempre tiene que ir de pie"). [reescrito -caso real reportado por
   el usuario con fotos: "columnas" de altura despareja] Para CADA SKU, en
   CADA intento de colocación, se prueban TODAS sus orientaciones
   disponibles y se usa la que le da la Z más baja en ese momento -no una
   orientación fija elegida de antemano por capacidad de grilla en un
   pallet vacío. Antes, una orientación fija por SKU significaba que, si
   esa orientación seguía encontrando dónde ir (aunque fuera solo
   siguiendo su propia columna, cada vez más arriba), nunca se comparaba
   contra la otra orientación "de pie" -así, un hueco angosto que dejaba
   OTRA columna ya agotada (footprint más chico que el de la columna
   vecina) se quedaba sin usar aunque la otra orientación calzara justo
   ahí, aunque hubiera piso libre. Probar todas cada vez sigue sin acostar
   nada para Licores/Lácteos/NABs (pedido explícito del usuario: mantener
   siempre de pie, ver PATCH_LOG.md) -solo elige, de las orientaciones que
   YA tenía permitidas, la más útil para el cuboide libre real disponible
   en ese momento. Como el motor sigue siendo el mismo MaxRects exacto,
   esto no relaja NADA de la garantía de soporte -solo evalúa más
   candidatas por cuboide libre real.
7. [tope real por SKU] `Cajas por PH` del Maestro es el máximo físico de
   cuántas cajas de un SKU pueden ir en UN pallet (sea homogéneo o
   mezclado) -se aplica como tope duro por pallet (`tope_pallet_por_sku` +
   `colocado_en_pallet`, reseteado en cada pallet nuevo), igual mecanismo
   que ya se había probado en PH_FRACCION.
8. [dispersos] Un SKU de poca demanda puede terminar solo en su propio
   pallet casi vacío simplemente porque el barrido lo fue dejando para el
   final -no porque no hubiera lugar real en otro pallet ya armado del
   mismo CD. `_redistribuir_dispersos` intenta, después del barrido
   principal, mover cada torre de un pallet muy vacío al espacio libre
   real de los demás pallets del CD antes de aceptarlo como pallet
   aparte.
"""
import random

import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import (
    _altura_presupuesto,
    _area_union_xy,
    _PalletEnConstruccion,
    _reconstruir_en_construccion,
)
from src.validacion_v5 import _area_cubierta_por_soporte
from src.torres import TorreCandidate, generar_torres_candidatas, generar_torres_candidatas_todas_orientaciones

TOL = 1e-6

# [sección 6] Categorías que pueden acostarse/voltearse libremente para
# aprovechar huecos irregulares -pedido explícito del usuario. NABs NUNCA
# entra acá: siempre de pie (mismas 2 orientaciones que el resto).
CATEGORIAS_ORIENTACION_FLEXIBLE = {"Comestibles", "Aseo", "Cigarros"}

# [sección 4b] Tolerancia de alto entre cajas de categorías distintas que
# comparten una misma cama -pedido explícito del usuario ("categorias
# disntinas si pueden compartir la misma cama siempre y cuando en alto
# tambien sea compartido"). Mismo valor (8cm) ya calibrado contra datos
# reales en una versión anterior de este armador (con 3cm, ~91% de
# pallets quedaban parciales; con 8cm, ~76%).
TOLERANCIA_ALTURA_CAMA_CM = 8.0

# [combinación por fila, caso real: Pallet 1 CD Callao, fotos del usuario]
# El desempate de `_empacar` (sección 4) hace ganar siempre a Licores toda
# celda que también le sirva a él -pedido explícito y probado con datos
# reales ("primero se tiene que acabar toda la demanda de licor por sku").
# Pero con datos reales de Pallet 1 (93 cajas, ~49 de Licores) eso deja a
# un SKU de footprint chico y mucha demanda (Electrolight, NABs) atado a
# UNA sola columna durante todo el armado -confirmado con trazas paso a
# paso: nunca hay un error de cálculo, la celda simplemente la gana Licores
# cada vez que también entra ahí, incluso cuando Licores YA tiene columnas
# de sobra para cubrir el resto de su propia demanda.
#
# Se probaron 3 variantes antes de esta (ver PATCH_LOG.md): un umbral de
# "demanda por columna" (mejoraba Pallet 1 pero rompía SJ87 del dataset de
# referencia en cascada), y una cesión por "capacidad instalada" sin
# restricción (mejoraba fuerte pero dejaba a Four Loko compartir el piso
# del pallet con Licores reales, algo que
# `test_four_loko_queda_en_banda_remanente_no_en_licores` prohíbe
# explícitamente) y esa misma restringida a z>0 en general (arregla ese
# test pero regresiona BK65 del dataset de referencia). Esta versión -
# cesión por capacidad instalada, con la excepción de remate solo en el
# piso- es la única de las 4 que pasa la suite completa Y mejora el
# dataset de referencia (56->54 pallets, ningún CD peor) Y Pallet 1
# (58->67 cajas, Electrolight 7->18) a la vez.
def _columnas_actuales_pos(pallet: PalletV5, sku: str) -> set[tuple[float, float]]:
    """Posiciones (x, y) DISTINTAS que ya tiene este SKU en el pallet -una
    torre más alta en la misma columna no cuenta dos veces."""
    return {(round(t.x, 4), round(t.y, 4)) for t in pallet.torres if t.sku == sku}


def _capacidad_instalada(pallet: PalletV5, sku: str, presupuesto: float) -> int:
    """Cuántas cajas MÁS de este SKU caben, sumando sobre TODAS sus
    columnas ya existentes, antes de llegar al presupuesto de altura -sin
    contar ninguna columna nueva. Si esto ya alcanza para su demanda
    pendiente, no necesita ganar una celda más -puede cederla."""
    por_columna: dict[tuple[float, float], tuple[float, float]] = {}
    for t in pallet.torres:
        if t.sku != sku:
            continue
        pos = (round(t.x, 4), round(t.y, 4))
        tope = t.z + t.altura
        actual = por_columna.get(pos)
        if actual is None or tope > actual[0]:
            por_columna[pos] = (tope, t.alto_caja)
    total = 0
    for tope, alto_caja in por_columna.values():
        total += max(0, int((presupuesto - tope + TOL) // alto_caja))
    return total


def _necesita_columna_nueva(
    pallet: PalletV5, sku: str, pendiente: int, nivel_sku: int, x: float, y: float, z: float, presupuesto: float,
) -> bool:
    """True si `sku` genuinamente necesita la celda (x, y, z) como columna
    NUEVA: no es continuación de una columna propia, su demanda pendiente
    supera lo que sus columnas YA existentes pueden cubrir subiendo -no es
    solo "más espacio por las dudas"-, y -excepción de remate- no es una
    categoría de remate (Four Loko/Cigarros incluidos,
    `nivel >= config.NIVEL_REMATE`) compitiendo por el PISO del pallet
    (z=0) -ese piso sigue siendo dominio exclusivo de Licores reales
    mientras compitan ahí, tal como prueba
    `test_four_loko_queda_en_banda_remanente_no_en_licores`. Esta función
    se usa para decidir si un candidato ENTRA a competir por desplazar al
    ganador normal -si un SKU de remate en el piso nunca llega a
    considerarse acá, nunca puede desplazar a nadie, sin necesidad de un
    chequeo aparte más adelante."""
    if (round(x, 4), round(y, 4)) in _columnas_actuales_pos(pallet, sku):
        return False
    if nivel_sku >= config.NIVEL_REMATE and z <= TOL:
        return False
    return pendiente > _capacidad_instalada(pallet, sku, presupuesto)


def _cabe_en_pallet(cand: TorreCandidate, presupuesto: float) -> bool:
    """Chequeo de geometría pura contra un pallet VACÍO -si ni siquiera acá
    entra, no va a entrar en ninguno más lleno (huella mayor a 120x100 en
    ambas orientaciones, o caja más alta que el presupuesto de altura)."""
    cols = int(config.PALLET_LARGO // cand.largo)
    filas = int(config.PALLET_ANCHO // cand.ancho)
    return cols > 0 and filas > 0 and cand.alto_caja <= presupuesto + TOL


def _soporte_viola_nivel(
    pallet: PalletV5, x: float, y: float, largo: float, ancho: float, z: float,
    nivel_sku: int, nivel_por_sku: dict[str, int],
) -> bool:
    """[sección 4] Por columna física: una caja nunca puede quedar apoyada
    DIRECTAMENTE encima de otra de un nivel MAYOR (ej. Licores, nivel 1,
    nunca sobre NABs, nivel 6) -pedido explícito: "nunca puede ir una caja
    de licor encima de otra categoria porque pesa mucho, pero si puede ir
    1 caja de nabs o de importados sobre licor". En z=0 (piso del pallet)
    no hay restricción -cualquier categoría puede arrancar ahí. Para z>0,
    se identifican las torres que son el soporte real e inmediato de esta
    huella (mismo criterio que la validación anti-flotación: tope de esas
    torres exactamente en `z`, huella que se solapa) -si CUALQUIERA de esas
    torres de soporte pertenece a un nivel MAYOR al que se está por
    colocar, es una violación."""
    if z <= TOL:
        return False
    for t in pallet.torres:
        if abs((t.z + t.altura) - z) > TOL:
            continue
        if t.x + t.largo <= x + TOL or x + largo <= t.x + TOL:
            continue
        if t.y + t.ancho <= y + TOL or y + ancho <= t.y + TOL:
            continue
        if nivel_por_sku.get(t.sku, 0) > nivel_sku:
            return True
    return False


def _altura_compatible_con_cama(pallet: PalletV5, z: float, alto_caja: float) -> bool:
    """[sección 4b] Por encima del piso del pallet (z>0): una caja nueva
    solo entra en una Z donde ya hay otras cajas si su alto coincide
    (dentro de `TOLERANCIA_ALTURA_CAMA_CM`) con TODO lo que ya está puesto
    exactamente ahí -evita camas con perfiles dispares. En el piso (z=0)
    no se restringe -mezclar ahí SKUs de alturas bien distintas es
    exactamente lo que el fix de "huella grande gana el empate" (ver
    PATCH_LOG.md) ya demostró que hace falta con datos reales (una SKU
    grande tipo BAT, 49cm, compartiendo piso con SKUs chicas de 18-24cm)
    -y coincide con las fotos de cubicaje real del usuario, donde botellas
    de alturas distintas conviven en la misma base sin ningún problema.
    No exige que UNA caja iguale la altura de OTRA -si una SKU de 15cm de
    alto comparte piso con otra de 30cm, la de 15cm simplemente apila una
    segunda caja encima de la primera para emparejar los 30cm; esa segunda
    caja queda en su PROPIA Z (no la compartida original), así que este
    chequeo nunca se dispara entre ellas."""
    if z <= TOL:
        return True
    for t in pallet.torres:
        if abs(t.z - z) <= TOL and abs(t.alto_caja - alto_caja) > TOLERANCIA_ALTURA_CAMA_CM + TOL:
            return False
    return True


def _cuboide_admite_candidato(
    pallet: PalletV5, c, cand: TorreCandidate, tope_capa: int | None,
    nivel_sku: int, nivel_por_sku: dict[str, int],
) -> bool:
    """[extraído de _mejor_cuboide_para_sku, sin cambio de comportamiento]
    ¿Entra 1 caja de `cand` en ESTE cuboide libre concreto? Descarta si:
    (a) `tope_capa` (Cajas_Cama_Efectivo real del Maestro) ya se alcanzó
    para este SKU en la Z exacta de ese cuboide, (b) colocar ahí violaría
    el orden de nivel/peso por columna (`_soporte_viola_nivel`), o (c) su
    alto no es compatible con lo que ya hay puesto en esa misma cama
    (`_altura_compatible_con_cama`). Reusado por `_mejor_cuboide_para_sku`
    (1 sola opción por SKU) y por `_candidatos_lote` del solver de N
    pallets fijos (varias opciones por SKU, ver comentario ahí)."""
    if cand.largo > c.w + TOL or cand.ancho > c.h + TOL or cand.alto_caja > c.d + TOL:
        return False
    if tope_capa is not None:
        ya_en_esta_capa = sum(
            t.cantidad for t in pallet.torres if t.sku == cand.sku and abs(t.z - c.z) <= TOL
        )
        if ya_en_esta_capa >= tope_capa:
            return False
    if _soporte_viola_nivel(pallet, c.x, c.y, cand.largo, cand.ancho, c.z, nivel_sku, nivel_por_sku):
        return False
    if not _altura_compatible_con_cama(pallet, c.z, cand.alto_caja):
        return False
    return True


def _mejor_cuboide_para_sku(
    pallet: PalletV5, pc: _PalletEnConstruccion, cand: TorreCandidate, tope_capa: int | None,
    nivel_sku: int, nivel_por_sku: dict[str, int],
) -> int | None:
    """[sección 2, 4, 4b] Entre los cuboides libres que reciban 1 caja de
    `cand`, el de menor Z (más bajo) -así se llena SIEMPRE la capa más
    baja disponible antes de subir, nunca se salta a una más alta habiendo
    sitio abajo (row-first, nunca columnas). Ver `_cuboide_admite_
    candidato` para los descartes por tope de capa/soporte/altura."""
    mejor_idx, mejor_clave = None, None
    for idx, c in enumerate(pc.libres):
        if not _cuboide_admite_candidato(pallet, c, cand, tope_capa, nivel_sku, nivel_por_sku):
            continue
        clave = (c.z, c.volumen)
        if mejor_clave is None or clave < mejor_clave:
            mejor_idx, mejor_clave = idx, clave
    return mejor_idx


def _empacar(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    presupuesto: float,
    cd: str,
    contador: list[int],
) -> list[PalletV5]:
    """[secciones 1-4, 4b, 7] Un barrido completo del algoritmo de camas
    sobre `pendientes` -extraído aparte para poder invocarlo más de una vez
    sobre distintos subconjuntos de demanda (ver sección 5, consolidación
    de remanentes) sin duplicar la lógica de armado."""
    pallets: list[PalletV5] = []

    while any(v > 0 for v in pendientes.values()):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        pc = _PalletEnConstruccion(pallet=pallet)
        avanzo_en_este_pallet = False
        # [sección 7] Cajas por PH es un tope por PALLET, no global -se
        # resetea acá, en cada pallet nuevo.
        colocado_en_pallet: dict[str, int] = {}

        guard = 0
        while True:
            guard += 1
            if guard > 100_000:
                break
            activos = [
                s
                for s in pendientes
                if pendientes[s] > 0
                and colocado_en_pallet.get(s, 0) < tope_pallet_por_sku.get(s, float("inf"))
            ]
            if not activos:
                break

            # [sección 4, corregido -bug real: con nivel como PRIMER
            # criterio, Licores le ganaba a Comestibles/NABs/Aseo por una Z
            # mucho más ALTA (apilando en su propia columna) en vez de
            # dejarlos usar una Z más baja en el piso -eso contradice
            # "cama por cama, fila por fila" (sección 2) y, con N pallets
            # fijos, causaba que hasta 30% de la demanda se quedara sin
            # colocar (verificado contra datos reales) por columnas
            # desparejas: Licores construía torres altas mientras el piso
            # seguía con hueco real disponible para otras categorías] La Z
            # es SIEMPRE el primer criterio -la cama más baja disponible
            # gana, sin importar la categoría. El NIVEL de categoría
            # (config.nivel_de_categoria: Licores=1 el más pesado/bajo,
            # subiendo hasta Cigarros=8) solo desempata cuando dos SKUs
            # podrían usar la MISMA Z -ahí sí gana Licores primero (pedido
            # explícito del usuario: "primero se tiene que acabar toda la
            # demanda de licor"), pero nunca a costa de saltarse una Z más
            # baja real. La restricción DURA de peso (nada más pesado
            # apoyado sobre algo menos pesado) sigue intacta y aparte, en
            # `_soporte_viola_nivel` -no depende de este orden de
            # competencia. Dentro del mismo (Z, nivel), MAYOR huella
            # primero -no más demanda primero. Verificado con datos reales
            # (BK31, PATCH_LOG.md): priorizar demanda dejaba que SKUs
            # chicas de mucha demanda acapararan el piso mientras estaba
            # abierto, fragmentándolo en bolsillos angostos -las SKUs
            # grandes (con menos margen para encajar en cualquier lado)
            # terminaban esperando y se quedaban sin sitio. "Piezas
            # grandes primero" es la heurística estándar de bin-packing.
            # Empate de huella: más demanda pendiente primero (sigue
            # concentrando el mismo SKU en capas consecutivas).
            mejor = None
            mejor_necesitado = None
            for sku in activos:
                tope_capa = capacidad_cama_por_sku.get(sku)
                nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
                # [sección 6, reescrito -caso real: columnas de altura
                # despareja] Se prueban TODAS las orientaciones de este SKU
                # (para Licores/Lácteos/NABs, siempre de pie, son solo 2;
                # para las categorías flexibles, hasta 6) y se usa la que
                # le da la Z más baja a ESTE SKU -no una orientación fija
                # "preferida" elegida de antemano por capacidad de grilla
                # en un pallet vacío. Antes, una orientación fija por SKU
                # significaba que si esa orientación seguía encontrando
                # dónde ir (aunque fuera en SU PROPIA columna, más arriba),
                # nunca se comparaba contra la otra orientación "de pie" -
                # así, un hueco angosto que dejaba OTRA columna ya agotada
                # se quedaba sin usar aunque la otra orientación calzara
                # justo ahí (columnas de altura pareja según el SKU, no
                # según el hueco real disponible). Probar todas cada vez
                # sigue sin acostar nada para Licores/Lácteos/NABs -esas
                # solo tienen las 2 "de pie"- y elige la MEJOR, no una fija
                # de antemano.
                mejor_para_sku = None
                for cand_op in por_sku[sku]:
                    idx_libre_op = _mejor_cuboide_para_sku(pallet, pc, cand_op, tope_capa, nivel_sku, nivel_por_sku)
                    if idx_libre_op is None:
                        continue
                    libre_op = pc.libres[idx_libre_op]
                    clave_op = (libre_op.z, libre_op.volumen)
                    if mejor_para_sku is None or clave_op < mejor_para_sku[0]:
                        mejor_para_sku = (clave_op, cand_op, idx_libre_op)
                if mejor_para_sku is None:
                    continue
                _, cand, idx_libre = mejor_para_sku
                libre = pc.libres[idx_libre]
                z_destino = libre.z
                area = cand.largo * cand.ancho
                clave = (z_destino, nivel_sku, -area, -pendientes[sku])
                if mejor is None or clave < mejor[0]:
                    mejor = (clave, sku, cand, idx_libre)
                # [combinación por fila, ver comentario arriba] Candidato
                # que SÍ necesita esta celda como columna nueva (footprint
                # chico, mucha demanda, ninguna columna propia le alcanza)
                # -se guarda aparte, sin nivel en la clave, para competir
                # en pie de igualdad.
                if _necesita_columna_nueva(pallet, sku, pendientes[sku], nivel_sku, libre.x, libre.y, z_destino, presupuesto):
                    clave_necesitado = (z_destino, -area, -pendientes[sku])
                    if mejor_necesitado is None or clave_necesitado < mejor_necesitado[0]:
                        mejor_necesitado = (clave_necesitado, sku, cand, idx_libre)

            if mejor is None:
                break  # nada entra ya en este pallet, ni siquiera más arriba

            _, sku, cand, idx_libre = mejor
            # [combinación por fila] Si el ganador normal ya no necesita ESTA
            # celda concreta (empate real: mismo índice de cuboide libre),
            # se la damos a quien sí la necesita. OJO: si esta celda es
            # continuación de la PROPIA columna del ganador, nunca se cede
            # -eso no es "columna nueva" para él, sin importar cuánta
            # capacidad instalada tenga en otro lado (la excepción de
            # remate ya se aplicó al construir `mejor_necesitado` arriba,
            # así que si llegó hasta acá es porque es un candidato legítimo).
            if mejor_necesitado is not None and mejor_necesitado[1] != sku and mejor_necesitado[3] == idx_libre:
                libre_ganador = pc.libres[idx_libre]
                pos_ganador = (round(libre_ganador.x, 4), round(libre_ganador.y, 4))
                ganador_ya_tiene_esta_columna = pos_ganador in _columnas_actuales_pos(pallet, sku)
                if not ganador_ya_tiene_esta_columna and pendientes[sku] <= _capacidad_instalada(pallet, sku, presupuesto):
                    _, sku, cand, idx_libre = mejor_necesitado
            pc.colocar(cand, 1, idx_libre)
            pendientes[sku] -= 1
            colocado_en_pallet[sku] = colocado_en_pallet.get(sku, 0) + 1
            avanzo_en_este_pallet = True

        if not avanzo_en_este_pallet:
            break  # nada entró en un pallet fresco -evitar loop infinito (no debería pasar tras el chequeo previo)
        pallets.append(pallet)

    return pallets


def _empacar_n_pallets_greedy(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    cd: str,
    contador: list[int],
    n_pallets: int,
) -> tuple[list[PalletV5], dict[str, int]]:
    """[reparto en N pallets fijos -pedido explícito del usuario: "esa
    cantidad de pallet total no puede variar siempre tiene que ser la que
    dice en la planificacion... nosotros lo que tenemos que hacer es
    cubicar de la mejor forma cada pallet"] A diferencia de `_empacar`
    (que abre un pallet nuevo apenas hace falta, hasta agotar la
    demanda), acá se abren los `n_pallets` DESDE EL INICIO -ninguno más,
    ninguno menos- y se reparte TODA la demanda entre ellos. En cada
    intento de colocación se compara la mejor posición de cada SKU
    pendiente en CADA uno de los N pallets (no solo "el pallet actual"),
    así que el barrido llena naturalmente primero los que tengan más
    espacio libre a menor Z -reparte la densidad de forma pareja entre
    los N, sin abrir un pallet N+1 aunque la demanda sea mucha. Reusa
    exactamente el mismo motor exacto (`_mejor_cuboide_para_sku`, mismas
    garantías de soporte real y de orden de nivel) por cada (SKU, pallet)
    candidato -no es un motor aproximado nuevo, es el mismo con un lazo
    exterior más ancho.

    [BASELINE GREEDY -ver `_empacar_n_pallets` más abajo] Esta función es
    la semilla/kill-switch del solver real: `_empacar_n_pallets` la corre
    primero para tener un incumbente de referencia, y solo se queda con
    el resultado del backtracking si estrictamente coloca MÁS cajas -este
    greedy nunca se modifica, así el comportamiento de hoy sigue siendo
    reproducible byte a byte llamando a esta función directamente.

    Devuelve `(pallets, sin_colocar)` -si algún SKU no encuentra lugar en
    NINGUNO de los N pallets ni siquiera en el límite de altura (los N
    pallets están genuinamente llenos), su demanda restante se reporta en
    `sin_colocar` en vez de forzar un pallet extra o exceder la altura
    máxima -nunca se relaja la garantía de altura para cumplir el
    conteo."""
    pallets: list[PalletV5] = []
    construcciones: list[_PalletEnConstruccion] = []
    colocados_por_pallet: list[dict[str, int]] = []
    for _ in range(n_pallets):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        pallets.append(pallet)
        construcciones.append(_PalletEnConstruccion(pallet=pallet))
        colocados_por_pallet.append({})

    guard = 0
    guard_max = 200_000
    presupuesto = _altura_presupuesto()
    while any(v > 0 for v in pendientes.values()):
        guard += 1
        if guard > guard_max:
            break

        mejor = None  # (clave, pallet_idx, sku, cand, idx_libre)
        mejor_necesitado = None  # [combinación por fila] ver _empacar arriba
        for sku, cantidad_pendiente in pendientes.items():
            if cantidad_pendiente <= 0:
                continue
            tope_capa = capacidad_cama_por_sku.get(sku)
            nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
            tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
            for pidx in range(n_pallets):
                if colocados_por_pallet[pidx].get(sku, 0) >= tope_pallet:
                    continue
                pallet = pallets[pidx]
                pc = construcciones[pidx]
                mejor_para_sku_pallet = None
                for cand_op in por_sku[sku]:
                    idx_libre_op = _mejor_cuboide_para_sku(pallet, pc, cand_op, tope_capa, nivel_sku, nivel_por_sku)
                    if idx_libre_op is None:
                        continue
                    libre_op = pc.libres[idx_libre_op]
                    clave_op = (libre_op.z, libre_op.volumen)
                    if mejor_para_sku_pallet is None or clave_op < mejor_para_sku_pallet[0]:
                        mejor_para_sku_pallet = (clave_op, cand_op, idx_libre_op)
                if mejor_para_sku_pallet is None:
                    continue
                _, cand, idx_libre = mejor_para_sku_pallet
                libre = pc.libres[idx_libre]
                z_destino = libre.z
                area = cand.largo * cand.ancho
                clave = (z_destino, nivel_sku, -area, -cantidad_pendiente)
                if mejor is None or clave < mejor[0]:
                    mejor = (clave, pidx, sku, cand, idx_libre)
                # [combinación por fila, ver _empacar arriba]
                if _necesita_columna_nueva(pallet, sku, cantidad_pendiente, nivel_sku, libre.x, libre.y, z_destino, presupuesto):
                    clave_necesitado = (z_destino, -area, -cantidad_pendiente)
                    if mejor_necesitado is None or clave_necesitado < mejor_necesitado[0]:
                        mejor_necesitado = (clave_necesitado, pidx, sku, cand, idx_libre)

        if mejor is None:
            break  # ninguno de los N pallets tiene lugar ya para nada pendiente

        _, pidx, sku, cand, idx_libre = mejor
        # [combinación por fila] misma regla que _empacar: nunca se cede una
        # celda que ya es continuación de la propia columna del ganador (la
        # excepción de remate ya se aplicó al construir `mejor_necesitado`).
        if mejor_necesitado is not None and mejor_necesitado[2] != sku and mejor_necesitado[1] == pidx and mejor_necesitado[4] == idx_libre:
            pallet_ganador = pallets[pidx]
            libre_ganador = construcciones[pidx].libres[idx_libre]
            pos_ganador = (round(libre_ganador.x, 4), round(libre_ganador.y, 4))
            ganador_ya_tiene_esta_columna = pos_ganador in _columnas_actuales_pos(pallet_ganador, sku)
            if not ganador_ya_tiene_esta_columna and pendientes[sku] <= _capacidad_instalada(pallet_ganador, sku, presupuesto):
                _, pidx, sku, cand, idx_libre = mejor_necesitado
        construcciones[pidx].colocar(cand, 1, idx_libre)
        pendientes[sku] -= 1
        colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + 1

    sin_colocar = {sku: cant for sku, cant in pendientes.items() if cant > 0}
    return pallets, sin_colocar


def _recalcular_metricas_pallet(pallet: PalletV5) -> None:
    """Recalcula `altura_final`/`peso_estimado`/`ocupacion_xy`/`volumen_
    utilizado` desde cero a partir de `pallet.torres` -necesario después de
    sacarle torres a un pallet a mano (ver `_redistribuir_dispersos`), ya
    que `_PalletEnConstruccion.colocar` solo actualiza estas métricas de
    forma incremental para el pallet que RECIBE una torre, no para el que
    la pierde."""
    if not pallet.torres:
        pallet.altura_final = 0.0
        pallet.peso_estimado = 0.0
        pallet.ocupacion_xy = 0.0
        pallet.volumen_utilizado = 0.0
        return
    pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in pallet.torres)
    pallet.peso_estimado = sum(t.peso for t in pallet.torres)
    area_ocupada = _area_union_xy(pallet.torres)
    pallet.ocupacion_xy = round(area_ocupada / (config.PALLET_LARGO * config.PALLET_ANCHO), 4)
    pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in pallet.torres), 2)


# [solver exacto de N pallets fijos -pedido explícito del usuario tras el
# intento fallido de "combinación por fila" sobre `_empacar`: "encaremos el
# diseño más grande pero solo usemos como base el pallet 1... si logramos
# replicar ese pallet a la perfección lo demás va a salir"] `_empacar_n_
# pallets_greedy` (arriba) es el mismo motor voraz de siempre -coloca 1
# caja del mejor candidato global por iteración, sin poder deshacer una
# mala decisión. Verificado con `grep -rn "pallets_objetivo"` en todo el
# repo: este camino de código NO tiene ningún llamador de producción
# (`pipeline_sku_bloque.py` nunca pasa `pallets_objetivo`) ni ningún test
# que lo cubra -a diferencia de `_empacar` (que si se toca arriesga el
# dataset de referencia completo vía `_redistribuir_dispersos` +
# consolidación de remanentes, ver el intento de combinación por fila
# fallido documentado arriba), acá se puede construir un backtracking real
# sin miedo a regresionar nada existente. `_empacar_n_pallets` (al final de
# esta sección) es el wrapper nuevo: corre el greedy de siempre como
# semilla/incumbente inicial, corre este backtracking desde cero, y se
# queda con el que coloque MÁS cajas -nunca puede ser peor que hoy.
COMBINACION_PALLETS_SHORTLIST_K = 8
COMBINACION_PALLETS_MAX_NODOS = 30_000
# [medido con datos reales, Pallet 1] Subir esto a 2 o 3 (más de una
# columna candidata por SKU en cada nodo) se probó explícitamente y dio
# PEOR resultado (71/93 en vez de 78/93) con el mismo o más presupuesto de
# nodos -el árbol se diluye entre más ramas por nodo sin encontrar mejores
# combinaciones, en vez de concentrar la búsqueda en qué SKU gana cada
# columna. Con 1 opción por SKU (su mejor cuboide, igual que el greedy) el
# solver ya sube Pallet 1 de 67 a 78 de 93 cajas. Queda como constante (no
# hardcodeado en 1) por si una instancia distinta a Pallet 1 se beneficia
# de más opciones -pero el default validado es 1.
COMBINACION_PALLETS_OPCIONES_POR_SKU = 1

# [LNS -ruina y reconstrucción, ver `_lns_mejorar_pallets`] Medido con
# datos reales (Pallet 1): el resultado del DFS (78/93) es un ÓPTIMO LOCAL
# del modelo de candidatos -sobra más del doble del volumen (917,000 cm³
# libres) que lo que necesitan las 15 cajas restantes (402,000 cm³), así
# que el problema es de búsqueda, no de capacidad física. Ampliar candidatos
# (2 intentos, ver COMBINACION_PALLETS_OPCIONES_POR_SKU arriba) diluye la
# búsqueda y empeora el resultado -acá en cambio se DESHACE una porción ya
# puesta y se reconstruye, escapando del óptimo local sin tocar el criterio
# de prioridad de cada nodo individual.
COMBINACION_PALLETS_LNS_ITERACIONES = 200
COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX = 40
COMBINACION_PALLETS_LNS_SKUS_A_ROMPER = 2
COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION = 3_000
# [multi-reinicio, ver `_empacar_n_pallets`] Una sola corrida de LNS
# depende de la suerte de la semilla -medido con 17 semillas distintas
# contra Pallet 1, la mayoría se queda en el mismo óptimo local del DFS
# (78/93) pero varias llegan a 83/93. Se prueban esta cantidad de semillas
# distintas desde el mismo punto de partida y se conserva el mejor.
COMBINACION_PALLETS_LNS_REINICIOS = 5


def _capacidad_restante_en_capa(pallet: PalletV5, sku: str, z: float, tope_capa: int | None) -> float:
    """Cuántas cajas MÁS de `sku` caben todavía en la capa exacta `z` de
    este pallet antes de tocar `Cajas_Cama_Efectivo` -mismo conteo que ya
    hace `_mejor_cuboide_para_sku` para decidir SI entra, pero acá hace
    falta el número exacto para decidir CUÁNTAS entran de una vez (lote)."""
    if tope_capa is None:
        return float("inf")
    ya_en_esta_capa = sum(t.cantidad for t in pallet.torres if t.sku == sku and abs(t.z - z) <= TOL)
    return max(0, tope_capa - ya_en_esta_capa)


def _snapshot_estado_pallets(
    construcciones: list[_PalletEnConstruccion], colocados_por_pallet: list[dict[str, int]], pendientes: dict[str, int],
) -> tuple[list[tuple[list, list]], list[dict[str, int]], dict[str, int]]:
    """[undo barato, sin deepcopy] `_actualizar_libres_maxrects`
    (`packing_columnar.py`) nunca muta un `_CuboidLibre` existente
    in-place -siempre arma una lista `nuevos` y reasigna `pc.libres` al
    resultado podado- así que alcanza con guardar la referencia a la lista
    VIEJA (O(1)). `pallet.torres` es distinto: `_PalletEnConstruccion.
    colocar` la muta con `.append()` en el mismo objeto lista, así que un
    snapshot posterior en la MISMA rama ve la lista crecer por debajo -
    guardar solo `len(...)` y después recortar la lista ACTUAL con `[:n]`
    falla en cuanto se restaura un snapshot más viejo después de haber
    hecho backtrack más allá de él (la lista ya fue truncada a algo más
    corto por un restore intermedio, y recortarla de nuevo da menos de lo
    que había). Por eso acá se guarda una COPIA real de `pallet.torres`
    (barata: son referencias a `Torre` ya construidas, no deepcopy) en vez
    de solo su longitud."""
    return (
        [(list(pc.pallet.torres), pc.libres) for pc in construcciones],
        [dict(d) for d in colocados_por_pallet],
        dict(pendientes),
    )


def _restaurar_estado_pallets(
    construcciones: list[_PalletEnConstruccion], colocados_por_pallet: list[dict[str, int]], pendientes: dict[str, int],
    snapshot: tuple[list[tuple[list, list]], list[dict[str, int]], dict[str, int]],
) -> None:
    snap_pallets, snap_colocados, snap_pendientes = snapshot
    for pc, (torres, libres) in zip(construcciones, snap_pallets):
        pc.pallet.torres = list(torres)
        pc.libres = libres
        _recalcular_metricas_pallet(pc.pallet)
    for d, snap_d in zip(colocados_por_pallet, snap_colocados):
        d.clear()
        d.update(snap_d)
    pendientes.clear()
    pendientes.update(snap_pendientes)


def _candidatos_lote(
    construcciones: list[_PalletEnConstruccion],
    colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    presupuesto: float,
    n_pallets: int,
) -> list[tuple[tuple, bool, int, str, TorreCandidate, int, int]]:
    """[granularidad de LOTE, no de caja] Para cada (SKU, pallet) activo,
    NO solo el mejor cuboide individual (eso fue la primera versión, y
    quedaba corto: convergía siempre en el mismo 78/93 en Pallet 1 sin
    importar cuánto presupuesto de nodos se le diera, porque cada SKU solo
    aportaba SU propia mejor opción al árbol -nunca "SKU X cede su mejor
    columna y usa la segunda mejor, liberando la primera para otro SKU
    necesitado"). Acá se juntan los top-`COMBINACION_PALLETS_OPCIONES_POR_
    SKU` cuboides DISTINTOS por (SKU, pallet) -no solo 1- antes de armar la
    lista global. Para cada opción se calcula cuántas caben de UNA vez en
    esa columna (tope de capa, tope de PH, profundidad Z del cuboide), se
    ordena todo por el mismo criterio de siempre `(z, nivel, -área,
    -pendiente)`, y se devuelve el top-`COMBINACION_PALLETS_SHORTLIST_K`
    global -garantizando que si hay un candidato que genuinamente necesita
    columna nueva (`_necesita_columna_nueva`, igual que la cesión ya
    shippeada) quede incluido aunque no entre en el top-K por prioridad
    normal."""
    candidatos = []
    for sku in pendientes:
        if pendientes[sku] <= 0:
            continue
        tope_capa = capacidad_cama_por_sku.get(sku)
        nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
        tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
        for pidx in range(n_pallets):
            ya_en_pallet = colocados_por_pallet[pidx].get(sku, 0)
            if ya_en_pallet >= tope_pallet:
                continue
            pallet = construcciones[pidx].pallet
            pc = construcciones[pidx]
            # [top-M cuboides distintos por SKU, no solo el mejor] Para
            # cada orientación, se prueban TODOS los cuboides libres (no
            # solo el mejor de `_mejor_cuboide_para_sku`) y se agrupan por
            # índice de cuboide -cada cuboide se queda con su mejor
            # candidato (menor volumen sobrante), pero se conservan varios
            # cuboides distintos por SKU.
            por_idx: dict[int, tuple[tuple, TorreCandidate]] = {}
            for cand_op in por_sku[sku]:
                for idx_op, c in enumerate(pc.libres):
                    if not _cuboide_admite_candidato(pallet, c, cand_op, tope_capa, nivel_sku, nivel_por_sku):
                        continue
                    clave_op = (c.z, c.volumen)
                    actual = por_idx.get(idx_op)
                    if actual is None or clave_op < actual[0]:
                        por_idx[idx_op] = (clave_op, cand_op)
            opciones = sorted(
                ((clave_op, idx_op, cand_op) for idx_op, (clave_op, cand_op) in por_idx.items()),
                key=lambda o: o[0],
            )[:COMBINACION_PALLETS_OPCIONES_POR_SKU]
            for _, idx_libre, cand in opciones:
                libre = pc.libres[idx_libre]
                cantidad = min(
                    pendientes[sku],
                    tope_pallet - ya_en_pallet,
                    _capacidad_restante_en_capa(pallet, sku, libre.z, tope_capa),
                    int((libre.d + TOL) // cand.alto_caja),
                )
                if cantidad <= 0:
                    continue
                area = cand.largo * cand.ancho
                necesita = _necesita_columna_nueva(
                    pallet, sku, pendientes[sku], nivel_sku, libre.x, libre.y, libre.z, presupuesto
                )
                clave = (libre.z, nivel_sku, -area, -pendientes[sku])
                candidatos.append((clave, necesita, pidx, sku, cand, idx_libre, int(cantidad)))

    candidatos.sort(key=lambda c: c[0])
    top = candidatos[:COMBINACION_PALLETS_SHORTLIST_K]
    if not any(c[1] for c in top):
        necesitado = next((c for c in candidatos if c[1]), None)
        if necesitado is not None:
            top.append(necesitado)
    return top


def _resolver_pallets_backtracking(
    construcciones: list[_PalletEnConstruccion],
    colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    presupuesto: float,
    n_pallets: int,
    max_nodos: int = COMBINACION_PALLETS_MAX_NODOS,
) -> int:
    """[backtracking real, DFS con poda] A diferencia del greedy (1 caja,
    sin vuelta atrás), acá cada nodo coloca un LOTE completo -toda una
    columna de una vez- y puede DESHACERLO si la rama no mejora el mejor
    resultado encontrado (`_snapshot_estado_pallets`/`_restaurar_estado_
    pallets`). La primera rama que explora cada nodo es siempre la de
    mayor prioridad (misma clave que usa el greedy) -así la primera hoja
    completa que encuentra ya iguala el resultado de hoy; de ahí en más
    solo puede empatar o mejorar. Acotado por
    `COMBINACION_PALLETS_MAX_NODOS` (conteo de nodos, no de reloj -
    reproducible entre corridas). Modifica `construcciones`/`colocados_
    por_pallet`/`pendientes` IN-PLACE, dejándolos en el MEJOR estado
    encontrado al terminar -no devuelve una copia."""
    demanda_inicial = sum(pendientes.values())
    estado = {"mejor_total": -1, "mejor_snapshot": None, "nodos": 0}

    def _volumen_libre_total() -> float:
        return sum(c.w * c.h * c.d for pc in construcciones for c in pc.libres)

    def _cota(colocado_actual: int) -> int:
        pendiente_total = sum(pendientes.values())
        if pendiente_total == 0:
            return colocado_actual
        volumenes_min = [
            min(cand.largo * cand.ancho * cand.alto_caja for cand in por_sku[sku])
            for sku, cant in pendientes.items() if cant > 0 and por_sku.get(sku)
        ]
        if not volumenes_min:
            return colocado_actual
        vol_min_caja = min(volumenes_min)
        cota_volumen = int(_volumen_libre_total() // vol_min_caja) if vol_min_caja > 0 else pendiente_total
        return colocado_actual + min(pendiente_total, cota_volumen)

    def _dfs(colocado_actual: int) -> None:
        estado["nodos"] += 1
        if colocado_actual > estado["mejor_total"]:
            estado["mejor_total"] = colocado_actual
            estado["mejor_snapshot"] = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
        if estado["nodos"] > max_nodos:
            return
        if colocado_actual >= demanda_inicial:
            return  # se colocó TODO -óptimo absoluto, no hay nada más que buscar
        if _cota(colocado_actual) <= estado["mejor_total"]:
            return  # ni en el mejor caso esta rama supera lo ya encontrado
        candidatos = _candidatos_lote(
            construcciones, colocados_por_pallet, pendientes, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
        )
        if not candidatos:
            return
        for _, _, pidx, sku, cand, idx_libre, cantidad in candidatos:
            snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            construcciones[pidx].colocar(cand, cantidad, idx_libre)
            pendientes[sku] -= cantidad
            colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + cantidad
            _dfs(colocado_actual + cantidad)
            _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
            if estado["nodos"] > max_nodos:
                break

    _dfs(demanda_inicial - sum(pendientes.values()))
    if estado["mejor_snapshot"] is not None:
        _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, estado["mejor_snapshot"])
    return estado["mejor_total"]


def _romper_skus_con_cascada(
    construcciones: list[_PalletEnConstruccion],
    colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int],
    elegidos: set[str],
    n_pallets: int,
) -> None:
    """[ruina, ver `_lns_mejorar_pallets`] Saca todas las torres de los
    SKUs `elegidos` de TODOS los pallets, devuelve sus cajas a
    `pendientes`, y reconstruye el espacio libre desde cero para cada
    pallet (mismo mecanismo que `_redistribuir_dispersos` usa para
    reinsertar torres sueltas).

    [bug real encontrado y corregido en esta sesión: "caja flotando"]
    Sacar SOLO las torres de los SKUs elegidos podía dejar OTRA torre (de
    un SKU distinto, no elegido) sin soporte real debajo si estaba
    apoyada justo encima de una de las removidas -acá se remueve en
    CASCADA: después de sacar las elegidas, cualquier torre que quede sin
    soporte real en TODA su huella (mismo criterio exacto que
    `validacion_v5._area_cubierta_por_soporte`, el que usa el gate de
    geometría) también se saca, devolviendo su SKU a `pendientes` -y se
    repite hasta que no quede ninguna inestable (puede haber cadenas de
    más de 1 nivel). Modifica `construcciones`/`colocados_por_pallet`/
    `pendientes` IN-PLACE."""
    for pidx in range(n_pallets):
        pc = construcciones[pidx]
        restantes = list(pc.pallet.torres)
        elegidos_pallet = set(elegidos)  # copia local -la cascada de ESTE pallet no debe afectar a los demás
        while True:
            nuevas_restantes = []
            cambio = False
            for t in restantes:
                if t.sku in elegidos_pallet:
                    cambio = True
                    continue
                if t.z > TOL:
                    soportes = [
                        o for o in restantes
                        if o is not t and o.sku not in elegidos_pallet and abs((o.z + o.altura) - t.z) <= TOL
                    ]
                    area_cubierta = _area_cubierta_por_soporte(t, soportes)
                    if area_cubierta < t.largo * t.ancho - TOL:
                        elegidos_pallet.add(t.sku)  # se agrega a la ronda de remoción, cascada
                        cambio = True
                        continue
                nuevas_restantes.append(t)
            restantes = nuevas_restantes
            if not cambio:
                break
        ids_restantes = {id(t) for t in restantes}
        for t in pc.pallet.torres:
            if id(t) not in ids_restantes:
                pendientes[t.sku] = pendientes.get(t.sku, 0) + t.cantidad
                colocados_por_pallet[pidx][t.sku] = colocados_por_pallet[pidx].get(t.sku, 0) - t.cantidad
        pc.pallet.torres = restantes
        _recalcular_metricas_pallet(pc.pallet)
        construcciones[pidx] = _reconstruir_en_construccion(pc.pallet)


def _lns_mejorar_pallets(
    construcciones: list[_PalletEnConstruccion],
    colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    presupuesto: float,
    n_pallets: int,
    semilla: str,
) -> int:
    """[LNS -ruina y reconstrucción, ver comentario junto a las
    constantes `COMBINACION_PALLETS_LNS_*`] Complementa el DFS de
    `_resolver_pallets_backtracking`: parte del incumbente YA construido
    en `construcciones`/`colocados_por_pallet` (no arranca de cero), y en
    cada iteración DESHACE todas las columnas de un par de SKUs elegidos
    al azar -sus cajas vuelven a `pendientes`- y vuelve a correr el mismo
    backtracking (con un presupuesto de nodos más chico,
    `COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION`, porque acá se
    corre muchas veces) sobre la demanda liberada + lo que ya estaba
    pendiente. Si el total colocado mejora, se queda con el resultado
    nuevo; si no, se revierte al mejor incumbente conocido
    (`_snapshot_estado_pallets`/`_restaurar_estado_pallets`, el mismo
    mecanismo de undo del DFS). Corta por iteraciones sin mejora
    consecutivas (`COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX`) o por el total
    de iteraciones (`COMBINACION_PALLETS_LNS_ITERACIONES`) -RNG con
    semilla fija (derivada de `cd`+`n_pallets` por el caller) para que el
    resultado sea reproducible entre corridas. Modifica `construcciones`/
    `colocados_por_pallet`/`pendientes` IN-PLACE, igual que el DFS.
    Devuelve el total de cajas colocadas en TODOS los pallets (no un delta
    relativo a esta llamada, a diferencia de `_resolver_pallets_
    backtracking`)."""
    rng = random.Random(semilla)

    def _total_colocado() -> int:
        return sum(sum(d.values()) for d in colocados_por_pallet)

    mejor_total = _total_colocado()
    mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
    sin_mejora = 0

    for _ in range(COMBINACION_PALLETS_LNS_ITERACIONES):
        if sin_mejora >= COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX:
            break
        skus_colocados = sorted({sku for d in colocados_por_pallet for sku, cant in d.items() if cant > 0})
        if not skus_colocados:
            break
        k = min(COMBINACION_PALLETS_LNS_SKUS_A_ROMPER, len(skus_colocados))
        elegidos = set(rng.sample(skus_colocados, k))

        _romper_skus_con_cascada(construcciones, colocados_por_pallet, pendientes, elegidos, n_pallets)

        # [reconstrucción] Mismo backtracking, presupuesto de nodos más
        # chico -acá se corre muchas veces, no una sola.
        _resolver_pallets_backtracking(
            construcciones, colocados_por_pallet, pendientes, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
            max_nodos=COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION,
        )

        total_actual = _total_colocado()
        if total_actual > mejor_total:
            mejor_total = total_actual
            mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            sin_mejora = 0
        else:
            _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor_snapshot)
            sin_mejora += 1

    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor_snapshot)
    return mejor_total


def _empacar_n_pallets(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    cd: str,
    contador: list[int],
    n_pallets: int,
) -> tuple[list[PalletV5], dict[str, int]]:
    """[wrapper -ver comentario de sección arriba] Corre el greedy de
    siempre (`_empacar_n_pallets_greedy`) para tener un incumbente de
    referencia, corre el backtracking real desde cero (mismos `pendientes`
    originales, pallets frescos -no continúa desde el estado ya "atascado"
    del greedy), y si todavía queda demanda sin colocar corre además LNS
    (`_lns_mejorar_pallets`, ruina y reconstrucción) sobre el resultado del
    backtracking -medido con datos reales (Pallet 1) que el DFS solo llega
    a un ÓPTIMO LOCAL (78/93) con volumen de sobra, ver comentario junto a
    `COMBINACION_PALLETS_LNS_ITERACIONES`. Se queda con el que haya
    colocado MÁS cajas -empate prefiere el greedy (determinismo, cero
    superficie de cambio nueva). El backtracking (y por lo tanto todo el
    resultado final) nunca puede dar menos que el greedy porque su primera
    rama explorada reproduce exactamente la misma prioridad."""
    pallets_greedy, sin_colocar_greedy = _empacar_n_pallets_greedy(
        dict(pendientes), por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, n_pallets,
    )
    total_greedy = sum(t.cantidad for p in pallets_greedy for t in p.torres)

    demanda_total = sum(pendientes.values())
    if total_greedy >= demanda_total:
        return pallets_greedy, sin_colocar_greedy  # ya se colocó todo -no hace falta buscar más

    presupuesto = _altura_presupuesto()
    pallets_bt: list[PalletV5] = []
    construcciones_bt: list[_PalletEnConstruccion] = []
    colocados_bt: list[dict[str, int]] = []
    for _ in range(n_pallets):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd)
        pallets_bt.append(pallet)
        construcciones_bt.append(_PalletEnConstruccion(pallet=pallet))
        colocados_bt.append({})
    pendientes_bt = dict(pendientes)

    _resolver_pallets_backtracking(
        construcciones_bt, colocados_bt, pendientes_bt, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
    )
    total_bt = sum(sum(d.values()) for d in colocados_bt)

    if total_bt < demanda_total:
        # [multi-reinicio -medido con datos reales, Pallet 1] Una sola
        # corrida de LNS depende de la suerte de la semilla: probado con 17
        # semillas distintas, el resultado varía entre 78 y 83 -la mayoría
        # se queda en 78 (el mismo óptimo local del DFS solo), pero varias
        # sí llegan a 83. En vez de confiar en una semilla fija, se prueban
        # `COMBINACION_PALLETS_LNS_REINICIOS` semillas (derivadas de
        # `cd`+`n_pallets`+número de intento, reproducibles) desde el MISMO
        # punto de partida (el incumbente del DFS) y se conserva el mejor.
        snapshot_dfs = _snapshot_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt)
        mejor_total_lns = total_bt
        mejor_snapshot_lns = snapshot_dfs
        for intento in range(COMBINACION_PALLETS_LNS_REINICIOS):
            _restaurar_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt, snapshot_dfs)
            total_intento = _lns_mejorar_pallets(
                construcciones_bt, colocados_bt, pendientes_bt, por_sku,
                capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
                semilla=f"{cd}-{n_pallets}-{intento}",
            )
            if total_intento > mejor_total_lns:
                mejor_total_lns = total_intento
                mejor_snapshot_lns = _snapshot_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt)
            if mejor_total_lns >= demanda_total:
                break  # ya se colocó TODO -no hace falta seguir probando semillas
        _restaurar_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt, mejor_snapshot_lns)
        total_bt = mejor_total_lns

    if total_bt > total_greedy:
        sin_colocar_bt = {sku: cant for sku, cant in pendientes_bt.items() if cant > 0}
        return pallets_bt, sin_colocar_bt
    return pallets_greedy, sin_colocar_greedy


# [sección 8, redistribución de dispersos] Un pallet por debajo de este
# umbral de ocupación XY es candidato a vaciarse hacia los pallets ya
# armados del mismo CD -ver `_redistribuir_dispersos`.
UMBRAL_OCUPACION_DISPERSO = 0.5


def _redistribuir_dispersos(
    pallets: list[PalletV5],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
) -> list[PalletV5]:
    """[sección 8] Un SKU de poca demanda puede perder la competencia por
    espacio en TODOS los pallets ya cerrados -no porque no hubiera lugar
    real, sino simplemente por el orden en que el barrido lo fue dejando
    para el final- y terminar solo, en su propio pallet casi vacío, recién
    cuando ya no queda nada más con qué competir.

    Antes de aceptar un pallet muy vacío (`UMBRAL_OCUPACION_DISPERSO`), se
    intenta mover cada una de sus torres al espacio libre REAL (MaxRects
    reconstruido, `_reconstruir_en_construccion` -mismo motor exacto, sin
    relajar ninguna garantía) de los demás pallets YA armados del mismo
    CD, respetando los mismos topes (`Cajas_Cama_Efectivo`, `Cajas por
    PH`) y el mismo orden de categoría que el armado original. Si TODAS
    sus torres encuentran lugar, el pallet disperso desaparece entero; si
    solo algunas, se queda con lo que no entró en ningún lado."""
    dispersos = [
        p for p in pallets
        if p.torres and (p.ocupacion_xy or 0) < UMBRAL_OCUPACION_DISPERSO
    ]
    if not dispersos:
        return pallets

    ids_dispersos = {id(p) for p in dispersos}
    destinos = [p for p in pallets if id(p) not in ids_dispersos]
    if not destinos:
        return pallets  # no hay a dónde mover nada

    resultado = list(destinos)
    for disperso in dispersos:
        torres_restantes = []
        for t in disperso.torres:
            nivel_sku = nivel_por_sku.get(t.sku, config.NIVEL_REMATE)
            tope_capa = capacidad_cama_por_sku.get(t.sku)
            tope_pallet = tope_pallet_por_sku.get(t.sku)
            cand = TorreCandidate(
                sku=t.sku, cd=t.cd, orientacion=t.orientacion, largo=t.largo, ancho=t.ancho,
                alto_caja=t.alto_caja, max_cajas_verticales=t.cantidad, cantidad_disponible=t.cantidad,
                peso_unitario=(t.peso / t.cantidad if t.cantidad else 0.0), fuente_geometria=t.fuente_geometria,
            )
            movida = False
            for destino in destinos:
                if tope_pallet is not None:
                    ya_en_destino = sum(tt.cantidad for tt in destino.torres if tt.sku == t.sku)
                    if ya_en_destino + t.cantidad > tope_pallet:
                        continue
                pc = _reconstruir_en_construccion(destino)
                idx_libre = _mejor_cuboide_para_sku(destino, pc, cand, tope_capa, nivel_sku, nivel_por_sku)
                if idx_libre is None:
                    continue
                pc.colocar(cand, t.cantidad, idx_libre)
                movida = True
                break
            if not movida:
                torres_restantes.append(t)

        if torres_restantes:
            disperso.torres = torres_restantes
            _recalcular_metricas_pallet(disperso)
            resultado.append(disperso)
        # si se movieron todas, el disperso no se agrega -desaparece.

    return resultado


# [sección 5] Un pallet por debajo de este umbral (fracción del
# presupuesto de altura de producto) es candidato a reempacarse junto con
# otros remanentes cortos -60% es conservador a propósito: no vale la pena
# deshacer un pallet que ya está razonablemente aprovechado solo para
# intentar exprimir el último margen.
UMBRAL_CONSOLIDACION_FRACCION = 0.6
MAX_INTENTOS_CONSOLIDACION = 3


def armar_pallets_bloques(
    df_cd: pd.DataFrame, cd: str, contador: list[int] | None = None, pallets_objetivo: int | None = None,
) -> list[PalletV5]:
    """[V-SKU_BLOQUE, camas] Punto de entrada. `df_cd` debe traer demanda
    pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría
    efectiva reconciliada y, si está disponible, `Cajas_Cama_Efectivo`
    (derivados.py) -sin esa columna, una capa no tiene tope propio más que
    la huella/orientación elegida.

    `pallets_objetivo` -pedido explícito del usuario: "esa cantidad de
    pallet total no puede variar siempre tiene que ser la que dice en la
    planificacion... nosotros lo que tenemos que hacer es cubicar de la
    mejor forma cada pallet"- es la cifra FIJA de pallets que ya viene
    decidida por la planificación externa (factor de PH físicas), subida
    por el usuario -el agente NO la calcula ni la ajusta. Si se pasa, el
    armado usa `_empacar_n_pallets` (reparte TODA la demanda del CD entre
    exactamente esa cantidad de pallets, sin abrir ni cerrar ninguno de
    más) en vez de `_empacar` (que abre pallets hasta agotar la demanda,
    el comportamiento de siempre si no se pasa este parámetro)."""
    contador = contador if contador is not None else [0]

    # [sección 6, orientación flexible] Comestibles/Aseo/Cigarros pueden
    # acostarse/voltearse -se les genera el set COMPLETO de 6 orientaciones
    # en vez de las 2 "de pie" de siempre. El resto de las categorías
    # (NABs incluido, pedido explícito: "nabs es el unico que siempre
    # tiene que ir de pie") sigue con `generar_torres_candidatas` normal.
    if "Categoria_Normalizada" in df_cd.columns:
        es_flexible = df_cd["Categoria_Normalizada"].isin(CATEGORIAS_ORIENTACION_FLEXIBLE)
        df_flexible, df_normal = df_cd[es_flexible], df_cd[~es_flexible]
    else:
        df_flexible, df_normal = df_cd.iloc[0:0], df_cd

    candidatas = generar_torres_candidatas(df_normal, config.ALTURA_PRODUCTO_MAX)
    candidatas += generar_torres_candidatas_todas_orientaciones(df_flexible, config.ALTURA_PRODUCTO_MAX)
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

    # [sección 4, nivel por peso/soporte] Licores (nivel 1, el más pesado)
    # nunca queda apoyado sobre nada de nivel mayor -pero SÍ puede compartir
    # cama con otras categorías (ver `_soporte_viola_nivel`, sin
    # exclusividad de cama). Se recorta cualquier nivel >= NIVEL_REMATE
    # (incluye NIVEL_CIGARROS de la pseudo-fila BAT, ver bat.py, y
    # cualquier SKU forzado a remate por Subcategoría RTD/Energizante -
    # Four Loko, ver derivados.py) a exactamente NIVEL_REMATE -así Cigarros
    # ya no es "siempre lo más alto obligatorio" (pedido explícito del
    # usuario), es un miembro más del grupo de remate, en igualdad de
    # condiciones con Comestibles.
    nivel_por_sku: dict[str, int] = {}
    if "Nivel_Categoria" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            nivel = fila.get("Nivel_Categoria")
            nivel_val = int(nivel) if pd.notna(nivel) else config.NIVEL_REMATE
            nivel_por_sku[sku] = min(nivel_val, config.NIVEL_REMATE)
    for sku in por_sku:
        nivel_por_sku.setdefault(sku, config.NIVEL_REMATE)

    # [sección 7] `Cajas por PH` real del Maestro -tope físico de cuántas
    # cajas de un SKU pueden ir en UN pallet (homogéneo o mezclado).
    tope_pallet_por_sku: dict[str, int] = {}
    if "Cajas por PH" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            cph = fila.get("Cajas por PH")
            if pd.notna(cph) and cph > 0:
                tope_pallet_por_sku[sku] = int(cph)

    presupuesto = _altura_presupuesto()

    # [chequeo previo] Un SKU que ni siquiera entra en un pallet VACÍO en
    # NINGUNA orientación nunca va a entrar en ninguno más lleno -se marca
    # sin_colocar ANTES de abrir pallets, para no abrir uno tras otro sin
    # poder nunca resolverlo. Se prueban todas las orientaciones acá (no
    # solo la preferida) -el fallback de orientación del barrido principal
    # puede rescatar una SKU cuya orientación de mejor grilla no entra pero
    # la rotada sí.
    sin_colocar: dict[str, int] = {}
    for sku in list(pendientes):
        if pendientes[sku] <= 0:
            continue
        if not any(_cabe_en_pallet(cand, presupuesto) for cand in por_sku[sku]):
            sin_colocar[sku] = pendientes[sku]
            pendientes[sku] = 0

    if pallets_objetivo is not None and pallets_objetivo > 0:
        # [reparto en N pallets fijos] Sin abrir-hasta-agotar ni
        # consolidación de remanentes -esos mecanismos existen para
        # decidir CUÁNTOS pallets hacen falta, pregunta que acá ya está
        # respondida desde afuera. Tampoco se corre `_redistribuir_
        # dispersos`: mover contenido de un pallet a otro podría dejar
        # alguno vacío y reducir el conteo por debajo de lo pedido.
        pallets, sin_colocar_barrido = _empacar_n_pallets(
            pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            cd, contador, pallets_objetivo,
        )
        for sku, cant in sin_colocar_barrido.items():
            sin_colocar[sku] = sin_colocar.get(sku, 0) + cant
    else:
        pallets = _empacar(
            pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, cd, contador
        )

        # [sección 5] Consolidación de remanentes: los pallets que quedaron
        # muy cortos se deshacen y se reempacan juntos -si mejora (menos
        # pallets), se queda con el resultado nuevo; si no, se descarta sin
        # tocar nada.
        umbral = presupuesto * UMBRAL_CONSOLIDACION_FRACCION
        for _intento in range(MAX_INTENTOS_CONSOLIDACION):
            cortos = [p for p in pallets if (p.altura_final - config.ALTURA_PALLET_VACIO) < umbral]
            if len(cortos) < 2:
                break
            pendientes_residual: dict[str, int] = {}
            for p in cortos:
                for t in p.torres:
                    pendientes_residual[t.sku] = pendientes_residual.get(t.sku, 0) + t.cantidad
            reempacados = _empacar(
                pendientes_residual, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                presupuesto, cd, contador,
            )
            if len(reempacados) >= len(cortos):
                break  # no mejoró -se descarta el intento, se conserva lo que ya había
            ids_cortos = {id(p) for p in cortos}
            pallets = [p for p in pallets if id(p) not in ids_cortos] + reempacados

        # [sección 8] Después del barrido y la consolidación, algunos SKUs
        # de poca demanda pueden haber quedado solos en su propio pallet
        # casi vacío -se intenta repartirlos en el espacio libre real de
        # los pallets ya armados antes de aceptarlos como pallets aparte.
        pallets = _redistribuir_dispersos(pallets, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku)

    if sin_colocar and pallets:
        pallets[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        pallets.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return pallets
