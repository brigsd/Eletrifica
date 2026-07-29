# Contexto do projeto

Leia isto antes de assumir qualquer coisa sobre o repositório. O que estiver
aqui vale mais do que qualquer nome ou URL que apareça no histórico da conversa.

## Este repositório é mexido por mais de um agente

Outras IAs trabalham neste projeto. **O repositório pode estar bem diferente do
que este arquivo descreve.** Trate o que vem abaixo como intenção de projeto,
não como inventário.

Antes de agir, olhe o estado real:

```bash
git log --oneline -15        # o que mudou desde a ultima vez
git status --short           # trabalho nao commitado de outra pessoa
ls tools/ docs/              # os arquivos que existem agora
```

O que **não** confiar sem conferir: a lista de ferramentas, a lista de arquivos,
e os números das verificações. O que **continua valendo** mesmo que o resto mude:
a identidade do repositório, a regra de que tudo é gerado a partir do `gerber/`,
e a separação entre o que o Gerber prova e o que não existe nele.

Se encontrar trabalho de outro agente pela metade, não desfaça: pergunte ou
construa em cima. E se alterar algo que este arquivo descreve, **atualize este
arquivo junto** — é ele que segura o contexto entre sessões e entre agentes.

## Identidade do repositório

| | |
|---|---|
| Nome atual | **`brigsd/Eletrifica`** |
| Nome antigo | `brigsd/Achievements` — **renomeado, não use mais** |
| Site | <https://brigsd.github.io/Eletrifica/> |
| GitHub Pages | branch `main`, pasta `/ (root)`, com `.nojekyll` |

> **Atenção:** a pasta local do checkout ainda pode se chamar `Achievements`, e
> conversas antigas ainda citam esse nome. Isso é só resíduo. O repositório é
> `Eletrifica`. A URL `brigsd.github.io/Achievements` responde **404** — o Pages
> não redireciona repositórios renomeados.
>
> O conteúdo original do repositório (um guia de achievements do GitHub) era
> descartável e foi substituído por completo, com autorização do dono.

## O que este projeto é

Engenharia reversa de uma placa de circuito impresso a partir do pacote Gerber,
que era o único material disponível. A placa é uma **controladora de CNC /
gravadora a laser de dois eixos com ESP32**: 70,5 × 54,6 mm, duas camadas,
19 componentes, 43 nets.

O que foi reconstruído: netlist, esquemático KiCad, desenhos do layout, modelo
3D e um visualizador interativo publicado no Pages.

## Regra que rege o projeto inteiro

Tudo é **gerado por script a partir do `gerber/`**, nunca desenhado à mão. Para
mudar qualquer saída, mude o script ou o Gerber e rode de novo. Nunca edite um
`.kicad_sch`, um SVG ou o `web/board.json` diretamente — eles são artefatos.

Distinga sempre estas duas coisas ao afirmar algo:

- **O Gerber prova**: conectividade, posição e orientação das peças, valores e
  part numbers (lidos da serigrafia), contorno da placa.
- **O Gerber não guarda**: altura e formato dos corpos. Esses valores são os
  típicos de cada encapsulamento, ficam na tabela `BODIES` em
  `tools/render_3d.py`, e devem ser apresentados como estimativa.

## Verificações (rode antes de afirmar que está certo)

```bash
python3 tools/verify_netlist.py   # esquemático x netlist da placa -> 22/22 nets
python3 tools/check_copper.py     # geometria do cobre x netlist   -> 43/43 ilhas
```

Esses números valem para o commit `7491d19`. **Rode as duas antes de afirmar
que algo está certo** — se alguém mexeu no esquemático ou nos scripts, o
resultado muda, e é o resultado de agora que conta, não o que está escrito aqui.

`check_copper.py` é independente do arquivo de netlist: rasteriza o cobre pelas
aberturas do próprio Gerber e só usa coordenadas. Os dois concordando é o que dá
confiança aos achados.

## Dois problemas encontrados na placa

1. **Elétrico, confirmado.** O source do Q1 (IRFZ44N) não chega ao GND em
   nenhuma camada — o net tem só `Q1.3` e `R1.1`. O laser não acende, faça o
   firmware o que fizer. Confirmado pelos dois métodos acima.
2. **Mecânico, a confirmar.** C1 e C2 ficam debaixo dos drivers A4988 e, pelas
   alturas usuais, faltam 2,5 mm de folga. A posição é fato; as alturas são
   estimativa. Só se resolve medindo a placa física.

Detalhes e as demais observações em `docs/analise.md`.

## Ferramentas

| Script | O que faz |
|--------|-----------|
| `tools/gen_schematic.py` | Gera o `.kicad_sch` a partir da netlist da placa |
| `tools/gen_docs.py` | Gera `docs/bom.md` e `docs/netlist.md` |
| `tools/render_layout.py` | Desenhos do layout (trilhas, pads, serigrafia) |
| `tools/render_3d.py` | 3D isométrico, laterais ortográficas, páginas por peça |
| `tools/export_web.py` | `web/board.json` e a textura, para o visualizador |
| `tools/verify_netlist.py` · `tools/check_copper.py` | As duas verificações |

Dependências em `requirements.txt`, mais o `kicad-cli` do KiCad 7+.

## Código de terceiros

`THIRD_PARTY.md` lista o que no repositório não é deste projeto: o three.js
versionado em `web/` (MIT) e os símbolos do KiCad embutidos no `.kicad_sch`
(CC-BY-SA 4.0 com exceção que dispensa o compartilhamento em projetos
eletrônicos). Se acrescentar qualquer dependência versionada, registre lá.

O projeto ainda não tem licença própria — decisão do dono, não assuma nenhuma.

## Ao mexer no visualizador

`index.html` na raiz, com Three.js **versionado** em `web/` — a página não busca
nada de CDN de propósito. Se alterar a geometria, rode `tools/export_web.py`
para o `board.json` não divergir dos desenhos impressos.
