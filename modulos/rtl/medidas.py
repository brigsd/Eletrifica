"""O que o RTL mediu, e as latências que o modelo usa a partir disso.

Os níveis lógicos vêm de `python3 -m modulos.rtl.sintese` (Yosys, alvo genérico);
tests/test_rtl.py confere que a síntese de agora dá os mesmos números. O número de
registros no caminho vem do próprio RTL e é provado ciclo a ciclo pelos testes cocotb
(a leitura volta exatamente em RL_CHIP + RL_EXTRA). Os atrasos por nível são
estimativas de processo, documentadas em docs/rtl.md.
"""
import math

# --- atrasos por nível (estimativas de processo) -----------------------------------
ATRASO_PORTA_PS = 25.0     # porta de 2 entradas com fio local num nó de 16/12 nm (FO4 ~ 12 ps)
REGISTRO_PS = 60.0         # clk->q + setup de um flip-flop no mesmo nó
ATRASO_LUT_PS = 600.0      # ECP5 grau 8: LUT4 ~0,25 ns + roteamento local ~0,35 ns
REGISTRO_FPGA_PS = 500.0

TCK_GDDR7_PS = 1000 / 2.667
TCK_DDR5_PS = 1000 / 2.4

# --- medido (níveis de porta no caminho mais longo entre registros) -------------------
NIVEIS = {"detector_rank": 11, "seletor_rank": 7, "mux_posse": 12, "emulador_manutencao": 11,
          "par_rank": 12, "ponte_mapa": 26}
REGISTROS_SELETOR_CA = 1   # o comando cruza o seletor num registro (CA ao chip, NOP ao outro)
REGISTROS_SELETOR_DQ = 1   # a leitura cruza o mux de DQ num registro

# --- latências que o modelo usa ---------------------------------------------------------
DETECTOR_RANK_PS = NIVEIS["detector_rank"] * ATRASO_PORTA_PS          # do 1º ciclo ao rank decidido
SELETOR_CA_PS = REGISTROS_SELETOR_CA * TCK_GDDR7_PS
SELETOR_DQ_PS = REGISTROS_SELETOR_DQ * TCK_GDDR7_PS
RL_EXTRA_TCK = REGISTROS_SELETOR_CA + REGISTROS_SELETOR_DQ
EMULADOR_PS = NIVEIS["emulador_manutencao"] * ATRASO_PORTA_PS        # caminho entre registros
PAR_RANK_PS = NIVEIS["par_rank"] * ATRASO_PORTA_PS
PONTE_MAPA_ESTAGIOS = math.ceil((NIVEIS["ponte_mapa"] * ATRASO_PORTA_PS + REGISTRO_PS) / TCK_DDR5_PS)
PONTE_MAPA_NS = PONTE_MAPA_ESTAGIOS * TCK_DDR5_PS / 1000            # no relógio do DDR5-4800


def cabe_no_tck(niveis, tck_ps=TCK_GDDR7_PS):
    return niveis * ATRASO_PORTA_PS + REGISTRO_PS <= tck_ps
