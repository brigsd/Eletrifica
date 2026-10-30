"""Gera projetos/interconexao-optica/docs/rtl.md: o que o RTL provou e o que a síntese mediu.

    python3 -m modulos.rtl.relatorio      # ~2 min: testes cocotb no Verilator + Yosys
"""
import ast
import xml.etree.ElementTree as ET
from pathlib import Path

from modulos.caminhos import BUILD, PROJETOS
from modulos.dados import comandos as K
from modulos.dados import memoria_unificada as MU
from modulos.conexoes import construir as C
from modulos.rtl import medidas as M
from modulos.rtl import sim, sintese

SAIDA = PROJETOS / "interconexao-optica" / "docs" / "rtl.md"
COCOTB = Path(__file__).parent / "cocotb"
# o que o modelo declarava antes de haver RTL (commit a17e30d)
DECLARADO = {"LATENCIA_RANK_PS": 200.0, "SELETOR_CA_PS": 250.0, "SELETOR_DQ_PS": 50.0,
             "RL_EXTRA_TCK": 2, "PONTE_LOGICA_NS": 2.0}


def _docstrings(top):
    arv = ast.parse((COCOTB / f"tb_{top}.py").read_text(encoding="utf-8"))
    return {f.name: " ".join((ast.get_docstring(f) or "").split()) for f in arv.body
            if isinstance(f, ast.AsyncFunctionDef)}


def _resultados(top):
    raiz = ET.parse(BUILD / "rtl" / top / "results.xml").getroot()
    return {tc.get("name"): tc.find("failure") is None for tc in raiz.iter("testcase")}


def gerar():
    testes = {}
    for top in sim.BANCADA:
        sim.rodar(top)
        doc = _docstrings(top)
        testes.update({(top, n): (ok, doc.get(n, "")) for n, ok in _resultados(top).items()})
    s = sintese.sintetizar_tudo()
    rl_chip = round(K.LATENCIAS["GDDR7-32"]["CL_ns"] / K.TCK_GDDR7_NS)
    wl = round(K.LATENCIAS["GDDR7-32"]["CWL_ns"] / K.TCK_GDDR7_NS)
    L = []
    w = L.append
    w("# RTL do banco unificado")
    w("")
    w("Gerado por `python3 -m modulos.rtl.relatorio`. Não edite à mão.")
    w("")
    w("Os blocos que o tradutor do rank 0 de cada par de chips GDDR7 e a ponte precisam, "
      "escritos em Verilog sintetizável (`modulos/rtl/hdl/`), testados ciclo a ciclo no "
      "Verilator com cocotb e sintetizados no Yosys. A codificação de comando é a de "
      "`modulos/dados/comandos.py` (`hdl/comandos.vh` é gerado dela).")
    w("")
    w(f"Relógio dos testes: CK de comando da GDDR7, {K.TCK_GDDR7_NS * 1000:.1f} ps. "
      f"RL do chip {rl_chip} CK, WL {wl} CK; o chip emulado declara à GPU RL de "
      f"{rl_chip + MU.RL_EXTRA_TCK} CK.")
    w("")
    w("## O que os testes provam")
    w("")
    w("| Bancada | Teste | Resultado | O que confere |")
    w("|---|---|---|---|")
    for (top, nome), (ok, doc) in testes.items():
        w(f"| `{top}` | `{nome}` | {'passa' if ok else '**falha**'} | {doc} |")
    w("")
    w(f"{sum(ok for ok, _ in testes.values())} de {len(testes)} testes passam.")
    w("")
    w("## Síntese")
    w("")
    w(f"Genérico (ASIC): `synth` + `abc` em portas de 2 entradas; atraso estimado de "
      f"{M.ATRASO_PORTA_PS:.0f} ps por nível e {M.REGISTRO_PS:.0f} ps de registro (nó de 16/12 nm). "
      f"ECP5: `synth_ecp5` só com LUT4; {M.ATRASO_LUT_PS:.0f} ps por nível e "
      f"{M.REGISTRO_FPGA_PS:.0f} ps de registro. A síntese mede células e níveis; os ps são estimativa.")
    w("")
    w("| Bloco | Papel | Portas | FF | Níveis | Caminho | Fecha em 1 CK GDDR7 | LUT4 ECP5 | Níveis ECP5 | fmax ECP5 |")
    w("|---|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for b, x in s.items():
        a, f = x["asic"], x["ecp5"]
        w(f"| `{b}` | {x['papel']} | {a['portas']} | {a['registros']} | {a['niveis']} | "
          f"{a['caminho_ps']:.0f} ps | {'sim' if a['fecha_no_tck'] else 'não'} | {f['lut4']} | "
          f"{f['niveis']} | {f['fmax_mhz']:.0f} MHz |")
    w("")
    w("A `ponte_mapa` roda no relógio do DDR5 (417 ps): o caminho de "
      f"{s['ponte_mapa']['asic']['caminho_ps']:.0f} ps pede {M.PONTE_MAPA_ESTAGIOS} estágios. "
      "No ECP5 nada roda a 2,667 GHz: um protótipo em FPGA desserializa o CA e roda a lógica a uma "
      "fração do CK. " + "; ".join(
          f"a 1:{k} ({1e6 / (K.TCK_GDDR7_NS * 1000) / k:.0f} MHz) fecham "
          + (", ".join(f"`{b}`" for b, x in s.items() if b != "ponte_mapa"
                       and x["ecp5"]["fmax_mhz"] >= 1e6 / (K.TCK_GDDR7_NS * 1000) / k) or "nenhum")
          for k in (8, 16)) + " (estimativa sem place-and-route).")
    w("")
    w("## Declarado contra medido")
    w("")
    med = {"LATENCIA_RANK_PS": C.LATENCIA_RANK_PS, "SELETOR_CA_PS": MU.SELETOR_CA_PS,
           "SELETOR_DQ_PS": MU.SELETOR_DQ_PS, "RL_EXTRA_TCK": MU.RL_EXTRA_TCK, "PONTE_LOGICA_NS": MU.PONTE_LOGICA_NS}
    como = {"LATENCIA_RANK_PS": f"{M.NIVEIS['detector_rank']} níveis x {M.ATRASO_PORTA_PS:.0f} ps",
            "SELETOR_CA_PS": "1 registro (1 CK)", "SELETOR_DQ_PS": "1 registro (1 CK): o mux de leitura é registrado",
            "RL_EXTRA_TCK": "os 2 registros; a leitura volta exatamente em RL+2 (cocotb)",
            "PONTE_LOGICA_NS": f"mapa {M.PONTE_MAPA_NS:.2f} ns ({M.PONTE_MAPA_ESTAGIOS} CK DDR5) "
                               f"+ fila {MU.PONTE_FILA_NS:.2f} ns (declarada, fora do RTL)"}
    w("| Constante | Declarado | Agora | De onde |")
    w("|---|---:|---:|---|")
    for k, v in DECLARADO.items():
        w(f"| `{k}` | {v:g} | {med[k]:.4g} | {como[k]} |")
    w("")
    w("A netlist liga um `emulador_manutencao` a cada detector de rank, com o arquivo RTL e o "
      "caminho medido; a R20 confere que ele existe, trata REF, WRTR e RDTR, responde no RL "
      "declarado e cabe num CK.")
    w("")
    w("## Simplificações")
    w("")
    for t in (
        "Codificação de comando no estilo do JESD239, não a tabela bit a bit (a mesma de `comandos.py`). "
        "O ACT leva os 3 bits altos da linha no primeiro ciclo, para o rank sair dele.",
        "DQ abstrato: 32 bits por CK, burst de 2 CK. Sem PAM3, WCK nem CRC.",
        "Treino periódico: só a FIFO de leitura (WRTR escreve, RDTR lê de volta), 4 entradas, "
        "padrão inicial fixo. Sem os padrões LFSR, sem WCK2CK, sem treino de VREF e de CA. "
        "O RDTR vai aos chips da GPU; o emulador responde quando nenhum chip do par é dela.",
        "REF absorvido vira dívida (até 15) que a ponte paga no chip; o MRS fica numa sombra de "
        "16 registradores para a ponte reaplicar ao devolver o rank. A ponte em si não está no RTL.",
        "Temporização da DRAM (tRCD, tRP, tRFC exatos) não é conferida pelos modelos de chip; "
        "o mux de posse espera tRFC = 747 CK depois de um REF.",
        "Atrasos por nível são estimativa de processo; não há biblioteca de células nem place-and-route.",
        "A `ponte_mapa` tem hoje um registro só; os 2 estágios supõem retemporização ideal.",
    ):
        w(f"- {t}")
    w("")
    w("## Rodar")
    w("")
    w("```bash")
    w("sudo apt-get install -y verilator yosys   # Verilator 5.020 do Ubuntu 24.04")
    w("python3 -m pip install -r requirements.txt  # cocotb 1.9")
    w("python3 -m modulos.rtl.sim                # testes cocotb")
    w("python3 -m modulos.rtl.sintese            # Yosys")
    w("python3 -m modulos.rtl.relatorio          # este arquivo")
    w("```")
    SAIDA.write_text("\n".join(L) + "\n", encoding="utf-8")
    return SAIDA


if __name__ == "__main__":
    for falta in (sim.disponivel(), sintese.disponivel()):
        if falta:
            raise SystemExit(falta)
    print(gerar())
