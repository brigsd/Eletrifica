"""Anéis de silício: modulador (só barramento) e filtro de demultiplexação (add-drop).

Modelo de anel acoplado a guia, em campo complexo. A fase de ida e volta é
linearizada em torno da ressonância: phi = -2*pi*(lambda - lambda_res) / FSR,
o que vale para qualquer ordem de ressonância (é periódico em FSR).
"""
from dataclasses import dataclass, field
import math

import numpy as np
from scipy.optimize import brentq

C = 299_792_458.0


def _r_para_largura(a, largura_nm, fsr_nm):
    """Acha o coeficiente de acoplamento r (sobreacoplado, r < a) que dá a largura pedida."""
    def largura(r):
        return (1 - r * a) * fsr_nm / (math.pi * math.sqrt(r * a))
    return brentq(lambda r: largura(r) - largura_nm, 0.5, a * 0.999999)


@dataclass
class Anel:
    raio_um: float = 5.0
    n_g: float = 4.2
    perda_db_cm: float = 40.0        # guia dopada (junção PN)
    q_carregado: float = 6000.0
    lambda_nm: float = 1310.0
    eficiencia_pm_v: float = 40.0    # deslocamento da ressonância por volt (depleção)
    dn_dT: float = 1.8e-4            # termo-óptico efetivo do Si
    aquecedor_nm_mw: float = 0.25
    tau_termico_us: float = 8.0
    r: float = field(init=False)

    def __post_init__(self):
        self.r = _r_para_largura(self.a, self.largura_nm, self.fsr_nm)

    @property
    def comprimento_m(self):
        return 2 * math.pi * self.raio_um * 1e-6

    @property
    def fsr_nm(self):
        return (self.lambda_nm * 1e-9) ** 2 / (self.n_g * self.comprimento_m) * 1e9

    @property
    def a(self):
        return 10 ** (-self.perda_db_cm * self.comprimento_m * 100 / 20)

    @property
    def largura_nm(self):
        return self.lambda_nm / self.q_carregado

    @property
    def largura_ghz(self):
        return C * self.largura_nm * 1e-9 / (self.lambda_nm * 1e-9) ** 2 / 1e9

    @property
    def tau_foton_ps(self):
        return self.q_carregado * self.lambda_nm * 1e-9 / (2 * math.pi * C) * 1e12

    @property
    def dlambda_dT_nm(self):
        return self.lambda_nm * self.dn_dT / self.n_g

    @property
    def kelvin_por_mw(self):
        return self.aquecedor_nm_mw / self.dlambda_dT_nm

    def fase(self, lam_nm, res_nm):
        return -2 * math.pi * (np.asarray(lam_nm) - np.asarray(res_nm)) / self.fsr_nm

    def campo(self, lam_nm, res_nm):
        e = np.exp(1j * self.fase(lam_nm, res_nm))
        return (self.r - self.a * e) / (1 - self.r * self.a * e)

    def transmissao(self, lam_nm, res_nm):
        return np.abs(self.campo(lam_nm, res_nm)) ** 2

    def atraso_grupo_ps(self, lam_nm, res_nm, d=1e-4):
        """-d(fase)/d(omega) do campo transmitido."""
        f1 = np.angle(self.campo(lam_nm - d, res_nm))
        f2 = np.angle(self.campo(lam_nm + d, res_nm))
        dfase = np.angle(np.exp(1j * (f2 - f1)))
        lam = self.lambda_nm * 1e-9
        domega = -2 * math.pi * C * (2 * d * 1e-9) / lam ** 2
        return -dfase / domega * 1e12


@dataclass
class FiltroAddDrop:
    """Anel de demultiplexação simétrico, guia sem dopagem."""
    raio_um: float = 5.0
    n_g: float = 4.2
    perda_db_cm: float = 3.0
    q_carregado: float = 5000.0
    lambda_nm: float = 1310.0
    r: float = field(init=False)

    def __post_init__(self):
        # simétrico: r1 = r2 = r, então a largura depende de r*r*a
        self.r = brentq(lambda r: (1 - r * r * self.a) * self.fsr_nm
                        / (math.pi * math.sqrt(r * r * self.a)) - self.largura_nm, 0.5, 0.999999)

    comprimento_m = Anel.comprimento_m
    fsr_nm = Anel.fsr_nm
    a = Anel.a
    largura_nm = Anel.largura_nm
    fase = Anel.fase

    @property
    def tau_foton_ps(self):
        return self.q_carregado * self.lambda_nm * 1e-9 / (2 * math.pi * C) * 1e12

    def _den(self, lam_nm, res_nm):
        return 1 - self.r * self.r * self.a * np.exp(1j * self.fase(lam_nm, res_nm))

    def queda(self, lam_nm, res_nm):
        """Potência que sai pela porta drop."""
        e = np.exp(1j * self.fase(lam_nm, res_nm) / 2)
        num = (1 - self.r ** 2) * math.sqrt(self.a) * e
        return np.abs(num / self._den(lam_nm, res_nm)) ** 2

    def passagem(self, lam_nm, res_nm):
        e = np.exp(1j * self.fase(lam_nm, res_nm))
        return np.abs((self.r - self.r * self.a * e) / self._den(lam_nm, res_nm)) ** 2
