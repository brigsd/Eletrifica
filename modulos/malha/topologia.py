"""Topologia: grade de segmentos iguais e as ligações de cobre entre vizinhos.

Segmento é identificado por (x, y), com 0 <= x < colunas e 0 <= y < linhas.
Ligação é o par de segmentos vizinhos (4 lados), guardado em ordem para que
(a, b) e (b, a) sejam a mesma ligação. Cada ligação tem faixas paralelas, e a
capacidade dela é faixas × gbps_por_faixa / 8, em GB/s.
"""
from dataclasses import dataclass


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

    def capacidade_gbs(self, lig):
        """Capacidade da ligação em GB/s (faixas × gbps / 8). Valida se a ligação existe."""
        a, b = lig
        if not (self.contem(a) and self.contem(b) and b in self.vizinhos(a)):
            raise ValueError(f"{lig} não é uma ligação entre vizinhos da malha")
        return self.faixas_por_ligacao * self.gbps_por_faixa / 8
