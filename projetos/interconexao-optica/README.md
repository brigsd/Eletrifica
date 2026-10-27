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

1. **Mapeamento funciona.** As 17 peças são identificadas só por sondagem fraca,
   em qualquer posição e rotação, com erro de micrômetros.
2. **64 comprimentos de onda por fibra não fecham** com anéis de 10 µm: os canais
   ficam mais próximos que a largura do filtro e a diafonia trava a taxa de
   erros, com qualquer potência. A configuração **viável** é 16 λ por fibra e um
   laser para cada 4 canais.
3. **Controle térmico por anel é obrigatório**: sem ele o enlace aguenta menos de
   1 °C de variação.
4. **Contatos de energia**: a 200 A, alguns pinos de núcleo da CPU perto do
   regulador passam de 1 A.
5. **Treino de memória** converge pelo caminho óptico, e quebra se uma peça se
   mover depois — a reconfiguração tem de vir antes do treino.

## Fontes do projeto

| Arquivo | O que define |
|---------|--------------|
| `montagem.json` | Tamanho da base, passo das células, onde cada peça foi encaixada (só a sondagem emulada lê isto) |
| `enlace.json` | Parâmetros físicos do enlace óptico e as configurações original, ajustada e viável |
| `docs/conceito.md` | O conceito, transcrito do documento do dono |

Tudo em `docs/*.svg`, `docs/resultados.md` e `web/` é gerado. Não edite à mão.

## Módulos usados

| Módulo | Simula |
|--------|--------|
| `modulos/componentes` | As peças: contatos, função de cada pino, trilhos, interfaces |
| `modulos/sistema` | Base de células, sondagem, identificação, configuração, simulação completa |
| `modulos/energia` | Divisão de corrente nos contatos, VRM, proteção contra curto, árvore de alimentação |
| `modulos/termico` | Temperatura da base em regime e no transiente |
| `modulos/optica` | Anel modulador, filtros, receptor, enlace no tempo, controle térmico dos anéis |
| `modulos/dados` | Protocolos, roteamento sinal → canal → fibra, latência, rajadas, treino de memória |
| `modulos/visual` | Cena do visualizador e gráficos |

As pinagens das peças são sintéticas: contagem, passo e proporção entre energia,
terra e sinal seguem cada encapsulamento, mas não a posição de cada sinal no
datasheet.
