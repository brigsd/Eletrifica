# Gargalos de um LLM fora da VRAM: o orçamento por link

Estudo, 2026-10-30. Sem implementação. Vale para qualquer motor e qualquer
modelo; o caso base é o Qwen3.8-Flash-Next no PC do dono.

## Em poucas palavras

O PC do dono aguentaria rodar o Qwen3.8-Flash-Next umas 10 vezes mais rápido do
que o colibri roda hoje (~25 a 40 contra 1 a 4 tok/s, estimativa). Quem atrasa
não é o hardware, é o programa: a CPU faz conta que a GPU faria, as cópias são
lentas e tudo anda em fila, com os links parados a maior parte do tempo. Como
uma estrada larga com o caminhão carregado à mão: alargar a estrada não ajuda;
carregar direito, sim.

## Regra geral

Cada token obriga certos bytes a atravessar certos links. Para cada link:

**tempo do link = bytes que precisam cruzá-lo por token / banda do link**

O teto de tokens/s sai do link mais lento quando todos trabalham ao mesmo tempo
(e da soma, se trabalham um depois do outro). Um projeto bom faz três coisas:

1. **Menos bytes no link lento:** a cache segura o que se repete; formato pequeno
   onde a banda é pouca.
2. **Todos os links cheios e em paralelo:** fila profunda no SSD, cópia direta
   para a VRAM, buffer duplo, trazer a próxima peça enquanto a atual é calculada.
3. **Sem ida e volta:** a GPU calcula a camada inteira; a CPU só decide o que
   trazer.

## Os três regimes

| Situação | Link que manda | O que resolve |
|---|---|---|
| Modelo inteiro maior que a VRAM | RAM → GPU (PCIe) | cada giro dos pesos render vários tokens (estudo do giro invertido) |
| MoE que cabe na RAM | RAM → GPU | VRAM com os especialistas quentes; a GPU calcula |
| MoE maior que a RAM | SSD → RAM | localidade dentro da conversa + VRAM + RAM como cache em camadas |

## Caso base: Qwen3.8-Flash-Next no PC do dono

O modelo: 125B, 6B ativos por token, 48 camadas, 512 especialistas por camada
(10 por token) mais um compartilhado. Por token: 480 especialistas de 2,64 MiB
em int4 (1,33 GB). A parte fixa (o tronco) tem ~4,5 GB em int8. A tabela de
n-gramas de 51B fica no disco: 16 leituras de 160 bytes por token.

PC: RTX 5070 12 GB (~670 GB/s), PCIe 5.0 x16 (~50 GB/s), 32 GB DDR5, SSD S70
Blade (~7 GB/s).

Localidade medida pelo colibri dentro de uma conversa (cache por camada):
32 vagas atendem 55 % das chamadas, 64 atendem 79 %, 128 atendem 90 %. Entre
conversas diferentes não há conjunto quente: cada assunto novo começa frio.

Divisão das memórias:
- **VRAM:** tronco (~4,5 GB) + ~2.100 especialistas (~44 vagas por camada, ~64 %
  das chamadas).
- **RAM:** ~25 GB com ~9.000 especialistas (total de ~230 vagas por camada, ~95 %).
- **SSD:** o resto (~5 % das chamadas).

| Link | O que cruza por token | Tempo |
|---|---|---|
| VRAM → GPU | tronco + ~310 especialistas (~5,4 GB) | ~8 ms |
| RAM → VRAM | ~145 especialistas (~0,4 GB) | ~8 ms |
| SSD → RAM | ~24 especialistas (~66 MB) | ~9 ms |

Teto: ~10 ms por token com os links em paralelo, ~25 ms em série. Com a espera
de cada camada (só se sabe quais especialistas vêm depois do roteador dela):
**~25 a 40 tok/s** (estimativa). Com os pesos originais em FP8 (4,7 MiB por
especialista, metade cabe), ~12 a 20.

## Comparação com o colibri

Medido por ele com este modelo:

| Máquina | tok/s |
|---|---|
| i9-14900K, 61 GB, SSD de 2,3 GB/s, só CPU, FP8 | 1,1 a 1,2 |
| Ryzen 7 8700GE, 61 GB, só CPU, int4, 170 vagas | 4,0 |
| Threadripper + duas GPUs de 8 GB, FP8 | 2,1 |

O teto do orçamento fica ~10 vezes acima. Onde o tempo vai, pelas medições dele
(por token, na máquina com duas GPUs):

- **a CPU calcula metade dos especialistas:** 93 a 192 ms;
- **cópia das faltas da cache de páginas para a cache dele:** 145 a 168 ms, ~1,5 GB/s
  (o SSD sozinho entrega 7);
- **tronco na GPU:** 52 a 89 ms para ~4 GB, quando a banda da placa permitiria ~9.

Nenhum link está cheio: o tempo vai em cálculo na CPU, cópias e ida e volta
entre CPU e GPU. O limite não é o barramento; é como os dados se movem. A
conclusão do registro de falhas do colibri ("não sobra 1,5 a 2 vezes") foi
medida no GLM-5.2 com tudo residente num servidor de 6 GPUs, não neste caso.

## Princípios para o motor

1. A GPU calcula tudo, inclusive DeltaNet, atenção e todos os especialistas; a
   CPU só move dados e decide o que trazer.
2. Faltas da RAM vão para a VRAM por DMA, em lote por camada; faltas do SSD
   entram em fila profunda direto na memória fixa (pinned), sem cópia extra.
3. A cache é dimensionada pela localidade dentro da conversa; no Qwen3.8,
   histórico entre conversas não ajuda.
4. A camada inteira roda na GPU numa só submissão; o roteador da camada seguinte,
   aplicado ao estado atual, adianta as leituras.
5. Formato pequeno onde o link é lento: int4 nos especialistas (ou FP8, se a
   resposta tiver de ser a original).
6. Chute (a cabeça MTP do Qwen3.8 acerta 94 a 96 % no 1º chute) só quando o
   acerto da cache é alto: com ~95 %, as linhas extras quase não leem o SSD.

## O que falta medir

- A localidade em conversas longas e com troca de assunto (o 95 % é extrapolado
  do 90 % de 128 vagas).
- O tempo para o primeiro token num assunto novo: o prompt toca quase todos os
  especialistas; ~68 GB em int4, ~10 s no SSD.
- A espera real por camada na 5070 (lançamento de núcleos e sincronização).

## Fontes

- [colibri: docs/qwen38.md](https://github.com/JustVugg/colibri/blob/e0db083/docs/qwen38.md)
  (arquitetura, memória, localidade, medições de CPU e GPU)
- [colibri: README](https://github.com/JustVugg/colibri/blob/e0db083/README.md)
