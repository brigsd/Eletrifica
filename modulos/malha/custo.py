"""Atraso e energia de um caminho, por salto.

Cada salto é um segmento que retransmite: atraso do tradutor (retemporização)
mais o voo do sinal pelo cobre do passo. A energia é por bit e cresce com o
número de saltos.

Os três valores abaixo são ESTIMATIVAS, não medidas:
"""
# Estimativas, a confirmar com medida ou datasheet:
RETEMPORIZACAO_NS = 1.5        # ns por salto no tradutor de cada segmento (estimativa)
PS_POR_MM = 7.0                # ps por mm de cobre em FR4 (estimativa de velocidade de propagação)
PJ_POR_BIT_SALTO = 2.0         # pJ por bit em cada salto (estimativa)


def atraso_salto_ns(passo_mm):
    return RETEMPORIZACAO_NS + passo_mm * PS_POR_MM / 1000.0


def atraso_caminho_ns(saltos, passo_mm):
    """Atraso determinístico de um caminho de `saltos` ligações, em ns."""
    return saltos * atraso_salto_ns(passo_mm)


def energia_pj_por_bit(saltos):
    return saltos * PJ_POR_BIT_SALTO


def conferir_orcamento(atraso_ns, orcamento_ns):
    """Devolve (cabe, folga_ns). Folga negativa quando o atraso estoura o orçamento."""
    folga = orcamento_ns - atraso_ns
    return folga >= 0, folga
