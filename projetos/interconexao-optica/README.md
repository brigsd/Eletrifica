# Interconexão Modular Óptica

> ### ▶ [**Abrir o visualizador 3D**](https://brigsd.github.io/Eletrifica/projetos/interconexao-optica/)
> Clique em **Ligar** para ver a base sondar, identificar, configurar e energizar
> cada peça, travar os anéis e acender as fibras. Duplo clique numa peça mostra o
> que ela faz e os números da simulação.

Uma base no lugar da placa-mãe: CPU, memória e GPU encaixam em qualquer posição
sobre um elastômero de células chaveadas; a base descobre o que foi encaixado,
alimenta cada peça e leva os dados por fibra óptica. Conceito em
[`docs/conceito.md`](docs/conceito.md).

Este diretório é o **emulador** desse sistema: lógica, energia, luz e dados,
simulados pelos módulos em `modulos/` da raiz.

## Resultados

Todos em [`docs/resultados.md`](docs/resultados.md), regenerado a cada rodada:

```bash
python3 -m modulos.sistema.simular     # ~30 s; grava docs/ e web/
```

Os achados principais:

1. **Mapeamento funciona.** As 18 peças são identificadas só por sondagem fraca,
   em qualquer posição e rotação, com erro de micrômetros.
2. **64 comprimentos de onda por fibra não fecham** com anéis de 10 µm: os canais
   ficam mais próximos que a largura do filtro e a diafonia trava a taxa de
   erros, com qualquer potência. A configuração **viável** é 16 λ por fibra e um
   laser para cada 4 canais.
3. **Controle térmico por anel é obrigatório**: sem ele o enlace aguenta menos de
   1 °C de variação.
4. **Contatos de energia**: a 200 A, com plano de 1 oz, pinos de núcleo da CPU
   perto do regulador passam de 1 A; com 2 oz o máximo cai para ~0,9 A.
5. **Treino de memória** converge pelo caminho óptico, e quebra se uma peça se
   mover depois — a reconfiguração tem de vir antes do treino.
6. **As conexões fecham salto a salto.** Cada sinal é seguido de pino a pino
   (célula, trilha, tradutor, laser, fibra, receptor, driver), com energia,
   controle e relógio de cada bloco. O conceito, como estava, dá ~2.800 erros no
   verificador; quatro decisões de projeto zeram todos, e o boot emulado completa.
7. **Contato imperfeito é detectado.** Canto levantado de 0,2° já degrada a CPU;
   0,5° a recusa. Sujeira condutiva e pino torto viram ponte e a peça não liga.
   Tabela em [`docs/defeitos.md`](docs/defeitos.md).
8. **Folga dos números escolhidos:** nenhum abaixo de 20 %; os mais justos são
   vias por chip (25 %) e perda da trilha (29 %). Ver
   [`docs/sensibilidade.md`](docs/sensibilidade.md).

9. **Chipset de verdade.** Um Intel B760 entra como peça: gera os relógios,
   sequencia a energia e carrega o ME e a BIOS da flash. O FPGA só orquestra a base.
10. **Memória compartilhada via CXL não fecha:** nem a i5-13600KF nem a GPU
    suportam CXL. Pelo PCIe com ReBAR, a CPU lê a GDDR7 a ~55 GB/s e ~800 ns,
    contra ~65 GB/s e ~90 ns da DDR5 local.

## Decisões de projeto que o verificador exigiu

Ficam em `montagem.json`, chave `projeto`:

| Decisão | Por quê |
|---------|---------|
| `tradutores: sob_peca` | Ao lado da peça, trilhas de até 120 mm estouram atraso e desalinhamento da GDDR7. Numa camada de fotônica sob a peça, o pino desce poucos mm. |
| `chave_celula: rele_mems` | A mesma chave não serve para 1 A de energia e para 32 Gb/s: transistor com R_on baixo tem dezenas de pF desligado. Relé aberto é vão de ar (~20 fF); só comuta sem corrente, e as células são configuradas antes de energizar. |
| `cobre_plano_oz: 2` | Com 1 oz, pinos de VCCIN perto do VRM passam de 1 A. |
| `placa_fria_h_w_m2k: 1000` | A interconexão dissipa ~88 W dentro da base; só com ar ela chega a ~200 °C e peças, relés e anéis passam do limite. Com placa fria de líquido sob a base, ~57 °C. |
| `vias_termicas_fracao: 0.05` | O LCP conduz mal: sem cobre atravessando a base, a placa fria rende ~230 W/m²K e a base passa de 95 °C. Com vias térmicas em 5 % da área, ~950 W/m²K e ~58 °C. |

## Fontes do projeto

| Arquivo | O que define |
|---------|--------------|
| `montagem.json` | Tamanho da base, passo das células, onde cada peça foi encaixada (só a sondagem emulada lê a posição) e as decisões de projeto |
| `enlace.json` | Parâmetros físicos do enlace óptico e as configurações original, ajustada e viável |
| `docs/conceito.md` | O conceito, transcrito do documento do dono |

Tudo em `docs/*.svg`, `docs/resultados.md` e `web/` é gerado. Não edite à mão.

## Módulos usados

| Módulo | Simula |
|--------|--------|
| `modulos/componentes` | As peças: contatos, função de cada pino, trilhos, interfaces |
| `modulos/sistema` | Base de células, chave da célula, sondagem, identificação, configuração, boot emulado, simulação completa |
| `modulos/conexoes` | Netlist do sistema inteiro (cada salto tipado) e o verificador de conexões, com 18 regras; sensibilidade dos números escolhidos |
| `modulos/energia` | Divisão de corrente nos contatos, VRM, proteção contra curto, árvore de alimentação |
| `modulos/termico` | Temperatura da base em regime e no transiente |
| `modulos/optica` | Anel modulador, filtros, receptor, enlace no tempo, controle térmico dos anéis |
| `modulos/dados` | Protocolos, roteamento sinal → canal → fibra, latência, rajadas, treino de memória |
| `modulos/visual` | Cena do visualizador e gráficos |

As pinagens das peças são sintéticas: contagem, passo e proporção entre energia,
terra e sinal seguem cada encapsulamento, mas não a posição de cada sinal no
datasheet.
