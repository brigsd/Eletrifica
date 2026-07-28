# Netlist da placa

Extraida de `gerber/FlyingProbeTesting.json`, que traz o net de cada pad.
Os nets `$1N1790`, `$1N1796` e `$1N2332` nao tem nome no arquivo original;
foram renomeados para `GATE_Q1`, `SRC_Q1` e `LED_A`.

| Net | Pinos | Ligacoes |
|-----|-------|----------|
| `GND` | 21 | C1.2, C14.2, C15.2, C2.2, C3.2, C4.2, D8.2, DRV1.10, DRV1.16, DRV1.5, DRV1.6, DRV1.7, DRV2.10, DRV2.16, DRV2.5, DRV2.6, DRV2.7, J1.2, U1.14, U1.17, U2.2 |
| `+12V` | 10 | C1.1, C14.1, C15.1, C2.1, C3.1, DRV1.9, DRV2.9, J1.1, R3.2, U2.1 |
| `+3V3` | 7 | DRV1.15, DRV1.3, DRV1.4, DRV2.15, DRV2.3, DRV2.4, U1.16 |
| `+5V` | 4 | C4.1, CN1.2, U1.15, U2.3 |
| `EN` | 3 | DRV1.8, DRV2.8, U1.10 |
| `GATE_Q1` | 3 | Q1.1, R1.2, R2.1 |
| `1A` | 2 | DRV1.13, M1.2 |
| `1A_2` | 2 | DRV2.13, M2.2 |
| `1B` | 2 | DRV1.14, M1.1 |
| `1B_2` | 2 | DRV2.14, M2.1 |
| `2A` | 2 | DRV1.12, M1.3 |
| `2A_2` | 2 | DRV2.12, M2.3 |
| `2B` | 2 | DRV1.11, M1.4 |
| `2B_2` | 2 | DRV2.11, M2.4 |
| `D13` | 2 | R2.2, U1.13 |
| `DIR` | 2 | DRV1.1, U1.9 |
| `DIR_2` | 2 | DRV2.1, U1.7 |
| `LASER_NEG` | 2 | CN1.1, Q1.2 |
| `LED_A` | 2 | D8.1, R3.1 |
| `SRC_Q1` | 2 | Q1.3, R1.1 |
| `STEP` | 2 | DRV1.2, U1.8 |
| `STEP_2` | 2 | DRV2.2, U1.12 |

Pinos do ESP32 sem ligacao: 20 de 30.

