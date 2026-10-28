import copy

import numpy as np
import pytest

from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M


def _mapear(montagem):
    contatos = B.calcular_contatos(montagem.base, montagem.colocacoes)
    sond = M.sondar(montagem, contatos)
    return contatos, sond, M.identificar(montagem.base, sond)


@pytest.fixture(scope="module")
def mapeado():
    m = B.carregar()
    return (m, *_mapear(m))


def test_identifica_todas_as_pecas(mapeado):
    m, _, _, ids = mapeado
    linhas = M.conferir(m, ids)
    assert len(linhas) == len(m.colocacoes)
    for l in linhas:
        assert l["tipo_achado"] == l["tipo_real"], l
        assert l["erro_mm"] < 0.05, l
        assert abs(l["erro_graus"]) < 0.5, l


def test_cada_celula_vai_para_o_pino_certo(mapeado):
    m, contatos, _, ids = mapeado
    verdade = {int(c): (m.colocacoes[k].tipo, int(i))
               for c, k, i in zip(contatos.celula, contatos.peca, contatos.pino)}
    erradas = sum(verdade[int(c)] != (ident.tipo, int(p))
                  for ident in ids for c, p in zip(ident.celulas, ident.pino) if p >= 0)
    assert erradas == 0


def test_sondagem_nao_vaza_nomes(mapeado):
    _, _, sond, _ = mapeado
    assert set(sond.assinatura.values()) <= {"referencia", "capacitivo", "diodo"}
    assert all(isinstance(g, int) for g in sond.assinatura)


def test_configuracao_so_liga_celulas_identificadas(mapeado):
    m, _, sond, ids = mapeado
    cfg = C.configurar(m.base, ids, sond)
    assert {p.nome for p in cfg.pecas} >= {"CPU", "GPU", "FPGA", "PCH", "DIMM", "PONTE", "MEM0", "MEM23"}
    ligadas = cfg.funcao > 0
    assert (cfg.peca[ligadas] >= 0).all()
    cpu = cfg.por_nome("CPU")
    assert len(cpu.celulas_do_pino) == 1700


@pytest.mark.parametrize("pid,graus", [("CPU", 37.0), ("CPU", 133.0), ("M3", 63.5), ("PCH", 301.0)])
def test_identifica_em_qualquer_giro(pid, graus):
    m = copy.deepcopy(B.carregar())
    col = m.por_id(pid)
    col.rot = graus
    m.colocacoes = [col]
    _, _, ids = _mapear(m)
    l = M.conferir(m, ids)[0]
    assert l["tipo_achado"] == l["tipo_real"]
    assert l["erro_mm"] < 0.05 and abs(l["erro_graus"]) < 0.5


def test_trocar_pecas_de_lugar_e_reiniciar():
    m = B.carregar()
    m2 = copy.deepcopy(m)
    cpu, gpu = m2.por_id("CPU"), m2.por_id("GPU")
    cpu.x, cpu.y, cpu.rot = 125.0, 135.0, 91.3
    gpu.rot = 2.0
    m2.colocacoes = [cpu, gpu, m2.por_id("FPGA")]
    _, _, ids = _mapear(m2)
    for l in M.conferir(m2, ids):
        assert l["tipo_achado"] == l["tipo_real"]
        assert l["erro_mm"] < 0.05 and abs(l["erro_graus"]) < 0.5
