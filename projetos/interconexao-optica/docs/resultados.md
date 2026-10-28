# Resultados da simulação

Gerado por `python3 -m modulos.sistema.simular`. Não edite à mão.

Conceito em [`conceito.md`](conceito.md). Visualizador 3D em [`../index.html`](../index.html).

## Etapa 1 e 2 — acoplamento e mapeamento

- 32360 células em contato, 0 em ponte, sondadas em 65 ms.
- **30 de 30 peças identificadas** só pelo padrão terra/energia/sinal. Erro máximo de posição 0,9 µm e 0,13°.
- Energizar antes da identificação é recusado: “nenhuma peça identificada ainda”.
- Trocar peças de lugar e girar qualquer peça em qualquer ângulo (37°, 63,5°, 133°, 301°) continua identificando certo (`tests/test_sistema.py`).

## Etapa 3 — energia

- Fonte de 12 V: 717 W (59,8 A); 394 W passam pela base, 323 W pelo cabo da GPU.
- VCCIN a 200 A em 376 pinos e 976 células: média 0,53 A por pino, máximo **0,88 A**; **0 pinos passam de 1 A**. Célula mais carregada: 0,38 A.
- Queda IR na base 22,3 mV, perdas 4,5 W.
- VRM, degrau 30 → 180 A: queda total 170 mV (reta de carga), assenta em 9,8 µs, desbalanço entre fases 9,1 %, eficiência 92,4 %.
- Curto numa célula: pico de 46 A, desarma em **151 ns**, 6,2 µJ na chave.

![VRM](vrm-degrau.svg)

## Temperatura da base

A interconexão dissipa **149 W** dentro da própria base (chips tradutores e lasers). Só com o ar do gabinete a base chegaria a 267 °C. Com a placa fria sob a base (1000 W/m²K, líquido a 35 °C) e vias térmicas de cobre em 5% da área atravessando o LCP (troca efetiva 952 W/m²K), em carga máxima a base chega a **64 °C**. Sem as vias, o LCP de 1 mm segura o calor e a placa fria sozinha não basta.

- Aquecedor dos anéis: o local mais exigente pede 3,40 nm de sintonia; o aquecedor dá 4,00 nm. 0 chips sem faixa. A frio, os aquecedores gastam 29,2 W.
- Consumo da interconexão: **166 W**, 11,2 pJ/bit sobre 14,8 Tb/s; uma ligação elétrica inteira custa ~6,3 pJ/bit. Partes: tradutores 88,1 W, controle das células 0,0 W, lasers 48,5 W, aquecedores (pior caso) 29,2 W.

Nos tradutores ópticos:

| Peça | °C |
|---|---|
| CPU | 44,6 |
| DIMM | 36,8 |
| FPGA | 37,6 |
| GPU | 52,1 |
| MEM0 | 48,0 |
| MEM1 | 53,7 |
| MEM2 | 52,9 |
| MEM3 | 47,1 |
| MEM4 | 51,6 |
| MEM5 | 53,5 |
| MEM6 | 51,4 |
| MEM7 | 51,0 |
| MEM8 | 45,8 |
| MEM9 | 53,0 |
| MEM10 | 49,6 |
| MEM11 | 46,8 |
| MEM12 | 48,5 |
| MEM13 | 46,8 |
| MEM14 | 48,9 |
| MEM15 | 47,4 |
| MEM16 | 46,9 |
| MEM17 | 44,6 |
| MEM18 | 47,3 |
| MEM19 | 50,7 |
| MEM20 | 50,3 |
| MEM21 | 46,5 |
| MEM22 | 48,2 |
| MEM23 | 47,1 |
| PCH | 36,8 |
| PONTE | 39,3 |

## Etapa 4 — enlace óptico

| Configuração | Cálculo do documento | Modelo físico | BER |
|---|---|---|---|
| original | -6,06 dB | não fecha | 4,1e-01 |
| ajustada | +2,46 dB | não fecha | 2,5e-01 |
| viável | +8,48 dB | +1,27 dB | 1,3e-17 |

- **64 comprimentos de onda por fibra não fecham.** Com anel de raio 5,0 µm o FSR é 13 nm; os canais ficam a 0,2 nm, menos que a largura do filtro. A soma do vazamento dos vizinhos fica do tamanho do sinal, e a BER trava num piso que mais potência não remove.
- **Configuração viável:** 16 λ por fibra a 1,16 nm (~203 GHz), anel de raio 3,5 µm (FSR 18,6 nm), 25 pm/V e 1 laser de 10 mW para cada 4 canais.

Varredura da configuração ajustada (margem em PAM3, dB):

| Raio | 8 λ | 16 λ | 32 λ | 64 λ |
|---|---|---|---|---|
| 5,0 µm | -4,60 | -5,21 | não fecha | não fecha |
| 3,5 µm | -4,54 | -4,75 | -6,94 | não fecha |
| 2,5 µm | -4,51 | -4,60 | -5,20 | não fecha |

Canais simulados no tempo (configuração viável):

| Sinal | BER | erros / bits | atraso eletro-óptico | olho |
|---|---|---|---|---|
| GDDR7 | 3,0e-14 | 0 / 5952 | 32 ps | 0,25 UI |
| PCIe5 | 4,9e-30 | 0 / 3968 | 25 ps | 0,44 UI |
| DDR5 | < 1e-30 | 0 / 3968 | 117 ps | 0,56 UI |

![Olho GDDR7](olho-gddr7.svg)

### Controle térmico dos anéis

- Sem controle o enlace aguenta **0,88 K** (NRZ) e **0,38 K** (PAM3) antes de perder a BER alvo.
- Com controle: trava em 200 µs; sob +10 K o erro máximo é 12,9 pm e o residual 0,05 pm. Sem controle chega a 561 pm.

![Controle térmico](controle-termico.svg)

## Conexões — a netlist do sistema inteiro

Cada sinal é seguido salto a salto: pino → célula → trilha na base → chip tradutor → modulador → fibra → filtro → receptor → driver de saída → trilha → célula → pino, com laser, alimentação, controle e relógio de cada bloco ativo. São 15669 blocos, 34726 ligações e 2225 sinais. O verificador (`modulos/conexoes/verificador.py`) confere 20 regras.

Erros por regra, do conceito até o projeto atual:

| Regra | conceito: tradutor ao lado, célula com MOSFET | tradutor sob a peça | + relé MEMS na célula | + plano de energia com 2 oz | + placa fria sob a base | + vias térmicas até a placa |
|---|---|---|---|---|---|---|
| banda | 9058 | 7702 | 0 | 0 | 0 | 0 |
| energia | 1 | 1 | 1 | 0 | 0 | 0 |
| temperatura | 149 | 165 | 167 | 166 | 61 | 0 |
| **total** | **9208** | **7868** | **168** | **166** | **61** | **0** |

O que cada decisão resolveu:

- **banda** (conceito): cel:CPU:DDR5_A_A_DQ0: banda 0,1 GHz < 2,4 GHz de DDR5-DQ
- **energia** (conceito): CPU:VCCIN: 21 pinos acima de 1 A (máx. 1,21 A)
- **temperatura** (conceito): peça MEM2 (GDDR7): 159,9 °C > 105 °C

- **Tradutor sob a peça:** com o chip ao lado, trilhas de até 120 mm na base estouram o atraso e o desalinhamento da GDDR7; numa camada de fotônica debaixo da peça, cada pino desce poucos milímetros até o seu chip.
- **Relé MEMS na célula:** a célula do conceito usa a mesma chave para 1 A de energia e para sinal de 32 Gb/s. Uma chave de transistor com R_on baixo o bastante para a energia tem dezenas de pF desligada, e isso derruba a banda de todo sinal rápido. Um relé, quando aberto, é um vão de ar: 20 fF. Ele só pode mudar de estado sem corrente, e a configuração das células acontece antes de energizar.
- **Plano de energia com 2 oz:** com 1 oz a corrente se concentra nos pinos de VCCIN perto do VRM e alguns passam de 1 A.
- **Placa fria sob a base:** a interconexão dissipa dezenas de watts dentro da base; com o ar do gabinete, peças, células (relé até 85 °C) e anéis passam do limite, e o aquecedor não cobre a variação de temperatura.
- **Vias térmicas até a placa:** o LCP conduz mal (0,3 W/m·K); sem cobre atravessando a base, a placa fria rende só ~230 W/m²K e ainda sobram peças quentes demais.

Folga de cada número escolhido: [`sensibilidade.md`](sensibilidade.md). Contato imperfeito (peça inclinada, sujeira, pino torto): [`defeitos.md`](defeitos.md).

### Boot emulado na netlist: pronto em 541 ms

Máquina de estados com guarda em cada transição (`modulos/sistema/boot.py`):

| Etapa | Concluída em |
|---|---|
| Sondagem | 0,00 ms |
| Identificação | 64,72 ms |
| Configuração | 67,72 ms |
| Fonte e standby | 168,72 ms |
| ME do chipset | 198,82 ms |
| Trilhos principais | 199,92 ms |
| Tradutores e lasers | 200,42 ms |
| Anéis travados | 200,62 ms |
| Núcleo da CPU | 201,29 ms |
| Relógio e reset | 202,29 ms |
| BIOS pela DMI | 222,29 ms |
| Treino da memória | 422,29 ms |
| PCIe e GDDR7 | 507,62 ms |
| Banco unificado | 541,27 ms |
| Pronto | 541,27 ms |

### O que o tradutor faz além de copiar

- **Decodificação parcial.** Os dados são copiados sem decodificar. O comando, não: para saber o sentido dos pinos bidirecionais e acompanhar os ajustes elétricos, o tradutor decodifica MRR, RD, WR, MRW:5,32,33,34,35 na DDR5 e RD, RDTR, WR, WRTR, MRS:3,7,8 na GDDR7, e copia sem ler o resto (ACT, NOP, PREab, PREpb, REFab, VREFCA). Leva 1,3 ns na DDR5 contra 15 ns até o primeiro dado, e 1,2 ns na GDDR7 contra 9 ns.
- **Ajustes dinâmicos da DDR5.** A CPU muda terminação e força de saída por MRW durante o uso. O tradutor de cada ponta espelha esses valores: com espelho, 0 de 10 comandos divergem; sem espelho, 8 de 10 (pior caso: programado 240 Ω, visto 40 Ω, -369 mV de amplitude).
- **PCIe 5.** A detecção de receptor é controlada pelo FPGA (o tradutor só apresenta terminação com a GPU identificada e a luz travada) e o ocioso elétrico atravessa a luz. A equalização escolhe o preset P8 com CTLE de 2 dB: olho com 0,82 de altura e 0,84 UI de largura; com um tradutor idealmente linear seria 0,82 e 0,84 UI — a não linearidade do anel quase não pesa em NRZ.

### Memória compartilhada vista pela CPU

Nem a i5-13600KF nem a GPU têm CXL. Com o banco unificado da base (seção seguinte), a CPU lê os mesmos chips da GPU pelo próprio canal DDR5, como RAM comum; o ReBAR pelo PCIe continua existindo:

| Opção | Banda | Latência | Coerente |
|---|---|---|---|
| GPU vista pela CPU (ReBAR, PCIe 5 x16) | 55 GB/s | 1201 ns | não |
| DDR5 local (1 canal DDR5-4800) | 33 GB/s | 93 ns | sim |
| Unificada no encapsulamento (LPDDR5X-8533, 128 bits) (não dá nesta montagem) | 116 GB/s | 110 ns | sim |
| Banco unificado pela ponte (48 GB, os chips da GPU) | 33 GB/s | 96 ns | por posse |

## Banco unificado — CPU e GPU na mesma memória

A GPU só tem uma porta rápida, a de memória; o PCIe até a CPU é o barramento lento do offloading. Então o banco compartilhado entra pela porta de memória da GPU. A base está no meio de cada pino e faz o que uma placa-mãe não faz (`modulos/dados/memoria_unificada.py`):

- **Mais chips por canal.** 24 chips GDDR7 de 16 Gb; a GPU enxerga 12 chips de 32 Gb (o maior do padrão), cada um feito de 2 vizinhos. O seletor do grupo escolhe o chip pelo comando, como num LRDIMM: 480 seletores, 12 detectores, e uma linha de atraso em cada porta deixa os chips do grupo chegando juntos.
- **A CPU nos mesmos chips.** Um canal DDR5 da CPU vai para a ponte, que se apresenta como um DIMM de 48 GB e declara CL53 no SPD (o DDR5 aceita até CL66; a leitura pela ponte leva 21,9 ns, com 1,61 ns de caminho até os chips e 1,30 ns de volta).
- **Um dono por rank.** 480 muxes de posse, comandados pelo FPGA; enquanto um rank é da CPU, a base absorve ~6,3 milhões de refresh por segundo que a GPU manda para ele.
- **Mesmo endereço dos dois lados.** No boot a ponte aprende os dois mapas com 29 sondas da GPU e 28 da CPU e confere com 64 sondas aleatórias de cada lado: **0 erros**; varrer o banco leva 33,6 ms. Um mapa fora da família (rank misturado com bit baixo) é avisado.

Netlist: R19 (posse) 0 erros, R20 (banco) 0 erros; boot com o banco pronto em 541 ms.

Emulação bit a bit:

- A CPU grava 2000 linhas pela ponte, entrega os ranks e a GPU lê: **0 erros**. A GPU grava 500, devolve e a CPU lê: **0 erros**. Entregar um rank leva 22 µs.
- Sem o protocolo de entrega (descarregar a cache antes de passar o rank): **200 de 200** linhas lidas velhas pela GPU.
- Fora da posse: 50 acessos da GPU e 50 da CPU a um rank que não é deles, todos recusados.

LLM: cada token lê o modelo inteiro. Teto de tokens/s:

| Modelo | GB | PC comum, offload na CPU | Offload pelo PCIe | Banco unificado | Carga pela ponte |
|---|---|---|---|---|---|
| 34B em 4 bits | 19 | 79,3 | 79,3 | **79,3** | 0,6 s |
| 70B em 4 bits | 40 | 4,5 | 3,3 | **38,5** | 1,2 s |
| 34B em 8 bits | 36 | 5,8 | 4,3 | **42,6** | 1,1 s |
| 120B em 4 bits | 68 | 1,7 | 1,2 | 2,5 (não cabe) | 2,1 s |

Offload: a mesma GPU com 24 GB de VRAM a 1536 GB/s, e o resto na RAM da CPU (dois canais DDR5, como num PC comum) ou lido pelo PCIe. Banco: 48 GB, todos a 1536 GB/s; o que passar disso cai no PCIe. A CPU grava o modelo direto no banco a 38,4 GB/s, sem cópia pelo PCIe.

## Etapa 5 — dados

- Canais ópticos: **2207** em **100 fibras** com pinos bidirecionais comutados; 3891 em 163 fibras com um canal por sentido.

| Enlace | Atraso dos dados | Trilha elétrica na mesma posição | Placa-mãe comum |
|---|---|---|---|
| CPU-DIMM | 478 ps | 714 ps | 408 ps |
| CPU-PONTE | 222 ps | 422 ps | 408 ps |
| GPU-MEM14 | 226 ps | 340 ps | 102 ps |
| PONTE-MEM14 | 365 ps | 626 ps | 102 ps |
| CPU-GPU | 338 ps | 544 ps | 1020 ps |
| CPU-PCH | 531 ps | 714 ps | 816 ps |
| CPU-FPGA | 1023 ps | 952 ps | 816 ps |

- Treino DDR5: DIMM converge (64 pistas, janela mínima 36 passos de 3,26 ps), PONTE converge.
- Mover o DIMM 10 mm depois de treinado: **9 de 64 pistas** saem do olho. Por isso a reconfiguração vem antes do treino.
- Rajadas pelo canal simulado: DDR5 escrita sem erro, DDR5 leitura sem erro, GDDR7 escrita sem erro.

