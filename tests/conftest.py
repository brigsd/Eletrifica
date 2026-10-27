import pytest


@pytest.fixture(scope="session")
def sistema_real():
    """Montagem, configuração (mapeamento real, ~15 s) e plano óptico, uma vez por sessão."""
    from modulos.dados import roteamento as DR
    from modulos.optica import enlace as E
    from modulos.sistema import base as B, configuracao as C, mapeamento as M

    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, s), s)
    viavel = E.carregar("viavel")
    plano = DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"])
    return m, cfg, plano, viavel


@pytest.fixture(scope="session")
def netlist_real(sistema_real):
    from modulos.conexoes.construir import construir

    m, cfg, plano, viavel = sistema_real
    return construir(m, cfg, plano, viavel, posicionamento="sob_peca", chave="rele_mems")
