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
