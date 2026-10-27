"""Configuração das células a partir do que o mapeamento achou.

Só usa a identificação (tipo + pose + pino de cada célula), nunca a montagem
real. Célula sem pino atribuído, ou em ponte entre dois pinos, fica desligada.
"""
from dataclasses import dataclass, field

import numpy as np

from modulos.componentes import obter
from modulos.sistema.base import CODIGO, DESLIGADA

APELIDO = {"i5-13600KF": "CPU", "DDR5-DIMM": "DIMM", "GPU": "GPU", "GDDR7": "MEM",
           "FPGA": "FPGA"}


@dataclass
class PecaConfigurada:
    nome: str
    tipo: str
    x: float
    y: float
    rot: float
    celulas_do_pino: dict = field(default_factory=dict)   # índice do pino -> células

    @property
    def peca(self):
        return obter(self.tipo)


@dataclass
class Configuracao:
    funcao: np.ndarray       # (ny, nx) DESLIGADA/F_SINAL/F_ENERGIA/F_TERRA
    peca: np.ndarray         # (ny, nx) índice em `pecas`, -1 = nenhuma
    pino: np.ndarray         # (ny, nx) índice do pino, -1 = nenhum
    pecas: list

    def por_nome(self, nome):
        return next(p for p in self.pecas if p.nome == nome)

    def resumo(self):
        f = self.funcao
        return {"sinal": int((f == 1).sum()), "energia": int((f == 2).sum()),
                "terra": int((f == 3).sum())}


def _nomear(identificacoes):
    """CPU, GPU, FPGA; DIMM0, DIMM1; MEM0..MEM11, numerados da esquerda/baixo."""
    por_tipo = {}
    for i, ident in enumerate(identificacoes):
        por_tipo.setdefault(ident.tipo, []).append(i)
    nomes = [None] * len(identificacoes)
    for tipo, idx in por_tipo.items():
        base = APELIDO.get(tipo, tipo)
        if len(idx) == 1:
            nomes[idx[0]] = base
            continue
        idx.sort(key=lambda i: (round(identificacoes[i].x / 5), identificacoes[i].y))
        for n, i in enumerate(idx):
            nomes[i] = f"{base}{n}"
    return nomes


def configurar(base, identificacoes, sondagem):
    funcao = np.full((base.ny, base.nx), DESLIGADA, dtype=np.int8)
    peca = np.full((base.ny, base.nx), -1, dtype=np.int16)
    pino = np.full((base.ny, base.nx), -1, dtype=np.int32)
    pecas = []
    for k, (ident, nome) in enumerate(zip(identificacoes, _nomear(identificacoes))):
        cat = obter(ident.tipo)
        pc = PecaConfigurada(nome, ident.tipo, ident.x, ident.y, ident.rot)
        ok = ident.pino >= 0
        cel, pin = ident.celulas[ok], ident.pino[ok]
        iy, ix = cel // base.nx, cel % base.nx
        funcao[iy, ix] = [CODIGO[cat.pinos[j].funcao] for j in pin]
        peca[iy, ix] = k
        pino[iy, ix] = pin
        for c, j in zip(cel, pin):
            pc.celulas_do_pino.setdefault(int(j), []).append(int(c))
        pecas.append(pc)
    if len(sondagem.pontes):
        iy, ix = sondagem.pontes // base.nx, sondagem.pontes % base.nx
        funcao[iy, ix] = DESLIGADA
        peca[iy, ix] = -1
        pino[iy, ix] = -1
    return Configuracao(funcao, peca, pino, pecas)
