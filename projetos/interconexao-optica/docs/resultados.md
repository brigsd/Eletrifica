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
- VCCIN a 200 A em 376 pinos e 976 células: média 0,53 A por pino, máximo **1,21 A**; **21 pinos passam de 1 A** (os mais perto do VRM). Célula mais carregada: 0,50 A.
- Queda IR na base 25,7 mV, perdas 5,1 W.
- VRM, degrau 30 → 180 A: queda total 170 mV (reta de carga), assenta em 9,8 µs, desbalanço entre fases 9,1 %, eficiência 92,4 %.
- Curto numa célula: pico de 46 A, desarma em **151 ns**, 6,2 µJ na chave.

![VRM](vrm-degrau.svg)

## Temperatura da base

Carga máxima, ar a 35 °C: a base chega a **119 °C**. Nos tradutores ópticos:

| Peça | °C |
|---|---|
| CPU | 95,9 |
| DIMM0 | 43,8 |
| DIMM1 | 42,2 |
| FPGA | 63,4 |
| GPU | 88,9 |
| MEM0 | 85,0 |
| MEM1 | 88,9 |
| MEM2 | 87,9 |
| MEM3 | 82,8 |
| MEM4 | 92,9 |
| MEM5 | 88,5 |
| MEM6 | 88,5 |
| MEM7 | 89,4 |
| MEM8 | 82,3 |
| MEM9 | 83,4 |
| MEM10 | 87,5 |
| MEM11 | 85,5 |

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

## Etapa 5 — dados

- Canais ópticos: **758** em **60 fibras** com pinos bidirecionais comutados; 1289 em 99 fibras com um canal por sentido.

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

