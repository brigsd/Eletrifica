import importlib.util

import pytest

from modulos.conexoes.netlist import Netlist, Requisito, Sinal
from modulos.sistema.boot import Execucao, emular


def _energia(nl, bloco, porta, sentido, rede):
    nl.porta(bloco, porta, "energia", sentido)
    nl.ligar((bloco, porta), (rede, "rede"), "trilha")


def _regulador(nl, id_, vin, vout, tensao):
    nl.bloco(id_, "regulador", tensao_v=tensao, corrente_max_a=10.0)
    _energia(nl, id_, "vin", "entra", vin)
    _energia(nl, id_, "vout", "sai", vout)


def _chip(nl, id_, rede_vdd, laser_fibra):
    nl.bloco(id_, "chip_tradutor", vias_max=64)
    _energia(nl, id_, "vdd", "entra", rede_vdd)
    nl.porta(id_, "ctl", "controle", "entra")
    nl.ligar((id_, "ctl"), ("ctl:fpga", "i3c0"), "trilha")
    nl.porta(id_, "laser", "optico", "entra")
    nl.ligar((id_, "laser"), (laser_fibra, "b"), "fibra")
    nl.porta(id_, "f0", "optico", "bidir")
    for v, t in (("t0", "via_tx"), ("r0", "via_rx")):
        nl.bloco(f"{id_}:{v}", t, pai=id_)
        nl.porta(f"{id_}:{v}", "e", "eletrico", "entra" if t == "via_tx" else "sai", "DDR5-DQ")
        nl.porta(f"{id_}:{v}", "luz", "optico", "sai" if t == "via_tx" else "entra")


def _pino(nl, peca, nome, padrao="DDR5-DQ", sentido="bidir"):
    id_ = f"{peca}:{nome}"
    nl.bloco(id_, "pino", peca=peca)
    nl.porta(id_, "e", "eletrico", sentido, padrao)
    cel = f"cel:{peca}:{nome}"
    nl.bloco(cel, "celula", n_celulas=3)
    nl.porta(cel, "pino", "eletrico", "bidir")
    nl.porta(cel, "base", "eletrico", "bidir")
    nl.ligar((id_, "e"), (cel, "pino"), "contato")
    return id_, cel


def netlist_minima():
    nl = Netlist()
    nl.bloco("fonte:atx", "fonte")
    nl.porta("fonte:atx", "12v", "energia", "sai")
    for r in ("rede:12v", "rede:3v3sb", "rede:vccin", "rede:vccsa", "rede:5v", "rede:0v9"):
        nl.bloco(r, "trilho")
        nl.porta(r, "rede", "energia", "bidir")
    nl.ligar(("fonte:atx", "12v"), ("rede:12v", "rede"), "trilha")
    _regulador(nl, "reg:3v3sb", "rede:12v", "rede:3v3sb", 3.3)
    _regulador(nl, "reg:vccin", "rede:12v", "rede:vccin", 1.25)
    _regulador(nl, "reg:vccsa", "rede:12v", "rede:vccsa", 1.05)
    _regulador(nl, "reg:5v", "rede:12v", "rede:5v", 5.0)
    _regulador(nl, "reg:0v9", "rede:12v", "rede:0v9", 0.9)

    nl.bloco("ctl:fpga", "controlador")
    _energia(nl, "ctl:fpga", "vdd", "entra", "rede:3v3sb")
    nl.porta("ctl:fpga", "i3c0", "controle", "sai")
    nl.porta("ctl:fpga", "spi", "controle", "sai")
    nl.bloco("flash:uefi", "flash")
    _energia(nl, "flash:uefi", "vdd", "entra", "rede:3v3sb")
    nl.porta("flash:uefi", "spi", "controle", "entra")
    nl.ligar(("ctl:fpga", "spi"), ("flash:uefi", "spi"), "trilha")

    nl.bloco("ctl:vrm", "controlador")
    _energia(nl, "ctl:vrm", "vdd", "entra", "rede:3v3sb")
    nl.porta("ctl:vrm", "pwm", "controle", "sai")
    nl.porta("reg:vccin", "ctl", "controle", "entra")
    nl.ligar(("ctl:vrm", "pwm"), ("reg:vccin", "ctl"), "trilha")

    nl.bloco("laser:0", "laser", lambdas_nm=[1310.0])
    _energia(nl, "laser:0", "vdd", "entra", "rede:0v9")
    for k in (0, 1):
        nl.porta("laser:0", f"out{k}", "optico", "sai")
        nl.bloco(f"fib:l{k}", "fibra")
        nl.porta(f"fib:l{k}", "a", "optico", "entra")
        nl.porta(f"fib:l{k}", "b", "optico", "sai")
        nl.ligar(("laser:0", f"out{k}"), (f"fib:l{k}", "a"), "fibra")
    _chip(nl, "tx:CPU:0", "rede:0v9", "fib:l0")
    _chip(nl, "tx:DIMM0:0", "rede:0v9", "fib:l1")
    nl.bloco("fib:0", "fibra")
    nl.porta("fib:0", "a", "optico", "bidir")
    nl.porta("fib:0", "b", "optico", "bidir")
    nl.ligar(("tx:CPU:0", "f0"), ("fib:0", "a"), "fibra")
    nl.ligar(("tx:DIMM0:0", "f0"), ("fib:0", "b"), "fibra")

    nl.bloco("clk:ref", "relogio")
    _energia(nl, "clk:ref", "vdd", "entra", "rede:3v3sb")
    nl.porta("clk:ref", "out0", "eletrico", "sai", "HCSL-100M")
    bclk, cel_bclk = _pino(nl, "CPU", "BCLK", "HCSL-100M", "entra")
    nl.ligar(("clk:ref", "out0"), (cel_bclk, "base"), "trilha")

    cpu, cel_cpu = _pino(nl, "CPU", "DDR5_A_A_DQ0")
    dimm, cel_dimm = _pino(nl, "DIMM0", "DDR5_A_DQ0")
    nl.ligar((cel_cpu, "base"), ("tx:CPU:0:t0", "e"), "trilha")
    nl.ligar((cel_dimm, "base"), ("tx:DIMM0:0:r0", "e"), "trilha")
    ida = [(cpu, "e"), (cel_cpu, "pino"), (cel_cpu, "base"), ("tx:CPU:0:t0", "e"),
           ("tx:CPU:0:t0", "luz"), ("fib:0", "a"), ("fib:0", "b"), ("tx:DIMM0:0:r0", "luz"),
           ("tx:DIMM0:0:r0", "e"), (cel_dimm, "base"), (cel_dimm, "pino"), (dimm, "e")]
    volta = [(dimm, "e"), (cel_dimm, "pino"), (cel_dimm, "base"), ("tx:DIMM0:0:t0", "e"),
             ("tx:DIMM0:0:t0", "luz"), ("fib:0", "b"), ("fib:0", "a"), ("tx:CPU:0:r0", "luz"),
             ("tx:CPU:0:r0", "e"), (cel_cpu, "base"), (cel_cpu, "pino"), (cpu, "e")]
    nl.sinal(Sinal(f"{cpu}->{dimm}", "DDR5-4800", "DQ", "DDR5-DQ", (cpu, "e"), (dimm, "e"),
                   ("ida", "volta"), "A0", {"ida": ida, "volta": volta}))

    for peca, cap, prov in (("CPU", "PCH/DMI", "ctl:fpga"), ("CPU", "VR-SVID", "ctl:vrm"),
                            ("CPU", "BCLK", "clk:ref"), ("CPU", "firmware-UEFI", "flash:uefi"),
                            ("CPU", "sequenciamento-PWROK", "ctl:fpga"),
                            ("CPU", "energia", "reg:vccin"),
                            ("DIMM0", "SPD/I3C", "ctl:fpga"), ("DIMM0", "energia", "reg:5v")):
        nl.requisitos.append(Requisito(peca, cap, prov))
    return nl


def test_boot_nominal_completo():
    ex = emular(netlist_minima())
    assert ex.ok, ex.parou_em
    nomes = [e["nome"] for e in ex.etapas]
    for n in ("Sondagem", "Trilhos principais", "Anéis travados", "Núcleo da CPU",
              "Relógio e reset", "Treino da memória", "Pronto"):
        assert n in nomes
    t = ex.tempos
    assert t["Sondagem"] < t["Trilhos principais"] < t["Anéis travados"] < t["Núcleo da CPU"]
    assert t["Núcleo da CPU"] < t["Relógio e reset"] < t["Treino da memória"] <= t["Pronto"]
    assert ex.eventos == sorted(ex.eventos, key=lambda e: e[0])
    assert "CPU" in ex.etapas[-1]["energizadas"] and "DDR5" in ex.etapas[-1]["enlaces_ativos"]


def test_ordem_dos_eventos_criticos():
    ex = emular(netlist_minima())
    quando = {}
    for t, alvo, estado, _ in ex.eventos:
        quando.setdefault((alvo, estado), t)
    assert quando[("reg:3v3sb", "power-good")] < quando[("ctl:fpga", "firmware carregado")]
    assert quando[("ctl:fpga", "RSMRST# solto")] < quando[("reg:vccsa", "power-good")]
    assert quando[("tx:CPU:0", "anéis travados")] < quando[("ctl:fpga", "PWROK")]
    assert quando[("ctl:fpga", "PWROK")] < quando[("reg:vccin", "power-good")]
    assert quando[("reg:vccin", "power-good")] < quando[("ctl:fpga", "PLTRST# solto")]


def test_tempos_medidos_sobrescrevem_os_tipicos():
    a = emular(netlist_minima())
    b = emular(netlist_minima(), sim={"aneis_travamento_us": 5_000.0})
    assert b.tempos["Anéis travados"] - a.tempos["Anéis travados"] == pytest.approx(4_800.0)


def test_laser_apagado_para_nos_aneis():
    ex = emular(netlist_minima(), falhas=("laser:0",))
    assert not ex.ok
    assert ex.parou_em["etapa"] == "Anéis" and ex.parou_em["bloco"] == "laser:0"
    assert "PWROK" not in [e[2] for e in ex.eventos]


def test_fibra_do_laser_cortada_para_nos_aneis():
    ex = emular(netlist_minima(), falhas=("lig:laser:0|fib:l1",))
    assert ex.parou_em["etapa"] == "Anéis" and ex.parou_em["bloco"] == "tx:DIMM0:0"


def test_regulador_sem_power_good_para_antes_do_pwrok():
    ex = emular(netlist_minima(), falhas=("reg:vccsa",))
    assert not ex.ok
    assert ex.parou_em["etapa"] == "PWROK" and ex.parou_em["bloco"] == "reg:vccsa"
    assert "PWROK" not in [e[2] for e in ex.eventos]


def test_pch_sem_provedor_nao_solta_pltrst():
    ex = emular(netlist_minima(), falhas=("req:CPU:PCH/DMI",))
    assert ex.parou_em["etapa"] == "PLTRST"
    estados = [e[2] for e in ex.eventos]
    assert "PWROK" in estados and "PLTRST# solto" not in estados


def test_sem_controle_do_chip_para_nos_tradutores():
    ex = emular(netlist_minima(), falhas=("lig:ctl:fpga|tx:DIMM0:0",))
    assert ex.parou_em["etapa"] == "Tradutores" and ex.parou_em["bloco"] == "tx:DIMM0:0"


def test_standby_morto_nao_liga_o_fpga():
    ex = emular(netlist_minima(), falhas=("reg:3v3sb",))
    assert ex.parou_em["etapa"] == "Standby"


def test_caminho_ddr5_incompleto_para_no_pltrst():
    nl = netlist_minima()
    s = next(iter(nl.sinais.values()))
    s.caminhos.pop("volta")
    ex = emular(nl)
    assert ex.parou_em["etapa"] == "PLTRST" and ex.parou_em["bloco"] == s.id


@pytest.mark.lento
@pytest.mark.skipif(importlib.util.find_spec("modulos.conexoes.construir") is None,
                    reason="construtor da netlist ainda não existe")
def test_boot_na_netlist_real():
    from modulos.conexoes import construir as K
    from modulos.sistema import base as B, configuracao as C, mapeamento as M

    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, s), s)
    nl = K.construir(m, cfg)
    assert isinstance(emular(nl), Execucao)
