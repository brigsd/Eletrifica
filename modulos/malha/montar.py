"""Liga a malha ao sistema real: segmentos sobre a base, fluxos do plano e avaliação.

Cada enlace do plano de roteamento vira um fluxo entre os segmentos onde estão
os seus tradutores; a banda do fluxo é a soma das taxas dos canais do enlace.
`avaliar` reserva tudo na malha e confere o atraso de cada fluxo contra o
orçamento do seu protocolo. Os números de MALHA_* e ORCAMENTO_NS são ESTIMATIVAS.
"""
import math

from modulos.malha import parametros
from modulos.malha.topologia import Malha
from modulos.malha.trafego import Fluxo, reservar

# Fallback (só se o malha.json faltar); o valor de verdade vem de `parametros.carregar()`.
MALHA_PASSO_MM = parametros.FALLBACK.passo_mm
MALHA_FAIXAS = parametros.FALLBACK.faixas_por_ligacao
MALHA_GBPS_POR_FAIXA = parametros.FALLBACK.gbps_por_faixa
ORCAMENTO_NS = dict(parametros.FALLBACK.orcamento_ns)
ORCAMENTO_PADRAO_NS = parametros.FALLBACK.orcamento_ns_padrao


def orcamento_ns(protocolo, params=None):
    """Atraso extra de IDA que o protocolo aceita (ns). Compare com o atraso de ida do fluxo."""
    return (params or parametros.carregar()).orcamento(protocolo)


def malha_da_base(base, passo_mm=None, faixas=None, gbps=None, params=None, tipo_salto="retransmite"):
    """Malha de segmentos que cobre a área inteira da base (arredonda para cima).

    Passo, faixas (por sentido) e taxa vêm de `params` (padrão: malha.json). A capacidade
    de uma ligação é faixas × taxa: o pior caso é o fluxo inteiro num só sentido.
    """
    p = params or parametros.carregar()
    passo_mm = p.passo_mm if passo_mm is None else passo_mm
    faixas = p.faixas_por_ligacao if faixas is None else faixas
    gbps = p.gbps_por_faixa if gbps is None else gbps
    colunas = max(1, math.ceil(base.largura / passo_mm - 1e-9))
    linhas = max(1, math.ceil(base.profundidade / passo_mm - 1e-9))
    return Malha(colunas=colunas, linhas=linhas, passo_mm=passo_mm,
                 faixas_por_ligacao=faixas, gbps_por_faixa=gbps,
                 tipo_salto=tipo_salto, params=p)


def segmento_de(malha, ponto):
    """Segmento (x, y) que contém um ponto da base, em mm."""
    x, y = ponto
    seg = (int(x // malha.passo_mm), int(y // malha.passo_mm))
    if not malha.contem(seg):
        raise ValueError(f"ponto {ponto} mm fora da malha {malha.colunas}x{malha.linhas}")
    return seg


def fluxos_do_plano(plano, malha):
    """Um fluxo por enlace: origem e destino são os segmentos dos tradutores."""
    fluxos = []
    for e in plano.enlaces:
        gbps = sum(plano.canais[i].taxa_gbps for i in e.canais)
        fluxos.append(Fluxo(
            nome=e.id,
            origem=segmento_de(malha, e.tradutor_a),
            destino=segmento_de(malha, e.tradutor_b),
            gbs=gbps / 8,            # Gb/s -> GB/s
            protocolo=e.protocolo,
        ))
    return fluxos


def avaliar(plano, base, malha=None, params=None):
    """Reserva os fluxos do plano na malha e devolve reserva, atrasos e resumo.

    `fora_do_orcamento` lista os fluxos cujo atraso passa do orçamento do protocolo;
    `acima_de_100` lista as ligações com ocupação acima da capacidade; `fora_da_perda`
    os fluxos com trecho acima do orçamento de perda; `fora_do_skew` os com
    desalinhamento acima do limite. São as entradas das regras R21 a R24.
    """
    malha = malha or malha_da_base(base, params=params)
    return avaliar_fluxos(fluxos_do_plano(plano, malha), malha)


def avaliar_fluxos(fluxos, malha):
    """Como `avaliar`, mas com os fluxos já montados (cenários alternativos)."""
    reserva = reservar(malha, fluxos)
    p = malha.params or parametros.carregar()

    detalhes = []
    for f, r in zip(fluxos, reserva.fluxos):
        orc = p.orcamento(f.protocolo)          # atraso extra de ida, como `r.atraso_ns`
        lim = p.limite_skew_ps(f.protocolo)
        detalhes.append({
            "nome": f.nome,
            "protocolo": f.protocolo,
            "saltos": r.saltos,
            "atraso_ns": r.atraso_ns,
            "orcamento_ns": orc,
            "folga_ns": orc - r.atraso_ns,
            "trecho_db": r.trecho_db,
            "orcamento_perda_db": p.orcamento_perda_trecho_db,
            "retemporizacoes": r.retemporizacoes,
            "desalinhamento_ps": r.desalinhamento_ps,
            "limite_skew_ps": lim,
        })
    fora = [d for d in detalhes if d["folga_ns"] < 0]
    fora_perda = [d for d in detalhes if d["trecho_db"] > d["orcamento_perda_db"] + 1e-9]
    fora_skew = [d for d in detalhes
                 if d["limite_skew_ps"] is not None and d["desalinhamento_ps"] > d["limite_skew_ps"] + 1e-9]
    ocupacoes = list(reserva.ocupacao.values())
    resumo = {
        "saltos_max": max((d["saltos"] for d in detalhes), default=0),
        "atraso_max_ns": max((d["atraso_ns"] for d in detalhes), default=0.0),
        "potencia_w": reserva.potencia_w,
        "ocupacao_max": max(ocupacoes, default=0.0),
        "trecho_db_max": max((d["trecho_db"] for d in detalhes), default=0.0),
        "retemporizacoes_max": max((d["retemporizacoes"] for d in detalhes), default=0),
        "desalinhamento_max_ps": max((d["desalinhamento_ps"] for d in detalhes), default=0.0),
    }
    return {
        "malha": malha,
        "reserva": reserva,
        "fluxos": detalhes,
        "fora_do_orcamento": fora,
        "acima_de_100": reserva.acima_de_100,
        "fora_da_perda": fora_perda,
        "fora_do_skew": fora_skew,
        "resumo": resumo,
    }
