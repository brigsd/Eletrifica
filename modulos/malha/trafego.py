"""Tráfego: fluxos reservados em rotas fixas, somados por ligação.

Cada fluxo tem origem, destino e banda em GB/s. A banda de cada fluxo soma em
cada ligação da sua rota. Como a rota é reservada, o atraso de um fluxo é só o
do caminho (sem fila). A ocupação de uma ligação acima de 100 % significa que a
reserva não cabe e o circuito não fecha.
"""
from dataclasses import dataclass, field

from modulos.malha import custo
from modulos.malha.rota import caminhos, rota_com_expressa


@dataclass(frozen=True)
class Fluxo:
    nome: str
    origem: tuple
    destino: tuple
    gbs: float                   # GB/s reservados
    protocolo: str = ""          # protocolo nativo do enlace (opcional)
    rota: str = "xy"             # "xy", "yx" ou "dividida" (XY e YX meio a meio)
    expressa: tuple = None       # ligação expressa que o fluxo usa (opcional)


@dataclass
class ResultadoFluxo:
    nome: str
    ligacoes: list
    saltos: int
    atraso_ns: float
    energia_pj_bit: float
    potencia_w: float


@dataclass
class Reserva:
    ocupacao: dict               # ligação -> fração da capacidade (0..n)
    acima_de_100: list           # [(ligação, ocupação)] com ocupação > 1
    fluxos: list = field(default_factory=list)   # ResultadoFluxo, na ordem de entrada
    potencia_w: float = 0.0

    @property
    def cabe(self):
        return not self.acima_de_100


def reservar(malha, fluxos):
    """Reserva os fluxos nas rotas fixas da malha e devolve a ocupação e o custo."""
    carga = {lig: 0.0 for lig in malha.todas_ligacoes()}
    resultados = []
    for f in fluxos:
        if f.gbs < 0:
            raise ValueError(f"fluxo {f.nome}: banda negativa")
        if f.expressa is not None:
            partes = rota_com_expressa(malha, f.origem, f.destino, f.expressa, f.rota)
        else:
            partes = caminhos(malha, f.origem, f.destino, f.rota)
        ligs, saltos, atraso = [], 0, 0.0
        for caminho, frac in partes:
            for lig in caminho:
                carga[lig] += f.gbs * frac
                if lig not in ligs:
                    ligs.append(lig)
            # cada ligação é um salto; a expressa é um salto só, com a distância dela
            saltos = max(saltos, len(caminho))
            atraso = max(atraso, sum(
                custo.atraso_ligacao_ns(malha.comprimento_mm(lig)) for lig in caminho))
        pj = custo.energia_pj_por_bit(saltos)
        # GB/s × 8e9 bit/s × pJ/bit × 1e-12 J/pJ = W
        potencia = f.gbs * 8e9 * pj * 1e-12
        resultados.append(ResultadoFluxo(
            nome=f.nome,
            ligacoes=ligs,
            saltos=saltos,
            atraso_ns=atraso,
            energia_pj_bit=pj,
            potencia_w=potencia,
        ))

    ocupacao = {lig: carga[lig] / malha.capacidade_gbs(lig) for lig in carga}
    acima = [(lig, ocupacao[lig]) for lig in carga if ocupacao[lig] > 1.0]
    return Reserva(
        ocupacao=ocupacao,
        acima_de_100=acima,
        fluxos=resultados,
        potencia_w=sum(r.potencia_w for r in resultados),
    )
