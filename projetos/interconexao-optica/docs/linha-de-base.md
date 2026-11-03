# Linha de base: sistema atual

Gerado por `python3 -m modulos.sistema.linha_de_base`. Não edite à mão.

Montagem: `montagem.json` (chave `rele_mems`, tradutores `sob_peca`, cobre de 2 oz).

| Medida | Valor |
|---|---|
| Erros do verificador | 0 |
| Avisos do verificador | 58 |
| Boot emulado ficou pronto | sim |
| Tempo do boot emulado | 541 ms |
| Consumo da interconexão | 166.1 W |
| Energia por bit | 11.2 pJ/bit (referência elétrica 6.3) |
| Banda da interconexão | 14.77 Tb/s |
| Temperatura máxima da base | 67.6 °C |
| Teto do LLM 70B em 4 bits (40 GB), banco unificado | 38.5 tok/s |
| Teto do mesmo LLM, PC comum (offload na CPU) | 4.5 tok/s |
| Capacidade do banco unificado | 48 GB |
| Banda do banco para a GPU | 1536 GB/s |
| Banda do banco para a CPU | 38.4 GB/s |

## Verificador por regra

| Regra | Erros | Avisos |
|---|---|---|
| R01-caminho | 0 | 0 |
| R02-sentido | 0 | 0 |
| R03-padrao | 0 | 0 |
| R04-banda | 0 | 0 |
| R05-optico | 0 | 0 |
| R06-energia | 0 | 0 |
| R07-controle | 0 | 0 |
| R08-capacidade | 0 | 0 |
| R09-tempo | 0 | 0 |
| R10-relogio | 0 | 0 |
| R11-requisito | 0 | 0 |
| R12-orfao | 0 | 0 |
| R13-temperatura | 0 | 57 |
| R14-consumo | 0 | 1 |
| R15-decodificacao | 0 | 0 |
| R16-ajuste | 0 | 0 |
| R17-pcie | 0 | 0 |
| R18-memoria-compartilhada | 0 | 0 |
| R19-posse | 0 | 0 |
| R20-banco | 0 | 0 |
