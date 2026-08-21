"""[V-AUTO] Corre V4 y V5 sobre la misma entrada y se queda con el mejor
resultado CD por CD -nunca puede dar peor que el mejor de los dos, porque
literalmente elige entre ellos."""
import pandas as pd
import pytest

import config
from models import Pallet, PalletV5, ResultadoPipeline
from src import benchmark, pipeline_auto
from src.pipeline_auto import _score_cd


def _pallet(id_, cd, altura=200.0, tipo="Mixto"):
    return Pallet(id=id_, cd=cd, tipo=tipo, altura_final=altura, peso_estimado=500.0)


def test_score_cd_prefiere_menos_pallets():
    pocos = [_pallet("A", "BK31"), _pallet("B", "BK31")]
    muchos = [_pallet("A", "BK31"), _pallet("B", "BK31"), _pallet("C", "BK31")]
    assert _score_cd(pocos) < _score_cd(muchos)


def test_score_cd_empate_en_pallets_prefiere_mas_cerca_del_target():
    cerca = [_pallet("A", "BK31", altura=config.ALTURA_TARGET)]
    lejos = [_pallet("A", "BK31", altura=config.ALTURA_TARGET - 40)]
    assert _score_cd(cerca) < _score_cd(lejos)


def test_score_cd_penaliza_bat_dedicado():
    """Mismo n_pallets (2) -el que tiene un dedicado BAT debe perder frente
    al que no, aunque el conteo bruto sea igual."""
    sin_dedicado = [_pallet("A", "BK31"), _pallet("B", "BK31")]
    con_dedicado = [_pallet("A", "BK31"), _pallet("PH-BAT-BK31-001", "BK31", altura=70.0)]
    assert _score_cd(sin_dedicado) < _score_cd(con_dedicado)


def test_score_cd_pallet_vacio_da_score_neutro():
    assert _score_cd([]) == (0, 0, 0, 0.0)


def _resultado_fake(pallets: list[Pallet], pallets_v5=None) -> ResultadoPipeline:
    bench = benchmark.calcular_kpis(pallets, demanda_unidades_error=0.0, geometria_inferida_count=0)
    return ResultadoPipeline(
        plan_picking_df=pd.DataFrame(),
        log_validacion_df=pd.DataFrame(),
        resumen_cd_df=pd.DataFrame(),
        pallets=pallets,
        info_sku={},
        auditoria_geometrica_df=pd.DataFrame(),
        benchmark_df=benchmark.benchmark_df([bench]),
        pallets_v5=pallets_v5,
    )


def test_elige_v5_en_el_cd_donde_v5_da_menos_pallets(monkeypatch):
    """BK31: V4 da 3 pallets, V5 da 2 -> gana V5. BK41: V4 da 1, V5 da 2 ->
    gana V4. El resultado final tiene que tener 2 (BK31, V5) + 1 (BK41, V4)
    = 3 pallets, ninguno de más."""
    v4 = _resultado_fake(
        [_pallet("PH-A", "BK31"), _pallet("PH-B", "BK31"), _pallet("PH-C", "BK31"), _pallet("PH-D", "BK41")]
    )
    v5 = _resultado_fake(
        [_pallet("PV5-A", "BK31"), _pallet("PV5-B", "BK31"), _pallet("PV5-C", "BK41"), _pallet("PV5-D", "BK41")],
        pallets_v5=[PalletV5(id="PV5-A", cd="BK31"), PalletV5(id="PV5-B", cd="BK31")],
    )

    monkeypatch.setattr(pipeline_auto, "ejecutar_core_v4", lambda *a, **k: v4)
    import src.pipeline_v5 as pipeline_v5_mod

    monkeypatch.setattr(pipeline_v5_mod, "ejecutar_core_v5", lambda *a, **k: v5)

    resultado = pipeline_auto.ejecutar_core_auto(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    ids = sorted(p.id for p in resultado.pallets)
    assert ids == ["PH-D", "PV5-A", "PV5-B"]
    assert len(resultado.pallets_v5) == 2  # solo las de BK31, que fue donde ganó V5


def test_empate_en_pallets_se_queda_con_v4(monkeypatch):
    """Mismo n_pallets, mismo score -> gana V4 (motor probado), no cambia
    de motor sin una razón medible."""
    v4 = _resultado_fake([_pallet("PH-A", "BK31", altura=config.ALTURA_TARGET)])
    v5 = _resultado_fake(
        [_pallet("PV5-A", "BK31", altura=config.ALTURA_TARGET)],
        pallets_v5=[PalletV5(id="PV5-A", cd="BK31")],
    )
    monkeypatch.setattr(pipeline_auto, "ejecutar_core_v4", lambda *a, **k: v4)
    import src.pipeline_v5 as pipeline_v5_mod

    monkeypatch.setattr(pipeline_v5_mod, "ejecutar_core_v5", lambda *a, **k: v5)

    resultado = pipeline_auto.ejecutar_core_auto(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert [p.id for p in resultado.pallets] == ["PH-A"]
    assert resultado.pallets_v5 == []


def test_pallets_requiere_revision_se_toman_de_v4_sin_duplicar(monkeypatch):
    revision = _pallet("SIN-ASIGNAR-BK31", "BK31", tipo="Requiere Revisión")
    v4 = _resultado_fake([_pallet("PH-A", "BK31"), revision])
    v5 = _resultado_fake([_pallet("PV5-A", "BK31")])  # V5 nunca genera Requiere Revisión propio

    monkeypatch.setattr(pipeline_auto, "ejecutar_core_v4", lambda *a, **k: v4)
    import src.pipeline_v5 as pipeline_v5_mod

    monkeypatch.setattr(pipeline_v5_mod, "ejecutar_core_v5", lambda *a, **k: v5)

    resultado = pipeline_auto.ejecutar_core_auto(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    ids = sorted(p.id for p in resultado.pallets)
    assert "SIN-ASIGNAR-BK31" in ids
    assert ids.count("SIN-ASIGNAR-BK31") == 1


@pytest.fixture(autouse=True)
def _restaurar_packer_version():
    original = config.PACKER_VERSION
    yield
    config.PACKER_VERSION = original


def test_integracion_auto_corre_de_punta_a_punta(dataset_factory):
    """Sin monkeypatch -corre los dos motores reales sobre un dataset
    sintético chico, tiene que devolver un resultado válido sin reventar."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 3, "cd": "BK41"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}, {"sku": 2, "categoria": "Aseo"}],
        uma_overrides=[{"sku": 1}, {"sku": 2}],
    )
    config.PACKER_VERSION = "AUTO"
    from src.pipeline import ejecutar_pipeline

    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert resultado.pallets
    cds = {p.cd for p in resultado.pallets}
    assert cds == {"BK31", "BK41"}
