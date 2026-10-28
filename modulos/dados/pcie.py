"""Treino do PCIe 5.0 através do tradutor óptico.

Três coisas que um fio faz sozinho e o tradutor precisa fazer de propósito:

1. Detecção de receptor: o transmissor descobre se há alguém do outro lado
   medindo a terminação. Quem ele mede é o tradutor vizinho; o tradutor só
   pode apresentar terminação quando o FPGA sabe que a peça do outro lado foi
   identificada e o enlace óptico travou.
2. Ocioso elétrico: entrar e sair dele tem de atravessar a luz (squelch), com
   latência dentro do que a especificação dá ao transmissor.
3. Equalização: o canal agora é trilha + tradutor + luz + receptor óptico +
   driver + trilha, e o anel não é linear. Os presets de FFE do transmissor e
   o CTLE/DFE do receptor precisam abrir o olho através disso.

Tempos e limites são os típicos da especificação PCIe 5.0, simplificados.
"""
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from modulos.optica import enlace as E

UI_GEN1_NS = 0.4                    # 2,5 GT/s
DETECT_QUIET_MS = 12.0              # timeout de Detect.Quiet
DETECT_TENTATIVAS = 3               # ciclos Detect sem receptor antes de desistir
POLLING_TS1 = 1024
TS_SIMBOLOS = 16
POLLING_TIMEOUT_MS = 24.0
POLLING_CONFIG_US = 2.0
CONFIGURATION_US = 50.0
RECOVERY_SPEED_US = 200.0
EQ_FASE01_MS = 1.0
EQ_AVALIACAO_PRESET_MS = 1.0        # o receptor avalia um preset pedido
EQ_FASE_TIMEOUT_MS = 24.0
LIMITE_SQUELCH_PS = 8000.0          # T_TX-IDLE-TO-DIFF-DATA

AMOSTRAS_UI = 32
N_BITS = 2048
CTLE_GANHOS_DB = (0, 2, 4, 6, 8, 10, 12)
CTLE_POLO_REL = (0.5, 1.0)          # polos em fração do baud (Nyquist e baud)
TRADUTOR_BANDA_GHZ = 45.0           # driver + entrada do modulador; e driver de saída
RUIDO_REL = 0.03                    # ruído do receptor óptico, rms, em fração da excursão
OLHO_MIN_ALTURA_REL = 0.15
OLHO_MIN_LARGURA_UI = 0.30

# presets do transmissor: (preshoot dB, de-ênfase dB)
PRESETS = {"P0": (0.0, -6.0), "P1": (0.0, -3.5), "P2": (0.0, -4.4), "P3": (0.0, -2.5),
           "P4": (0.0, 0.0), "P5": (1.9, 0.0), "P6": (2.5, 0.0), "P7": (3.5, -6.0),
           "P8": (3.5, -3.5), "P9": (3.5, 0.0), "P10": (0.0, -9.5)}


def coeficientes(preshoot_db, deenfase_db):
    """(c-1, c0, c+1) com |c-1| + c0 + |c+1| = 1."""
    vb = 10 ** (-preshoot_db / 20)
    a = (1 - vb) / 2
    va = vb * 10 ** (deenfase_db / 20)
    b = (1 - 2 * a - va) / 2
    return -a, 1 - a - b, -b


# ---------------------------------------------------------------- tradutor e LTSSM
@dataclass
class LadoTradutor:
    politica: str            # "controlada" | "sempre" | "nunca" | None
    par_identificado: bool
    optico_travado: bool
    squelch_ps: float

    @property
    def terminacao(self):
        if self.politica == "controlada":
            return self.par_identificado and self.optico_travado
        return self.politica == "sempre"


@dataclass
class ResultadoLTSSM:
    ok: bool
    estados: list = field(default_factory=list)     # (estado, início ms, duração ms)
    parou_em: str = ""
    motivo: str = ""

    @property
    def total_ms(self):
        return sum(d for _, _, d in self.estados)


def ltssm(cpu, gpu, olho, gt_s=32.0):
    """Do Detect ao L0 na taxa final. `cpu`/`gpu`: o tradutor que cada transmissor enxerga."""
    r = ResultadoLTSSM(False)
    t = 0.0

    def estado(nome, dur_ms):
        nonlocal t
        r.estados.append((nome, t, dur_ms))
        t += dur_ms

    for _ in range(DETECT_TENTATIVAS):
        estado("Detect.Quiet", DETECT_QUIET_MS)
        estado("Detect.Active", 0.01)
        if cpu.terminacao and gpu.terminacao:
            break
    else:
        quem = "CPU" if not cpu.terminacao else "GPU"
        r.parou_em = "Detect"
        r.motivo = (f"o transmissor da {quem} não acha receptor: o tradutor do lado dela não "
                    "apresenta terminação" + (" (política sem controle)" if (cpu if quem == "CPU" else gpu).politica
                                              not in ("controlada", "sempre") else ""))
        return r
    pior_squelch = max(cpu.squelch_ps, gpu.squelch_ps)
    if pior_squelch > LIMITE_SQUELCH_PS:
        estado("Polling.Active", POLLING_TIMEOUT_MS)
        r.parou_em = "Polling"
        r.motivo = (f"saída do ocioso elétrico leva {pior_squelch:.0f} ps para atravessar o tradutor; "
                    f"limite {LIMITE_SQUELCH_PS:.0f} ps")
        return r
    estado("Polling.Active", POLLING_TS1 * TS_SIMBOLOS * 10 * UI_GEN1_NS * 1e-6)
    estado("Polling.Configuration", POLLING_CONFIG_US * 1e-3)
    estado("Configuration", CONFIGURATION_US * 1e-3)
    estado("L0 (2,5 GT/s)", 0.0)
    estado("Recovery.Speed", RECOVERY_SPEED_US * 1e-3)
    estado("Recovery.Equalization fases 0-1", EQ_FASE01_MS)
    fase = len(PRESETS) * EQ_AVALIACAO_PRESET_MS
    if fase > EQ_FASE_TIMEOUT_MS:
        r.parou_em, r.motivo = "Recovery.Equalization", "avaliar os presets passa do timeout da fase"
        return r
    estado("Recovery.Equalization fase 2", fase)
    if not olho["aberto"]:
        estado("Recovery.Equalization fase 3", EQ_FASE_TIMEOUT_MS)
        r.parou_em = "Recovery.Equalization"
        r.motivo = (f"nenhum preset abre o olho a {gt_s:.0f} GT/s: altura {olho['altura_rel']:.2f}, "
                    f"largura {olho['largura_ui']:.2f} UI")
        return r
    estado("Recovery.Equalization fase 3", fase)
    estado(f"L0 ({gt_s:.0f} GT/s)", 0.0)
    r.ok = True
    return r


# ---------------------------------------------------------------- equalização
def _perda_trilha(f_ghz, comprimento_mm, perda_db_mm_ghz):
    return 10 ** (-(perda_db_mm_ghz * comprimento_mm * np.abs(f_ghz)) / 20)


def _passa_baixa(f_ghz, fc_ghz, ordem=1):
    if ordem == 1:
        return 1 / (1 + 1j * f_ghz / fc_ghz)
    s = 1j * f_ghz / fc_ghz
    return 1 / (s ** 2 + math.sqrt(2) * s + 1)


def _filtrar(x, h):
    return np.real(np.fft.ifft(np.fft.fft(x) * h))


def _transferencia_anel(cfg):
    """Potência óptica normalizada em função do sinal de entrada em [-1, 1]."""
    anel = E._anel(cfg)
    v = E._tensoes(cfg, 2)
    d0 = E.ponto_operacao(anel, v)
    vpp = cfg["driver"]["vpp"]
    ef = anel.eficiencia_pm_v * 1e-3
    t0, t1 = anel.transmissao(0.0, d0), anel.transmissao(0.0, d0 + ef * vpp)

    def mapa(x):
        volts = (np.clip(x, -1, 1) + 1) / 2 * vpp
        t = anel.transmissao(0.0, d0 + ef * volts)
        return (t - t0) / (t1 - t0) * 2 - 1
    return mapa, anel.tau_foton_ps


@lru_cache(maxsize=64)
def equalizar(comprimento_cpu_mm=6.0, comprimento_gpu_mm=6.0, perda_db_mm_ghz=0.004, gt_s=32.0,
              linear=False, banda_tradutor_ghz=TRADUTOR_BANDA_GHZ, config_optica="viavel", semente=0):
    """Melhor preset do transmissor e ganho do CTLE, e o olho no receptor."""
    cfg = E.carregar(config_optica)
    baud = gt_s * 1e9
    fs = baud * AMOSTRAS_UI
    n = N_BITS * AMOSTRAS_UI
    f = np.fft.fftfreq(n, 1 / fs) / 1e9
    rng = np.random.default_rng(semente)
    bits = rng.integers(0, 2, N_BITS)
    sim = 2.0 * bits - 1
    ruido = _filtrar(rng.standard_normal(n), _passa_baixa(f, cfg["receptor"]["banda_rel"] * gt_s, 2))
    ruido /= np.std(ruido)
    mapa, tau_ps = _transferencia_anel(cfg)
    rx_banda = cfg["receptor"]["banda_rel"] * gt_s

    h_antes = (_perda_trilha(f, comprimento_cpu_mm, perda_db_mm_ghz)
               * _passa_baixa(f, banda_tradutor_ghz))
    h_optico = _passa_baixa(f, 1 / (2 * math.pi * tau_ps * 1e-3)) * _passa_baixa(f, rx_banda, 2)
    h_depois = (_passa_baixa(f, banda_tradutor_ghz)
                * _perda_trilha(f, comprimento_gpu_mm, perda_db_mm_ghz))

    melhor = None
    for nome, (ps, de) in PRESETS.items():
        cm1, c0, cp1 = coeficientes(ps, de)
        x = c0 * sim + cm1 * np.roll(sim, -1) + cp1 * np.roll(sim, 1)
        w = _filtrar(np.repeat(x, AMOSTRAS_UI), h_antes)
        w = w if linear else mapa(w)
        w = _filtrar(w, h_optico)
        w = _filtrar(w + RUIDO_REL * np.ptp(w) / 2 * ruido, h_depois)
        for g in CTLE_GANHOS_DB:
            fz = CTLE_POLO_REL[0] * gt_s / 10 ** (g / 20)
            h_ctle = (1 + 1j * f / fz) / (1 + 1j * f / (CTLE_POLO_REL[0] * gt_s)) \
                / (1 + 1j * f / (CTLE_POLO_REL[1] * gt_s)) * 10 ** (-g / 20)
            y = _filtrar(w, h_ctle)
            olho = _olho(_alinhar(y, sim), bits)
            olho.update({"preset": nome, "ctle_db": g})
            if melhor is None or (olho["altura_rel"], olho["largura_ui"]) > (melhor["altura_rel"], melhor["largura_ui"]):
                melhor = olho
    melhor["aberto"] = (melhor["altura_rel"] >= OLHO_MIN_ALTURA_REL
                        and melhor["largura_ui"] >= OLHO_MIN_LARGURA_UI)
    melhor["linear"] = linear
    return melhor


def _alinhar(y, sim):
    """Desloca a saída pelo atraso do canal, para cada UI começar no seu próprio bit."""
    ideal = np.repeat(sim, AMOSTRAS_UI)
    corr = np.real(np.fft.ifft(np.fft.fft(y) * np.conj(np.fft.fft(ideal))))
    atraso = int(np.argmax(corr)) - AMOSTRAS_UI // 2
    return np.roll(y, -atraso)


def _olho(y, bits, pula=64):
    """Olho com DFE de 1 tap, em cada uma das fases do UI."""
    amostras = y.reshape(-1, AMOSTRAS_UI)[pula:-pula]
    b = bits[pula:-pula]
    ant = 2.0 * bits[pula - 1:-pula - 1] - 1
    alturas = []
    for k in range(AMOSTRAS_UI):
        v = amostras[:, k]
        A = np.column_stack([2.0 * b - 1, ant, np.ones_like(v)])
        coef, *_ = np.linalg.lstsq(A, v, rcond=None)
        principal, h1 = coef[0], coef[1]
        if principal <= 0:
            alturas.append(-1.0)
            continue
        vd = v - h1 * ant
        alt = (vd[b == 1].min() - vd[b == 0].max()) / (2 * principal)
        alturas.append(alt)
    alturas = np.array(alturas)
    melhor = int(np.argmax(alturas))
    largura = float((alturas >= OLHO_MIN_ALTURA_REL / 2).sum()) / AMOSTRAS_UI
    return {"altura_rel": float(alturas[melhor]), "largura_ui": largura, "fase": melhor}


# ---------------------------------------------------------------- na netlist
def _trilhas_do_caminho(netlist, cam):
    out = []
    for b, _ in cam:
        blk = netlist.blocos.get(b)
        if blk is not None and blk.tipo == "trilha" and (not out or out[-1][0] != b):
            out.append((b, float(blk.atributos.get("comprimento_mm", 0.0)),
                        float(blk.atributos.get("perda_db_mm_ghz", 0.004))))
    return out


def canais_da_netlist(netlist, protocolo="PCIe5"):
    """Pior canal de cada protocolo PCIe: as trilhas de cada ponta e a perda por mm."""
    pior = None
    for s in netlist.sinais.values():
        if s.protocolo != protocolo:
            continue
        for cam in s.caminhos.values():
            tr = _trilhas_do_caminho(netlist, cam)
            if len(tr) < 2:
                continue
            c = (tr[0][1], tr[-1][1], max(t[2] for t in tr))
            if pior is None or c[0] + c[1] > pior[0] + pior[1]:
                pior = c
    return pior


def vias_pcie(netlist, protocolo=None):
    """Vias de tradutor que levam sinais PCIe, com o lado (peça) de cada uma."""
    out = []
    for s in netlist.sinais.values():
        if not s.protocolo.startswith("PCIe") or (protocolo and s.protocolo != protocolo):
            continue
        for cam in s.caminhos.values():
            for b, _ in cam:
                blk = netlist.blocos.get(b)
                if blk is not None and blk.tipo in ("via_tx", "via_rx"):
                    out.append((s, blk))
    return out


def avaliar_netlist(netlist, protocolo="PCIe5", comparar_linear=True):
    gt = 32.0 if protocolo == "PCIe5" else 16.0
    canal = canais_da_netlist(netlist, protocolo)
    if canal is None:
        return None
    args = (round(canal[0], 2), round(canal[1], 2), round(canal[2], 6), gt)
    out = {"protocolo": protocolo, "canal_mm": (canal[0], canal[1]), "olho": equalizar(*args)}
    if comparar_linear:
        out["olho_linear"] = equalizar(*args, linear=True)
    return out
