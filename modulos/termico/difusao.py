"""Calor na base: difusão 2D no cobre + LCP, com convecção nas duas faces.

Grade grossa (2 mm). Fontes: a parte do calor de cada peça que desce para a
base (o resto vai ao dissipador da peça), as perdas do VRM espalhadas na sua
zona e as perdas dos contatos sob a CPU. Bordas adiabáticas.
"""
import math
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

# camadas da base
COBRE_ESP_M = 2 * 70e-6          # dois planos de 2 oz
K_COBRE, RHOC_COBRE = 390.0, 3.45e6
LCP_ESP_M = 1.0e-3
K_LCP, RHOC_LCP = 0.3, 1.6e6


@dataclass
class ResultadoTermico:
    passo_mm: float
    t_amb: float
    regime: np.ndarray            # (gy, gx) °C
    tempos_s: np.ndarray
    quadros: np.ndarray           # (n_tempos, gy, gx) °C
    fontes_w: np.ndarray          # (gy, gx) W por nó
    perda_conveccao_w: float      # em regime
    tradutores: dict              # nome -> {"x", "y", "regime_c"}

    def _amostra(self, campo, x, y):
        gy, gx = campo.shape
        fx = np.clip(x / self.passo_mm - 0.5, 0, gx - 1.000001)
        fy = np.clip(y / self.passo_mm - 0.5, 0, gy - 1.000001)
        i, j = int(fx), int(fy)
        ax, ay = fx - i, fy - j
        return float((1 - ax) * (1 - ay) * campo[j, i] + ax * (1 - ay) * campo[j, i + 1]
                     + (1 - ax) * ay * campo[j + 1, i] + ax * ay * campo[j + 1, i + 1])

    def temperatura_em(self, x, y, t=None):
        """°C no ponto (mm) no instante t (s) depois de ligar; None ou além do fim = regime."""
        if t is None or t >= self.tempos_s[-1]:
            return self._amostra(self.regime, x, y)
        k = int(np.searchsorted(self.tempos_s, t))
        if k == 0:
            return self._amostra(self.quadros[0], x, y)
        t0, t1 = self.tempos_s[k - 1], self.tempos_s[k]
        a = (t - t0) / (t1 - t0)
        return ((1 - a) * self._amostra(self.quadros[k - 1], x, y)
                + a * self._amostra(self.quadros[k], x, y))


def _retangulo(pc):
    cat = pc.peca
    c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
    return c, s, cat.largura / 2, cat.profundidade / 2


def _espalhar(fontes, passo, xs, ys, dentro, potencia):
    m = dentro(xs, ys)
    if m.sum() == 0 or potencia == 0:
        return
    fontes[m] += potencia / m.sum()


def locais_tradutores(configuracao, afastamento_mm=2.0):
    """Tradutor na borda da peça voltada para a peça-par mais próxima."""
    pos = {}
    pecas = configuracao.pecas
    for pc in pecas:
        cat = pc.peca
        pares = {i.par for i in cat.interfaces.values()}
        candidatos = [o for o in pecas if o is not pc and o.tipo in pares]
        if not candidatos:
            continue
        alvo = min(candidatos, key=lambda o: math.hypot(o.x - pc.x, o.y - pc.y))
        c, s, w, d = _retangulo(pc)
        bordas = [(w + afastamento_mm, 0), (-w - afastamento_mm, 0),
                  (0, d + afastamento_mm), (0, -d - afastamento_mm)]
        pts = [(pc.x + c * bx - s * by, pc.y + s * bx + c * by) for bx, by in bordas]
        pos[pc.nome] = min(pts, key=lambda p: math.hypot(p[0] - alvo.x, p[1] - alvo.y))
    return pos


def simular(base, configuracao, zonas, carga="max", perdas_vrm_w=15.0,
            perdas_contatos_w=5.0, passo_mm=2.0, t_amb=35.0, h_conv=30.0, tempos_s=None):
    """h_conv em W/(m².K) por face: ~30 com ar forçado do gabinete, ~10-15 em convecção natural."""
    gx = int(math.ceil(base.largura / passo_mm))
    gy = int(math.ceil(base.profundidade / passo_mm))
    xs = (np.arange(gx) + 0.5) * passo_mm
    ys = (np.arange(gy) + 0.5) * passo_mm
    X, Y = np.meshgrid(xs, ys)
    fontes = np.zeros((gy, gx))

    for pc in configuracao.pecas:
        cat = pc.peca
        p = (cat.potencia_max if carga == "max" else cat.potencia_tipica) * cat.fracao_calor_base
        c, s, w, d = _retangulo(pc)

        def dentro(x, y, pc=pc, c=c, s=s, w=w, d=d):
            dx, dy = x - pc.x, y - pc.y
            u, v = c * dx + s * dy, -s * dx + c * dy
            return (np.abs(u) <= w) & (np.abs(v) <= d)
        _espalhar(fontes, passo_mm, X, Y, dentro, p)
        if pc.nome == "CPU":
            _espalhar(fontes, passo_mm, X, Y, dentro, perdas_contatos_w)
    z = zonas.get("vrm_cpu")
    if z:
        _espalhar(fontes, passo_mm, X, Y,
                  lambda x, y: (x >= z["x0"]) & (x <= z["x1"]) & (y >= z["y0"]) & (y <= z["y1"]),
                  perdas_vrm_w)

    h = passo_mm * 1e-3
    g_lat = K_COBRE * COBRE_ESP_M + K_LCP * LCP_ESP_M      # W/K entre nós vizinhos (quadrado)
    g_conv = 2 * h_conv * h * h
    cap = (RHOC_COBRE * COBRE_ESP_M + RHOC_LCP * LCP_ESP_M) * h * h
    n = gx * gy
    idx = np.arange(n).reshape(gy, gx)
    a = np.concatenate([idx[:, :-1].ravel(), idx[:-1, :].ravel()])
    b = np.concatenate([idx[:, 1:].ravel(), idx[1:, :].ravel()])
    L = sp.coo_matrix((np.full(len(a), -g_lat), (a, b)), shape=(n, n))
    L = L + L.T
    grau = -np.asarray(L.sum(axis=1)).ravel()
    K = (L + sp.diags(grau + g_conv)).tocsc()           # K (T - Tamb) = q

    q = fontes.ravel()
    theta = splu(K).solve(q)
    regime = t_amb + theta.reshape(gy, gx)
    perda_conv = float(g_conv * theta.sum())

    if tempos_s is None:
        tempos_s = np.concatenate([[0.0], np.logspace(-1, 3.6, 36)])
    quadros = [np.full((gy, gx), t_amb)]
    th = np.zeros(n)
    for t0, t1 in zip(tempos_s[:-1], tempos_s[1:]):
        dt = t1 - t0
        lu = splu((sp.diags(np.full(n, cap / dt)) + K).tocsc())
        th = lu.solve(cap / dt * th + q)
        quadros.append(t_amb + th.reshape(gy, gx))

    res = ResultadoTermico(passo_mm, t_amb, regime, np.asarray(tempos_s), np.array(quadros),
                           fontes, perda_conv, {})
    for nome, (x, y) in locais_tradutores(configuracao).items():
        res.tradutores[nome] = {"x": x, "y": y, "regime_c": res.temperatura_em(x, y)}
    return res
