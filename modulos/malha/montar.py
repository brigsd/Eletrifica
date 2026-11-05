"""Liga a malha ao sistema real: segmentos sobre a base, fluxos do plano e avaliação.

Cada enlace do plano de roteamento vira um fluxo entre os segmentos onde estão
os seus tradutores; a banda do fluxo é a soma das taxas dos canais do enlace.
`avaliar` reserva tudo na malha e confere o atraso de cada fluxo contra o
orçamento do seu protocolo. Os números de MALHA_* e ORCAMENTO_NS são ESTIMATIVAS.
"""
import math

from modulos.malha.topologia import Malha
from modulos.malha.trafego import Fluxo, reservar

# Estimativas, a confirmar com o projeto da placa:
MALHA_PASSO_MM = 25.0          # lado de cada segmento quadrado sobre a base
MALHA_FAIXAS = 64              # faixas paralelas em cada ligação entre vizinhos
MALHA_GBPS_POR_FAIXA = 32.0    # taxa de cada faixa

# Atraso extra (ns) que cada protocolo aceita além do caminho direto.
ORCAMENTO_NS = {
    "GDDR7-32": 10.0,    # estimativa: janela de treino do banco, pouca folga
    "DDR5-4800": 15.0,   # estimativa: folga do CL/RL da DDR5 sem reajuste
    "PCIe5": 100.0,      # estimativa: PCIe tolera latência de dezenas de ns
    "PCIe4": 100.0,
}
ORCAMENTO_PADRAO_NS = 20.0   # protocolos sem entrada acima (estimativa)


def orcamento_ns(protocolo):
    return ORCAMENTO_NS.get(protocolo, ORCAMENTO_PADRAO_NS)


def malha_da_base(base, passo_mm=MALHA_PASSO_MM, faixas=MALHA_FAIXAS, gbps=MALHA_GBPS_POR_FAIXA):
    """Malha de segmentos que cobre a área inteira da base (arredonda para cima)."""
    colunas = max(1, math.ceil(base.largura / passo_mm - 1e-9))
    linhas = max(1, math.ceil(base.profundidade / passo_mm - 1e-9))
    return Malha(colunas=colunas, linhas=linhas, passo_mm=passo_mm,
                 faixas_por_ligacao=faixas, gbps_por_faixa=gbps)


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


def avaliar(plano, base, malha=None):
    """Reserva os fluxos do plano na malha e devolve reserva, atrasos e resumo.

    `fora_do_orcamento` lista os fluxos cujo atraso passa do orçamento do protocolo;
    `acima_de_100` lista as ligações com ocupação acima da capacidade. São as duas
    entradas que o verificador usa nas regras R21 e R22.
    """
    malha = malha or malha_da_base(base)
    fluxos = fluxos_do_plano(plano, malha)
    reserva = reservar(malha, fluxos)

    detalhes = []
    for f, r in zip(fluxos, reserva.fluxos):
        orc = orcamento_ns(f.protocolo)
        detalhes.append({
            "nome": f.nome,
            "protocolo": f.protocolo,
            "saltos": r.saltos,
            "atraso_ns": r.atraso_ns,
            "orcamento_ns": orc,
            "folga_ns": orc - r.atraso_ns,
        })
    fora = [d for d in detalhes if d["folga_ns"] < 0]
    ocupacoes = list(reserva.ocupacao.values())
    resumo = {
        "saltos_max": max((d["saltos"] for d in detalhes), default=0),
        "atraso_max_ns": max((d["atraso_ns"] for d in detalhes), default=0.0),
        "potencia_w": reserva.potencia_w,
        "ocupacao_max": max(ocupacoes, default=0.0),
    }
    return {
        "malha": malha,
        "reserva": reserva,
        "fluxos": detalhes,
        "fora_do_orcamento": fora,
        "acima_de_100": reserva.acima_de_100,
        "resumo": resumo,
    }
