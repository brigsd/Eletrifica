# Contato imperfeito

Gerado por `python3 -m modulos.sistema.levantamento_defeitos`. Não edite à mão.

Cada defeito altera a verdade física antes da sondagem (`modulos/sistema/defeitos.py`); a base só vê o que a sondagem devolve. Peça **recusada** ou **desconhecida** não ganha nenhuma célula ligada; **degradada** liga com menos folga de corrente.

| Defeito | Identificou | Veredito | Motivo |
|---|---|---|---|
| nenhum | i5-13600KF | CPU: ok | — |
| 5% do VCCIN sem contato | i5-13600KF | CPU: degradado | — |
| 20% do VCCIN sem contato | i5-13600KF | CPU: recusada | energia sem folga: VCCIN perdeu 75 de 376 pinos |
| 1 sinal (PWROK) sem contato | i5-13600KF | CPU: recusada | sinal sem contato na interface AUX: PWROK |
| inclinada 0,1° (canto levantado) | i5-13600KF | CPU: ok | — |
| inclinada 0,2° (canto levantado) | i5-13600KF | CPU: degradado | — |
| inclinada 0,5° (canto levantado) | i5-13600KF | CPU: recusada | energia sem folga: VCC1P8 perdeu 14 de 20 pinos / energia sem folga: VCCIN perdeu 102 de 376 pinos |
| partícula condutiva entre sinal e terra | i5-13600KF | CPU: recusada | ponte entre redes: CPU.DDR5_A_B_CA2, CPU.VSS |
| pino torto 0,1 mm | i5-13600KF | CPU: ok | — |
| pino torto 0,45 mm | i5-13600KF | CPU: recusada | contato fora do lugar: células sob uma rede respondem por outra (CPU.VCCIN, CPU.VSS) |
| peça fora do catálogo ao lado | desconhecida, i5-13600KF | CPU: ok; 1 desconhecida(s), nada ligado | — |
| metade da CPU fora da base | i5-13600KF | CPU: recusada | energia sem folga: VDD2 perdeu 46 de 124 pinos / sinal sem contato na interface AUX: SVID_CLK, SVID_DATA, SVID_ALERT, PWROK |
| duas GDDR7 com corpos encostados | GDDR7, GDDR7 | MEM0: ok; MEM1: ok | — |
| duas GDDR7 com pinos a 0,45 mm | GDDR7, GDDR7 | MEM1: recusada; MEM0: recusada | ponte entre redes: MEM1.GX_DQ8, MEM1.VSS, MEM0.GX_DQ8, MEM0.VSS / ponte entre redes: MEM1.VDDQ, MEM0.GX_CA4 |
