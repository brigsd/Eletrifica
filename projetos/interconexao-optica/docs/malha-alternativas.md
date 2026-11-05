# Malha: alternativas lado a lado

> Gerado por `python3 -m modulos.malha.comparar`. Não edite à mão.

Os números vêm de `malha.json` (`docs/malha-parametros.md` traz as fontes). **O que ainda é
estimativa**, sem fonte pública: o salto por chave (0,15 ns, 0,3 pJ/bit), o orçamento de atraso
da GDDR7, o orçamento de perda e o skew de GDDR7 e DDR5, o fator de perda do PAM3 e o pJ/bit do
retimer. Vale para comparar as alternativas entre si, não como previsão.

| Parâmetro | Valor | Tipo |
|---|---:|---|
| Passo do segmento | 25 mm | decisão |
| Faixas por ligação (por sentido) × taxa | 32 × 32 Gb/s | derivado |
| Retemporização (retimer PCIe 5, baixa latência) | 5 ns, 3 pJ/bit | datasheet / estimativa (pJ) |
| Cobre (megtron6) | 6.2 ps/mm, 0.02 dB/mm a 16 GHz | derivado |
| Fator de perda da GDDR7 (PAM3) | 0.7 | **estimativa** |
| Salto por chave | 0.15 ns, 0.3 pJ/bit | **estimativa, sem fonte** |
| Orçamento de perda por trecho | 16 dB (PCIe 5, placa-base) | spec p/ PCIe; **estimativa p/ GDDR7 e DDR5** |
| Orçamento de atraso de ida (GDDR7 / DDR5 / PCIe) | 5 / 5.8 / 128 ns | GDDR7 **estimativa**; DDR5 derivado; PCIe spec |
| Limite de skew entre faixas (GDDR7 / DDR5 / PCIe 5) | 4.7 / 208 / 9.4 ps | **estimativa** (DDR5: spec via patente) |

Problema (ciclo 2): os enlaces de memória da GPU convergem nela e a rota XY empilha tudo
nas mesmas ligações. Regras: R21 conta fluxos acima do orçamento de atraso de ida do protocolo;
R22, ligações acima de 100 %; R23, fluxos cuja perda acumulada entre retemporizações passa do
orçamento; R24, fluxos cujas faixas chegam com diferença de atraso acima do limite de skew.

| Cenário | Saltos máx | Atraso máx (ns) | Potência (W) | Ocupação máx | R21 | R22 | Perda/trecho máx (dB) · retimers | Desalinh. máx (ps) | R23 | R24 | T máx base (°C) | GPU-MEM: saltos / atraso (ns) | Custo extra |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Atual (XY) | 7 | 36.09 | 403 | 1800 % | 37 | 34 | 0.50 · 0 | 0.0 | 0 | 0 | 122 | 2 / 10.31 | - |
| 1. Fibra gigante | 1 | 5.78 | 124 | 212 % | 36 | 27 | 1.75 · 0 | 0.0 | 0 | 0 | 74 | 1 / 5.22 | 23 expressas (até 125 mm) |
| 2. Ligações largas | 7 | 36.09 | 403 | 100 % | 37 | 0 | 0.50 · 0 | 0.0 | 0 | 0 | 122 | 2 / 10.31 | 34 ligações alargadas (+3936 faixas) |
| 2. Ligações largas + peça grande | 7 | 36.09 | 383 | 100 % | 35 | 0 | 0.50 · 0 | 0.0 | 0 | 0 | 122 | 1 / 5.16 | 33 ligações alargadas (+3744 faixas); GPU em 9 segmentos |
| 3. Rotas espalhadas | 7 | 36.09 | 403 | 1323 % | 37 | 42 | 0.50 · 0 | 0.0 | 0 | 0 | 99 | 2 / 10.31 | - |
| 4. Memória colada | 7 | 36.09 | 462 | 1588 % | 49 | 31 | 0.50 · 0 | 0.0 | 0 | 0 | 126 | 1 / 5.16 | - |
| 5. Salto por chave | 7 | 2.13 | 40 | 1800 % | 0 | 34 | 2.45 · 0 | 0.0 | 0 | 0 | 70 | 2 / 0.61 | retimer a cada 32 (DDR5-4800) / 45 (GDDR7-32) / 32 (PCIe4) / 32 (PCIe5) segmentos |
| Peça grande | 7 | 36.09 | 383 | 1800 % | 35 | 33 | 0.50 · 0 | 0.0 | 0 | 0 | 122 | 1 / 5.16 | GPU em 9 segmentos |
| Peça grande + espalhadas | 7 | 36.09 | 383 | 1323 % | 35 | 40 | 0.50 · 0 | 0.0 | 0 | 0 | 97 | 1 / 5.16 | GPU em 9 segmentos |
| Peça grande + espalhadas + largas | 7 | 36.09 | 383 | 98 % | 35 | 0 | 0.50 · 0 | 0.0 | 0 | 0 | 97 | 1 / 5.16 | 40 ligações alargadas (+3360 faixas); GPU em 9 segmentos |
| Fibra gigante + largas | 1 | 5.78 | 124 | 100 % | 36 | 0 | 1.75 · 0 | 0.0 | 0 | 0 | 74 | 1 / 5.22 | 23 expressas (até 125 mm); 27 ligações alargadas (+1152 faixas) |
| Peça grande + fibra gigante + largas | 1 | 5.78 | 117 | 100 % | 34 | 0 | 1.75 · 0 | 0.0 | 0 | 0 | 74 | 1 / 5.16 | 19 expressas (até 125 mm); 25 ligações alargadas (+1088 faixas); GPU em 9 segmentos |
| Colada + espalhadas + largas | 7 | 36.09 | 462 | 99 % | 49 | 0 | 0.50 · 0 | 0.0 | 0 | 0 | 105 | 1 / 5.16 | 31 ligações alargadas (+3968 faixas) |
| Chave + largas | 7 | 2.13 | 40 | 100 % | 0 | 0 | 2.45 · 0 | 0.0 | 0 | 0 | 70 | 2 / 0.61 | 34 ligações alargadas (+3936 faixas); retimer a cada 32 (DDR5-4800) / 45 (GDDR7-32) / 32 (PCIe4) / 32 (PCIe5) segmentos |
| Chave + fibra gigante | 1 | 0.93 | 12 | 212 % | 0 | 27 | 1.75 · 0 | 0.0 | 0 | 0 | 68 | 1 / 0.37 | 23 expressas (até 125 mm); retimer a cada 32 (DDR5-4800) / 45 (GDDR7-32) / 32 (PCIe4) / 32 (PCIe5) segmentos |
| Chave + fibra gigante + largas | 1 | 0.93 | 12 | 100 % | 0 | 0 | 1.75 · 0 | 0.0 | 0 | 0 | 68 | 1 / 0.37 | 23 expressas (até 125 mm); 27 ligações alargadas (+1152 faixas); retimer a cada 32 (DDR5-4800) / 45 (GDDR7-32) / 32 (PCIe4) / 32 (PCIe5) segmentos |
| Chave em FR4 | 7 | 2.26 | 40 | 1800 % | 0 | 34 | 7.35 · 0 | 0.0 | 0 | 0 | 70 | 2 / 0.65 | retimer a cada 10 (DDR5-4800) / 15 (GDDR7-32) / 10 (PCIe4) / 10 (PCIe5) segmentos |
| Chave em FR4 + fibra gigante + largas | 1 | 1.01 | 12 | 100 % | 0 | 0 | 5.25 · 0 | 0.0 | 0 | 0 | 68 | 1 / 0.39 | 23 expressas (até 125 mm); 27 ligações alargadas (+1152 faixas); retimer a cada 10 (DDR5-4800) / 15 (GDDR7-32) / 10 (PCIe4) / 10 (PCIe5) segmentos |

Sem malha, a base chega a 68 °C (sistema atual: placa fria e vias térmicas). A coluna de temperatura soma o calor da malha ao do sistema atual (tradutores, lasers, peças);
é conservador, porque os tradutores existentes e a retransmissão da malha são em parte o mesmo trabalho.
Cada ligação reparte a potência meio a meio entre seus dois segmentos.

## Como cada alternativa foi montada

- **Atual (XY)**: rota XY, 64 faixas por ligação, tudo igual.
- **1. Fibra gigante**: expressa ponto a ponto para cada par distante; 1 salto.
- **2. Ligações largas**: capacidade por ligação ajustada.
- **2. Ligações largas + peça grande**: capacidade por ligação ajustada; GPU recebe fluxos por todos os lados.
- **3. Rotas espalhadas**: XY e YX meio a meio; mesmos saltos nas duas partes.
- **4. Memória colada**: chip vizinho do tradutor da GPU (referência).
- **5. Salto por chave**: chave analógica por salto (estimativa); retimer a cada N segmentos pela perda do cobre.
- **Peça grande**: só a GPU em vários segmentos.
- **Peça grande + espalhadas**: GPU em vários segmentos, XY/YX.
- **Peça grande + espalhadas + largas**: idem, com ligações alargadas onde sobra.
- **Fibra gigante + largas**: expressas e capacidade ajustada.
- **Peça grande + fibra gigante + largas**: as três juntas.
- **Colada + espalhadas + largas**: referência com a sobra ajustada.
- **Chave + largas**: salto por chave e capacidade ajustada.
- **Chave + fibra gigante**: salto por chave e expressas.
- **Chave + fibra gigante + largas**: salto por chave, expressas e capacidade ajustada.
- **Chave em FR4**: salto por chave com laminado FR4 (0,06 dB/mm): o retimer entra a cada N segmentos.
- **Chave em FR4 + fibra gigante + largas**: idem, com expressas (125 mm de FR4 = 7,5 dB) e capacidade ajustada.

## Premissas das alternativas

- **Capacidade:** 32 faixas × 32 Gb/s por ligação (por sentido). Memória é half-duplex, então o
  pior caso é o fluxo inteiro num sentido só; é conservador em relação ao modelo antigo (64).
- **Fibra gigante:** uma expressa por par origem-destino com 2 saltos ou mais, de capacidade
  igual à de uma ligação comum; custa um salto (retemporização + distância em linha reta).
- **Ligações largas:** a capacidade sobe em múltiplos da ligação comum, só onde passa de 100 %.
  "Faixas extras" é a soma do que foi acrescentado.
- **Peça grande:** a GPU ocupa a caixa dos segmentos dos seus tradutores; cada fluxo sai da
  face voltada para o destino. Saltos dentro da peça não custam atraso nem energia (premissa).
- **Rotas espalhadas:** metade do fluxo por XY, metade por YX; mesmos saltos, mesmo atraso.
  Na grade uniforme as duas metades têm o mesmo comprimento e o desalinhamento sai 0; ele só
  aparece com trilhas de comprimento diferente (R24 cobre esse caso, testado à parte).
- **Memória colada:** cada chip da GPU vai para um segmento vizinho do tradutor (fora da caixa
  da GPU, balanceando as ligações). A ponte continua onde está e passa a alcançar os chips
  novos, por isso o pior caso geral (coluna "Saltos máx") pode piorar: veja a coluna GPU-MEM,
  que é o caso de referência.
- **Salto por chave:** cada salto só desvia o sinal por chave (atraso e energia da estimativa);
  um retimer (5 ns, 3 pJ/bit) entra sempre que a perda acumulada do cobre passaria de 16 dB.
  N = 16 dB / (passo × dB/mm): com Megtron 6 são 32 segmentos (GDDR7: 45), mais do que a base
  inteira tem de largura; por isso a rota nunca precisa de retimer no meio. Os retimers dos
  extremos (tradutores de origem e destino) já estão no caminho direto e não entram na conta.
  Com FR4 (0,06 dB/mm) N cai para 10 (GDDR7: 15) e o pior caminho, de 7 saltos (7,3 dB), ainda não precisa de retimer; a regra só morde em malhas maiores ou perda maior (testado à parte). A chave não tem perda de inserção modelada (sem fonte).
- As colunas R21 a R24 são as contagens do verificador sobre cada cenário.
