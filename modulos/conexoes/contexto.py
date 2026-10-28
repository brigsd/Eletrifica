"""Monta o contexto que o verificador usa além da netlist: temperaturas, contatos, orçamentos.

    t = simular_termico(montagem, configuracao, netlist, dist, placa_fria, vias_termicas)
    ctx = montar(montagem, configuracao, netlist, t, contatos=[dist])
    verificar(netlist, ctx)
"""
import math

import numpy as np

from modulos.termico import difusao

TIPOS_COM_TEMPERATURA = ("chip_tradutor", "laser", "regulador", "celula")
AMOSTRAS_POR_LADO = 5           # grade de amostras na área de cada peça


def fontes_calor(netlist):
    """Calor que a interconexão dissipa na própria base: chips tradutores e lasers."""
    out = []
    for c in netlist.por_tipo("chip_tradutor"):
        p = float(c.atributos.get("potencia_w", 0.0)) + sum(
            float(f.atributos.get("potencia_w", 0.0) or 0.0) for f in netlist.filhos(c.id))
        out.append((c.posicao[0], c.posicao[1], c.atributos["largura_mm"], c.atributos["profundidade_mm"], p))
    for l in netlist.por_tipo("laser"):
        out.append((l.posicao[0], l.posicao[1], 40.0, 25.0, float(l.atributos["potencia_eletrica_w"])))
    return out


def simular_termico(montagem, configuracao, netlist, dist, placa_fria, vias_termicas=0.0):
    """Temperatura da base em regime: perdas nos contatos mais o calor da interconexão."""
    h = None if placa_fria is None else difusao.h_atraves_da_base(placa_fria, vias_termicas)
    return difusao.simular(montagem.base, configuracao, montagem.zonas, perdas_contatos_w=dist["perdas_w"],
                           fontes_extra=fontes_calor(netlist), h_inferior=h)


def _temperatura_peca(termico, pc):
    c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
    w, d = pc.peca.largura / 2, pc.peca.profundidade / 2
    t = []
    for lx in np.linspace(-w, w, AMOSTRAS_POR_LADO):
        for ly in np.linspace(-d, d, AMOSTRAS_POR_LADO):
            t.append(float(termico.temperatura_em(pc.x + c * lx - s * ly, pc.y + s * lx + c * ly)))
    return max(t)


def montar(montagem, configuracao, netlist, termico, contatos=None, **extra):
    """`extra` repassa chaves opcionais, ex. orcamento_trilha_db, atraso_max_ps, meta_pj_bit."""
    temperaturas = {}
    for pc in configuracao.pecas:
        temperaturas[pc.nome] = _temperatura_peca(termico, pc)
    for b in netlist.blocos.values():
        if b.tipo in TIPOS_COM_TEMPERATURA and b.posicao is not None:
            temperaturas[b.id] = float(termico.temperatura_em(float(b.posicao[0]), float(b.posicao[1])))
    ctx = {
        "temperaturas": temperaturas,
        "tipos_pecas": {pc.nome: pc.tipo for pc in configuracao.pecas},
        "t_min_c": float(termico.t_amb),
        "t_base_max_c": float(np.max(termico.regime)),
    }
    if contatos:
        ctx["contatos"] = list(contatos)
    ctx.update({k: v for k, v in extra.items() if v is not None})
    return ctx
