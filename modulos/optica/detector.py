"""Receptor: fotodetector de Ge + TIA, ruído e taxa de erro para M níveis."""
from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import erfc

Q_E = 1.602176634e-19


def cauda(x):
    return 0.5 * erfc(np.asarray(x, dtype=float) / math.sqrt(2))


@dataclass
class Receptor:
    responsividade_a_w: float = 0.9
    escuro_na: float = 50.0
    tia_pa_rthz: float = 15.0
    rin_db_hz: float = -145.0
    banda_rel: float = 0.7

    def banda_hz(self, baud):
        return self.banda_rel * baud

    def sigma(self, i_a, baud, i_sinal_a=None):
        """Desvio do ruído em A: térmico do TIA, shot e RIN do laser."""
        b = self.banda_hz(baud)
        i = np.asarray(i_a, dtype=float)
        sinal = i if i_sinal_a is None else np.asarray(i_sinal_a, dtype=float)
        termico = (self.tia_pa_rthz * 1e-12) ** 2 * b
        shot = 2 * Q_E * (i + self.escuro_na * 1e-9) * b
        rin = 10 ** (self.rin_db_hz / 10) * sinal ** 2 * b
        return np.sqrt(termico + shot + rin)


def bits_por_simbolo(m):
    return 1.0 if m == 2 else (1.5 if m == 3 else math.log2(m))


def ber_niveis(medias, sigmas):
    """Limiares no meio de níveis vizinhos; BER ~ SER / bits por símbolo."""
    mu = np.asarray(medias, dtype=float)
    sg = np.asarray(sigmas, dtype=float)
    ordem = np.argsort(mu)
    mu, sg = mu[ordem], sg[ordem]
    m = len(mu)
    lim = (mu[1:] + mu[:-1]) / 2
    ser = 0.0
    for k in range(m):
        if k < m - 1:
            ser += cauda((lim[k] - mu[k]) / sg[k])
        if k > 0:
            ser += cauda((mu[k] - lim[k - 1]) / sg[k])
    return float(ser / m / bits_por_simbolo(m))


def fator_q(medias, sigmas):
    mu = np.asarray(medias, dtype=float)
    sg = np.asarray(sigmas, dtype=float)
    o = np.argsort(mu)
    mu, sg = mu[o], sg[o]
    return float(np.min((mu[1:] - mu[:-1]) / (sg[1:] + sg[:-1])))


def sensibilidade_dbm(receptor, baud, er_linear, ber_alvo=1e-12, niveis=2):
    """Potência óptica média que dá a BER alvo, com a razão de extinção dada."""
    def ber(log_p):
        p = 10 ** log_p
        pmin = 2 * p / (1 + er_linear)
        pmax = pmin * er_linear
        niv = pmin + np.arange(niveis) * (pmax - pmin) / (niveis - 1)
        i = receptor.responsividade_a_w * niv
        return math.log10(max(ber_niveis(i, receptor.sigma(i, baud)), 1e-300)) - math.log10(ber_alvo)
    log_p = brentq(ber, -9, 0)
    return 10 * log_p + 30
