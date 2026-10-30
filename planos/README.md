# Planos

Contrato de como o projeto planeja trabalho grande. Vale para pessoas e agentes.

## Regras

1. **Um plano ativo por vez.** Ele fica aqui, na raiz de `planos/`, com o nome
   `AAAA-MM-DD-assunto.md` (data em que foi aberto).
2. **Nada se apaga.** Quando o plano sai de ativo, o arquivo é **movido** (não
   copiado, não reescrito) para uma das três pastas:

   | Pasta | Quando |
   |---|---|
   | `concluidos/` | todas as etapas feitas e verificadas |
   | `encerrados/` | parado no meio: parte feita, o resto não vai seguir |
   | `cancelados/` | abandonado antes de produzir resultado |

3. Antes de mover, escreva no fim do plano uma seção **Desfecho**: data, o que
   foi feito (commits), o que ficou e por quê.
4. Abrir um plano novo exige que o anterior já tenha saído da raiz.
5. Durante o plano, marque cada etapa (`[ ]`, `[x]`) e registre decisões do dono
   com data. Mudança de rumo vira uma linha em **Histórico**, não reescrita.

## Formato do plano

```
# Título
Aberto em: AAAA-MM-DD · Responsável: ...
## Objetivo
## Etapas        (lista com [ ] / [x], cada uma com critério de pronto)
## Decisões      (do dono, com data)
## Histórico
## Desfecho      (só ao sair da raiz)
```
