"""[PATCH V6.12-D6.1] Tests de `_canonicalizar_ids_pallets_v5`
(src/pipeline_sku_bloque.py) -fix de V6.12-D6 (ID_ASSIGNMENT_NONDETERMINISM):
`ID_Pallet`/`N_Parihuela` ya NO deben depender de cuántos intentos internos
(probes de `politica_a_descenso`, Rescue, Repair, Exact, Global) precedieron
a la materialización final de un CD, solo del contenido/geometría final.
Ver V6.12-D6 para el diagnóstico completo (reproducido empíricamente: mismo
contenido, `ID_Pallet` corrido)."""
from models import PalletV5, Torre
from src.estabilidad import EstabilidadPallet
from src.pipeline_sku_bloque import _canonicalizar_ids_pallets_v5


def _torre(sku, x, y, z, cantidad=10, largo=30, ancho=20, alto_caja=15.0, orientacion="L×A"):
    return Torre(
        sku=sku, cd="BK31", x=x, y=y, largo=largo, ancho=ancho, alto_caja=alto_caja,
        cantidad=cantidad, peso=1.0, orientacion=orientacion, fuente_geometria="TEST", z=z,
    )


def _pallet(id_, cd, torres, con_estabilidad=False):
    p = PalletV5(id=id_, cd=cd, torres=list(torres))
    if con_estabilidad:
        p.metadata["estabilidad"] = EstabilidadPallet(
            pallet_id=id_, centro_masa_x=0.0, centro_masa_y=0.0, desviacion_centro_masa=0.0,
        )
    return p


def _ids_por_firma(pallets_v5):
    """Mapa {firma_de_contenido: id_final} -para comparar dos corridas sin
    depender de qué objeto físico terminó en cuál posición."""
    from src.pipeline_sku_bloque import _firma_pallet_canonica
    return {_firma_pallet_canonica(p): p.id for p in pallets_v5}


def test_1_distintos_ids_temporales_mismo_contenido_da_mismo_resultado():
    """Dos listas con el MISMO contenido por pallet, pero IDs de partida
    distintos (simulando que una corrida consumió más/menos contador en
    sondeos descartados) -deben terminar con el mismo id final por firma."""
    torres_a = [_torre("A", 0, 0, 0), _torre("B", 30, 0, 0)]
    torres_b = [_torre("C", 0, 0, 0)]

    corrida_1 = [_pallet("PV5-BK31-021", "BK31", torres_a), _pallet("PV5-BK31-022", "BK31", torres_b)]
    corrida_2 = [_pallet("PV5-BK31-018", "BK31", torres_a), _pallet("PV5-BK31-019", "BK31", torres_b)]

    _canonicalizar_ids_pallets_v5(corrida_1)
    _canonicalizar_ids_pallets_v5(corrida_2)

    assert _ids_por_firma(corrida_1) == _ids_por_firma(corrida_2)


def test_2_distinto_insertion_order_da_mismo_resultado():
    """Mismo contenido, orden de inserción invertido -mismo resultado."""
    torres_a = [_torre("A", 0, 0, 0)]
    torres_b = [_torre("B", 30, 0, 0)]
    torres_c = [_torre("C", 60, 0, 0)]

    orden_1 = [_pallet("PV5-BK31-001", "BK31", torres_a),
               _pallet("PV5-BK31-002", "BK31", torres_b),
               _pallet("PV5-BK31-003", "BK31", torres_c)]
    orden_2 = [_pallet("PV5-BK31-001", "BK31", torres_c),
               _pallet("PV5-BK31-002", "BK31", torres_a),
               _pallet("PV5-BK31-003", "BK31", torres_b)]

    _canonicalizar_ids_pallets_v5(orden_1)
    _canonicalizar_ids_pallets_v5(orden_2)

    assert _ids_por_firma(orden_1) == _ids_por_firma(orden_2)
    assert sorted(p.id for p in orden_1) == sorted(p.id for p in orden_2)


def test_3_pallets_duplicados_identicos_da_output_identico():
    """Dos pallets con firma canónica IDÉNTICA (contenido físicamente
    intercambiable) -el resultado exportable (conjunto de (cd, firma, id))
    debe ser el mismo sin importar cuál copia física recibe cuál número."""
    torres_x = [_torre("X", 0, 0, 0, cantidad=5)]

    corrida_1 = [_pallet("PV5-BK31-005", "BK31", torres_x), _pallet("PV5-BK31-006", "BK31", list(torres_x))]
    corrida_2 = [_pallet("PV5-BK31-006", "BK31", list(torres_x)), _pallet("PV5-BK31-005", "BK31", torres_x)]

    _canonicalizar_ids_pallets_v5(corrida_1)
    _canonicalizar_ids_pallets_v5(corrida_2)

    firmas_y_ids_1 = sorted((_firma, id_) for _firma, id_ in
                             [(tuple(sorted((t.sku, t.cantidad) for t in p.torres)), p.id) for p in corrida_1])
    firmas_y_ids_2 = sorted((_firma, id_) for _firma, id_ in
                             [(tuple(sorted((t.sku, t.cantidad) for t in p.torres)), p.id) for p in corrida_2])
    assert firmas_y_ids_1 == firmas_y_ids_2
    assert {p.id for p in corrida_1} == {"PV5-BK31-001", "PV5-BK31-002"}


def test_4_representacion_numerica_equivalente_da_mismo_resultado():
    """Mismo contenido, coordenadas con ruido de punto flotante que
    redondea igual a 2 decimales (`_firma_pallet_canonica` ya usa la
    precisión contractual de `global_rescue._signature_torres`) -debe
    tratarse como el mismo pallet a efectos de la asignación de ID."""
    torres_exactas = [_torre("A", 10.00, 20.00, 0.00)]
    torres_con_ruido = [_torre("A", 10.0 + 1e-9, 20.0 - 1e-9, 0.0 + 4e-9)]

    corrida_1 = [_pallet("PV5-BK31-050", "BK31", torres_exactas), _pallet("PV5-BK31-051", "BK31", [_torre("B", 0, 0, 0)])]
    corrida_2 = [_pallet("PV5-BK31-030", "BK31", torres_con_ruido), _pallet("PV5-BK31-031", "BK31", [_torre("B", 0, 0, 0)])]

    _canonicalizar_ids_pallets_v5(corrida_1)
    _canonicalizar_ids_pallets_v5(corrida_2)

    ids_a = sorted(p.id for p in corrida_1 if any(t.sku == "A" for t in p.torres))
    ids_b = sorted(p.id for p in corrida_2 if any(t.sku == "A" for t in p.torres))
    assert ids_a == ids_b


def test_5_ids_finales_quedan_consecutivos_001_a_n():
    torres = [[_torre(f"SKU{i}", i * 10, 0, 0)] for i in range(4)]
    pallets = [_pallet(f"PV5-BK31-{900+i:03d}", "BK31", t) for i, t in enumerate(torres)]

    _canonicalizar_ids_pallets_v5(pallets)

    ids_finales = sorted(p.id for p in pallets)
    assert ids_finales == [f"PV5-BK31-{i:03d}" for i in range(1, 5)]


def test_6_excluye_pallets_bat_dedicados_del_renombrado():
    """Prefijo dedicado `PV5-BAT-{cd}-NNN` (`bat.renombrar_pallets_bat_puros`,
    reconocido por `benchmark.calcular_kpis` vía `startswith`) -nunca se
    toca ni se reordena junto con los pallets normales."""
    normal = _pallet("PV5-BK31-099", "BK31", [_torre("A", 0, 0, 0)])
    bat_dedicado = _pallet("PV5-BAT-BK31-001", "BK31", [_torre("BAT_MARCADOR", 50, 0, 0)])

    pallets = [bat_dedicado, normal]
    _canonicalizar_ids_pallets_v5(pallets)

    assert bat_dedicado.id == "PV5-BAT-BK31-001"
    assert normal.id == "PV5-BK31-001"


def test_7_no_mezcla_pallets_de_distintos_cd():
    p_bk31 = _pallet("PV5-BK31-050", "BK31", [_torre("A", 0, 0, 0)])
    p_sj87 = _pallet("PV5-SJ87-050", "SJ87", [_torre("A", 0, 0, 0)])

    pallets = [p_bk31, p_sj87]
    _canonicalizar_ids_pallets_v5(pallets)

    assert p_bk31.id == "PV5-BK31-001"
    assert p_sj87.id == "PV5-SJ87-001"


def test_8_resella_pallet_id_embebido_en_metadata_estabilidad():
    p = _pallet("PV5-BK31-077", "BK31", [_torre("A", 0, 0, 0)], con_estabilidad=True)
    assert p.metadata["estabilidad"].pallet_id == "PV5-BK31-077"

    _canonicalizar_ids_pallets_v5([p])

    assert p.id == "PV5-BK31-001"
    assert p.metadata["estabilidad"].pallet_id == "PV5-BK31-001"


def test_9_idempotente_correrlo_dos_veces_no_cambia_nada():
    pallets = [_pallet("PV5-BK31-003", "BK31", [_torre("B", 30, 0, 0)]),
               _pallet("PV5-BK31-001", "BK31", [_torre("A", 0, 0, 0)])]
    _canonicalizar_ids_pallets_v5(pallets)
    ids_primera = sorted(p.id for p in pallets)

    _canonicalizar_ids_pallets_v5(pallets)
    ids_segunda = sorted(p.id for p in pallets)

    assert ids_primera == ids_segunda == ["PV5-BK31-001", "PV5-BK31-002"]
