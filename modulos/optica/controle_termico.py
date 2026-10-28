"""Controle térmico do anel: aquisição a partir do frio e travamento por lado da franja.

O anel sai de fábrica com a ressonância deslocada para o azul; o aquecedor só
desloca para o vermelho. Na partida o aquecedor sobe em rampa até o monitor
(potência média na porta de passagem) cruzar o ponto de operação pelo lado
certo; daí um PI segura a sintonia contra a temperatura ambiente.
"""
import math

import numpy as np
from scipy.optimize import brentq

from modulos.optica import enlace as E


def curva_ber(cfg, simbolo=None, faixa_nm=0.4, pontos=161):
    erros = np.linspace(-faixa_nm, faixa_nm, pontos)
    log_ber = np.array([math.log10(max(E.ber_estatica(cfg, e, simbolo), 1e-300))
                        for e in erros])
    return erros, log_ber


def _limite(cfg, simbolo, m0, penalidade, sinal):
    f = lambda e: m0 - E.margem_db(cfg, sinal * e, simbolo) - penalidade
    passo, e = 0.002, 0.0
    while e < 0.5:
        if f(e + passo) > 0:
            return brentq(lambda x: min(f(x), 50.0), e, e + passo, xtol=1e-5)
        e += passo
    return 0.5


def janela_termica(cfg, simbolo=None, penalidade_db=1.0):
    """Quanto o anel pode esquentar ou esfriar, sem controle.

    `kelvin` é a janela para `penalidade_db` de perda de margem; `kelvin_ber_alvo`
    é a janela até a BER alvo (só existe se a margem com sintonia perfeita for positiva).
    """
    anel = E._anel(cfg)
    simbolo = simbolo or cfg["simbolo"]
    m0 = E.margem_db(cfg, 0.0, simbolo)
    out = {"margem_0_db": m0, "penalidade_db": penalidade_db,
           "erro_max_pm": 0.0, "kelvin": 0.0, "kelvin_ber_alvo": 0.0}
    if not math.isfinite(m0):
        return out
    erro = min(_limite(cfg, simbolo, m0, penalidade_db, s) for s in (1, -1))
    out["erro_max_pm"] = erro * 1e3
    out["kelvin"] = erro / anel.dlambda_dT_nm
    if m0 > 0:
        e_alvo = min(_limite(cfg, simbolo, m0, m0, s) for s in (1, -1))
        out["kelvin_ber_alvo"] = e_alvo / anel.dlambda_dT_nm
    return out


def simular(cfg, perturbacao_K, duracao_us, dt_us=0.1, controle=True, semente=0,
            simbolo=None, a_cada=10):
    simbolo = simbolo or cfg["simbolo"]
    t_cfg = cfg["termico"]
    anel = E._anel(cfg)
    rng = np.random.default_rng(semente)
    m = E.niveis_de(simbolo)
    desloc = anel.eficiencia_pm_v * 1e-3 * E._tensoes(cfg, m)
    d0 = E.ponto_operacao(anel, desloc / (anel.eficiencia_pm_v * 1e-3))

    def monitor(delta):
        return float(anel.transmissao(0.0, delta + desloc).mean())

    alvo = monitor(d0)
    inclinacao = (monitor(d0 + 1e-3) - monitor(d0 - 1e-3)) / 2e-3
    frio = d0 + t_cfg["desvio_frio_nm"] + rng.normal(0, t_cfg["variacao_fabricacao_nm"])
    eff = anel.aquecedor_nm_mw
    kpm = anel.kelvin_por_mw
    tau = anel.tau_termico_us
    pmax = t_cfg["aquecedor_max_mw"]
    kp = t_cfg["kp"]
    ki = kp / tau

    erros_c, log_ber_c = curva_ber(cfg, simbolo)

    if controle:
        ph, temp, estado, integ = 0.0, 0.0, "rampa", 0.0
    else:
        ph = (d0 - frio) / eff
        temp, estado, integ = kpm * ph, "fixo", ph
    minimo, saturado, perdas = 1.0, 0.0, 0
    passos = int(round(duracao_us / dt_us))
    serie = {k: [] for k in ("tempo_us", "perturbacao_K", "temperatura_K", "aquecedor_mw",
                             "erro_pm", "log10_ber", "travado")}
    travou_em = None
    for n in range(passos):
        t = n * dt_us
        amb = perturbacao_K(t)
        temp += (amb + kpm * ph - temp) * dt_us / tau
        delta = frio + anel.dlambda_dT_nm * temp
        medido = monitor(delta) + rng.normal(0, t_cfg["ruido_monitor"])
        if estado == "rampa":
            ph = min(ph + t_cfg["rampa_aquisicao_mw_us"] * dt_us, pmax)
            minimo = min(minimo, medido)
            cruzou = (medido <= alvo) if inclinacao < 0 else (minimo < alvo - 0.05 and medido >= alvo)
            if cruzou:
                estado, integ, travou_em = "travado", ph, t
            elif ph >= pmax:                       # varreu a faixa toda sem achar: recomeça
                ph, minimo = 0.0, 1.0
        elif estado == "travado":
            e_nm = (medido - alvo) / inclinacao
            integ = min(max(integ - ki * e_nm / eff * dt_us, 0.0), pmax)
            ph = min(max(integ - kp * e_nm / eff, 0.0), pmax)
            saturado = saturado + dt_us if ph in (0.0, pmax) else 0.0
            if saturado > 5 * tau:                 # passou para o outro lado da ressonância
                estado, ph, minimo, saturado = "rampa", 0.0, 1.0, 0.0
                perdas += 1
        if n % a_cada == 0:
            erro = delta - d0
            serie["tempo_us"].append(t)
            serie["perturbacao_K"].append(amb)
            serie["temperatura_K"].append(temp)
            serie["aquecedor_mw"].append(ph)
            serie["erro_pm"].append(erro * 1e3)
            serie["log10_ber"].append(float(np.interp(erro, erros_c, log_ber_c,
                                                      left=0.0, right=0.0)))
            serie["travado"].append(estado != "rampa")
    out = {k: np.array(v) for k, v in serie.items()}
    out["travou_em_us"] = travou_em
    out["perdas_de_travamento"] = perdas
    out["ressonancia_fria_nm"] = frio - d0
    return out
