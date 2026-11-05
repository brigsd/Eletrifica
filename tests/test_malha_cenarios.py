"""Alternativas da malha: expressas, capacidade por ligação, rotas espalhadas, memória colada."""
import pytest

from modulos.malha import cenarios as CE
from modulos.malha import custo
from modulos.malha.parametros import FALLBACK as FIXOS
from modulos.malha.rota import caminhos, rota_com_expressa, rota_yx
from modulos.malha.topologia import Malha, ligacao
from modulos.malha.trafego import Fluxo, reservar


@pytest.fixture
def m():
    # 6x6, capacidade padrão 2 GB/s por ligação, passo 10 mm
    return Malha(colunas=6, linhas=6, passo_mm=10.0, faixas_por_ligacao=1, gbps_por_faixa=16.0, params=FIXOS)


# ----------------------------------------------------------- rápidos
def test_rota_yx_anda_primeiro_y(m):
    ligs, n = rota_yx(m, (0, 0), (2, 2))
    assert n == 4 and ligs[0] == ligacao((0, 0), (0, 1))


def test_dividida_tem_mesmos_saltos_e_soma_um(m):
    partes = caminhos(m, (0, 0), (3, 2), "dividida")
    assert len(partes) == 2
    assert len(partes[0][0]) == len(partes[1][0]) == 5
    assert sum(f for _, f in partes) == pytest.approx(1.0)
    assert partes[0][0] != partes[1][0]


def test_dividida_na_mesma_linha_e_caminho_unico(m):
    assert len(caminhos(m, (0, 0), (4, 0), "dividida")) == 1


def test_dividir_o_fluxo_divide_a_carga_e_mantem_o_atraso(m):
    xy = reservar(m, [Fluxo("f", (0, 0), (3, 3), 2.0)])
    dv = reservar(m, [Fluxo("f", (0, 0), (3, 3), 2.0, rota="dividida")])
    assert xy.fluxos[0].saltos == dv.fluxos[0].saltos == 6
    assert xy.fluxos[0].atraso_ns == pytest.approx(dv.fluxos[0].atraso_ns)
    assert max(xy.ocupacao.values()) == pytest.approx(1.0)
    assert max(dv.ocupacao.values()) == pytest.approx(0.5)
    assert dv.potencia_w == pytest.approx(xy.potencia_w)


def test_capacidade_por_ligacao_e_override(m):
    lig = ligacao((0, 0), (1, 0))
    m2 = m.com_capacidade(lig, 8.0)
    assert m2.capacidade_gbs(lig) == 8.0
    assert m.capacidade_gbs(lig) == 2.0                    # a original não muda
    assert m2.capacidade_gbs(ligacao((1, 0), (2, 0))) == 2.0
    r = reservar(m2, [Fluxo("f", (0, 0), (1, 0), 4.0)])
    assert r.ocupacao[lig] == pytest.approx(0.5) and r.cabe
    with pytest.raises(ValueError):
        m.com_capacidade(ligacao((0, 0), (2, 2)), 1.0)


def test_expressa_e_um_salto_com_atraso_da_distancia(m):
    me = m.com_expressa((0, 0), (5, 0), gbs=10.0)
    r = reservar(me, [Fluxo("f", (0, 0), (5, 0), 4.0, expressa=((0, 0), (5, 0)))])
    (res,) = r.fluxos
    assert res.saltos == 1
    assert res.atraso_ns == pytest.approx(custo.atraso_ligacao_ns(50.0, FIXOS))
    # o caminho comum teria 5 saltos
    comum = reservar(m, [Fluxo("f", (0, 0), (5, 0), 4.0)]).fluxos[0]
    assert res.atraso_ns < comum.atraso_ns
    assert r.ocupacao[ligacao((0, 0), (5, 0))] == pytest.approx(0.4)
    assert res.energia_pj_bit == custo.energia_pj_por_bit(1, FIXOS)


def test_expressa_sem_fluxo_marcado_nao_e_usada(m):
    me = m.com_expressa((0, 0), (5, 0))
    r = reservar(me, [Fluxo("f", (0, 0), (5, 0), 1.0)])
    assert r.fluxos[0].saltos == 5
    assert r.ocupacao[ligacao((0, 0), (5, 0))] == 0.0


def test_expressa_entre_pontos_quaisquer_com_acesso_pelas_pontas(m):
    me = m.com_expressa((1, 1), (4, 4))
    partes = rota_com_expressa(me, (0, 1), (4, 5), ((4, 4), (1, 1)))
    (ligs, frac), = partes
    assert frac == 1.0
    assert ligs[0] == ligacao((0, 1), (1, 1))               # entra pela ponta mais perto
    assert ligacao((1, 1), (4, 4)) in ligs and len(ligs) == 3


def test_expressa_invalida(m):
    with pytest.raises(ValueError):
        m.com_expressa((0, 0), (1, 0))                       # vizinhos
    with pytest.raises(ValueError):
        m.com_expressa((0, 0), (9, 9))                       # fora
    with pytest.raises(ValueError):
        rota_com_expressa(m, (0, 0), (3, 3), ((0, 0), (3, 3)))   # não existe


def test_api_antiga_inalterada(m):
    r = reservar(m, [Fluxo("f", (0, 0), (2, 1), 1.0)])
    assert r.fluxos[0].saltos == 3
    assert r.fluxos[0].atraso_ns == pytest.approx(custo.atraso_caminho_ns(3, 10.0, FIXOS))
    assert len(m.ligacoes()) == len(m.todas_ligacoes())


# ----------------------------------------------------------- lentos (configuração real)
@pytest.fixture(scope="module")
def real(sistema_real):
    m, cfg, plano, viavel = sistema_real
    return plano, m.base


@pytest.mark.lento
def test_atual_reproduz_avaliar(real):
    from modulos.malha import montar as MO
    plano, base = real
    a = MO.avaliar(plano, base)
    c = CE.atual(plano, base)
    assert c["resumo"]["saltos_max"] == a["resumo"]["saltos_max"]
    assert c["resumo"]["ocupacao_max"] == pytest.approx(a["resumo"]["ocupacao_max"])
    assert c["resumo"]["erros_r21"] == len(a["fora_do_orcamento"])
    assert c["resumo"]["erros_r22"] == len(a["acima_de_100"])


@pytest.mark.lento
def test_fibra_gigante_corta_saltos_e_atraso(real):
    plano, base = real
    a, f = CE.atual(plano, base), CE.fibra_gigante(plano, base)
    assert f["resumo"]["saltos_max"] == 1
    assert f["resumo"]["atraso_max_ns"] < a["resumo"]["atraso_max_ns"]
    # com a retemporização real (5 ns), até 1 salto estoura os 5 ns da GDDR7: só o salto por chave fecha
    assert 0 < f["resumo"]["erros_r21"] <= a["resumo"]["erros_r21"]
    assert f["extras"]["expressas"] > 0
    fixa = CE.combinar(plano, base, nome="x", expressas=True, params=FIXOS)     # custos antigos
    assert fixa["resumo"]["erros_r21"] == 0


@pytest.mark.lento
def test_ligacoes_largas_zeram_r22_sem_mexer_no_atraso(real):
    plano, base = real
    a, g = CE.atual(plano, base), CE.ligacoes_largas(plano, base)
    assert g["resumo"]["erros_r22"] == 0 and g["resumo"]["ocupacao_max"] <= 1.0
    assert g["resumo"]["atraso_max_ns"] == pytest.approx(a["resumo"]["atraso_max_ns"])
    assert g["extras"]["ligacoes_largas"] == a["resumo"]["erros_r22"]


@pytest.mark.lento
def test_peca_grande_reduz_saltos_da_gpu(real):
    plano, base = real
    a, g = CE.atual(plano, base), CE.ligacoes_largas(plano, base, peca_grande=True)
    assert g["extras"]["gpu_mem_saltos_max"] <= a["extras"]["gpu_mem_saltos_max"]
    assert g["resumo"]["potencia_w"] <= a["resumo"]["potencia_w"]


@pytest.mark.lento
def test_rotas_espalhadas_mantem_saltos_e_baixam_a_ocupacao(real):
    plano, base = real
    a, e = CE.atual(plano, base), CE.rotas_espalhadas(plano, base)
    assert e["resumo"]["saltos_max"] == a["resumo"]["saltos_max"]
    assert e["resumo"]["atraso_max_ns"] == pytest.approx(a["resumo"]["atraso_max_ns"])
    assert e["resumo"]["potencia_w"] == pytest.approx(a["resumo"]["potencia_w"])
    assert e["resumo"]["ocupacao_max"] < a["resumo"]["ocupacao_max"]


@pytest.mark.lento
def test_memoria_colada_tem_um_salto_para_a_gpu(real):
    plano, base = real
    c = CE.memoria_colada(plano, base)
    assert c["extras"]["gpu_mem_saltos_max"] == 1
    gpu = [d for d in c["fluxos"] if d["nome"].startswith("GPU-MEM")]
    assert gpu and all(d["saltos"] == 1 for d in gpu)
    # 1 salto = 5 ns de retimer + 25 mm de cobre: um pouco acima dos 5,0 ns da GDDR7
    assert all(d["atraso_ns"] == pytest.approx(5.0 + 25 * 6.2 / 1000) and d["folga_ns"] < 0 for d in gpu)


@pytest.mark.lento
def test_combinacao_fecha_r21_e_r22(real):
    plano, base = real
    r = CE.combinar(plano, base, nome="x", expressas=True, largas=True, params=FIXOS)
    assert r["resumo"]["erros_r21"] == 0 and r["resumo"]["erros_r22"] == 0
    real = CE.combinar(plano, base, nome="y", expressas=True, largas=True)       # malha.json
    assert real["resumo"]["erros_r22"] == 0 and real["resumo"]["erros_r21"] > 0


@pytest.mark.lento
def test_todos_devolve_o_resumo_do_avaliar(real):
    plano, base = real
    for r in CE.todos(plano, base):
        for k in ("saltos_max", "atraso_max_ns", "potencia_w", "ocupacao_max", "erros_r21", "erros_r22",
                  "erros_r23", "erros_r24", "trecho_db_max", "desalinhamento_max_ps"):
            assert k in r["resumo"]
        assert r["resumo"]["erros_r21"] == len(r["fora_do_orcamento"])
        assert r["resumo"]["erros_r22"] == len(r["acima_de_100"])
        assert r["resumo"]["erros_r23"] == len(r["fora_da_perda"])
        assert r["resumo"]["erros_r24"] == len(r["fora_do_skew"])
