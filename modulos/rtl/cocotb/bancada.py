"""Bancada ciclo a ciclo do par_rank: controlador GPU, dois chips GDDR7 e a ponte.

Convenção de tempo: tudo é lido e dirigido na borda de descida. O ciclo c é o intervalo
entre a borda de subida c e a c+1; o que a bancada põe no barramento na descida do ciclo
c é amostrado pelo RTL na subida seguinte. Modelos dos chips em Python, com a mesma
tabela de comandos (modulos.dados.comandos) que gerou o comandos.vh.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

from modulos.dados import comandos as K
from modulos.dados import memoria_unificada as MU

P = "GDDR7-32"
COD = {t.nome: t.codigo for t in K.TABELA[P]}
NOME = {t.codigo: t.nome for t in K.TABELA[P]}
DOIS = {t.codigo for t in K.TABELA[P] if t.ciclos == 2}
RL_CHIP = round(K.LATENCIAS[P]["CL_ns"] / K.TCK_GDDR7_NS)
WL = round(K.LATENCIAS[P]["CWL_ns"] / K.TCK_GDDR7_NS)
RL_GPU = RL_CHIP + MU.RL_EXTRA_TCK
BL, W = 2, 32
NOP = COD["NOP"]
TCK_FS = 2 * round(K.TCK_GDDR7_NS * 1e6 / 2)   # CK de comando da GDDR7, par para a meia onda
FIFO_INICIAL = [[0xA55A0000 | i] * BL for i in range(4)]


def cmd(nome, **kw):
    return K.codificar(P, nome, **kw)


class Chip:
    """Um chip GDDR7 real de 16 Gb: bancos com linha aberta, leitura em RL, escrita em WL,
    FIFO de treino (WRTR/RDTR) de 4 entradas."""

    def __init__(self, nome):
        self.nome, self.mem, self.aberto = nome, {}, {}
        self.seg = None
        self.saida, self.capt = {}, {}
        self.fifo = [list(x) for x in FIFO_INICIAL]
        self.wptr = self.rptr = 0
        self.log = []              # (ciclo do primeiro word, nome, banco)
        self.erros = []

    def ciclo(self, c, ca, dq_w):
        if c in self.capt:
            onde, k, j = self.capt.pop(c)
            if onde == "mem":
                self.mem.setdefault(k, [0] * BL)[j] = dq_w
            else:
                self.fifo[k][j] = dq_w
        if self.seg is not None:
            w0, self.seg = self.seg, None
            self._cmd(c - 1, w0, ca)
        elif (ca & 0x1F) in DOIS:
            self.seg = ca
        else:
            self._cmd(c, ca, 0)
        s = self.saida.pop(c, None)          # o dado é lido na hora em que sai
        if s is None:
            return 0
        onde, k, j = s
        return self.mem.get(k, [0] * BL)[j] if onde == "mem" else self.fifo[k][j]

    def _cmd(self, c0, w0, w1):
        cod, banco = w0 & 0x1F, (w0 >> 5) & 0x1F
        nome = NOME.get(cod, "?")
        if nome == "NOP":
            return
        self.log.append((c0, nome, banco))
        if nome == "ACT":
            if banco in self.aberto:
                self.erros.append(f"{self.nome} c{c0}: ACT em banco {banco} aberto")
            self.aberto[banco] = (((w0 >> 10) & 7) << 14 | (w1 & 0x3FFF)) & 0xFFFF
        elif nome in ("RD", "WR"):
            if banco not in self.aberto:
                self.erros.append(f"{self.nome} c{c0}: {nome} em banco {banco} fechado")
                return
            k = (banco, self.aberto[banco], w1 & 0x3FF)
            for j in range(BL):
                if nome == "RD":
                    self.saida[c0 + RL_CHIP + j] = ("mem", k, j)
                else:
                    self.capt[c0 + WL + j] = ("mem", k, j)
        elif nome == "PRE":
            self.aberto.pop(banco, None)
        elif nome == "REF":
            if self.aberto:
                self.erros.append(f"{self.nome} c{c0}: REF com bancos abertos {sorted(self.aberto)}")
        elif nome == "WRTR":
            for j in range(BL):
                self.capt[c0 + WL + j] = ("fifo", self.wptr, j)
            self.wptr = (self.wptr + 1) % 4
        elif nome == "RDTR":
            for j in range(BL):
                self.saida[c0 + RL_CHIP + j] = ("fifo", self.rptr, j)
            self.rptr = (self.rptr + 1) % 4


class Bancada:
    def __init__(self, dut):
        self.dut = dut
        self.chips = [Chip("chip0"), Chip("chip1")]
        self.c = 0
        self.t = 10                    # próximo ciclo livre do controlador da GPU
        self.ca, self.dqw = {}, {}
        self.ponte_ca = [{}, {}]
        self.ponte_dq = [{}, {}]
        self.ponte_ref = {}
        self.pedidos = {}
        self.esperado = {}             # ciclo -> palavra que a GPU tem de receber
        self.recebido = {}             # ciclo -> (valido, palavra)
        self.amostras = {}             # ciclo -> dict de saídas do RTL
        self.enviados = []             # (ciclo, nome, banco, rank esperado ou None)

    # ---- controlador da GPU
    def gpu(self, nome, rank=None, dados=None, esperado=None, folga=1, **kw):
        ws = cmd(nome, **kw)
        t0 = self.t
        for i, w in enumerate(ws):
            self.ca[t0 + i] = w
        if nome in ("WR", "WRTR"):
            for j in range(BL):
                self.dqw[t0 + WL + j] = dados[j]
        if esperado is not None:
            for j in range(BL):
                self.esperado[t0 + RL_GPU + j] = esperado[j]
        self.enviados.append((t0, nome, kw.get("banco", 0), rank))
        self.t = t0 + max(len(ws), BL) + folga - 1
        return t0

    def esperar(self, n):
        self.t += n

    # ---- ponte
    def ponte(self, r, t0, nome, dados=None, **kw):
        for i, w in enumerate(cmd(nome, **kw)):
            self.ponte_ca[r][t0 + i] = w
        if nome == "WR":
            for j in range(BL):
                self.ponte_dq[r][t0 + WL + j] = dados[j]

    async def rodar(self, ate):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, TCK_FS, units="fs").start())
        for s in ("gpu_ca", "ponte_ca0", "ponte_ca1"):
            getattr(d, s).value = NOP
        for s in ("gpu_dq_w", "ponte_dq0", "ponte_dq1", "ponte_ref", "mrs_restaurado", "pedido",
                  "pedido_rank", "pedido_dono", "chip_dq_r0", "chip_dq_r1"):
            getattr(d, s).value = 0
        d.rst.value = 1
        for _ in range(3):
            await RisingEdge(d.clk)
        d.rst.value = 0
        while self.c < ate:
            await FallingEdge(d.clk)
            self.c += 1
            c = self.c
            amostra = {n: int(getattr(d, n).value) for n in
                       ("chip_ca0", "chip_ca1", "chip_dq_w0", "chip_dq_w1", "gpu_dq_r", "gpu_dq_valido",
                        "dono", "pronto", "ocupado", "ref_devido0", "ref_devido1", "mrs_pendente",
                        "violacoes")}
            self.amostras[c] = amostra
            for r in range(2):
                out = self.chips[r].ciclo(c, amostra[f"chip_ca{r}"], amostra[f"chip_dq_w{r}"])
                getattr(d, f"chip_dq_r{r}").value = out
            self.recebido[c] = (amostra["gpu_dq_valido"], amostra["gpu_dq_r"])
            d.gpu_ca.value = self.ca.get(c, NOP)
            d.gpu_dq_w.value = self.dqw.get(c, 0)
            for r in range(2):
                getattr(d, f"ponte_ca{r}").value = self.ponte_ca[r].get(c, NOP)
                getattr(d, f"ponte_dq{r}").value = self.ponte_dq[r].get(c, 0)
            d.ponte_ref.value = self.ponte_ref.get(c, 0)
            p = self.pedidos.get(c)
            d.pedido.value = 1 if p else 0
            if p:
                d.pedido_rank.value, d.pedido_dono.value = p

    # ---- conferências
    def conferir_leituras(self):
        """Cada leitura chega exatamente no ciclo esperado e só nele."""
        erros = []
        for c, v in sorted(self.esperado.items()):
            val, w = self.recebido.get(c, (0, 0))
            if not val or w != v:
                erros.append(f"c{c}: esperado {v:#010x}, veio valido={val} {w:#010x}")
        extras = [c for c, (val, _) in self.recebido.items() if val and c not in self.esperado]
        if extras:
            erros.append(f"dado fora de hora nos ciclos {extras[:8]}")
        return erros

    def conferir_roteamento(self):
        """Cada comando chegou ao chip do rank certo, e só a ele (os de difusão, aos dois)."""
        erros = []
        logs = [{(c, n, b) for c, n, b in ch.log} for ch in self.chips]
        for t0, nome, banco, rank in self.enviados:
            if rank is None:
                continue
            alvo = (t0 + 1, nome, banco)
            for r in range(2):
                quer = rank == "ambos" or rank == r
                if (alvo in logs[r]) != quer:
                    erros.append(f"{nome} b{banco} c{t0}: chip{r} {'não ' if quer else ''}recebeu")
        for ch in self.chips:
            erros += ch.erros
        return erros
