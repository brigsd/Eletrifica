"""RTL do banco unificado: testes cocotb no Verilator (modulos/rtl/cocotb) e síntese no Yosys."""
import shutil

import pytest

from modulos.rtl import gerar, sim


def test_comandos_vh_bate_com_a_tabela():
    """O .vh versionado é o que a tabela de comandos.py gera."""
    assert (gerar.HDL / "comandos.vh").read_text(encoding="utf-8") == gerar.texto()


def _exigir_simulador():
    falta = sim.disponivel()
    if falta:
        pytest.skip(f"RTL não simulado: {falta}")


@pytest.mark.lento
@pytest.mark.parametrize("top", sorted(sim.BANCADA))
def test_cocotb(top):
    """Cada banco de testes cocotb roda inteiro e passa (ver modulos/rtl/cocotb/tb_*.py)."""
    _exigir_simulador()
    testes, falhas = sim.rodar(top)
    assert testes > 0 and falhas == 0, f"{top}: {falhas} de {testes} testes falharam (build/rtl/{top})"
