"""Calor da malha na base: a potência de cada segmento vira fonte da simulação térmica.

A potência de cada ligação (energia por bit × banda) é repartida meio a meio entre os
dois segmentos que ela liga (`Reserva.calor_w`). Cada segmento vira um quadrado de
`passo_mm` de lado em `fontes_extra` de `modulos/termico/difusao.simular`, junto das
fontes que `modulos/conexoes/contexto.py` já monta (tradutores e lasers). Cenário à
parte: `CX.simular_termico` e o sistema atual sem malha não mudam.

Conservador: o calor da malha SOMA ao dos chips tradutores do sistema atual, embora
os dois representem em parte o mesmo trabalho de retransmissão.
"""
from modulos.conexoes import contexto as CX
from modulos.termico import difusao


def fontes_da_malha(av):
    """[(x, y, largura, profundidade, W)] por segmento com calor, no formato de `fontes_extra`."""
    passo = av["malha"].passo_mm
    return [((sx + 0.5) * passo, (sy + 0.5) * passo, passo, passo, w)
            for (sx, sy), w in sorted(av["reserva"].calor_w.items()) if w > 0]


def simular(m, cfg, netlist, dist, placa_fria, vias_termicas=0.0, av=None):
    """Temperatura da base com o calor do sistema atual e, se `av`, o da malha."""
    h = None if placa_fria is None else difusao.h_atraves_da_base(placa_fria, vias_termicas)
    fontes = CX.fontes_calor(netlist) + (fontes_da_malha(av) if av else [])
    return difusao.simular(m.base, cfg, m.zonas, perdas_contatos_w=dist["perdas_w"],
                           fontes_extra=fontes, h_inferior=h)


def temperatura_max(m, cfg, netlist, dist, placa_fria, vias_termicas=0.0, av=None):
    return float(simular(m, cfg, netlist, dist, placa_fria, vias_termicas, av).regime.max())
