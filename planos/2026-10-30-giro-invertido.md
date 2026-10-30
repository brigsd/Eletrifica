# Giro invertido: muitos tokens por leitura dos pesos

Aberto em: 2026-10-30 · Responsável: Claude (sessões e subagentes)

## Objetivo

Rodar no PC do dono um modelo **inteiro** (denso, não MoE) maior que a VRAM numa
velocidade confortável, sem trocar hardware e sem mudar a resposta do modelo.

Alvo: um modelo inteiro de 32B em 4 bits (~18 GB) na RTX 5070 (12 GB), de
**~6 tokens/s** (llama.cpp hoje) para **~20** (faixa de 15 a 25, estimativa).

## A ideia

- **Giro:** a parte do modelo que não cabe na VRAM passa da RAM para a GPU pelo
  PCIe, camada por camada, a cada passada. Quase ninguém gera texto assim: cada
  passada rende 1 token e custa ~11 GB de leitura no 32B.
- **O inverso:** num modelo inteiro, todo token usa todos os pesos, então uma
  passada custa o mesmo para 1 token ou para ~200. Em vez de acelerar o giro,
  cada giro passa a render vários tokens:
  1. um modelo pequeno, residente na VRAM, chuta uma árvore de ~200 continuações;
  2. o giro passa o modelo grande uma vez, e a GPU confere a árvore inteira (ela
     ficaria parada esperando os pesos, então a conta sai de graça até o limite
     de cálculo dela);
  3. fica o caminho mais longo que o modelo grande confirma, ~6 a 8 tokens por
     giro. O texto é idêntico ao do modelo grande sozinho.
- **Por que só no inteiro:** no MoE cada chute chama especialistas diferentes, e
  o giro teria de trazer quase todos. O reaproveitamento some.
- **Passo novo** (não achamos quem faça): o chute é o próprio modelo grande, só
  com os bits altos de cada peso, guardados na VRAM; o giro traz só os bits
  baixos. Os bits altos servem ao chute e à conferência, sem cópia extra. O
  chute erra menos (é o mesmo modelo) e o giro encolhe. Risco: os bits altos
  sozinhos chutarem mal; a etapa 2 mede isso antes de construir.

## O que é medido e o que é conta

- **Medido na VM** (não depende do hardware): tokens aceitos por giro, por
  tamanho de árvore e tipo de texto; texto idêntico ao de referência.
- **Conta até a etapa 4:** tempo do giro = bytes do giro / banda do PCIe +
  leitura da VRAM + tempo do chute; o cálculo da GPU limita o tamanho da árvore.
- **Medido no PC do dono** (etapas 4 e 5): tokens/s de verdade.

## Organização

```
modulos/llm/           código próprio; os artigos são referência
  modelos.py           baixa e carrega os modelos (ficam em build/, fora do git)
  arvore.py            chute em árvore pelo modelo pequeno
  conferir.py          conferência da árvore numa passada (máscara de atenção em árvore)
  bits.py              pesos em bits altos + bits baixos (etapa 2)
  medir.py             tokens por giro x tamanho da árvore x tipo de texto
  conta.py             tempo do giro e tokens/s pela banda de cada máquina
  giro.py              giro real na GPU: RAM -> VRAM em fila dupla (etapa 4)
projetos/giro-invertido/
  textos.json          prompts de conversa, código e texto criativo (fonte)
  docs/resultados.md   gerado: medido e conta lado a lado, antes e depois
  medidas/<máquina>/<hash>.json   resultados do PC do dono, publicados
tests/test_llm.py      pulado com aviso se faltar torch, modelo ou GPU
```

## Etapas

- [ ] **0. Base.** Módulo `modulos/llm/`, PyTorch para CPU e `transformers` num
  `requirements` próprio, com um job `llm` na CI como o `rtl`. Escolher uma
  família de modelos inteiros com vários tamanhos e o mesmo tokenizador (ex.:
  Qwen): na VM (4 núcleos, 15 GB), um de ~0,5B chuta e um de 1,5B a 3B confere.
  `textos.json` com os três tipos de texto. Pronto: geração de referência (o
  modelo que confere, sozinho, sempre a palavra mais provável) gravada por
  script e repetível; `CLAUDE.md` com a seção do projeto.
- [ ] **1. Chute em árvore e conferência numa passada (VM).** O pequeno monta a
  árvore com as continuações mais prováveis até o orçamento B; o grande confere
  todas numa passada; fica o caminho mais longo confirmado, e a cache de atenção
  guarda só ele. Pronto: (a) texto idêntico à referência em todos os prompts,
  com um teste no pytest usando um modelo minúsculo aleatório (sem download, roda
  na CI); (b) tabela de tokens por giro para B = 1, 8, 32, 64, 128, 256, por tipo
  de texto. Amostragem com temperatura fica para depois.
- [ ] **2. Bits altos como chute (VM).** Quantizar o modelo que confere em 4 bits,
  em formato aninhado, e usar só os bits altos como chute (simulado no PyTorch,
  sem núcleo próprio). Formatos: (a) truncar o 4 bits comum nos 2 altos; (b) 2 + 2
  em resíduo (o 1º estágio otimizado para funcionar sozinho em 2 bits, o 2º
  corrige o resto); (c) 3 + 1. Conferir se a parte alta do 32B cabe na VRAM com a
  cache (2 bits: ~8 GB, cabe; 3 bits: ~12 GB, só até ~24B). Pronto: o 4 bits
  aninhado sem perda contra o 4 bits comum (perplexidade num texto fixo); tabela
  com tokens por giro, bytes por giro e tokens por GB girado, contra o chute da
  etapa 1; decisão do dono registrada: segue ou não para a etapa 5.
- [ ] **3. Conta dos tokens/s.** `conta.py` com os números de cada máquina (VRAM,
  banda do PCIe e da RAM, cálculo da GPU), combinados com o medido nas etapas 1
  e 2. Pronto: `docs/resultados.md` gerado por script, antes e depois, separando
  medido de conta, e conferido contra a ordem de grandeza dos artigos.
- [ ] **4. Giro real no PC do dono.** Linux ou WSL, PyTorch com suporte à 5070;
  ligado à sessão pelo Remote Control ou rodado pelo dono com um comando. Medir
  antes a banda real do PCIe e da RAM. RAM fixa (pinned), fila dupla (traz a
  camada seguinte enquanto a GPU calcula a atual), núcleos de 4 bits, chute
  residente na VRAM. Pronto: o 32B em 4 bits na 5070 com texto idêntico à
  referência; tokens/s medido contra o giro simples (B = 1) e contra o llama.cpp
  com o mesmo modelo; resultado publicado em `medidas/`. Alvo: ~20 tokens/s.
- [ ] **5. Passo novo no PC (só se a etapa 2 aprovar).** Bits altos na VRAM, bits
  baixos na RAM; núcleo de GPU próprio que junta as duas partes na hora; o chute
  usa só os altos. Pronto: tokens/s medido contra a etapa 4, com texto idêntico.

Cada etapa: teste no pytest, relatório gerado por script, `CLAUDE.md` atualizado.

## Números de partida (estimativa, 2026-10-30)

| 32B em 4 bits no PC do dono | tokens/s |
|---|---|
| llama.cpp hoje (a CPU calcula a parte que está na RAM) | ~6 |
| Giro invertido | ~20 (15 a 25) |
| Mais o passo novo | a medir |

PC do dono: i5-13600KF, 32 GB DDR5 (~80 GB/s), RTX 5070 com 12 GB GDDR7
(~670 GB/s), PCIe 5.0 x16 (~50 GB/s na prática, a medir), MAG Z790 Tomahawk.

## Referências

- [SpecExec](https://arxiv.org/abs/2406.02532) (2024): árvore grande com giro;
  4 a 6 tokens/s em modelos de 50B+ numa GPU comum, 10 a 18 vezes o giro simples.
- [Sequoia](https://arxiv.org/abs/2402.12374) (2024): árvore ajustada ao
  hardware; Llama2-70B com giro a ~0,56 s/token.
- [SubSpec](https://arxiv.org/abs/2509.18344) (2025): chute = o próprio modelo,
  com cópias de poucos bits das camadas do giro na VRAM; 9 a 12,5 vezes o giro
  simples.
- [ShadowSpec](https://icml.cc/virtual/2026/75131) (2026): aproveita o tempo do
  giro; 17 a 54 % sobre o SubSpec.
- [SPEQ](https://arxiv.org/abs/2510.18525) (2025): chute tirado de parte dos bits
  do próprio modelo, sem giro.

## Decisões

- 2026-10-30 — Dono: foco em modelos inteiros, não MoE ("o segredo está no
  sentido inverso").
- 2026-10-30 — Dono pediu o plano depois de ver o antes e depois (~6 → ~20
  tokens/s) e a complexidade das partes.

## Histórico

- 2026-10-30 — Plano aberto, depois do encerramento do plano dos motores. Origem:
  a conversa sobre o gargalo do LLM (giro dos pesos, sentido inverso, modelos
  inteiros).
