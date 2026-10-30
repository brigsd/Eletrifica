"""Síntese dos blocos do RTL com Yosys: área e profundidade lógica, e a latência que sai delas.

Dois alvos:
- genérico (ASIC): `synth` + `abc` para portas de 2 entradas e MUX. A profundidade é o
  maior número de portas entre dois registros (ou entre a entrada e um registro), pelo
  `ltp -noff`. Latência = níveis x ATRASO_PORTA_PS (+ o registro, quando há um).
- FPGA Lattice ECP5 (`synth_ecp5 -noccu2 -nowidelut`: só LUT4, para cada nível ser uma
  LUT); níveis x ATRASO_LUT_PS.
  Mostra que o mesmo RTL cabe e fecha tempo num FPGA de protótipo.

Os atrasos por nível são estimativas documentadas (não há biblioteca de células nem
place-and-route aqui); o que a síntese mede de fato é a contagem de células e de níveis.

    python3 -m modulos.rtl.sintese
"""
import json
import re
import shutil
import subprocess

from modulos.caminhos import BUILD
from modulos.dados import comandos as K
from modulos.rtl.sim import HDL

from modulos.rtl.medidas import ATRASO_LUT_PS, ATRASO_PORTA_PS, REGISTRO_FPGA_PS, REGISTRO_PS

TCK_PS = K.TCK_GDDR7_NS * 1000

PAR = ["decod_ca.v", "detector_rank.v", "seletor_rank.v", "mux_posse.v", "emulador_manutencao.v", "par_rank.v"]
BLOCOS = {                 # bloco -> (arquivos, o que o bloco é)
    "detector_rank": (PAR[:2], "decodifica ACT/banco e decide o rank"),
    "seletor_rank": (PAR, "CA ao chip escolhido, NOP ao outro; mux de leitura do DQ"),
    "mux_posse": (PAR, "dono por rank, troca só com o chip parado"),
    "emulador_manutencao": (PAR, "absorve REF/MRS e responde WRTR/RDTR no RL"),
    "par_rank": (PAR, "o tradutor do rank 0 inteiro"),
    "ponte_mapa": (["ponte_mapa.v"], "mapa aprendido DDR5 -> GDDR7 (GF(2) e resto por 3)"),
}


def disponivel():
    return None if shutil.which("yosys") else "yosys não instalado (sudo apt-get install -y yosys)"


def _yosys(script):
    r = subprocess.run(["yosys", "-q", "-p", script], cwd=HDL, capture_output=True, text=True, check=True)
    return r.stdout


def _ler(saida):
    celulas = {}
    for nome, n in re.findall(r"^\s+(\S+)\s+(\d+)\s*$", saida, re.M):
        if not nome.startswith("Number"):
            celulas[nome] = celulas.get(nome, 0) + int(n)
    total = int(re.findall(r"Number of cells:\s+(\d+)", saida)[-1])
    niveis = int(re.findall(r"Longest topological path in \S+ \(length=(\d+)\)", saida)[-1])
    return {"celulas": total, "tipos": celulas, "niveis": niveis}


def sintetizar(bloco):
    arquivos, _ = BLOCOS[bloco]
    ler = f"read_verilog -I. {' '.join(arquivos)}; "
    gen = _ler(_yosys(ler + f"synth -flatten -top {bloco}; "
                      "abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT,MUX; opt_clean; "
                      "tee -o /dev/stdout stat; tee -o /dev/stdout ltp -noff"))
    fpga = _ler(_yosys(ler + f"synth_ecp5 -noccu2 -nowidelut -top {bloco}; tee -o /dev/stdout stat; "
                       "delete t:TRELLIS_FF t:TRELLIS_DPR16X4 t:DP16KD; tee -o /dev/stdout ltp -noff"))
    ffs = sum(n for t, n in gen["tipos"].items() if "DFF" in t.upper())
    out = {
        "bloco": bloco, "papel": BLOCOS[bloco][1],
        "asic": {"celulas": gen["celulas"], "registros": ffs, "portas": gen["celulas"] - ffs,
                 "niveis": gen["niveis"], "caminho_ps": gen["niveis"] * ATRASO_PORTA_PS},
        "ecp5": {"lut4": fpga["tipos"].get("LUT4", 0), "ff": fpga["tipos"].get("TRELLIS_FF", 0),
                 "carry": fpga["tipos"].get("CCU2C", 0), "niveis": fpga["niveis"],
                 "caminho_ps": fpga["niveis"] * ATRASO_LUT_PS},
    }
    out["asic"]["fecha_no_tck"] = out["asic"]["caminho_ps"] + REGISTRO_PS <= TCK_PS
    out["ecp5"]["fmax_mhz"] = 1e6 / (out["ecp5"]["caminho_ps"] + REGISTRO_FPGA_PS)
    return out


def sintetizar_tudo():
    from modulos.rtl import gerar
    gerar.gerar()
    r = {b: sintetizar(b) for b in BLOCOS}
    destino = BUILD / "rtl"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "sintese.json").write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    return r


if __name__ == "__main__":
    falta = disponivel()
    if falta:
        raise SystemExit(falta)
    for b, x in sintetizar_tudo().items():
        print(f"{b:22s} ASIC {x['asic']['portas']:6d} portas {x['asic']['registros']:5d} FF "
              f"{x['asic']['niveis']:3d} níveis {x['asic']['caminho_ps']:6.0f} ps | ECP5 {x['ecp5']['lut4']:5d} LUT4 "
              f"{x['ecp5']['ff']:5d} FF {x['ecp5']['niveis']:3d} níveis {x['ecp5']['fmax_mhz']:5.0f} MHz")
