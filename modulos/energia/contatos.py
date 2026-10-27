"""Como a corrente de um trilho se divide entre as células e os pinos.

Rede resistiva resolvida por análise nodal: plano de cobre da base (grade
quadrada), alimentado pela zona do VRM; cada célula de energia é uma chave de
potência mais os microfios do elastômero, ligando o plano ao pino; todos os
pinos do trilho se encontram num nó só, o plano do encapsulamento (o die).
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from modulos.sistema.base import F_ENERGIA


def _celulas_do_trilho(base, configuracao, peca, trilho):
    pc = configuracao.por_nome(peca)
    cat = pc.peca
    pinos, celulas = [], []
    for j, cels in sorted(pc.celulas_do_pino.items()):
        p = cat.pinos[j]
        if p.grupo != trilho:
            continue
        cels = [c for c in cels
                if configuracao.funcao[c // base.nx, c % base.nx] == F_ENERGIA]
        if cels:
            pinos.append(j)
            celulas.append(cels)
    return pc, pinos, celulas


def distribuir(base, configuracao, peca="CPU", trilho="VCCIN", corrente_a=200.0,
               zona_vrm=None, r_folha_mohm=0.25, passo_mm=0.8, r_on_mohm=25.0,
               r_fios_mohm=5.0, r_pino_pkg_mohm=1.0, variacao_ron=0.10, semente=0,
               margem_mm=4.0):
    pc, pinos, celulas = _celulas_do_trilho(base, configuracao, peca, trilho)
    if not pinos:
        raise ValueError(f"{peca} não tem células de {trilho}")
    todas = np.concatenate([np.array(c) for c in celulas])
    cx, cy = base.centro(todas % base.nx, todas // base.nx)
    x0, x1, y0, y1 = cx.min(), cx.max(), cy.min(), cy.max()
    if zona_vrm:
        x0, x1 = min(x0, zona_vrm["x0"]), max(x1, zona_vrm["x1"])
        y0, y1 = min(y0, zona_vrm["y0"]), max(y1, zona_vrm["y1"])
    x0, y0, x1, y1 = x0 - margem_mm, y0 - margem_mm, x1 + margem_mm, y1 + margem_mm
    gx = int(np.ceil((x1 - x0) / passo_mm)) + 1
    gy = int(np.ceil((y1 - y0) / passo_mm)) + 1
    n_plano = gx * gy
    no = lambda ix, iy: iy * gx + ix

    # fontes: nós do plano dentro da zona do VRM (ou a borda esquerda, sem zona)
    xs = x0 + np.arange(gx) * passo_mm
    ys = y0 + np.arange(gy) * passo_mm
    XX, YY = np.meshgrid(xs, ys)
    if zona_vrm:
        fonte = ((XX >= zona_vrm["x0"]) & (XX <= zona_vrm["x1"])
                 & (YY >= zona_vrm["y0"]) & (YY <= zona_vrm["y1"])).ravel()
    else:
        fonte = (XX <= x0 + passo_mm).ravel()

    n_pinos = len(pinos)
    n = n_plano + n_pinos + 1            # plano, pinos, die
    die = n - 1
    linhas, colunas, valores = [], [], []

    def liga(a, b, g):
        linhas.extend([a, b, a, b]); colunas.extend([a, b, b, a])
        valores.extend([g, g, -g, -g])

    g_folha = 1.0 / (r_folha_mohm * 1e-3)       # quadrado: R = r_folha
    ix, iy = np.meshgrid(np.arange(gx), np.arange(gy))
    for a, b in ((no(ix[:, :-1], iy[:, :-1]), no(ix[:, 1:], iy[:, 1:])),
                 (no(ix[:-1, :], iy[:-1, :]), no(ix[1:, :], iy[1:, :]))):
        for u, v in zip(a.ravel(), b.ravel()):
            liga(int(u), int(v), g_folha)

    rng = np.random.default_rng(semente)
    r_cel = []
    cel_no_plano, cel_no_pino = [], []
    for k, cels in enumerate(celulas):
        for c in cels:
            x, y = base.centro(c % base.nx, c // base.nx)
            jx = int(round((float(x) - x0) / passo_mm))
            jy = int(round((float(y) - y0) / passo_mm))
            r = (r_on_mohm * (1 + variacao_ron * rng.standard_normal()) + r_fios_mohm) * 1e-3
            r_cel.append(r)
            cel_no_plano.append(no(jx, jy))
            cel_no_pino.append(n_plano + k)
            liga(no(jx, jy), n_plano + k, 1.0 / r)
    for k in range(n_pinos):
        liga(n_plano + k, die, 1.0 / (r_pino_pkg_mohm * 1e-3))

    G = sp.csr_matrix((valores, (linhas, colunas)), shape=(n, n))
    livre = np.ones(n, bool)
    livre[np.nonzero(fonte)[0]] = False         # fontes presas em 0 V (referência = saída do VRM)
    b = np.zeros(n)
    b[die] = -corrente_a
    v = np.zeros(n)
    v[livre] = spsolve(G[livre][:, livre].tocsc(), b[livre])

    r_cel = np.array(r_cel)
    i_cel = (v[cel_no_plano] - v[cel_no_pino]) / r_cel
    i_pino = np.zeros(n_pinos)
    np.add.at(i_pino, np.array(cel_no_pino) - n_plano, i_cel)

    mapa = np.zeros((base.ny, base.nx))
    todas_c = [c for cels in celulas for c in cels]
    mapa[np.array(todas_c) // base.nx, np.array(todas_c) % base.nx] = i_cel

    perda_cel = float((i_cel ** 2 * r_cel).sum())
    perda_pkg = float((i_pino ** 2 * r_pino_pkg_mohm * 1e-3).sum())
    queda = float(-v[die])
    return {
        "peca": peca, "trilho": trilho, "corrente_a": corrente_a,
        "pinos": n_pinos, "celulas": len(i_cel),
        "corrente_pino": i_pino, "corrente_celula": i_cel,
        "pino_max_a": float(i_pino.max()), "pino_medio_a": float(i_pino.mean()),
        "pinos_acima_1a": int((i_pino > 1.0).sum()),
        "celula_max_a": float(i_cel.max()), "celula_media_a": float(i_cel.mean()),
        "celulas_acima_1a": int((i_cel > 1.0).sum()),
        "queda_ir_mv": queda * 1e3,
        "perdas_w": perda_cel + perda_pkg + _perda_plano(v, G, n_plano),
        "perda_celulas_w": perda_cel,
        "mapa_corrente": mapa,
        "soma_pinos_a": float(i_pino.sum()),
    }


def _perda_plano(v, G, n_plano):
    """Perda no cobre do plano: v^T L v, com L a laplaciana só das arestas plano-plano."""
    diag_celulas = np.asarray(G[:n_plano, n_plano:].sum(axis=1)).ravel()
    L = G[:n_plano, :n_plano] + sp.diags(diag_celulas)
    vp = v[:n_plano]
    return float(vp @ (L @ vp))
