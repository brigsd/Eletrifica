# Quantizar a cache de contexto (KV)

Estudo, 2026-10-30. Sem implementação.

## Configuração

llama.cpp: `-ctk q8_0 -ctv q8_0 -fa` (o `-fa` é obrigatório para quantizar o V).
Ollama: `OLLAMA_KV_CACHE_TYPE=q8_0`. Mista: `-ctk q8_0 -ctv q4_0`.

| 32B, 32 mil tokens | Cache |
|---|---|
| f16 | ~8,6 GB |
| q8_0 | ~4,3 GB |
| q4_0 | ~2,1 GB |
| q2 | ~1,1 GB |

## Velocidade

- Contexto curto, modelo na VRAM: quase nada; pode ficar um pouco mais lento.
- Modelo maior que a VRAM: a VRAM liberada recebe camadas, e menos pesos ficam
  na RAM. 32B a 32 mil tokens: f16 → q8_0, ~4 → ~5,5 tokens/s; q2, ~7 (conta,
  não medição).
- Contexto longo: a cache inteira é lida a cada token; menor, lê mais rápido.

## Por que o q4_0 perde em contexto longo

Cada número da cache leva um erro de arredondamento. Com milhares de tokens, há
muitos de pontuação parecida na atenção, e o erro troca a ordem: o modelo olha o
token errado. A chave (K) é a mais sensível: alguns canais têm valores muito
maiores e, com uma escala por bloco, esmagam a precisão dos outros.

## Quem escolhe o que guardar: LLM menor ou algoritmo

O algoritmo. O melhor sinal de quais tokens importam é a atenção do próprio
modelo, que sai de graça. Um LLM menor custaria cálculo e só daria um palpite.
Algoritmos: H2O, SnapKV (os mais olhados), StreamingLLM (começo e fim), KIVI
(chave quantizada por canal).

## Cache em q2 com reparo

Cache inteira em q2 na VRAM, cópia exata na RAM (SSD só se não couber). A cada
token, a atenção sobre o q2 aponta os ~500 tokens mais importantes, e só esses
voltam exatos. No 32B, ~256 KB por token: ~130 MB por passo, ~3 ms pelo PCIe
vindo da RAM, ~18 ms do SSD. Ganha velocidade só em contexto longo, pela VRAM
liberada.

Por que funciona: a atenção se concentra em poucas centenas de tokens; o q2
basta para achá-los, e o reparo corrige justamente esses. Onde falha: atenção
espalhada (resumir um documento inteiro pede mais tokens exatos), token mal
ordenado pelo q2 fica de fora, e buscar na hora atrasa (é preciso prever antes).

Já existe: o **SpeCache** (ICML 2025) é quase esta ideia inteira. Cópia de 1 ou
2 bits na VRAM, original de 16 bits na RAM, busca só os mais importantes, e
prevê o que buscar gerando um token de chute, para a viagem correr junto com o
cálculo. Com a cache 10 vezes menor, não perdeu contexto (LongBench,
Needle-in-a-Haystack). Variantes: InfiniGen, ShadowKV. SSD como terceira camada:
KVSwap, LeoAM, SWARM. Nada disso está no llama.cpp.

## Fontes

- [KV Cache Quantization in Ollama and llama.cpp](https://llmhardware.io/guides/kv-cache-quantization-ollama-llama-cpp)
- [Llama.cpp Context Size](https://fast.io/resources/llama-cpp-context-size/)
- [SpeCache](https://arxiv.org/abs/2503.16163)
- [KVSwap](https://arxiv.org/pdf/2511.11907)
- [LeoAM](https://arxiv.org/pdf/2506.20187)
- [SWARM](https://arxiv.org/pdf/2603.17803)
