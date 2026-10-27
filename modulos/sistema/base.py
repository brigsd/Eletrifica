"""A base modular: grade de células sob um elastômero anisotrópico.

Cada célula é um ponto de contato chaveado. Uma peça encaixada em qualquer
posição toca as células que caem sob seus pads; quem decide o papel de cada
célula (energia, terra, sinal ou desligada) é o mapeamento, depois.
"""
import json
import math
from dataclasses import dataclass

import numpy as np

from modulos.caminhos import PROJETOS
from modulos.componentes import ENERGIA, SINAL, TERRA, obter

PROJETO = PROJETOS / "interconexao-optica"

DESLIGADA, F_SINAL, F_ENERGIA, F_TERRA = 0, 1, 2, 3
CODIGO = {SINAL: F_SINAL, ENERGIA: F_ENERGIA, TERRA: F_TERRA}


@dataclass
class Colocacao:
    id: str
    tipo: str
    x: float
    y: float
    rot: float          # graus
    extra: dict

    @property
    def peca(self):
        return obter(self.tipo)

    def pinos_na_base(self):
        """Coordenadas (x, y) de cada pino no referencial da base."""
        c, s = math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))
        p = np.array([(q.x, q.y) for q in self.peca.pinos])
        return np.column_stack([self.x + c * p[:, 0] - s * p[:, 1],
                                self.y + s * p[:, 0] + c * p[:, 1]])

    def contorno(self):
        c, s = math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))
        w, d = self.peca.largura / 2, self.peca.profundidade / 2
        return [(self.x + c * x - s * y, self.y + s * x + c * y)
                for x, y in ((-w, -d), (w, -d), (w, d), (-w, d))]


class Base:
    def __init__(self, largura, profundidade, passo, raio_contato):
        self.largura, self.profundidade = largura, profundidade
        self.passo, self.raio_contato = passo, raio_contato
        self.nx, self.ny = int(round(largura / passo)), int(round(profundidade / passo))

    def centro(self, ix, iy):
        return (np.asarray(ix) + 0.5) * self.passo, (np.asarray(iy) + 0.5) * self.passo


@dataclass
class Contatos:
    """Quem toca quem. `celula` é o índice plano (iy * nx + ix)."""
    celula: np.ndarray
    peca: np.ndarray     # índice da colocação
    pino: np.ndarray     # índice do pino dentro da peça
    distancia: np.ndarray


def calcular_contatos(base, colocacoes):
    cel, pec, pin, dist = [], [], [], []
    for k, col in enumerate(colocacoes):
        xy = col.pinos_na_base()
        alcance = col.peca.diametro_pad / 2 + base.raio_contato
        r = int(math.ceil(alcance / base.passo)) + 1
        ix0 = np.floor(xy[:, 0] / base.passo).astype(int)
        iy0 = np.floor(xy[:, 1] / base.passo).astype(int)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                ix, iy = ix0 + dx, iy0 + dy
                cx, cy = base.centro(ix, iy)
                d = np.hypot(cx - xy[:, 0], cy - xy[:, 1])
                ok = (d < alcance) & (ix >= 0) & (iy >= 0) & (ix < base.nx) & (iy < base.ny)
                idx = np.nonzero(ok)[0]
                cel.append(iy[idx] * base.nx + ix[idx])
                pec.append(np.full(len(idx), k))
                pin.append(idx)
                dist.append(d[idx])
    return Contatos(*(np.concatenate(a) for a in (cel, pec, pin, dist)))


@dataclass
class Montagem:
    base: Base
    colocacoes: list
    zonas: dict
    projeto: dict          # decisões de projeto: chave da célula, posição dos tradutores...

    def por_id(self, id_):
        return next(c for c in self.colocacoes if c.id == id_)


def carregar(caminho=None):
    data = json.loads((caminho or PROJETO / "montagem.json").read_text())
    b = data["base"]
    base = Base(b["largura_mm"], b["profundidade_mm"], b["passo_celula_mm"],
                b["raio_contato_celula_mm"])
    cols = []
    for p in data["pecas"]:
        extra = {k: v for k, v in p.items() if k not in ("id", "tipo", "x", "y", "rot")}
        cols.append(Colocacao(p["id"], p["tipo"], p["x"], p["y"], p["rot"], extra))
    return Montagem(base, cols, data.get("zonas", {}), data.get("projeto", {}))
