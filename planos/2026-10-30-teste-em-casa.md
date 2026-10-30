# Teste em casa: Qwen3.8-Flash-Next perto do teto do PC

Aberto em: 2026-10-30 · Responsável: Claude (código e análise) e o dono
(execução no PC)

## Objetivo

No PC do dono (RTX 5070 12 GB, 32 GB DDR5, SSD S70 Blade, i5-13600KF), rodar o
Qwen3.8-Flash-Next o mais perto possível do teto calculado em
`estudos/2026-10-30-gargalos-do-llm.md`: **~25 a 40 tok/s** em int4 (~12 a 20 em
FP8), contra 1 a 4 tok/s do colibri hoje. As respostas não podem mudar: em cada
passo, os tokens (modo determinístico) saem idênticos aos da referência do
mesmo formato.

## Antes de começar (no PC)

- **Linux nativo** (outro SSD ou dual boot). No colibri, WSL2 com disco virtual
  mediu ~2 a 3 GB/s de leitura; nativo, ~6 a 7.
- **CUDA 12.8 ou mais nova** (a 5070 é Blackwell).
- **~260 GB livres no SSD:** 186 GB do modelo em FP8 e 68 GB dos especialistas
  em int4.
- **SSD no slot M.2 ligado direto à CPU** (em geral o M2_1; confira no manual
  da placa), não num do chipset.
- **Placa de vídeo em PCIe 5.0 x16:** `nvidia-smi -q | grep -A4 "Link Width"`.
- Fechar o resto durante as medições: são só 32 GB de RAM.

## Etapas

- [ ] **0. Medir os links do PC.** Compilar o `iobench` do colibri
  (`gcc -O2 -fopenmp c/iobench.c -o iobench`) e ler um arquivo do modelo com blocos
  do tamanho de um especialista, leitura direta, 8 threads:
  `./iobench <arquivo .safetensors> 2.6 64 8 1` e `... 4.7 64 8 1`. PCIe: o
  `nvbandwidth` da NVIDIA (cópia de memória fixa para a GPU). Pronto: as duas
  bandas anotadas e o orçamento refeito com elas.
- [ ] **1. Linha de base: o colibri como está.** Baixar o modelo na revisão fixa
  (`docs/qwen38.md` do colibri), compilar o `qwen38` com CUDA, gerar o int4
  (`tools/convert_qwen38_experts_int4.py`). Rodar o melhor que ele tem hoje, nas
  duas formas: GPU com FP8 (cache de VRAM, tronco na GPU, `Q38_DN_GPU=1`,
  `DIRECT=1`, tamanho de cache pelo `coli plan`) e CPU com int4. Medir com
  `tools/datapoint.py` (frio, morno e prompts em rodízio) e `COLI_TIMERS=1` (onde
  vai o tempo). Gravar os tokens de referência de cada formato. Pronto: tok/s de
  antes, a divisão do tempo e as referências gravadas.
- [ ] **2. Localidade no PC.** Com o rastro de roteamento do colibri, medir
  quantas chamadas cada tamanho de cache atende (32, 64, 128 e 256 vagas por
  camada) numa conversa longa e com troca de assunto. Pronto: a curva medida e o
  teto refeito com ela (o estudo extrapolou 95 % a partir dos 90 % de 128 vagas).
- [ ] **3. O motor que põe a GPU primeiro.** Uma mudança por vez, cada uma medida
  contra a anterior, com os tokens idênticos à referência:
  1. a GPU calcula todos os especialistas: falta na VRAM vem da RAM por DMA, em
     lote por camada; a CPU não calcula especialista nenhum;
  2. leitura do SSD em fila profunda, direto para memória fixa, sem a cópia da
     cache de páginas (hoje ~1,5 GB/s);
  3. a camada inteira na GPU: os valores intermediários ficam lá, sem ida e
     volta por matriz (hoje uma por matriz, 553 matrizes);
  4. especialistas em int4 na GPU: o dobro cabe na VRAM e cada link carrega a
     metade (referência própria do int4);
  5. o roteador da camada seguinte adianta as leituras, e o MTP liga quando o
     acerto da cache passar de ~90 %.

  Pronto: tok/s de cada passo; alvo de ~25 a 40 tok/s.
- [ ] **4. Resultado publicado.** Um JSON pequeno por máquina e um relatório
  gerado por script, com o medido ao lado da conta. Pronto: relatório no
  repositório.

## Decisões (a tomar com o dono)

- **Base do motor:** um fork do colibri (Apache 2.0; o `qwen38.c` e o tier de
  CUDA já existem e conferem tudo contra a referência) ou código próprio.
  Recomendação: o fork, porque o modelo é complexo (DeltaNet, atenção esparsa,
  hiperconexões, tabela de n-gramas, MTP).
- **Como o código chega ao PC:** o dono roda os comandos e cola o resultado, ou
  liga o PC à sessão pelo Remote Control.

## Histórico

- 2026-10-30 — Plano aberto a pedido do dono ("quero fazer um teste em casa para
  tentar chegar nessa velocidade"), a partir do estudo dos gargalos.
