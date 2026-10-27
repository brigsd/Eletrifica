"""Mapeamento antes de energizar: descobre que peça está onde, só sondando células.

A sondagem é fraca (microamperes) e só revela o que um instrumento veria:
quais células estão em curto entre si, e a assinatura elétrica de cada grupo —
a referência (terra), um trilho (capacitância grande para a referência) ou um
sinal (diodo de proteção para a referência). Nomes de pino e de peça nunca
saem da sondagem. A identificação compara o padrão terra/energia/sinal com as
pinagens do catálogo, em qualquer posição e rotação.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.spatial import cKDTree

from modulos.componentes import CATALOGO, ENERGIA, SINAL, TERRA, obter
from modulos.sistema.base import CODIGO, F_ENERGIA, F_SINAL, F_TERRA

ASSINATURA = {TERRA: "referencia", ENERGIA: "capacitivo", SINAL: "diodo"}
CLASSE = {"referencia": F_TERRA, "capacitivo": F_ENERGIA, "diodo": F_SINAL}


@dataclass
class Sondagem:
    celula: np.ndarray       # índice plano
    grupo: np.ndarray        # id anônimo do grupo em curto
    assinatura: dict         # grupo -> "referencia" | "capacitivo" | "diodo"
    referencia: dict         # grupo -> grupo de referência (o terra daquela peça)
    pontes: np.ndarray       # células que tocam dois nets: ficam fora


def sondar(montagem, contatos, semente=0):
    """Emula a sondagem. A verdade (nome de cada net) fica aqui dentro."""
    cols = montagem.colocacoes
    net_de = {}
    for cel, k, i in zip(contatos.celula, contatos.peca, contatos.pino):
        p = cols[k].peca.pinos[i]
        net = (k, p.grupo) if p.funcao != SINAL else (k, p.nome)
        net_de.setdefault(int(cel), set()).add((net, p.funcao))
    pontes = np.array(sorted(c for c, n in net_de.items()
                             if len({x[0] for x in n}) > 1), dtype=int)
    validas = {c: next(iter(n)) for c, n in net_de.items() if len({x[0] for x in n}) == 1}

    rng = np.random.default_rng(semente)
    nets = sorted({v[0] for v in validas.values()}, key=str)
    anon = dict(zip(nets, rng.permutation(len(nets))))
    funcao_net = {v[0]: v[1] for v in validas.values()}
    assinatura = {int(anon[n]): ASSINATURA[f] for n, f in funcao_net.items()}
    terra_da_peca = {n[0]: int(anon[n]) for n, f in funcao_net.items() if f == TERRA}
    referencia = {int(anon[n]): terra_da_peca.get(n[0], -1) for n in funcao_net}

    cel = np.array(sorted(validas), dtype=int)
    grupo = np.array([anon[validas[c][0]] for c in cel], dtype=int)
    return Sondagem(cel, grupo, assinatura, referencia, pontes)


@dataclass
class Identificacao:
    tipo: str
    x: float
    y: float
    rot: float
    acerto: float           # fração das células que caem num pino da mesma classe
    cobertura: float        # fração dos pinos do catálogo tocados
    margem: float           # distância para a segunda melhor hipótese
    celulas: np.ndarray     # células desta peça
    classes: np.ndarray     # classe medida de cada célula
    pino: np.ndarray        # pino do catálogo atribuído a cada célula (-1 = nenhum)


def _pose_pinos(peca, x, y, rot):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    p = np.array([(q.x, q.y) for q in peca.pinos])
    return np.column_stack([x + c * p[:, 0] - s * p[:, 1], y + s * p[:, 0] + c * p[:, 1]])


def _classes_catalogo(peca):
    return np.array([CODIGO[p.funcao] for p in peca.pinos])


def _avaliar(peca, pose, xy, cls, alcance):
    pins = _pose_pinos(peca, *pose)
    pcls = _classes_catalogo(peca)
    d, j = cKDTree(pins).query(xy, distance_upper_bound=alcance)
    perto = np.isfinite(d)
    certo = perto & (pcls[np.minimum(j, len(pins) - 1)] == cls)
    acerto = certo.sum() / len(xy)
    tocados = np.unique(j[certo])
    pino = np.where(certo, j, -1)
    return acerto, len(tocados) / len(pins), pino


def _custo_suave(params, peca, xy, cls, sigma):
    pins = _pose_pinos(peca, *params)
    pcls = _classes_catalogo(peca)
    d, j = cKDTree(pins).query(xy, k=3, distance_upper_bound=4 * sigma)
    j = np.minimum(j, len(pins) - 1)
    w = np.exp(-(d ** 2) / (2 * sigma ** 2))
    w[~np.isfinite(d)] = 0.0
    igual = pcls[j] == cls[:, None]
    return -(w * igual).sum() + (w * ~igual).sum()


def _icp(peca, pose, xy, cls, alcance, voltas=12):
    """Cada célula puxa o pino de mesma classe mais próximo; a pose rígida sai por SVD."""
    local = np.array([(q.x, q.y) for q in peca.pinos])
    pcls = _classes_catalogo(peca)
    arvores = {k: (cKDTree(local[pcls == k]), np.nonzero(pcls == k)[0]) for k in np.unique(pcls)}
    x, y, rot = pose
    for _ in range(voltas):
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        # célula -> referencial da peça
        dx, dy = xy[:, 0] - x, xy[:, 1] - y
        loc = np.column_stack([c * dx + s * dy, -s * dx + c * dy])
        src, dst = [], []
        for k, (arv, idx) in arvores.items():
            m = cls == k
            if not m.any():
                continue
            d, j = arv.query(loc[m], distance_upper_bound=alcance * 1.5)
            ok = np.isfinite(d)
            src.append(local[idx[j[ok]]])
            dst.append(xy[m][ok])
        src, dst = np.concatenate(src), np.concatenate(dst)
        ms, md = src.mean(0), dst.mean(0)
        u, _, vt = np.linalg.svd((src - ms).T @ (dst - md))
        r = (u @ vt).T
        if np.linalg.det(r) < 0:
            vt[-1] *= -1
            r = (u @ vt).T
        rot = math.degrees(math.atan2(r[1, 0], r[0, 0]))
        x, y = md - r @ ms
    return np.array([x, y, rot])


def identificar(base, sondagem):
    """Agrupa as células por peça (pelo terra de referência) e reconhece cada grupo."""
    xs, ys = base.centro(sondagem.celula % base.nx, sondagem.celula // base.nx)
    xy_all = np.column_stack([xs, ys])
    ref = np.array([sondagem.referencia[g] for g in sondagem.grupo])
    cls_all = np.array([CLASSE[sondagem.assinatura[g]] for g in sondagem.grupo])

    saida = []
    for terra in sorted({r for r in ref if r >= 0}):
        m = ref == terra
        xy, cls = xy_all[m], cls_all[m]
        saida.append(_reconhecer(base, xy, cls, sondagem.celula[m]))
    return saida


def _reconhecer(base, xy, cls, celulas):
    area_contato = lambda peca: math.pi * (peca.diametro_pad / 2 + base.raio_contato) ** 2
    hipoteses = []
    for tipo in CATALOGO:
        peca = obter(tipo)
        esperado = len(peca.pinos) * area_contato(peca) / base.passo ** 2
        if not 0.6 < len(xy) / esperado < 1.6:
            continue
        alcance = peca.diametro_pad / 2 + base.raio_contato
        pins0 = np.array([(q.x, q.y) for q in peca.pinos])
        for rot0 in (0.0, 90.0, 180.0, 270.0):
            c, s = math.cos(math.radians(rot0)), math.sin(math.radians(rot0))
            cx = c * pins0[:, 0].mean() - s * pins0[:, 1].mean()
            cy = s * pins0[:, 0].mean() + c * pins0[:, 1].mean()
            x0, y0 = xy[:, 0].mean() - cx, xy[:, 1].mean() - cy
            res = minimize(_custo_suave, [x0, y0, rot0], args=(peca, xy, cls, 0.25),
                           method="Nelder-Mead",
                           options={"xatol": 0.005, "fatol": 0.5, "initial_simplex":
                                    [[x0, y0, rot0], [x0 + 0.3, y0, rot0],
                                     [x0, y0 + 0.3, rot0], [x0, y0, rot0 + 1.0]]})
            pose = _icp(peca, res.x, xy, cls, alcance)
            acerto, cobertura, pino = _avaliar(peca, pose, xy, cls, alcance)
            hipoteses.append((acerto * cobertura, tipo, pose, acerto, cobertura, pino))
    hipoteses.sort(key=lambda h: -h[0])
    nota, tipo, pose, acerto, cobertura, pino = hipoteses[0]
    margem = nota - (hipoteses[1][0] if len(hipoteses) > 1 else 0.0)
    rot = float(pose[2]) % 360.0
    return Identificacao(tipo, float(pose[0]), float(pose[1]), rot, acerto, cobertura,
                         margem, celulas, cls, pino)


def conferir(montagem, identificacoes):
    """Compara o que o mapeamento achou com o que foi encaixado (só para teste)."""
    sobra = list(montagem.colocacoes)
    linhas = []
    for ident in identificacoes:
        col = min(sobra, key=lambda c: math.hypot(c.x - ident.x, c.y - ident.y))
        sobra.remove(col)
        drot = (ident.rot - col.rot + 180) % 360 - 180
        linhas.append({"id": col.id, "tipo_real": col.tipo, "tipo_achado": ident.tipo,
                       "erro_mm": math.hypot(col.x - ident.x, col.y - ident.y),
                       "erro_graus": drot, "acerto": ident.acerto,
                       "cobertura": ident.cobertura, "margem": ident.margem})
    return linhas
