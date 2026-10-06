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
import multiprocessing
import os
import random
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import (
    _actualizar_libres_maxrects,
    _altura_presupuesto,
    _area_union_xy,
    _CuboidLibre,
    _PalletEnConstruccion,
    _reconstruir_en_construccion,
)
from src.validacion_v5 import _tiene_soporte_admisible
from src import diagnostico_no_colocadas
from src.torres import (
    TorreCandidate,
    crear_torre,
    generar_torres_candidatas,
    generar_torres_candidatas_todas_orientaciones,
)

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
    cols = int(config.PALLET_LARGO_EFECTIVO // cand.largo)
    filas = int(config.PALLET_ANCHO_EFECTIVO // cand.ancho)
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


def _solapa_con_torres(pallet: PalletV5, x: float, y: float, z: float, w: float, h: float, d: float) -> bool:
    """[Refinamiento 'tolerancia de sobresaliente'] True si la caja
    (x,y,z,w,h,d) se solaparía con alguna `Torre` YA colocada en el pallet
    -mismo criterio de solape AABB que usa MaxRects (`_se_solapan`,
    packing_columnar.py), aplicado acá contra geometría OCUPADA en vez de
    contra cuboides libres. Único chequeo de seguridad del sobresaliente:
    nunca puede aterrizar sobre otra caja, solo sobre aire completamente
    libre."""
    for t in pallet.torres:
        if (
            t.x < x + w - TOL and x < t.x + t.largo - TOL
            and t.y < y + h - TOL and y < t.y + t.ancho - TOL
            and t.z < z + d - TOL and z < t.z + t.altura - TOL
        ):
            return True
    return False


# [PATCH V6.12-FASE1D, orden de predicados] Auditoría real sobre 500.000
# llamadas capturadas de BK52+BK53 (evaluando los 3 checks SIN
# short-circuit): FIT (directo/tolerancia) es más selectivo Y más barato
# que OVERHANG (el más caro de los 3 -180.84ns/call vs 95.97ns FIT/72.78ns
# HEIGHT, medido con `time.perf_counter()`, sin cProfile). El orden previo
# (OVERHANG->HEIGHT->FIT, el mismo con el que arrancaba este código) era
# el PEOR de las 6 permutaciones posibles en la simulación por
# probabilidad-conjunta-real x costo; FIT->HEIGHT->OVERHANG fue la mejor,
# confirmada con un microbenchmark offline real (no solo simulado): 100%
# equivalencia booleana (500.000 llamadas reales + 9 edge cases -límite
# exacto de overhang/altura/fit, tolerancia activada y desactivada, fallo
# simultáneo de 2 y 3 checks- 0 diferencias) y +27.42% (BK52) / +16.25%
# (BK53) / +21.06% (combinado) de mejora. Mismas comparaciones, misma
# tolerancia, mismo resultado -solo cambia el ORDEN en que se evalúan.
#
# [SINCRONIZACIÓN OBLIGATORIA] `_cuboide_admite_candidato` (más abajo) NO
# llama a esta función -tiene su PROPIA copia inlineada de esta misma
# lógica (mismo orden FIT->HEIGHT->OVERHANG, mismas subrutinas reales) por
# el costo de la capa extra de llamada Python en un hot path de 116-142
# millones de llamadas/CD (ver comentario junto a `_cuboide_admite_
# candidato`). Cualquier cambio de comparación, tolerancia o criterio
# físico ACÁ debe replicarse EXACTO ahí también -y viceversa- o las dos
# funciones divergen en silencio. Antes de aceptar un cambio en cualquiera
# de las dos, re-correr `tests/test_packing_bloques_predicate_order.py`
# (los 9 casos límite) contra AMBAS.
def _fit_directo_o_con_tolerancia(pallet: PalletV5, c, cand: TorreCandidate) -> bool:
    """Admite hasta 2 cm por lado, con apoyo real y sin colisiones.

    El margen de soporte se aplica a ambos ejes y es independiente de
    si la categoría permite acostar la caja. La posición debe respetar
    además el margen exterior de la parihuela.
    """
    directo = cand.largo <= c.w + TOL and cand.ancho <= c.h + TOL
    if not directo:
        tolerancia = config.TOLERANCIA_OVERHANG_CM
        if (cand.largo > c.w + tolerancia + TOL
                or cand.ancho > c.h + tolerancia + TOL):
            return False
    if cand.alto_caja > c.d + TOL:
        return False
    margen = config.SOBRESALIENTE_MAX_CM
    if (c.x < -margen - TOL or c.y < -margen - TOL
            or c.x + cand.largo > config.PALLET_LARGO + margen + TOL
            or c.y + cand.ancho > config.PALLET_ANCHO + margen + TOL):
        return False
    if directo:
        return True  # MaxRects ya garantiza espacio libre y apoyo en el cuboide.
    if _solapa_con_torres(pallet, c.x, c.y, c.z, cand.largo, cand.ancho, cand.alto_caja):
        return False
    if c.z > TOL:
        soportes = [t for t in pallet.torres if abs(t.z + t.altura - c.z) <= TOL]
        torre = crear_torre(cand, x=c.x, y=c.y, z=c.z, cantidad=1)
        if not _tiene_soporte_admisible(torre, soportes):
            return False
    return True


def _cantidad_sin_solape(pallet, c, cand, cantidad):
    """Acota el lote completo: el vuelo puede chocar con una caja más arriba."""
    for t in pallet.torres:
        if (t.x < c.x + cand.largo - TOL and c.x < t.x + t.largo - TOL
                and t.y < c.y + cand.ancho - TOL and c.y < t.y + t.ancho - TOL
                and t.z + t.altura > c.z + TOL):
            cantidad = min(cantidad, max(0, int((t.z - c.z + TOL) // cand.alto_caja)))
    return cantidad


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
    pallets fijos (varias opciones por SKU, ver comentario ahí).

    [PATCH V6.12-FASE1D] Esta es la función MÁS llamada de todo el motor
    (116-142 millones de veces por CD en BK52/BK53, ver auditoría Fase 0/
    1A/1D) -antes delegaba en `_fit_directo_o_con_tolerancia` como llamada
    aparte; ahora inlinea esa misma lógica YA reordenada (FIT->HEIGHT->
    OVERHANG, ver comentario junto a `_fit_directo_o_con_tolerancia`)
    directo acá, para no pagar la capa extra de llamada Python en el hot
    path -el reorden solo (sin inlinear) medía 14.46% combinado en
    BK52+BK53 (por debajo del gate de 15%); inlineado da 27.42%/16.25%/
    21.06% (BK52/BK53/combinado), 100% equivalente contra el original en
    500.000 llamadas reales + 9 edge cases. `_fit_directo_o_con_
    tolerancia` se mantiene intacta como función propia (la usan tests
    directamente) pero ya no la llama esta función.

    [SINCRONIZACIÓN OBLIGATORIA] El bloque de abajo (FIT->HEIGHT->
    OVERHANG, mismas subrutinas reales: `_solapa_con_torres`, `_tiene_
    soporte_admisible`, `_soporte_viola_nivel`, `_altura_compatible_con_
    cama`) es una copia intencional de `_fit_directo_o_con_tolerancia`
    -ver el comentario junto a esa función sobre por qué existen las dos y
    la obligación de mantenerlas sincronizadas ante cualquier cambio de
    comparación/tolerancia/criterio físico."""
    directo = cand.largo <= c.w + TOL and cand.ancho <= c.h + TOL
    if not directo:
        tolerancia = config.TOLERANCIA_OVERHANG_CM
        if (cand.largo > c.w + tolerancia + TOL
                or cand.ancho > c.h + tolerancia + TOL):
            return False
    if cand.alto_caja > c.d + TOL:
        return False
    margen = config.SOBRESALIENTE_MAX_CM
    if (c.x < -margen - TOL or c.y < -margen - TOL
            or c.x + cand.largo > config.PALLET_LARGO + margen + TOL
            or c.y + cand.ancho > config.PALLET_ANCHO + margen + TOL):
        return False
    if not directo:
        if _solapa_con_torres(pallet, c.x, c.y, c.z, cand.largo, cand.ancho, cand.alto_caja):
            return False
        if c.z > TOL:
            soportes = [t for t in pallet.torres if abs(t.z + t.altura - c.z) <= TOL]
            torre = crear_torre(cand, x=c.x, y=c.y, z=c.z, cantidad=1)
            if not _tiene_soporte_admisible(torre, soportes):
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


def _hay_torre_mismo_sku_en_xy(pallet: PalletV5, sku: str, x: float, y: float) -> bool:
    """[Refinamiento 'seguir la misma torre' -pedido explícito del usuario
    tras la sesión BK31: se prefirió apilar una 4ta caja de Altomayo sobre
    las 3 que ya estaban en vez de meter un SKU distinto en el mismo lugar,
    aunque ambos hubieran calzado igual de bien] True si el pallet ya tiene
    una `Torre` de `sku` exactamente en (x,y) -pasa cuando el cuboide libre
    se abrió justo encima de una torre existente del mismo SKU (mismo
    footprint, `_actualizar_libres_maxrects` en packing_columnar.py). Usado
    solo como DESEMPATE en `_candidatos_lote` (ver comentario ahí) -nunca
    cambia qué es geométricamente válido."""
    return any(t.sku == sku and abs(t.x - x) <= TOL and abs(t.y - y) <= TOL for t in pallet.torres)


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
                # [Refinamiento 'seguir la misma torre', mismo criterio que
                # _candidatos_lote -desempate DESPUÉS de -area, nunca antes]
                mismo_sku_continua = 0 if _hay_torre_mismo_sku_en_xy(pallet, sku, libre.x, libre.y) else 1
                clave = (z_destino, nivel_sku, -area, mismo_sku_continua, -pendientes[sku])
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


def _reservar_skus_grandes(
    construcciones: list[_PalletEnConstruccion],
    colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    n_pallets: int,
    presupuesto: float,
) -> frozenset[str]:
    """[Refinamiento 'grandes primero' -pedido explícito del usuario tras
    comparar BK31 (Pallets_Objetivo=1) a mano vs. el motor real: el motor
    dejaba a Picaras (el footprint más grande de la demanda) sin ningún
    hueco contiguo, porque SKUs más chicos fragmentaban el piso antes de
    que le tocara competir. 3 intentos previos (documentados en
    PATCH_LOG.md) probaron: (1) reservar de a un SKU por vez -el primero
    devoraba el piso y dejaba a los demás sin lugar; (2) turnos de 1 caja
    por SKU -esparcía cada SKU por todo el piso en vez de apilarlo
    compacto; (3) turnos de 1 COLUMNA completa por SKU -mejoró mucho pero
    seguía fragmentando: como cada SKU competía por SU cuboide más barato
    de forma aislada (sin saber qué haría el próximo SKU), las columnas de
    medidas distintas (24x31 Vino, 28.5x30/30x39 Picaras, etc, sin
    múltiplos comunes) dejaban huecos que no calzaban entre sí -confirmado
    con datos reales: 54% de piso libre en área total, pero fragmentado en
    formas que no servían para Vino.

    **Este intento (shelf-packing conjunto, Shelf-First-Fit-Decreasing-
    Height, técnica estándar de bin-packing 2D):** en vez de que cada SKU
    busque su propio hueco por separado, se arman "estantes" explícitos a
    lo ancho del pallet (franjas en Y), cada uno con la profundidad del
    primer SKU que lo abre -TODOS los SKUs (no solo los "grandes") compiten
    por el MISMO estante abierto, en orden de profundidad decreciente
    (clásico del shelf-packing: los más profundos primero, para que los
    más angostos rellenen el resto del ancho del estante después). Esto es
    lo que de verdad reproduce el armado a mano: Vino en su grilla regular,
    Picaras en su propia franja de 3 carriles al lado, ambos coordinados
    por el mismo proceso en vez de competir a ciegas cuboide por cuboide.

    Para cada SKU se elige la orientación que minimiza el ÁREA TOTAL que
    necesita (`columnas_necesarias x largo x ancho`, considerando cuántas
    capas entran verticalmente en el presupuesto de altura) -ya no
    necesariamente el footprint mínimo por unidad, sino la mejor combinación
    área/altura para TODA su demanda.

    Modifica `construcciones`/`colocados_por_pallet`/`pendientes` IN PLACE
    (mismo patrón que `_resolver_pallets_backtracking`, actualizando
    también `pc.libres` vía `_actualizar_libres_maxrects` para que el
    backtracking que corre después vea el espacio libre real). Devuelve el
    conjunto de SKUs que procesó, para que `_empacar_n_pallets` los proteja
    de la fase de LNS (`skus_protegidos` en `_lns_mejorar_pallets` -sin
    esto, el LNS puede deshacer lo que se armó acá con tal de colocar más
    cajas de un SKU que apila más denso, aunque dropear otro SKU entero sea
    peor para el negocio). SOLO se llama desde el camino de
    `Pallets_Objetivo` (`priorizar_grandes=True`) -el camino abierto por
    defecto nunca pasa por acá."""
    mejor_orientacion: dict[str, tuple[TorreCandidate, int, int]] = {}
    for sku, cands in por_sku.items():
        unidades = pendientes.get(sku, 0)
        if unidades <= 0 or not cands:
            continue
        mejor = None
        for cand in cands:
            if cand.alto_caja <= 0 or cand.largo > config.PALLET_LARGO + TOL or cand.ancho > config.PALLET_ANCHO + TOL:
                continue
            capas = max(1, int((presupuesto + TOL) // cand.alto_caja))
            columnas = -(-unidades // capas)  # ceil sin importar float
            area_total = columnas * cand.largo * cand.ancho
            clave = (area_total, cand.ancho, cand.largo)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, cand, capas, columnas)
        if mejor is not None:
            _, cand, capas, columnas = mejor
            mejor_orientacion[sku] = (cand, capas, columnas)

    if not mejor_orientacion:
        return frozenset()

    # [Shelf-First-Fit-Decreasing-Height] Los SKUs con estante más
    # profundo (mayor `ancho` en su orientación elegida) van primero -así
    # abren los estantes que los SKUs más angostos pueden compartir
    # después, en vez de que un SKU angosto abra un estante que después
    # ningún SKU profundo puede aprovechar.
    orden = sorted(mejor_orientacion.keys(), key=lambda sku: -mejor_orientacion[sku][0].ancho)

    for pidx in range(n_pallets):
        pallet = construcciones[pidx].pallet
        pc = construcciones[pidx]
        estantes: list[dict] = []  # cada uno: {"y", "profundidad", "x_cursor"}

        def _colocar(cand: TorreCandidate, x: float, y: float, z: float, cantidad: int) -> None:
            torre = crear_torre(cand, x=x, y=y, cantidad=cantidad, z=z)
            pc.libres = _actualizar_libres_maxrects(pc.libres, x, y, z, torre.largo, torre.ancho, torre.altura)
            pallet.torres.append(torre)
            pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in pallet.torres)
            pallet.peso_estimado += torre.peso
            pallet.ocupacion_xy = round(
                _area_union_xy(pallet.torres) / (config.PALLET_LARGO * config.PALLET_ANCHO), 4
            )
            pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in pallet.torres), 2)

        for sku in orden:
            if pendientes.get(sku, 0) <= 0:
                continue
            cand, capas_por_columna, columnas_necesarias = mejor_orientacion[sku]
            tope_capa = capacidad_cama_por_sku.get(sku)
            nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
            tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
            ya_en_pallet = colocados_por_pallet[pidx].get(sku, 0)

            # [cama por cama, no columna por columna -bug real de esta
            # sesión, ver PATCH_LOG.md] `Cajas_Cama_Efectivo` (`tope_capa`)
            # es un tope FÍSICO POR CAPA compartido entre TODAS las columnas
            # del SKU (ej. Vino: máximo 15 cajas en la misma altura Z, sin
            # importar cuántas columnas distintas la formen) -apilar una
            # columna entera de una (varias capas de una vez) antes de abrir
            # la siguiente agotaba ese tope compartido en las primeras 2-3
            # columnas, dejando a las demás sin ninguna capa disponible
            # aunque sobrara piso. Ahora se llena una CAPA (Z) a la vez:
            # primero reutiliza las columnas de este SKU ya abiertas
            # (apilando una capa más en cada una), y solo abre columnas
            # nuevas si esa capa concreta todavía tiene cupo Y sobra piso.
            columnas_sku: list[dict] = []  # {"x", "y"}
            capa = 0
            while pendientes.get(sku, 0) > 0 and ya_en_pallet < tope_pallet:
                z = capa * cand.alto_caja
                if z + cand.alto_caja > presupuesto + TOL:
                    break  # esta capa ya no entra en la altura disponible
                cupo_capa = _capacidad_restante_en_capa(pallet, sku, z, tope_capa)
                if cupo_capa <= 0:
                    break  # el tope de Cajas_Cama_Efectivo para esta Z ya está lleno

                avanzo_en_capa = False
                for col in columnas_sku:
                    if pendientes.get(sku, 0) <= 0 or ya_en_pallet >= tope_pallet or cupo_capa <= 0:
                        break
                    cuboide = _CuboidLibre(col["x"], col["y"], z, cand.largo, cand.ancho, presupuesto - z)
                    if not _cuboide_admite_candidato(pallet, cuboide, cand, tope_capa, nivel_sku, nivel_por_sku):
                        continue
                    cantidad = min(pendientes[sku], tope_pallet - ya_en_pallet, cupo_capa, 1)
                    if cantidad <= 0:
                        continue
                    _colocar(cand, col["x"], col["y"], z, cantidad)
                    pendientes[sku] -= cantidad
                    colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + cantidad
                    ya_en_pallet += cantidad
                    cupo_capa -= cantidad
                    avanzo_en_capa = True

                # [tope de columnas NUEVAS por capa -bug real de esta
                # sesión] Sin `tope_capa` (o con uno holgado), nada más
                # frenaba cuántas columnas NUEVAS se abrían en la PRIMERA
                # capa -terminaba abriendo una columna nueva por cada
                # unidad de demanda entera (ej. 10 columnas de 1 caja cada
                # una) en vez de `columnas_necesarias` columnas apiladas
                # `capas_por_columna` de alto -devoraba el piso para un
                # solo SKU igual que en los intentos anteriores. Ahora solo
                # se abren columnas nuevas hasta `columnas_necesarias`;
                # superado ese número, el resto de la demanda de esta capa
                # espera a la reutilización de columnas en capas futuras.
                while (
                    pendientes.get(sku, 0) > 0 and ya_en_pallet < tope_pallet and cupo_capa > 0
                    and len(columnas_sku) < columnas_necesarias
                ):
                    # [Shelf BEST-Fit, probando TODOS antes de rendirse -bug
                    # real de esta sesión, ver PATCH_LOG.md: Vodka/KR
                    # Naranja/Gaseosa Oro/Altomayo terminaban en 0 cajas
                    # porque el ÚNICO estante evaluado (el de menos ancho
                    # libre) resultaba con una altura de caja incompatible
                    # (`TOLERANCIA_ALTURA_CAMA_CM`) y el código se rendía ahí
                    # mismo, sin probar los demás estantes abiertos que sí
                    # habrían servido] Se ordenan los estantes candidatos
                    # (ancho/profundidad suficiente) de menos a más ancho
                    # libre, y se prueba cada uno hasta encontrar el primero
                    # que `_cuboide_admite_candidato` acepta de verdad -solo
                    # se abre un estante nuevo si NINGUNO de los existentes
                    # sirve.
                    candidatos_estante = sorted(
                        (
                            est for est in estantes
                            if est["profundidad"] + TOL >= cand.ancho
                            and est["x_cursor"] + cand.largo <= config.PALLET_LARGO + TOL
                        ),
                        key=lambda est: config.PALLET_LARGO - est["x_cursor"],
                    )
                    estante = None
                    for candidato in candidatos_estante:
                        cuboide = _CuboidLibre(
                            candidato["x_cursor"], candidato["y"], z, cand.largo, cand.ancho, presupuesto - z
                        )
                        if _cuboide_admite_candidato(pallet, cuboide, cand, tope_capa, nivel_sku, nivel_por_sku):
                            estante = candidato
                            break
                    if estante is None:
                        y_nuevo = max((est["y"] + est["profundidad"] for est in estantes), default=0.0)
                        if y_nuevo + cand.ancho > config.PALLET_ANCHO + TOL:
                            break  # no entra ni un estante nuevo -se acabó el fondo del pallet
                        cuboide_nuevo = _CuboidLibre(0.0, y_nuevo, z, cand.largo, cand.ancho, presupuesto - z)
                        if not _cuboide_admite_candidato(pallet, cuboide_nuevo, cand, tope_capa, nivel_sku, nivel_por_sku):
                            break  # ni un estante nuevo sirve (soporte/nivel) -no tiene sentido seguir
                        estante = {"y": y_nuevo, "profundidad": cand.ancho, "x_cursor": 0.0}
                        estantes.append(estante)

                    x, y = estante["x_cursor"], estante["y"]
                    cantidad = min(pendientes[sku], tope_pallet - ya_en_pallet, cupo_capa, 1)
                    if cantidad <= 0:
                        break
                    _colocar(cand, x, y, z, cantidad)
                    pendientes[sku] -= cantidad
                    colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + cantidad
                    ya_en_pallet += cantidad
                    cupo_capa -= cantidad
                    estante["x_cursor"] += cand.largo
                    columnas_sku.append({"x": x, "y": y})
                    avanzo_en_capa = True

                if not avanzo_en_capa:
                    break  # esta capa no aceptó nada más (piso agotado) -no tiene sentido seguir
                capa += 1

    return frozenset(orden)


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
                # [Refinamiento 'seguir la misma torre', mismo criterio que
                # _empacar/_candidatos_lote -desempate DESPUÉS de -area]
                mismo_sku_continua = 0 if _hay_torre_mismo_sku_en_xy(pallet, sku, libre.x, libre.y) else 1
                clave = (z_destino, nivel_sku, -area, mismo_sku_continua, -cantidad_pendiente)
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

# [PATCH V6.12-D7B-0 -"Deterministic LNS restarts"] Cantidad de reinicios del
# camino SECUENCIAL (`paralelo_lns=False`, el que usa el batch multi-CD de
# `pipeline_sku_bloque._procesar_cd`). Antes, cuántos reinicios corrían lo
# decidía un reloj (`reloj_lns() > deadline_lns`, CPU-time) -criterio
# algorítmico basado en tiempo. Medido en V6.12-D7A/D7B (batch real de 9
# CDs): los 7 CDs que usan LNS ejecutaban SIEMPRE exactamente 1 reinicio
# (el primero completaba la demanda o excedía el tope de reloj por un
# margen enorme), así que este valor reproduce el comportamiento real
# actual, ahora explícito y sin reloj. El camino PARALELO sigue corriendo
# `COMBINACION_PALLETS_LNS_REINICIOS` semillas (los reinicios extra SÍ
# aportan valor medido: SJ95 semilla 1, SJ97 semilla 2).
COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL = 1

# [tope de reloj real -pedido explícito del usuario tras el corrido con
# `Pallets_Objetivo` real que quedó colgado >21 horas] `max_nodos` acota
# la CANTIDAD de nodos, no lo que tarda cada uno -con `pallets_objetivo`
# apretado contra la demanda real (varios CDs, N pallets fijos muy por
# debajo del óptimo abierto) el estado queda mucho más fragmentado que en
# Pallet 1 (único caso medido hasta ahora) y `_candidatos_lote`/el
# snapshot por nodo se vuelven caros -sin este tope, ese costo por nodo
# multiplicado por hasta 5 reinicios x 200 iteraciones x 3,000 nodos de
# reconstrucción puede tardar horas. Estos topes son DEADLINES de reloj,
# chequeados en el punto más caliente de cada bucle -nunca puede empeorar
# el resultado: el DFS y el LNS siempre devuelven el MEJOR incumbente
# encontrado hasta el corte, no fallan ni tiran excepción.
#
# [PATCH V6.11-R3] Qué reloj mide ese deadline ya NO es siempre
# `time.time()` -ver `_search_budget_now`. DFS y LNS SECUENCIALES
# (`paralelo_lns=False`, el camino real de cada CD dentro del pipeline
# multi-CD, `pipeline_sku_bloque.py`) usan `time.process_time()`: bajo
# contención de CPU entre CDs hermanos corriendo en paralelo (varios
# `ProcessPoolExecutor` de `pipeline_sku_bloque.py`), un deadline de reloj
# de pared se cumplía con MENOS trabajo real hecho según qué tan cargada
# estuviera la máquina en ese momento -mismo input, mismo algoritmo,
# resultado distinto entre corridas (confirmado empíricamente en BK43,
# CIERRE V6.11-R1/R2). CPU-time del propio proceso es inmune a esa
# contención. El LNS PARALELO interno (`ProcessPoolExecutor` de más abajo,
# `paralelo_lns=True`) sigue usando `time.monotonic()` -el CPU-time del
# proceso padre no representa el trabajo real de sus procesos hijos, y
# `fork` sí garantiza que padre e hijos compartan el mismo reloj de pared.
COMBINACION_PALLETS_TIEMPO_MAX_DFS_SEGUNDOS = 45.0
COMBINACION_PALLETS_TIEMPO_MAX_LNS_SEGUNDOS = 90.0


def _tiempo_max_dfs(demanda_total: int) -> float:
    """[escalado por tamaño -pedido explícito del usuario: el camino
    abierto (`_empacar_optimizado`) prueba VARIOS `n_pallets` por CD
    (búsqueda binaria), así que el tope fijo de arriba (pensado para UN
    solo intento con `Pallets_Objetivo`) multiplicado por hasta 5 intentos
    volvía lenta hasta la suite de tests (CDs chicos sintéticos no
    necesitan 20s de DFS para converger). Escala con la demanda real -un
    problema chico converge en un puñado de nodos igual, sin gastar el
    tope completo; un CD real grande sigue teniendo el mismo tope de
    siempre (el `min` lo satura en el valor de antes)."""
    return min(COMBINACION_PALLETS_TIEMPO_MAX_DFS_SEGUNDOS, 1.0 + demanda_total * 0.05)


def _tiempo_max_lns(demanda_total: int) -> float:
    """Ver `_tiempo_max_dfs` -mismo escalado, para la fase de LNS."""
    return min(COMBINACION_PALLETS_TIEMPO_MAX_LNS_SEGUNDOS, 2.0 + demanda_total * 0.1)


def _search_budget_now(*, incluye_trabajo_hijos: bool = False) -> float:
    """[PATCH V6.11-R3] Reloj del presupuesto de DFS/LNS. `incluye_
    trabajo_hijos=False` (DFS siempre, y LNS cuando corre secuencial en el
    mismo proceso que hace el trabajo real) usa `time.process_time()` -no
    avanza con la contención de CPU de otros procesos hermanos (ver
    CIERRE V6.11-R1/R2: bajo contención multi-CD, un deadline de
    `time.time()` se cumplía con MENOS trabajo real hecho, cambiando el
    resultado -mismo input, mismo algoritmo, distinta cantidad de búsqueda
    completada). `incluye_trabajo_hijos=True` (LNS paralelo interno,
    `ProcessPoolExecutor`) usa `time.monotonic()` -el CPU-time del proceso
    padre NO representa el trabajo real de los procesos hijos, que corren
    de verdad en paralelo."""
    if incluye_trabajo_hijos:
        return time.monotonic()
    return time.process_time()


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
                cantidad = _cantidad_sin_solape(pallet, libre, cand, cantidad)
                if cantidad <= 0:
                    continue
                area = cand.largo * cand.ancho
                necesita = _necesita_columna_nueva(
                    pallet, sku, pendientes[sku], nivel_sku, libre.x, libre.y, libre.z, presupuesto
                )
                # [Refinamiento 'seguir la misma torre'] Desempate DESPUÉS de
                # -area a propósito -nunca debe ganarle a la prioridad real
                # de densidad, solo decide entre candidatos que YA tapizan el
                # cuboide igual de bien (misma área exacta).
                mismo_sku_continua = 0 if _hay_torre_mismo_sku_en_xy(pallet, sku, libre.x, libre.y) else 1
                clave = (libre.z, nivel_sku, -area, mismo_sku_continua, -pendientes[sku])
                candidatos.append((clave, necesita, pidx, sku, cand, idx_libre, int(cantidad)))

    # [combinación por cama -pedido explícito del usuario, con fotos reales
    # de un pallet físico: "necesito que repliques este tipo de
    # cubicacion... pones una caja y otra y otra EN LA MISMA CAMA hasta
    # llenar el 120x100, una vez que lo llenas recien pasas a la segunda
    # cama"] La búsqueda de arriba arma candidatos por SKU -para cada SKU,
    # su(s) mejor(es) cuboide(s) según SU propia prioridad. Eso deja huecos
    # que NINGÚN SKU eligió como su destino preferido, aunque exista un SKU
    # que lo taparía casi perfecto -medido con datos reales: 78%-95% de
    # huella cubierta, sin mejorar por más presupuesto de nodos/tiempo que
    # se le diera a la búsqueda de arriba (ver PATCH_LOG.md), porque esa
    # combinación nunca llegaba a competir. Acá se pregunta al revés: para
    # cada cuboide libre en la FRONTERA actual (la Z más baja disponible
    # entre TODOS los pallets activos -"la cama que se está llenando
    # ahora"), ¿qué SKU lo tapa MEJOR a él específicamente (menos área
    # sobrante)? Se agrega ese candidato aunque el SKU no lo hubiera
    # elegido por su propia prioridad -así una cama puede combinar tantos
    # SKUs distintos como hagan falta para tapizarla antes de que el árbol
    # considere subir de nivel. Acotado a la FRONTERA (no todos los
    # cuboides de todos los pallets) para no disparar el costo por nodo.
    #
    # [aparte de `candidatos`, no mezclado -bug real encontrado escribiendo
    # esto] Si se agregaran directo a `candidatos`, el corte a top-K de más
    # abajo (`candidatos.sort()[:SHORTLIST_K]`) los descarta en la práctica:
    # ordenan por `-area`, así que un SKU CHICO que tapa perfecto un
    # huequito angosto (exactamente el caso que se busca rescatar) pierde
    # contra cualquier SKU grande en competencia por la MISMA Z, aunque el
    # SKU grande ya tenga su propio candidato en la lista general. Se
    # guardan aparte y se garantizan en el resultado final más abajo, uno
    # por cuboide de la frontera -igual mecanismo que ya usa `necesitado`.
    candidatos_frontera: list[tuple[tuple, bool, int, str, TorreCandidate, int, int]] = []
    z_frontera = min((c.z for pc in construcciones for c in pc.libres), default=None)
    if z_frontera is not None:
        for pidx in range(n_pallets):
            pc = construcciones[pidx]
            pallet = pc.pallet
            for idx_libre, c in enumerate(pc.libres):
                if abs(c.z - z_frontera) > TOL:
                    continue
                mejor_fit = None  # ((area_sobrante, mismo_sku_continua), sku, cand, cantidad)
                for sku in pendientes:
                    if pendientes[sku] <= 0:
                        continue
                    tope_capa = capacidad_cama_por_sku.get(sku)
                    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
                    tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
                    ya_en_pallet = colocados_por_pallet[pidx].get(sku, 0)
                    if ya_en_pallet >= tope_pallet:
                        continue
                    for cand_op in por_sku[sku]:
                        if not _cuboide_admite_candidato(pallet, c, cand_op, tope_capa, nivel_sku, nivel_por_sku):
                            continue
                        sobra = c.w * c.h - cand_op.largo * cand_op.ancho
                        cantidad = min(
                            pendientes[sku], tope_pallet - ya_en_pallet,
                            _capacidad_restante_en_capa(pallet, sku, c.z, tope_capa),
                            int((c.d + TOL) // cand_op.alto_caja),
                        )
                        cantidad = _cantidad_sin_solape(pallet, c, cand_op, cantidad)
                        if cantidad <= 0:
                            continue
                        # [Refinamiento 'seguir la misma torre'] Mismo
                        # criterio que arriba: desempate SOLO cuando `sobra`
                        # ya está empatada -nunca le gana a "menos hueco".
                        mismo_sku_continua = 0 if _hay_torre_mismo_sku_en_xy(pallet, sku, c.x, c.y) else 1
                        clave_fit = (sobra, mismo_sku_continua)
                        if mejor_fit is None or clave_fit < mejor_fit[0]:
                            mejor_fit = (clave_fit, sku, cand_op, cantidad)
                if mejor_fit is not None:
                    _, sku, cand, cantidad = mejor_fit
                    area = cand.largo * cand.ancho
                    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
                    necesita = _necesita_columna_nueva(
                        pallet, sku, pendientes[sku], nivel_sku, c.x, c.y, c.z, presupuesto
                    )
                    mismo_sku_continua = 0 if _hay_torre_mismo_sku_en_xy(pallet, sku, c.x, c.y) else 1
                    clave = (c.z, nivel_sku, -area, mismo_sku_continua, -pendientes[sku])
                    candidatos_frontera.append((clave, necesita, pidx, sku, cand, idx_libre, int(cantidad)))

    candidatos.sort(key=lambda c: c[0])
    top = candidatos[:COMBINACION_PALLETS_SHORTLIST_K]
    if not any(c[1] for c in top):
        necesitado = next((c for c in candidatos if c[1]), None)
        if necesitado is not None:
            top.append(necesitado)

    # [garantía -ver comentario junto a `candidatos_frontera`] Cada cuboide
    # de la frontera actual aporta SU mejor candidato al árbol, sin pasar
    # por el corte de prioridad general -así una cama puede terminar
    # combinando tantos SKUs como cuboides libres tenga, no solo los que ya
    # ganaban por prioridad global.
    ya_cubiertos = {(c[2], c[5]) for c in top}
    for cand_frontera in candidatos_frontera:
        clave_f, necesita_f, pidx_f, sku_f, cand_f, idx_libre_f, cantidad_f = cand_frontera
        if (pidx_f, idx_libre_f) in ya_cubiertos:
            continue
        top.append(cand_frontera)
        ya_cubiertos.add((pidx_f, idx_libre_f))

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
    limite_tiempo: float | None = None,
    reloj: Callable[[], float] = time.process_time,
) -> int:
    """[backtracking real, DFS con poda] A diferencia del greedy (1 caja,
    sin vuelta atrás), acá cada nodo coloca un LOTE completo -toda una
    columna de una vez- y puede DESHACERLO si la rama no mejora el mejor
    resultado encontrado (`_snapshot_estado_pallets`/`_restaurar_estado_
    pallets`). La primera rama que explora cada nodo es siempre la de
    mayor prioridad (misma clave que usa el greedy) -así la primera hoja
    completa que encuentra ya iguala el resultado de hoy; de ahí en más
    solo puede empatar o mejorar. Acotado ÚNICAMENTE por
    `COMBINACION_PALLETS_MAX_NODOS` (conteo de nodos, reproducible entre
    corridas) -ver solución encontrada/espacio agotado más abajo.

    [PATCH V6.12-D5 -"Deterministic DFS/LNS Work Budgets"] `limite_tiempo`/
    `reloj` YA NO deciden el corte -confirmado (V6.12-2A2-D2/D3/D4) que un
    deadline de `process_time()` real puede cortar esta búsqueda en un
    número de nodos DISTINTO entre corridas con la MISMA entrada, según
    cuánto throughput efectivo tuvo el proceso en ese instante (contención
    real de procesos hermanos -no reproducible con quemadores de CPU
    sintéticos, ver D3- nunca "cuánto trabajo lógico hay que hacer").
    Resultado ahora depende ÚNICAMENTE de: (1) solución encontrada (la
    demanda completa, ver `colocado_actual >= demanda_inicial` abajo -una
    vez encontrada, ninguna otra rama puede superarla, la poda por cota la
    descarta sola), (2) `max_nodos` agotado, o (3) espacio agotado (la
    cota de la rama ya no supera lo encontrado, o no quedan candidatos).
    Se mantienen `limite_tiempo`/`reloj` en la firma SOLO por compatibilidad
    con los callers existentes (`rescue_solver._aplicar_ruina_dirigida`,
    `_lns_mejorar_pallets`) -no se tocan esos módulos en este parche- pero
    ya no participan en ninguna decisión de corte acá adentro.

    [PATCH V6.11-R3, sigue vigente] `reloj` default `time.process_time`
    -esta función SIEMPRE corre en el mismo proceso que hace el trabajo
    real, tanto llamada directa (DFS inicial de `_empacar_n_pallets`) como
    desde adentro de `_lns_mejorar_pallets` en su variante secuencial; el
    único caso que corre en un proceso hijo (`_lns_una_semilla_worker`, LNS
    paralelo) pasa `reloj=` explícito con `time.monotonic` -ver
    `_search_budget_now` (este comentario describe el dominio temporal del
    parámetro, que sigue existiendo en la firma; no implica que se use acá
    para cortar, ver arriba). Modifica `construcciones`/`colocados_
    por_pallet`/`pendientes` IN-PLACE, dejándolos en el MEJOR estado
    encontrado al terminar -no devuelve una copia."""
    demanda_inicial = sum(pendientes.values())
    # [densidad como criterio de desempate -bug real de esta sesión,
    # reportado por el usuario con fotos de un pallet real todavía con
    # huecos visibles tras varios intentos de "más tiempo de búsqueda" que
    # no cambiaron NADA el resultado] `estado["mejor_total"]` solo contaba
    # CAJAS -en la enorme mayoría de los casos la demanda YA entra completa
    # de varias formas distintas (la huella se llene o no), así que la
    # primera hoja que el DFS encuentra (que reproduce casi exactamente la
    # prioridad del greedy, ver docstring) empataba con TODO lo que venía
    # después -ninguna rama más densa lograba nunca superar el `>` estricto
    # de abajo, así que se descartaba sin importar cuánto presupuesto de
    # nodos/tiempo se le diera. Ahora, en caso de empate en cajas, gana la
    # rama que cubre MÁS huella real (`area_actual`, la unión de footprints
    # -exactamente lo que pide el usuario: menos hueco visible entre
    # cajas). Se mantiene barato de calcular: como las torres nunca se
    # superponen (garantía del motor MaxRects), la unión de footprints es
    # simplemente la SUMA incremental del área de cada columna NUEVA que se
    # abre (0 si la colocación solo extiende una columna ya existente en
    # ese mismo x,y) -no hace falta un sweep completo en cada nodo.
    area_inicial = sum(_area_union_xy(pc.pallet.torres) for pc in construcciones)
    estado = {"mejor_total": -1, "mejor_area": -1.0, "mejor_snapshot": None, "nodos": 0}

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

    def _dfs(colocado_actual: int, area_actual: float) -> None:
        estado["nodos"] += 1
        if colocado_actual > estado["mejor_total"] or (
            colocado_actual == estado["mejor_total"] and area_actual > estado["mejor_area"]
        ):
            estado["mejor_total"] = colocado_actual
            estado["mejor_area"] = area_actual
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
            libre = construcciones[pidx].libres[idx_libre]
            columna_nueva = not any(
                abs(t.x - libre.x) <= TOL and abs(t.y - libre.y) <= TOL
                for t in construcciones[pidx].pallet.torres
            )
            delta_area = cand.largo * cand.ancho if columna_nueva else 0.0
            construcciones[pidx].colocar(cand, cantidad, idx_libre)
            pendientes[sku] -= cantidad
            colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + cantidad
            _dfs(colocado_actual + cantidad, area_actual + delta_area)
            _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
            if estado["nodos"] > max_nodos:
                break

    _dfs(demanda_inicial - sum(pendientes.values()), area_inicial)
    if estado["mejor_snapshot"] is not None:
        _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, estado["mejor_snapshot"])
    # [PATCH V6.12-D7B-P2] Si el `reloj` recibido es un `MedidorTrabajo` (budget
    # de trabajo determinista, ver src/medidor_trabajo.py) se le suman las
    # visitas de este DFS. Con un `reloj` normal (función) no hace nada.
    registrar_nodos = getattr(reloj, "registrar_nodos", None)
    if registrar_nodos is not None:
        registrar_nodos(estado["nodos"])
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
    soporte real admisible (mismo margen por lado que
    `validacion_v5._tiene_soporte_admisible`, el que usa el gate de
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
                    if not _tiene_soporte_admisible(t, soportes):
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
    limite_tiempo: float | None = None,
    skus_protegidos: frozenset[str] = frozenset(),
    reloj: Callable[[], float] = time.process_time,
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
    mecanismo de undo del DFS). Corta ÚNICAMENTE por: (1) solución completa
    (`mejor_total` ya alcanzó toda la demanda disponible al entrar -nada
    más que optimizar), (2) iteraciones sin mejora consecutivas
    (`COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX`), o (3) el total de
    iteraciones (`COMBINACION_PALLETS_LNS_ITERACIONES`) -RNG con semilla
    fija (derivada de `cd`+`n_pallets` por el caller) para que el resultado
    sea reproducible entre corridas. Modifica `construcciones`/
    `colocados_por_pallet`/`pendientes` IN-PLACE, igual que el DFS.
    Devuelve el total de cajas colocadas en TODOS los pallets (no un delta
    relativo a esta llamada, a diferencia de `_resolver_pallets_
    backtracking`).

    [PATCH V6.12-D5 -"Deterministic DFS/LNS Work Budgets"] `limite_tiempo`/
    `reloj` YA NO deciden en qué iteración termina este loop -mismo
    hallazgo que en `_resolver_pallets_backtracking` (V6.12-2A2-D2/D3/D4):
    un deadline de `process_time()` real cortaba esto en una iteración
    DISTINTA entre corridas con la MISMA entrada según el throughput
    efectivo del proceso en ese instante, nunca según cuánto trabajo lógico
    hacía falta. Se mantienen en la firma solo por compatibilidad con
    `rescue_solver`/`repair_solver` (no se tocan en este parche) y porque
    siguen reenviándose tal cual a las reconstrucciones DFS internas -esas
    ya inertes para decidir cortes también (ver `_resolver_pallets_
    backtracking`); la reconstrucción interna corta por su propio
    `max_nodos` (`COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION`), nunca
    por tiempo.

    `skus_protegidos` -[Refinamiento 'grandes primero', ver
    `_reservar_skus_grandes`] SKUs que nunca se ofrecen como candidatos a
    romper -sin esto, el LNS (que solo optimiza CANTIDAD total de cajas)
    tiende a deshacer justo los SKUs de footprint grande que se reservaron
    a propósito, a cambio de más cajas de un SKU chico que apila más denso
    -confirmado con datos reales de BK31 (Picaras se perdía en el LNS pase
    tras pase, siempre convergiendo al mismo óptimo local de "más Vino, sin
    Picaras"). Vacío por defecto -sin cambio de comportamiento fuera del
    camino de `Pallets_Objetivo` con `priorizar_grandes=True`.

    [PATCH V6.11-R3] `reloj` default `time.process_time` -ver comentario
    de `_resolver_pallets_backtracking` y `_search_budget_now`. El caller
    paralelo (`_lns_una_semilla_worker`) pasa `reloj=time.monotonic`
    explícito."""
    rng = random.Random(semilla)

    def _total_colocado() -> int:
        return sum(sum(d.values()) for d in colocados_por_pallet)

    mejor_total = _total_colocado()
    mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
    sin_mejora = 0
    # [PATCH V6.12-D5] Techo real de "solución completa" -constante durante
    # todo este LNS (nunca cambia la demanda TOTAL, solo qué parte está
    # colocada vs pendiente en cada iteración).
    demanda_total_lns = mejor_total + sum(pendientes.values())

    for _ in range(COMBINACION_PALLETS_LNS_ITERACIONES):
        if mejor_total >= demanda_total_lns:
            break  # [PATCH V6.12-D5] ya se colocó el 100% -nada más que optimizar
        if sin_mejora >= COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX:
            break
        skus_colocados = sorted({
            sku for d in colocados_por_pallet for sku, cant in d.items()
            if cant > 0 and sku not in skus_protegidos
        })
        if not skus_colocados:
            break
        k = min(COMBINACION_PALLETS_LNS_SKUS_A_ROMPER, len(skus_colocados))
        elegidos = set(rng.sample(skus_colocados, k))

        _romper_skus_con_cascada(construcciones, colocados_por_pallet, pendientes, elegidos, n_pallets)

        # [reconstrucción] Mismo backtracking, presupuesto de nodos más
        # chico -acá se corre muchas veces, no una sola. [PATCH V6.12-D5]
        # `limite_tiempo=`/`reloj=` se siguen reenviando tal cual (mismos
        # nombres de parámetro que antes) pero ya son inertes para decidir
        # ningún corte -ver docstring de ambas funciones; el único corte
        # real de esta reconstrucción es su propio `max_nodos` de acá abajo.
        _resolver_pallets_backtracking(
            construcciones, colocados_por_pallet, pendientes, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
            max_nodos=COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION,
            limite_tiempo=limite_tiempo, reloj=reloj,
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


def _seleccionar_mejor_reinicio(
    mejor_total_inicial: int,
    mejor_snapshot_inicial,
    resultados_por_semilla: list[tuple[int, list[_PalletEnConstruccion], list[dict[str, int]], dict[str, int]]],
):
    """[PATCH V6.12-D7B-0] Elige el mejor reinicio LNS de forma DETERMINISTA.
    `resultados_por_semilla` viene en ORDEN DE ÍNDICE DE SEMILLA (no de
    terminación). Criterio: el mismo de siempre -`total_intento` ESTRICTAMENTE
    mayor que el mejor vigente (el incumbente de entrada, el DFS, gana
    empates contra cualquier semilla)- recorrido por índice de semilla
    ascendente, así que ante un empate entre semillas gana la de MENOR
    índice, sin depender de qué proceso hijo terminó primero. No cambia el
    score: solo elimina el orden de terminación como desempate."""
    mejor_total = mejor_total_inicial
    mejor_snapshot = mejor_snapshot_inicial
    for total_intento, construcciones_i, colocados_i, pendientes_i in resultados_por_semilla:
        if total_intento > mejor_total:
            mejor_total = total_intento
            mejor_snapshot = (
                [(list(pc.pallet.torres), pc.libres) for pc in construcciones_i],
                [dict(d) for d in colocados_i],
                dict(pendientes_i),
            )
    return mejor_total, mejor_snapshot


def _lns_una_semilla_worker(
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
    limite_tiempo: float | None = None,
    skus_protegidos: frozenset[str] = frozenset(),
) -> tuple[int, list[_PalletEnConstruccion], list[dict[str, int]], dict[str, int]]:
    """[paralelización -pedido explícito del usuario: "como podemos hacer
    para que no demore tanto"] Función de nivel de módulo (necesaria para
    que `ProcessPoolExecutor` pueda "picklearla" y mandarla a otro
    proceso) que corre UNA sola semilla de `_lns_mejorar_pallets` hasta el
    final. Los argumentos ya le llegan a este proceso como una copia
    independiente (el propio mecanismo de serialización del `Executor` al
    mandarlos -ningún estado se comparte entre procesos, así que no hace
    falta copiarlos a mano acá), así que puede mutarlos libremente sin
    afectar al proceso llamador. Devuelve el total colocado y el estado
    final -el llamador decide con cuál de las N semillas se queda.
    `limite_tiempo` es un deadline absoluto de `time.monotonic()`
    -comparable entre este proceso hijo y el padre porque `fork` hereda el
    mismo reloj de pared. `skus_protegidos` -ver `_lns_mejorar_pallets`.

    [PATCH V6.11-R3] Este worker SOLO corre dentro de un proceso hijo de
    `ProcessPoolExecutor` (LNS paralelo, `paralelo_lns=True`) -pasa
    `reloj=time.monotonic` explícito a `_lns_mejorar_pallets`: el CPU-time
    de ESTE proceso hijo no es comparable con el deadline que calculó el
    padre (cada hijo tendría su propio reloj de CPU arrancando de cero),
    así que el reloj de pared sigue siendo el correcto acá -ver
    `_search_budget_now`."""
    total = _lns_mejorar_pallets(
        construcciones, colocados_por_pallet, pendientes, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, semilla,
        limite_tiempo=limite_tiempo, skus_protegidos=skus_protegidos, reloj=time.monotonic,
    )
    return total, construcciones, colocados_por_pallet, pendientes


def _empacar_n_pallets(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    cd: str,
    contador: list[int],
    n_pallets: int,
    paralelo_lns: bool = True,
    con_lns: bool = True,
    priorizar_grandes: bool = False,
    max_nodos_dfs: int = COMBINACION_PALLETS_MAX_NODOS,
    presupuesto_rescue_nodos: int | None = None,
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
    rama explorada reproduce exactamente la misma prioridad.

    `con_lns=False` -pedido explícito del usuario tras medir que la suite
    de tests pasó de 56s a 43 minutos: `_empacar_optimizado` (camino
    abierto) llama a esta función varias veces por CD (búsqueda binaria de
    N) y antes de este flag cada llamada pagaba el costo completo de LNS
    (hasta 5 semillas en paralelo). Con `con_lns=False` se salta esa fase
    -sirve para SONDEAR rápido "¿entran 100% de las cajas en N pallets?"
    solo con DFS (mucho más barato, sin el multi-reinicio), reservando el
    LNS completo para una única corrida final sobre la N que la búsqueda
    binaria termine eligiendo. Puede subestimar qué N es factible (LNS
    encuentra soluciones que el DFS solo no ve) -aceptable para sondear: la
    N final igual se re-verifica con LNS completo antes de aceptarse.

    [corregido -bug real de esta sesión, reportado por el usuario con una
    captura de un pallet real con huecos visibles todavía] El sondeo
    (`con_lns=False`) tenía ADEMÁS un tope de tiempo propio, fijo en 5s,
    aparte del escalado por demanda -para que la suite de tests no
    volviera a tardar minutos. Pero ese tope de 5s aplicaba IGUAL a un CD
    real grande, cortando el sondeo mucho antes de lo que `_tiempo_max_dfs`
    (escalado por demanda) ya permitía -el efecto real era subestimar
    demasiado agresivamente qué N es factible, dejando el resultado final
    con más huecos de los necesarios. Se saca ese tope aparte: el sondeo
    ahora usa el mismo `_tiempo_max_dfs` escalado por demanda que todo lo
    demás (ya de por sí chico para datasets de test sintéticos chicos, y
    generoso para CDs reales grandes -ver PATCH_LOG.md).

    `priorizar_grandes=False` (default) -[Refinamiento 'grandes primero',
    pedido explícito del usuario, ver `_reservar_skus_grandes`] Cuando es
    `True` (SOLO la llamada directa de `armar_pallets_bloques` cuando el
    usuario fijó `Pallets_Objetivo` -nunca las llamadas internas de
    `_empacar_optimizado`, que deben seguir dando los mismos números ya
    verificados del camino abierto), reserva territorio para los SKUs de
    footprint grande ANTES de que el backtracking arranque -sin esto, un
    SKU grande (ej. Picaras, 39x30) puede quedarse sin ningún hueco
    contiguo porque SKUs chicos ya fragmentaron el piso para cuando le
    toca competir, aunque sobre aire/altura sin usar en varias columnas
    (confirmado con datos reales: más presupuesto de búsqueda no cambiaba
    el resultado -no era falta de tiempo, era de orden). No toca
    `_empacar_n_pallets_greedy` (el baseline de comparación de abajo sigue
    siendo el greedy de siempre) -si "grandes primero" empeorara algo, el
    guard de más abajo (`total_bt` vs `total_greedy`) ya descarta el
    resultado y vuelve al greedy: cero riesgo de regresión por diseño.

    [PATCH V6.12-D7B-P1 -"Probe DFS work budget"] `max_nodos_dfs` es el tope
    de nodos del DFS INICIAL de esta función (el de abajo, con
    `_resolver_pallets_backtracking`) -default `COMBINACION_PALLETS_MAX_
    NODOS` (30000), así que TODO caller que no lo pase (la materialización
    final de `_empacar_optimizado`, `Pallets_Objetivo` fijo vía
    `armar_pallets_bloques`) queda exactamente igual. Solo el sondeo de
    `busqueda_n_pallets.probe()` lo sobrescribe (`PROBE_DFS_MAX_NODES`).
    No afecta al DFS de reconstrucción del LNS ni al de Rescue/Repair, que
    tienen su propio `max_nodos`.

    [PATCH V6.12-D7B-P2 -"Probe Rescue work budget"] `presupuesto_rescue_nodos`
    (default `None`): cuando se pasa, Rescue corta por un presupuesto de NODOS
    (`rescue_solver(presupuesto_nodos=...)`, ver `src/medidor_trabajo.py`) en
    vez del CPU-time de siempre. SOLO lo pasa `busqueda_n_pallets.probe()`
    (`PROBE_RESCUE_MAX_NODES`); la materialización final y `Pallets_Objetivo`
    fijo no lo pasan y Rescue queda exactamente igual (el kwarg ni siquiera se
    envía). Repair/Exact/Global no cambian."""
    pallets_greedy, sin_colocar_greedy = _empacar_n_pallets_greedy(
        dict(pendientes), por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, n_pallets,
    )
    total_greedy = sum(t.cantidad for p in pallets_greedy for t in p.torres)

    demanda_total = sum(pendientes.values())
    # [bug real de esta sesión, encontrado tras varios intentos fallidos de
    # "más presupuesto de búsqueda" que no cambiaban NADA el resultado]
    # ANTES, si el greedy ya colocaba el 100% (el caso más común -casi
    # cualquier N razonable ya alcanza), la función devolvía ese resultado
    # de inmediato: el backtracking NUNCA llegaba a correr. Cuando el único
    # objetivo era "cuántas cajas entran", eso era correcto (no había nada
    # más que mejorar). Pero ahora el backtracking TAMBIÉN busca mejor
    # DENSIDAD (huella cubierta, ver `_resolver_pallets_backtracking`) para
    # la MISMA cantidad de cajas -este atajo descartaba esa búsqueda por
    # completo, siempre, en el caso más común. Se saca: el backtracking
    # corre igual, y la comparación final (más abajo) decide con criterio
    # de densidad, no solo de cantidad.

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

    skus_protegidos: frozenset[str] = frozenset()
    if priorizar_grandes:
        skus_protegidos = _reservar_skus_grandes(
            construcciones_bt, colocados_bt, pendientes_bt, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, n_pallets, presupuesto,
        )

    # [PATCH V6.11-R3] Este DFS SIEMPRE corre en el proceso que llama a
    # `_empacar_n_pallets` (nunca en un hijo de `ProcessPoolExecutor`,
    # pase lo que pase con `paralelo_lns` -eso solo afecta a la fase de
    # LNS más abajo) -CPU-time es correcto y, a diferencia del reloj de
    # pared, no se ve afectado por la contención de CPU de otros CDs
    # corriendo en paralelo (ver CIERRE V6.11-R1/R2).
    _resolver_pallets_backtracking(
        construcciones_bt, colocados_bt, pendientes_bt, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
        max_nodos=max_nodos_dfs,
        limite_tiempo=_search_budget_now(incluye_trabajo_hijos=False) + _tiempo_max_dfs(demanda_total),
        reloj=lambda: _search_budget_now(incluye_trabajo_hijos=False),
    )
    total_bt = sum(sum(d.values()) for d in colocados_bt)

    if total_bt < demanda_total and con_lns:
        # [multi-reinicio -medido con datos reales, Pallet 1; pedido
        # explícito del usuario: "como podemos hacer para que no demore
        # tanto"] Una sola corrida de LNS depende de la suerte de la
        # semilla: probado con 17 semillas distintas, el resultado varía
        # entre 78 y 83 -la mayoría se queda en 78 (el mismo óptimo local
        # del DFS solo), pero varias sí llegan a 83. Las
        # `COMBINACION_PALLETS_LNS_REINICIOS` semillas son 100%
        # independientes entre sí (cada una arranca del mismo incumbente
        # del DFS, sin compartir estado) -con `paralelo_lns=True` (default)
        # corren en procesos separados a la vez (`ProcessPoolExecutor`),
        # bajando el tiempo de reloj hasta ~Nx en una máquina con N
        # núcleos libres, sin sacrificar nada de calidad (exactamente el
        # mismo trabajo, solo en paralelo en vez de en serie). Con
        # `paralelo_lns=False` (cuando el LLAMADOR ya paraleliza por CD,
        # ver `pipeline_sku_bloque.py`) corren secuenciales, una tras otra
        # -evita anidar 2 pools de procesos y saturar los núcleos reales.
        snapshot_dfs = _snapshot_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt)
        mejor_total_lns = total_bt
        mejor_snapshot_lns = snapshot_dfs
        # [tope de reloj real, ver comentario junto a COMBINACION_PALLETS_
        # TIEMPO_MAX_LNS_SEGUNDOS] Un solo deadline absoluto para TODA la
        # fase de LNS -en paralelo, lo respeta cada semilla por igual (no
        # se suma, corren a la vez). [PATCH V6.12-D7B-0] Ya NO decide cuántos
        # reinicios corren (ver `COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL`)
        # ni corta nada: se mantiene solo para la firma de las funciones LNS.
        # [PATCH V6.11-R3] `paralelo_lns=True` reparte el trabajo real en
        # procesos hijos (`ProcessPoolExecutor` más abajo) -el CPU-time de
        # ESTE proceso (el padre) no avanza mientras los hijos trabajan,
        # así que el deadline tiene que ser de reloj de pared
        # (`time.monotonic()`, que padre e hijos SÍ comparten vía fork).
        # `paralelo_lns=False` corre todo en este mismo proceso -ahí
        # CPU-time es la medida correcta (inmune a la contención externa
        # de otros CDs, ver `_search_budget_now`).
        reloj_lns = (
            (lambda: _search_budget_now(incluye_trabajo_hijos=True)) if paralelo_lns
            else (lambda: _search_budget_now(incluye_trabajo_hijos=False))
        )
        deadline_lns = reloj_lns() + _tiempo_max_lns(demanda_total)

        if paralelo_lns:
            n_procesos = min(COMBINACION_PALLETS_LNS_REINICIOS, os.cpu_count() or 1)
            contexto = multiprocessing.get_context("fork") if hasattr(os, "fork") else None
            with ProcessPoolExecutor(max_workers=n_procesos, mp_context=contexto) as executor:
                futuros = [
                    executor.submit(
                        _lns_una_semilla_worker, construcciones_bt, colocados_bt, pendientes_bt, por_sku,
                        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
                        f"{cd}-{n_pallets}-{intento}", deadline_lns, skus_protegidos,
                    )
                    for intento in range(COMBINACION_PALLETS_LNS_REINICIOS)
                ]
                # [PATCH V6.12-D7B-0] Los resultados se leen EN ORDEN DE SEMILLA
                # (`.result()` bloquea hasta que ESA semilla termina), nunca en
                # orden de terminación (`as_completed`): ante un empate de
                # cajas el ganador era "el primero en terminar" -dependiente
                # del tiempo. Ver `_seleccionar_mejor_reinicio`.
                resultados_por_semilla = [futuro.result() for futuro in futuros]
            mejor_total_lns, mejor_snapshot_lns = _seleccionar_mejor_reinicio(
                mejor_total_lns, mejor_snapshot_lns, resultados_por_semilla,
            )
            _restaurar_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt, mejor_snapshot_lns)
        else:
            # [PATCH V6.12-D7B-0] La cantidad de reinicios es un LÍMITE
            # EXPLÍCITO (`COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL`), ya
            # no `reloj_lns() > deadline_lns`. `limite_tiempo`/`reloj` se
            # siguen reenviando solo por compatibilidad de firma: son
            # inertes para decidir cortes desde V6.12-D5.
            for intento in range(COMBINACION_PALLETS_LNS_REINICIOS_SECUENCIAL):
                _restaurar_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt, snapshot_dfs)
                total_intento = _lns_mejorar_pallets(
                    construcciones_bt, colocados_bt, pendientes_bt, por_sku,
                    capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
                    semilla=f"{cd}-{n_pallets}-{intento}", limite_tiempo=deadline_lns,
                    skus_protegidos=skus_protegidos, reloj=reloj_lns,
                )
                if total_intento > mejor_total_lns:
                    mejor_total_lns = total_intento
                    mejor_snapshot_lns = _snapshot_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt)
                if mejor_total_lns >= demanda_total:
                    break  # ya se colocó TODO -no hace falta seguir probando semillas
            _restaurar_estado_pallets(construcciones_bt, colocados_bt, pendientes_bt, mejor_snapshot_lns)

        pallets_bt = [pc.pallet for pc in construcciones_bt]
        total_bt = mejor_total_lns

    # [empate en cantidad -preferir densidad, no el greedy a ciegas -ver
    # comentario junto a `demanda_total` arriba] Mismo criterio que ya usa
    # `_resolver_pallets_backtracking` internamente: en empate de cajas
    # colocadas, gana la huella (`_area_union_xy`) más cubierta -esto es lo
    # que hace que el resultado final realmente refleje el trabajo de
    # densidad del backtracking en vez de descartarlo por "total_bt no fue
    # ESTRICTAMENTE mayor".
    if total_bt > total_greedy or (
        total_bt == total_greedy
        and sum(_area_union_xy(pc.pallet.torres) for pc in construcciones_bt)
        > sum(_area_union_xy(p.torres) for p in pallets_greedy)
    ):
        sin_colocar_bt = {sku: cant for sku, cant in pendientes_bt.items() if cant > 0}
        pallets_final, sin_colocar_final = pallets_bt, sin_colocar_bt
    else:
        pallets_final, sin_colocar_final = pallets_greedy, sin_colocar_greedy

    # [PATCH V6.02, sección 3] Rescue mode -SOLO cuando quedó demanda sin
    # colocar. Nunca reemplaza el camino normal: intenta mejorarlo, y el
    # resultado solo se acepta si el score final es estrictamente mejor
    # (ver `rescue_solver._score_solucion`) -de lo contrario se conserva
    # `pallets_final`/`sin_colocar_final` de arriba tal cual, sin ningún
    # cambio de comportamiento.
    if sin_colocar_final:
        from src.rescue_solver import RESCUE_TIME_MAX_SECONDS, _score_solucion, rescue_solver, skus_completos

        # [PATCH V6.12-R2-A1] Los deadlines de rescue/repair/exact/global
        # (abajo) pasan a CPU-time (`time.process_time()`) -mismo dominio
        # temporal que sus `reloj` internos (rescue_solver.py,
        # repair_solver.py, global_rescue.py, y el orquestador de
        # exact_repair.py), corregido tras la auditoría R2-A0/R2-A1: antes
        # eran `time.time()` (reloj de pared), sensible a la contención de
        # otros CDs corriendo en paralelo en el mismo host.
        # [ojo -aliasing] `rescue_solver` recibe los MISMOS objetos
        # `PalletV5` de `pallets_final` (los envuelve, no los copia) y los
        # muta in-place mientras explora -por eso el score "de antes" se
        # calcula ACÁ, con los datos de ESTE momento, no releyendo
        # `pallets_final` después de la llamada (para entonces ya puede
        # estar mutado a lo que sea que el rescue haya dejado puesto).
        total_final = demanda_total - sum(sin_colocar_final.values())
        pendientes_actual = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
        # [PATCH V6.04, sección 3] SKUs completos en el camino normal -el
        # mismo "baseline protegido" que usa rescue_solver puertas adentro,
        # acá para la comparación de aceptar/rechazar el resultado ENTERO.
        skus_protegidos_cd = skus_completos(pendientes_actual, por_sku)
        score_actual = _score_solucion(total_final, pendientes_actual, por_sku, pallets_final, skus_protegidos_cd)

        deadline_rescue = time.process_time() + RESCUE_TIME_MAX_SECONDS
        # [PATCH V6.12-D7B-P2] El kwarg SOLO se envía en contexto probe: fuera
        # de él la llamada es idéntica a la de siempre.
        kwargs_rescue = {} if presupuesto_rescue_nodos is None else {"presupuesto_nodos": presupuesto_rescue_nodos}
        pallets_rescue, sin_colocar_rescue, stats_rescue = rescue_solver(
            pallets_final, sin_colocar_final, por_sku, capacidad_cama_por_sku, nivel_por_sku,
            tope_pallet_por_sku, n_pallets, presupuesto, deadline=deadline_rescue, **kwargs_rescue,
        )
        total_rescue = demanda_total - sum(sin_colocar_rescue.values())
        pendientes_rescue = {**{sku: 0 for sku in por_sku}, **sin_colocar_rescue}
        score_rescue = _score_solucion(total_rescue, pendientes_rescue, por_sku, pallets_rescue, skus_protegidos_cd)
        aceptado = score_rescue > score_actual
        if aceptado:
            pallets_final, sin_colocar_final = pallets_rescue, sin_colocar_rescue

        # [PATCH V6.04, sección 14] Si el rescue V6.02 no llegó al 100%,
        # intentar el Repair Solver v2 (coverage-aware LNS + neighborhoods
        # iterativos + ejection chains) sobre lo que haya quedado -nunca
        # reemplaza al rescue, solo lo mejora con el mismo criterio de
        # score de arriba.
        if sin_colocar_final:
            from src.repair_solver import RESCUE_TIME_MAX_SECONDS as REPAIR_TIME_MAX_SECONDS
            from src.repair_solver import repair_solver

            total_pre_repair = demanda_total - sum(sin_colocar_final.values())
            pendientes_pre_repair = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
            score_pre_repair = _score_solucion(
                total_pre_repair, pendientes_pre_repair, por_sku, pallets_final, skus_protegidos_cd,
            )
            deadline_repair = time.process_time() + REPAIR_TIME_MAX_SECONDS
            pallets_repair, sin_colocar_repair, stats_repair = repair_solver(
                pallets_final, sin_colocar_final, por_sku, capacidad_cama_por_sku, nivel_por_sku,
                tope_pallet_por_sku, n_pallets, presupuesto, skus_protegidos_cd, deadline=deadline_repair,
            )
            total_repair = demanda_total - sum(sin_colocar_repair.values())
            pendientes_repair = {**{sku: 0 for sku in por_sku}, **sin_colocar_repair}
            score_repair = _score_solucion(
                total_repair, pendientes_repair, por_sku, pallets_repair, skus_protegidos_cd,
            )
            if score_repair > score_pre_repair:
                pallets_final, sin_colocar_final = pallets_repair, sin_colocar_repair
            if pallets_final:
                pallets_final[-1].metadata["repair_stats"] = stats_repair

        # [PATCH V6.04, sección 14] Último fallback: Exact Local Repair
        # (OR-Tools CP-SAT) sobre un vecindario chico y acotado -solo si
        # el Repair Solver v2 tampoco llegó al 100%. Se prueba contra CADA
        # pallet del CD (la demanda faltante no está atada a uno en
        # particular) y se conserva solo si mejora el score global.
        if sin_colocar_final:
            from src.exact_repair import EXACT_REPAIR_TIME_MAX_SECONDS, exact_repair_orquestado

            deadline_exact = time.process_time() + EXACT_REPAIR_TIME_MAX_SECONDS * 3
            stats_exact_total = {"activado": True, "intentos": 0, "exitos": 0, "cajas_recuperadas": 0}
            for idx in range(len(pallets_final)):
                if not sin_colocar_final or time.process_time() > deadline_exact:
                    break
                total_pre_exact = demanda_total - sum(sin_colocar_final.values())
                pendientes_pre_exact = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
                score_pre_exact = _score_solucion(
                    total_pre_exact, pendientes_pre_exact, por_sku, pallets_final, skus_protegidos_cd,
                )
                pallet_exact, sin_colocar_exact, stats_exact = exact_repair_orquestado(
                    pallets_final[idx], por_sku, sin_colocar_final, tope_pallet_por_sku, presupuesto,
                    deadline=deadline_exact,
                )
                total_exact = total_pre_exact + stats_exact.get("cajas_recuperadas", 0)
                pallets_intento = list(pallets_final)
                pallets_intento[idx] = pallet_exact
                score_exact = _score_solucion(
                    total_exact, {**{sku: 0 for sku in por_sku}, **sin_colocar_exact}, por_sku,
                    pallets_intento, skus_protegidos_cd,
                )
                stats_exact_total["intentos"] += stats_exact.get("intentos", 0)
                stats_exact_total["exitos"] += stats_exact.get("exitos", 0)
                stats_exact_total["cajas_recuperadas"] += stats_exact.get("cajas_recuperadas", 0)
                if score_exact > score_pre_exact:
                    pallets_final = pallets_intento
                    sin_colocar_final = sin_colocar_exact
            if pallets_final:
                pallets_final[-1].metadata["exact_repair_stats"] = stats_exact_total

        # [PATCH V6.05, Fase 2] Último fallback: Global Rescue -reconstruye
        # el CD ENTERO desde `n_pallets` pallets vacíos con Beam Search
        # (`src/global_rescue.py`), cuando NINGUNA capa de reparación local
        # (Rescue V6.02, Repair V6.04, Exact Local Repair, todas arriba)
        # llegó al 100%. Se activa únicamente si, después de TODAS esas
        # capas, sigue quedando demanda sin colocar (`sin_colocar_final`
        # no vacío, equivalente a `cajas_colocadas < demanda_total`) -no
        # reemplaza ninguna capa previa, no se toca nada de lo de arriba.
        if sin_colocar_final:
            from src.global_rescue import GLOBAL_RESCUE_TIME_SECONDS, global_rescue
            from src.validacion_v5 import validar_pallet_v5

            total_pre_global = demanda_total - sum(sin_colocar_final.values())
            pendientes_pre_global = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
            score_pre_global = _score_solucion(
                total_pre_global, pendientes_pre_global, por_sku, pallets_final, skus_protegidos_cd,
            )
            deadline_global = time.process_time() + GLOBAL_RESCUE_TIME_SECONDS
            pallets_global, sin_colocar_global, stats_global = global_rescue(
                pallets_final, sin_colocar_final, por_sku, capacidad_cama_por_sku, nivel_por_sku,
                tope_pallet_por_sku, n_pallets, cd, presupuesto, deadline=deadline_global, contador=contador,
            )
            total_global = demanda_total - sum(sin_colocar_global.values())
            pendientes_global = {**{sku: 0 for sku in por_sku}, **sin_colocar_global}
            score_global = _score_solucion(
                total_global, pendientes_global, por_sku, pallets_global, skus_protegidos_cd,
            )
            # [fallback obligatorio, pedido explícito del usuario: "el
            # resultado de Global Rescue nunca puede empeorar el mejor
            # resultado anterior"] Doble red de seguridad antes de aceptar
            # el reemplazo: (a) el score debe ser ESTRICTAMENTE mejor que
            # el incumbent -igual o peor conserva `pallets_final`/
            # `sin_colocar_final` tal cual, sin tocar nada; (b) TODOS los
            # pallets candidatos deben pasar `validar_pallet_v5` -Global
            # Rescue ya valida internamente (`stats_global["errores_
            # geometricos"]`), pero se re-verifica acá, en la frontera del
            # pipeline, sin confiar ciegamente en el resultado de un módulo
            # ajeno para decidir qué se devuelve como resultado final.
            geometria_valida = all(validar_pallet_v5(p) == [] for p in pallets_global)
            if score_global > score_pre_global and geometria_valida:
                pallets_final, sin_colocar_final = pallets_global, sin_colocar_global
            if pallets_final:
                pallets_final[-1].metadata["global_rescue_stats"] = stats_global

        # [PATCH V6.03, sección 12] Instrumentación de uso del rescue, con
        # los nombres de campo exactos que pide el patch -para que el
        # reporte multi-CD (src/validacion_multicd.py) pueda leerla sin
        # adivinar convenciones.
        if pallets_final:
            cajas_despues = total_rescue if aceptado else total_final
            pallets_final[-1].metadata["rescue_stats"] = {
                **stats_rescue,
                "rescue_activado": True,
                "rescue_motivo": (
                    f"{demanda_total - total_final} cajas sin colocar tras el camino normal "
                    f"(greedy+DFS+LNS) con pallets_objetivo={n_pallets} fijado"
                ),
                "rescue_cajas_antes": total_final,
                "rescue_cajas_despues": cajas_despues,
                "rescue_cajas_recuperadas": cajas_despues - total_final,
                "rescue_tiempo_s": stats_rescue.get("tiempo_segundos"),
                "rescue_conflictos_evaluados": stats_rescue.get("conflictos_evaluados"),
                "rescue_blockers_retirados": stats_rescue.get("blockers_retirados"),
                "rescue_skus_faltantes_antes": sorted(sku for sku, cant in pendientes_actual.items() if cant > 0),
            }

    return pallets_final, sin_colocar_final


# [camino abierto, sin Pallets_Objetivo -pedido explícito del usuario tras
# comparar una captura real del render isométrico contra una foto de un
# pallet físico: "el 100% o lo maximo posible de la superficie de cada cama
# tiene que estar llena... recien pasar a la siguiente cama"] Con cuántos
# pasos de búsqueda binaria intentar bajar de `N_greedy`.
#
# [subido de vuelta a 2->5 -corregido, bug real de esta sesión] Se había
# bajado a 2 (y agregado un tope de 5s aparte al sondeo, ver `con_lns` en
# `_empacar_n_pallets`) para que la suite de tests no tardara 43 minutos
# -pero el usuario reportó, con una captura real de un pallet real vuelto
# a correr, que TODAVÍA quedaban huecos visibles. Medido directo
# (`ocupacion_xy` de los pallets reales del resultado): 78%-95% de huella
# cubierta, NO cerca de 100% -confirmando el reclamo. La causa: recortar
# el presupuesto de búsqueda para la suite de tests también le recortaba
# presupuesto real al cubicaje de producción, contradiciendo la prioridad
# explícita del usuario ("máxima densidad, acepto minutos"). El tope de 5s
# aparte del sondeo se sacó (ver `con_lns`); acá se sube el número de
# pasos -la suite de tests igual queda protegida por el escalado de
# `_tiempo_max_dfs`/`_tiempo_max_lns` por demanda (datasets sintéticos
# chicos siguen convergiendo rápido), no por este número.
#
# [PATCH V6.12-R2-B] `_empacar_optimizado` ya NO usa esta constante
# directamente -el binary search viejo se reemplazó por Policy A
# (`src.busqueda_n_pallets.politica_a_descenso`), que reusa el MISMO
# valor (5) bajo el nombre `POLICY_A_MAX_SOLVES` -mismo presupuesto,
# gobierna una política distinta (descenso persistente, no bisección). Se
# deja esta constante tal cual (no se borra, no se cambia su valor) por
# la historia de por qué es 5, documentada arriba.
COMBINACION_ABIERTO_MAX_INTENTOS_BUSQUEDA = 5


def _empacar_optimizado(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    presupuesto: float,
    cd: str,
    contador: list[int],
    paralelo_lns: bool,
) -> list[PalletV5]:
    """[camino abierto, ver comentario junto a COMBINACION_ABIERTO_MAX_
    INTENTOS_BUSQUEDA] `_empacar` (greedy de 1 caja a la vez, sin vuelta
    atrás) ya coloca el 100% de la demanda por construcción -su corte es
    agotar `pendientes`, no falta de espacio- pero la reparte con huecos
    dentro de cada cama porque nunca puede deshacer una elección para
    dejarle lugar a otro SKU que complementaría mejor el piso. Retar al
    backtracking+LNS YA probado (`_empacar_n_pallets`, hoy solo se usaba con
    `Pallets_Objetivo`) a colocar la MISMA demanda completa en MENOS
    pallets que el greedy lo obliga a combinar SKUs dentro de la misma cama
    para que todo siga entrando -eso es, en este motor, lo mismo que "tapizar
    la cama antes de subir de nivel".

    [PATCH V6.12-R2-B, reemplaza el binary search viejo] Búsqueda de la N
    mínima de pallets que sigue colocando el 100% de la demanda ORIGINAL
    (no la del greedy, para no arrastrar sus decisiones subóptimas), vía
    `src.busqueda_n_pallets` -ver ese módulo para el diseño completo
    (auditoría V6.12-R1/R2-B0/R2-B de esta sesión). El binary search
    viejo trataba "`_empacar_n_pallets(con_lns=False)` no llegó al 100%"
    como PRUEBA de infactibilidad (`lo = mid + 1`) -bug real: "no
    encontrado dentro del presupuesto" nunca prueba nada, solo es
    `UNKNOWN`. El reemplazo:

    1. Calcula un `hard_lower_bound` matemático (peso + volumen + Cajas
       por PH, `busqueda_n_pallets.hard_lower_bound`) -ningún N por debajo
       puede colocar el 100%, sin importar el algoritmo; se descarta
       GRATIS, sin gastar un solo sondeo.
    2. `Policy A` (`politica_a_descenso`): desciende de a 1 desde
       `n_greedy - 1` hasta el hard bound (tope 5 solves) -un sondeo
       `UNKNOWN` se registra pero NUNCA corta el descenso (a diferencia
       del bug viejo). El resultado es siempre "la N mínima que se
       demostró FEASIBLE", nunca "la N que sobrevivió a la búsqueda".
    3. Materialización: SEPARADA de la búsqueda -una sola corrida FINAL,
       con LNS completo, en la N que ganó (`best_feasible`) -acá sí se
       busca la mejor densidad posible, no solo factibilidad. Si esa
       corrida no llega al 100% (más raro, pero posible: el LNS
       multi-reinicio puede no reproducir lo que el sondeo YA demostró
       factible, por variación de semillas), se usa el `witness` real del
       sondeo -NUNCA se retrocede a `pallets_greedy` habiendo demostrado
       constructivamente una N menor.

    `contador` sigue sin resetearse entre intentos (contador global de IDs
    únicos, ver comentario histórico de esta función); los intentos
    descartados dejan huecos cosméticos en la numeración, nunca una
    colisión de ID."""
    pendientes_originales = dict(pendientes)
    pallets_greedy = _empacar(
        dict(pendientes_originales), por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, cd, contador,
    )
    n_greedy = len(pallets_greedy)
    if n_greedy <= 1:
        return pallets_greedy  # nada que comprimir

    from src.busqueda_n_pallets import BusquedaState, hard_lower_bound, politica_a_descenso

    hard_lb = hard_lower_bound(pendientes_originales, por_sku, tope_pallet_por_sku)
    if hard_lb > n_greedy:
        # [invariante -pedido explícito, sección B] `_empacar` (greedy) ya
        # demostró CONSTRUCTIVAMENTE que n_greedy es FEASIBLE -un hard
        # bound matemático que diga que hace falta MÁS que eso es una
        # contradicción real (el bound estaría mal, no la solución
        # greedy). Nunca debería pasar; si pasa, hay que auditar
        # `busqueda_n_pallets.hard_lower_bound` antes de seguir, no
        # silenciarlo.
        raise AssertionError(
            f"[V6.12-R2-B] hard_lower_bound={hard_lb} > n_greedy={n_greedy} para CD={cd} -- "
            "el bound matemático contradice una solución greedy ya válida; auditar el bound "
            "(src/busqueda_n_pallets.hard_lower_bound) antes de continuar."
        )

    state = BusquedaState(hard_lower_bound=hard_lb)
    state.registrar_feasible_directo(n_greedy, pallets_greedy)
    politica_a_descenso(
        state, pendientes_originales, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, paralelo_lns,
    )

    best_n = state.best_feasible
    witness = state.best_feasible_pallets

    # Materialización -SIEMPRE una corrida final con LNS completo en la N
    # ganadora (idéntico en espíritu a lo que ya hacía el código viejo en
    # `hi`) -la búsqueda de arriba NUNCA decide directamente qué layout se
    # exporta (sección A de la autorización).
    pallets_final, sin_colocar_final = _empacar_n_pallets(
        dict(pendientes_originales), por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, best_n, paralelo_lns=paralelo_lns,
    )
    metadata_optimality = {
        "status": state.optimality_status(),
        "hard_lower_bound": hard_lb,
        "best_feasible_n": best_n,
        "n_greedy": n_greedy,
        "solves_realizados": state.solves_realizados,
        "trace": state.trace,
    }
    if not sin_colocar_final:
        if pallets_final:
            pallets_final[-1].metadata["optimality_status"] = metadata_optimality
        return pallets_final

    # [pedido explícito -sección A] la corrida final con LNS completo no
    # llegó al 100% -si YA demostramos constructivamente que `best_n` es
    # FEASIBLE (el witness real del sondeo, o `pallets_greedy` si
    # `best_n == n_greedy`), usarlo: nunca retroceder a una solución peor
    # habiendo demostrado una mejor.
    if witness is not None:
        if witness:
            witness[-1].metadata["optimality_status"] = {
                **metadata_optimality, "fuente": "witness_probe_no_reproducido_por_LNS_final",
            }
        return witness
    return pallets_greedy  # no debería llegar nunca acá si `state` es consistente


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
    paralelo_lns: bool = True,
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
    el comportamiento de siempre si no se pasa este parámetro).

    `paralelo_lns` (default `True`) -pedido explícito del usuario: "como
    podemos hacer para que no demore tanto". Cuando el DFS no completa
    toda la demanda, el LNS prueba varias semillas en procesos separados
    (`ProcessPoolExecutor`) para bajar el tiempo de reloj. Poner esto en
    `False` cuando el LLAMADOR ya está paralelizando por CD (ver
    `pipeline_sku_bloque.py`) -evita anidar dos pools de procesos, que
    satura los núcleos disponibles en vez de acelerar (N CDs en paralelo x
    5 reinicios cada uno son muchos más procesos que núcleos reales)."""
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
            cd, contador, pallets_objetivo, paralelo_lns=paralelo_lns, priorizar_grandes=True,
        )
        for sku, cant in sin_colocar_barrido.items():
            sin_colocar[sku] = sin_colocar.get(sku, 0) + cant
    else:
        pallets = _empacar_optimizado(
            pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, cd, contador,
            paralelo_lns,
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

    if sin_colocar:
        # [sección 5] Diagnóstico de motivo de rechazo -puramente de
        # lectura sobre el resultado ya congelado, no cambia `pallets` ni
        # ninguna decisión de armado (ver src/diagnostico_no_colocadas.py).
        pallets[-1].metadata["diagnostico_no_colocadas"] = diagnostico_no_colocadas.diagnosticar(
            pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        )

    return pallets
