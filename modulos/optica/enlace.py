"""Enlace óptico de um pino: anel modulador -> fibra WDM -> filtro add-drop -> PD/TIA.

Três níveis de detalhe:
- calculo_simples: o cálculo de orçamento do documento do projeto, como foi escrito;
- orcamento: modelo físico estático com o anel real, diafonia e ruído;
- simular_canal: simulação no tempo, todos os canais da fibra com dados aleatórios.
"""
import copy
import json
import math
from dataclasses import dataclass

import numpy as np
from scipy import signal
from scipy.optimize import brentq

from modulos.caminhos import PROJETOS
from modulos.optica.anel import C, Anel, FiltroAddDrop
from modulos.optica.detector import Receptor, ber_niveis, bits_por_simbolo, fator_q, sensibilidade_dbm

ARQUIVO = PROJETOS / "interconexao-optica" / "enlace.json"


def carregar(nome="ajustada", caminho=None):
    data = json.loads((caminho or ARQUIVO).read_text())
    cfg = copy.deepcopy(data["comum"])
    for k, v in copy.deepcopy(data[nome]).items():     # dicionários (anel, filtro) mesclam
        cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    cfg["nome"] = nome
    return cfg


def calculo_simples(cfg):
    """O script do documento, com os mesmos números."""
    pinos, gbps, lambdas = cfg["pinos"], cfg["gbps_por_pino"], cfg["canais_por_fibra"]
    banda_TBps = pinos * gbps / 8 / 1000
    fibras = -(-pinos // lambdas)
    prop_ns = cfg["fibra_cm"] / 100 * 1e9 / (3e8 / cfg["n_g_fibra"])
    atraso = prop_ns + cfg["atraso_mod_ns"] + cfg["atraso_det_ns"]
    canal = 10 * math.log10(cfg["laser_mw"]) - 10 * math.log10(cfg["lambdas_por_laser"])
    recebido = canal - cfg["perdas_db"]
    return {"canal_dbm": canal, "recebido_dbm": recebido,
            "margem_db": recebido - cfg["sensibilidade_ref_dbm"],
            "banda_TBps": banda_TBps, "fibras": fibras, "atraso_ns": atraso}


# ---- peças do modelo físico -------------------------------------------------

def _anel(cfg):
    a = cfg["anel"]
    return Anel(raio_um=a["raio_um"], n_g=a["n_g"], perda_db_cm=a["perda_db_cm"],
                q_carregado=a["q_carregado"], lambda_nm=cfg["lambda_nm"],
                eficiencia_pm_v=a["eficiencia_pm_v"], dn_dT=a["dn_dT"],
                aquecedor_nm_mw=a["aquecedor_nm_mw"], tau_termico_us=a["tau_termico_us"])


def _filtro(cfg):
    f = cfg["filtro"]
    return FiltroAddDrop(raio_um=f["raio_um"], n_g=f["n_g"], perda_db_cm=f["perda_db_cm"],
                         q_carregado=f["q_carregado"], lambda_nm=cfg["lambda_nm"])


def _receptor(cfg):
    return Receptor(**cfg["receptor"])


def niveis_de(simbolo):
    return 3 if simbolo == "PAM3" else 2


def baud_de(cfg, simbolo):
    return cfg["gbps_por_pino"] * 1e9 / bits_por_simbolo(niveis_de(simbolo))


def grade(cfg, anel=None):
    anel = anel or _anel(cfg)
    n = cfg["canais_por_fibra"]
    esp = cfg.get("espacamento_nm") or anel.fsr_nm / n
    return cfg["lambda_nm"] + (np.arange(n) - (n - 1) / 2) * esp, esp


def _tensoes(cfg, m):
    return np.arange(m) * cfg["driver"]["vpp"] / (m - 1)


def ponto_operacao(anel, tensoes):
    """Dessintonia laser-anel (nm) que maximiza a amplitude óptica entre os níveis extremos."""
    w = anel.largura_nm
    deltas = np.linspace(-3 * w, 3 * w, 1201)
    desloc = anel.eficiencia_pm_v * 1e-3 * tensoes
    t = anel.transmissao(0.0, deltas[:, None] + desloc[None, :])
    oma = np.abs(t[:, -1] - t[:, 0])
    return float(deltas[np.argmax(oma)])


def _wrap(d, fsr):
    return (d + fsr / 2) % fsr - fsr / 2


def _ganhos_rx(filtro, lam):
    """g[k, j]: fração da potência de lambda_j que chega ao PD do canal k (cascata de filtros)."""
    n = len(lam)
    queda = filtro.queda(lam[None, :], lam[:, None])        # [filtro k, canal j]
    passa = filtro.passagem(lam[None, :], lam[:, None])
    antes = np.vstack([np.ones(n), np.cumprod(passa, axis=0)[:-1]])
    return queda * antes


def _estatica(cfg, erro_nm, simbolo, ganho=1.0):
    anel, filtro, rx = _anel(cfg), _filtro(cfg), _receptor(cfg)
    m = niveis_de(simbolo)
    baud = baud_de(cfg, simbolo)
    lam, esp = grade(cfg, anel)
    n = len(lam)
    k = n // 2
    v = _tensoes(cfg, m)
    desloc = anel.eficiencia_pm_v * 1e-3 * v
    d0 = ponto_operacao(anel, v)

    t_nom = anel.transmissao(0.0, d0 + desloc)                  # níveis de um canal qualquer
    t_alvo = anel.transmissao(0.0, d0 + desloc + erro_nm)        # o canal em teste
    # barramento TX: a luz de lambda_k passa por todos os outros anéis
    outros = [i for i in range(n) if i != k]
    res = lam[outros][:, None] + d0 + desloc[None, :]
    t_out = anel.transmissao(lam[k], res)
    e1, e2 = t_out.mean(1), (t_out ** 2).mean(1)
    m1, m2 = float(np.prod(e1)), float(np.prod(e2))
    var_rel = max(m2 - m1 ** 2, 0.0) / m1 ** 2

    p_ch = cfg["laser_mw"] * 1e-3 / cfg["lambdas_por_laser"] * 10 ** (-cfg["perdas_db"] / 10) * ganho
    g = _ganhos_rx(filtro, lam)[k]
    p_k = p_ch * m1 * t_alvo * g[k]                              # níveis no PD, W
    media_outro = p_ch * m1 * t_nom.mean()
    var_outro = (p_ch * m1) ** 2 * t_nom.var()
    gx = np.delete(g, k)
    xt_media = float((gx * media_outro).sum())
    xt_var = float((gx ** 2 * var_outro).sum())

    r = rx.responsividade_a_w
    i_sinal = r * p_k
    i_tot = i_sinal + r * xt_media
    sig = np.sqrt(rx.sigma(i_tot, baud, i_sinal) ** 2
                  + r ** 2 * (var_rel * p_k ** 2 + xt_var))
    return {"anel": anel, "filtro": filtro, "rx": rx, "baud": baud, "esp": esp, "d0": d0,
            "t_nom": t_nom, "t_alvo": t_alvo, "p_ch": p_ch, "p_k": p_k, "i": i_tot, "sigma": sig,
            "ber": ber_niveis(i_tot, sig), "q": fator_q(i_tot, sig), "xt_media": xt_media,
            "var_rel": var_rel, "g": g, "k": k, "m1": m1}


def ber_estatica(cfg, erro_nm=0.0, simbolo=None):
    return _estatica(cfg, erro_nm, simbolo or cfg["simbolo"])["ber"]


def margem_db(cfg, erro_nm=0.0, simbolo=None):
    """Perda extra que o enlace aguenta antes de passar da BER alvo (-inf: piso de diafonia)."""
    simbolo = simbolo or cfg["simbolo"]
    alvo = cfg["ber_alvo"]

    def falta(log_g):
        b = _estatica(cfg, erro_nm, simbolo, 10 ** log_g)["ber"]
        return math.log10(max(b, 1e-300)) - math.log10(alvo)

    if falta(3.0) > 0:
        return -math.inf
    if falta(-3.0) < 0:
        return 30.0
    return -10 * brentq(falta, -3.0, 3.0, xtol=1e-4)


def orcamento(cfg, erro_nm=0.0, simbolo=None):
    simbolo = simbolo or cfg["simbolo"]
    s = _estatica(cfg, erro_nm, simbolo)
    alvo = cfg["ber_alvo"]
    t = s["t_nom"]
    er = float(t.max() / t.min())
    rx, baud = s["rx"], s["baud"]
    margem = margem_db(cfg, erro_nm, simbolo)
    p_med = float(s["p_k"].mean())
    return {
        "simbolo": simbolo, "baud_g": baud / 1e9,
        "fsr_nm": s["anel"].fsr_nm, "largura_nm": s["anel"].largura_nm,
        "espacamento_nm": s["esp"], "dessintonia_nm": s["d0"],
        "il_modulador_db": -10 * math.log10(t.max()), "er_db": 10 * math.log10(er),
        "canal_dbm": 10 * math.log10(s["p_ch"] / 10 ** (-cfg["perdas_db"] / 10) * 1e3),
        "recebido_dbm": 10 * math.log10(p_med * 1e3),
        "oma_uw": float((s["p_k"].max() - s["p_k"].min()) * 1e6),
        "diafonia_rx_db": 10 * math.log10(max(s["xt_media"], 1e-30) / p_med),
        "perda_barramento_tx_db": -10 * math.log10(s["m1"]),
        "q": s["q"], "ber": s["ber"],
        "sensibilidade_dbm": sensibilidade_dbm(rx, baud, er, alvo, niveis_de(simbolo)),
        "margem_db": margem,
    }


# ---- simulação no tempo -------------------------------------------------------

BER_OLHO = 1e-6     # nível em que a largura do olho é medida


@dataclass
class ResultadoCanal:
    ber_estimada: float
    erros_contados: int
    simbolos: int
    q: float
    atraso_ps: float
    largura_olho_ui: float
    altura_olho_ua: float
    rlm: float
    olho: dict


def _passa_baixa_1(x, tau_s, fs):
    a = 1 - math.exp(-1 / (tau_s * fs))
    return signal.lfilter([a], [1, a - 1], x, axis=-1)


def _butter(x, fc, fs, ordem=2):
    b, a = signal.butter(ordem, min(fc / (fs / 2), 0.99))
    return signal.lfilter(b, a, x, axis=-1)


def simular_canal(cfg, n_simbolos=4096, semente=0, erro_nm=0.0, simbolo=None, amostras=16):
    simbolo = simbolo or cfg["simbolo"]
    anel, filtro, rx = _anel(cfg), _filtro(cfg), _receptor(cfg)
    rng = np.random.default_rng(semente)
    m = niveis_de(simbolo)
    baud = baud_de(cfg, simbolo)
    fs = baud * amostras
    lam, _ = grade(cfg, anel)
    n = len(lam)
    k = n // 2
    v = _tensoes(cfg, m)
    d0 = ponto_operacao(anel, v)
    t_estat = anel.transmissao(0.0, d0 + anel.eficiencia_pm_v * 1e-3 * v)
    mapa = v if t_estat[-1] > t_estat[0] else v[::-1]           # símbolo maior = mais luz

    simb = rng.integers(0, m, size=(n, n_simbolos))
    g = _ganhos_rx(filtro, lam)[k]
    rel_rx = np.nonzero(g > 1e-4)[0]
    alcance = 8 * anel.largura_nm + anel.eficiencia_pm_v * 1e-3 * v[-1] + abs(erro_nm)

    cache = {}

    def deslocamento(i):
        if i not in cache:
            onda = np.repeat(mapa[simb[i]], amostras)
            onda = _butter(onda, cfg["driver"]["banda_rel"] * baud, fs)
            cache[i] = anel.eficiencia_pm_v * 1e-3 * onda + (erro_nm if i == k else 0.0)
        return cache[i]

    p_ch = cfg["laser_mw"] * 1e-3 / cfg["lambdas_por_laser"] * 10 ** (-cfg["perdas_db"] / 10)
    tau_anel = anel.tau_foton_ps * 1e-12
    p_pd = np.zeros(n_simbolos * amostras)
    for j in rel_rx:
        trans = np.ones(n_simbolos * amostras)
        for i in range(n):
            if abs(_wrap(lam[j] - lam[i] - d0, anel.fsr_nm)) > alcance:
                continue
            t = anel.transmissao(lam[j], lam[i] + d0 + deslocamento(i))
            trans *= _passa_baixa_1(t, tau_anel, fs)
        p_pd += g[j] * p_ch * trans
    p_pd = _passa_baixa_1(p_pd, filtro.tau_foton_ps * 1e-12, fs)

    r = rx.responsividade_a_w
    i_pd = r * p_pd + rx.escuro_na * 1e-9
    esc = math.sqrt(fs / 2)
    ruido = (rx.tia_pa_rthz * 1e-12 * esc * rng.standard_normal(i_pd.size)
             + np.sqrt(2 * 1.602176634e-19 * i_pd) * esc * rng.standard_normal(i_pd.size)
             + r * p_pd * math.sqrt(10 ** (rx.rin_db_hz / 10)) * esc * rng.standard_normal(i_pd.size))
    saida = _butter(i_pd + ruido, rx.banda_rel * baud, fs)

    # atraso: correlação com a sequência ideal do canal em teste
    ideal = np.repeat(simb[k].astype(float), amostras)
    a = saida - saida.mean()
    b = ideal - ideal.mean()
    corr = signal.correlate(a, b, mode="full", method="fft")
    lags = np.arange(-len(b) + 1, len(a))
    janela = (lags >= 0) & (lags < 10 * amostras)
    lag = int(lags[janela][np.argmax(corr[janela])])

    pula = 64
    idx_s = np.arange(pula, n_simbolos - pula)
    por_fase = {}
    for fase in range(-amostras, 2 * amostras):
        pos = lag + fase + amostras * idx_s
        ok = (pos >= 0) & (pos < saida.size)
        y, s = saida[pos[ok]], simb[k][idx_s[ok]]
        mu = np.array([y[s == q].mean() for q in range(m)])
        sg = np.array([y[s == q].std() for q in range(m)])
        por_fase[fase] = (ber_niveis(mu, sg), mu, sg, y, s)
    fase = min(por_fase, key=lambda f: por_fase[f][0])
    ber, mu, sg, y, s = por_fase[fase]
    abertos = sum(1 for f in range(fase - amostras // 2, fase + amostras // 2)
                  if por_fase.get(f, (1.0,))[0] <= BER_OLHO)
    lim = (mu[1:] + mu[:-1]) / 2
    decidido = np.searchsorted(lim, y)
    erros = int((decidido != s).sum())
    altura = min(float(y[s == q + 1].min() - y[s == q].max()) for q in range(m - 1))
    d = np.diff(mu)
    rlm = float(d.min() / d.mean())

    inicio = lag + fase - amostras // 2
    tr = []
    for p in range(pula, min(pula + 300, n_simbolos - 3)):
        a0 = inicio + p * amostras
        if a0 + 2 * amostras <= saida.size:
            tr.append(saida[a0:a0 + 2 * amostras] * 1e6)
    olho = {"t_ui": (np.arange(2 * amostras) / amostras).tolist(),
            "amostras_ua": np.array(tr).round(3).tolist(),
            "limiares_ua": (lim * 1e6).tolist()}
    atraso_ps = (lag + fase - amostras / 2) / fs * 1e12
    return ResultadoCanal(ber, erros, int(len(y) * bits_por_simbolo(m)), fator_q(mu, sg),
                          atraso_ps, abertos / amostras, altura * 1e6, rlm, olho)


def varrer(cfg, canais_por_fibra=(8, 16, 32, 64), raios_um=(5.0, 3.5, 2.5), simbolo=None):
    out = []
    for raio in raios_um:
        for n in canais_por_fibra:
            c = copy.deepcopy(cfg)
            c["canais_por_fibra"] = n
            c["espacamento_nm"] = None
            c["anel"]["raio_um"] = raio
            c["filtro"]["raio_um"] = raio
            o = orcamento(c, simbolo=simbolo)
            out.append({"raio_um": raio, "canais_por_fibra": n,
                        "fibras": -(-cfg["pinos"] // n), "espacamento_nm": o["espacamento_nm"],
                        "fsr_nm": o["fsr_nm"], "margem_db": o["margem_db"], "ber": o["ber"],
                        "diafonia_rx_db": o["diafonia_rx_db"]})
    return out


def atraso_total_ps(cfg, comprimento_m, medido_ps=None):
    if medido_ps is None:
        medido_ps = simular_canal(cfg, n_simbolos=1024).atraso_ps
    return comprimento_m * cfg["n_g_fibra"] / C * 1e12 + medido_ps
