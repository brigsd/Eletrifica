# Sensibilidade

Gerado por `python3 -m modulos.conexoes.sensibilidade`. Não edite à mão.

Para cada número escolhido no projeto, o valor em que o projeto atual passa a reprovar e a regra que quebra. Folga abaixo de 20 % em negrito.

| Parâmetro | Atual | Reprova em | Folga | Quebra |
|---|---|---|---|---|
| vias por chip | 96 | 77 | 25 % | R04-banda |
| perda da trilha (dB/mm/GHz) | 0,004 | 0,00517 | 29,35 % | R04-banda |
| orçamento de trilha GDDR7 (dB) | 4 | 3,09 | 29,35 % | R04-banda |
| Q do anel, para baixo | 6000 | 4534 | 32,33 % | margem óptica |
| perdas passivas (dB) | 7,50 | 10,39 | 38,50 % | margem óptica |
| lado do chip (mm) | 10 | 14,01 | 40,09 % | R04-banda |
| atraso máximo GDDR7 (ps) | 1000 | 598 | 67,09 % | R09-tempo |
| Q do anel, para cima | 6000 | 10968 | 82,80 % | anel irrealizável |
| eficiência do anel (pm/V) | 40 | 21,11 | 89,50 % | margem óptica |
| potência do laser (mW) | 10 | 5,18 | 92,94 % | margem óptica |
| ruído do TIA (pA/√Hz) | 15 | 30,77 | 105 % | margem óptica |
| R_on do relé (Ω), para baixo | 0,05 | 0,022 | 127 % | R06-energia |
| C_off do relé (fF) | 20 | 58,50 | 192 % | R04-banda |
| orçamento de trilha PCIe5 (dB) | 8 | 2,20 | 263 % | R04-banda |
| pJ/bit de transmissão | 1,50 | não reprova até ×100 | > 9900 % | — |
| pJ/bit de recepção | 1,50 | não reprova até ×100 | > 9900 % | — |
| R_on do relé (Ω), para cima | 0,05 | não reprova até ×100 | > 9900 % | — |
