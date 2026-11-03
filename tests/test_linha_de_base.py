import pytest

from modulos.conexoes.verificador import REGRAS
from modulos.sistema import linha_de_base as LB


@pytest.mark.lento
def test_tabela_da_linha_de_base():
    R = LB.calcular()
    t = LB.tabela(R)
    for rotulo in ("Erros do verificador", "Avisos do verificador", "Boot emulado ficou pronto",
                   "Tempo do boot emulado", "Consumo da interconexão", "Energia por bit",
                   "Temperatura máxima da base", "Teto do LLM 70B em 4 bits",
                   "Teto do mesmo LLM, PC comum", "Capacidade do banco unificado",
                   "Banda do banco para a GPU", "Banda do banco para a CPU"):
        assert rotulo in t, rotulo
    for r in REGRAS:
        assert f"| {r} |" in t, r
    assert R["verificador"]["erros"] == 0
    assert R["boot"]["ok"]
    assert R["llm"]["banco_tok_s"] > R["llm"]["comum_tok_s"]
