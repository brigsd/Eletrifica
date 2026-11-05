"""Malha ligada ao sistema: fluxos do plano, avaliação e as regras R21/R22 do verificador."""
import pytest

from modulos.conexoes.netlist import Netlist
from modulos.conexoes.verificador import verificar
from modulos.dados.roteamento import Canal, Enlace, Plano
from modulos.malha import montar as MO
from modulos.malha.parametros import FALLBACK as FIXOS
from modulos.sistema import base as B


def _base():
    return B.Base(320.0, 240.0, 0.4, 0.2)


def _centro(seg, passo=25.0):
    """Ponto no centro do segmento (x, y), em mm."""
    return ((seg[0] + 0.5) * passo, (seg[1] + 0.5) * passo)


def _plano(enlaces):
    """enlaces: lista de (id, protocolo, segmento_a, segmento_b, [taxa_gbps por canal])."""
    canais, ens = [], []
    for eid, prot, sa, sb, taxas in enlaces:
        idx = []
        for k, t in enumerate(taxas):
            canais.append(Canal(eid, "A", "B", f"p{k}", f"q{k}", "ida", prot, "DQ", t, t, "NRZ", eid))
            idx.append(len(canais) - 1)
        ens.append(Enlace(eid, "A", "B", prot, idx, _centro(sa), _centro(sb)))
    return Plano(ens, canais, [], 64, "comutado", "barramento", {})


def _verificar_malha(malha):
    return verificar(Netlist(), {"malha": malha})


# ----------------------------------------------------------- rápidos
def test_malha_da_base_cobre_a_base_inteira():
    m = MO.malha_da_base(_base(), params=FIXOS)
    # 320 / 25 = 12,8 -> 13 colunas; 240 / 25 = 9,6 -> 10 linhas
    assert (m.colunas, m.linhas) == (13, 10)
    assert m.passo_mm == MO.MALHA_PASSO_MM
    assert m.faixas_por_ligacao == MO.MALHA_FAIXAS
    assert m.gbps_por_faixa == MO.MALHA_GBPS_POR_FAIXA


def test_orcamento_por_protocolo():
    assert MO.orcamento_ns("GDDR7-32", FIXOS) == 10.0
    assert MO.orcamento_ns("DDR5-4800", FIXOS) == 15.0
    assert MO.orcamento_ns("PCIe5", FIXOS) == 100.0
    assert MO.orcamento_ns("AUX", FIXOS) == MO.ORCAMENTO_PADRAO_NS == 20.0


def test_segmento_de_ponto_fora_da_base_falha():
    m = MO.malha_da_base(_base(), params=FIXOS)
    with pytest.raises(ValueError):
        MO.segmento_de(m, (400.0, 10.0))


def test_fluxos_do_plano_somam_taxa_dos_canais_em_gbs():
    m = MO.malha_da_base(_base(), params=FIXOS)
    plano = _plano([("E1", "GDDR7-32", (0, 0), (1, 0), [16.0, 16.0, 16.0, 16.0])])
    (f,) = MO.fluxos_do_plano(plano, m)
    assert f.nome == "E1"
    assert f.origem == (0, 0) and f.destino == (1, 0)
    assert f.gbs == pytest.approx(64.0 / 8)      # 4 canais × 16 Gb/s = 64 Gb/s = 8 GB/s
    assert f.protocolo == "GDDR7-32"


def test_fluxo_aceita_protocolo_opcional_sem_quebrar():
    from modulos.malha.trafego import Fluxo
    assert Fluxo("x", (0, 0), (1, 0), 1.0).protocolo == ""


def test_avaliar_sem_erro_quando_cabe_e_chega_no_prazo():
    b = _base()
    plano = _plano([
        ("PERTO", "GDDR7-32", (0, 0), (1, 0), [32.0] * 4),      # 1 salto
        ("MEIO", "DDR5-4800", (0, 1), (3, 1), [32.0] * 4),      # 3 saltos
    ])
    r = MO.avaliar(plano, b, params=FIXOS)
    assert r["fora_do_orcamento"] == []
    assert r["acima_de_100"] == []
    assert r["resumo"]["saltos_max"] == 3
    assert r["resumo"]["ocupacao_max"] < 1.0
    rel = _verificar_malha(r)
    assert rel.contagem("R21-malha-atraso") == 0
    assert rel.contagem("R22-malha-ocupacao") == 0


def test_r21_erro_quando_o_atraso_passa_do_orcamento_gddr7():
    # passo 25 mm: 1,675 ns por salto. 5 saltos = 8,4 ns (cabe); 6 = 10,05 ns (estoura 10 ns)
    b = _base()
    plano = _plano([
        ("CINCO", "GDDR7-32", (0, 0), (5, 0), [32.0] * 4),
        ("SEIS", "GDDR7-32", (0, 1), (6, 1), [32.0] * 4),
    ])
    r = MO.avaliar(plano, b, params=FIXOS)
    assert [d["nome"] for d in r["fora_do_orcamento"]] == ["SEIS"]
    rel = _verificar_malha(r)
    assert rel.contagem("R21-malha-atraso") == 1
    (v,) = [v for v in rel.violacoes if v.regra == "R21-malha-atraso"]
    assert v.alvo == "SEIS" and "6 saltos" in v.mensagem


def test_r22_erro_quando_a_ligacao_passa_da_capacidade():
    # 1 faixa de 8 Gb/s = 1 GB/s por ligação; o fluxo leva 2 GB/s (16 Gb/s) num salto só
    b = _base()
    m = MO.malha_da_base(b, faixas=1, gbps=8.0, params=FIXOS)
    plano = _plano([("CHEIO", "PCIe5", (0, 0), (1, 0), [16.0])])
    r = MO.avaliar(plano, b, malha=m)
    assert len(r["acima_de_100"]) == 1
    assert r["acima_de_100"][0][1] == pytest.approx(2.0)
    rel = _verificar_malha(r)
    assert rel.contagem("R22-malha-ocupacao") == 1


def test_verificar_sem_malha_nao_roda_r21_nem_r22():
    rel = verificar(Netlist())
    assert all(v.regra not in ("R21-malha-atraso", "R22-malha-ocupacao") for v in rel.violacoes)
    rel2 = verificar(Netlist(), {"margem_db": 3.0})
    assert all(v.regra not in ("R21-malha-atraso", "R22-malha-ocupacao") for v in rel2.violacoes)


def test_r21_e_r22_estao_em_regras():
    from modulos.conexoes.verificador import REGRAS
    assert "R21-malha-atraso" in REGRAS and "R22-malha-ocupacao" in REGRAS


# ----------------------------------------------------------- lentos (configuração real)
@pytest.mark.lento
def test_avaliar_configuracao_real(sistema_real):
    m, cfg, plano, viavel = sistema_real
    r = MO.avaliar(plano, m.base)
    assert len(r["fluxos"]) == len(plano.enlaces)
    assert r["resumo"]["saltos_max"] >= 1
    assert r["resumo"]["potencia_w"] > 0
    rel = _verificar_malha(r)
    # as regras contam exatamente o que o avaliar listou
    assert rel.contagem("R21-malha-atraso") == len(r["fora_do_orcamento"])
    assert rel.contagem("R22-malha-ocupacao") == len(r["acima_de_100"])


@pytest.mark.lento
def test_faixas_menores_nao_melhoram_a_ocupacao_real(sistema_real):
    m, cfg, plano, viavel = sistema_real
    padrao = MO.avaliar(plano, m.base)
    fino = MO.avaliar(plano, m.base, malha=MO.malha_da_base(m.base, faixas=4))
    assert fino["resumo"]["ocupacao_max"] > padrao["resumo"]["ocupacao_max"]
    assert len(fino["acima_de_100"]) >= len(padrao["acima_de_100"])


@pytest.mark.lento
def test_netlist_real_sem_malha_nao_tem_r21_nem_r22(netlist_real):
    rel = verificar(netlist_real)
    assert rel.contagem("R21-malha-atraso") == 0
    assert rel.contagem("R21-malha-atraso", "aviso") == 0
    assert rel.contagem("R22-malha-ocupacao") == 0
    assert rel.contagem("R22-malha-ocupacao", "aviso") == 0
