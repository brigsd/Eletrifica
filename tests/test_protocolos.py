import pytest

from modulos.conexoes.verificador import verificar
from modulos.dados import comandos as K
from modulos.dados import ddr5 as D
from modulos.dados import pcie as P
from modulos.sistema.boot import emular


@pytest.mark.parametrize("protocolo", sorted(K.TABELA))
def test_decodificador_acerta_a_tabela(protocolo):
    for t in K.TABELA[protocolo]:
        palavras = K.codificar(protocolo, t.nome, ma=34, op=0x2B, banco=3, coluna=17)
        (cmd,) = K.decodificar(protocolo, palavras)
        assert cmd.nome == t.nome and cmd.sentido_dq == t.sentido_dq
        if t.registrador:
            assert cmd.registrador == (34, 0x2B)


def test_sequencia_mista_e_o_que_o_tradutor_precisa_ler():
    ws = K.codificar("DDR5-4800", "ACT") + K.codificar("DDR5-4800", "WR") + K.codificar("DDR5-4800", "NOP") \
        + K.codificar("DDR5-4800", "RD")
    assert [c.nome for c in K.decodificar("DDR5-4800", ws)] == ["ACT", "WR", "NOP", "RD"]
    nec = K.necessarios("DDR5-4800")
    assert {"RD", "WR", "MRR"} <= set(nec) and any(x.startswith("MRW:") and "34" in x for x in nec)
    assert "ACT" in K.copiados_sem_ler("DDR5-4800") and "ACT" not in nec


@pytest.mark.parametrize("protocolo", sorted(K.TABELA))
def test_decodificar_cabe_antes_do_primeiro_dado(protocolo):
    assert K.latencia_decodificacao_ps(protocolo) + 300.0 < K.janela_ps(protocolo)


def test_espelhamento_acompanha_o_mrw():
    passos = D.simular(espelhar=True)
    assert not any(p.diverge for p in passos)
    escritas = [p for p in passos if p.situacao == "escrita"]
    assert [p.visto_cpu["terminacao"] for p in escritas] == [80.0, 240.0]


def test_sem_espelhar_a_terminacao_diverge():
    r = D.resumo(D.simular(espelhar=False))
    assert r["divergem"] > 0
    assert r["por_situacao"]["escrita"]["programado"] == "240 Ω"
    assert abs(r["pior_erro_amplitude_mv"]) > 100


def test_faixas_permitidas_cobrem_o_padrao():
    assert None in D.PERMITIDOS["DDR5-4800"]["terminacao"]
    assert {34.0, 40.0, 48.0} == set(D.PERMITIDOS["DDR5-4800"]["forca"])


def test_presets_somam_um():
    for ps, de in P.PRESETS.values():
        cm1, c0, cp1 = P.coeficientes(ps, de)
        assert abs(abs(cm1) + c0 + abs(cp1) - 1) < 1e-9 and cm1 <= 0 and cp1 <= 0


def test_equalizacao_abre_o_olho_e_compara_com_o_linear():
    anel = P.equalizar(30.0, 30.0, 0.004, 32.0)
    linear = P.equalizar(30.0, 30.0, 0.004, 32.0, linear=True)
    assert anel["aberto"] and anel["preset"] in P.PRESETS
    assert abs(anel["altura_rel"] - linear["altura_rel"]) < 0.1


def test_canal_ruim_fecha_o_olho():
    assert not P.equalizar(400.0, 400.0, 0.01, 32.0)["aberto"]


def _lado(**kw):
    base = dict(politica="controlada", par_identificado=True, optico_travado=True, squelch_ps=4000.0)
    base.update(kw)
    return P.LadoTradutor(**base)


def test_ltssm_chega_a_l0():
    r = P.ltssm(_lado(), _lado(), P.equalizar(30.0, 30.0, 0.004, 32.0))
    assert r.ok and r.estados[-1][0].startswith("L0 (32")
    assert 20.0 < r.total_ms < P.DETECT_QUIET_MS + 2 * P.EQ_FASE_TIMEOUT_MS + 5


def test_ltssm_para_em_detect_sem_terminacao():
    r = P.ltssm(_lado(optico_travado=False), _lado(), P.equalizar(30.0, 30.0, 0.004, 32.0))
    assert not r.ok and r.parou_em == "Detect"
    r = P.ltssm(_lado(politica=None), _lado(), P.equalizar(30.0, 30.0, 0.004, 32.0))
    assert r.parou_em == "Detect"


def test_ltssm_para_no_polling_com_squelch_lento():
    r = P.ltssm(_lado(squelch_ps=20_000.0), _lado(), P.equalizar(30.0, 30.0, 0.004, 32.0))
    assert r.parou_em == "Polling"


def test_ltssm_para_na_equalizacao_sem_olho():
    r = P.ltssm(_lado(), _lado(), P.equalizar(400.0, 400.0, 0.01, 32.0))
    assert r.parou_em == "Recovery.Equalization"


@pytest.mark.lento
def test_netlist_real_passa_nas_regras_de_protocolo(netlist_real):
    rel = verificar(netlist_real)
    assert not [v.mensagem for v in rel.erros if v.regra in ("R15-decodificacao", "R16-ajuste", "R17-pcie")]
    assert D.avaliar_netlist(netlist_real)["problemas"] == []


@pytest.mark.lento
def test_boot_real_para_no_detect_sem_terminacao_controlada(sistema_real):
    from modulos.conexoes.construir import construir
    m, cfg, plano, viavel = sistema_real
    nl = construir(m, cfg, plano, viavel, posicionamento="sob_peca", chave="rele_mems")
    ok = emular(nl)
    assert ok.ok and any(e[2] == "enlace PCIe ativo" for e in ok.eventos)
    for b in nl.por_tipo("via_tx"):
        if b.atributos.get("deteccao_receptor"):
            b.atributos["deteccao_receptor"] = "sempre"
    # apresentar terminação sempre não trava o boot, mas o verificador reprova
    assert "R17-pcie" in verificar(nl).regras_com_erro()
    for b in nl.por_tipo("via_tx"):
        if b.atributos.get("deteccao_receptor"):
            b.atributos["deteccao_receptor"] = None
    ex = emular(nl)
    assert ex.parou_em["etapa"] == "PCIe" and "Detect" in ex.parou_em["motivo"]
