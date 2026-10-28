# Sensibilidade

Gerado por `python3 -m modulos.conexoes.sensibilidade`. Não edite à mão.

Para cada número escolhido no projeto, o valor em que o projeto atual passa a reprovar e a regra que quebra. Folga abaixo de 20 % em negrito.

| Parâmetro | Atual | Reprova em | Folga | Quebra |
|---|---|---|---|---|
| lado do chip (mm) | 10 | 10,87 | **8,73 %** | R04-banda |
| Q do anel, para baixo | 6000 | 5325 | **12,67 %** | margem óptica |
| perdas passivas (dB) | 7,50 | 8,79 | **17,26 %** | margem óptica |
| vias por chip | 96 | 77 | 25 % | R04-banda, R12-orfao |
| perda da trilha (dB/mm/GHz) | 0,004 | 0,00506 | 26,43 % | R04-banda |
| orçamento de trilha GDDR7 (dB) | 4 | 3,16 | 26,43 % | R04-banda |
| eficiência do anel (pm/V) | 25 | 19,55 | 27,88 % | margem óptica |
| potência do laser (mW) | 10 | 7,39 | 35,38 % | margem óptica |
| ruído do TIA (pA/√Hz) | 15 | 20,77 | 38,50 % | margem óptica |
| atraso máximo GDDR7 (ps) | 1000 | 674 | 48,30 % | R09-tempo |
| Q do anel, para cima | 6000 | 10968 | 82,80 % | anel irrealizável |
| pJ/bit de transmissão | 2,50 | 5,26 | 110 % | R13-temperatura |
| pJ/bit de recepção | 2,50 | 5,26 | 110 % | R13-temperatura |
| R_on do relé (Ω), para baixo | 0,05 | 0,022 | 127 % | R06-energia |
| C_off do relé (fF) | 20 | 58,50 | 192 % | R04-banda |
| orçamento de trilha PCIe5 (dB) | 8 | 2,20 | 263 % | R04-banda |
| R_on do relé (Ω), para cima | 0,05 | 0,994 | 1887 % | R13-temperatura |
