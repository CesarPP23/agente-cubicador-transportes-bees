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
4. [reescrito -pedido explícito del usuario: "primero todos los licores...
   la siguiente cama deberia ser de lacteos o nabs"] Se reemplazó la
   competencia simultánea por nivel (todas las categorías mezclándose
   libremente, con nivel solo como desempate) por 4 BANDAS estrictamente
   secuenciales (`_banda_de_sku`): banda 1 Licores, banda 2 Lácteos,
   banda 3 NABs, banda 4 "remanente" (Aseo, Importados, Merch,
   Comestibles, Cigarros -y cualquier SKU forzado a nivel remate por
   Subcategoría RTD/Energizante, ver derivados.py- mezclados libremente
   entre sí). La banda es el PRIMER criterio de la competencia por
   cuboide libre (antes de la Z), así que una banda menor SIEMPRE gana
   sobre una mayor mientras tenga algún lugar disponible, por lejano que
   sea -eso agota Licores en la práctica antes de que Lácteos empiece a
   colocarse, sin necesitar una pasada separada ni resetear el estado 3D.
   Dentro de la MISMA banda (en particular banda 4, remanente) las
   categorías compiten en igualdad de condiciones -ninguna es "más alta"
   que otra- y SÍ pueden compartir la misma cama, incluso apiladas una
   sobre otra. Cigarros dejó de ser un caso especial "siempre lo más
   alto" (pedido explícito: "ya no es obligatorio que sea lo más alto");
   es un miembro más de la banda remanente. La única restricción física
   que sigue vigente por columna es que nada quede apoyado DIRECTAMENTE
   encima de soporte de una banda mayor (`_soporte_viola_banda`) -en la
   práctica esto ya casi nunca se dispara entre bandas 1-3 (el orden
   estricto ya lo evita de por sí) y nunca se dispara dentro de la banda
   4 (misma banda, nunca es "mayor" que sí misma).
4b. [alto compartido en la banda remanente -pedido explícito: "categorias
   disntinas si pueden compartir la misma cama siempre y cuando en alto
   tambien sea compartido"] Cuando la banda 4 arma una cama mezclando
   categorías distintas, una caja nueva solo entra en una Z donde ya hay
   otras cajas de la banda remanente si su alto coincide (dentro de
   `TOLERANCIA_ALTURA_CAMA_CM`) con el de TODO lo que ya está ahí -evita
   camas con perfiles dispares (una caja bajita al lado de una alta dejan
   un hueco que nadie más aprovecha). Las bandas 1-3 (una sola categoría
   cada una: Licores/Lácteos/NABs) no llevan esta restricción -la regla,
   tal como la pidió el usuario, es específica de mezclar categorías
   distintas en el remanente.
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
   aparte. [se retiró acá la reserva de altura dedicada para Cigarros que
   existió en una versión anterior de este archivo: dejó de tener sentido
   en cuanto Cigarros pasó a ser un miembro más de la banda remanente
   (sección 4) en vez del único SKU que siempre pierde la competencia por
   nivel -ver PATCH_LOG.md, sección "reescritura de bandas".]
"""
import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import (
    _altura_presupuesto,
    _area_union_xy,
    _PalletEnConstruccion,
    _reconstruir_en_construccion,
)
from src.torres import TorreCandidate, generar_torres_candidatas, generar_torres_candidatas_todas_orientaciones

TOL = 1e-6

# [sección 6] Categorías que pueden acostarse/voltearse libremente para
# aprovechar huecos irregulares -pedido explícito del usuario. NABs NUNCA
# entra acá: siempre de pie (mismas 2 orientaciones que el resto).
CATEGORIAS_ORIENTACION_FLEXIBLE = {"Comestibles", "Aseo", "Cigarros"}

# [sección 4] Bandas estrictamente secuenciales -concepto propio de este
# armador, DISTINTO de `config.Nivel_Categoria` (que sigue existiendo tal
# cual para reportes/exports). 1-3 son de una sola categoría cada una; 4
# agrupa todo lo que antes competía "por nivel" al final (Aseo,
# Importados, Merch, Comestibles, Cigarros, y cualquier SKU forzado a
# nivel remate por Subcategoría RTD/Energizante -ver derivados.py).
BANDA_LICORES = 1
BANDA_LACTEOS = 2
BANDA_NABS = 3
BANDA_REMANENTE = 4

_BANDA_POR_CATEGORIA_ESTRICTA = {
    "Licores": BANDA_LICORES,
    "Lácteos": BANDA_LACTEOS,
    "NABs": BANDA_NABS,
}

# [sección 4b] Tolerancia de alto entre cajas de categorías distintas que
# comparten una misma cama dentro de la banda remanente -pedido explícito
# del usuario ("categorias disntinas si pueden compartir la misma cama
# siempre y cuando en alto tambien sea compartido"). Mismo valor (8cm) ya
# calibrado contra datos reales en una versión anterior de este armador
# (con 3cm, ~91% de pallets quedaban parciales; con 8cm, ~76%).
TOLERANCIA_ALTURA_CAMA_CM = 8.0


def _banda_de_sku(categoria: str | None, nivel_categoria_original: float | None) -> int:
    """[sección 4] Deriva la banda de armado a partir de la categoría real
    del SKU y su `Nivel_Categoria` original (calculado por
    `config.nivel_de_categoria`/`derivados.py`, que YA sabe distinguir un
    SKU forzado a nivel remate por Subcategoría RTD/Energizante -ej. Four
    Loko, que es categoría Licores pero remate por regla de negocio- de
    uno que es remate por ser Comestibles/Cigarros de verdad). Cualquier
    SKU cuyo nivel original ya sea "remate o más" (`config.NIVEL_REMATE`,
    o `config.NIVEL_CIGARROS` para Cigarros/BAT) cae en la banda remanente
    sin importar su categoría textual -así Four Loko no vuelve a colarse
    en la banda de Licores solo porque su Categoria_Normalizada diga
    "Licores"."""
    if nivel_categoria_original is not None and nivel_categoria_original >= config.NIVEL_REMATE:
        return BANDA_REMANENTE
    return _BANDA_POR_CATEGORIA_ESTRICTA.get(categoria, BANDA_REMANENTE)


def _cabe_en_pallet(cand: TorreCandidate, presupuesto: float) -> bool:
    """Chequeo de geometría pura contra un pallet VACÍO -si ni siquiera acá
    entra, no va a entrar en ninguno más lleno (huella mayor a 120x100 en
    ambas orientaciones, o caja más alta que el presupuesto de altura)."""
    cols = int(config.PALLET_LARGO // cand.largo)
    filas = int(config.PALLET_ANCHO // cand.ancho)
    return cols > 0 and filas > 0 and cand.alto_caja <= presupuesto + TOL


def _soporte_viola_banda(
    pallet: PalletV5, x: float, y: float, largo: float, ancho: float, z: float,
    banda_sku: int, banda_por_sku: dict[str, int],
) -> bool:
    """[sección 4] Por columna física: una caja nunca puede quedar apoyada
    DIRECTAMENTE encima de otra de una banda mayor (ej. Licores sobre
    NABs). En z=0 (piso del pallet) no hay restricción. Para z>0, se
    identifican las torres que son el soporte real e inmediato de esta
    huella (mismo criterio que la validación anti-flotación: tope de esas
    torres exactamente en `z`, huella que se solapa) -si CUALQUIERA de esas
    torres de soporte pertenece a una banda mayor a la que se está por
    colocar, es una violación. Dentro de la banda remanente (4) esto nunca
    se dispara entre sí mismas (4 > 4 es falso) -ahí la única restricción
    de mezcla es `_altura_compatible_con_cama`."""
    if z <= TOL:
        return False
    for t in pallet.torres:
        if abs((t.z + t.altura) - z) > TOL:
            continue
        if t.x + t.largo <= x + TOL or x + largo <= t.x + TOL:
            continue
        if t.y + t.ancho <= y + TOL or y + ancho <= t.y + TOL:
            continue
        if banda_por_sku.get(t.sku, 0) > banda_sku:
            return True
    return False


def _altura_compatible_con_cama(pallet: PalletV5, z: float, alto_caja: float, banda_sku: int) -> bool:
    """[sección 4b] Solo restringe la banda remanente (4), y solo por
    ENCIMA del piso del pallet (z>0): distintas categorías SI pueden
    compartir una misma cama, pero solo si sus altos coinciden (dentro de
    `TOLERANCIA_ALTURA_CAMA_CM`) con TODO lo que ya hay puesto exactamente
    en esa Z. En el piso (z=0) no se restringe -mezclar ahí SKUs de alturas
    bien distintas es exactamente lo que el fix de "huella grande gana el
    empate" (ver PATCH_LOG.md) ya demostró que hace falta con datos reales
    (una SKU grande tipo BAT, 49cm, compartiendo piso con SKUs chicas de
    18-24cm) -y coincide con las fotos de cubicaje real del usuario, donde
    botellas de alturas distintas conviven en la misma base sin ningún
    problema. Bandas 1-3 (una sola categoría cada una) tampoco llevan esta
    restricción en ningún caso."""
    if banda_sku != BANDA_REMANENTE or z <= TOL:
        return True
    for t in pallet.torres:
        if abs(t.z - z) <= TOL and abs(t.alto_caja - alto_caja) > TOLERANCIA_ALTURA_CAMA_CM + TOL:
            return False
    return True


def _cama_es_de_otra_banda_estricta(pallet: PalletV5, z: float, banda_sku: int, banda_por_sku: dict[str, int]) -> bool:
    """[sección 4] Bandas 1-3 (Licores/Lácteos/NABs) nunca comparten cama
    (misma Z) entre sí -pedido explícito: "si la demanda pide 1 cama de
    licores la siguiente cama deberia ser de lacteos o nabs" implica que
    cada cama de estas 3 bandas pertenece a UNA sola banda, nunca mezclada
    con otra de las 3. La banda remanente (4) queda afuera por completo de
    esta restricción: puede compartir cualquier cama (con bandas 1-3 o
    consigo misma) -es, por diseño, el grupo que rellena lo que quede."""
    if banda_sku == BANDA_REMANENTE:
        return False
    for t in pallet.torres:
        if abs(t.z - z) <= TOL:
            otra_banda = banda_por_sku.get(t.sku, BANDA_REMANENTE)
            if otra_banda != BANDA_REMANENTE and otra_banda != banda_sku:
                return True
    return False


def _mejor_cuboide_para_sku(
    pallet: PalletV5, pc: _PalletEnConstruccion, cand: TorreCandidate, tope_capa: int | None,
    banda_sku: int, banda_por_sku: dict[str, int],
) -> int | None:
    """[sección 2, 4, 4b] Entre los cuboides libres que reciban 1 caja de
    `cand`, el de menor Z (más bajo) -así se llena SIEMPRE la capa más
    baja disponible antes de subir, nunca se salta a una más alta habiendo
    sitio abajo (row-first, nunca columnas). Descarta un cuboide si: (a)
    `tope_capa` (Cajas_Cama_Efectivo real del Maestro) ya se alcanzó para
    este SKU en la Z exacta de ese cuboide, (b) colocar ahí violaría el
    orden de banda por columna (`_soporte_viola_banda`), (c) esa cama ya
    es de otra banda estricta distinta (`_cama_es_de_otra_banda_estricta`),
    o (d) -solo en la banda remanente- su alto no es compatible con lo que
    ya hay puesto en esa misma cama (`_altura_compatible_con_cama`)."""
    mejor_idx, mejor_clave = None, None
    for idx, c in enumerate(pc.libres):
        if cand.largo > c.w + TOL or cand.ancho > c.h + TOL or cand.alto_caja > c.d + TOL:
            continue
        if tope_capa is not None:
            ya_en_esta_capa = sum(
                t.cantidad for t in pallet.torres if t.sku == cand.sku and abs(t.z - c.z) <= TOL
            )
            if ya_en_esta_capa >= tope_capa:
                continue
        if _cama_es_de_otra_banda_estricta(pallet, c.z, banda_sku, banda_por_sku):
            continue
        if _soporte_viola_banda(pallet, c.x, c.y, cand.largo, cand.ancho, c.z, banda_sku, banda_por_sku):
            continue
        if not _altura_compatible_con_cama(pallet, c.z, cand.alto_caja, banda_sku):
            continue
        clave = (c.z, c.volumen)
        if mejor_clave is None or clave < mejor_clave:
            mejor_idx, mejor_clave = idx, clave
    return mejor_idx


def _empacar(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    banda_por_sku: dict[str, int],
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

            # [sección 4] Entre TODOS los SKUs pendientes, cuál -colocado
            # en su mejor cuboide propio- gana. La BANDA es el primer
            # criterio: una banda menor SIEMPRE gana sobre una mayor
            # mientras tenga algún cuboide disponible, por lejano que sea
            # -así se agota Licores antes de que Lácteos empiece, Lácteos
            # antes que NABs, y NABs antes que la banda remanente, sin
            # necesitar una pasada separada. Dentro de la MISMA banda, Z
            # más baja primero (row-first), y dentro de esa Z, MAYOR
            # huella primero -no más demanda primero. Verificado con datos
            # reales (BK31, PATCH_LOG.md): priorizar demanda dejaba que
            # SKUs chicas de mucha demanda acapararan el piso mientras
            # estaba abierto, fragmentándolo en bolsillos angostos -las
            # SKUs grandes (con menos margen para encajar en cualquier
            # lado) terminaban esperando y se quedaban sin sitio. "Piezas
            # grandes primero" es la heurística estándar de bin-packing.
            # Empate de huella: más demanda pendiente primero (sigue
            # concentrando el mismo SKU en capas consecutivas).
            mejor = None
            for sku in activos:
                tope_capa = capacidad_cama_por_sku.get(sku)
                banda_sku = banda_por_sku.get(sku, BANDA_REMANENTE)
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
                    idx_libre_op = _mejor_cuboide_para_sku(pallet, pc, cand_op, tope_capa, banda_sku, banda_por_sku)
                    if idx_libre_op is None:
                        continue
                    libre_op = pc.libres[idx_libre_op]
                    clave_op = (libre_op.z, libre_op.volumen)
                    if mejor_para_sku is None or clave_op < mejor_para_sku[0]:
                        mejor_para_sku = (clave_op, cand_op, idx_libre_op)
                if mejor_para_sku is None:
                    continue
                _, cand, idx_libre = mejor_para_sku
                z_destino = pc.libres[idx_libre].z
                area = cand.largo * cand.ancho
                clave = (banda_sku, z_destino, -area, -pendientes[sku])
                if mejor is None or clave < mejor[0]:
                    mejor = (clave, sku, cand, idx_libre)

            if mejor is None:
                break  # nada entra ya en este pallet, ni siquiera más arriba

            _, sku, cand, idx_libre = mejor
            pc.colocar(cand, 1, idx_libre)
            pendientes[sku] -= 1
            colocado_en_pallet[sku] = colocado_en_pallet.get(sku, 0) + 1
            avanzo_en_este_pallet = True

        if not avanzo_en_este_pallet:
            break  # nada entró en un pallet fresco -evitar loop infinito (no debería pasar tras el chequeo previo)
        pallets.append(pallet)

    return pallets


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


# [sección 8, redistribución de dispersos] Un pallet por debajo de este
# umbral de ocupación XY es candidato a vaciarse hacia los pallets ya
# armados del mismo CD -ver `_redistribuir_dispersos`.
UMBRAL_OCUPACION_DISPERSO = 0.5


def _redistribuir_dispersos(
    pallets: list[PalletV5],
    capacidad_cama_por_sku: dict[str, int],
    banda_por_sku: dict[str, int],
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
            banda_sku = banda_por_sku.get(t.sku, BANDA_REMANENTE)
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
                idx_libre = _mejor_cuboide_para_sku(destino, pc, cand, tope_capa, banda_sku, banda_por_sku)
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


def armar_pallets_bloques(df_cd: pd.DataFrame, cd: str, contador: list[int] | None = None) -> list[PalletV5]:
    """[V-SKU_BLOQUE, camas] Punto de entrada. `df_cd` debe traer demanda
    pendiente (`Cajas_Remanente` o `Cajas_Teoricas_Redondeadas`), geometría
    efectiva reconciliada y, si está disponible, `Cajas_Cama_Efectivo`
    (derivados.py) -sin esa columna, una capa no tiene tope propio más que
    la huella/orientación elegida."""
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

    # [sección 4, bandas] Licores/Lácteos/NABs (bandas 1-3) cada una su
    # propia banda estrictamente secuencial; todo lo demás (Aseo,
    # Importados, Merch, Comestibles, Cigarros, y cualquier SKU forzado a
    # nivel remate por Subcategoría RTD/Energizante -Four Loko, ver
    # derivados.py-) cae en la banda remanente (4). Sin dato de categoría
    # (ej. la pseudo-fila BAT, que trae Categoria_Normalizada="Cigarros" y
    # Nivel_Categoria=NIVEL_CIGARROS explícitos -ver bat.py-) también cae
    # en remanente vía `_banda_de_sku`.
    banda_por_sku: dict[str, int] = {}
    if "Categoria_Normalizada" in df_cd.columns or "Nivel_Categoria" in df_cd.columns:
        for _, fila in df_cd.drop_duplicates(subset="SKU").iterrows():
            sku = fila["SKU"]
            if sku not in por_sku:
                continue
            categoria = fila.get("Categoria_Normalizada")
            nivel = fila.get("Nivel_Categoria")
            nivel_val = float(nivel) if pd.notna(nivel) else None
            banda_por_sku[sku] = _banda_de_sku(categoria, nivel_val)
    for sku in por_sku:
        banda_por_sku.setdefault(sku, BANDA_REMANENTE)

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

    pallets = _empacar(
        pendientes, por_sku, capacidad_cama_por_sku, banda_por_sku, tope_pallet_por_sku, presupuesto, cd, contador
    )

    # [sección 5] Consolidación de remanentes: los pallets que quedaron muy
    # cortos se deshacen y se reempacan juntos -si mejora (menos pallets),
    # se queda con el resultado nuevo; si no, se descarta sin tocar nada.
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
            pendientes_residual, por_sku, capacidad_cama_por_sku, banda_por_sku, tope_pallet_por_sku,
            presupuesto, cd, contador,
        )
        if len(reempacados) >= len(cortos):
            break  # no mejoró -se descarta el intento, se conserva lo que ya había
        ids_cortos = {id(p) for p in cortos}
        pallets = [p for p in pallets if id(p) not in ids_cortos] + reempacados

    # [sección 8] Después del barrido y la consolidación, algunos SKUs de
    # poca demanda pueden haber quedado solos en su propio pallet casi
    # vacío -se intenta repartirlos en el espacio libre real de los
    # pallets ya armados antes de aceptarlos como pallets aparte.
    pallets = _redistribuir_dispersos(pallets, capacidad_cama_por_sku, banda_por_sku, tope_pallet_por_sku)

    if sin_colocar and pallets:
        pallets[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        pallets.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return pallets
