# Malha: alternativas lado a lado

> Gerado por `python3 -m modulos.malha.comparar`. Não edite à mão.

**Custo e atraso ainda são estimativas** (`modulos/malha/custo.py`: retemporização por
salto, ps por mm, pJ por bit por salto). Os números reais estão em pesquisa; a tabela
vale para comparar as alternativas entre si, não como previsão.

Problema (ciclo 2): os enlaces de memória da GPU convergem nela e a rota XY empilha tudo
nas mesmas ligações; o pior caminho passa do orçamento da GDDR7 (10 ns). R21 conta fluxos
acima do orçamento do protocolo; R22 conta ligações acima de 100 %.

| Cenário | Saltos máx | Atraso máx (ns) | Potência (W) | Ocupação máx | R21 | R22 | GPU-MEM: saltos / atraso (ns) | Custo extra |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Atual (XY) | 7 | 11.73 | 269 | 900 % | 8 | 29 | 2 / 3.35 | - |
| 1. Fibra gigante | 1 | 2.38 | 83 | 106 % | 0 | 9 | 1 / 1.75 | 23 expressas (até 125 mm) |
| 2. Ligações largas | 7 | 11.73 | 269 | 100 % | 8 | 0 | 2 / 3.35 | 29 ligações alargadas (+3456 faixas) |
| 2. Ligações largas + peça grande | 7 | 11.73 | 256 | 100 % | 8 | 0 | 1 / 1.68 | 26 ligações alargadas (+3264 faixas); GPU em 9 segmentos |
| 3. Rotas espalhadas | 7 | 11.73 | 269 | 662 % | 8 | 30 | 2 / 3.35 | - |
| 4. Memória colada | 7 | 11.73 | 308 | 794 % | 15 | 22 | 1 / 1.68 | - |
| Peça grande | 7 | 11.73 | 256 | 900 % | 8 | 26 | 1 / 1.68 | GPU em 9 segmentos |
| Peça grande + espalhadas | 7 | 11.73 | 256 | 662 % | 8 | 25 | 1 / 1.68 | GPU em 9 segmentos |
| Peça grande + espalhadas + largas | 7 | 11.73 | 256 | 95 % | 8 | 0 | 1 / 1.68 | 25 ligações alargadas (+2624 faixas); GPU em 9 segmentos |
| Fibra gigante + largas | 1 | 2.38 | 83 | 53 % | 0 | 0 | 1 / 1.75 | 23 expressas (até 125 mm); 9 ligações alargadas (+576 faixas) |
| Peça grande + fibra gigante + largas | 1 | 2.38 | 78 | 53 % | 0 | 0 | 1 / 1.68 | 19 expressas (até 125 mm); 9 ligações alargadas (+576 faixas); GPU em 9 segmentos |
| Colada + espalhadas + largas | 7 | 11.73 | 308 | 99 % | 15 | 0 | 1 / 1.68 | 23 ligações alargadas (+3328 faixas) |

## Como cada alternativa foi montada

- **Atual (XY)**: rota XY, 64 faixas por ligação, tudo igual.
- **1. Fibra gigante**: expressa ponto a ponto para cada par distante; 1 salto.
- **2. Ligações largas**: capacidade por ligação ajustada.
- **2. Ligações largas + peça grande**: capacidade por ligação ajustada; GPU recebe fluxos por todos os lados.
- **3. Rotas espalhadas**: XY e YX meio a meio; mesmos saltos nas duas partes.
- **4. Memória colada**: chip vizinho do tradutor da GPU (referência).
- **Peça grande**: só a GPU em vários segmentos.
- **Peça grande + espalhadas**: GPU em vários segmentos, XY/YX.
- **Peça grande + espalhadas + largas**: idem, com ligações alargadas onde sobra.
- **Fibra gigante + largas**: expressas e capacidade ajustada.
- **Peça grande + fibra gigante + largas**: as três juntas.
- **Colada + espalhadas + largas**: referência com a sobra ajustada.

## Premissas das alternativas

- **Fibra gigante:** uma expressa por par origem-destino com 2 saltos ou mais, de capacidade
  igual à de uma ligação comum; custa um salto (retemporização + distância em linha reta).
- **Ligações largas:** a capacidade sobe em múltiplos da ligação comum, só onde passa de 100 %.
  "Faixas extras" é a soma do que foi acrescentado.
- **Peça grande:** a GPU ocupa a caixa dos segmentos dos seus tradutores; cada fluxo sai da
  face voltada para o destino. Saltos dentro da peça não custam atraso nem energia (premissa).
- **Rotas espalhadas:** metade do fluxo por XY, metade por YX; mesmos saltos, mesmo atraso.
- **Memória colada:** cada chip da GPU vai para um segmento vizinho do tradutor (fora da caixa
  da GPU, balanceando as ligações). A ponte continua onde está e passa a alcançar os chips
  novos, por isso o pior caso geral (coluna "Saltos máx") pode piorar: veja a coluna GPU-MEM,
  que é o caso de referência.
- As colunas R21/R22 são as contagens do verificador sobre cada cenário.
