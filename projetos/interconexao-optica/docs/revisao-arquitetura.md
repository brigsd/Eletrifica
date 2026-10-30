# Revisão da arquitetura (2026-10-30)

Perguntas do dono sobre o projeto como um todo, respondidas com o que o modelo
atual mostra. Escrita à mão, como o `viabilidade.md`; os números vêm de
[`resultados.md`](resultados.md), que é gerado.

## 1. A fibra óptica funciona aqui? Do jeito que está?

Funciona na física; não do jeito que está.

- O custo está na conversão, não no caminho: tradutores ~88 W e lasers ~48 W
  são quase todo o consumo da base (~166 W, ~11 pJ/bit contra ~6 de uma
  ligação elétrica).
- Em salto curto (1 a 6 cm, GPU até os chips GDDR7) o cobre faz o mesmo com
  menos energia; é o que toda placa de vídeo faz.
- A luz se paga em distância longa (mais de ~10 cm) e onde evita carga
  elétrica (vários chips num canal, como o par do banco unificado).
- Fibra solta (180 fibras no 3D) é o pior jeito: dentro da placa a luz deveria
  andar em guias embutidos.

## 2. Trilhos de vidro ou cristal: um caminho mais otimizado?

- Guias de luz embutidos em vidro existem (vidro com troca iônica; substratos
  de núcleo de vidro anunciados pela Intel para encapsulamento).
- Não aceleram a informação: no vidro a luz anda ~5 ps/mm, igual à fibra; no
  cobre o sinal anda ~6 a 7 ps/mm. Em 6 cm a diferença é ~0,1 ns. A latência
  vem da conversão e da lógica, não do meio.
- O ganho é outro: sem fibras soltas, densidade e alinhamento fixos, e o vidro
  aguenta melhor o calor que o LCP. Nenhum material conhecido "acelera" a
  informação de forma útil (cristal fotônico desacelera a luz).

## 3. A matéria-prima da base é a certa?

O LCP serve bem ao sinal elétrico (perde pouco) e mal ao calor (~0,3 W/m·K):
foi por isso que precisamos de placa fria e vias térmicas.

| Material | Calor (W/m·K) | Guia de luz embutido | Observação |
|---|---|---|---|
| LCP (atual) | ~0,3 | não | barato e flexível; segura o calor |
| Núcleo de vidro | ~1 | sim | plano, vias através do vidro; meio-termo |
| Cerâmica AlN | ~150 ou mais | não | resolve o calor; cara e rígida |

Combinação sugerida: núcleo de vidro (luz por dentro, cobre por cima) e
cerâmica só sob as peças quentes.

## 4. Onde estamos complicando à toa

- **Célula chaveada (relé MEMS) em cada ponto de 0,4 mm.** É a maior
  complicação e o bloqueio nº 1. Mais simples: cada peça comum vai num
  **adaptador** (soquete LGA1700 de verdade para a CPU, adaptador para os BGA)
  que apresenta à base uma grade padrão com energia, terra e sinal em lugares
  fixos. A base vira um "pegboard": qualquer posição, em passos de alguns
  milímetros, sem chave por célula.
- **Copiar cada pino de DDR5 e GDDR7 pela luz.** É o bloqueio nº 2, sem
  evidência. Onde houver luz, terminar o protocolo na borda (como a ponte do
  banco já faz) e mandar pacotes em menos canais rápidos.
- **Lasers sempre acesos nos caminhos da ponte.** Desligar o caminho de quem
  não é dono do rank.

## 5. O socket da CPU funcionaria na prática?

Não do jeito que está. O modelo cobre a geometria dos contatos (elastômero,
células, corrente por pino) e deixa de fora a mecânica: força por contato que
o LGA exige, placa de pressão, empenamento conhecido do LGA1700 e planicidade
da base sob carga. Com o adaptador do item 4, a CPU usa o soquete LGA1700 real,
que já é provado.

## Proposta

Base em núcleo de vidro, luz embutida só para distância longa, cobre para o
curto, peças em adaptadores sobre grade padrão, banco unificado mantido. Tira os
dois maiores bloqueios do `viabilidade.md` e mantém o centro do projeto
(memória compartilhada; qualquer posição, em passos). A modelagem dessa versão
ao lado da atual é a etapa 10 do plano ativo em `planos/`.
