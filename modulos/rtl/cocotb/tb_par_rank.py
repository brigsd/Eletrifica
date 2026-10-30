"""Testes cocotb do par_rank (detector, seletor, mux de posse, emulador de manutenção)."""
import random

import cocotb

from bancada import BL, FIFO_INICIAL, RL_GPU, WL, Bancada
from modulos.dados import memoria_unificada as MU


def _falhar(erros):
    assert not erros, "\n".join(erros[:20]) + (f"\n... +{len(erros) - 20}" if len(erros) > 20 else "")


def _palavras(rng):
    return [rng.getrandbits(32) for _ in range(BL)]


class Trafego:
    """Controlador da GPU que mantém uma linha aberta por banco (a GPU vê um chip só)."""

    def __init__(self, b, rng):
        self.b, self.rng = b, rng
        self.aberto = {}              # banco -> linha de 17 bits
        self.escrito = {}             # (rank, banco, linha16, coluna) -> dados

    def abrir(self, banco, linha):
        if self.aberto.get(banco) == linha:
            return
        if banco in self.aberto:
            self.b.gpu("PRE", rank=self.aberto[banco] >> 16, banco=banco)
        self.b.gpu("ACT", rank=linha >> 16, banco=banco, linha=linha)
        self.aberto[banco] = linha

    def escrever(self, banco, linha, coluna, dados=None):
        self.abrir(banco, linha)
        dados = dados or _palavras(self.rng)
        self.b.gpu("WR", rank=linha >> 16, banco=banco, coluna=coluna, dados=dados)
        self.escrito[(linha >> 16, banco, linha & 0xFFFF, coluna)] = dados

    def ler(self, banco, linha, coluna, esperado=None):
        self.abrir(banco, linha)
        k = (linha >> 16, banco, linha & 0xFFFF, coluna)
        self.b.gpu("RD", rank=linha >> 16, banco=banco, coluna=coluna,
                   esperado=esperado if esperado is not None else self.escrito.get(k, [0] * BL))

    def fechar_tudo(self):
        for banco, linha in sorted(self.aberto.items()):
            self.b.gpu("PRE", rank=linha >> 16, banco=banco)
        self.aberto.clear()

    def refresh(self):
        self.fechar_tudo()
        self.b.gpu("REF", rank="ambos")


@cocotb.test()
async def trafego_intercalado(dut):
    """ACT/RD/WR/PRE/REF misturados em bancos dos dois ranks: cada comando chega ao chip
    certo, o outro recebe NOP, REF vai aos dois e cada leitura volta em RL_CHIP+RL_EXTRA."""
    rng = random.Random(1)
    b = Bancada(dut)
    g = Trafego(b, rng)
    for i in range(300):
        rank = rng.randrange(2)
        banco = rng.randrange(16)
        linha = rank << 16 | rng.choice((0x0123, 0x4567, 0xBEEF))
        coluna = rng.randrange(1024)
        if rng.random() < 0.5 or not g.escrito:
            g.escrever(banco, linha, coluna)
        else:
            r, bb, l16, col = rng.choice(sorted(g.escrito))
            g.ler(bb, r << 16 | l16, col)
        if i % 60 == 59:
            g.refresh()
    await b.rodar(b.t + RL_GPU + 10)
    _falhar(b.conferir_leituras() + b.conferir_roteamento())
    # os dados ficaram no chip do rank que a linha manda
    for (r, banco, l16, col), dados in g.escrito.items():
        assert b.chips[r].mem.get((banco, l16, col)) == dados
        assert (banco, l16, col) not in b.chips[1 - r].mem or b.chips[1 - r].mem[(banco, l16, col)] != dados
    refs = [sum(1 for _, n, _ in ch.log if n == "REF") for ch in b.chips]
    assert refs == [5, 5], refs


@cocotb.test()
async def troca_de_dono(dut):
    """O FPGA pede o rank 1 para a ponte no meio do tráfego: a troca espera o banco aberto
    no rank 1 fechar, o rank 0 continua servindo a GPU, a ponte grava no chip 1, o REF da
    GPU no rank 1 é absorvido, e na volta a GPU lê o que a ponte gravou."""
    rng = random.Random(2)
    b = Bancada(dut)
    g = Trafego(b, rng)
    g.escrever(3, 1 << 16 | 0x0042, 7)               # banco 3 aberto no rank 1
    t_pedido = b.t
    b.pedidos[t_pedido] = (1, 1)
    for _ in range(40):                              # tráfego no rank 0 enquanto o pedido espera
        g.escrever(rng.randrange(4, 16), 0x0100, rng.randrange(64))
    t_pre = b.t
    b.gpu("PRE", rank=1, banco=3)
    del g.aberto[3]
    for k in range(30):
        banco = 4 + k % 12
        g.ler(banco, g.aberto[banco], next(c for (r, bb, l, c) in g.escrito if bb == banco and r == 0)) \
            if banco in g.aberto and any(bb == banco and r == 0 for (r, bb, l, c) in g.escrito) \
            else g.escrever(banco, 0x0100, k)
    # a ponte escreve no chip 1 depois que ele for dela
    t_ponte = b.t + 50
    dados_cpu = [0xC0FFEE01, 0xC0FFEE02]
    b.ponte(1, t_ponte, "ACT", banco=9, linha=0x0777)
    b.ponte(1, t_ponte + 4, "WR", banco=9, coluna=5, dados=dados_cpu)
    b.ponte(1, t_ponte + 4 + WL + 6, "PRE", banco=9)
    # a GPU manda REF (rank 0 recebe, rank 1 absorvido) e a ponte faz o dela
    b.t = t_ponte + WL + 20
    g.refresh()
    t_ref_ponte = b.t + 4
    b.ponte_ref[t_ref_ponte] = 0b10
    b.ponte(1, t_ref_ponte, "REF")
    # volta para a GPU, que lê o que a CPU gravou
    t_volta = t_ref_ponte + 800
    b.pedidos[t_volta] = (1, 0)
    b.t = t_volta + 10
    g.ler(9, 1 << 16 | 0x0777, 5, esperado=dados_cpu)
    await b.rodar(b.t + RL_GPU + 10)
    _falhar(b.conferir_leituras() + b.chips[0].erros + b.chips[1].erros)
    a = b.amostras
    trocas = [c for c in sorted(a) if a[c]["pronto"]]
    assert len(trocas) == 2, (trocas, t_pre, t_ponte, t_ref_ponte, t_volta, b.t,
                              [(c, a[c]["ocupado"], a[c]["dono"]) for c in range(t_volta - 2, t_volta + 6)])
    assert t_pre < trocas[0] <= t_pre + 4, (t_pre, trocas)       # só depois do PRE do rank 1
    assert all(a[c]["dono"] == 0 for c in range(t_pedido, t_pre)), "trocou com banco aberto"
    assert a[t_ponte]["dono"] == 0b10
    assert b.chips[1].mem[(9, 0x0777, 5)] == dados_cpu
    assert max(a[c]["ref_devido1"] for c in a) == 1 and a[t_volta]["ref_devido1"] == 0
    assert trocas[1] > t_volta
    ref_chip1 = [c for c, n, _ in b.chips[1].log if n == "REF"]
    assert ref_chip1 == [t_ref_ponte + 1], ref_chip1   # só o REF da ponte chegou ao chip 1


@cocotb.test()
async def treino_com_a_cpu(dut):
    """Os dois ranks com a ponte: a GPU retreina o chip que acha que é dela. A base absorve
    o REF (conta o que o chip deve), guarda o MRS, captura o WRTR no WL e devolve o RDTR
    exatamente em RL_CHIP + RL_EXTRA, nem um ciclo antes nem depois. Depois, com o rank 0
    de volta à GPU, quem responde é o chip real."""
    rng = random.Random(3)
    b = Bancada(dut)
    b.pedidos[5] = (0, 1)
    b.pedidos[8] = (1, 1)
    b.t = 20
    for _ in range(3):
        b.gpu("REF", rank=None)
        b.esperar(4)
    b.gpu("MRS", ma=7, op=0x5C)
    padroes = [_palavras(rng) for _ in range(2)]
    for p in padroes:
        b.gpu("WRTR", dados=p)
    b.esperar(WL + 4)
    t_rdtr = [b.gpu("RDTR", esperado=p, folga=2) for p in padroes]
    b.gpu("RDTR", esperado=FIFO_INICIAL[2])           # entrada ainda não escrita
    b.gpu("RD", banco=1, coluna=3)                    # violação: rank da ponte
    b.esperar(RL_GPU + 10)
    # rank 0 volta para a GPU; o chip real responde o treino
    t_volta = b.t
    b.pedidos[t_volta] = (0, 0)
    b.t = t_volta + 10
    p = _palavras(rng)
    b.gpu("WRTR", dados=p)
    b.esperar(WL + 4)
    b.gpu("RDTR", esperado=p)
    await b.rodar(b.t + RL_GPU + 10)
    _falhar(b.conferir_leituras())
    a = b.amostras
    for t in t_rdtr:
        assert not a[t + RL_GPU - 1]["gpu_dq_valido"] and not a[t + RL_GPU + BL]["gpu_dq_valido"]
    assert a[t_volta]["ref_devido0"] == 3 and a[t_volta]["ref_devido1"] == 3
    assert a[t_volta]["mrs_pendente"] == 0b11
    assert a[t_volta]["violacoes"] == 1
    assert not any(n in ("REF", "MRS", "WRTR", "RDTR") for c, n, _ in b.chips[0].log if c < t_volta)
    assert not b.chips[1].log
    assert [n for _, n, _ in b.chips[0].log] == ["WRTR", "RDTR"]


@cocotb.test()
async def cruzado_com_python(dut):
    """Mesmas entradas, mesmo resultado: o banco de memoria_unificada (mapa da GPU
    aleatório) grava; o RTL, alimentado com os comandos que a GPU geraria para cada
    endereço, devolve o que Banco.gpu_ler devolve, do chip que o Python escolheu."""
    rng = random.Random(4)
    banco = MU.Banco(MU.mapa_gpu_aleatorio(rng), MU.mapa_cpu_aleatorio(rng))
    total = int(MU.CANAIS_GPU * MU.CHIP_REAL_GB * 2**30 * 2)
    canal, enderecos = None, []
    while len(enderecos) < 200:
        o = rng.randrange(0, total, 8)
        loc = banco.gpu.local(o)
        canal = loc.canal if canal is None else canal
        if loc.canal == canal:
            enderecos.append(o)
            banco.gpu_gravar(o - o % MU.CHUNK_GPU_B, bytes(rng.getrandbits(8) for _ in range(MU.CHUNK_GPU_B)))
    b = Bancada(dut)
    # os chips do canal recebem o conteúdo que o Python guardou
    for (cn, rank, bn, l16, col), dados in banco.dados.items():
        if cn != canal:
            continue
        for k in range(MU.CHUNK_GPU_B // 8):
            b.chips[rank].mem[(bn, l16, col << 5 | k)] = [int.from_bytes(dados[8 * k + 4 * j:8 * k + 4 * j + 4],
                                                                         "little") for j in range(BL)]
    g = Trafego(b, rng)
    ranks = []
    for o in enderecos:
        loc = banco.gpu.local(o)
        esp = banco.gpu_ler(o, 8)
        ranks.append(loc.rank)
        g.ler(loc.banco, loc.linha, loc.coluna << 5 | loc.byte // 8,
              esperado=[int.from_bytes(esp[4 * j:4 * j + 4], "little") for j in range(BL)])
    await b.rodar(b.t + RL_GPU + 10)
    _falhar(b.conferir_leituras() + b.conferir_roteamento())
    assert 0 in ranks and 1 in ranks
