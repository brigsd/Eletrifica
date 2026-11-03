# Ponto perfeito: a placa própria, melhoria por melhoria

Aberto em: 2026-11-03 · Responsável: Claude (sessões e subagentes)

## Objetivo

Achar a melhor combinação para a nossa placa (CPU, GPU, RAM e SSD continuam
peças comuns): mais banda e capacidade de memória para a GPU, passando em todas
as regras do verificador e no `viabilidade.md`. Método: juntar melhorias uma por
vez; o que virar restrição é analisado e resolvido, nem que seja trocando o
conjunto que resolvia parte do problema.

Ponto de partida: o banco unificado (0 erros, boot ~540 ms, 70B em 4 bits com
teto de ~38 tok/s). Restrições conhecidas: célula chaveada (o relé não existe),
GDDR7 por luz (sem evidência), calor (~149 W na base), plataforma Intel.

## Método (dono, 2026-11-03)

Quando algo resolve um problema mas cria outro:
1. **Algo parecido ou melhor resolve isso?** Procurar alternativas conhecidas.
2. **Se não:** como melhorar ou adaptar o que temos?

Cada ciclo vira uma linha no Histórico: o problema, as alternativas, a escolha.

## 1º vetor: minhoca

| Minhoca | Placa | Ataca |
|---|---|---|
| segmentos iguais, cada um com seu gânglio | módulos iguais, cada um com tradutor e controle local | FPGA central e fiação longa |
| peristaltismo: onda empurra de segmento em segmento | dados de vizinho em vizinho, ligações curtas de cobre, rota decidida no tradutor | a célula chaveada |
| respira pela pele inteira | calor espalhado por todos os segmentos | calor concentrado |

Parentes conhecidos: arrays sistólicos e redes em malha dentro de chips. Não
achamos isso usado como placa-mãe de peças comuns.

## O que o simulador valida hoje e o que falta

Valida: netlist salto a salto, atraso por caminho (R09), banda por canal (R04),
energia, temperatura 2D, consumo, protocolo bit a bit, boot.

Falta para a minhoca:
- topologia em malha de segmentos com rota de vários saltos (hoje só ligação
  direta tradutor → destino);
- atraso e energia **por salto** (cada segmento retransmite), e se o atraso
  total cabe no CL/RL e continua determinístico para o treino da memória;
- **tráfego**: vários fluxos dividindo as mesmas ligações (ocupação, fila,
  congestionamento), que hoje não existe;
- regras novas no verificador para isso.

## Etapas

- [ ] **0. Linha de base.** Rodar o simulador atual e registrar os números de
  referência (tok/s, erros, consumo, temperatura, boot). Pronto: tabela gerada por
  script.
- [ ] **1. Simulador de malha.** Módulo novo (topologia de segmentos, rota de
  vários saltos, atraso/energia por salto, simulador de tráfego por fluxo),
  integrado ao `construir.py` para o verificador enxergar os saltos; regras novas
  (atraso determinístico dentro do CL/RL; ocupação de cada ligação ≤ capacidade).
  Pronto: testes no pytest, incluindo casos que devem falhar.
- [ ] **2. Minhoca no simulador.** Montagem com segmentos no lugar das células
  chaveadas, lado a lado com a atual. Pronto: relatório com as duas versões e as
  restrições que aparecerem.
- [ ] **3. Ciclos de restrição.** Cada restrição vira uma linha no Histórico:
  análise, opção escolhida, efeito medido.
- [ ] **4. Próximas melhorias**, uma por vez: cobre curto e luz longa (revisão da
  arquitetura), banco de pentes DDR5, o que mais aparecer.

## Decisões

- 2026-11-03 — Dono: este plano ativo; o teste em casa cancelado. Primeiro vetor:
  a minhoca. Precisamos de testes; se o simulador não valida, melhorá-lo.

## Histórico

- 2026-11-03 — Plano aberto.
- 2026-11-03 — Ciclo 1, problema: a minhoca leva os dados entre segmentos, mas a
  peça cai em qualquer posição e algo precisa ligar cada pino ao fio certo.
  Alternativas: adaptador em grade (existe, mas a posição fica presa à grade);
  conector que só conduz na vertical (resolve o contato, não diz qual pino é qual);
  chave eletrônica dentro do tradutor (serve para sinal, não aguenta 1 A de
  energia). Adaptação proposta: dividir por função, energia por zonas fixas e
  sinal pela chave eletrônica do tradutor. A medir no simulador.
