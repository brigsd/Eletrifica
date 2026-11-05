"""Atraso, energia e perda de um caminho.

Dois tipos de salto (`Malha.tipo_salto`):

- `retransmite`: cada salto passa por um tradutor que retemporiza (atraso e energia
  de retimer) mais o voo do sinal pelo cobre do passo. A perda zera a cada salto.
- `chave`: o salto só desvia o sinal por chave analógica (atraso e energia pequenos,
  ESTIMATIVAS sem fonte). A perda do cobre se acumula; um retimer obrigatório entra
  quando a perda acumulada passaria do orçamento por trecho (`orcamento_perda_trecho_db`).

Os valores vêm de `parametros.carregar()` (malha.json); `p=` troca por outros, para
os testes. `conferir_orcamento` compara o atraso de IDA com o orçamento de ida.
"""
import math

from modulos.malha import parametros

RETEMPORIZACAO_NS = parametros.FALLBACK.retemporizacao_ns     # fallback (estimativa)
PS_POR_MM = parametros.FALLBACK.ps_por_mm
PJ_POR_BIT_SALTO = parametros.FALLBACK.pj_por_bit_salto

TIPOS_SALTO = ("retransmite", "chave")


def _p(p):
    return p if p is not None else parametros.carregar()


def atraso_salto_ns(passo_mm, p=None):
    p = _p(p)
    return p.retemporizacao_ns + passo_mm * p.ps_por_mm / 1000.0


def atraso_ligacao_ns(comprimento_mm, p=None):
    """Atraso de UM salto por uma ligação de `comprimento_mm` (retemporização + a distância)."""
    p = _p(p)
    return p.retemporizacao_ns + comprimento_mm * p.ps_por_mm / 1000.0


def atraso_caminho_ns(saltos, passo_mm, p=None):
    """Atraso determinístico de um caminho de `saltos` ligações, em ns."""
    return saltos * atraso_salto_ns(passo_mm, p)


def energia_pj_por_bit(saltos, p=None):
    return saltos * _p(p).pj_por_bit_salto


def conferir_orcamento(atraso_ns, orcamento_ns):
    """Devolve (cabe, folga_ns). `atraso_ns` e `orcamento_ns` são ambos de IDA."""
    folga = orcamento_ns - atraso_ns
    return folga >= 0, folga


def perda_db(comprimento_mm, protocolo="", p=None):
    """Perda do cobre em dB numa distância (dB/mm do material, fator da GDDR7 PAM3)."""
    return comprimento_mm * _p(p).perda_db_mm(protocolo)


def saltos_ate_retemporizar(passo_mm, protocolo="", p=None):
    """N: quantos segmentos de `passo_mm` cabem no orçamento de perda antes do retimer."""
    p = _p(p)
    por_segmento = passo_mm * p.perda_db_mm(protocolo)
    if por_segmento <= 0:
        return math.inf
    return int(math.floor(p.orcamento_perda_trecho_db / por_segmento + 1e-9))


def percurso(comprimentos_mm, tipo="retransmite", protocolo="", p=None):
    """Custo de um caminho dado o comprimento de cada ligação, em ordem.

    Devolve dict: atraso_ns, energia_pj_bit, pj_por_ligacao (energia atribuída a cada
    ligação, inclusive o retimer que entra antes dela), retimers (por ligação: True se
    entra um retimer antes dela), trecho_db (maior perda acumulada entre retemporizações).
    """
    p = _p(p)
    if tipo not in TIPOS_SALTO:
        raise ValueError(f"tipo de salto desconhecido: {tipo!r}")
    atraso, pjs, rets, trecho_max, acc = 0.0, [], [], 0.0, 0.0
    for c in comprimentos_mm:
        voo = c * p.ps_por_mm / 1000.0
        perda = perda_db(c, protocolo, p)
        if tipo == "retransmite":
            atraso += p.retemporizacao_ns + voo
            pjs.append(p.pj_por_bit_salto)
            rets.append(True)
            trecho_max = max(trecho_max, perda)
            continue
        ret = acc > 0 and acc + perda > p.orcamento_perda_trecho_db + 1e-9
        if ret:
            acc = 0.0
            atraso += p.retemporizacao_ns
        acc += perda
        trecho_max = max(trecho_max, acc)
        atraso += p.salto_chave_ns + voo
        pjs.append(p.salto_chave_pj_por_bit + (p.pj_por_bit_salto if ret else 0.0))
        rets.append(ret)
    return {"atraso_ns": atraso, "energia_pj_bit": sum(pjs), "pj_por_ligacao": pjs,
            "retimers": rets, "trecho_db": trecho_max}
