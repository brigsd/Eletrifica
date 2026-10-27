import math

import numpy as np
import pytest

from modulos.optica import controle_termico as T
from modulos.optica import enlace as E
from modulos.optica.anel import Anel
from modulos.optica.detector import Receptor, ber_niveis, sensibilidade_dbm


def boa():
    c = E.carregar("ajustada")
    c["canais_por_fibra"] = 8
    c["lambdas_por_laser"] = 8
    return c


def test_calculo_simples_bate_com_o_documento():
    o = E.calculo_simples(E.carregar("original"))
    a = E.calculo_simples(E.carregar("ajustada"))
    assert o["margem_db"] == pytest.approx(-6.1, abs=0.05)
    assert a["margem_db"] == pytest.approx(2.5, abs=0.05)
    assert a["banda_TBps"] == pytest.approx(1.54, abs=0.01)
    assert a["fibras"] == 6
    assert a["atraso_ns"] == pytest.approx(0.34, abs=0.01)


def test_anel_de_10_um():
    a = Anel()
    assert a.fsr_nm == pytest.approx(13.0, abs=0.1)
    assert a.largura_nm == pytest.approx(1310 / 6000)
    assert 10 * math.log10(a.transmissao(1310.0, 1310.0)) < -5


def test_ber_niveis_e_sensibilidade():
    assert ber_niveis([0.0, 1.0], [1 / 14, 1 / 14]) == pytest.approx(1.28e-12, rel=0.05)
    rx = Receptor()
    assert -18 < sensibilidade_dbm(rx, 32e9, 10.0) < -12


def test_menos_canais_por_fibra_e_melhor():
    c16, c64 = E.carregar("ajustada"), E.carregar("ajustada")
    c16["canais_por_fibra"] = 16
    o16, o64 = E.orcamento(c16), E.orcamento(c64)
    assert o64["margem_db"] == -math.inf
    assert o16["margem_db"] > -10
    assert o16["diafonia_rx_db"] < o64["diafonia_rx_db"] - 10


def test_simulacao_nrz_limpa():
    r = E.simular_canal(boa(), n_simbolos=4096, simbolo="NRZ")
    assert r.erros_contados == 0
    assert r.ber_estimada < 1e-9
    assert 0 < r.atraso_ps < 100
    assert r.largura_olho_ui > 0.3


def test_controle_termico_segura_e_sem_controle_perde():
    c = boa()
    subida = lambda t: 10.0 * (1 - math.exp(-(t - 400) / 200)) if t >= 400 else 0.0
    com = T.simular(c, subida, 1500, controle=True, simbolo="NRZ")
    depois = com["tempo_us"] > com["travou_em_us"] + 50
    assert com["perdas_de_travamento"] == 0
    assert np.abs(com["erro_pm"][depois]).max() < 20
    sem = T.simular(c, subida, 1500, controle=False, simbolo="NRZ")
    assert sem["log10_ber"][-1] > -3


def test_degrau_abrupto_retrava():
    degrau = lambda t: 10.0 if t >= 400 else 0.0
    r = T.simular(boa(), degrau, 1500, controle=True, simbolo="NRZ")
    assert r["perdas_de_travamento"] >= 1
    assert abs(r["erro_pm"][-1]) < 20
