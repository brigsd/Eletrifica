"""Topologia: grade de segmentos iguais e as ligações de cobre entre vizinhos.

Segmento é identificado por (x, y), com 0 <= x < colunas e 0 <= y < linhas.
Ligação é o par de segmentos vizinhos (4 lados), guardado em ordem para que
(a, b) e (b, a) sejam a mesma ligação. Cada ligação tem faixas paralelas, e a
capacidade dela é faixas × gbps_por_faixa / 8, em GB/s.
"""
import math
from dataclasses import dataclass, field, replace


def ligacao(a, b):
    """Chave canônica da ligação entre dois segmentos vizinhos."""
    return (a, b) if a <= b else (b, a)


@dataclass(frozen=True)
class Malha:
    colunas: int
    linhas: int
    passo_mm: float                 # comprimento de cada ligação entre vizinhos
    faixas_por_ligacao: int
    gbps_por_faixa: float
    # Extensões opcionais (a API antiga não as usa):
    capacidades: dict = field(default_factory=dict, hash=False)   # ligação vizinha -> GB/s (override)
    expressas: dict = field(default_factory=dict, hash=False)     # ligação expressa -> GB/s

    def __post_init__(self):
        if self.colunas < 1 or self.linhas < 1:
            raise ValueError("a malha precisa de pelo menos 1 coluna e 1 linha")
        if self.passo_mm <= 0 or self.faixas_por_ligacao < 1 or self.gbps_por_faixa <= 0:
            raise ValueError("passo, faixas e gbps por faixa têm de ser positivos")

    def segmentos(self):
        return [(x, y) for y in range(self.linhas) for x in range(self.colunas)]

    def contem(self, segmento):
        x, y = segmento
        return 0 <= x < self.colunas and 0 <= y < self.linhas

    def vizinhos(self, segmento):
        x, y = segmento
        candidatos = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        return [s for s in candidatos if self.contem(s)]

    def ligacoes(self):
        """Todas as ligações da malha, em ordem estável."""
        return [(s, v) for s in self.segmentos() for v in self.vizinhos(s) if s < v]

    def capacidade_padrao_gbs(self):
        return self.faixas_por_ligacao * self.gbps_por_faixa / 8

    def todas_ligacoes(self):
        """Ligações entre vizinhos mais as expressas."""
        return self.ligacoes() + sorted(self.expressas)

    def com_capacidade(self, lig, gbs):
        """Nova malha com a capacidade de uma ligação (vizinha ou expressa) trocada."""
        lig = ligacao(*lig)
        if gbs <= 0:
            raise ValueError("capacidade tem de ser positiva")
        if lig in self.expressas:
            return replace(self, expressas={**self.expressas, lig: gbs})
        self.capacidade_gbs(lig)       # valida
        return replace(self, capacidades={**self.capacidades, lig: gbs})

    def com_expressa(self, a, b, gbs=None):
        """Nova malha com uma ligação expressa ponto a ponto entre dois segmentos quaisquer.

        Capacidade própria (`gbs`, padrão = a de uma ligação comum). Vizinhos não
        precisam de expressa: já têm ligação.
        """
        for s in (a, b):
            if not self.contem(s):
                raise ValueError(f"segmento {s} fora da malha {self.colunas}x{self.linhas}")
        if a == b or b in self.vizinhos(a):
            raise ValueError(f"expressa entre {a} e {b}: precisa ligar segmentos não vizinhos")
        gbs = self.capacidade_padrao_gbs() if gbs is None else gbs
        if gbs <= 0:
            raise ValueError("capacidade tem de ser positiva")
        return replace(self, expressas={**self.expressas, ligacao(a, b): gbs})

    def comprimento_mm(self, lig):
        """Comprimento da ligação: o passo para vizinhos, a reta entre centros para expressas."""
        a, b = lig
        return math.hypot(a[0] - b[0], a[1] - b[1]) * self.passo_mm

    def eh_expressa(self, lig):
        return ligacao(*lig) in self.expressas

    def capacidade_gbs(self, lig):
        """Capacidade da ligação em GB/s (faixas × gbps / 8, ou o override). Valida se existe."""
        lig = ligacao(*lig)
        if lig in self.expressas:
            return self.expressas[lig]
        if lig in self.capacidades:
            return self.capacidades[lig]
        a, b = lig
        if not (self.contem(a) and self.contem(b) and b in self.vizinhos(a)):
            raise ValueError(f"{lig} não é uma ligação entre vizinhos da malha")
        return self.faixas_por_ligacao * self.gbps_por_faixa / 8
