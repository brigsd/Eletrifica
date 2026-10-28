"""Mapeamento antes de energizar: descobre que peça está onde, só sondando células.

A sondagem é fraca (microamperes) e só revela o que um instrumento veria:
quais células estão em curto entre si, e a assinatura elétrica de cada grupo —
a referência (terra), um trilho (capacitância grande para a referência) ou um
sinal (diodo de proteção para a referência). Nomes de pino e de peça nunca
saem da sondagem. A identificação compara o padrão terra/energia/sinal com as
pinagens do catálogo, em qualquer posição e rotação.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.spatial import ConvexHull, cKDTree

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


def _net(peca_k, p):
    return (peca_k, p.grupo) if p.funcao != SINAL else (peca_k, p.nome)


def sondar(montagem, contatos, semente=0, curtos=()):
    """Emula a sondagem. A verdade (nome de cada net) fica aqui dentro.

    `curtos`: condutores estranhos (partícula, rebarba), cada um uma lista de
    (índice da peça, índice do pino) que ele liga entre si. Uma célula que toca
    dois pinos também os liga: o fio do elastômero não depende da chave.
    """
    cols = montagem.colocacoes
    net_de = {}
    for cel, k, i in zip(contatos.celula, contatos.peca, contatos.pino):
        p = cols[k].peca.pinos[i]
        net_de.setdefault(int(cel), set()).add((_net(k, p), p.funcao))
    pontes = np.array(sorted(c for c, n in net_de.items()
                             if len({x[0] for x in n}) > 1), dtype=int)
    validas = {c: next(iter(n)) for c, n in net_de.items() if len({x[0] for x in n}) == 1}

    funcao_net = {}
    for n in net_de.values():
        for net, f in n:
            funcao_net[net] = f
    pai = {net: net for net in funcao_net}

    def raiz(a):
        while pai[a] != a:
            pai[a] = pai[pai[a]]
            a = pai[a]
        return a

    def unir(a, b):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            pai[max(ra, rb, key=str)] = min(ra, rb, key=str)

    for n in net_de.values():
        nets = [x[0] for x in n]
        for b in nets[1:]:
            unir(nets[0], b)
    for curto in curtos:
        nets = [_net(k, cols[k].peca.pinos[i]) for k, i in curto]
        nets = [x for x in nets if x in pai]
        for b in nets[1:]:
            unir(nets[0], b)

    comp = {}
    for net in funcao_net:
        comp.setdefault(raiz(net), []).append(net)
    raizes = sorted(comp, key=str)
    rng = np.random.default_rng(semente)
    anon = {r: int(a) for r, a in zip(raizes, rng.permutation(len(raizes)))}

    def assinatura_de(nets):
        fs = {funcao_net[n] for n in nets}
        return ASSINATURA[TERRA if TERRA in fs else ENERGIA if ENERGIA in fs else SINAL]

    assinatura = {anon[r]: assinatura_de(ns) for r, ns in comp.items()}
    terra_da_peca = {}
    for r, ns in comp.items():
        for n in ns:
            if funcao_net[n] == TERRA:
                terra_da_peca.setdefault(n[0], anon[r])
    referencia = {}
    for r, ns in comp.items():
        if assinatura[anon[r]] == "referencia":
            referencia[anon[r]] = anon[r]
        else:
            pecas = sorted({n[0] for n in ns})
            referencia[anon[r]] = next((terra_da_peca[k] for k in pecas if k in terra_da_peca), -1)

    cel = np.array(sorted(validas), dtype=int)
    grupo = np.array([anon[raiz(validas[c][0])] for c in cel], dtype=int)
    return Sondagem(cel, grupo, assinatura, referencia, pontes)


DESCONHECIDA = "desconhecida"
ACERTO_MIN = 0.85           # abaixo disso o padrão não é de nenhuma peça do catálogo
COBERTURA_MIN = 0.2         # menos de 20 % dos pinos tocados: não dá para afirmar o que é
MIN_CELULAS = 30            # grupo menor que isso é resto, não peça
RAZAO_CELULAS = (0.2, 4.0)  # células medidas / esperadas para o tipo ser testado


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
    pinos_sem_contato: list = field(default_factory=list)   # índices do catálogo
    pontes: list = field(default_factory=list)  # [{"redes": [(i_ident, net)], "celulas": n}]


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
        if len(src) < 3:            # hipótese sem casamento nenhum: nada a ajustar
            break
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
    """Agrupa as células por peça (pelo terra de referência) e reconhece cada grupo.

    Um grupo pode ter mais de uma peça (terras em curto) ou nenhuma do catálogo:
    reconhece a melhor, tira as células que caem sob ela e repete com o resto.
    """
    xs, ys = base.centro(sondagem.celula % base.nx, sondagem.celula // base.nx)
    xy_all = np.column_stack([xs, ys])
    ref = np.array([sondagem.referencia[g] for g in sondagem.grupo], dtype=int)
    cls_all = np.array([CLASSE[sondagem.assinatura[g]] for g in sondagem.grupo])

    saida = []
    for terra in sorted({int(r) for r in ref if r >= 0}):
        m = ref == terra
        saida += _reconhecer_tudo(base, xy_all[m], cls_all[m], sondagem.celula[m])
    sem_ref = ref < 0
    if sem_ref.sum() >= MIN_CELULAS:
        saida.append(_desconhecida(xy_all[sem_ref], cls_all[sem_ref], sondagem.celula[sem_ref]))
    diagnosticar(base, sondagem, saida)
    return saida


def _desconhecida(xy, cls, celulas):
    return Identificacao(DESCONHECIDA, float(xy[:, 0].mean()), float(xy[:, 1].mean()), 0.0,
                         0.0, 0.0, 0.0, celulas, cls, np.full(len(celulas), -1))


def _reconhecer_tudo(base, xy, cls, celulas):
    out = []
    resto = np.ones(len(xy), bool)
    while resto.sum() >= MIN_CELULAS:
        idx = np.nonzero(resto)[0]
        ident = _reconhecer(base, xy[idx], cls[idx], celulas[idx])
        if ident is None:
            out.append(_desconhecida(xy[idx], cls[idx], celulas[idx]))
            break
        out.append(ident)
        peca = obter(ident.tipo)
        alcance = peca.diametro_pad / 2 + base.raio_contato
        d, _ = cKDTree(_pose_pinos(peca, ident.x, ident.y, ident.rot)).query(xy[idx])
        resto[idx[d <= 1.5 * alcance]] = False
    return out


def _angulo_retangulo(xy):
    """Ângulo (mod 90°) do retângulo de área mínima que envolve as células: a orientação
    da peça, em qualquer giro."""
    try:
        h = xy[ConvexHull(xy).vertices]
    except Exception:
        return 0.0
    melhor = (math.inf, 0.0)
    for a, b in zip(h, np.roll(h, -1, axis=0)):
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s = math.cos(-ang), math.sin(-ang)
        u = c * h[:, 0] - s * h[:, 1]
        v = s * h[:, 0] + c * h[:, 1]
        area = (u.max() - u.min()) * (v.max() - v.min())
        if area < melhor[0] - 1e-9:
            melhor = (area, math.degrees(ang) % 90.0)
    th = melhor[1]
    return th - 90.0 if th > 45.0 else th


def _reconhecer(base, xy, cls, celulas):
    area_contato = lambda peca: math.pi * (peca.diametro_pad / 2 + base.raio_contato) ** 2
    hipoteses = []
    for tipo in CATALOGO:
        peca = obter(tipo)
        esperado = len(peca.pinos) * area_contato(peca) / base.passo ** 2
        if not RAZAO_CELULAS[0] < len(xy) / esperado < RAZAO_CELULAS[1]:
            continue
        alcance = peca.diametro_pad / 2 + base.raio_contato
        pins0 = np.array([(q.x, q.y) for q in peca.pinos])
        theta = _angulo_retangulo(xy)
        for rot0 in (theta, theta + 90.0, theta + 180.0, theta + 270.0):
            c, s = math.cos(math.radians(rot0)), math.sin(math.radians(rot0))
            rp = np.column_stack([c * pins0[:, 0] - s * pins0[:, 1], s * pins0[:, 0] + c * pins0[:, 1]])
            # centro do retângulo envolvente: não se move quando falta um canto
            x0 = (xy[:, 0].min() + xy[:, 0].max()) / 2 - (rp[:, 0].min() + rp[:, 0].max()) / 2
            y0 = (xy[:, 1].min() + xy[:, 1].max()) / 2 - (rp[:, 1].min() + rp[:, 1].max()) / 2
            res = minimize(_custo_suave, [x0, y0, rot0], args=(peca, xy, cls, 0.25),
                           method="Nelder-Mead",
                           options={"xatol": 0.005, "fatol": 0.5, "initial_simplex":
                                    [[x0, y0, rot0], [x0 + 0.3, y0, rot0],
                                     [x0, y0 + 0.3, rot0], [x0, y0, rot0 + 1.0]]})
            pose = _icp(peca, res.x, xy, cls, alcance)
            acerto, cobertura, pino = _avaliar(peca, pose, xy, cls, alcance)
            hipoteses.append((acerto * cobertura, tipo, pose, acerto, cobertura, pino))
    if not hipoteses:
        return None
    hipoteses.sort(key=lambda h: -h[0])
    nota, tipo, pose, acerto, cobertura, pino = hipoteses[0]
    if acerto < 0.97:
        # contato parcial: o retângulo medido pode estar cortado (borda da base,
        # canto levantado); alinha por cada borda e depois procura na grade
        melhor = _alinhar_bordas(base, obter(tipo), pose, xy, cls, (nota, pose, acerto, cobertura, pino))
        nota, pose, acerto, cobertura, pino = _busca_na_grade(base, obter(tipo), melhor[1], xy, cls, melhor)
    # o acerto conta só as células que caem sob a peça: o resto pode ser de outra
    dentro = _celulas_sob(obter(tipo), pose, xy, base)
    acerto = float((pino[dentro] >= 0).mean()) if dentro.any() else 0.0
    if acerto < ACERTO_MIN or cobertura < COBERTURA_MIN:
        return None
    margem = nota - (hipoteses[1][0] if len(hipoteses) > 1 else 0.0)
    rot = float(pose[2]) % 360.0
    return Identificacao(tipo, float(pose[0]), float(pose[1]), rot, acerto, cobertura,
                         margem, celulas, cls, pino)


def _alinhar_bordas(base, peca, pose, xy, cls, melhor):
    alcance = peca.diametro_pad / 2 + base.raio_contato
    rp = _pose_pinos(peca, 0.0, 0.0, pose[2])
    opcoes = []
    for eixo in (0, 1):
        lo, hi = xy[:, eixo].min(), xy[:, eixo].max()
        opcoes.append(((lo + hi) / 2 - (rp[:, eixo].min() + rp[:, eixo].max()) / 2,
                       lo - rp[:, eixo].min(), hi - rp[:, eixo].max()))
    for x0 in opcoes[0]:
        for y0 in opcoes[1]:
            p = _icp(peca, np.array([x0, y0, pose[2]]), xy, cls, alcance, voltas=8)
            a, cob, pino = _avaliar(peca, p, xy, cls, alcance)
            if a * cob > melhor[0]:
                melhor = (a * cob, p, a, cob, pino)
    return melhor


def _busca_na_grade(base, peca, pose, xy, cls, melhor, passos=2):
    alcance = peca.diametro_pad / 2 + base.raio_contato
    local = np.array([(q.x, q.y) for q in peca.pinos])
    d, _ = cKDTree(local).query(local, k=2)
    passo = float(np.median(d[:, 1]))
    c, s = math.cos(math.radians(pose[2])), math.sin(math.radians(pose[2]))
    for i in range(-passos, passos + 1):
        for j in range(-passos, passos + 1):
            if i == 0 and j == 0:
                continue
            dx, dy = passo * (c * i - s * j), passo * (s * i + c * j)
            p = _icp(peca, np.array([pose[0] + dx, pose[1] + dy, pose[2]]), xy, cls, alcance, voltas=6)
            a, cob, pino = _avaliar(peca, p, xy, cls, alcance)
            if a * cob > melhor[0]:
                melhor = (a * cob, p, a, cob, pino)
    return melhor


def _celulas_sob(peca, pose, xy, base):
    alcance = peca.diametro_pad / 2 + base.raio_contato
    d, _ = cKDTree(_pose_pinos(peca, *pose)).query(xy)
    return d <= 1.5 * alcance


def _net_catalogo(p):
    return p.grupo if p.funcao != SINAL else p.nome


def diagnosticar(base, sondagem, identificacoes):
    """Pinos sem contato e pontes, só com o que foi medido e a pose achada.

    Uma ponte aparece como um grupo em curto que cai sob pinos de redes
    diferentes (pela geometria da pose, não pela classe medida). Terra com terra
    de outra peça não conta: os terras se juntam na base de qualquer jeito.
    """
    grupo_da_celula = dict(zip(sondagem.celula.tolist(), sondagem.grupo.tolist()))
    redes_do_grupo = {}
    for i, ident in enumerate(identificacoes):
        if ident.tipo == DESCONHECIDA:
            continue
        peca = obter(ident.tipo)
        ident.pontes = []
        alcance = peca.diametro_pad / 2 + base.raio_contato
        xs, ys = base.centro(ident.celulas % base.nx, ident.celulas // base.nx)
        d, j = cKDTree(_pose_pinos(peca, ident.x, ident.y, ident.rot)).query(
            np.column_stack([xs, ys]), distance_upper_bound=alcance)
        # pino em curto continua em contato: sem contato é não ter célula sob ele
        tocados = set(int(x) for x in j[np.isfinite(d)])
        ident.pinos_sem_contato = sorted(set(range(len(peca.pinos))) - tocados)
        for cel, dist, jj in zip(ident.celulas.tolist(), d, j):
            if not np.isfinite(dist):
                continue
            p = peca.pinos[int(jj)]
            g = grupo_da_celula[cel]
            redes_do_grupo.setdefault(g, {}).setdefault((i, _net_catalogo(p), p.funcao), 0)
            redes_do_grupo[g][(i, _net_catalogo(p), p.funcao)] += 1
    grupos_da_rede = {}
    for g, redes in redes_do_grupo.items():
        for r in redes:
            grupos_da_rede.setdefault(r, set()).add(g)
    for g, redes in redes_do_grupo.items():
        if len(redes) < 2 or all(f == TERRA for _, _, f in redes):
            continue
        # curto: as redes inteiras viraram uma só; senão, só algumas células de uma
        # rede respondem pela outra (pino fora do lugar sobre a célula do vizinho)
        tipo = "curto" if all(len(grupos_da_rede[r]) == 1 for r in redes) else "fora_do_lugar"
        ponte = {"tipo": tipo, "redes": sorted((i, net) for i, net, _ in redes),
                 "celulas": sum(redes.values())}
        for i in sorted({i for i, _, _ in redes}):
            identificacoes[i].pontes.append(ponte)
    return identificacoes


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
