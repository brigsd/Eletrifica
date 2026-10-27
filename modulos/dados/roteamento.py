"""Roteamento: cada pino de dados vira canal óptico, e os canais viram fibras.

O sistema decide sozinho quem fala com quem: qual canal DDR5 da CPU vai para
qual DIMM, e qual canal GDDR7 da GPU vai para qual chip, por atribuição ótima
de distância. Um par diferencial é um canal; um pino bidirecional é um canal
comutado (o sentido troca) ou dois dedicados (um por sentido).
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from modulos.dados.protocolos import (BIDIRECIONAIS_AUX, PAPEIS_DADOS, PROTOCOLOS,
                                      papel)

FOLGA_VERTICAL_MM = 10.0     # subida e descida da fibra entre a base e o tradutor
FOLGA_PARADA_MM = 5.0        # desvio em cada parada de um barramento WDM
SAIDA_MM = 3.0               # trecho reto saindo do tradutor
PAPEIS_BARRAMENTO = ("DQ", "DQS", "TX", "RX", "DMI")   # vão em fibras de dados; o resto, de controle
PARADAS_MAX = 2              # destinos por fibra de barramento: mais paradas, mais atraso


@dataclass
class Canal:
    enlace: str
    origem: str
    destino: str
    pino_origem: str
    pino_destino: str
    sentido: str            # "ida" (origem->destino), "volta", "duplo" (comutado)
    protocolo: str
    papel: str
    taxa_gbps: float
    gbaud: float
    codificacao: str
    grupo: str
    fibra: int = -1
    lambda_idx: int = -1

    @property
    def dados(self):
        return self.papel in PAPEIS_DADOS


@dataclass
class Fibra:
    id: int
    hub: str
    destinos: list
    sentido: str
    classe: str
    protocolo: str
    canais: list = field(default_factory=list)
    rota: list = field(default_factory=list)        # [(x, y), ...] mm
    distancia_ate: dict = field(default_factory=dict)   # destino -> mm ao longo da fibra

    @property
    def comprimento_mm(self):
        return max(self.distancia_ate.values()) if self.distancia_ate else 0.0


@dataclass
class Enlace:
    id: str
    a: str
    b: str
    protocolo: str
    canais: list = field(default_factory=list)
    tradutor_a: tuple = (0.0, 0.0)
    tradutor_b: tuple = (0.0, 0.0)

    def fibras(self, plano):
        return sorted({plano.canais[i].fibra for i in self.canais})


@dataclass
class Plano:
    enlaces: list
    canais: list
    fibras: list
    canais_por_fibra: int
    modo_bidirecional: str
    topologia: str
    poses: dict

    def enlace(self, id_):
        return next(e for e in self.enlaces if e.id == id_)

    def totais(self):
        pinos = {}
        for c in self.canais:
            if c.dados:
                pinos[(c.origem, c.pino_origem)] = c.taxa_gbps
        return {"canais": len(self.canais),
                "fibras": len(self.fibras),
                "canais_dados": sum(c.dados for c in self.canais),
                "banda_pinos_GBps": sum(pinos.values()) / 8,
                "capacidade_optica_GBps": sum(c.taxa_gbps for c in self.canais if c.dados) / 8,
                "fibra_total_mm": sum(f.comprimento_mm for f in self.fibras)}

    def por_interface(self, protocolo, papel_=None):
        return [c for c in self.canais if c.protocolo == protocolo
                and (papel_ is None or c.papel == papel_)]


# ---------------------------------------------------------------- geometria
def _global(pc, x, y):
    c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
    return pc.x + c * x - s * y, pc.y + s * x + c * y


def _centroide(pc, nomes):
    idx = pc.peca._indice()
    pts = np.array([_global(pc, idx[n].x, idx[n].y) for n in nomes])
    return pts.mean(0)


def tradutor(pc, alvo):
    """Ponto na borda da peça voltado para `alvo`, e a normal daquela borda."""
    c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
    dx, dy = alvo[0] - pc.x, alvo[1] - pc.y
    lx, ly = c * dx + s * dy, -s * dx + c * dy
    w, h = pc.peca.largura / 2, pc.peca.profundidade / 2
    tx = w / abs(lx) if lx else math.inf
    ty = h / abs(ly) if ly else math.inf
    t = min(tx, ty)
    px, py = lx * t, ly * t
    nx, ny = (math.copysign(1, lx), 0.0) if tx <= ty else (0.0, math.copysign(1, ly))
    gx, gy = _global(pc, px, py)
    return (gx, gy), (c * nx - s * ny, s * nx + c * ny)


def _rota(p, np_, q, nq):
    """Fibra roteada em L entre dois tradutores, saindo reto de cada borda."""
    p1 = (p[0] + SAIDA_MM * np_[0], p[1] + SAIDA_MM * np_[1])
    q1 = (q[0] + SAIDA_MM * nq[0], q[1] + SAIDA_MM * nq[1])
    canto = (q1[0], p1[1]) if abs(np_[0]) >= abs(np_[1]) else (p1[0], q1[1])
    return [p, p1, canto, q1, q]


def _comprimento(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


# ---------------------------------------------------------------- sinais
_SENTIDO_AUX = {"SVID_CLK": "ida", "SVID_DATA": "duplo", "SVID_ALERT": "volta",
                "PWROK": "volta", "PLTRST": "volta", "PROCHOT": "volta",
                "THERMTRIP": "ida", "BCLK": "volta", "CATERR": "ida", "TCK": "volta",
                "TDI": "volta", "TDO": "ida", "TMS": "volta", "TRST": "volta",
                "SMBUS_CLK": "volta", "SMBUS_DATA": "duplo", "VIDSCK": "ida",
                "PECI": "duplo", "RSMRST": "volta", "SLP_S3": "volta"}


def _sentido(protocolo, nome, papel_):
    """Sentido visto do lado `a` do enlace (CPU ou GPU)."""
    if protocolo == "AUX":
        return _SENTIDO_AUX[nome]
    if papel_ in ("DQ", "DQS"):
        return "duplo"
    if papel_ in ("ALERT", "EDC", "RX"):
        return "volta"
    if papel_ == "DMI":
        return "ida" if int(nome.split("_")[-1]) % 2 == 0 else "volta"
    return "ida"


def _grupo(prefixo, nome, papel_):
    num = int("".join(ch for ch in nome.split("_")[-1] if ch.isdigit()) or 0)
    if papel_ == "DQ":
        return f"{prefixo}_B{num // 8}"
    if papel_ == "DQS":
        return f"{prefixo}_B{num}"
    if papel_ in ("CA", "CS", "CK", "WCK"):          # RESET é estático: fica fora do grupo
        return f"{prefixo}_CTRL"
    return nome


def _sinais_enlace(mapa):
    """Lista (pino_a, pino_b, sentido, protocolo, papel, grupo)."""
    out = []
    for pa, pb, prefixo, prot in mapa:
        p = papel(pa)
        if prot == "PCIe5" and p in ("TX", "RX"):
            par = pa.replace("TX", "RX") if p == "TX" else pa.replace("RX", "TX")
            pb = par
        sentido = _sentido(prot, pa, p)
        if prot == "AUX" and pa in BIDIRECIONAIS_AUX:
            sentido = "duplo"
        out.append((pa, pb, sentido, prot, p, _grupo(prefixo, pa, p)))
    return out


def _canais(enlace_id, a, b, sinais, modo):
    out = []
    for pa, pb, sentido, prot, p, grupo in sinais:
        pr = PROTOCOLOS[prot]
        dados = p in PAPEIS_DADOS
        taxa = pr.taxa_gbps if dados else pr.taxa_controle_gbps
        bps = pr.bits_por_simbolo if dados else 1.0
        cod = pr.codificacao if dados else "NRZ"
        sentidos = ["ida", "volta"] if (sentido == "duplo" and modo == "dedicado") else [sentido]
        for s in sentidos:
            out.append(Canal(enlace_id, a, b, pa, pb, s, prot, p, taxa, taxa / bps, cod, grupo))
    return out


# ---------------------------------------------------------------- plano
def _enlaces(cfg):
    """Monta os enlaces lógicos e decide as atribuições."""
    pecas = {p.nome: p for p in cfg.pecas}
    cpu, gpu, fpga = pecas["CPU"], pecas["GPU"], pecas["FPGA"]
    dimms = sorted(n for n in pecas if n.startswith("DIMM"))
    mems = sorted((n for n in pecas if n.startswith("MEM")), key=lambda n: int(n[3:]))
    enlaces = []

    canais_cpu = ["DDR5_A", "DDR5_B"]
    custo = np.array([[np.hypot(*(_centroide(cpu, cpu.peca.interfaces[ci].sinais)
                                  - _centroide(pecas[d], pecas[d].peca.interfaces["DDR5"].sinais)))
                       for d in dimms] for ci in canais_cpu])
    linhas, colunas = linear_sum_assignment(custo)
    for i, j in zip(linhas, colunas):
        ci, d = canais_cpu[i], dimms[j]
        mapa = []
        for n in cpu.peca.interfaces[ci].sinais:
            resto = n[len(ci) + 1:]
            sub = resto.split("_")[0] if "_" in resto else ""
            mapa.append((n, f"DDR5_{resto}", f"{ci}_{sub}" if sub else ci, "DDR5-4800"))
        enlaces.append((f"CPU-{d}", "CPU", d, ci, mapa))

    gs = sorted({s.split("_")[0] for s in gpu.peca.interfaces["GDDR7"].sinais},
                key=lambda g: int(g[1:]))
    sinais_g = {g: [s for s in gpu.peca.interfaces["GDDR7"].sinais if s.startswith(g + "_")]
                for g in gs}
    custo = np.array([[np.hypot(*(_centroide(gpu, sinais_g[g]) - np.array([pecas[m].x, pecas[m].y])))
                       for m in mems] for g in gs])
    linhas, colunas = linear_sum_assignment(custo)
    for i, j in zip(linhas, colunas):
        g, m = gs[i], mems[j]
        mapa = [(n, "GX_" + n.split("_", 1)[1], g, "GDDR7-32") for n in sinais_g[g]]
        enlaces.append((f"GPU-{m}", "GPU", m, g, mapa))

    # relógios de referência não viajam com os dados: vêm do gerador de relógio da base
    mapa = [(n, n, "PEG", "PCIe5") for n in cpu.peca.interfaces["PEG"].sinais if not _relogio(n)]
    enlaces.append(("CPU-GPU", "CPU", "GPU", "PEG", mapa))

    xcvr = set(fpga.peca.interfaces["XCVR"].sinais)
    mapa = []
    for n in cpu.peca.interfaces["PCH"].sinais:
        if _relogio(n):
            continue
        par = n.replace("TX", "#").replace("RX", "TX").replace("#", "RX") if n.startswith("PCIE4") else n
        if par not in xcvr:
            raise ValueError(f"o FPGA não tem transceptor para {n}")
        mapa.append((n, par, "PCH", "PCIe4"))
    ctl = iter(fpga.peca.interfaces["CTL"].sinais)
    mapa += [(n, next(ctl), "AUX", "AUX") for n in cpu.peca.interfaces["AUX"].sinais if not _relogio(n)]
    enlaces.append(("CPU-FPGA", "CPU", "FPGA", "PCH", mapa))
    return enlaces


def _relogio(nome):
    return nome == "BCLK" or nome.startswith("REFCLK")


def _empacotar(canais_idx, canais, capacidade, ordem_destinos, paradas_max=PARADAS_MAX):
    """Grupos inteiros, na ordem dos destinos, primeiro que couber, até `paradas_max` destinos."""
    grupos = {}
    for i in canais_idx:
        c = canais[i]
        grupos.setdefault((ordem_destinos.index(c.destino), c.grupo), []).append(i)
    fibras, atual = [], []
    for chave in sorted(grupos):
        g = grupos[chave]
        if len(g) > capacidade:
            raise ValueError(f"grupo {chave[1]} tem {len(g)} canais e a fibra comporta {capacidade}")
        destinos = {canais[i].destino for i in atual} | {canais[g[0]].destino}
        if len(atual) + len(g) > capacidade or len(destinos) > paradas_max:
            fibras.append(atual)
            atual = []
        atual = atual + g
    if atual:
        fibras.append(atual)
    return fibras


def rotear(configuracao, canais_por_fibra=64, modo_bidirecional="comutado",
           topologia="barramento"):
    if modo_bidirecional not in ("comutado", "dedicado"):
        raise ValueError(modo_bidirecional)
    if topologia not in ("barramento", "ponto_a_ponto"):
        raise ValueError(topologia)
    pecas = {p.nome: p for p in configuracao.pecas}
    canais, enlaces = [], []
    for eid, a, b, _interface, mapa in _enlaces(configuracao):
        sinais = _sinais_enlace(mapa)
        novos = _canais(eid, a, b, sinais, modo_bidirecional)
        e = Enlace(eid, a, b, mapa[0][3], list(range(len(canais), len(canais) + len(novos))))
        pa, pb = pecas[a], pecas[b]
        e.tradutor_a = tradutor(pa, (pb.x, pb.y))[0]
        e.tradutor_b = tradutor(pb, (pa.x, pa.y))[0]
        canais += novos
        enlaces.append(e)

    # canais que compartilham fibra: mesmo hub, família do enlace, sentido e classe
    familia = {e.id: e.protocolo for e in enlaces}
    pools = {}
    for i, c in enumerate(canais):
        classe = "dados" if c.papel in PAPEIS_BARRAMENTO else "controle"
        chave = ((c.origem, familia[c.enlace]) if topologia == "barramento" else (c.enlace,)) \
            + (c.sentido, classe)
        pools.setdefault(chave, []).append(i)

    fibras = []
    for chave, idx in sorted(pools.items(), key=lambda kv: str(kv[0])):
        hub = canais[idx[0]].origem
        destinos = sorted({canais[i].destino for i in idx})
        ph = pecas[hub]
        # ordem de visita: vizinho mais próximo a partir do hub
        ordem, pos = [], (ph.x, ph.y)
        resto = list(destinos)
        while resto:
            prox = min(resto, key=lambda d: math.hypot(pecas[d].x - pos[0], pecas[d].y - pos[1]))
            ordem.append(prox)
            resto.remove(prox)
            pos = (pecas[prox].x, pecas[prox].y)
        for grupo_fibra in _empacotar(idx, canais, canais_por_fibra, ordem):
            dests = [d for d in ordem if any(canais[i].destino == d for i in grupo_fibra)]
            f = Fibra(len(fibras), hub, dests, chave[-2], chave[-1],
                      familia[canais[idx[0]].enlace])
            alvo = np.mean([(pecas[d].x, pecas[d].y) for d in dests], axis=0)
            p, n = tradutor(ph, alvo)
            rota, dist = [p], 0.0
            for d in dests:
                q, nq = tradutor(pecas[d], p)
                trecho = _rota(p, n, q, nq)
                dist += _comprimento(trecho) + (FOLGA_PARADA_MM if len(rota) > 1 else 0.0)
                rota += trecho[1:]
                f.distancia_ate[d] = dist + FOLGA_VERTICAL_MM
                p, n = q, (-nq[0], -nq[1])
            f.rota = rota
            for k, i in enumerate(grupo_fibra):
                canais[i].fibra, canais[i].lambda_idx = f.id, k
                f.canais.append(i)
            fibras.append(f)

    poses = {p.nome: (p.x, p.y, p.rot) for p in configuracao.pecas}
    return Plano(enlaces, canais, fibras, canais_por_fibra, modo_bidirecional, topologia, poses)
