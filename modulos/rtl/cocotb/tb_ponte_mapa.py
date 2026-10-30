"""Testes cocotb do núcleo da ponte: mapa aprendido (GF(2) e resto por 3) contra o Python."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

from modulos.dados import memoria_unificada as MU

TCK_DDR5_FS = 2 * round(1e6 / 2.4 / 2)     # a ponte roda no relógio do DDR5-4800


async def _carregar(d, qual, linhas):
    for k, v in enumerate(linhas):
        d.carga.value, d.carga_qual.value, d.carga_idx.value, d.carga_dado.value = 1, qual, k, v
        await FallingEdge(d.clk)
    d.carga.value = 0


@cocotb.test()
async def mapa_igual_ao_python(dut):
    """O FPGA carrega os mapas que a calibração aprendeu; para 2000 linhas de cache da CPU,
    o RTL leva os campos DDR5 dos pinos ao mesmo local GDDR7 que Banco._ponte_local."""
    rng = random.Random(7)
    banco = MU.Banco(MU.mapa_gpu_aleatorio(rng), MU.mapa_cpu_aleatorio(rng))
    cal = MU.calibrar(banco, rng)
    assert cal["rank_contiguo"]
    cocotb.start_soon(Clock(dut.clk, TCK_DDR5_FS, units="fs").start())
    await FallingEdge(dut.clk)
    await _carregar(dut, 0, MU._inversa(banco.aprendido_cpu.linhas, MU.BITS_L))
    await _carregar(dut, 1, banco.aprendido_gpu.linhas)
    await _carregar(dut, 2, banco.aprendido_gpu.grupos)
    linhas_janela = int(MU.CANAIS_GPU * MU.RANKS * MU.CHIP_REAL_GB * 2**30) // MU.LINHA_CPU_B
    erros = 0
    for _ in range(2000):
        linha = rng.randrange(linhas_janela)
        v = banco.cpu.campos(linha * MU.LINHA_CPU_B)           # o que o controlador põe nos pinos
        for nome in ("sub", "coluna", "banco", "rank", "linha"):
            getattr(dut, nome).value = v[nome]
        await FallingEdge(dut.clk)
        loc = banco._ponte_local(linha)
        rtl = tuple(int(getattr(dut, n).value) for n in ("g_canal", "g_banco", "g_linha", "g_coluna", "g_byte"))
        if rtl != (loc.canal, loc.banco, loc.linha, loc.coluna, loc.byte):
            erros += 1
            dut._log.error(f"linha {linha}: RTL {rtl} Python {loc}")
    assert erros == 0
