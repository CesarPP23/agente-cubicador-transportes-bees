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
4. Entre SKUs de categorías distintas: Licores (nivel bajo) nunca queda
   apoyado directamente ENCIMA de NABs (nivel alto) -la regla real
   confirmada por el usuario es por COLUMNA física, no por "banda
   horizontal completa": "no se le puede encimar licores sobre nabs".
   Se verifica en cada colocación, no separando el armado en pasadas por
   nivel -todos los SKUs de todos los niveles compiten juntos por el
   cuboide libre más bajo disponible en todo momento, y solo se descarta
   una colocación si el soporte real e inmediato debajo de esa huella
   pertenece a un nivel mayor al que se está por colocar (ver
   `_soporte_viola_nivel`). Esto es deliberadamente MENOS estricto que
   "primero se agota una categoría entera antes de tocar la siguiente"
   -esa regla adicional nunca fue pedida, era una simplificación de
   implementación que dejaba pallets cortos cuando la huella de una
   categoría fragmentaba el piso de forma incompatible con la siguiente
   (ver PATCH_LOG.md, sección "competencia por nivel").
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
6. [orientación flexible] Comestibles/Aseo/Cigarros pueden acostarse o
   voltearse en cualquiera de sus 6 orientaciones (`torres.generar_torres_
   candidatas_todas_orientaciones`) para aprovechar huecos irregulares que
   ninguna orientación "de pie" calza -NABs y el resto de las categorías
   siguen con las 2 orientaciones de siempre (pedido explícito: "nabs es
   el unico que siempre tiene que ir de pie"). Como el motor sigue siendo
   el mismo MaxRects exacto, esto no relaja NADA de la garantía de soporte
   -solo le da más formas candidatas para probar en cada cuboide libre
   real.
7. [tope real por SKU] `Cajas por PH` del Maestro es el máximo físico de
   cuántas cajas de un SKU pueden ir en UN pallet (sea homogéneo o
   mezclado) -se aplica como tope duro por pallet (`tope_pallet_por_sku` +
   `colocado_en_pallet`, reseteado en cada pallet nuevo), igual mecanismo
   que ya se había probado en PH_FRACCION.
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


def _mejor_orientacion_grilla(candidatas: list[TorreCandidate]) -> TorreCandidate:
    """Fija UNA sola orientación por SKU para todo el pallet (base estricta
    120x100) -nunca mezclada, eso fragmentaba el espacio de formas que
    después ninguna orientación podía volver a aprovechar bien. Base
    estricta (no la extendida con sobresaliente): una capa puede terminar
    compartida por varios SKUs, y mezclar sobresalientes de SKUs distintos
    en direcciones distintas da un perfil irregular -ver PATCH_LOG.md,
    sección sobresaliente."""
    def _capacidad_grilla(c: TorreCandidate) -> int:
        cols = int(config.PALLET_LARGO // c.largo)
        filas = int(config.PALLET_ANCHO // c.ancho)
        return cols * filas

    return max(candidatas, key=_capacidad_grilla)


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
    """[sección 4] La regla real confirmada por el usuario es por columna
    física: una caja nunca puede quedar apoyada DIRECTAMENTE encima de otra
    de un nivel de categoría mayor (ej. Licores sobre NABs). En z=0 (piso
    del pallet) no hay restricción -cualquier categoría puede arrancar ahí.
    Para z>0, se identifican las torres que son el soporte real e inmediato
    de esta huella (mismo criterio que la validación anti-flotación: tope
    de esas torres exactamente en `z`, huella que se solapa) -si CUALQUIERA
    de esas torres de soporte pertenece a un nivel mayor al que se está por
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


def _mejor_cuboide_para_sku(
    pallet: PalletV5, pc: _PalletEnConstruccion, cand: TorreCandidate, tope_capa: int | None,
    nivel_sku: int, nivel_por_sku: dict[str, int],
) -> int | None:
    """[sección 2-4] Entre los cuboides libres que reciban 1 caja de
    `cand`, el de menor Z (más bajo) -así se llena SIEMPRE la capa más
    baja disponible antes de subir, nunca se salta a una más alta habiendo
    sitio abajo (row-first, nunca columnas). Descarta un cuboide si: (a)
    `tope_capa` (Cajas_Cama_Efectivo real del Maestro) ya se alcanzó para
    este SKU en la Z exacta de ese cuboide -evita que la geometría pura
    permita más cajas por capa de las que el Maestro valida como reales-,
    o (b) colocar ahí violaría el orden de categoría por columna (ver
    `_soporte_viola_nivel`)."""
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
        if _soporte_viola_nivel(pallet, c.x, c.y, cand.largo, cand.ancho, c.z, nivel_sku, nivel_por_sku):
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
    """[secciones 1-4, 7, 8] Un barrido completo del algoritmo de camas
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

        # [sección 4] TODOS los SKUs de TODOS los niveles compiten juntos
        # por el cuboide libre más bajo disponible -no se procesa "primero
        # una categoría entera, después la siguiente". El orden de
        # categoría (ninguna caja apoyada directo encima de una de nivel
        # mayor) lo garantiza `_mejor_cuboide_para_sku` en cada colocación
        # individual, no la secuencia del barrido.
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

            # [sección 2] Entre TODOS los SKUs pendientes, cuál -colocado
            # en su mejor cuboide propio- logra la Z más baja. Empates:
            # nivel de categoría más bajo primero (Licores antes que NABs
            # cuando ambos podrían ir igual de bajo, para que el pallet
            # tienda a formar capas limpias cuando la geometría lo permite
            # sin forzarlo), y dentro del mismo nivel, MAYOR huella
            # primero -no más demanda primero. Verificado con datos reales
            # (BK31, PATCH_LOG.md): priorizar demanda dejaba que SKUs
            # chicas de mucha demanda acapararan el piso mientras estaba
            # abierto, fragmentándolo en bolsillos angostos -las SKUs
            # grandes (que tienen MENOS margen para encajar en cualquier
            # lado) terminaban esperando y se quedaban sin sitio. "Piezas
            # grandes primero" es la heurística estándar de bin-packing:
            # colocar lo más difícil de encajar mientras todavía hay piso
            # abierto, dejar lo chico (más flexible) para después. Empate
            # de huella: más demanda pendiente primero (sigue concentrando
            # el mismo SKU en capas consecutivas, como pedía el usuario).
            # [sección 8, reserva de altura real para Cigarros -caso real:
            # pallets BAT/Cigarros con 1-6 cajas solas en su propio pallet,
            # porque el resto del contenido ya usaba TODA la altura
            # disponible (hasta 200.0 de 200.1cm) antes de que a Cigarros
            # le tocara competir. Cigarros SIEMPRE tiene que quedar
            # apoyado sobre todo lo demás (nunca al revés) -eso significa
            # que solo puede usar el margen de altura que sobre DESPUÉS de
            # acomodar el resto, así que si el resto se lo gasta todo,
            # Cigarros nunca tiene dónde ir. Mientras haya demanda
            # pendiente de Cigarros, se reserva su propia altura -SKUs de
            # cualquier otro nivel no pueden colocarse si eso invade esa
            # reserva (Cigarros mismo nunca la invade, es SU reserva)."]
            altura_reservada_cigarros = 0.0
            skus_cigarros_pendientes = [
                s for s in activos if nivel_por_sku.get(s, 0) == config.NIVEL_CIGARROS
            ]
            if skus_cigarros_pendientes:
                altura_reservada_cigarros = max(por_sku[s][0].alto_caja for s in skus_cigarros_pendientes)

            def _buscar_mejor(respetar_reserva: bool):
                mejor_local = None
                for sku in activos:
                    tope_capa = capacidad_cama_por_sku.get(sku)
                    nivel_sku = nivel_por_sku.get(sku, 0)
                    # [sección 6] Entre las candidatas "de pie" (siempre existen
                    # -son las mismas 2 de siempre) se elige la preferida por
                    # mejor grilla; las "acostado" (si las hay, solo en
                    # categorías flexibles) quedan como fallback más abajo -de
                    # pie siempre gana primero cuando sirve, acostado es último
                    # recurso, no la opción por defecto.
                    de_pie = [c for c in por_sku[sku] if "de pie" in c.orientacion] or por_sku[sku]
                    cand = _mejor_orientacion_grilla(de_pie)
                    idx_libre = _mejor_cuboide_para_sku(pallet, pc, cand, tope_capa, nivel_sku, nivel_por_sku)
                    if idx_libre is None and len(por_sku[sku]) > 1:
                        # [fallback de orientación] La orientación preferida
                        # (mejor grilla) no entra en NINGÚN cuboide libre en
                        # este momento -antes de dar por perdido este SKU en
                        # este pallet, probar sus otras orientaciones (la otra
                        # "de pie", y para categorías flexibles también las 4
                        # "acostado"). Real, verificado con datos reales: el
                        # piso se fragmenta en bolsillos con formas que no
                        # coinciden con la orientación preferida de una SKU,
                        # pero sí con otra -preferir siempre la de mejor grilla
                        # cuando sirve (así una SKU no mezcla orientaciones sin
                        # necesidad real, eso fragmentaba en versiones
                        # anteriores), y solo caer a las demás como último
                        # recurso en vez de dejar espacio utilizable sin usar.
                        for alterna in por_sku[sku]:
                            if alterna is cand:
                                continue
                            idx_libre = _mejor_cuboide_para_sku(pallet, pc, alterna, tope_capa, nivel_sku, nivel_por_sku)
                            if idx_libre is not None:
                                cand = alterna
                                break
                    if idx_libre is None:
                        continue
                    z_destino = pc.libres[idx_libre].z
                    if (
                        respetar_reserva
                        and altura_reservada_cigarros > TOL
                        and nivel_sku != config.NIVEL_CIGARROS
                        and presupuesto - (z_destino + cand.alto_caja) < altura_reservada_cigarros - TOL
                    ):
                        continue  # invadiría la reserva de altura de Cigarros -descartar esta colocación
                    area = cand.largo * cand.ancho
                    clave = (z_destino, nivel_sku, -area, -pendientes[sku])
                    if mejor_local is None or clave < mejor_local[0]:
                        mejor_local = (clave, sku, cand, idx_libre)
                return mejor_local

            mejor = _buscar_mejor(respetar_reserva=True)
            if mejor is None and altura_reservada_cigarros > TOL:
                # [sección 8, válvula de escape] Respetar la reserva no dejó
                # NINGUNA colocación válida -si ni Cigarros puede usar ese
                # margen (o no hay Cigarros disponible ahora mismo por otra
                # razón, ej. su propio tope_capa), reservarlo igual solo
                # desperdicia altura sin ayudar a nadie. Se reintenta sin la
                # reserva -progreso real gana sobre una reserva que no sirve.
                mejor = _buscar_mejor(respetar_reserva=False)

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
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
) -> list[PalletV5]:
    """[sección 8, caso real: pallets BAT/Cigarros con 1-6 cajas solas en
    su propio pallet -reportado por el usuario con fotos de cubicaje real
    sin ningún espacio libre] Un SKU de nivel alto (Cigarros/BAT, siempre
    el último en la prioridad de armado) puede perder la competencia por
    espacio en TODOS los pallets ya cerrados -no porque no hubiera lugar
    real, sino porque siempre pierde el desempate mientras algo de nivel
    más bajo todavía tuviera dónde ir- y terminar solo, en su propio
    pallet casi vacío, recién cuando ya no queda nada más con qué competir.

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

    # [orden por categoría] Licores (nivel 1) nunca arriba de NABs (nivel
    # 6); remate (Comestibles/Cigarros/Four Loko -ver derivados.py-, nivel
    # 7) siempre lo último. Sin dato de categoría (ej. la pseudo-fila BAT,
    # que no trae Categoria_Normalizada propia) se asume remate -Cigarros
    # ya es remate por Categoría, es el mismo producto físico.
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
        pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, cd, contador
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
            pendientes_residual, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            presupuesto, cd, contador,
        )
        if len(reempacados) >= len(cortos):
            break  # no mejoró -se descarta el intento, se conserva lo que ya había
        ids_cortos = {id(p) for p in cortos}
        pallets = [p for p in pallets if id(p) not in ids_cortos] + reempacados

    # [sección 8] Después del barrido y la consolidación, algunos SKUs de
    # nivel alto y poca demanda (típicamente Cigarros/BAT) pueden haber
    # quedado solos en su propio pallet casi vacío -se intenta repartirlos
    # en el espacio libre real de los pallets ya armados antes de
    # aceptarlos como pallets aparte.
    pallets = _redistribuir_dispersos(pallets, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku)

    if sin_colocar and pallets:
        pallets[-1].metadata["sin_colocar"] = sin_colocar
    elif sin_colocar:
        contador[0] += 1
        pallets.append(PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd, metadata={"sin_colocar": sin_colocar}))

    return pallets
