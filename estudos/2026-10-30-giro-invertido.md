# Giro invertido: muitos tokens por leitura dos pesos

Estudo, 2026-10-30. Sem implementação.

## Problema

Um modelo de LLM maior que a VRAM gera texto devagar: a cada token, a parte dos
pesos que ficou fora da VRAM é lida da memória lenta (RAM a ~80 GB/s, ou PCIe a
~50 GB/s), contra ~670 GB/s da VRAM. A GPU passa quase todo o tempo esperando.

## Ideia

- **Giro:** a parte do modelo que não cabe na VRAM passa da RAM para a GPU,
  camada por camada, a cada passada.
- **O inverso:** num modelo inteiro (denso, não MoE), todo token usa todos os
  pesos, então uma passada custa o mesmo para 1 token ou para ~200. Em vez de
  acelerar o giro, cada giro rende vários tokens:
  1. um modelo pequeno, na VRAM, chuta uma árvore de ~200 continuações;
  2. o giro passa o modelo grande uma vez, e a GPU confere a árvore inteira;
  3. fica o caminho mais longo confirmado, ~6 a 8 tokens por giro. O texto é
     idêntico ao do modelo grande sozinho.
- **Por que só no inteiro:** no MoE cada chute chama especialistas diferentes, e
  o giro teria de trazer quase todos.
- **No giro, não no modo comum:** no modo comum (llama.cpp) a CPU calcula a parte
  da RAM e não dá conta de conferir 200 chutes. A GPU dá.

## Variante: bits altos como chute

O chute é o próprio modelo grande, só com os bits altos de cada peso, guardados
na VRAM; o giro traz só os bits baixos. Os bits altos servem ao chute e à
conferência, sem cópia extra. Não achamos quem faça. Risco: os bits altos
sozinhos chutarem mal (truncar um 4 bits comum dá um 2 bits ruim; um formato em
resíduo, 2 + 2, otimizado para o 1º estágio funcionar sozinho, pode resolver).
Num 32B, a parte alta em 2 bits ocupa ~8 GB e cabe nos 12 GB.

## Variante: modelo agressivo na VRAM e cópia exata fora

O modelo inteiro quantizado de forma agressiva (2 bits, ~8 GB no 32B) cabe na
VRAM; a cópia exata fica fora. O reparo não pode ser como o da cache: lá, a cada
token, só ~500 tokens do contexto importam; aqui, num modelo inteiro, todo peso
entra em todo token, e reparar só os importantes traria quase o modelo todo.
O reparo é por conferência:

1. **Em lote, sem perda:** o 2 bits chuta, a cópia exata confere muitos tokens
   de uma vez. É o giro invertido com o 2 bits como chute.
2. **Só na dúvida, com perda pequena:** o 2 bits gera sozinho; quando a
   confiança cai, o exato confere e corrige (BiLD, 2023: ~2 vezes).

Onde guardar a cópia: a RAM é ~10 vezes mais rápida que o SSD, e os ~16 GB do
32B em 4 bits cabem nela. O SSD só tem vantagem própria para o original de 16
bits (~64 GB, não cabe na RAM): resposta igual à do original, ~9 s por
conferência.

| 32B no PC do dono (estimativa) | tokens/s | Qualidade |
|---|---|---|
| llama.cpp hoje, 4 bits | ~6 | a do 4 bits |
| 2 bits sozinho na VRAM | ~50 | perda visível |
| 2 bits + cópia de 4 bits na RAM, em lote | ~20 ou mais | igual à do 4 bits |
| 2 bits + original de 16 bits no SSD, em lote | ~2 | igual à do original |

As peças existem (SubSpec, SpecExec com 16 bits na RAM, BiLD); a combinação do 2
bits na VRAM conferido pelo original de 16 bits lido do SSD não achamos.

## Ligação com a cache de contexto

Ideias do estudo `2026-10-30-cache-de-contexto.md`, aplicadas aqui:

- **Cache menor, menos giro.** Tudo o que a cache libera na VRAM vira peso que
  não precisa girar. No 32B a 32 mil tokens, de f16 para q8_0 são ~4 GB a menos
  no giro (~11 → ~7 GB por passada).
- **O chute escolhe a cache.** O modelo pequeno já roda a cada giro; a atenção
  dele pode prever quais tokens da cache o grande vai olhar. Só esses ficam em
  precisão alta, sem custo de um modelo extra.
- **Q2 com reparo dentro do giro.** O reparo (trazer da RAM os ~500 tokens
  exatos) pode viajar junto com as camadas, enquanto a GPU calcula; os ~3 ms
  somem dentro do tempo do giro.
- **Cuidado:** a árvore de ~200 chutes também cria cache; ela é temporária e
  fica fora da cache quantizada.

## Números (estimativa, 32B em 4 bits no PC do dono)

| | tokens/s |
|---|---|
| llama.cpp hoje | ~6 |
| Giro invertido | ~20 (15 a 25, conforme o texto) |
| Com os bits altos | não estimado |

PC: i5-13600KF, 32 GB DDR5, RTX 5070 12 GB, PCIe 5.0 x16.

## Complexidade

1. Provar a ideia (tokens por giro, com modelos pequenos): simples.
2. Rodar rápido num PC: médio; o trabalho é trazer a próxima camada enquanto a
   GPU calcula a atual.
3. Bits altos: pesquisa; formato de pesos e código de GPU próprios.

## Referências

- [SpecExec](https://arxiv.org/abs/2406.02532) (2024): 4 a 6 tokens/s em 50B+ numa GPU comum, 10 a 18 vezes o giro simples.
- [Sequoia](https://arxiv.org/abs/2402.12374) (2024): Llama2-70B com giro a ~0,56 s/token.
- [SubSpec](https://arxiv.org/abs/2509.18344) (2025): cópias de poucos bits das camadas do giro como chute; 9 a 12,5 vezes.
- [ShadowSpec](https://icml.cc/virtual/2026/75131) (2026): 17 a 54 % sobre o SubSpec.
- [SPEQ](https://arxiv.org/abs/2510.18525) (2025): chute tirado de parte dos bits do próprio modelo, sem giro.
- [BiLD](https://arxiv.org/abs/2302.07863) (2023): o pequeno gera e chama o grande na dúvida; ~2 vezes, perda pequena.
