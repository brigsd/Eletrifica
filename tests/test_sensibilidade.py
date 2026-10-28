import pytest

from modulos.conexoes import construir as K
from modulos.conexoes.sensibilidade import tabela_md, varrer


def test_parametros_valem_so_na_chamada(sistema_real):
    m, cfg, plano, opt = sistema_real
    antes = K.VIAS_MAX
    poucas = K.construir(m, cfg, plano, opt, chave="rele_mems", posicionamento="sob_peca",
                         parametros={"VIAS_MAX": 80})
    assert K.VIAS_MAX == antes
    normal = K.construir(m, cfg, plano, opt, chave="rele_mems", posicionamento="sob_peca")
    n_chips = lambda nl: len(nl.por_tipo("chip_tradutor"))
    assert n_chips(poucas) > n_chips(normal)
    assert all(c.atributos["vias_max"] == antes for c in normal.por_tipo("chip_tradutor"))


def test_parametro_desconhecido_e_recusado(sistema_real):
    m, cfg, plano, opt = sistema_real
    with pytest.raises(KeyError):
        K.construir(m, cfg, plano, opt, parametros={"NAO_EXISTE": 1})
    assert K.VIAS_MAX == 96


@pytest.mark.lento
def test_acha_limites_e_o_projeto_atual_esta_dentro(sistema_real):
    r = varrer(sistema_real, {"perdas passivas (dB)", "perda da trilha (dB/mm/GHz)"})
    assert r["erros_nominais"] == {}
    por_nome = {l["parametro"]: l for l in r["linhas"]}
    for nome in ("perdas passivas (dB)", "perda da trilha (dB/mm/GHz)"):
        l = por_nome[nome]
        assert l["fator"] is not None and l["fator"] > 1.0, l
        assert l["regra_que_quebra"]
    assert "| perdas passivas (dB) |" in tabela_md(r)
