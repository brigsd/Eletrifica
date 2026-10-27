"""Monta a netlist do sistema inteiro a partir do que o mapeamento e o roteamento decidiram.

Cada sinal rápido percorre: pino -> célula -> trilha da base -> chip tradutor
(chave de sentido, via de transmissão, mux) -> acoplador -> fibra -> ... ->
demux -> via de recepção -> trilha -> célula -> pino. Sinais lentos vão por
trilha elétrica direta, com conversor de nível e pull-up quando precisam.
Laser, energia, controle e relógio de cada bloco ativo também são blocos.
Os números típicos ficam nas constantes abaixo.
"""
import math
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from modulos.conexoes.netlist import Netlist, Requisito, Sinal
from modulos.conexoes.padroes import PADROES, padrao_do_pino
from modulos.conexoes.posicao import Ocupacao, manhattan
from modulos.optica import enlace as E
from modulos.sistema.celula import chave as chave_da_celula

# --- chip tradutor -----------------------------------------------------------
VIAS_MAX = 96                 # vias (tx + rx) por chip
CHIP_MM = (10.0, 10.0)
AFASTAMENTO_CHIP_MM = 2.0     # da borda da peça até a borda do chip
VDD_CHIP_V = 0.9
PJ_BIT_TX = 1.5               # driver + modulador
PJ_BIT_RX = 1.5               # fotodetector + TIA + driver de saída
AQUECEDOR_MW = 3.0            # médio por anel (modulador ou filtro)
CONTROLE_CHIP_W = 0.15        # lógica de travamento, DACs e ADCs dos anéis

# --- célula e trilha da base -------------------------------------------------
# a chave de cada célula vem de modulos.sistema.celula (uma especificação só)
VERTICAL_FOTONICA_MM = 3.0    # do contato até a camada de fotônica, por dentro da base
Z_TRILHA_OHM = {"se": 40.0, "diff": 85.0}
PERDA_DB_MM_GHZ = 0.004       # linha fina em LCP
CAMADAS_SINAL = 4
PASSO_TRILHA_MM = 0.15        # 75 µm de linha + 75 µm de espaço
CAMADA_LENTA = 5              # sinais lentos numa camada própria

# --- óptica ------------------------------------------------------------------
LASER_MM = (40.0, 25.0)
PENTES_POR_MODULO = 8         # pentes de comprimentos de onda por módulo de laser
LASER_EFICIENCIA = 0.15       # óptico / elétrico
LASER_TEC_W = 2.0
DIVISOR_SAIDAS_MAX = 16
PERDA_FIBRA_DB_MM = 0.35e-6   # 0,35 dB/km
PERDA_CONECTOR_DB = 0.25
ALVO_LASER = (295.0, 25.0)

# --- controle e energia ------------------------------------------------------
DISPOSITIVOS_POR_I3C = 12
CELULAS_POR_MATRIZ = 4096     # endereçamento linha x coluna de um controlador regional
MARGEM_REGULADOR = 1.25
PULLUP_OHM = 1000.0

DIREITO = {"ida": "sai", "volta": "entra", "duplo": "bidir"}
INVERSO = {"ida": "entra", "volta": "sai", "duplo": "bidir"}


def _global(pc, x, y):
    c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
    return pc.x + c * x - s * y, pc.y + s * x + c * y


def _contorno(pc):
    w, d = pc.peca.largura / 2, pc.peca.profundidade / 2
    return [_global(pc, x, y) for x, y in ((-w, -d), (w, -d), (w, d), (-w, d))]


def _protocolo_dos_pinos(peca):
    out = {}
    for itf in peca.interfaces.values():
        for s in itf.sinais:
            out[s] = itf.protocolo
    return out


class _Construtor:
    def __init__(self, montagem, configuracao, plano, cfg_optica, chave=None,
                 posicionamento="ao_lado"):
        if posicionamento not in ("ao_lado", "sob_peca"):
            raise ValueError(posicionamento)
        self.m, self.cfg, self.plano, self.opt = montagem, configuracao, plano, cfg_optica
        self.chave_celula = chave_da_celula(chave)
        self.posicionamento = posicionamento
        self.nl = Netlist()
        self.pecas = {p.nome: p for p in configuracao.pecas}
        self.base = montagem.base
        self.oc = Ocupacao(self.base.largura, self.base.profundidade)
        self.oc_fotonica = Ocupacao(self.base.largura, self.base.profundidade)   # camada interna
        for p in self.pecas.values():
            self.oc.ocupar_poligono(_contorno(p), p.nome)
        z = montagem.zonas.get("vrm_cpu")
        if z:
            self.oc.retangulos.append((z["x0"], z["y0"], z["x1"], z["y1"], "vrm_cpu"))
        self.prot = {n: _protocolo_dos_pinos(p.peca) for n, p in self.pecas.items()}
        self.grade, self.espacamento = E.grade(cfg_optica)
        self.i3c = []            # [porta, dispositivos]
        self.reg_de_trilho = {}  # trilho -> regulador que o alimenta
        self.carga_trilho = defaultdict(float)     # trilho -> corrente (A)
        self._n = defaultdict(int)                 # contadores de vias e chaves por chip
        self.lambdas_tx = defaultdict(lambda: defaultdict(int))   # chip -> λ -> vias tx
        self.ca_fontes = defaultdict(list)         # (chip, (enlace, subcanal)) -> pontos do CA
        self.aux_alvos = {}

    # ------------------------------------------------------------------ util
    def _pino_xy(self, peca, nome):
        pc = self.pecas[peca]
        p = pc.peca.pino(nome)
        return _global(pc, p.x, p.y)

    def _padrao(self, peca, nome):
        return padrao_do_pino(self.prot[peca][nome], nome)

    def _ctl_i3c(self, bloco, porta="ctl"):
        if not self.i3c or self.i3c[-1][1] >= DISPOSITIVOS_POR_I3C:
            n = len(self.i3c)
            self.nl.porta("ctl:fpga", f"i3c{n}", "controle", "sai", barramento="I3C",
                          max_dispositivos=DISPOSITIVOS_POR_I3C)
            self.i3c.append([f"i3c{n}", 0])
        self.i3c[-1][1] += 1
        self.nl.ligar(("ctl:fpga", self.i3c[-1][0]), (bloco, porta), "trilha")

    def _ctl_celula(self, bloco, peca):
        """Célula -> controlador regional da peça (matriz) -> I3C do FPGA."""
        cid = f"ctl:cel:{peca}"
        if cid not in self.nl.blocos:
            pc = self.pecas[peca]
            alvo = (pc.x, pc.y - pc.peca.profundidade / 2 - 6)
            pos = self.oc.colocar(alvo, 4, 4, cid)
            self.nl.bloco(cid, "controlador", pos, peca=peca, capacidades=["controle-celulas"],
                          celulas=0)
            self.nl.porta(cid, "ctl", "controle", "entra")
            self.nl.porta(cid, "matriz", "controle", "sai", barramento="matriz",
                          max_dispositivos=CELULAS_POR_MATRIZ)
            self.nl.porta(cid, "vdd", "energia", "entra", tensao_v=1.8)
            self._ctl_i3c(cid)
            self._alimentar(cid, "vdd", "rail:aux:1V8", 0.02)
        self.nl.blocos[cid].atributos["celulas"] += 1
        self.nl.ligar((cid, "matriz"), (bloco, "ctl"), "trilha")

    def _alimentar(self, bloco, porta, trilho, corrente_a):
        if trilho not in self.nl.blocos and trilho in self.aux_alvos:
            v, alvo = self.aux_alvos[trilho]
            self.reg(trilho.replace("rail:", ""), v, alvo)
        self.nl.ligar((trilho, "rede"), (bloco, porta), "trilha")
        self.nl.blocos[bloco].portas[porta].atributos["corrente_a"] = round(corrente_a, 5)
        self.carga_trilho[trilho] += corrente_a

    # ------------------------------------------------------------ infraestrutura
    def infraestrutura(self):
        nl = self.nl
        e12 = self.m.zonas.get("entrada_12v", {"x": 6, "y": 130})
        nl.bloco("fonte:atx", "fonte", (e12["x"], e12["y"]), potencia_w=850,
                 capacidades=["12V-cabo", "energia"])
        nl.porta("fonte:atx", "12v", "energia", "sai", tensao_v=12.0, corrente_a=60.0)
        nl.porta("fonte:atx", "pcie_12v", "energia", "sai", tensao_v=12.0, corrente_a=50.0)
        nl.bloco("rail:12V", "trilho", (e12["x"] + 8, e12["y"]), tensao_v=12.0)
        nl.porta("rail:12V", "rede", "energia", "bidir", tensao_v=12.0)
        nl.ligar(("fonte:atx", "12v"), ("rail:12V", "rede"), "trilha")

        fpga = self.pecas["FPGA"]
        caps = ["controle", "sequenciamento-PWROK", "SPD/I3C"]
        if "XCVR" in fpga.peca.interfaces:          # DMI exige transceptores, não E/S comum
            caps.append("PCH/DMI")
        nl.bloco("ctl:fpga", "controlador", (fpga.x, fpga.y), peca="FPGA", capacidades=caps)
        nl.porta("ctl:fpga", "vdd", "energia", "entra", tensao_v=0.85)
        nl.porta("ctl:fpga", "spi_flash", "controle", "sai", barramento="SPI")

        z = self.m.zonas["vrm_cpu"]
        vx, vy = (z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2
        nl.bloco("ctl:vrm", "controlador", (vx, z["y0"] + 4), capacidades=["VR-SVID"],
                 fases=z.get("fases", 8))
        for s in ("svid_clk", "svid_data", "svid_alert"):
            nl.porta("ctl:vrm", s, "eletrico", "bidir" if s == "svid_data" else
                     ("entra" if s == "svid_clk" else "sai"),
                     padrao="SVID-DATA" if s == "svid_data" else "SVID")
        nl.porta("ctl:vrm", "pwm", "controle", "sai", fases=z.get("fases", 8))
        nl.porta("ctl:vrm", "ctl", "controle", "entra")
        nl.porta("ctl:vrm", "vdd", "energia", "entra", tensao_v=3.3)

        cx, cy = self.oc.colocar((fpga.x + 30, fpga.y), 6, 6, "clk:ref")
        nl.bloco("clk:ref", "relogio", (cx, cy), frequencia_mhz=100.0, jitter_fs=100.0,
                 capacidades=["BCLK", "REFCLK"])
        nl.porta("clk:ref", "vdd", "energia", "entra", tensao_v=3.3)
        nl.porta("clk:ref", "ctl", "controle", "entra")
        fx, fy = self.oc.colocar((fpga.x, fpga.y - 28), 6, 5, "flash:uefi")
        nl.bloco("flash:uefi", "flash", (fx, fy), capacidade_mb=32, capacidades=["firmware-UEFI"])
        nl.porta("flash:uefi", "spi", "controle", "entra", barramento="SPI")
        nl.porta("flash:uefi", "vdd", "energia", "entra", tensao_v=1.8)
        nl.ligar(("ctl:fpga", "spi_flash"), ("flash:uefi", "spi"), "trilha")

        # trilhos auxiliares: criados no primeiro uso
        self.aux_alvos = {"rail:aux:3V3": (3.3, (e12["x"] + 20, e12["y"] + 20)),
                          "rail:aux:1V8": (1.8, (fpga.x + 25, fpga.y - 20)),
                          "rail:aux:1V05": (1.05, (vx, z["y1"] + 8)),
                          "rail:aux:1V1": (1.1, (vx, z["y1"] + 16)),
                          "rail:aux:1V2": (1.2, (110, 112))}
        self._alimentar("ctl:vrm", "vdd", "rail:aux:3V3", 0.05)
        self._alimentar("clk:ref", "vdd", "rail:aux:3V3", 0.1)
        self._alimentar("flash:uefi", "vdd", "rail:aux:1V8", 0.02)
        self._ctl_i3c("clk:ref")
        self._ctl_i3c("ctl:vrm")

        # trilhos das peças
        for nome, pc in self.pecas.items():
            for t in pc.peca.trilhos.values():
                rid = f"rail:{nome}:{t.nome}"
                if t.origem == "cabo":
                    nl.bloco(rid, "trilho", (pc.x, pc.y), tensao_v=12.0, peca=nome,
                             trilho_peca=t.nome, nota="VRM da própria GPU, pelo cabo")
                    nl.porta(rid, "rede", "energia", "bidir", tensao_v=12.0)
                    nl.ligar(("fonte:atx", "pcie_12v"), (rid, "rede"), "cabo")
                    potencia = t.tensao * t.corrente_max
                    self.carga_cabo = potencia / 12.0 / 0.9
                    self._consumidor(nome, t, rid, self.carga_cabo)
                    continue
                nl.bloco(rid, "trilho", (pc.x, pc.y), tensao_v=t.tensao, peca=nome,
                         trilho_peca=t.nome, corrente_a=t.corrente_max)
                nl.porta(rid, "rede", "energia", "bidir", tensao_v=t.tensao)
                if nome == "CPU" and t.nome == "VCCIN":
                    rg = "reg:CPU:VCCIN"
                    if rg not in nl.blocos:
                        nl.bloco(rg, "regulador", (vx, vy), tensao_v=t.tensao,
                                 corrente_max_a=0.0, fases=z.get("fases", 8),
                                 controle="SVID", capacidades=["energia"])
                        nl.porta(rg, "vin", "energia", "entra", tensao_v=12.0)
                        nl.porta(rg, "vout", "energia", "sai", tensao_v=t.tensao)
                        nl.porta(rg, "ctl", "controle", "entra")
                        nl.ligar(("rail:12V", "rede"), (rg, "vin"), "trilha")
                        nl.ligar(("ctl:vrm", "pwm"), (rg, "ctl"), "trilha")
                else:
                    rg = f"reg:{pc.tipo}:{t.nome}"
                    if rg not in nl.blocos:
                        pos = self.oc.colocar((pc.x, pc.y - pc.peca.profundidade / 2 - 12), 6, 6, rg)
                        nl.bloco(rg, "regulador", pos, tensao_v=t.tensao, corrente_max_a=0.0,
                                 capacidades=["energia"])
                        nl.porta(rg, "vin", "energia", "entra", tensao_v=12.0)
                        nl.porta(rg, "vout", "energia", "sai", tensao_v=t.tensao)
                        nl.porta(rg, "ctl", "controle", "entra")
                        nl.ligar(("rail:12V", "rede"), (rg, "vin"), "trilha")
                        self._ctl_i3c(rg)
                nl.ligar((rg, "vout"), (rid, "rede"), "trilha")
                self.reg_de_trilho[rid] = rg
                self._consumidor(nome, t, rid, t.corrente_max)
        self._alimentar("ctl:fpga", "vdd", "rail:FPGA:VCCINT", 0.0)

    def _consumidor(self, peca, trilho, rid, corrente_a):
        """Os pinos de alimentação de um trilho da peça, agregados num bloco só."""
        pc = self.pecas[peca]
        idx = [i for i, p in enumerate(pc.peca.pinos) if p.grupo == trilho.nome]
        celulas = sum(len(pc.celulas_do_pino.get(i, [])) for i in idx)
        bid = f"{peca}:{trilho.nome}"
        self.nl.bloco(bid, "pino", (pc.x, pc.y), peca=peca, pino=trilho.nome, n_pinos=len(idx),
                      n_celulas=celulas, chave=self.chave_celula.nome, r_on_ohm=self.chave_celula.r_on_ohm,
                      c_ff=self.chave_celula.c_off_ff, origem=trilho.origem)
        self.nl.porta(bid, "e", "energia", "entra", tensao_v=trilho.tensao if trilho.origem == "base"
                      else 12.0)
        self._alimentar(bid, "e", rid, corrente_a)

    def reg(self, nome, tensao, alvo):
        rg, rid = f"reg:{nome}", f"rail:{nome}"
        pos = self.oc.colocar(alvo, 6, 6, rg)
        self.nl.bloco(rg, "regulador", pos, tensao_v=tensao, corrente_max_a=0.0,
                      capacidades=["energia"])
        self.nl.porta(rg, "vin", "energia", "entra", tensao_v=12.0)
        self.nl.porta(rg, "vout", "energia", "sai", tensao_v=tensao)
        self.nl.porta(rg, "ctl", "controle", "entra")
        self.nl.bloco(rid, "trilho", pos, tensao_v=tensao)
        self.nl.porta(rid, "rede", "energia", "bidir", tensao_v=tensao)
        self.nl.ligar(("rail:12V", "rede"), (rg, "vin"), "trilha")
        self.nl.ligar((rg, "vout"), (rid, "rede"), "trilha")
        self.reg_de_trilho[rid] = rg
        self._ctl_i3c(rg)
        return rid

    # --------------------------------------------------------- pino, célula, trilha
    def pino(self, peca, nome, sentido, padrao=None):
        """Garante pino + célula + trilha; devolve o id da trilha (ponta "b" livre)."""
        pid, cid, tid = f"{peca}:{nome}", f"cel:{peca}:{nome}", f"tr:{peca}:{nome}"
        if pid in self.nl.blocos:
            return tid
        nl = self.nl
        pad = padrao or self._padrao(peca, nome)
        xy = self._pino_xy(peca, nome)
        pc = self.pecas[peca]
        idx = next(i for i, p in enumerate(pc.peca.pinos) if p.nome == nome)
        n_cel = len(pc.celulas_do_pino.get(idx, []))
        nl.bloco(pid, "pino", xy, peca=peca, pino=nome)
        nl.porta(pid, "e", "eletrico", sentido, padrao=pad)
        # r_on e c_ff são por célula; o verificador combina as n_celulas em paralelo
        nl.bloco(cid, "celula", xy, peca=peca, n_celulas=n_cel, r_on_ohm=self.chave_celula.r_on_ohm,
                 c_ff=self.chave_celula.c_off_ff, chave=self.chave_celula.nome)
        nl.porta(cid, "pino", "eletrico", "bidir", padrao=pad)
        nl.porta(cid, "base", "eletrico", "bidir", padrao=pad)
        nl.porta(cid, "ctl", "controle", "entra")
        nl.ligar((pid, "e"), (cid, "pino"), "contato", n_celulas=n_cel)
        self._ctl_celula(cid, peca)
        modo = PADROES[pad].modo
        nl.bloco(tid, "trilha", xy, comprimento_mm=0.0, z_ohm=Z_TRILHA_OHM[modo],
                 perda_db_mm_ghz=PERDA_DB_MM_GHZ, camada=None, de=pid)
        nl.porta(tid, "a", "eletrico", "bidir", padrao=pad)
        nl.porta(tid, "b", "eletrico", "bidir", padrao=pad)
        nl.ligar((cid, "base"), (tid, "a"), "trilha")
        return tid

    def _comprimento(self, tid, ate_xy, camada, vertical_mm=0.0):
        b = self.nl.blocos[tid]
        b.atributos["comprimento_mm"] = round(manhattan(b.posicao, ate_xy) + vertical_mm, 2)
        b.atributos["camada"] = camada
        b.atributos["ate"] = (round(ate_xy[0], 2), round(ate_xy[1], 2))

    def _ate_chip(self, tid, chip):
        """Trilha do pino até o chip: lateral na base, ou descendo até a camada de fotônica."""
        ch = self.nl.blocos[chip]
        vertical = VERTICAL_FOTONICA_MM if ch.atributos.get("camada") == "fotonica" else 0.0
        self._comprimento(tid, ch.posicao, "sinal", vertical)

    # ------------------------------------------------------------------ chips
    def chips(self):
        """Agrupa as vias de cada peça por fibra e empacota em chips."""
        canais = self.plano.canais
        self.rapidos = [i for i, c in enumerate(canais) if self._rapido(c)]
        vias = defaultdict(lambda: defaultdict(int))      # peca -> fibra -> vias
        tensao = {}
        pontos = defaultdict(list)                        # (peca, fibra) -> posições dos pinos
        for i in self.rapidos:
            c = canais[i]
            for lado, peca, pino in (("a", c.origem, c.pino_origem), ("b", c.destino, c.pino_destino)):
                tx, rx = self._papeis(c, lado)
                vias[peca][c.fibra] += tx + rx
                tensao[(peca, c.fibra)] = PADROES[self._padrao(peca, pino)].tensao_v
                pontos[(peca, c.fibra)].append(self._pino_xy(peca, pino))
        self.chip_de = {}
        self.chips_da_peca = defaultdict(list)
        # peças com menos vias escolhem lugar primeiro (as GDDR7 antes da GPU)
        for peca, por_fibra in sorted(vias.items(), key=lambda kv: (sum(kv[1].values()), kv[0])):
            pc = self.pecas[peca]
            grupos = defaultdict(list)
            for f, n in por_fibra.items():
                cx, cy = np.mean(pontos[(peca, f)], axis=0)
                angulo = math.atan2(cy - pc.y, cx - pc.x)
                grupos[tensao[(peca, f)]].append((angulo, n, f))
            k = 0
            caixas_peca = []
            for v, lista in sorted(grupos.items()):
                # fibras vizinhas no mesmo chip: cada chip atende um trecho contínuo da peça
                lista.sort()
                total = sum(n for _, n, _ in lista)
                n_chips = math.ceil(total / VIAS_MAX)
                alvo_por_chip = total / n_chips
                caixas = [[0, []]]
                for _, n, f in lista:
                    cx = caixas[-1]
                    if cx[1] and (cx[0] + n > VIAS_MAX or
                                  (cx[0] >= alvo_por_chip and len(caixas) < n_chips)):
                        caixas.append([0, []])
                        cx = caixas[-1]
                    cx[0] += n
                    cx[1].append(f)
                for usadas, fs in caixas:
                    centro = np.mean([q for f in fs for q in pontos[(peca, f)]], axis=0)
                    caixas_peca.append((v, tuple(centro), fs))
            alvos = [c for _, c, _ in caixas_peca]
            if self.posicionamento == "sob_peca":
                # camada de fotônica dentro da base: uma grade de vagas debaixo da peça,
                # cada grupo de pinos na vaga mais próxima (atribuição ótima)
                vagas = self._vagas_sob(pc)
                if len(vagas) >= len(caixas_peca):
                    custo = np.array([[math.dist(a, s) for s in vagas] for a in alvos])
                    lin, col = linear_sum_assignment(custo)
                    alvos = [vagas[j] for _, j in sorted(zip(lin, col))]
            for (v, centro, fs), alvo in zip(caixas_peca, alvos):
                cid = f"tx:{peca}:{k}"
                k += 1
                if self.posicionamento == "sob_peca":
                    pos = self.oc_fotonica.colocar(alvo, CHIP_MM[0], CHIP_MM[1], cid)
                else:
                    pos = self.oc.colocar(self._fora_da_peca(pc, centro), CHIP_MM[0], CHIP_MM[1], cid)
                self._criar_chip(cid, peca, pos, v)
                self.chips_da_peca[peca].append(cid)
                for f in fs:
                    self.chip_de[(peca, f)] = cid
        self._saida_trilhas()

    def _vagas_sob(self, pc, sobra_mm=2.0):
        """Centros de uma grade de chips debaixo da peça (com uma pequena sobra na borda)."""
        passo = CHIP_MM[0] + 1.2
        out = []
        w = pc.peca.largura + 2 * sobra_mm
        d = pc.peca.profundidade + 2 * sobra_mm
        nx = max(1, int((w - CHIP_MM[0]) // passo) + 1)
        ny = max(1, int((d - CHIP_MM[1]) // passo) + 1)
        for i in range(nx):
            for j in range(ny):
                lx = (i - (nx - 1) / 2) * passo
                ly = (j - (ny - 1) / 2) * passo
                out.append(tuple(round(float(q), 3) for q in _global(pc, lx, ly)))
        return out

    @staticmethod
    def _fora_da_peca(pc, ponto):
        """Ponto logo fora da borda da peça mais próxima de `ponto`."""
        c, s = math.cos(math.radians(pc.rot)), math.sin(math.radians(pc.rot))
        dx, dy = ponto[0] - pc.x, ponto[1] - pc.y
        lx, ly = c * dx + s * dy, -s * dx + c * dy
        w, h = pc.peca.largura / 2, pc.peca.profundidade / 2
        d = CHIP_MM[0] / 2 + AFASTAMENTO_CHIP_MM
        opcoes = [(w - lx, (w + d, ly)), (lx + w, (-w - d, ly)),
                  (h - ly, (lx, h + d)), (ly + h, (lx, -h - d))]
        qx, qy = min(opcoes)[1]
        return _global(pc, qx, qy)

    def _criar_chip(self, cid, peca, pos, vddio):
        nl = self.nl
        nl.bloco(cid, "chip_tradutor", pos, peca=peca, vias_max=VIAS_MAX, largura_mm=CHIP_MM[0],
                 profundidade_mm=CHIP_MM[1], potencia_w=CONTROLE_CHIP_W, vddio_v=vddio,
                 vias_tx=0, vias_rx=0,
                 camada="fotonica" if self.posicionamento == "sob_peca" else "superficie")
        nl.porta(cid, "vdd", "energia", "entra", tensao_v=VDD_CHIP_V)
        nl.porta(cid, "vddio", "energia", "entra", tensao_v=vddio)
        nl.porta(cid, "ctl", "controle", "entra")
        nl.porta(cid, "laser", "optico", "entra", lambdas_nm=[])
        self._ctl_i3c(cid)

    def _saida_trilhas(self):
        """Quantas trilhas saem de baixo de cada peça contra quantas cabem."""
        demanda = defaultdict(int)
        for c in self.plano.canais:
            demanda[c.origem] += 1
            demanda[c.destino] += 1
        for peca, chips in self.chips_da_peca.items():
            pc = self.pecas[peca]
            perimetro = 2 * (pc.peca.largura + pc.peca.profundidade)
            cap = int(perimetro / PASSO_TRILHA_MM) * CAMADAS_SINAL
            for cid in chips:
                self.nl.blocos[cid].atributos["saida_peca"] = {"demanda": demanda[peca],
                                                               "capacidade": cap}

    def _rapido(self, c):
        if c.papel == "REFCLK":
            return False
        return (PADROES[self._padrao(c.origem, c.pino_origem)].alta_velocidade
                or PADROES[self._padrao(c.destino, c.pino_destino)].alta_velocidade)

    @staticmethod
    def _papeis(c, lado):
        """(tx, rx) vias que o canal pede no lado a ou b."""
        if c.sentido == "duplo":
            return 1, 1
        transmite = (c.sentido == "ida") == (lado == "a")
        return (1, 0) if transmite else (0, 1)

    def _via(self, chip, tipo, padrao, lam, taxa, atividade=1.0):
        nl = self.nl
        n = self._n[(chip, tipo)]
        self._n[(chip, tipo)] += 1
        vid = f"{chip}:{tipo}{n}"
        tx = tipo == "t"
        nl.bloco(vid, "via_tx" if tx else "via_rx", nl.blocos[chip].posicao, pai=chip,
                 lambda_nm=round(float(self.grade[lam]), 4), lambda_idx=lam, taxa_gbps=taxa)
        suportados = sorted(p for p, d in PADROES.items() if d.alta_velocidade)
        if tx:
            nl.porta(vid, "e", "eletrico", "entra", padrao=padrao, padroes=suportados)
            nl.porta(vid, "luz", "optico", "sai", lambda_nm=float(self.grade[lam]))
            nl.porta(vid, "laser", "optico", "entra", lambda_nm=float(self.grade[lam]))
            nl.ligar((chip, "laser"), (vid, "laser"), "guia")
            self.lambdas_tx[chip][lam] += 1
            nl.blocos[chip].atributos["vias_tx"] += 1
        else:
            nl.porta(vid, "luz", "optico", "entra", lambda_nm=float(self.grade[lam]))
            nl.porta(vid, "e", "eletrico", "sai", padrao=padrao, padroes=suportados,
                     terminacao=PADROES[padrao].terminacao)
            nl.blocos[chip].atributos["vias_rx"] += 1
        nl.porta(vid, "vdd", "energia", "entra", tensao_v=VDD_CHIP_V)
        nl.porta(vid, "ctl", "controle", "entra")
        nl.ligar((chip, "vdd"), (vid, "vdd"), "interno")
        nl.ligar((chip, "ctl"), (vid, "ctl"), "interno")
        pj = PJ_BIT_TX if tx else PJ_BIT_RX
        nl.blocos[chip].atributos["potencia_w"] += taxa * pj * 1e-3 * atividade + AQUECEDOR_MW * 1e-3
        nl.blocos[vid].atributos["atividade"] = atividade
        return vid

    # ------------------------------------------------------------ fibras e óptica
    def fibras(self):
        nl = self.nl
        canais = self.plano.canais
        rapidos = set(self.rapidos)
        self.cadeia = {}            # fibra -> [(peca, chip, elementos)] na ordem do fluxo
        self.segmentos = {}
        for f in self.plano.fibras:
            if not any(i in rapidos for i in f.canais):
                continue
            ordem = [f.hub] + list(f.destinos)
            if f.sentido == "volta":
                ordem = ordem[::-1]
            duplo = f.sentido == "duplo"
            lam = [round(float(self.grade[canais[i].lambda_idx]), 4) for i in f.canais if i in rapidos]
            # quem transmite / recebe em cada parada
            tx_em, rx_em = defaultdict(bool), defaultdict(bool)
            for i in f.canais:
                if i not in rapidos:
                    continue
                c = canais[i]
                for lado, peca in (("a", c.origem), ("b", c.destino)):
                    t, r = self._papeis(c, lado)
                    tx_em[peca] |= bool(t)
                    rx_em[peca] |= bool(r)
            se = "bidir" if duplo else None
            paradas = []
            for k, peca in enumerate(ordem):
                chip = self.chip_de[(peca, f.id)]
                els = []
                if k > 0:
                    ac = f"{chip}:ac{f.id}"
                    nl.bloco(ac, "acoplador", nl.blocos[chip].posicao, pai=chip, perda_db=1.5)
                    nl.porta(ac, "fibra", "optico", se or "entra")
                    nl.porta(ac, "chip", "optico", se or "sai")
                    els.append(("ac", ac, "fibra", "chip"))
                if rx_em[peca]:
                    dm = f"{chip}:demux{f.id}"
                    nl.bloco(dm, "demux", nl.blocos[chip].posicao, pai=chip, fibra=f.id)
                    nl.porta(dm, "in", "optico", se or "entra")
                    nl.porta(dm, "passa", "optico", se or "sai")
                    els.append(("demux", dm, "in", "passa"))
                if tx_em[peca]:
                    mx = f"{chip}:mux{f.id}"
                    nl.bloco(mx, "mux", nl.blocos[chip].posicao, pai=chip, fibra=f.id)
                    nl.porta(mx, "passa", "optico", se or "entra")
                    nl.porta(mx, "out", "optico", se or "sai")
                    els.append(("mux", mx, "passa", "out"))
                if k < len(ordem) - 1:
                    ac = f"{chip}:ac{f.id}s"
                    nl.bloco(ac, "acoplador", nl.blocos[chip].posicao, pai=chip, perda_db=1.5)
                    nl.porta(ac, "chip", "optico", se or "entra")
                    nl.porta(ac, "fibra", "optico", se or "sai")
                    els.append(("ac", ac, "chip", "fibra"))
                for (_, b1, _, p1), (_, b2, p2, _) in zip(els, els[1:]):
                    nl.ligar((b1, p1), (b2, p2), "guia")
                paradas.append((peca, chip, els))
            segs = []
            for k in range(len(ordem) - 1):
                sid = f"fib:{f.id}" if len(ordem) == 2 else f"fib:{f.id}.{k}"
                a_peca, b_peca = ordem[k], ordem[k + 1]
                da = f.distancia_ate.get(a_peca, 0.0) if a_peca != f.hub else 0.0
                db = f.distancia_ate.get(b_peca, 0.0) if b_peca != f.hub else 0.0
                comp = abs(db - da)
                pa, pb = nl.blocos[paradas[k][1]].posicao, nl.blocos[paradas[k + 1][1]].posicao
                nl.bloco(sid, "fibra", ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2),
                         comprimento_mm=round(comp, 1), lambdas_nm=lam, sentido=f.sentido,
                         perda_db=round(2 * PERDA_CONECTOR_DB + comp * PERDA_FIBRA_DB_MM, 3),
                         protocolo=f.protocolo, de=paradas[k][1], para=paradas[k + 1][1],
                         rota=[(round(x, 2), round(y, 2)) for x, y in f.rota])
                nl.porta(sid, "a", "optico", se or "entra")
                nl.porta(sid, "b", "optico", se or "sai")
                nl.ligar((paradas[k][2][-1][1], "fibra"), (sid, "a"), "fibra")
                nl.ligar((sid, "b"), (paradas[k + 1][2][0][1], "fibra"), "fibra")
                segs.append(sid)
            self.cadeia[f.id] = paradas
            self.segmentos[f.id] = segs

    def _optico(self, f, i_tx, i_rx, lam, vtx, vrx):
        """Caminho óptico da via_tx na parada i_tx até a via_rx na parada i_rx."""
        nl = self.nl
        paradas, segs = self.cadeia[f], self.segmentos[f]
        caminho = [(vtx, "luz")]
        _, _, els = paradas[i_tx]
        mx = next(e for e in els if e[0] == "mux")
        nl.porta(mx[1], f"in{lam}", "optico", "entra", lambda_nm=float(self.grade[lam]))
        nl.ligar((vtx, "luz"), (mx[1], f"in{lam}"), "guia")
        pos_mx = els.index(mx)
        if i_rx > i_tx:
            caminho += [(mx[1], f"in{lam}"), (mx[1], mx[3])]
            for e in els[pos_mx + 1:]:
                caminho += [(e[1], e[2]), (e[1], e[3])]
            for s in range(i_tx + 1, i_rx + 1):
                caminho += [(segs[s - 1], "a"), (segs[s - 1], "b")]
                for e in paradas[s][2]:
                    if s == i_rx and e[0] == "demux":
                        caminho += [(e[1], "in"), (e[1], f"out{lam}")]
                        break
                    caminho += [(e[1], e[2]), (e[1], e[3])]
        else:
            caminho += [(mx[1], f"in{lam}"), (mx[1], mx[2])]
            for e in reversed(els[:pos_mx]):
                caminho += [(e[1], e[3]), (e[1], e[2])]
            for s in range(i_tx - 1, i_rx - 1, -1):
                caminho += [(segs[s], "b"), (segs[s], "a")]
                for e in reversed(paradas[s][2]):
                    if s == i_rx and e[0] == "demux":
                        caminho += [(e[1], "passa"), (e[1], f"out{lam}")]
                        break
                    caminho += [(e[1], e[3]), (e[1], e[2])]
        dm = caminho[-1][0]
        if f"out{lam}" not in nl.blocos[dm].portas:
            nl.porta(dm, f"out{lam}", "optico", "sai", lambda_nm=float(self.grade[lam]))
        nl.ligar((dm, f"out{lam}"), (vrx, "luz"), "guia")
        return caminho + [(vrx, "luz")]

    # ------------------------------------------------------------ sinais rápidos
    def sinais_rapidos(self):
        nl = self.nl
        canais = self.plano.canais
        self.chave = {}                  # (peca, pino) -> (chave, via_tx, via_rx)
        self.ca_por_chave = defaultdict(list)
        trilhas_do_grupo = defaultdict(set)      # (enlace, grupo, peca) -> trilhas
        for i in self.rapidos:
            c = canais[i]
            f = c.fibra
            paradas = self.cadeia[f]
            idx = {p[0]: k for k, p in enumerate(paradas)}
            pad_a = self._padrao(c.origem, c.pino_origem)
            pad_b = self._padrao(c.destino, c.pino_destino)
            prot = c.protocolo
            pontas = {}
            for lado, peca, pino, pad in (("a", c.origem, c.pino_origem, pad_a),
                                         ("b", c.destino, c.pino_destino, pad_b)):
                sentido_pino = DIREITO[c.sentido] if lado == "a" else INVERSO[c.sentido]
                tid = self.pino(peca, pino, sentido_pino, pad)
                chip = self.chip_de[(peca, f)]
                self._ate_chip(tid, chip)
                t, r = self._papeis(c, lado)
                atv = 0.5 if c.sentido == "duplo" else 1.0       # tx e rx se alternam
                vtx = self._via(chip, "t", pad, c.lambda_idx, c.taxa_gbps, atv) if t else None
                vrx = self._via(chip, "r", pad, c.lambda_idx, c.taxa_gbps, atv) if r else None
                ch = None
                if c.sentido == "duplo":
                    ch = f"{chip}:s{self._n[(chip, 's')]}"
                    self._n[(chip, "s")] += 1
                    nl.bloco(ch, "chave_sentido", nl.blocos[chip].posicao, pai=chip, pino=f"{peca}:{pino}")
                    nl.porta(ch, "pino", "eletrico", "bidir", padrao=pad)
                    nl.porta(ch, "tx", "eletrico", "sai", padrao=pad)
                    nl.porta(ch, "rx", "eletrico", "entra", padrao=pad)
                    nl.porta(ch, "sentido", "controle", "entra")
                    nl.ligar((tid, "b"), (ch, "pino"), "trilha")
                    nl.ligar((ch, "tx"), (vtx, "e"), "interno")
                    nl.ligar((vrx, "e"), (ch, "rx"), "interno")
                    self.ca_por_chave[chip].append((ch, c.enlace, c.grupo.rsplit("_", 1)[0]))
                elif vtx:
                    nl.ligar((tid, "b"), (vtx, "e"), "trilha")
                else:
                    nl.ligar((vrx, "e"), (tid, "b"), "trilha")
                pontas[lado] = dict(peca=peca, pino=pino, tid=tid, vtx=vtx, vrx=vrx, ch=ch, chip=chip)
                trilhas_do_grupo[(c.enlace, c.grupo, peca)].add(tid)
                if c.papel in ("CA", "CS", "CK"):
                    chave_grupo = (c.enlace, c.grupo.rsplit("_", 1)[0])
                    ponto = (tid, "b") if lado == "a" else (vrx, "e")
                    self.ca_fontes[(chip, chave_grupo)].append(ponto)

            def eletrico_tx(p):
                cam = [(f"{p['peca']}:{p['pino']}", "e"), (f"cel:{p['peca']}:{p['pino']}", "pino"),
                       (f"cel:{p['peca']}:{p['pino']}", "base"), (p["tid"], "a"), (p["tid"], "b")]
                if p["ch"]:
                    cam += [(p["ch"], "pino"), (p["ch"], "tx")]
                return cam + [(p["vtx"], "e")]

            def eletrico_rx(p):
                cam = [(p["vrx"], "e")]
                if p["ch"]:
                    cam += [(p["ch"], "rx"), (p["ch"], "pino")]
                return cam + [(p["tid"], "b"), (p["tid"], "a"), (f"cel:{p['peca']}:{p['pino']}", "base"),
                              (f"cel:{p['peca']}:{p['pino']}", "pino"), (f"{p['peca']}:{p['pino']}", "e")]

            def caminho(tx, rx):
                opt = self._optico(f, idx[tx["peca"]], idx[rx["peca"]], c.lambda_idx, tx["vtx"], rx["vrx"])
                return eletrico_tx(tx) + opt + eletrico_rx(rx)

            a, b = pontas["a"], pontas["b"]
            if c.sentido == "volta":
                orig, dest = b, a
            else:
                orig, dest = a, b
            sid = f"{orig['peca']}.{orig['pino']}->{dest['peca']}.{dest['pino']}"
            s = Sinal(sid, prot, c.papel, pad_a if orig is a else pad_b,
                      (f"{orig['peca']}:{orig['pino']}", "e"), (f"{dest['peca']}:{dest['pino']}", "e"),
                      ("ida", "volta") if c.sentido == "duplo" else ("ida",), c.grupo)
            s.caminhos["ida"] = caminho(orig, dest)
            if c.sentido == "duplo":
                s.caminhos["volta"] = caminho(dest, orig)
            nl.sinal(s)
        self._casar_comprimentos(trilhas_do_grupo)
        self._detectores()

    def _casar_comprimentos(self, grupos):
        """Serpentina: dentro de um grupo síncrono, toda trilha fica com o comprimento da maior."""
        for tids in grupos.values():
            if len(tids) < 2:
                continue
            maior = max(self.nl.blocos[t].atributos["comprimento_mm"] for t in tids)
            for t in tids:
                a = self.nl.blocos[t].atributos
                a["serpentina_mm"] = round(maior - a["comprimento_mm"], 2)
                a["comprimento_mm"] = round(maior, 2)

    def _detectores(self):
        nl = self.nl
        fontes = self.ca_fontes
        for chip, chaves in self.ca_por_chave.items():
            det = f"{chip}:det"
            nl.bloco(det, "detector_sentido", nl.blocos[chip].posicao, pai=chip)
            nl.porta(det, "sentido", "controle", "sai")
            nl.porta(det, "vdd", "energia", "entra", tensao_v=VDD_CHIP_V)
            nl.ligar((chip, "vdd"), (det, "vdd"), "interno")
            grupos = sorted({(e, g) for _, e, g in chaves})
            k = 0
            for g in grupos:
                # o CA daquele subcanal pode estar em outro chip da mesma peça
                peca = nl.blocos[chip].atributos["peca"]
                pontos = []
                for (ch2, g2), pts in fontes.items():
                    if g2 == g and nl.blocos[ch2].atributos["peca"] == peca:
                        pontos += pts
                for ponto in pontos:
                    pad = nl.blocos[ponto[0]].portas[ponto[1]].padrao
                    nl.porta(det, f"ca{k}", "eletrico", "entra", padrao=pad, grupo=g[1])
                    nl.ligar(ponto, (det, f"ca{k}"), "trilha" if ponto[0] != chip else "interno")
                    k += 1
            nl.blocos[det].atributos["entradas_ca"] = k
            for ch, _, _ in chaves:
                nl.ligar((det, "sentido"), (ch, "sentido"), "interno")

    # ------------------------------------------------------------ sinais lentos
    def sinais_lentos(self):
        nl = self.nl
        for c in self.plano.canais:
            if c.papel == "REFCLK" or self._rapido(c):
                continue
            a_peca, a_pino, b_peca, b_pino = c.origem, c.pino_origem, c.destino, c.pino_destino
            if a_pino in ("SVID_CLK", "SVID_DATA", "SVID_ALERT", "BCLK"):
                continue
            self._lento(c, a_peca, a_pino, b_peca, b_pino)
        # SVID: CPU <-> controlador do VRM
        for pino, porta, sentido in (("SVID_CLK", "svid_clk", "ida"), ("SVID_DATA", "svid_data", "duplo"),
                                     ("SVID_ALERT", "svid_alert", "volta")):
            tid = self.pino("CPU", pino, DIREITO[sentido])
            self._comprimento(tid, nl.blocos["ctl:vrm"].posicao, CAMADA_LENTA)
            nl.ligar((tid, "b"), ("ctl:vrm", porta), "trilha")
            self._pullup(f"CPU:{pino}", ("ctl:vrm", porta), "rail:aux:1V05", 1.05)
            cam = [("CPU:" + pino, "e"), (f"cel:CPU:{pino}", "pino"), (f"cel:CPU:{pino}", "base"),
                   (tid, "a"), (tid, "b"), ("ctl:vrm", porta)]
            orig, dest = (("CPU:" + pino, "e"), ("ctl:vrm", porta))
            sid = f"CPU.{pino}->VRM.{porta}"
            if sentido == "volta":
                sid = f"VRM.{porta}->CPU.{pino}"
                orig, dest, cam = dest, orig, cam[::-1]
            s = Sinal(sid, "AUX", pino, padrao_do_pino("AUX", pino), orig, dest,
                      ("ida", "volta") if sentido == "duplo" else ("ida",), "SVID")
            s.caminhos["ida"] = cam
            if sentido == "duplo":
                s.caminhos["volta"] = cam[::-1]
            nl.sinal(s)

    def _lento(self, c, a_peca, a_pino, b_peca, b_pino):
        nl = self.nl
        pad_a, pad_b = self._padrao(a_peca, a_pino), self._padrao(b_peca, b_pino)
        ta = self.pino(a_peca, a_pino, DIREITO[c.sentido], pad_a)
        tb = self.pino(b_peca, b_pino, INVERSO[c.sentido], pad_b)
        xa, xb = nl.blocos[ta].posicao, nl.blocos[tb].posicao
        meio = ((xa[0] + xb[0]) / 2, (xa[1] + xb[1]) / 2)
        self._comprimento(ta, meio, CAMADA_LENTA)
        self._comprimento(tb, meio, CAMADA_LENTA)
        va, vb = PADROES[pad_a].tensao_v, PADROES[pad_b].tensao_v
        meio_cam = []
        if abs(va - vb) > 0.05:
            cn = f"cn:{a_peca}:{a_pino}"
            nl.bloco(cn, "conversor_nivel", meio, bidirecional=c.sentido == "duplo")
            nl.porta(cn, "a", "eletrico", "bidir", padrao=pad_a)
            nl.porta(cn, "b", "eletrico", "bidir", padrao=pad_b)
            nl.porta(cn, "vcca", "energia", "entra", tensao_v=va)
            nl.porta(cn, "vccb", "energia", "entra", tensao_v=vb)
            self._alimentar(cn, "vcca", self._aux_rail(va), 0.001)
            self._alimentar(cn, "vccb", self._aux_rail(vb), 0.001)
            nl.ligar((ta, "b"), (cn, "a"), "trilha")
            nl.ligar((cn, "b"), (tb, "b"), "trilha")
            meio_cam = [(cn, "a"), (cn, "b")]
        else:
            nl.ligar((ta, "b"), (tb, "b"), "trilha")
        for peca, pino, pad, t in ((a_peca, a_pino, pad_a, ta), (b_peca, b_pino, pad_b, tb)):
            if PADROES[pad].terminacao == "dreno_aberto":
                self._pullup(f"{peca}:{pino}", (t, "b"), self._aux_rail(PADROES[pad].tensao_v),
                             PADROES[pad].tensao_v)
        cam = [(f"{a_peca}:{a_pino}", "e"), (f"cel:{a_peca}:{a_pino}", "pino"),
               (f"cel:{a_peca}:{a_pino}", "base"), (ta, "a"), (ta, "b")] + meio_cam + \
              [(tb, "b"), (tb, "a"), (f"cel:{b_peca}:{b_pino}", "base"),
               (f"cel:{b_peca}:{b_pino}", "pino"), (f"{b_peca}:{b_pino}", "e")]
        if c.sentido == "volta":
            cam = cam[::-1]
            orig, dest = (b_peca, b_pino), (a_peca, a_pino)
        else:
            orig, dest = (a_peca, a_pino), (b_peca, b_pino)
        s = Sinal(f"{orig[0]}.{orig[1]}->{dest[0]}.{dest[1]}", c.protocolo, c.papel,
                  self._padrao(*orig), (f"{orig[0]}:{orig[1]}", "e"), (f"{dest[0]}:{dest[1]}", "e"),
                  ("ida", "volta") if c.sentido == "duplo" else ("ida",), c.grupo)
        s.caminhos["ida"] = cam
        if c.sentido == "duplo":
            s.caminhos["volta"] = cam[::-1]
        nl.sinal(s)

    def sideband(self):
        """SPD de cada DIMM (HSCL/HSDA, I3C de 1,0 V) até pinos livres do FPGA, por trilha."""
        if "FPGA" not in self.pecas:
            return
        usados = {c.pino_destino for c in self.plano.canais if c.destino == "FPGA"}
        livres = iter(n for n in self.pecas["FPGA"].peca.interfaces["CTL"].sinais if n not in usados)
        for dimm in sorted(n for n in self.pecas if n.startswith("DIMM")):
            if "SPD" not in self.pecas[dimm].peca.interfaces:
                continue
            for pino, sentido in (("HSCL", "ida"), ("HSDA", "duplo")):
                c = _CanalLento("FPGA-" + dimm, sentido, "AUX", pino, "SPD_" + dimm)
                self._lento(c, "FPGA", next(livres), dimm, pino)

    def _aux_rail(self, v):
        for nome, tv in (("rail:aux:1V05", 1.05), ("rail:aux:1V1", 1.1), ("rail:aux:1V2", 1.2),
                         ("rail:aux:1V8", 1.8), ("rail:aux:3V3", 3.3)):
            if abs(tv - v) < 0.03:
                return nome
        return "rail:aux:1V05" if v < 1.0 else "rail:aux:3V3"

    def _pullup(self, nome, ponto, trilho, v):
        tid = f"pu:{nome}"
        if tid in self.nl.blocos:
            return
        self.nl.bloco(tid, "terminacao", self.nl.blocos[ponto[0]].posicao, ohm=PULLUP_OHM, funcao="pull-up")
        self.nl.porta(tid, "e", "eletrico", "bidir", padrao=self.nl.blocos[ponto[0]].portas[ponto[1]].padrao)
        self.nl.porta(tid, "vdd", "energia", "entra", tensao_v=v)
        self.nl.ligar(ponto, (tid, "e"), "trilha")
        self._alimentar(tid, "vdd", trilho, v / PULLUP_OHM)

    # ------------------------------------------------------------------ relógios
    def relogios(self):
        nl = self.nl
        alvos = []
        for peca in sorted(self.prot):
            for pino, prot in sorted(self.prot[peca].items()):
                if pino == "BCLK" or pino.startswith("REFCLK"):
                    alvos.append((peca, pino, prot))
        for n, (peca, pino, prot) in enumerate(alvos):
            nl.porta("clk:ref", f"out{n}", "eletrico", "sai", padrao="HCSL-100M")
            tid = self.pino(peca, pino, "entra", "HCSL-100M")
            self._comprimento(tid, nl.blocos["clk:ref"].posicao, CAMADA_LENTA)
            nl.ligar(("clk:ref", f"out{n}"), (tid, "b"), "trilha")
            # relógios independentes: cada um é o seu próprio grupo
            s = Sinal(f"clk:ref.out{n}->{peca}.{pino}", prot, "REFCLK", "HCSL-100M",
                      ("clk:ref", f"out{n}"), (f"{peca}:{pino}", "e"), ("ida",), f"REFCLK_{peca}_{pino}")
            s.caminhos["ida"] = [("clk:ref", f"out{n}"), (tid, "b"), (tid, "a"),
                                 (f"cel:{peca}:{pino}", "base"), (f"cel:{peca}:{pino}", "pino"),
                                 (f"{peca}:{pino}", "e")]
            nl.sinal(s)

    # --------------------------------------------------------------------- laser
    def laser(self):
        nl = self.nl
        cap = int(self.opt["lambdas_por_laser"]) * PENTES_POR_MODULO
        n_lam = len(self.grade)
        modulos = []            # [restante por λ (array), [chips]]
        ligacoes = []           # (modulo, chip, lambdas)
        for chip in sorted(self.lambdas_tx):
            dem = np.zeros(n_lam, int)
            for lam, q in self.lambdas_tx[chip].items():
                dem[lam] = q
            while dem.sum() > 0:
                parte = np.minimum(dem, cap)
                k_mod = next((k for k, m in enumerate(modulos)
                              if (m[0] >= parte).all() and len(m[1]) < DIVISOR_SAIDAS_MAX), None)
                if k_mod is None:
                    modulos.append([np.full(n_lam, cap), []])
                    k_mod = len(modulos) - 1
                modulos[k_mod][0] -= parte
                modulos[k_mod][1].append(chip)
                ligacoes.append((k_mod, chip, [int(i) for i in np.nonzero(parte)[0]]))
                dem -= parte
        saidas = defaultdict(int)
        for k, (_, chips) in enumerate(modulos):
            lid, did = f"laser:{k}", f"div:{k}"
            pos = self.oc.colocar(ALVO_LASER, LASER_MM[0], LASER_MM[1], lid)
            lams = [round(float(x), 4) for x in self.grade]
            usados = cap - modulos[k][0]                      # canais por λ neste módulo
            linhas = int(np.ceil(usados / int(self.opt["lambdas_por_laser"])).sum())
            p_opt = linhas * float(self.opt["laser_mw"]) * 1e-3
            nl.bloco(lid, "laser", pos, lambdas_nm=lams, potencia_mw=float(self.opt["laser_mw"]),
                     capacidades=["laser"],
                     canais_por_linha=int(self.opt["lambdas_por_laser"]), pentes=PENTES_POR_MODULO,
                     linhas_acesas=linhas,
                     potencia_eletrica_w=round(p_opt / LASER_EFICIENCIA + LASER_TEC_W, 2))
            nl.porta(lid, "out0", "optico", "sai", lambdas_nm=lams)
            nl.porta(lid, "vdd", "energia", "entra", tensao_v=3.3)
            nl.porta(lid, "ctl", "controle", "entra")
            self._alimentar(lid, "vdd", "rail:aux:3V3", nl.blocos[lid].atributos["potencia_eletrica_w"] / 3.3)
            self._ctl_i3c(lid)
            nl.bloco(did, "divisor", pos, saidas=len(chips),
                     perda_db=round(10 * math.log10(max(len(chips), 1)) + 0.5, 2))
            nl.porta(did, "in", "optico", "entra", lambdas_nm=lams)
            nl.ligar((lid, "out0"), (did, "in"), "guia")
        for mod, chip, lams in ligacoes:
            did = f"div:{mod}"
            n = saidas[mod]
            saidas[mod] += 1
            nl.porta(did, f"out{n}", "optico", "sai")
            fid = f"fibl:{mod}:{n}"
            pl, pc = nl.blocos[f"laser:{mod}"].posicao, nl.blocos[chip].posicao
            comp = manhattan(pl, pc) + 20.0
            lam_nm = [round(float(self.grade[i]), 4) for i in lams]
            nl.bloco(fid, "fibra", ((pl[0] + pc[0]) / 2, (pl[1] + pc[1]) / 2), comprimento_mm=round(comp, 1),
                     lambdas_nm=lam_nm, sentido="ida", funcao="laser",
                     perda_db=round(2 * PERDA_CONECTOR_DB + comp * PERDA_FIBRA_DB_MM, 3),
                     de=f"laser:{mod}", para=chip)
            nl.porta(fid, "a", "optico", "entra")
            nl.porta(fid, "b", "optico", "sai")
            nl.ligar((did, f"out{n}"), (fid, "a"), "fibra")
            nl.ligar((fid, "b"), (chip, "laser"), "fibra")
            nl.blocos[chip].portas["laser"].atributos["lambdas_nm"] = sorted(
                set(nl.blocos[chip].portas["laser"].atributos["lambdas_nm"]) | set(lam_nm))
            nl.requisitos.append(Requisito(chip, "laser", f"laser:{mod}"))

    # ---------------------------------------------------------- energia dos chips
    def energia_chips(self):
        nl = self.nl
        tensoes = sorted({nl.blocos[c].atributos["vddio_v"] for cs in self.chips_da_peca.values() for c in cs})
        rail_core = self.reg("tx:0V9", VDD_CHIP_V, (200, 100))
        rail_io = {}
        for v in tensoes:
            rail_io[v] = self.reg(f"tx:io{v:.2f}".replace(".", "V"), v, (205, 112 + 8 * len(rail_io)))
        for chips in self.chips_da_peca.values():
            for chip in chips:
                b = nl.blocos[chip]
                b.atributos["potencia_w"] = round(b.atributos["potencia_w"], 3)
                vias = b.atributos["vias_tx"] + b.atributos["vias_rx"]
                p_io = vias * 0.004            # driver de saída e terminação
                p_core = b.atributos["potencia_w"] - p_io
                self._alimentar(chip, "vdd", rail_core, p_core / VDD_CHIP_V)
                self._alimentar(chip, "vddio", rail_io[b.atributos["vddio_v"]], p_io / b.atributos["vddio_v"])
                nl.requisitos.append(Requisito(chip, "energia", rail_core.replace("rail:", "reg:")))
                nl.requisitos.append(Requisito(chip, "controle", "ctl:fpga"))

    def fechar_reguladores(self):
        """Cada regulador pela carga ligada aos trilhos que ele alimenta, com margem."""
        nl = self.nl
        por_reg = defaultdict(float)
        for rid, corrente in self.carga_trilho.items():
            nl.blocos[rid].atributos["carga_a"] = round(corrente, 3)
            if rid in self.reg_de_trilho:
                por_reg[self.reg_de_trilho[rid]] += corrente
        for rg, corrente in por_reg.items():
            nl.blocos[rg].atributos["corrente_max_a"] = round(corrente * MARGEM_REGULADOR, 3)
            nl.blocos[rg].atributos["carga_a"] = round(corrente, 3)

    # ---------------------------------------------------------------- requisitos
    def requisitos(self):
        R = self.nl.requisitos
        R += [Requisito("CPU", "PCH/DMI", "ctl:fpga"),
              Requisito("CPU", "VR-SVID", "ctl:vrm"),
              Requisito("CPU", "BCLK", "clk:ref"),
              Requisito("CPU", "firmware-UEFI", "flash:uefi"),
              Requisito("CPU", "sequenciamento-PWROK", "ctl:fpga")]
        for nome in self.pecas:
            if nome.startswith("DIMM"):
                tem = all(f"{nome}:{p}" in self.nl.blocos for p in ("HSCL", "HSDA"))
                R.append(Requisito(nome, "SPD/I3C", "ctl:fpga" if tem else None))
        raiz = "CPU:PEG_TX0"
        if raiz in self.nl.blocos:
            self.nl.blocos[raiz].atributos["capacidades"] = ["raiz-PCIe"]
        R += [Requisito("GPU", "raiz-PCIe", raiz if raiz in self.nl.blocos else None),
              Requisito("GPU", "12V-cabo", "fonte:atx")]


class _CanalLento:
    """O mínimo de um canal do roteamento, para sinais que só existem na base."""

    def __init__(self, enlace, sentido, protocolo, papel, grupo):
        self.enlace, self.sentido, self.protocolo, self.papel, self.grupo = \
            enlace, sentido, protocolo, papel, grupo


def construir(montagem, configuracao, plano, cfg_optica, chave=None, posicionamento="ao_lado"):
    """chave: nome em modulos.sistema.celula.CHAVES; posicionamento: "ao_lado" | "sob_peca"."""
    c = _Construtor(montagem, configuracao, plano, cfg_optica, chave, posicionamento)
    c.infraestrutura()
    c.chips()
    c.fibras()
    c.sinais_rapidos()
    c.sinais_lentos()
    c.sideband()
    c.relogios()
    c.laser()
    c.energia_chips()
    c.requisitos()
    c.fechar_reguladores()
    return c.nl
