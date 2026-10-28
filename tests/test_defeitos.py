import copy

import numpy as np
import pytest

from modulos.componentes import ENERGIA
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import defeitos as D
from modulos.sistema import mapeamento as M
from modulos.sistema.base import DESLIGADA


def _so(*ids):
    m0 = B.carregar()
    m = copy.deepcopy(m0)
    m.colocacoes = [m0.por_id(i) for i in ids]
    return m


def _rodar(m, contatos=None, curtos=()):
    ct = contatos if contatos is not None else B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct, curtos=curtos)
    ids = M.identificar(m.base, s)
    return ids, C.configurar(m.base, ids, s)


def _peca(cfg, nome):
    return next(p for p in cfg.pecas + cfg.recusadas if p.nome == nome)


def _nada_ligado(cfg, pc):
    cels = [c for cs in pc.celulas_do_pino.values() for c in cs]
    return (cfg.funcao.ravel()[cels] == DESLIGADA).all()


@pytest.fixture(scope="module")
def cpu():
    m = _so("CPU")
    return m, B.calcular_contatos(m.base, m.colocacoes)


@pytest.mark.lento
def test_nominal_ok(cpu):
    m, ct = cpu
    _, cfg = _rodar(m, ct)
    assert _peca(cfg, "CPU").avaliacao["veredito"] == "ok"
    assert not cfg.recusadas and not cfg.desconhecidas


@pytest.mark.lento
def test_perder_poucos_pinos_de_vccin_degrada(cpu):
    m, ct = cpu
    c2, perdidos = D.sem_contato(m, ct, "CPU", 0.05, funcao=ENERGIA, grupo="VCCIN")
    _, cfg = _rodar(m, c2)
    pc = cfg.por_nome("CPU")
    assert pc.avaliacao["veredito"] == "degradado"
    assert sorted(pc.pinos_sem_contato) == sorted(perdidos.tolist())


@pytest.mark.lento
def test_perder_muitos_pinos_de_vccin_recusa_e_nao_energiza(cpu):
    m, ct = cpu
    c2, _ = D.sem_contato(m, ct, "CPU", 0.20, funcao=ENERGIA, grupo="VCCIN")
    _, cfg = _rodar(m, c2)
    pc = _peca(cfg, "CPU")
    assert pc in cfg.recusadas
    assert any("energia sem folga: VCCIN" in x for x in pc.avaliacao["motivos"])
    assert _nada_ligado(cfg, pc)


@pytest.mark.lento
def test_sinal_sem_contato_recusa(cpu):
    m, ct = cpu
    j = next(i for i, p in enumerate(m.colocacoes[0].peca.pinos) if p.nome == "PWROK")
    _, cfg = _rodar(m, D.tirar_pinos(ct, 0, [j]))
    pc = _peca(cfg, "CPU")
    assert pc.avaliacao["sinais_sem_contato"] == {"AUX": ["PWROK"]}


@pytest.mark.lento
def test_inclinacao_pequena_nao_perde_contato(cpu):
    m, ct = cpu
    c2, perdidos = D.inclinar(m, ct, "CPU", 0.1)
    assert len(perdidos) == 0
    assert _peca(_rodar(m, c2)[1], "CPU").avaliacao["veredito"] == "ok"


@pytest.mark.lento
def test_canto_levantado_identifica_e_recusa(cpu):
    m, ct = cpu
    c2, perdidos = D.inclinar(m, ct, "CPU", 0.5)
    ids, cfg = _rodar(m, c2)
    assert [i.tipo for i in ids] == ["i5-13600KF"]
    pc = _peca(cfg, "CPU")
    assert sorted(pc.pinos_sem_contato) == sorted(perdidos.tolist())
    assert pc.avaliacao["veredito"] == "recusada"


@pytest.mark.lento
def test_particula_entre_sinal_e_terra(cpu):
    m, ct = cpu
    c2, curtos = D.particula(m.base, m, ct, "CPU", 1)
    _, cfg = _rodar(m, c2, curtos)
    pc = _peca(cfg, "CPU")
    assert pc in cfg.recusadas
    assert [p["tipo"] for p in pc.pontes] == ["curto"]
    assert any(net == "VSS" for _, net in pc.pontes[0]["redes"])


@pytest.mark.lento
def test_pino_torto(cpu):
    m, ct = cpu
    _, cfg = _rodar(m, D.entortar_pino(m.base, m, ct, "CPU", 300, 0.1, 0.0))
    assert _peca(cfg, "CPU").avaliacao["veredito"] == "ok"
    _, cfg = _rodar(m, D.entortar_pino(m.base, m, ct, "CPU", 300, 0.45, 0.0))
    pc = _peca(cfg, "CPU")
    assert pc in cfg.recusadas and pc.pontes[0]["tipo"] == "fora_do_lugar"


@pytest.mark.lento
def test_peca_fora_do_catalogo_nao_energiza(cpu):
    m, _ = cpu
    m2 = D.peca_estranha(m, 60.0, 60.0)
    ids, cfg = _rodar(m2)
    assert sorted(i.tipo for i in ids) == ["desconhecida", "i5-13600KF"]
    assert len(cfg.desconhecidas) == 1 and cfg.por_nome("CPU")
    estranha = next(i for i in ids if i.tipo == "desconhecida")
    assert (cfg.funcao.ravel()[estranha.celulas] == DESLIGADA).all()


@pytest.mark.lento
def test_peca_parcialmente_fora_da_base(cpu):
    m, _ = cpu
    m2 = D.deslocar(m, "CPU", x=15.0)
    ct = B.calcular_contatos(m2.base, m2.colocacoes)
    verdade = len(m2.colocacoes[0].peca.pinos) - len(set(ct.pino.tolist()))
    ids, cfg = _rodar(m2, ct)
    assert [i.tipo for i in ids] == ["i5-13600KF"]
    assert abs(ids[0].x - 15.0) < 0.05
    assert len(_peca(cfg, "CPU").pinos_sem_contato) == verdade
    assert _peca(cfg, "CPU") in cfg.recusadas


def test_corpos_encostados_nao_fazem_ponte():
    m = D.encostar(_so("M0", "M3"), "M0", "M3", folga_corpo_mm=0.0)
    _, cfg = _rodar(m)
    assert [p.avaliacao["veredito"] for p in cfg.pecas] == ["ok", "ok"]


def test_pinos_a_menos_de_uma_celula_fazem_ponte_entre_pecas():
    m = D.encostar(_so("M0", "M3"), "M0", "M3", distancia_pinos_mm=0.45)
    ids, cfg = _rodar(m)
    assert sorted(i.tipo for i in ids) == ["GDDR7", "GDDR7"]
    assert len(cfg.recusadas) == 2
    redes = {peca for p in cfg.recusadas for pt in p.pontes for peca, _ in pt["redes"]}
    assert redes == {"MEM0", "MEM1"}
