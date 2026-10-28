# Viabilidade prática

O simulador mostra que o projeto é **coerente com as próprias premissas**. Este
documento confere se cada premissa **existe no mundo real**, com fonte.
Pesquisa feita em 2026-10-28.

Classificação de cada premissa:

- **à venda** — produto comercial com datasheet;
- **demonstrado** — artigo ou protótipo publicado;
- **sem evidência** — nada encontrado;
- **bloqueio comercial** — a tecnologia existe, mas o acesso a ela é restrito.

## Veredito

A física fecha; **três coisas não existem hoje**:

1. **A célula chaveada.** Não há chave que leve 1 A de energia e tenha ~20 fF
   desligada num passo de 0,4 mm. O relé MEMS mais próximo é ~150× maior, e a
   base precisaria de ~480 mil deles. As matrizes reconfiguráveis que existem
   (Aptix, Pickering) só chaveiam sinal lento.
2. **DDR5 e GDDR7 por óptica linear.** Nada real copia o sinal de memória para a
   luz: todos os sistemas ópticos de memória (Celestial AI, Ayar Labs) terminam
   o protocolo e usam o seu próprio. A GDDR7 longe da GPU exigiria um
   controlador de memória novo, feito pelo fabricante da GPU.
3. **Acesso à plataforma Intel.** Datasheets, pinagem, firmware ME e BIOS do
   B760 + i5-13600KF ficam restritos a parceiros OEM da Intel.

O que já é maduro: PCIe por óptica linear, placa fria, pentes de laser com 16 λ,
escala de dezenas de chips fotônicos num só sistema e o teste de contato por
sondagem.

## Premissa por premissa

### Base, contato e energia

| Premissa | Status | Melhor exemplo real | Distância | Risco |
|---|---|---|---|---|
| Elastômero com 1 A por contato, passo de 0,8/0,7 mm | à venda para sinal; 1 A não confirmado | Fujipoly Zebra: 250–500 mA por fio. LGA da TE: 0,5 A por contato. Socket com mola (Invisipin): 1–4 A. Borracha precisa de 0,1–0,25 mm de curso | ~2× a corrente dos elastoméricos publicados | médio |
| Relé MEMS por célula: 0,4 mm, 50 mΩ, 20 fF, 1 A | **sem evidência** nessa densidade | Menlo MM9200: 10 A, 10 mΩ, em 5×5 mm. ADI ADGM1121: 3 Ω, 200 mA, ~1,6 pF desligado | ~150× mais denso, C_off ~80× menor, 480 mil unidades | **alto** |
| Soquete universal reconfigurável | demonstrado / à venda, só sinal lento | Aptix (936 pinos programáveis); Pickering (4.096 pontos a 1 A, relés reed) | nada a 32 Gb/s nem a 200 A | alto |
| LCP multicamada com fotônica embutida e vias térmicas | demonstrado em partes | fotônica de silício embutida em substrato orgânico a 112 Gb/s; ativos embutidos em LCP; LCP estável até ~125 °C | nunca juntos, nem em 320×240 mm | médio-alto |
| Placa fria sob a base | à venda | placas frias passam de dezenas de milhares de W/m²K do lado do líquido | sobra; o gargalo é atravessar a base | baixo |
| 200 A da CPU por células chaveadas | sem evidência | 0,53 A médios por pino batem com o 0,5 A do LGA real | depende da célula | alto |
| Sondagem que identifica a peça | teste de contato demonstrado; identificação sem evidência | ATE já testa aberto/curto pelos diodos de proteção | casar com um catálogo é software | baixo-médio |

### Fotônica e laser

| Premissa | Status | Melhor exemplo real | Distância | Risco |
|---|---|---|---|---|
| Anel 5 µm, Q 6000, 40 pm/V, 32 Gb/s NRZ e PAM3, travamento em 200 µs | demonstrado | anel a 32 Gb/s NRZ com 0,43 Vpp; aquecedores de 0,04 a 0,95 nm/mW; travamento em 200 µs | **40 pm/V é otimista**: o típico é ~25 (ver correções). PAM3 em anel: sem evidência específica | médio |
| 16 λ por fibra a ~0,8 nm, 10 mW para cada 4 canais | à venda / demonstrado | Ayar SuperNova: 16 λ (CW-WDM MSA). Sivers: >65 mW por canal a 400 GHz. Intel OCI: 8 λ a 200 GHz | potência e número de λ ok; **~140 GHz é mais denso** que os 200–400 GHz demonstrados | médio |
| Chip com 96 vias em 10×10 mm, 1,5 pJ/bit por lado, cópia linear | demonstrado em parte | Ayar TeraPHY: 8 Tbps por chiplet, ~5 pJ/bit. Intel OCI: 4 Tbps, 5 pJ/bit. Óptica linear (LPO): ~50 % menos energia que com DSP | densidade ok; energia ~1,7× otimista; **cópia linear de qualquer protocolo de pino: nenhum produto** | médio-alto |
| PCIe 5 por óptica linear | à venda / demonstrado | redriver linear Gen5 da TI (detecção de receptor e treino transparentes); PCIe 5 a 25 m por óptica (Anritsu/Kyocera); PCIe 7 sem retimer por óptica linear | pequena | **baixo** |
| DDR5 e GDDR7 por óptica linear | **sem evidência** | só patentes; os sistemas ópticos de memória terminam o protocolo (Celestial AI: 120–300 ns) | bidirecional, com terminação dinâmica, por luz linear: nada | **alto** |
| 34 chips e ~2.500 anéis numa base | escala demonstrada | Lightmatter M1000: 34 chips, 1.024 SerDes, 256 fibras | comparável, mas num interposer rígido; atraso de enlace linear sem número publicado | médio |

### Plataforma e protocolos

| Premissa | Status | Melhor exemplo real | Distância | Risco |
|---|---|---|---|---|
| B760 + i5-13600KF numa placa própria | **bloqueio comercial** | documentação sob contrato de confidencialidade com a Intel; kit do ME restrito a OEMs; o mais perto de um não-OEM é o coreboot da Dasharo numa placa da MSI | precisa ser parceiro OEM da Intel | **alto** |
| Dispositivo no meio da DDR5 (sentido e espelho de terminação) | parecido à venda; com óptica, sem evidência | LRDIMM/MRDIMM: o RCD comanda os buffers de dados por barramento lateral (Micron 256 GB DDR5-8800) | os precedentes são padrão JEDEC dentro do módulo, com BIOS de servidor | médio-alto |
| GPU com a GDDR7 a alguns cm, por óptica | **sem evidência** | a GDDR7 fica colada à GPU por integridade de sinal | exige um controlador de memória novo, do fabricante da GPU | **alto** |
| Memória compartilhada via CXL | inexistente em desktop | CXL só em servidor (Sapphire Rapids); expansores CXL medidos com 214–394 ns e 18–52 GB/s | exige trocar a CPU | alto |
| ReBAR | à venda | a CPU acessando a VRAM: uma fonte cita ~1.200 ns | o simulador usa ~800 ns (otimista) | baixo |

## Correções que a pesquisa trouxe para o modelo

As tabelas acima avaliam as premissas como estavam. Todas as correções abaixo já
foram aplicadas ao modelo (2026-10-28); o efeito é o medido depois de rodar de novo.

| Premissa no modelo | Valor real | Efeito |
|---|---|---|
| LCP aguenta 200 °C | ~125 °C | limite corrigido em `modulos/componentes/limites.py`; a base fica em ~67 °C, então nada reprova |
| anel com 40 pm/V | ~25 pm/V típico | junto com o anel menor abaixo, a margem em PAM3 cai de +2,9 dB para **+1,3 dB**; ainda fecha. Com 1 laser para cada 2 canais iria a +4,3 dB, com o dobro de potência de laser |
| 1,5 pJ/bit por lado | ~2,5 pJ/bit (5 pJ/bit no enlace) | tradutores de ~51 W para ~81 W. A base dissipa ~118 W e, com a placa fria, fica em ~67 °C. Consumo de ~97 W para ~130 W: 8,8 pJ/bit, acima dos ~6,3 de uma ligação elétrica |
| canais a ~140 GHz | 200–400 GHz demonstrados | 16 λ a 200 GHz não cabem num FSR de 13 nm. A configuração `viavel` passa a anel de raio 3,5 µm: FSR de 18,6 nm e 16 λ a ~203 GHz |
| CPU lê a VRAM em ~800 ns | ~1.200 ns (uma fonte, método não informado) | ReBAR a ~1.200 ns, contra ~90 ns da DDR5 local |

## Banco unificado (2026-10-28)

A memória compartilhada é o centro do conceito. Sem CXL nas peças, o modelo agora a
resolve na própria base (`modulos/dados/memoria_unificada.py`): 24 chips GDDR7 que a GPU
enxerga como 12 de 32 Gb, mais uma ponte que a CPU enxerga como DIMM. O que existe de
cada parte:

| Premissa | Status | Melhor exemplo real | Distância | Risco |
|---|---|---|---|---|
| Base multiplica os chips por canal (um chip de 32 Gb feito de dois de 16 Gb, escolhidos pelo comando) | parecido à venda | LRDIMM DDR3: o buffer converte o chip select do controlador em vários ranks físicos, 2:1 ou 4:1, pela linha e coluna; o padrão GDDR7 vai de 16 a 32 Gb | ninguém faz isso em GDDR7; a GPU precisa aceitar o chip de 32 Gb do padrão, que talvez nunca tenha visto | médio |
| Ponte que se apresenta como DIMM DDR5 com CL53 e grava nos chips GDDR7 | parecido | os registradores do DDR5 aceitam CL22 a CL66; o MRDIMM já põe um buffer no caminho e paga latência | o controlador da i5 tem de aceitar CL53 a 4800 MT/s e um SPD fora dos perfis comuns | médio |
| Aprender os mapas de endereço da CPU e da GPU no boot | demonstrado em pesquisa | DRAMA: mapas da Intel são XOR de bits, achados por tempo de acesso; GPUHammer: mapa da GDDR6 de uma A6000 achado do mesmo jeito | o DRAMA avisa que triplo canal pode não ser linear; nos 12 canais o modelo usa o resto por 3, e a calibração confere com sondas aleatórias | médio |
| Base responde refresh e treino periódico da GPU para o chip que está com a CPU | sem evidência | modelos de memória GDDR7 existem como IP de verificação | a base passa a imitar parte de um chip GDDR7 | médio-alto |
| Posse por rank respeitada pelo software | depende do runtime | — | o runtime da GPU (o nosso, no laboratório) só usa o rank que é dela | baixo |

## O que destravaria cada bloqueio

- **Célula chaveada:** abrir mão da célula de função selecionável. Os caminhos
  são células separadas para energia e para sinal, com zonas de energia fixas
  (a peça deixa de poder ir para "qualquer posição"), ou uma chave nova,
  eletromecânica e de altíssima densidade — o que é pesquisa de dispositivo,
  não de sistema.
- **Memória por luz:** terminar o protocolo. O tradutor passaria a ser um
  controlador de memória com SerDes, como fazem Celestial AI e CXL, e isso exige
  CPU e GPU que falem esse protocolo.
- **Plataforma:** parceria OEM com a Intel, ou uma plataforma com documentação
  aberta (por exemplo, um SoC RISC-V ou ARM sem chipset fechado).

## Fontes

- Banco unificado: [LRDIMM e multiplicação de rank](https://www.electronicdesign.com/memory/take-lrdimm-challenge-boost-server-speed-capacity), [patente de rank não binário](https://patents.justia.com/patent/10522209), [CL22 a CL66 no DDR5](https://www.anandtech.com/show/16143), [GDDR7 de 16 a 32 Gb](https://www.guru3d.com/story/jedec-jesd239-gddr7-standard-upcoming-highspeed-memory-technology/), [MRDIMM](https://amp.hothardware.com/news/ddr5-mrdimms-standardized-up-to-17600), [DRAMA](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/pessl), [GPUHammer](https://arxiv.org/html/2507.08166v1)

- Elastômero e LGA: [ISC](https://abachy.com/node/1004), [Fujipoly Zebra](https://pcdandf.com/pcdesign/index.php/editorial/menu-new-indust-prod/5630-fujipoly-releases-silver-zebra-connector), [TE LGA](https://uk.rs-online.com/web/p/prototyping-sockets/1855357), [Invisipin](https://www.advantest.com/en/products/component-test-system/ais/invisipin-test-sockets/), [patente KR102728126B1](https://patents.google.com/patent/KR102728126B1/ko)
- MEMS: [Menlo Micro](https://www.microwavejournal.com/articles/39237-menlo-micro-demonstrates-highest-power-mems-switch), [ADI ADGM1121](https://mouser.com/datasheet/2/609/adgm1121-3468022.pdf), [ADI FAQ](https://ez.analog.com/switches_multiplexers/a/documents/do27248/mems-switch-technology-faq-s)
- Interconexão reconfigurável: [Aptix](https://patents.google.com/patent/US5414638), [preço Aptix](https://www.design-reuse.com/news/provider882.html), [Pickering](https://www.microwavejournal.com/articles/32842-ultra-high-density-pxi-matrix-module-family-40-558)
- Substrato: [SPIE 112 Gb/s](https://ebooks.spiedigitallibrary.org/conference-proceedings-of-spie/11998/1199809/112-Gb-s-PAM4-transmission-using-polymer-waveguide-coupled-silicon/10.1117/12.2615086.full), [LCP com ativos embutidos](https://pcdandf.com/pcdesign/index.php/2009-archive-articles/4703-embedded-active-components-in-multilayer-lcp-packages), [Dyconex](https://evertiq.com/news/15743)
- Refrigeração: [IBM](https://research.ibm.com/publications/direct-liquid-jet-impingement-cooling-with-micronsized-nozzle-array-and-distributed-return-architecture)
- Teste de contato: [patente](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6337573), [SOPK](https://frothingham.com/spt/fec200/soft/tests/sopk.htm)
- Anel e aquecedor: [arXiv 2509.01555](https://arxiv.org/abs/2509.01555), [UCSB](https://siliconphotonics.ece.ucsb.edu/sites/default/files/2018-01/khope17ol.pdf), [CEA-Leti](https://www.cea.fr/cea-tech/leti/english/Documents/pres-WS-LID-2018/D43D/Session2/D43D18-S24-Y.Thonnart.pdf), [MIT](https://mtlsites.mit.edu/annual_reports/2012/adiabatic-resonant-microring-arm-modulator)
- Laser: [Sivers/Ayar 2022](https://www.sivers-semiconductors.com/press/sivers-photonics-and-ayar-labs-demonstrate-supernova-multi-wavelength-light-source-with-sivers-dfb-laser-arrays-at-ecoc-2022/), [Sivers/Ayar 2023](https://www.sivers-semiconductors.com/press/sivers-photonics-demonstrates-cw-wdm-msa-compliant-dfb-laser-arrays-with-ayar-labs-supernova-at-ofc-2023-supporting-the-next-generation-of-network-technology/)
- Chips ópticos: [Intel OCI](https://heise.de/-9779713), [Ayar Labs](https://yespress.io/ayar-labs), [Semtech LPO](https://www.semtech.com/company/press/semtech-to-showcase-new-linear-pluggable-optical-links-for-ai-and-ml-data-center-interconnects-at-ofc-2024), [Lightmatter M1000](https://www.theregister.com/2025/04/01/lightmatter_photonics_passage/), [Ayar 4 Tbps](https://www.businesswire.com/news/home/20231108423376/en/Ayar-Labs-Showcases-4-Tbps-Optically-enabled-Intel-FPGA-at-Supercomputing-2023)
- PCIe por óptica: [TI SN75LVPE5412](https://www.mouser.in/new/texas-instruments/ti-sn75lvpe5412-linear-redriver/), [Kyocera](https://global.kyocera.com/newsroom/news/2023/000694.html), [Amphenol](https://videos.amphenol-cs.com/detail/video/6379970812112/qsfp-dd-linear-pluggable-optics-demo-by-amphenol), [Synopsys](https://synopsys.com/blogs/chip-design/pcie-over-fiber-optics-pcie-7.html), [Keysight](https://www.keysight.com/se/en/assets/3124-1383/demos/PCIe-7-0-Over-Optics-Demo.html)
- Memória: [patente](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8032033), [Celestial AI](https://www.nextplatform.com/2024/04/04/celestial-ai-wants-to-break-the-memory-wall-fuse-hbm-with-ddr5/), [GDDR7 no layout](https://www.nextpcb.com/blog/hbm-vs-gddr7-pcb-layout), [Renesas RCD](https://www.renesas.com/en/products/5rcd0148), [Micron MRDIMM](https://tomshardware.com/desktops/servers/micron-unveils-mrdimms-for-intel-xeon-6-up-to-256gb-ddr5-8800-modules)
- Plataforma Intel: [RDC](https://edc.intel.com/content/www/us/en/resources-documentation/rdc-user-guide/getting-access/), [WinRAID](https://winraid.level1techs.com/t/intel-csme-drivers-firmware-and-tools-for-me-2-15/30719?page=103), [Dasharo](https://docs.dasharo.com/variants/msi_z790/releases/)
- CXL e ReBAR: [STH](https://www.servethehome.com/4th-gen-intel-xeon-scalable-sapphire-rapids-leaps-forward/9/), [arXiv 2303.15375](https://arxiv.org/pdf/2303.15375), [RasterGrid](https://www.rastergrid.com/?p=612)
