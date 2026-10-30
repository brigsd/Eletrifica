"""Gera hdl/comandos.vh a partir da tabela de modulos.dados.comandos.

O RTL e o modelo Python usam os mesmos códigos: o .vh é artefato, não se edita à mão.

    python3 -m modulos.rtl.gerar
"""
from pathlib import Path

from modulos.dados import comandos as K
from modulos.dados import memoria_unificada as MU

HDL = Path(__file__).parent / "hdl"
PROTOCOLO = "GDDR7-32"


def ciclos(ns):
    return round(ns / K.TCK_GDDR7_NS)


def texto():
    L = K.LATENCIAS[PROTOCOLO]
    linhas = ["// GERADO por python3 -m modulos.rtl.gerar a partir de modulos/dados/comandos.py.",
              "// Não edite: mude a tabela em Python e gere de novo.",
              f"// Codificação de comando da {PROTOCOLO}, 14 bits de CA por ciclo de CK.",
              "localparam CA_W = 14;"]
    for t in K.TABELA[PROTOCOLO]:
        linhas.append(f"localparam [4:0] CMD_{t.nome} = 5'b{t.codigo:05b};   // {t.ciclos} ciclo(s)")
    dois = " || ".join(f"c == CMD_{t.nome}" for t in K.TABELA[PROTOCOLO] if t.ciclos == 2)
    linhas += [f"localparam integer RL_CHIP = {ciclos(L['CL_ns'])};      // CK: CL de {L['CL_ns']} ns",
               f"localparam integer WL_CHIP = {ciclos(L['CWL_ns'])};      // CK: CWL de {L['CWL_ns']} ns",
               f"localparam integer RL_EXTRA = {MU.RL_EXTRA_TCK};      // CK a mais que o chip emulado declara",
               "function dois_ciclos(input [4:0] c);",
               f"    dois_ciclos = {dois};",
               "endfunction"]
    return "\n".join(linhas) + "\n"


def gerar():
    (HDL / "comandos.vh").write_text(texto(), encoding="utf-8")


if __name__ == "__main__":
    gerar()
    print(HDL / "comandos.vh")
