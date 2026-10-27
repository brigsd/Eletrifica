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
ls modulos/ projetos/        # os modulos e projetos que existem agora
```

O que **não** confiar sem conferir: a lista de módulos, a lista de arquivos,
e os números das verificações. O que **continua valendo** mesmo que o resto mude:
a identidade do repositório, a regra de que tudo é gerado por script, e a
separação entre o que a fonte prova e o que é estimativa.

Se encontrar trabalho de outro agente pela metade, não desfaça: pergunte ou
construa em cima. E se alterar algo que este arquivo descreve, **atualize este
arquivo junto** — é ele que segura o contexto entre sessões e entre agentes.

## Como o dono quer a conversa

- Respostas **curtas, diretas e claras**. Só o que importa.
- Quando não entender algo, **pergunte de forma simples**.
- No projeto de simulação, não gaste texto justificando limites de simulação
  contra teste de bancada.

## Identidade do repositório

| | |
|---|---|
| Nome atual | **`brigsd/Eletrifica`** |
| Nome antigo | `brigsd/Achievements` — **renomeado, não use mais** |
| Site | <https://brigsd.github.io/Eletrifica/> (página inicial) |
| GitHub Pages | branch `main`, pasta `/ (root)`, com `.nojekyll` |

> **Atenção:** a pasta local do checkout ainda pode se chamar `Achievements`, e
> conversas antigas ainda citam esse nome. Isso é só resíduo. O repositório é
> `Eletrifica`. A URL `brigsd.github.io/Achievements` responde **404** — o Pages
> não redireciona repositórios renomeados.

## Estrutura

```
modulos/      ferramentas por objetivo; cada pasta é um módulo Python
  caminhos.py   RAIZ, PROJETOS, BUILD — use isto, não monte caminho na mão
  pcb/          engenharia reversa de PCB a partir do Gerber
projetos/     um diretório por projeto (dados de origem + saídas geradas + visualizador)
  cnc-laser/    gerber/, hardware/, docs/, web/, index.html, README.md
tests/        pytest; `python3 -m pytest` na raiz
vendor/three/ three.js r128 versionado, compartilhado pelos visualizadores
scratch/      rascunho, ignorado pelo git (só o README é versionado)
build/        intermediários, ignorado pelo git
index.html    página inicial do Pages, com um cartão por projeto
```

Tudo roda **da raiz** como módulo: `python3 -m modulos.<modulo>.<script>`.
Os módulos importam uns aos outros por `from modulos.x import y`.

Até o commit `e185dfb` a estrutura era plana (`tools/`, `gerber/`, `docs/`,
`web/`, `index.html` na raiz, tudo da CNC). Se uma conversa antiga citar esses
caminhos, o equivalente agora é `modulos/pcb/` e `projetos/cnc-laser/`.

## Regra que rege o repositório inteiro

Tudo é **gerado por script**, nunca desenhado à mão. Para mudar qualquer saída,
mude o script ou a fonte e rode de novo. Nunca edite um `.kicad_sch`, um SVG ou
um `.json` exportado diretamente — eles são artefatos.

---

## Projeto `cnc-laser`

Engenharia reversa de uma placa a partir do pacote Gerber, que era o único
material disponível. A placa é uma **controladora de CNC / gravadora a laser de
dois eixos com ESP32**: 70,5 × 54,6 mm, duas camadas, 19 componentes, 43 nets.
Reconstruído: netlist, esquemático KiCad, desenhos do layout, modelo 3D e um
visualizador interativo em `projetos/cnc-laser/index.html`.

A fonte é `projetos/cnc-laser/gerber/`. Distinga sempre:

- **O Gerber prova**: conectividade, posição e orientação das peças, valores e
  part numbers (lidos da serigrafia), contorno da placa.
- **O Gerber não guarda**: altura e formato dos corpos. Esses valores são os
  típicos de cada encapsulamento, ficam na tabela `BODIES` em
  `modulos/pcb/render_3d.py`, e devem ser apresentados como estimativa.

### Verificações (rode antes de afirmar que está certo)

```bash
python3 -m modulos.pcb.verify_netlist   # esquemático x netlist da placa -> 22/22 nets
python3 -m modulos.pcb.check_copper     # geometria do cobre x netlist   -> 43/43 ilhas
```

As duas também rodam pelo `pytest` (`tests/test_pcb.py`; a do esquemático é
pulada se não houver `kicad-cli`). `check_copper` foi conferido como 43/43 depois
da reestruturação. **Rode antes de afirmar** — o resultado de agora é o que conta.

`check_copper` é independente do arquivo de netlist: rasteriza o cobre pelas
aberturas do próprio Gerber e só usa coordenadas.

Os PNG gerados variam com a versão de `cairosvg`/`pillow`; SVG, JSON e MD
regeneram byte a byte idênticos. Não commite PNG regerado só por isso.

### Dois problemas encontrados na placa

1. **Elétrico, confirmado.** O source do Q1 (IRFZ44N) não chega ao GND em
   nenhuma camada — o net tem só `Q1.3` e `R1.1`. O laser não acende.
2. **Mecânico, a confirmar.** C1 e C2 ficam debaixo dos drivers A4988 e, pelas
   alturas usuais, faltam 2,5 mm de folga. A posição é fato; as alturas são
   estimativa.

Detalhes em `projetos/cnc-laser/docs/analise.md`.

### Ferramentas (`modulos/pcb/`)

| Script | O que faz |
|--------|-----------|
| `gen_schematic.py` | Gera o `.kicad_sch` a partir da netlist da placa |
| `gen_docs.py` | Gera `docs/bom.md` e `docs/netlist.md` |
| `render_layout.py` | Desenhos do layout (trilhas, pads, serigrafia) |
| `render_3d.py` | 3D isométrico, laterais ortográficas, páginas por peça |
| `export_web.py` | `web/board.json` e a textura, para o visualizador |
| `verify_netlist.py` · `check_copper.py` | As duas verificações |

Dependências em `requirements.txt`, mais o `kicad-cli` do KiCad 7+.

---

## Código de terceiros

`THIRD_PARTY.md` lista o que não é deste projeto: o three.js em `vendor/three/`
(MIT) e os símbolos do KiCad embutidos no `.kicad_sch` (CC-BY-SA 4.0 com
exceção). Se acrescentar qualquer dependência versionada, registre lá.

O projeto é **MIT** (`LICENSE`), só sobre o que foi criado aqui. O
`projetos/cnc-laser/gerber/` fica de fora de propósito: pertence a quem desenhou
a placa. Não estenda a licença a ele.

## Ao mexer num visualizador

Cada projeto tem o seu `index.html`, que carrega `../../vendor/three/` — nada
de CDN, de propósito. Se alterar a geometria, rode o exportador do projeto para
o `.json` não divergir dos desenhos. Ao criar um projeto novo com visualizador,
acrescente um cartão no `index.html` da raiz.
