import config
from models import Cama, Pallet, PalletLinea


def _construir_lineas(camas: list[Cama], info_sku: dict[str, dict]) -> list[PalletLinea]:
    totales: dict[str, int] = {}
    for cama in camas:
        for sku, qty in cama.cantidades.items():
            totales[sku] = totales.get(sku, 0) + qty

    lineas = []
    for sku, qty in totales.items():
        meta = info_sku[sku]
        lineas.append(
            PalletLinea(
                sku=sku,
                descripcion=meta["descripcion"],
                categoria=meta["categoria"],
                nivel_categoria=meta["nivel_categoria"],
                cajas_demanda_oficial=qty,
                cajas_extra_consolidacion=0,
                peso_no_validable=meta["peso_no_validable"],
            )
        )
    return lineas


def _altura_desde_camas(camas: list[Cama]) -> float:
    return config.ALTURA_PALLET_VACIO + sum(c.altura_cama for c in camas)


def calcular_altura_pallet(pallet: Pallet) -> float:
    """[V3 / sección 10] Única función de altura de todo el sistema:
    `Altura_Final = Altura_Pallet_Vacio + suma(Altura_Cama)`. Nunca calcular
    un PH (o cualquier otro tipo de pallet) como `camas * alto_caja` sin sumar
    la tarima.

    Nota: una caja BAT queda representada como una Cama más dentro de
    `pallet.camas` (ver bat._colocar_bat), no aparte -así el resto del motor
    (orden vertical, remate exclusivo, esta misma función) no necesita una
    rama especial para BAT. `pallet.cajas_bat` es solo trazabilidad/auditoría
    de qué caja BAT es y qué SKUs tiene adentro; sumarla de nuevo acá
    duplicaría la altura que ya aporta su Cama.
    """
    return _altura_desde_camas(pallet.camas)


def _es_flexible(cama: Cama) -> bool:
    """[V4b / fotos de los 42 pallets reales] Con mezcla libre por geometría,
    cualquier cama puede reubicarse durante la consolidación -ya no hay una
    noción de "carga" que deba quedarse fija en la base por nivel de
    categoría (esa jerarquía se retiró de `packing_2d.generar_camas` y de
    `armar_pallets`). `Cama.es_flexible` (nivel_efectivo >= NABs) queda en el
    modelo para trazabilidad/auditoría, no como gate acá."""
    return True


def _remate_de(pallet: Pallet) -> str | None:
    for cama in pallet.camas:
        cr = cama.categoria_remate
        if cr is not None:
            return cr
    return None


def _remate_compatible(pallet: Pallet, cama: Cama) -> bool:
    """Antes recibía un string de categoría suelto; ahora recibe la cama porque
    con camas mixtas `categoria_remate` puede ser None (ej. cama de solo NABs, o
    NABs mezclada con niveles bajos) y eso también es información relevante."""
    cr = cama.categoria_remate
    if cr is not None:
        actual = _remate_de(pallet)
        return actual is None or actual == cr
    return _remate_de(pallet) is None  # sin remate: solo si el pallet aún no tiene remate


def _peso_cama(cama: Cama, info_sku: dict[str, dict]) -> float:
    """[PARCHE P4] Peso de una cama, para poder usarlo como restricción."""
    return sum(qty * (info_sku[sku].get("peso_caja") or 0.0) for sku, qty in cama.cantidades.items())


def _peso_desde_camas(camas: list[Cama], info_sku: dict[str, dict]) -> float:
    return sum(_peso_cama(c, info_sku) for c in camas)


def _puede_soportar(pallet: Pallet) -> bool:
    """[PARCHE P5] ¿La cama que hoy está arriba del pallet puede sostener otra?

    [V3 / sección 10] `FILL_RATIO_MIN_SOPORTE=0` NO debe interpretarse como
    "seguridad validada" -que dé un número de pallets más parecido al real no
    prueba estabilidad física. Sigue en 0 porque es el valor con el que se
    corrió la última validación contra pallets reales, pero es una restricción
    de seguridad de carga sin validar formalmente, no una que se optimizó.
    """
    if not pallet.camas:
        return True
    return pallet.camas[-1].fill_ratio >= config.FILL_RATIO_MIN_SOPORTE


def _limite_altura(pallet: Pallet) -> float:
    """[V3 / sección 6, 11.4] Tope operacional único para TODAS las camas
    (incluido remate no-BAT, ej. Comestibles): config.ALTURA_MAX_OBSERVADA.

    Ya no hay una distinción "techo normal (205) vs. tope duro (210) según si
    el pallet ya superó el mínimo", ni una reserva de altura para remate
    (RESERVA_ALTURA_REMATE quedó en 0, ver config.py) -esa reserva existía
    para Cigarros, que ahora se maneja aparte con hosts BAT dinámicos
    (bat.asignar_hosts_bat), no reservando margen de antemano en pallets que
    quizás nunca lo necesiten.

    ALTURA_MAX_OBSERVADA es un tope OPERACIONAL, no un límite normativo
    validado (config.ALTURA_HARD_VALIDADA sigue en None) -es el máximo
    observado en la operación real (215cm), usado acá porque el motor
    necesita algún punto de corte para decidir cuándo dejar de apilar.
    """
    return config.ALTURA_MAX_OBSERVADA


def _cabe(pallet: Pallet, cama: Cama, info_sku: dict[str, dict]) -> bool:
    """Restricciones duras para apoyar `cama` sobre `pallet`: altura (siempre) y,
    si config.PESO_ES_RESTRICCION_DURA, peso. [V4b / fotos de los 42 pallets
    reales] Confirmado con Omar: la única restricción dura de armado es la
    altura -el peso se sigue calculando y reportando (validacion_peso.py,
    ESTADO_ALERTA_PESO) pero por defecto ya no bloquea una combinación que
    geométricamente conviene."""
    if cama.altura_cama > _limite_altura(pallet) - pallet.altura_final + 1e-9:
        return False
    if config.PESO_ES_RESTRICCION_DURA and pallet.peso_estimado + _peso_cama(cama, info_sku) > config.PESO_HARD_KG + 1e-9:
        return False
    return _puede_soportar(pallet)  # [PARCHE P5]


def _colocar(pallet: Pallet, cama: Cama, info_sku: dict[str, dict]) -> None:
    pallet.camas.append(cama)
    pallet.altura_final += cama.altura_cama
    pallet.peso_estimado += _peso_cama(cama, info_sku)  # [P4] peso acumulado en vivo


def _crear_pallet(cd: str, contador: list[int]) -> Pallet:
    contador[0] += 1
    return Pallet(
        id=f"PH-MIX-{cd}-{contador[0]:03d}",
        cd=cd,
        tipo="Mixto",
        altura_final=config.ALTURA_PALLET_VACIO,
        peso_estimado=0.0,
    )


def _asignar_camas(
    camas: list[Cama],
    cd: str,
    contador: list[int],
    pallets_abiertos: list[Pallet],
    info_sku: dict[str, dict],
) -> None:
    """[V4b / fotos de los 42 pallets reales] Bin-packing best-fit SIN pases
    por nivel de categoría: para cada cama (de mayor a menor altura, con el
    peso como segundo criterio -las camas más pesadas se procesan primero,
    así tienden a terminar más abajo en el pallet que las reciba, como en las
    fotos- busca entre TODOS los pallets ya abiertos del CD -incluidos los
    homogéneos, cualquier cosa puede rematar cualquier pallet- el que tenga
    menos espacio libre y aun así la reciba; solo abre un pallet nuevo si
    ninguno de los existentes sirve.

    Nota: si una cama no entra ni en un pallet vacío (ej. su propia altura ya
    supera el límite), igual se coloca en el pallet nuevo y el Paso 5 la
    marca. Es deliberado: nunca se descarta demanda en silencio.
    """
    for cama in sorted(camas, key=lambda c: (-c.altura_cama, -_peso_cama(c, info_sku))):
        candidatos = [p for p in pallets_abiertos if _cabe(p, cama, info_sku)]
        destino = max(candidatos, key=lambda p: p.altura_final) if candidatos else None
        if destino is None:
            destino = _crear_pallet(cd, contador)
            pallets_abiertos.append(destino)
        _colocar(destino, cama, info_sku)


def _consolidar_pallets(pallets_cd: list[Pallet], info_sku: dict[str, dict]) -> list[Pallet]:
    """Red de seguridad final: vacía, cuando es posible, los pallets que quedaron por
    debajo del mínimo, encimando sus camas en otros pallets del mismo CD que
    aún tengan espacio, en vez de dejarlos como pallets casi vacíos."""
    pequenos = sorted(
        (p for p in pallets_cd if p.altura_final < config.ALTURA_TOLERADO_MIN),
        key=lambda p: p.altura_final,
    )
    eliminados: set[int] = set()
    tocados: set[int] = set()

    for origen in pequenos:
        if origen.altura_final >= config.ALTURA_TOLERADO_MIN:
            continue  # ya se completó recibiendo camas de otro pallet chico

        # [PARCHE P6] Altura de referencia congelada explícitamente. El guard
        # "nunca mover hacia un pallet peor" debe comparar contra la altura del
        # ORIGEN ANTES de empezar a vaciarlo, no contra un valor que muta.
        altura_referencia = origen.altura_final

        # [V4b] Con mezcla libre, cualquier cama es movible (_es_flexible ya
        # siempre True) -se ordenan por -altura_cama solo para decidir en qué
        # orden INTENTAR moverlas afuera; las que no se mueven ("sobrantes")
        # conservan su posición relativa original.
        flexibles = sorted(origen.camas, key=lambda c: -c.altura_cama)
        movidas: set[int] = set()

        for cama in flexibles:
            candidatos = [
                candidato
                for candidato in pallets_cd
                if candidato is not origen
                and id(candidato) not in eliminados
                and candidato.altura_final >= altura_referencia
                and _cabe(candidato, cama, info_sku)
            ]
            destino = max(candidatos, key=lambda c: c.altura_final) if candidatos else None
            if destino is None:
                continue
            _colocar(destino, cama, info_sku)
            tocados.add(id(destino))
            movidas.add(id(cama))

        nuevas_camas = [c for c in origen.camas if id(c) not in movidas]
        origen.camas = nuevas_camas
        if nuevas_camas:
            origen.altura_final = calcular_altura_pallet(origen)
            origen.peso_estimado = _peso_desde_camas(nuevas_camas, info_sku)  # [P4]
            origen.estado = config.estado_pallet_por_altura(origen.altura_final)
            tocados.add(id(origen))
        else:
            eliminados.add(id(origen))

    resultado = [p for p in pallets_cd if id(p) not in eliminados]
    for pallet in resultado:
        if id(pallet) in tocados:
            pallet.lineas = _construir_lineas(pallet.camas, info_sku)
    return resultado


def armar_pallets(
    camas_por_cd: dict[str, list[Cama]],
    info_sku: dict[str, dict],
    pallets_semilla: list[Pallet] | None = None,
) -> list[Pallet]:
    """[V4b / fotos de los 42 pallets reales] Ya no hay pases separados por
    nivel de categoría ni remate exclusivo -un solo pase de bin-packing sobre
    TODAS las camas del CD (ver `_asignar_camas`), confirmado con Omar:
    buscar la mejor forma geométrica en que entren las cajas necesarias para
    el CD, minimizando cuántos pallets hace falta mover."""
    todos_pallets: list[Pallet] = []

    semillas_por_cd: dict[str, list[Pallet]] = {}
    for pallet in pallets_semilla or []:
        semillas_por_cd.setdefault(pallet.cd, []).append(pallet)

    # [PARCHE P3] `sorted(...)`: iterar un set de strings hace que el orden dependa
    # del hash de cada string, que con PYTHONHASHSEED aleatorio (default de Python 3)
    # CAMBIA entre procesos. El plan por CD era el mismo, pero el orden de las filas
    # del Excel de salida variaba entre corridas -> imposible diffear la corrida de
    # hoy contra la de ayer. Para una herramienta que corre a diario eso es ruido puro.
    for cd in sorted(set(camas_por_cd) | set(semillas_por_cd)):
        contador = [0]
        pallets_abiertos: list[Pallet] = list(semillas_por_cd.get(cd, []))
        camas_iniciales = {id(p): len(p.camas) for p in pallets_abiertos}

        _asignar_camas(camas_por_cd.get(cd, []), cd, contador, pallets_abiertos, info_sku)

        for pallet in pallets_abiertos:
            if pallet.tipo.startswith("Homogéneo") and len(pallet.camas) > camas_iniciales[id(pallet)]:
                pallet.tipo = "Homogéneo + Remate"
            pallet.lineas = _construir_lineas(pallet.camas, info_sku)
            pallet.estado = config.estado_pallet_por_altura(pallet.altura_final)

        todos_pallets.extend(_consolidar_pallets(pallets_abiertos, info_sku))

    return todos_pallets
