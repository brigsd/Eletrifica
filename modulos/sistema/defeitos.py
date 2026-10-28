"""Contato imperfeito entre peça e base: defeitos aplicados à verdade física.

Cada função muda o que realmente toca o quê (Contatos) ou onde a peça está
(Montagem) ANTES da sondagem; o mapeamento continua vendo só o que a sondagem
mede. Partículas condutoras viram `curtos` para `mapeamento.sondar`.
"""
import copy
import math
import numpy as np

from modulos.componentes import ENERGIA, SINAL, TERRA
from modulos.componentes.catalogo import Componente, Pino, Trilho
from modulos.sistema.base import Colocacao, Contatos

ESPESSURA_ELASTOMERO_MM = 0.5
COMPRESSAO_NOMINAL_MM = 0.10     # 20 % da espessura, aplicada pela moldura de pressão
COMPRESSAO_MINIMA_MM = 0.03      # abaixo disso o microfio não faz contato estável
CURSO_MM = COMPRESSAO_NOMINAL_MM - COMPRESSAO_MINIMA_MM
PARTICULA_MM = 0.35              # cavaco metálico ou fragmento de solda


def _filtrar(contatos, manter):
    return Contatos(contatos.celula[manter], contatos.peca[manter], contatos.pino[manter],
                    contatos.distancia[manter])


def _juntar(*cs):
    return Contatos(*(np.concatenate([getattr(c, f) for c in cs])
                      for f in ("celula", "peca", "pino", "distancia")))


def _indice(montagem, peca_id):
    return next(k for k, c in enumerate(montagem.colocacoes) if c.id == peca_id)


def _local(col):
    """Pinos no referencial da peça (mm)."""
    return np.array([(p.x, p.y) for p in col.peca.pinos])


def _celulas_perto(base, x, y, alcance):
    r = int(math.ceil(alcance / base.passo)) + 1
    ix0, iy0 = int(math.floor(x / base.passo)), int(math.floor(y / base.passo))
    cel, dist = [], []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            ix, iy = ix0 + dx, iy0 + dy
            if not (0 <= ix < base.nx and 0 <= iy < base.ny):
                continue
            cx, cy = base.centro(ix, iy)
            d = math.hypot(float(cx) - x, float(cy) - y)
            if d < alcance:
                cel.append(iy * base.nx + ix)
                dist.append(d)
    return cel, dist


def tirar_pinos(contatos, k, pinos):
    pinos = set(int(j) for j in pinos)
    fora = (contatos.peca == k) & np.isin(contatos.pino, list(pinos))
    return _filtrar(contatos, ~fora)


# ---------------------------------------------------------------- (a) inclinação
def inclinar(montagem, contatos, peca_id, graus, direcao_graus=45.0):
    """Peça inclinada em torno do centro: do lado que sobe, a compressão do
    elastômero cai; pino com compressão menor que a mínima perde o contato.
    `direcao_graus` 45 levanta um canto (eixo diagonal)."""
    k = _indice(montagem, peca_id)
    loc = _local(montagem.colocacoes[k])
    u = np.array([math.cos(math.radians(direcao_graus)), math.sin(math.radians(direcao_graus))])
    sobe = loc @ u * math.tan(math.radians(graus))
    perdidos = np.nonzero(sobe > CURSO_MM)[0]
    return tirar_pinos(contatos, k, perdidos), perdidos


# ------------------------------------------------- (b) pinos sem contato ao acaso
def sem_contato(montagem, contatos, peca_id, fracao, semente=0, funcao=None, grupo=None):
    """Sujeira não condutiva ou desgaste: uma fração dos pinos (opcionalmente só
    de uma função ou de um grupo/trilho) perde todo o contato."""
    k = _indice(montagem, peca_id)
    pinos = montagem.colocacoes[k].peca.pinos
    elegiveis = [j for j, p in enumerate(pinos)
                 if (funcao is None or p.funcao == funcao) and (grupo is None or p.grupo == grupo)]
    rng = np.random.default_rng(semente)
    n = int(round(fracao * len(elegiveis)))
    perdidos = rng.choice(elegiveis, size=n, replace=False) if n else np.array([], int)
    return tirar_pinos(contatos, k, perdidos), np.sort(perdidos)


# -------------------------------------------------------- (c) partícula condutora
def particula(base, montagem, contatos, peca_id, n=1, semente=0, entre=(SINAL, TERRA),
              diametro_mm=PARTICULA_MM):
    """Partícula condutora sobre o elastômero, entre dois pinos vizinhos de redes
    diferentes (`entre` = as duas funções). Devolve os curtos para sondar()."""
    k = _indice(montagem, peca_id)
    col = montagem.colocacoes[k]
    pinos = col.peca.pinos
    xy = col.pinos_na_base()
    rng = np.random.default_rng(semente)
    raio_pad = col.peca.diametro_pad / 2
    a_lista = [j for j, p in enumerate(pinos) if p.funcao == entre[0]]
    curtos = []
    for _ in range(n):
        for _tentativa in range(200):
            a = int(rng.choice(a_lista))
            d = np.hypot(*(xy - xy[a]).T)
            d[a] = np.inf
            viz = [j for j in np.argsort(d)[:8] if pinos[j].funcao == entre[1]
                   and d[j] - 2 * raio_pad < diametro_mm]
            if viz:
                b = int(viz[0])
                break
        else:
            raise ValueError(f"nenhum par {entre} perto o bastante em {peca_id}")
        centro = (xy[a] + xy[b]) / 2
        tocados = [j for j in range(len(pinos))
                   if np.hypot(*(xy[j] - centro)) < diametro_mm / 2 + raio_pad]
        curtos.append([(k, j) for j in tocados])
    return contatos, curtos


# ------------------------------------------------------------- (d) pino torto
def entortar_pino(base, montagem, contatos, peca_id, pino, dx_mm, dy_mm):
    """O pino sai do lugar: o contato dele é refeito na posição nova (pode tocar
    a célula de um vizinho)."""
    k = _indice(montagem, peca_id)
    col = montagem.colocacoes[k]
    x, y = col.pinos_na_base()[pino]
    sem = tirar_pinos(contatos, k, [pino])
    cel, dist = _celulas_perto(base, x + dx_mm, y + dy_mm,
                               col.peca.diametro_pad / 2 + base.raio_contato)
    novo = Contatos(np.array(cel, int), np.full(len(cel), k), np.full(len(cel), pino),
                    np.array(dist, float))
    return _juntar(sem, novo)


# ------------------------------------------------------- (e) peça fora do catálogo
class ColocacaoEstranha(Colocacao):
    """Peça que não existe no catálogo (o mapeamento não pode conhecê-la)."""

    def __init__(self, id_, x, y, rot, componente):
        super().__init__(id_, componente.tipo, x, y, rot, {})
        self._componente = componente

    @property
    def peca(self):
        return self._componente


def componente_estranho(semente=0, n=24, passo=0.9):
    """Grade de pinos com terra, energia e sinal sorteados: não bate com nada."""
    rng = np.random.default_rng(semente)
    x0 = -(n - 1) * passo / 2
    pinos = []
    funcoes = rng.choice([TERRA, ENERGIA, SINAL], size=n * n, p=[0.45, 0.2, 0.35])
    for i, f in enumerate(funcoes):
        ix, iy = i % n, i // n
        grupo = {TERRA: "VSS", ENERGIA: "VX"}.get(f, f"S{i}")
        pinos.append(Pino(f"{grupo}_{i}", f, grupo, x0 + ix * passo, x0 + iy * passo))
    lado = n * passo + 2
    return Componente("PECA-X", "peça fora do catálogo", lado, lado, 2.0, 0.5, pinos,
                      {"VX": Trilho("VX", 1.0, 5.0, "base")}, {}, 5.0, 5.0, 0.1, "#777777")


def peca_estranha(montagem, x, y, rot=0.0, semente=0):
    m = copy.deepcopy(montagem)
    m.colocacoes.append(ColocacaoEstranha("X", x, y, rot, componente_estranho(semente)))
    return m


# ---------------------------------------------- (f) peça parcialmente fora da base
def deslocar(montagem, peca_id, x=None, y=None, rot=None):
    m = copy.deepcopy(montagem)
    col = m.colocacoes[_indice(m, peca_id)]
    col.x = col.x if x is None else x
    col.y = col.y if y is None else y
    col.rot = col.rot if rot is None else rot
    return m


# ------------------------------------------------------- (g) duas peças encostadas
def encostar(montagem, id_fixa, id_movel, folga_corpo_mm=None, distancia_pinos_mm=None):
    """Põe a peça móvel à direita da fixa, centrada em y. Com `folga_corpo_mm` os
    corpos ficam a essa distância (0 = encostados); com `distancia_pinos_mm` são
    as fileiras de pinos mais próximas que ficam a essa distância (pode exigir
    corpos sobrepostos)."""
    m = copy.deepcopy(montagem)
    fixa, movel = m.colocacoes[_indice(m, id_fixa)], m.colocacoes[_indice(m, id_movel)]
    xs_f = fixa.pinos_na_base()[:, 0]
    movel.y = fixa.y
    if folga_corpo_mm is not None:
        borda_f = max(p[0] for p in fixa.contorno())
        meia = movel.x - min(p[0] for p in movel.contorno())
        movel.x = borda_f + folga_corpo_mm + meia
    else:
        recuo = movel.x - movel.pinos_na_base()[:, 0].min()
        movel.x = xs_f.max() + distancia_pinos_mm + recuo
    return m

