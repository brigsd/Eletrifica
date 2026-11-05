"""Física real na malha: parâmetros do malha.json, salto por chave, perda por trecho,
desalinhamento entre faixas e calor. Os rápidos montam malhas pequenas com parâmetros
explícitos; só os marcados `lento` usam o sistema real."""
import pytest

from modulos.conexoes.netlist import Netlist
from modulos.conexoes.verificador import REGRAS, verificar
from modulos.malha import calor as CA
from modulos.malha import custo
from modulos.malha import montar as MO
from modulos.malha import parametros as PA
from modulos.malha.topologia import Malha, ligacao
from modulos.malha.trafego import Fluxo, reservar

FIXOS = PA.FALLBACK


def _p(**kw):
    return PA.com(FIXOS, **kw)


def _malha(colunas=4, linhas=4, tipo="retransmite", p=None, passo=25.0):
    return Malha(colunas=colunas, linhas=linhas, passo_mm=passo, faixas_por_ligacao=32,
                 gbps_por_faixa=32.0, tipo_salto=tipo, params=p or FIXOS)


def _verificar(av):
    return verificar(Netlist(), {"malha": av})


# ------------------------------------------------------------ 1. parâmetros da fonte
def test_json_alimenta_os_parametros():
    p = PA.carregar()
    assert p.origem.endswith("malha.json")
    assert (p.passo_mm, p.faixas_por_ligacao, p.gbps_por_faixa) == (25.0, 32, 32.0)
    assert p.retemporizacao_ns == 5.0 and p.pj_por_bit_salto == 3.0
    assert p.material == "megtron6" and p.ps_por_mm == 6.2 and p.perda_db_por_mm == 0.020
    assert p.orcamento("GDDR7-32") == 5.0 and p.orcamento("DDR5-4800") == 5.8
    assert p.orcamento("PCIe5") == 128.0
    assert p.salto_chave_ns == 0.15 and p.salto_chave_pj_por_bit == 0.3
    assert p.orcamento_perda_trecho_db == 16.0


def test_material_troca_ps_e_perda():
    fr4 = PA.carregar(material="fr4")
    assert fr4.ps_por_mm == 6.9 and fr4.perda_db_por_mm == 0.060


def test_arquivo_ausente_cai_no_fallback(tmp_path):
    assert PA.carregar(tmp_path / "nao_existe.json") is PA.FALLBACK


def test_malha_da_base_usa_o_json_e_aceita_valores_explicitos():
    from modulos.sistema import base as B
    b = B.Base(320.0, 240.0, 0.4, 0.2)
    m = MO.malha_da_base(b)
    assert (m.passo_mm, m.faixas_por_ligacao) == (25.0, 32)
    m2 = MO.malha_da_base(b, passo_mm=40.0, faixas=8, gbps=16.0, params=FIXOS)
    assert (m2.passo_mm, m2.faixas_por_ligacao, m2.gbps_por_faixa) == (40.0, 8, 16.0)


def test_orcamento_e_de_ida_e_o_fluxo_tambem():
    # 1 salto de 25 mm: 5 + 25 × 6,2 ps = 5,155 ns de ida. GDDR7 aceita 5,0 (erro); DDR5 5,8 (cabe).
    p = PA.carregar()
    m = _malha(3, 1, p=p)
    av = MO.avaliar_fluxos([Fluxo("G", (0, 0), (1, 0), 1.0, "GDDR7-32"),
                            Fluxo("D", (1, 0), (2, 0), 1.0, "DDR5-4800")], m)
    g, d = av["fluxos"]
    assert g["atraso_ns"] == pytest.approx(5.155) and d["atraso_ns"] == pytest.approx(5.155)
    assert g["folga_ns"] == pytest.approx(5.0 - 5.155) and d["folga_ns"] == pytest.approx(5.8 - 5.155)
    assert [x["nome"] for x in av["fora_do_orcamento"]] == ["G"]       # sem dobrar a ida
    assert _verificar(av).contagem("R21-malha-atraso") == 1
    assert custo.conferir_orcamento(5.155, 5.0) == (False, pytest.approx(-0.155))
    assert custo.conferir_orcamento(5.155, 5.8)[0]


def test_orcamento_do_json_vale_mais_que_o_fallback():
    assert MO.orcamento_ns("GDDR7-32") == 5.0
    assert MO.orcamento_ns("GDDR7-32", FIXOS) == 10.0


# ------------------------------------------------------------ 2. salto por chave
def test_chave_so_desvia_o_sinal():
    p = _p(retemporizacao_ns=5.0, ps_por_mm=6.0, salto_chave_ns=0.15, salto_chave_pj_por_bit=0.3,
           pj_por_bit_salto=3.0)
    ch = custo.percurso([25.0] * 4, "chave", "PCIe5", p)
    assert ch["atraso_ns"] == pytest.approx(4 * (0.15 + 0.15))
    assert ch["energia_pj_bit"] == pytest.approx(4 * 0.3)
    assert not any(ch["retimers"])
    rt = custo.percurso([25.0] * 4, "retransmite", "PCIe5", p)
    assert rt["atraso_ns"] == pytest.approx(4 * (5.0 + 0.15)) and rt["energia_pj_bit"] == pytest.approx(12.0)
    assert ch["atraso_ns"] < rt["atraso_ns"] and ch["energia_pj_bit"] < rt["energia_pj_bit"]


def test_tipo_de_salto_invalido_falha():
    with pytest.raises(ValueError):
        _malha(tipo="magica")
    with pytest.raises(ValueError):
        custo.percurso([25.0], "magica")


def test_n_vem_da_perda_do_cobre():
    # FR4 0,06 dB/mm × 25 mm = 1,5 dB por segmento; 16 / 1,5 = 10,67 -> N = 10
    fr4 = _p(perda_db_por_mm=0.06)
    assert custo.saltos_ate_retemporizar(25.0, "PCIe5", fr4) == 10
    # GDDR7 perde 0,7×: 1,05 dB por segmento -> 15
    assert custo.saltos_ate_retemporizar(25.0, "GDDR7-32", fr4) == 15
    # Megtron 6 0,02 dB/mm: 0,5 dB por segmento -> 32
    assert custo.saltos_ate_retemporizar(25.0, "PCIe5", _p(perda_db_por_mm=0.02)) == 32


def test_retimer_entra_a_cada_n_segmentos():
    fr4 = _p(perda_db_por_mm=0.06)
    dez = custo.percurso([25.0] * 10, "chave", "PCIe5", fr4)
    onze = custo.percurso([25.0] * 11, "chave", "PCIe5", fr4)
    vinte_e_um = custo.percurso([25.0] * 21, "chave", "PCIe5", fr4)
    assert sum(dez["retimers"]) == 0 and dez["trecho_db"] == pytest.approx(15.0)
    assert sum(onze["retimers"]) == 1 and onze["retimers"][10]
    assert sum(vinte_e_um["retimers"]) == 2
    for r in (dez, onze, vinte_e_um):
        assert r["trecho_db"] <= 16.0 + 1e-9
    # o 11º salto custa a chave, o voo e mais o retimer (1,5 ns, 2,0 pJ/bit nos valores fixos)
    assert onze["atraso_ns"] - dez["atraso_ns"] == pytest.approx(0.15 + 25 * 7.0 / 1000 + 1.5)
    assert onze["energia_pj_bit"] == pytest.approx(11 * 0.3 + 2.0)


def test_retimer_aparece_no_atraso_do_fluxo():
    fr4 = _p(perda_db_por_mm=0.06, retemporizacao_ns=5.0, ps_por_mm=6.0)
    m = _malha(colunas=14, linhas=1, tipo="chave", p=fr4)
    r = reservar(m, [Fluxo("longo", (0, 0), (11, 0), 1.0, "PCIe5")]).fluxos[0]
    esperado = 11 * (0.15 + 0.15) + 5.0
    assert r.atraso_ns == pytest.approx(esperado) and r.retemporizacoes == 1
    curto = reservar(m, [Fluxo("c", (0, 0), (10, 0), 1.0, "PCIe5")]).fluxos[0]
    assert curto.retemporizacoes == 0 and curto.atraso_ns == pytest.approx(10 * 0.3)


def test_chave_fecha_o_atraso_que_o_retimer_por_salto_estoura():
    # 4 saltos de 25 mm, GDDR7 (5,0 ns): retransmitindo = 4 × 5,155; por chave = 4 × 0,31
    fl = [Fluxo("g", (0, 0), (3, 1), 1.0, "GDDR7-32")]
    p = PA.carregar()
    rt = MO.avaliar_fluxos(fl, _malha(p=p))
    ch = MO.avaliar_fluxos(fl, _malha(tipo="chave", p=p))
    assert len(rt["fora_do_orcamento"]) == 1 and ch["fora_do_orcamento"] == []
    assert ch["resumo"]["potencia_w"] < rt["resumo"]["potencia_w"]


# ------------------------------------------------------------ 3. perda por trecho (R23)
def test_r23_passa_quando_o_trecho_cabe():
    m = _malha(colunas=14, linhas=1, tipo="chave", p=_p(perda_db_por_mm=0.06))
    av = MO.avaliar_fluxos([Fluxo("ok", (0, 0), (12, 0), 1.0, "PCIe5")], m)
    assert av["fora_da_perda"] == [] and av["resumo"]["trecho_db_max"] <= 16.0
    assert _verificar(av).contagem("R23-malha-perda") == 0


def test_r23_erro_quando_uma_ligacao_so_ja_passa_do_orcamento():
    # expressa de 300 mm em FR4 = 18 dB > 16, e nenhum retimer cabe no meio dela
    p = _p(perda_db_por_mm=0.06)
    m = _malha(colunas=14, linhas=1, tipo="chave", p=p).com_expressa((0, 0), (12, 0))
    av = MO.avaliar_fluxos([Fluxo("longa", (0, 0), (12, 0), 1.0, "PCIe5", expressa=((0, 0), (12, 0)))], m)
    assert av["resumo"]["trecho_db_max"] == pytest.approx(18.0)
    rel = _verificar(av)
    assert rel.contagem("R23-malha-perda") == 1
    (v,) = [v for v in rel.violacoes if v.regra == "R23-malha-perda"]
    assert v.alvo == "longa" and "18.0 dB" in v.mensagem and "16 dB" in v.mensagem


def test_r23_na_gddr7_o_fator_do_pam3_deixa_passar():
    # 250 mm: PCIe 5 a 0,06 dB/mm = 15 dB (cabe); expressa de 300 mm: GDDR7 = 12,6 dB (cabe), PCIe 18 (erro)
    p = _p(perda_db_por_mm=0.06)
    m = _malha(colunas=14, linhas=1, tipo="chave", p=p).com_expressa((0, 0), (12, 0))
    fl = [Fluxo("g", (0, 0), (12, 0), 1.0, "GDDR7-32", expressa=((0, 0), (12, 0))),
          Fluxo("p", (0, 0), (12, 0), 1.0, "PCIe5", expressa=((0, 0), (12, 0)))]
    av = MO.avaliar_fluxos(fl, m)
    assert [d["nome"] for d in av["fora_da_perda"]] == ["p"]


def test_r23_retransmitindo_a_perda_zera_a_cada_salto():
    p = _p(perda_db_por_mm=0.06)
    av = MO.avaliar_fluxos([Fluxo("f", (0, 0), (12, 0), 1.0, "PCIe5")], _malha(14, 1, "retransmite", p))
    assert av["resumo"]["trecho_db_max"] == pytest.approx(1.5) and av["fora_da_perda"] == []


def test_r23_e_r24_estao_em_regras_e_sem_malha_nao_rodam():
    assert "R23-malha-perda" in REGRAS and "R24-malha-skew" in REGRAS
    rel = verificar(Netlist())
    assert rel.contagem("R23-malha-perda") == 0 and rel.contagem("R24-malha-skew") == 0


# ------------------------------------------------------------ 4. desalinhamento (R24)
def _dividido(proto, extra_mm):
    """(0,0)->(1,1) dividido em XY e YX; a ligação (0,0)-(1,0) ganha `extra_mm` de trilha."""
    m = _malha(2, 2, p=_p())
    m = m.com_comprimento(ligacao((0, 0), (1, 0)), 25.0 + extra_mm)
    return MO.avaliar_fluxos([Fluxo("f", (0, 0), (1, 1), 1.0, proto, rota="dividida")], m)


def test_partes_iguais_nao_tem_desalinhamento():
    av = _dividido("GDDR7-32", 0.0)
    assert av["fluxos"][0]["desalinhamento_ps"] == pytest.approx(0.0)
    assert av["fora_do_skew"] == []


def test_r24_passa_dentro_do_limite_da_gddr7():
    # 0,5 mm × 7,0 ps/mm = 3,5 ps <= 4,7 ps (skew_max, o treinável da GDDR7 falta)
    av = _dividido("GDDR7-32", 0.5)
    assert av["fluxos"][0]["desalinhamento_ps"] == pytest.approx(3.5)
    assert av["fluxos"][0]["limite_skew_ps"] == 4.7
    assert _verificar(av).contagem("R24-malha-skew") == 0


def test_r24_erro_acima_do_limite_da_gddr7():
    av = _dividido("GDDR7-32", 1.0)           # 7,0 ps > 4,7 ps
    assert [d["nome"] for d in av["fora_do_skew"]] == ["f"]
    rel = _verificar(av)
    (v,) = [v for v in rel.violacoes if v.regra == "R24-malha-skew"]
    assert "7.0 ps" in v.mensagem and "4.7 ps" in v.mensagem


def test_r24_usa_o_treinavel_quando_existe():
    # DDR5: 7 ps cabem folgados no treinável de 208 ps; PCIe 5 sem treinável usa o skew_max de 9,4 ps
    assert _dividido("DDR5-4800", 1.0)["fora_do_skew"] == []
    assert _dividido("PCIe5", 1.0)["fora_do_skew"] == []          # 7,0 <= 9,4
    assert len(_dividido("PCIe5", 2.0)["fora_do_skew"]) == 1       # 14,0 > 9,4


def test_r24_ddr5_estoura_o_treinavel():
    assert len(_dividido("DDR5-4800", 50.0)["fora_do_skew"]) == 1  # 350 ps > 208 ps


def test_fluxo_de_um_caminho_so_nao_tem_desalinhamento():
    m = _malha(2, 2, p=_p()).com_comprimento(ligacao((0, 0), (1, 0)), 80.0)
    av = MO.avaliar_fluxos([Fluxo("f", (0, 0), (1, 1), 1.0, "GDDR7-32")], m)
    assert av["fluxos"][0]["desalinhamento_ps"] == 0.0 and av["fora_do_skew"] == []


def test_protocolo_sem_limite_nao_e_checado():
    assert _p().limite_skew_ps("AUX") is None
    assert _dividido("AUX", 100.0)["fora_do_skew"] == []


def test_comprimento_invalido():
    with pytest.raises(ValueError):
        _malha().com_comprimento(ligacao((0, 0), (1, 0)), 0.0)
    with pytest.raises(ValueError):
        _malha().com_comprimento(ligacao((0, 0), (2, 2)), 10.0)


# ------------------------------------------------------------ 5. calor
def test_calor_soma_a_potencia_e_reparte_pelos_segmentos():
    m = _malha(3, 1, p=_p())
    r = reservar(m, [Fluxo("f", (0, 0), (2, 0), 2.0)])      # 2 saltos × 2 pJ/bit × 16 Gb/s = 0,064 W
    assert r.potencia_w == pytest.approx(0.064)
    assert sum(r.calor_w.values()) == pytest.approx(r.potencia_w)
    # cada salto 0,032 W: pontas ganham metade, o do meio recebe a metade de cada salto
    assert r.calor_w[(0, 0)] == pytest.approx(0.016)
    assert r.calor_w[(1, 0)] == pytest.approx(0.032)
    assert r.calor_w[(2, 0)] == pytest.approx(0.016)


def test_calor_dividido_passa_pelos_dois_caminhos():
    m = _malha(2, 2, p=_p())
    r = reservar(m, [Fluxo("f", (0, 0), (1, 1), 2.0, rota="dividida")])
    assert sum(r.calor_w.values()) == pytest.approx(r.potencia_w)
    assert set(r.calor_w) == {(0, 0), (1, 0), (0, 1), (1, 1)}


def test_fontes_da_malha_no_formato_do_difusao():
    m = _malha(3, 1, p=_p())
    av = MO.avaliar_fluxos([Fluxo("f", (0, 0), (2, 0), 2.0)], m)
    fontes = CA.fontes_da_malha(av)
    assert len(fontes) == 3
    x, y, w, d, pot = fontes[1]
    assert (x, y, w, d) == (37.5, 12.5, 25.0, 25.0) and pot == pytest.approx(0.032)
    assert sum(f[4] for f in fontes) == pytest.approx(av["resumo"]["potencia_w"])


def test_sem_fluxo_nao_ha_calor():
    av = MO.avaliar_fluxos([], _malha(2, 2, p=_p()))
    assert CA.fontes_da_malha(av) == [] and av["resumo"]["potencia_w"] == 0.0


# ------------------------------------------------------------ lentos (sistema real)
@pytest.fixture(scope="module")
def termico_real(sistema_real):
    from modulos.conexoes.construir import construir
    from modulos.sistema.simular import _contatos
    m, cfg, plano, viavel = sistema_real
    pj = m.projeto
    nl = construir(m, cfg, plano, viavel, posicionamento=pj.get("tradutores", "sob_peca"),
                   chave=pj.get("chave_celula"))
    dist = _contatos(m, cfg, pj.get("chave_celula"), pj.get("cobre_plano_oz", 1))
    return m, cfg, nl, dist, pj.get("placa_fria_h_w_m2k"), pj.get("vias_termicas_fracao", 0.0)


@pytest.mark.lento
def test_sem_malha_a_temperatura_e_a_do_sistema_atual(termico_real):
    from modulos.conexoes import contexto as CX
    m, cfg, nl, dist, placa, vias = termico_real
    a = CX.simular_termico(m, cfg, nl, dist, placa, vias)
    assert CA.temperatura_max(*termico_real) == pytest.approx(float(a.regime.max()))


@pytest.mark.lento
def test_malha_esquenta_a_base(sistema_real, termico_real):
    from modulos.malha import cenarios as CE
    m, cfg, plano, viavel = sistema_real
    sem = CA.temperatura_max(*termico_real)
    atual = CE.atual(plano, m.base)
    chave = CE.salto_chave(plano, m.base)
    t_atual = CA.temperatura_max(*termico_real, av=atual)
    t_chave = CA.temperatura_max(*termico_real, av=chave)
    assert t_atual > sem
    assert sem <= t_chave < t_atual            # a chave dissipa bem menos


@pytest.mark.lento
def test_salto_chave_fecha_o_atraso_no_sistema_real(sistema_real):
    from modulos.malha import cenarios as CE
    m, cfg, plano, viavel = sistema_real
    a, c = CE.atual(plano, m.base), CE.salto_chave(plano, m.base)
    assert a["resumo"]["erros_r21"] > 0 and c["resumo"]["erros_r21"] == 0
    assert c["resumo"]["potencia_w"] < a["resumo"]["potencia_w"]
    assert c["resumo"]["erros_r23"] == 0 and c["resumo"]["erros_r24"] == 0
    assert c["extras"]["chave_n"]["GDDR7-32"] > 0
    comb = CE.combinar(plano, m.base, nome="x", chave=True, expressas=True, largas=True)
    assert comb["resumo"]["erros_r21"] == comb["resumo"]["erros_r22"] == 0
