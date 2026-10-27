# Resultados da simulação

Gerado por `python3 -m modulos.sistema.simular`. Não edite à mão.

Conceito em [`conceito.md`](conceito.md). Visualizador 3D em [`../index.html`](../index.html).

## Etapa 1 e 2 — acoplamento e mapeamento

- 21717 células em contato, 0 em ponte, sondadas em 43 ms.
- **17 de 17 peças identificadas** só pelo padrão terra/energia/sinal. Erro máximo de posição 2,2 µm e 0,13°.
- Energizar antes da identificação é recusado: “nenhuma peça identificada ainda”.
- Trocar peças de lugar e girar a CPU 91° continua identificando certo (`tests/test_sistema.py`).

## Etapa 3 — energia

- Fonte de 12 V: 641 W (53,4 A); 318 W passam pela base, 323 W pelo cabo da GPU.
- VCCIN a 200 A em 376 pinos e 976 células: média 0,53 A por pino, máximo **0,88 A**; **0 pinos passam de 1 A**. Célula mais carregada: 0,38 A.
- Queda IR na base 22,3 mV, perdas 4,5 W.
- VRM, degrau 30 → 180 A: queda total 170 mV (reta de carga), assenta em 9,8 µs, desbalanço entre fases 9,1 %, eficiência 92,4 %.
- Curto numa célula: pico de 46 A, desarma em **151 ns**, 6,2 µJ na chave.

![VRM](vrm-degrau.svg)

## Temperatura da base

Carga máxima, ar a 35 °C: a base chega a **118 °C**. Nos tradutores ópticos:

| Peça | °C |
|---|---|
| CPU | 94,6 |
| DIMM0 | 43,7 |
| DIMM1 | 42,2 |
| FPGA | 63,3 |
| GPU | 88,7 |
| MEM0 | 85,0 |
| MEM1 | 88,8 |
| MEM2 | 87,7 |
| MEM3 | 82,8 |
| MEM4 | 92,5 |
| MEM5 | 88,4 |
| MEM6 | 88,5 |
| MEM7 | 88,9 |
| MEM8 | 82,2 |
| MEM9 | 83,3 |
| MEM10 | 87,3 |
| MEM11 | 85,2 |

## Etapa 4 — enlace óptico

| Configuração | Cálculo do documento | Modelo físico | BER |
|---|---|---|---|
| original | -6,06 dB | não fecha | 3,9e-01 |
| ajustada | +2,46 dB | não fecha | 2,2e-01 |
| viável | +8,48 dB | +2,85 dB | 8,0e-25 |

- **64 comprimentos de onda por fibra não fecham.** Com anel de 10 µm o FSR é 13 nm; 64 canais ficam a 0,2 nm, menos que a largura do filtro. A soma do vazamento dos vizinhos fica do tamanho do sinal, e a BER trava num piso que mais potência não remove.
- **Configuração viável:** 16 λ por fibra e 1 laser de 10 mW para cada 4 canais.

Varredura da configuração ajustada (margem em PAM3, dB):

| Raio | 8 λ | 16 λ | 32 λ | 64 λ |
|---|---|---|---|---|
| 5,0 µm | -2,58 | -3,17 | não fecha | não fecha |
| 3,5 µm | -2,52 | -2,73 | -4,87 | não fecha |
| 2,5 µm | -2,49 | -2,58 | -3,16 | não fecha |

Canais simulados no tempo (configuração viável):

| Sinal | BER | erros / bits | atraso eletro-óptico | olho |
|---|---|---|---|---|
| GDDR7 | 1,2e-21 | 0 / 5952 | 32 ps | 0,31 UI |
| PCIe5 | < 1e-30 | 0 / 3968 | 25 ps | 0,44 UI |
| DDR5 | < 1e-30 | 0 / 3968 | 117 ps | 0,56 UI |

![Olho GDDR7](olho-gddr7.svg)

### Controle térmico dos anéis

- Sem controle o enlace aguenta **1,00 K** (NRZ) e **0,54 K** (PAM3) antes de perder a BER alvo.
- Com controle: trava em 200 µs; sob +10 K o erro máximo é 13,3 pm e o residual 0,05 pm. Sem controle chega a 561 pm.

![Controle térmico](controle-termico.svg)

## Conexões — a netlist do sistema inteiro

Cada sinal é seguido salto a salto: pino → célula → trilha na base → chip tradutor → modulador → fibra → filtro → receptor → driver de saída → trilha → célula → pino, com laser, alimentação, controle e relógio de cada bloco ativo. São 8807 blocos, 19121 ligações e 764 sinais. O verificador (`modulos/conexoes/verificador.py`) confere 12 regras.

Erros por regra, do conceito até o projeto atual:

| Regra | conceito: tradutor ao lado, célula com MOSFET | tradutor sob a peça | + relé MEMS na célula | + plano de energia com 2 oz |
|---|---|---|---|---|
| banda | 2658 | 2520 | 0 | 0 |
| energia | 1 | 1 | 1 | 0 |
| tempo | 46 | 0 | 0 | 0 |
| **total** | **2705** | **2521** | **1** | **0** |

O que cada decisão resolveu:

- **banda** (conceito): cel:CPU:DDR5_A_A_DQ0: banda 0,1 GHz < 2,4 GHz de DDR5-DQ
- **energia** (conceito): CPU:VCCIN: 21 pinos acima de 1 A (máx. 1,21 A)
- **tempo** (conceito): GPU.G8_DQ16->MEM3.GX_DQ16 (ida): 1120 ps > 1000 ps

- **Tradutor sob a peça:** com o chip ao lado, trilhas de até 120 mm na base estouram o atraso e o desalinhamento da GDDR7; numa camada de fotônica debaixo da peça, cada pino desce poucos milímetros até o seu chip.
- **Relé MEMS na célula:** a célula do conceito usa a mesma chave para 1 A de energia e para sinal de 32 Gb/s. Uma chave de transistor com R_on baixo o bastante para a energia tem dezenas de pF desligada, e isso derruba a banda de todo sinal rápido. Um relé, quando aberto, é um vão de ar: 20 fF. Ele só pode mudar de estado sem corrente, e a configuração das células acontece antes de energizar.
- **Plano de energia com 2 oz:** com 1 oz a corrente se concentra nos pinos de VCCIN perto do VRM e alguns passam de 1 A.

### Boot emulado na netlist: pronto em 551 ms

Máquina de estados com guarda em cada transição (`modulos/sistema/boot.py`):

| Etapa | Concluída em |
|---|---|
| Sondagem | 0,00 ms |
| Identificação | 43,43 ms |
| Configuração | 46,43 ms |
| Fonte e standby | 147,43 ms |
| Trilhos principais | 198,53 ms |
| Tradutores e lasers | 199,03 ms |
| Anéis travados | 199,23 ms |
| Núcleo da CPU | 199,80 ms |
| Relógio e reset | 200,80 ms |
| Treino da memória | 400,80 ms |
| PCIe e GDDR7 | 550,80 ms |
| Pronto | 550,80 ms |

## Etapa 5 — dados

- Canais ópticos: **755** em **64 fibras** com pinos bidirecionais comutados; 1287 em 103 fibras com um canal por sentido.

| Enlace | Atraso dos dados | Trilha elétrica na mesma posição | Placa-mãe comum |
|---|---|---|---|
| CPU-DIMM0 | 478 ps | 714 ps | 408 ps |
| CPU-DIMM1 | 654 ps | 952 ps | 408 ps |
| GPU-MEM7 | 226 ps | 340 ps | 102 ps |
| CPU-GPU | 337 ps | 544 ps | 1020 ps |
| CPU-FPGA | 511 ps | 952 ps | 816 ps |

- Treino DDR5: DIMM0 converge (64 pistas, janela mínima 36 passos de 3,26 ps), DIMM1 converge.
- Mover o DIMM0 10 mm depois de treinado: **9 de 64 pistas** saem do olho. Por isso a reconfiguração vem antes do treino.
- Rajadas pelo canal simulado: DDR5 escrita sem erro, DDR5 leitura sem erro, GDDR7 escrita sem erro.

