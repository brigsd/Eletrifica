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
# sinais de plataforma da CPU que são do chipset; o resto do AUX (JTAG, VIDSCK) é do FPGA
PARA_PCH = ("PWROK", "PLTRST", "RSMRST", "SLP_S3", "THERMTRIP", "CATERR", "PROCHOT", "PECI",
            "SMBUS_CLK", "SMBUS_DATA")
NOME_NO_PCH = {"RSMRST": "RSMRST_CPU", "SLP_S3": "SLP_S3_CPU"}


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
    canal_mem: str = ""     # canal GDDR7 do controlador (G0..G11) quando há mais de um chip por canal
    rank: int = 0
    lider: str = ""         # chip do rank 0 do canal: o tradutor do grupo fica sob ele
    sombra_de: int = -1     # rank > 0: usa a luz do canal do rank 0 (o seletor do grupo escolhe o chip)

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
    if papel_ == "EDC":
        return f"{prefixo}_EDC"
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


def _canais(enlace_id, a, b, sinais, modo, canal_mem="", rank=0, lider=""):
    out = []
    for pa, pb, sentido, prot, p, grupo in sinais:
        pr = PROTOCOLOS[prot]
        dados = p in PAPEIS_DADOS
        taxa = pr.taxa_gbps if dados else pr.taxa_controle_gbps
        bps = pr.bits_por_simbolo if dados else 1.0
        cod = pr.codificacao if dados else "NRZ"
        sentidos = ["ida", "volta"] if (sentido == "duplo" and modo == "dedicado") else [sentido]
        for s in sentidos:
            out.append(Canal(enlace_id, a, b, pa, pb, s, prot, p, taxa, taxa / bps, cod, grupo,
                             canal_mem=canal_mem, rank=rank, lider=lider))
    return out


# ---------------------------------------------------------------- plano
def _enlaces(cfg):
    """Monta os enlaces lógicos e decide as atribuições."""
    pecas = {p.nome: p for p in cfg.pecas}
    cpu, gpu, fpga = pecas["CPU"], pecas["GPU"], pecas["FPGA"]
    dimms = sorted(n for n, p in pecas.items() if n != "CPU" and "DDR5" in p.peca.interfaces)
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
    if len(mems) % len(gs):
        raise ValueError(f"{len(mems)} chips GDDR7 não dividem por {len(gs)} canais")
    ranks = len(mems) // len(gs)
    xy = {m: np.array([pecas[m].x, pecas[m].y]) for m in mems}
    # chips vizinhos formam o grupo de um canal (multiplicação de rank pela base, como num LRDIMM)
    grupos, livres = [], set(mems)
    while livres:
        m = min(livres, key=lambda n: (min(np.hypot(*(xy[n] - xy[o])) for o in livres - {n})
                                       if len(livres) > 1 else 0.0, n))
        g = sorted(livres, key=lambda o: (np.hypot(*(xy[m] - xy[o])), o))[:ranks]
        grupos.append(g)
        livres -= set(g)
    centro = [np.mean([xy[m] for m in g], axis=0) for g in grupos]
    custo = np.array([[np.hypot(*(_centroide(gpu, sinais_g[c]) - centro[k])) for k in range(len(grupos))]
                      for c in gs])
    linhas, colunas = linear_sum_assignment(custo)
    chip_de = {}
    for i, j in zip(linhas, colunas):
        # rank 0 é o chip mais perto do canal: é sob ele que fica o tradutor do grupo
        ordem_g = sorted(grupos[j], key=lambda m: (np.hypot(*(_centroide(gpu, sinais_g[gs[i]]) - xy[m])), m))
        for r, m in enumerate(ordem_g):
            chip_de[(gs[i], r)] = m
    controladores = [("GPU", sinais_g)]
    ponte = next((n for n, p in pecas.items() if p.tipo == "PONTE-MEM"), None)
    if ponte:
        # a ponte fala com os mesmos chips, na mesma posição de canal e rank que a GPU;
        # o RESET dos chips é só da GPU
        sp = pecas[ponte].peca.interfaces["GDDR7"].sinais
        controladores.append((ponte, {g: [s for s in sp if s.startswith(g + "_") and papel(s) != "RESET"]
                                      for g in gs}))
    for nome_c, sinais_c in controladores:
        for (g, r), m in sorted(chip_de.items(), key=lambda kv: (int(kv[0][0][1:]), kv[0][1])):
            prefixo = g if nome_c == "GPU" else f"{nome_c}.{g}"      # grupos síncronos por controlador
            mapa = [(n, "GX_" + n.split("_", 1)[1], prefixo, "GDDR7-32") for n in sinais_c[g]]
            extra = (g, r, chip_de[(g, 0)]) if ranks > 1 else ("", 0, "")
            enlaces.append((f"{nome_c}-{m}", nome_c, m, g, mapa, extra))

    # relógios de referência não viajam com os dados: vêm do gerador de relógio da base
    mapa = [(n, n, "PEG", "PCIe5") for n in cpu.peca.interfaces["PEG"].sinais if not _relogio(n)]
    enlaces.append(("CPU-GPU", "CPU", "GPU", "PEG", mapa))

    xcvr = set(fpga.peca.interfaces["XCVR"].sinais)
    pch = pecas.get("PCH")
    para_pch = set(PARA_PCH) if pch else set()

    def par_pcie4(n):
        return n.replace("TX", "#").replace("RX", "TX").replace("#", "RX")

    if pch:
        mapa = [(n, n, "DMI", "PCIe4") for n in cpu.peca.interfaces["DMI"].sinais]
        mapa += [(n, NOME_NO_PCH.get(n, n), "AUX", "AUX") for n in cpu.peca.interfaces["AUX"].sinais
                 if n in para_pch]
        enlaces.append(("CPU-PCH", "CPU", "PCH", "DMI", mapa))
    mapa = []
    for n in cpu.peca.interfaces["PCIE4"].sinais:
        if _relogio(n):
            continue
        if par_pcie4(n) not in xcvr:
            raise ValueError(f"o FPGA não tem transceptor para {n}")
        mapa.append((n, par_pcie4(n), "PCIE4", "PCIe4"))
    ctl = iter(fpga.peca.interfaces["CTL"].sinais)
    mapa += [(n, next(ctl), "AUX", "AUX") for n in cpu.peca.interfaces["AUX"].sinais
             if not _relogio(n) and n not in para_pch]
    enlaces.append(("CPU-FPGA", "CPU", "FPGA", "PCIE4", mapa))
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
    for eid, a, b, _interface, mapa, *rank in _enlaces(configuracao):
        sinais = _sinais_enlace(mapa)
        novos = _canais(eid, a, b, sinais, modo_bidirecional, *(rank[0] if rank else ()))
        e = Enlace(eid, a, b, mapa[0][3], list(range(len(canais), len(canais) + len(novos))))
        pa, pb = pecas[a], pecas[b]
        e.tradutor_a = tradutor(pa, (pb.x, pb.y))[0]
        e.tradutor_b = tradutor(pb, (pa.x, pa.y))[0]
        canais += novos
        enlaces.append(e)

    # os chips de rank > 0 recebem a mesma luz do chip do rank 0 do canal
    lider = {(c.origem, c.destino, c.pino_origem, c.sentido): i for i, c in enumerate(canais)
             if c.canal_mem and c.rank == 0}
    for c in canais:
        if c.canal_mem and c.rank > 0:
            c.sombra_de = lider[(c.origem, c.lider, c.pino_origem, c.sentido)]

    # canais que compartilham fibra: mesmo hub, família do enlace, sentido e classe
    familia = {e.id: e.protocolo for e in enlaces}
    pools = {}
    for i, c in enumerate(canais):
        if c.sombra_de >= 0:
            continue
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
        # com vários chips por canal, os chips do mesmo canal ficam juntos (rank 0, rank 1...)
        canal_de = {canais[i].destino: (canais[i].canal_mem, canais[i].rank) for i in idx}
        blocos = {}
        for d in destinos:
            blocos.setdefault(canal_de[d][0] or d, []).append(d)
        centro = {k: np.mean([(pecas[d].x, pecas[d].y) for d in v], axis=0) for k, v in blocos.items()}
        ordem, pos = [], (ph.x, ph.y)
        resto = list(blocos)
        while resto:
            prox = min(resto, key=lambda k: math.hypot(centro[k][0] - pos[0], centro[k][1] - pos[1]))
            ordem += sorted(blocos[prox], key=lambda d: canal_de[d][1])
            resto.remove(prox)
            pos = tuple(centro[prox])
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

    for c in canais:
        if c.sombra_de >= 0:
            c.fibra, c.lambda_idx = canais[c.sombra_de].fibra, canais[c.sombra_de].lambda_idx
    poses = {p.nome: (p.x, p.y, p.rot) for p in configuracao.pecas}
    return Plano(enlaces, canais, fibras, canais_por_fibra, modo_bidirecional, topologia, poses)
