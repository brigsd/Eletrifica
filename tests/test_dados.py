import copy
import os

import pytest

from modulos.componentes import obter
from modulos.dados import emulador as E
from modulos.dados.latencia import calcular
from modulos.dados.protocolos import PROTOCOLOS
from modulos.dados.roteamento import rotear


@pytest.fixture(scope="module")
def cfg():
    from modulos.sistema import base as B, configuracao as C, mapeamento as M

    m = B.carregar()
    contatos = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, contatos)
    return C.configurar(m.base, M.identificar(m.base, s), s)


@pytest.fixture(scope="module")
def plano(cfg):
    return rotear(cfg)


def test_protocolos_basicos():
    assert PROTOCOLOS["GDDR7-32"].codificacao == "PAM3"
    assert PROTOCOLOS["GDDR7-32"].gbaud == pytest.approx(32 / 1.5)
    assert PROTOCOLOS["DDR5-4800"].bidirecional and not PROTOCOLOS["PCIe5"].bidirecional


def test_todas_as_interfaces_roteadas(plano):
    ids = {e.id for e in plano.enlaces}
    assert {"CPU-DIMM0", "CPU-DIMM1", "CPU-GPU", "CPU-PCH", "CPU-FPGA"} <= ids
    assert {f"GPU-MEM{i}" for i in range(12)} <= ids
    assert all(c.fibra >= 0 for c in plano.canais)
    # cada canal DDR5 da CPU foi para um DIMM diferente, cada canal GDDR7 para um chip diferente
    origens = {plano.canais[plano.enlace(f"CPU-DIMM{i}").canais[0]].pino_origem[:6]
               for i in (0, 1)}
    assert origens == {"DDR5_A", "DDR5_B"}
    gs = {plano.canais[plano.enlace(f"GPU-MEM{i}").canais[0]].pino_origem.split("_")[0]
          for i in range(12)}
    assert len(gs) == 12


def test_contagem_bate_com_pinagem(plano):
    cpu = obter("i5-13600KF")
    relogio = lambda n: n == "BCLK" or n.startswith("REFCLK")   # vêm do gerador de relógio
    sinais_cpu = sum(1 for k in ("DDR5_A", "DDR5_B", "PEG", "DMI", "PCIE4", "AUX")
                     for n in cpu.interfaces[k].sinais if not relogio(n))
    sinais_gpu = len(obter("GPU").interfaces["GDDR7"].sinais)
    pinos = {(c.origem, c.pino_origem) for c in plano.canais}
    assert len(pinos) == sinais_cpu + sinais_gpu
    # comutado: um canal por pino
    assert len(plano.canais) == len(pinos)


def test_dmi_vai_ao_pch_pcie4_ao_fpga_e_relogio_fica_fora(plano):
    canais = lambda e: [plano.canais[i] for i in plano.enlace(e).canais]
    pch = {c.pino_origem: c.pino_destino for c in canais("CPU-PCH")}
    assert pch["DMI_3"] == "DMI_3" and len([n for n in pch if n.startswith("DMI_")]) == 16
    assert pch["PWROK"] == "PWROK" and pch["RSMRST"] == "RSMRST_CPU"
    xcvr = [c for c in canais("CPU-FPGA") if c.protocolo == "PCIe4"]
    assert xcvr and all(not c.pino_destino.startswith("CTL_") for c in xcvr)
    par = {c.pino_origem: c.pino_destino for c in xcvr}
    assert par["PCIE4_TX0"] == "PCIE4_RX0" and not any(n.startswith("DMI") for n in par)
    assert not any(c.papel == "REFCLK" or c.pino_origem == "BCLK" for c in plano.canais)


def test_dedicado_dobra_so_os_bidirecionais(cfg, plano):
    ded = rotear(cfg, modo_bidirecional="dedicado")
    bidir = sum(c.sentido == "duplo" for c in plano.canais)
    assert len(ded.canais) == len(plano.canais) + bidir
    assert not any(c.sentido == "duplo" for c in ded.canais)


def test_grupos_de_byte_numa_fibra_so(cfg):
    for modo in ("comutado", "dedicado"):
        p = rotear(cfg, modo_bidirecional=modo)
        fibras = {}
        for c in p.canais:
            fibras.setdefault((c.enlace, c.grupo, c.sentido), set()).add(c.fibra)
        assert all(len(v) == 1 for v in fibras.values())
        assert all(len(f.canais) <= p.canais_por_fibra for f in p.fibras)


@pytest.mark.parametrize("modo,topologia,canais,fibras", [
    ("comutado", "barramento", 384, 6),
    ("dedicado", "barramento", 768, 12),
    ("comutado", "ponto_a_ponto", 384, 12),
    ("dedicado", "ponto_a_ponto", 768, 24),
])
def test_gddr7_384_pinos(cfg, modo, topologia, canais, fibras):
    p = rotear(cfg, modo_bidirecional=modo, topologia=topologia)
    dq = [c for c in p.canais if c.protocolo == "GDDR7-32" and c.papel == "DQ"]
    assert len(dq) == canais
    assert len({c.fibra for c in dq}) == fibras
    banda = sum(c.taxa_gbps for c in dq if c.sentido != "volta") / 8
    assert banda == pytest.approx(1536.0)


def test_latencia_e_comutacao(plano):
    L = calcular(plano)
    ddr = L.enlace("CPU-DIMM0")
    assert 100 < ddr.atraso_dados_ps < 1000
    assert ddr.treinavel
    assert ddr.comutacao["decodificacao_escondida"]
    assert "cabe_na_bolha" in ddr.comutacao
    assert not L.enlace("CPU-GPU").comutacao


@pytest.mark.parametrize("modo", ["comutado", "dedicado"])
def test_rajadas_em_canal_ideal(cfg, modo):
    p = rotear(cfg, modo_bidirecional=modo)
    for op in ("escrita", "leitura"):
        d = os.urandom(64)
        r = E.rajada_ddr5(p, "CPU-DIMM1", op, d, subcanal="B")
        assert r.ok and r.recebidos == d and r.sentido_decodificado == op
        g = os.urandom(48)
        r = E.rajada_gddr7(p, "GPU-MEM5", op, g)
        assert r.ok and r.recebidos == g


def test_comando_corrompido_perde_a_rajada(plano):
    r = E.rajada_ddr5(plano, "CPU-DIMM0", "escrita", os.urandom(64),
                      modelo=E.canal_ideal(0.3, semente=1))
    assert r.sentido_decodificado == "invalido"
    assert r.erros_bits > 0


def test_treinamento_converge_e_quebra_se_o_caminho_muda(cfg, plano):
    L = calcular(plano)
    t = E.treinar(plano, L, "CPU-DIMM0")
    assert t.convergiu and len(t.pistas) == 64
    assert E.verificar(t, plano, L)["falhas"] == 0

    movido = copy.deepcopy(cfg)
    movido.por_nome("DIMM0").y += 25.0
    p2 = rotear(movido)
    L2 = calcular(p2)
    assert E.verificar(t, p2, L2)["falhas"] == len(t.pistas)
    assert E.treinar(p2, L2, "CPU-DIMM0").convergiu


def test_treinamento_gddr7(plano):
    L = calcular(plano)
    assert E.treinar(plano, L, "GPU-MEM0").convergiu
    estreito = E.treinar(plano, L, "GPU-MEM0", largura_olho_ui=0.03)
    assert not estreito.convergiu
