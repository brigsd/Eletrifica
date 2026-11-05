"""Malha de segmentos: topologia, rota XY, custo por salto e reserva de tráfego."""
import pytest

from modulos.malha import custo
from modulos.malha.parametros import FALLBACK as FIXOS   # valores fixos: o teste não depende do malha.json
from modulos.malha.rota import rota_xy
from modulos.malha.topologia import Malha, ligacao
from modulos.malha.trafego import Fluxo, reservar


@pytest.fixture
def malha3():
    # 3x3, 1 faixa de 16 Gb/s: capacidade de cada ligação = 2 GB/s
    return Malha(colunas=3, linhas=3, passo_mm=10.0, faixas_por_ligacao=1, gbps_por_faixa=16.0, params=FIXOS)


def test_rota_xy_anda_primeiro_x_depois_y(malha3):
    ligs, saltos = rota_xy(malha3, (0, 0), (2, 2))
    assert saltos == 4
    assert ligs == [
        ligacao((0, 0), (1, 0)),
        ligacao((1, 0), (2, 0)),
        ligacao((2, 0), (2, 1)),
        ligacao((2, 1), (2, 2)),
    ]


def test_rota_xy_mesmo_segmento_e_zero_saltos(malha3):
    assert rota_xy(malha3, (1, 1), (1, 1)) == ([], 0)


def test_rota_xy_sentido_negativo(malha3):
    ligs, saltos = rota_xy(malha3, (2, 2), (0, 1))
    assert saltos == 3
    assert ligs[0] == ligacao((2, 2), (1, 2))


def test_rota_fora_da_malha_falha(malha3):
    with pytest.raises(ValueError):
        rota_xy(malha3, (0, 0), (3, 0))


def test_topologia_ligacoes_de_grade(malha3):
    # grade 3x3 tem 12 ligações entre vizinhos de 4 lados
    assert len(malha3.ligacoes()) == 12
    assert malha3.vizinhos((0, 0)) == [(1, 0), (0, 1)]
    assert malha3.vizinhos((1, 1)) == [(2, 1), (0, 1), (1, 2), (1, 0)]


def test_capacidade_da_ligacao(malha3):
    # 1 faixa × 16 Gb/s / 8 = 2 GB/s
    assert malha3.capacidade_gbs(ligacao((0, 0), (1, 0))) == pytest.approx(2.0)
    m4 = Malha(colunas=2, linhas=1, passo_mm=5.0, faixas_por_ligacao=4, gbps_por_faixa=25.0)
    assert m4.capacidade_gbs(ligacao((0, 0), (1, 0))) == pytest.approx(12.5)


def test_capacidade_de_ligacao_inexistente_falha(malha3):
    with pytest.raises(ValueError):
        malha3.capacidade_gbs(ligacao((0, 0), (2, 2)))


def test_atraso_dentro_e_fora_do_orcamento():
    # passo 10 mm: 1,5 + 10 × 7 ps/mm = 1,57 ns por salto; 3 saltos = 4,71 ns
    atraso = custo.atraso_caminho_ns(3, 10.0, FIXOS)
    assert atraso == pytest.approx(4.71)
    cabe, folga = custo.conferir_orcamento(atraso, 5.0)
    assert cabe and folga == pytest.approx(0.29)
    cabe, folga = custo.conferir_orcamento(atraso, 4.0)
    assert not cabe and folga == pytest.approx(-0.71)


def test_energia_por_bit_cresce_com_saltos():
    assert custo.energia_pj_por_bit(0, FIXOS) == 0.0
    assert custo.energia_pj_por_bit(3, FIXOS) == pytest.approx(6.0)


def test_fluxos_pequenos_cabem(malha3):
    fluxos = [
        Fluxo("a", (0, 0), (2, 0), 0.5),
        Fluxo("b", (0, 2), (2, 2), 0.5),
    ]
    r = reservar(malha3, fluxos)
    assert r.cabe and r.acima_de_100 == []
    assert r.ocupacao[ligacao((0, 0), (1, 0))] == pytest.approx(0.25)
    assert [f.nome for f in r.fluxos] == ["a", "b"]


def test_ligacao_central_sobrecarregada_falha(malha3):
    # Dois fluxos de 1,2 GB/s saem de (0,1), andam em X pelo centro (1,1)-(2,1)
    # e somam 2,4 GB/s numa ligação de 2 GB/s.
    fluxos = [
        Fluxo("p", (0, 1), (2, 1), 1.2),
        Fluxo("q", (0, 1), (2, 2), 1.2),
    ]
    r = reservar(malha3, fluxos)
    assert not r.cabe
    acima = dict(r.acima_de_100)
    central = ligacao((1, 1), (2, 1))
    assert central in acima
    assert acima[central] == pytest.approx(1.2)
    assert r.ocupacao[ligacao((0, 1), (1, 1))] == pytest.approx(1.2)


def test_atraso_por_fluxo_e_reservado(malha3):
    r = reservar(malha3, [Fluxo("x", (0, 0), (2, 2), 0.1)])
    f = r.fluxos[0]
    assert f.saltos == 4
    assert f.atraso_ns == pytest.approx(4 * (1.5 + 10 * 7.0 / 1000))


def test_potencia_bate_com_conta_a_mao(malha3):
    # 2 GB/s = 16 Gb/s; 3 saltos × 2 pJ/bit = 6 pJ/bit
    # 2 × 8e9 bit/s × 6e-12 J/bit = 0,096 W
    r = reservar(malha3, [Fluxo("y", (0, 0), (2, 1), 2.0)])
    assert r.fluxos[0].saltos == 3
    assert r.fluxos[0].energia_pj_bit == pytest.approx(6.0)
    assert r.potencia_w == pytest.approx(0.096)
    r2 = reservar(malha3, [Fluxo("a", (0, 0), (2, 1), 2.0), Fluxo("b", (0, 0), (1, 0), 1.0)])
    # b: 1 salto, 2 pJ/bit, 1 GB/s -> 8e9 × 2e-12 = 0,016 W
    assert r2.potencia_w == pytest.approx(0.096 + 0.016)


def test_banda_negativa_falha(malha3):
    with pytest.raises(ValueError):
        reservar(malha3, [Fluxo("z", (0, 0), (1, 0), -1.0)])
