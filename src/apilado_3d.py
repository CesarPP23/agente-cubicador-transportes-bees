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


def _agrupar_camas(lista_camas: list[Cama]) -> tuple[dict[int, list[Cama]], dict[str, list[Cama]]]:
    camas_por_nivel: dict[int, list[Cama]] = {n: [] for n in range(1, 7)}
    camas_remate: dict[str, list[Cama]] = {cat: [] for cat in config.CATEGORIAS_REMATE}
    for cama in lista_camas:
        if cama.nivel_categoria is not None:
            camas_por_nivel[cama.nivel_categoria].append(cama)
        else:
            categoria = cama.categorias[0]
            camas_remate.setdefault(categoria, []).append(cama)
    return camas_por_nivel, camas_remate


def _altura_desde_camas(camas: list[Cama]) -> float:
    return config.ALTURA_PALLET_VACIO + sum(c.altura_cama for c in camas)


def _es_flexible(cama: Cama) -> bool:
    categoria = cama.categorias[0]
    return categoria == "NABs" or categoria in config.CATEGORIAS_REMATE


def _remate_de(pallet: Pallet) -> str | None:
    for cama in pallet.camas:
        if cama.categorias[0] in config.CATEGORIAS_REMATE:
            return cama.categorias[0]
    return None


def _remate_compatible(pallet: Pallet, categoria: str) -> bool:
    if categoria in config.CATEGORIAS_REMATE:
        actual = _remate_de(pallet)
        return actual is None or actual == categoria
    return _remate_de(pallet) is None  # NABs: solo si el pallet aún no tiene remate


def _crear_pallet(cd: str, contador: list[int]) -> Pallet:
    contador[0] += 1
    return Pallet(id=f"PH-MIX-{cd}-{contador[0]:03d}", cd=cd, tipo="Mixto", altura_final=config.ALTURA_PALLET_VACIO)


def _asignar_camas(
    camas: list[Cama],
    es_elegible,
    cd: str,
    contador: list[int],
    pallets_abiertos: list[Pallet],
) -> None:
    """Bin-packing best-fit: para cada cama (de mayor a menor altura), busca entre
    TODOS los pallets ya abiertos del CD el que tenga menos espacio libre y aun así
    la reciba; solo abre un pallet nuevo si ninguno de los existentes sirve. Así se
    exploran todas las combinaciones posibles antes de decidir abrir un pallet más,
    en vez de cerrar pallets uno por uno en secuencia."""
    for cama in sorted(camas, key=lambda c: -c.altura_cama):
        candidatos = [
            p
            for p in pallets_abiertos
            if es_elegible(p) and cama.altura_cama <= config.ALTURA_TOTAL_MAX - p.altura_final + 1e-9
        ]
        destino = max(candidatos, key=lambda p: p.altura_final) if candidatos else None
        if destino is None:
            destino = _crear_pallet(cd, contador)
            pallets_abiertos.append(destino)
        destino.camas.append(cama)
        destino.altura_final += cama.altura_cama


def _asignar_remate(
    camas_remate: dict[str, list[Cama]],
    cd: str,
    contador: list[int],
    pallets_abiertos: list[Pallet],
) -> None:
    todas = [(cama, categoria) for categoria, colas in camas_remate.items() for cama in colas]
    todas.sort(key=lambda t: -t[0].altura_cama)
    for cama, categoria in todas:
        candidatos = [
            p
            for p in pallets_abiertos
            if _remate_compatible(p, categoria) and cama.altura_cama <= config.ALTURA_TOTAL_MAX - p.altura_final + 1e-9
        ]
        destino = max(candidatos, key=lambda p: p.altura_final) if candidatos else None
        if destino is None:
            destino = _crear_pallet(cd, contador)
            pallets_abiertos.append(destino)
        destino.camas.append(cama)
        destino.altura_final += cama.altura_cama


def _consolidar_pallets(pallets_cd: list[Pallet], info_sku: dict[str, dict]) -> list[Pallet]:
    """Red de seguridad final: vacía, cuando es posible, los pallets que quedaron por
    debajo del mínimo, encimando sus camas de NABs/remate en otros pallets del mismo
    CD que aún tengan espacio, en vez de dejarlos como pallets casi vacíos."""
    pequenos = sorted(
        (p for p in pallets_cd if p.altura_final < config.ALTURA_TOTAL_MIN),
        key=lambda p: p.altura_final,
    )
    eliminados: set[int] = set()
    tocados: set[int] = set()

    for origen in pequenos:
        if origen.altura_final >= config.ALTURA_TOTAL_MIN:
            continue  # ya se completó recibiendo camas de otro pallet chico

        fijas = [c for c in origen.camas if not _es_flexible(c)]
        flexibles = sorted((c for c in origen.camas if _es_flexible(c)), key=lambda c: -c.altura_cama)
        sobrantes: list[Cama] = []

        for cama in flexibles:
            categoria = cama.categorias[0]
            candidatos = [
                candidato
                for candidato in pallets_cd
                if candidato is not origen
                and id(candidato) not in eliminados
                and candidato.altura_final >= origen.altura_final  # nunca mover hacia un pallet peor
                and cama.altura_cama <= config.ALTURA_TOTAL_MAX - candidato.altura_final + 1e-9
                and _remate_compatible(candidato, categoria)
            ]
            destino = max(candidatos, key=lambda c: c.altura_final) if candidatos else None
            if destino is None:
                sobrantes.append(cama)
                continue
            destino.camas.append(cama)
            destino.altura_final = _altura_desde_camas(destino.camas)
            tocados.add(id(destino))

        nuevas_camas = fijas + sobrantes
        origen.camas = nuevas_camas
        if nuevas_camas:
            origen.altura_final = _altura_desde_camas(nuevas_camas)
            origen.estado = (
                config.ESTADO_PALLET_PARCIAL if origen.altura_final < config.ALTURA_TOTAL_MIN else config.ESTADO_OK
            )
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
        camas_por_nivel, camas_remate = _agrupar_camas(camas_por_cd.get(cd, []))
        contador = [0]
        pallets_abiertos: list[Pallet] = list(semillas_por_cd.get(cd, []))
        camas_iniciales = {id(p): len(p.camas) for p in pallets_abiertos}

        for nivel in range(1, 6):  # niveles base 1-5: nunca sobre un pallet homogéneo
            _asignar_camas(
                camas_por_nivel[nivel],
                lambda p: not p.tipo.startswith("Homogéneo"),
                cd, contador, pallets_abiertos,
            )

        _asignar_camas(  # NABs (nivel 6): cualquier pallet -incluidos homogéneos- sin remate aún
            camas_por_nivel[6],
            lambda p: _remate_de(p) is None,
            cd, contador, pallets_abiertos,
        )

        _asignar_remate(camas_remate, cd, contador, pallets_abiertos)

        for pallet in pallets_abiertos:
            if pallet.tipo.startswith("Homogéneo") and len(pallet.camas) > camas_iniciales[id(pallet)]:
                pallet.tipo = "Homogéneo + Remate"
            pallet.lineas = _construir_lineas(pallet.camas, info_sku)
            pallet.estado = (
                config.ESTADO_PALLET_PARCIAL if pallet.altura_final < config.ALTURA_TOTAL_MIN else config.ESTADO_OK
            )

        todos_pallets.extend(_consolidar_pallets(pallets_abiertos, info_sku))

    return todos_pallets
