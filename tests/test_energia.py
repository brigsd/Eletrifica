import numpy as np
import pytest

from modulos.energia import arvore, contatos, protecao, vrm
from modulos.termico import difusao


@pytest.fixture(scope="module")
def montado():
    from modulos.sistema import base as B, configuracao as C, mapeamento as M

    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct)
    return m, C.configurar(m.base, M.identificar(m.base, s), s)


def test_corrente_se_conserva_nos_contatos(montado):
    m, cfg = montado
    r = contatos.distribuir(m.base, cfg, corrente_a=200.0, zona_vrm=m.zonas["vrm_cpu"])
    assert r["soma_pinos_a"] == pytest.approx(200.0, rel=1e-6)
    assert r["corrente_celula"].sum() == pytest.approx(200.0, rel=1e-6)
    assert r["mapa_corrente"].sum() == pytest.approx(200.0, rel=1e-6)
    assert r["perdas_w"] == pytest.approx(r["queda_ir_mv"] * 1e-3 * 200.0, rel=1e-3)


def test_vrm_estavel_e_assenta():
    r = vrm.simular_degrau()
    assert r["assentamento_us"] < 50.0
    assert abs(r["v"][-2000:] - r["v_final"]).max() < 1e-3
    sem_desvio = vrm.simular_degrau(desvio_dcr=0.0)
    assert abs(sem_desvio["erro_reta_carga_mv"]) < 0.5
    assert 0.85 < r["eficiencia"] < 0.97


def test_vrm_segue_svid():
    r = vrm.simular_degrau(i1=30.0, svid=[(20.0, 1.10)], t_total_us=120.0, desvio_dcr=0.0)
    assert r["v_final"] == pytest.approx(1.10 - 1.1e-3 * 30.0, abs=1e-3)


def test_curto_desarma_em_menos_de_1us():
    r = protecao.simular_curto()
    assert r["tempo_disparo_ns"] < 1000.0
    assert r["i"][-1] < 0.01


def test_nao_energiza_sem_identificacao(montado):
    _, cfg = montado
    ok, _ = protecao.pode_energizar(0, {"configuracao": None})
    assert not ok
    iy, ix = np.argwhere(cfg.funcao == 2)[0]
    celula = iy * cfg.funcao.shape[1] + ix
    assert protecao.pode_energizar(celula, {"configuracao": cfg})[0]
    iy, ix = np.argwhere(cfg.funcao == 3)[0]
    assert not protecao.pode_energizar(iy * cfg.funcao.shape[1] + ix, {"configuracao": cfg})[0]


def test_arvore_fecha(montado):
    _, cfg = montado
    r = arvore.balanco(cfg)
    assert r["carga_fonte_12v_w"] == pytest.approx(
        r["potencia_cargas_w"] + r["perdas_conversores_w"] + r["perdas_contatos_w"])
    assert r["pela_base_w"] + r["pelo_cabo_w"] == pytest.approx(r["carga_fonte_12v_w"])


def test_termico_balanco_de_energia(montado):
    m, cfg = montado
    r = difusao.simular(m.base, cfg, m.zonas)
    assert r.perda_conveccao_w == pytest.approx(r.fontes_w.sum(), rel=1e-6)
    assert r.regime.min() > r.t_amb
    x, y = r.tradutores["CPU"]["x"], r.tradutores["CPU"]["y"]
    assert r.temperatura_em(x, y, 0.0) == pytest.approx(r.t_amb)
    assert r.temperatura_em(x, y, 1.0) < r.temperatura_em(x, y, 100.0) <= r.temperatura_em(x, y) + 1e-6
