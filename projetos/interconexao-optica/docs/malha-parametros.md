# Parâmetros da malha (minhoca)

Pesquisa feita em 2026-11-05. A fonte dos números é `../malha.json`; este
documento mostra a faixa encontrada, o valor escolhido e de onde veio.

Classificação:

- **datasheet** — número publicado pelo fabricante;
- **spec** — número de norma ou artigo;
- **derivado** — conta nossa sobre números de fonte;
- **estimativa** — sem fonte; é chute informado e deve ser medido.

## Tabela

| Parâmetro | Faixa encontrada | Escolhido | Tipo | Fonte |
|---|---|---|---|---|
| `passo_mm` | UCIe de pacote padrão: até 25 mm | 25 | decisão | [Tom's Hardware](https://www.tomshardware.com/news/new-ucie-chiplet-standard-supported-by-intel-amd-and-arm) |
| `retemporizacao_ns` (por salto) | retimer PCIe 5 em baixa latência: <5 (Phison), ~10 (Kandou, Microchip); modo normal: 64 típico; UCIe TX+RX: <2 | **5,0** (otimista 2,0) | datasheet | [Phison PS7201](https://www.phison.com/images/products_datasheet/redriver/Public_PS7201_PCIe_Gen5_Retimer_IC_Datasheet_v3.9.pdf), [Synopsys UCIe](https://www.synopsys.com/designware-ip/technical-bulletin/ucie-multi-die-socs.html) |
| `pj_por_bit_salto` | UCIe 0,25–0,6; retimer PCIe 5 ~2,2–4,5 | **3,0** | estimativa | [seekcomp](https://www.seekcomp.com/article/bGpxLTkwNjU=) (terceiros, 2,3 W/x16), UCIe acima |
| `ps_por_mm` | FR4 6,9–7,2; baixa perda 6,1–6,2 | FR4 6,9; Megtron 6/7 6,2 | derivado | [Intel](https://intel.com/content/www/us/en/docs/programmable/683073/current/determine-the-delay.html) (182 e 156 ps/pol) |
| `perda_db_por_mm` FR4 (16 GHz) | 0,051 (TI) a 0,079 (Intel, 14 GHz, 5 mil) | **0,060** | datasheet/modelo | [TI](https://ti.com/document-viewer/lit/html/SNLA426/GUID-ECB0A154-6208-45B4-BADE-2C989C251EB3), [Intel](https://intel.com/content/www/us/en/docs/programmable/683132/current/pcb-stackup-selection-guideline.html) |
| `perda_db_por_mm` Megtron 6 | 0,013 (TI) a 0,033 (Intel) | **0,020** | datasheet/modelo | idem |
| `perda_db_por_mm` Megtron 7 | sem valor a 16 GHz; ~0,025 a 12,5 GHz (2014) | **0,015** | estimativa | [EE Times Japan](https://eetimes.itmedia.co.jp/ee/spv/1406/06/news044.html); o gráfico do datasheet não deu texto |
| `fator_perda_gddr7_pam3` | Nyquist do PAM3 ~10,7 GHz | 0,7 da perda a 16 GHz | estimativa | conta de frequência |
| Orçamento de perda PCIe 5 | 36 dB a 16 GHz (placa 16, CEM 1,5, cartão 9,5, raiz 9) | 36; margem 10–20 % | spec | [Astera Labs](https://www.asteralabs.com/?p=18375) |
| Orçamento de perda GDDR7 / DDR5 | não publicado (JESD239 e JESD79-5 fechados) | nulo | — | — |
| `trilhas_por_mm_por_camada` | 5/5 mil acoplado; 3W = 15 mil entre pares | 2,6 single-ended; 1,3 pares | derivado | [AtlasPCB](https://www.atlaspcb.com/blog/differential-pair-routing-tight-vs-loose-coupling/), [AllPCB](https://www.allpcb.com/blog/pcb-design/differential-pair-routing-techniques.html) (blogs) |
| `camadas_sinal` | breakout em 3–4 camadas | 4 | estimativa | [rfessentials](https://rfessentials.com/rf-knowledge-base/how-do-i-design-the-breakout-region-from-a-bga-to-pcb-traces-for-a-high-speed-fp/) |
| `faixas_por_ligacao` | — | **32 por sentido** | derivado | 25 mm × 1,3 × 4 × 0,5 aproveitamento = 65 pares, dois sentidos |
| `gbps_por_faixa` | PCIe 5: 32 GT/s NRZ; GDDR7: 32 Gb/s PAM3 | 32 | spec | [Electronic Design](https://electronicdesign.com/technologies/communications/article/21267698/astera-labs-how-to-manage-the-pcie-50-channel-insertion-loss-budget), [JEDEC](https://www.jedec.org/node/9394) |
| `orcamento_ns` DDR5 (ida) | registrador de CL: 22–66; projeto: CL38 | **5,8** (11,7 ida e volta) | derivado | [AnandTech](https://www.anandtech.com/show/16143) |
| `orcamento_ns` PCIe 5/4 (ida) | 64 ns por retimer, até 2 | **128** | spec | [Phison](https://www.phison.com/retimer-ic/) |
| `orcamento_ns` GDDR7 (ida) | faixa de RL não achada | **5,0** (10 ida e volta) | estimativa | sem fonte |
| `skew_max_ps` (residual após treino) | — | GDDR7 4,7; DDR5 20,8; PCIe5 9,4; PCIe4 18,75 | estimativa | convenção 10 %/30 % UI de `protocolos.py` |
| `skew_treinavel_ps` DDR5 | nivelamento de escrita: DQS a −0,5 tCK do CK | 208 ps | spec (via patente) | [Justia](https://patents.justia.com/patent/20190235760) |

## O que a pesquisa não achou

- **RL da GDDR7 e skew absorvido pelo treino**: JESD239 é fechado e os
  datasheets (Micron, Samsung) não saíram na busca. O orçamento da GDDR7 e os
  skews da GDDR7/PCIe continuam estimativa. Próximo passo: datasheet de GDDR7
  sob NDA ou o artigo ISSCC 2024.
- **Faixa de atraso por bit das PHYs**: é decisão de implementação, não de norma.
- **Perda de canal da GDDR7**: nenhuma fonte pública.
- **Energia por bit de retimer**: nenhum fabricante publica pJ/bit; o 3,0 vem
  de uma potência de terceiros (2,3 W para x16 Gen5, dividida por 512 Gb/s).
- **Redriver (sem retemporização)**: não achei latência de datasheet.

## Leitura

- O orçamento é o atraso **extra de ida**. Como o comando vai e o dado volta,
  o controlador vê o dobro; por isso o DDR5 aceita 5,8 ns de ida.
- Um salto custa ~5,2 ns (5 de retemporização + 0,16 de cobre em 25 mm de
  Megtron 6). Com 5 ns de orçamento, **a GDDR7 só aceita um salto**, e o DDR5
  também. Só o PCIe passa dos 7 saltos. Para a memória fechar na minhoca, o
  tradutor precisa chegar perto do UCIe (~2 ns) ou a rota precisa de menos saltos.
- O cobre em si não é problema: 25 mm custam 0,5 dB em Megtron 6 e 1,5 dB em
  FR4 a 16 GHz, longe dos 16 dB da placa-base de PCIe 5. A retemporização por
  salto zera a perda a cada segmento.
- A borda de 25 mm dá ~65 pares por camada-conjunto; a ligação com 64 faixas
  só cabe se for um sentido só ou com aproveitamento de 100 %.
