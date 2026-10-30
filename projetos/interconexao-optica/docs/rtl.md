# RTL do banco unificado

Gerado por `python3 -m modulos.rtl.relatorio`. Não edite à mão.

Os blocos que o tradutor do rank 0 de cada par de chips GDDR7 e a ponte precisam, escritos em Verilog sintetizável (`modulos/rtl/hdl/`), testados ciclo a ciclo no Verilator com cocotb e sintetizados no Yosys. A codificação de comando é a de `modulos/dados/comandos.py` (`hdl/comandos.vh` é gerado dela).

Relógio dos testes: CK de comando da GDDR7, 375.0 ps. RL do chip 32 CK, WL 27 CK; o chip emulado declara à GPU RL de 34 CK.

## O que os testes provam

| Bancada | Teste | Resultado | O que confere |
|---|---|---|---|
| `par_rank` | `trafego_intercalado` | passa | ACT/RD/WR/PRE/REF misturados em bancos dos dois ranks: cada comando chega ao chip certo, o outro recebe NOP, REF vai aos dois e cada leitura volta em RL_CHIP+RL_EXTRA. |
| `par_rank` | `troca_de_dono` | passa | O FPGA pede o rank 1 para a ponte no meio do tráfego: a troca espera o banco aberto no rank 1 fechar, o rank 0 continua servindo a GPU, a ponte grava no chip 1, o REF da GPU no rank 1 é absorvido, e na volta a GPU lê o que a ponte gravou. |
| `par_rank` | `treino_com_a_cpu` | passa | Os dois ranks com a ponte: a GPU retreina o chip que acha que é dela. A base absorve o REF (conta o que o chip deve), guarda o MRS, captura o WRTR no WL e devolve o RDTR exatamente em RL_CHIP + RL_EXTRA, nem um ciclo antes nem depois. Depois, com o rank 0 de volta à GPU, quem responde é o chip real. |
| `par_rank` | `cruzado_com_python` | passa | Mesmas entradas, mesmo resultado: o banco de memoria_unificada (mapa da GPU aleatório) grava; o RTL, alimentado com os comandos que a GPU geraria para cada endereço, devolve o que Banco.gpu_ler devolve, do chip que o Python escolheu. |
| `ponte_mapa` | `mapa_igual_ao_python` | passa | O FPGA carrega os mapas que a calibração aprendeu; para 2000 linhas de cache da CPU, o RTL leva os campos DDR5 dos pinos ao mesmo local GDDR7 que Banco._ponte_local. |

5 de 5 testes passam.

## Síntese

Genérico (ASIC): `synth` + `abc` em portas de 2 entradas; atraso estimado de 25 ps por nível e 60 ps de registro (nó de 16/12 nm). ECP5: `synth_ecp5` só com LUT4; 600 ps por nível e 500 ps de registro. A síntese mede células e níveis; os ps são estimativa.

| Bloco | Papel | Portas | FF | Níveis | Caminho | Fecha em 1 CK GDDR7 | LUT4 ECP5 | Níveis ECP5 | fmax ECP5 |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| `detector_rank` | decodifica ACT/banco e decide o rank | 289 | 35 | 11 | 275 ps | sim | 105 | 5 | 286 MHz |
| `seletor_rank` | CA ao chip escolhido, NOP ao outro; mux de leitura do DQ | 55 | 129 | 7 | 175 ps | sim | 42 | 3 | 435 MHz |
| `mux_posse` | dono por rank, troca só com o chip parado | 674 | 128 | 12 | 300 ps | sim | 395 | 6 | 244 MHz |
| `emulador_manutencao` | absorve REF/MRS e responde WRTR/RDTR no RL | 440 | 410 | 11 | 275 ps | sim | 489 | 4 | 345 MHz |
| `par_rank` | o tradutor do rank 0 inteiro | 1450 | 702 | 12 | 300 ps | sim | 1066 | 7 | 213 MHz |
| `ponte_mapa` | mapa aprendido DDR5 -> GDDR7 (GF(2) e resto por 3) | 3732 | 1496 | 26 | 650 ps | não | 1496 | 12 | 130 MHz |

A `ponte_mapa` roda no relógio do DDR5 (417 ps): o caminho de 650 ps pede 2 estágios. No ECP5 nada roda a 2,667 GHz: um protótipo em FPGA desserializa o CA e roda a lógica a uma fração do CK. a 1:8 (333 MHz) fecham `seletor_rank`, `emulador_manutencao`; a 1:16 (167 MHz) fecham `detector_rank`, `seletor_rank`, `mux_posse`, `emulador_manutencao`, `par_rank` (estimativa sem place-and-route).

## Declarado contra medido

| Constante | Declarado | Agora | De onde |
|---|---:|---:|---|
| `LATENCIA_RANK_PS` | 200 | 275 | 11 níveis x 25 ps |
| `SELETOR_CA_PS` | 250 | 375 | 1 registro (1 CK) |
| `SELETOR_DQ_PS` | 50 | 375 | 1 registro (1 CK): o mux de leitura é registrado |
| `RL_EXTRA_TCK` | 2 | 2 | os 2 registros; a leitura volta exatamente em RL+2 (cocotb) |
| `PONTE_LOGICA_NS` | 2 | 1.833 | mapa 0.83 ns (2 CK DDR5) + fila 1.00 ns (declarada, fora do RTL) |

A netlist liga um `emulador_manutencao` a cada detector de rank, com o arquivo RTL e o caminho medido; a R20 confere que ele existe, trata REF, WRTR e RDTR, responde no RL declarado e cabe num CK.

## Simplificações

- Codificação de comando no estilo do JESD239, não a tabela bit a bit (a mesma de `comandos.py`). O ACT leva os 3 bits altos da linha no primeiro ciclo, para o rank sair dele.
- DQ abstrato: 32 bits por CK, burst de 2 CK. Sem PAM3, WCK nem CRC.
- Treino periódico: só a FIFO de leitura (WRTR escreve, RDTR lê de volta), 4 entradas, padrão inicial fixo. Sem os padrões LFSR, sem WCK2CK, sem treino de VREF e de CA. O RDTR vai aos chips da GPU; o emulador responde quando nenhum chip do par é dela.
- REF absorvido vira dívida (até 15) que a ponte paga no chip; o MRS fica numa sombra de 16 registradores para a ponte reaplicar ao devolver o rank. A ponte em si não está no RTL.
- Temporização da DRAM (tRCD, tRP, tRFC exatos) não é conferida pelos modelos de chip; o mux de posse espera tRFC = 747 CK depois de um REF.
- Atrasos por nível são estimativa de processo; não há biblioteca de células nem place-and-route.
- A `ponte_mapa` tem hoje um registro só; os 2 estágios supõem retemporização ideal.

## Rodar

```bash
sudo apt-get install -y verilator yosys   # Verilator 5.020 do Ubuntu 24.04
python3 -m pip install -r requirements.txt  # cocotb 1.9
python3 -m modulos.rtl.sim                # testes cocotb
python3 -m modulos.rtl.sintese            # Yosys
python3 -m modulos.rtl.relatorio          # este arquivo
```
