"""Roda os testes cocotb do RTL no Verilator.

    python3 -m modulos.rtl.sim              # todos
    python3 -m modulos.rtl.sim par_rank     # um banco de testes

Os testes ficam em modulos/rtl/cocotb/ e rodam ciclo a ciclo com o CK de comando da
GDDR7 (comandos.TCK_GDDR7_NS). Construção em build/rtl/.
"""
import os
import shutil
import sys
from pathlib import Path

from modulos.caminhos import BUILD, RAIZ
from modulos.rtl import gerar

HDL = Path(__file__).parent / "hdl"
BANCADA = {
    "par_rank": ["decod_ca.v", "detector_rank.v", "seletor_rank.v", "mux_posse.v",
                 "emulador_manutencao.v", "par_rank.v"],
    "ponte_mapa": ["ponte_mapa.v"],
}


def disponivel():
    """None se dá para simular; senão, o que falta."""
    if shutil.which("verilator") is None:
        return "verilator não instalado (sudo apt-get install -y verilator)"
    try:
        import cocotb
    except ImportError:
        return "cocotb não instalado (python3 -m pip install -r requirements.txt)"
    if not cocotb.__version__.startswith("1."):
        # o cocotb 2 exige Verilator >= 5.036; o do Ubuntu 24.04 é o 5.020
        return f"cocotb {cocotb.__version__}: use o 1.9 (requirements.txt) com o Verilator do apt"
    return None


def rodar(top, testcase=None):
    """Constrói e roda; devolve (testes, falhas)."""
    import warnings

    warnings.filterwarnings("ignore", message="Python runners")
    from cocotb.runner import get_results, get_runner

    gerar.gerar()
    destino = BUILD / "rtl" / top
    r = get_runner("verilator")
    r.build(sources=[HDL / f for f in BANCADA[top]], includes=[HDL], hdl_toplevel=top,
            build_dir=destino, build_args=["-Wno-fatal", "-Wno-WIDTH", "--timescale-override", "1ps/1fs"],
            timescale=("1ps", "1fs"), always=True)
    caminho = [str(RAIZ), str(Path(__file__).parent / "cocotb")]
    for p in caminho:                  # o runner passa o sys.path ao simulador
        if p not in sys.path:
            sys.path.insert(0, p)
    env = {}
    xml = r.test(test_module=f"tb_{top}", hdl_toplevel=top, build_dir=destino, test_dir=destino,
                 testcase=testcase, extra_env=env, timescale=("1ps", "1fs"))
    return get_results(xml)


if __name__ == "__main__":
    falta = disponivel()
    if falta:
        sys.exit(falta)
    for top in sys.argv[1:] or BANCADA:
        print(top, rodar(top))
