import math

import pytest

from modulos.conexoes.netlist import Netlist, Requisito
from modulos.conexoes.verificador import verificar
from modulos.dados.memoria_compartilhada import comparar
from modulos.sistema.boot import emular


def _corte_dmi(nl):
    """Uma ligação que só a DMI usa: trilha do pino até a via do tradutor."""
    cam = nl.sinais["CPU.DMI_0->PCH.DMI_0"].caminhos["ida"]
    p, q = next((p, q) for p, q in zip(cam, cam[1:])
                if nl.blocos[p[0]].tipo == "trilha" and nl.blocos[q[0]].tipo == "via_tx")
    return f"lig:{p[0]}|{q[0]}"


@pytest.mark.lento
def test_pch_identificado(sistema_real):
    m, cfg, _, _ = sistema_real
    pc, col = cfg.por_nome("PCH"), m.por_id("PCH")
    assert pc.peca.tipo == "PCH" and pc.avaliacao["veredito"] == "ok"
    assert math.hypot(pc.x - col.x, pc.y - col.y) < 0.05


@pytest.mark.lento
def test_requisitos_de_plataforma_apontam_para_o_pch(netlist_real):
    nl = netlist_real
    req = {(r.peca, r.capacidade): r.provedor for r in nl.requisitos}
    assert nl.blocos["ctl:pch"].atributos["plataforma"] == "PCH"
    for peca, cap in (("CPU", "PCH/DMI"), ("CPU", "sequenciamento-PWROK"), ("DIMM", "SPD/I3C"),
                      ("PONTE", "SPD/I3C")):
        assert req[(peca, cap)] == "ctl:pch", (peca, cap)
    assert req[("CPU", "BCLK")] == "clk:pch"
    assert req[("CPU", "firmware-UEFI")] == req[("PCH", "firmware-ME")] == "flash:uefi"
    # a flash é lida pela SPI do PCH, por trilha
    spi = [s for s in nl.sinais.values() if s.grupo == "SPI"]
    assert len(spi) == 4 and all("PCH" in s.id and "flash" in s.id for s in spi)


@pytest.mark.lento
def test_boot_com_pch_segue_a_sequencia_intel(netlist_real):
    ex = emular(netlist_real)
    assert ex.ok, ex.parou_em
    nomes = [e["nome"] for e in ex.etapas]
    assert nomes.index("Fonte e standby") < nomes.index("ME do chipset") < nomes.index("Trilhos principais")
    assert nomes.index("Relógio e reset") < nomes.index("BIOS pela DMI") < nomes.index("Treino da memória")
    quando = {}
    for t, alvo, estado, detalhe in ex.eventos:
        quando.setdefault((alvo, estado), t)
        if estado == "power-good" and detalhe.startswith("VID de boot"):
            quando.setdefault("vccin", t)
    ordem = [("ctl:pch", "standby"), ("ctl:fpga", "RSMRST# solto"), ("ctl:pch", "ME pronto"),
             ("ctl:pch", "SLP_S3# solto"), ("ctl:fpga", "SYS_PWROK"), ("ctl:pch", "PROCPWRGD"),
             "vccin", ("ctl:pch", "PLTRST# solto"), ("CPU", "BIOS lida")]
    ts = [quando[k] for k in ordem]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)
    # os reguladores principais só sobem depois do SLP_S3#
    assert all(t > quando[("ctl:pch", "SLP_S3# solto")] for t, alvo, estado, _ in ex.eventos
               if estado == "power-good" and alvo.startswith("reg:PCH:VCCPRIM"))


@pytest.mark.lento
@pytest.mark.parametrize("falha, etapa, bloco", [
    ("regiao:flash:uefi:ME", "ME", "flash:uefi"),
    ("ctl:pch", "RSMRST#", "ctl:pch"),
    (_corte_dmi, "BIOS pela DMI", "CPU.DMI_0->PCH.DMI_0"),
])
def test_falhas_de_plataforma_param_na_etapa_certa(netlist_real, falha, etapa, bloco):
    f = falha(netlist_real) if callable(falha) else falha
    ex = emular(netlist_real, falhas=(f,))
    assert not ex.ok
    assert ex.parou_em["etapa"] == etapa and ex.parou_em["bloco"] == bloco, ex.parou_em


def test_cxl_ausente_e_aviso_nao_erro():
    nl = Netlist()
    nl.bloco("CPU:PEG_TX0", "pino", capacidades=["raiz-PCIe"])
    nl.requisitos.append(Requisito("GPU", "memoria-compartilhada", None))
    rel = verificar(nl)
    assert rel.contagem("R18-memoria-compartilhada", "aviso") == 1
    assert not [v for v in rel.erros if v.regra in ("R11-requisito", "R18-memoria-compartilhada")]
    nl.blocos["CPU:PEG_TX0"].atributos["capacidades"].append("memoria-compartilhada")
    nl.requisitos[0] = Requisito("GPU", "memoria-compartilhada", "CPU:PEG_TX0")
    assert verificar(nl).contagem("R18-memoria-compartilhada", "aviso") == 0


def test_flash_sem_regiao_me_e_erro():
    nl = Netlist()
    nl.bloco("flash:uefi", "flash", regioes=["descritor", "BIOS"],
             capacidades=["firmware-UEFI", "firmware-ME"])
    nl.requisitos += [Requisito("PCH", "firmware-ME", "flash:uefi"),
                      Requisito("CPU", "firmware-UEFI", "flash:uefi")]
    erros = [v.alvo for v in verificar(nl).erros if v.regra == "R11-requisito"]
    assert erros == ["PCH:firmware-ME"]


@pytest.mark.lento
def test_netlist_real_compartilha_pelo_banco_e_nao_tem_erro_de_plataforma(netlist_real):
    rel = verificar(netlist_real)
    assert rel.contagem("R18-memoria-compartilhada", "aviso") == 0       # o banco unificado provê
    assert rel.contagem("R18-memoria-compartilhada", "erro") == 0
    assert rel.contagem("R11-requisito", "erro") == 0


@pytest.mark.lento
def test_memoria_compartilhada_quatro_linhas_coerentes(netlist_real):
    t = comparar(netlist_real)
    assert set(t) == {"rebar_pcie", "ddr5_local", "unificada", "banco"}
    bc = t["banco"]
    assert bc["nesta_montagem"] and bc["coerente"] == "por posse"
    # a CPU lê o banco quase como a DDR5 local, e muito mais perto que o ReBAR
    assert t["ddr5_local"]["latencia_ns"] < bc["latencia_ns"] < t["ddr5_local"]["latencia_ns"] + 15
    assert bc["latencia_ns"] < t["rebar_pcie"]["latencia_ns"] / 10
    rb, dd, un = t["rebar_pcie"], t["ddr5_local"], t["unificada"]
    assert not rb["coerente"] and dd["coerente"] and un["coerente"]
    assert rb["nesta_montagem"] and dd["nesta_montagem"] and not un["nesta_montagem"]
    assert 0.85 < rb["banda_gb_s"] / rb["banda_pico_gb_s"] < 0.95       # TLP e DLLP
    assert dd["banda_gb_s"] < rb["banda_gb_s"] < un["banda_gb_s"]      # a CPU tem um DIMM só
    assert dd["latencia_ns"] < un["latencia_ns"] < rb["latencia_ns"]
    # o caminho óptico da netlist entra ida e volta
    assert rb["caminho_ns"] > 0 and dd["caminho_ns"] > 0 and un["caminho_ns"] == 0
    assert dd["latencia_ns"] == pytest.approx(90.0 + 2 * dd["caminho_ns"])
