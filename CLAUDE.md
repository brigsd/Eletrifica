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
- Isto é um **laboratório**: quando uma restrição aparece, resolva no projeto.
  Não troque o conceito por um conjunto de produtos prontos.

## Identidade do repositório

| | |
|---|---|
| Nome atual | **`brigsd/Eletrifica`** |
| Nome antigo | `brigsd/Achievements` — **renomeado, não use mais** |
| Site | <https://brigsd.github.io/Eletrifica/> (página inicial) |
| GitHub Pages | branch `main`, pasta `/ (root)`, com `.nojekyll` |
| Conta do GitHub nas sessões | **`warbookbr`** (colaborador com Write). Push com 403: confira `gh api repos/brigsd/Eletrifica --jq .permissions.push` antes de mexer em token ou app |

> **Atenção:** a pasta local do checkout ainda pode se chamar `Achievements`, e
> conversas antigas ainda citam esse nome. Isso é só resíduo. O repositório é
> `Eletrifica`. A URL `brigsd.github.io/Achievements` responde **404** — o Pages
> não redireciona repositórios renomeados.

## Estrutura

```
modulos/      ferramentas por objetivo; cada pasta é um módulo Python
  caminhos.py   RAIZ, PROJETOS, BUILD — use isto, não monte caminho na mão
  pcb/          engenharia reversa de PCB a partir do Gerber
  componentes/  modelos das peças do projeto óptico
  sistema/      base de células, chave da célula, sondagem, identificação, boot, simulação
  conexoes/     netlist do sistema inteiro + verificador (18 regras) + sensibilidade
  energia/ termico/ optica/ dados/   simuladores
  visual/       cena 3D e gráficos SVG
projetos/     um diretório por projeto (dados de origem + saídas geradas + visualizador)
  cnc-laser/    gerber/, hardware/, docs/, web/, index.html, README.md
  interconexao-optica/   montagem.json, enlace.json, docs/, web/, index.html, README.md
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
pulada se não houver `kicad-cli`). As duas foram conferidas (43/43 e netlists
idênticas) depois da reestruturação. `python3 -m pytest` roda a suíte inteira
(~100 s; `-m "not lento"` pula as mais demoradas). **Rode antes de afirmar** — o resultado de agora é o que conta.

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

## Projeto `interconexao-optica`

Emulador de uma base modular que substitui a placa-mãe: CPU i5-13600KF, 1 DDR5,
a ponte do banco (PONTE-MEM), GPU, 24 chips GDDR7, um chipset Intel B760 (PCH) e
um FPGA, 30 peças encaixadas em qualquer posição e giro sobre células
chaveadas; dados por fibra óptica. **O centro do conceito é a memória
compartilhada** (dono, 2026-10-28): CPU e GPU na mesma memória, como num Apple
Silicon, com peças comuns. O conceito do dono está em
`projetos/interconexao-optica/docs/conceito.md` (cópia do documento
<https://claude.ai/artifact/3NMHV7qQad9bxKu82cApAJ>).

Fontes: `montagem.json` (onde cada peça foi encaixada e, na chave `projeto`,
as decisões de projeto) e `enlace.json` (parâmetros ópticos). Tudo o mais é
gerado por:

```bash
python3 -m modulos.sistema.simular    # ~2,5 min: docs/resultados.md, docs/*.svg, web/
```

Regras do modelo:

- **A sondagem não vaza a verdade.** `mapeamento.sondar` é o único lugar que lê
  a montagem real; a identificação, a configuração e tudo depois dela usam só o
  que a sondagem devolve. Não atalhe isso.
- **Pinagens sintéticas.** Contagem, passo e proporção energia/terra/sinal
  seguem cada encapsulamento; a posição de cada sinal não é a do datasheet.
- `calculo_simples` reproduz o cálculo do documento; `orcamento` é o modelo
  físico. Os dois aparecem lado a lado no relatório.
- **Nada é conectado por mágica.** `modulos/conexoes/construir.py` monta a
  netlist com cada salto de cada sinal (célula, trilha, chip tradutor, laser,
  fibra, receptor, driver), mais energia, controle e relógio de cada bloco.
  `verificador.py` confere 20 regras (R13 temperatura e R14 consumo usam o
  contexto de `contexto.py`, montado da simulação térmica e de energia);
  `modulos/sistema/boot.py` liga o sistema
  como máquina de estados sobre essa netlist. Um módulo novo que crie
  conexões tem de entrar na netlist, senão o verificador não o enxerga.
- **Uma chave por célula.** `modulos/sistema/celula.py` é a especificação
  única, usada pela energia e pelos sinais. Não use números de chave soltos.
  O relé MEMS por célula (`rele_mems`) é **premissa aceita pelo dono**
  (2026-10-28): não troque sem perguntar.
- Os testes da netlist real usam o fixture `netlist_real` de `tests/conftest.py`.
- O tradutor copia os **dados** sem decodificar, mas decodifica o **comando**
  (`modulos/dados/comandos.py`): sentido dos bidirecionais e MRW de terminação e
  força, que ele espelha (`ddr5.py`). O PCIe tem detecção de receptor controlada
  pelo FPGA e LTSSM/equalização em `pcie.py`. Regras R15–R17.
- **Banco unificado** (`memoria: unificada` em `montagem.json`;
  `modulos/dados/memoria_unificada.py`). A GPU só tem uma porta rápida, a de
  memória; o PCIe é o gargalo do offloading. Cada canal da GPU atende dois
  chips vizinhos (a GPU vê um de 32 Gb): no roteamento o rank 1 é `sombra_de`
  do rank 0 e usa a mesma luz; no tradutor sob o rank 0 ficam o mux de posse
  (GPU ou ponte) e o seletor de rank (qual chip), com linha de atraso. A ponte é
  peça do catálogo (PONTE-MEM): para a CPU é um DIMM de 48 GB com CL maior no
  SPD; ela aprende os mapas de endereço no boot (XOR de bits, e resto por 3 nos
  12 canais). Regras R19 (posse) e R20 (banco); etapa "Banco unificado" no boot.
- **Contato imperfeito** (`modulos/sistema/defeitos.py`) altera a verdade antes
  da sondagem; peça recusada ou desconhecida não liga célula nenhuma.
- Dois relatórios à parte, mais lentos, regenerados à mão:
  `python3 -m modulos.conexoes.sensibilidade` (docs/sensibilidade.md, ~10 min: refaz a
  temperatura a cada variação) e
  `python3 -m modulos.sistema.levantamento_defeitos` (docs/defeitos.md, ~2 min).

**Viabilidade prática:** `projetos/interconexao-optica/docs/viabilidade.md`
(pesquisa com fontes, 2026-10-28). Os três bloqueios reais: a célula chaveada
(relé de 1 A e ~20 fF a 0,4 mm não existe), DDR5/GDDR7 por óptica linear (sem
evidência) e o acesso à plataforma Intel (restrito a OEMs). Ao mudar uma
premissa física do modelo, confira nesse documento se o valor é realista.

Resultados atuais (confira rodando, não confie nestes números):

- 30/30 peças identificadas, erro de µm, em qualquer giro (o ângulo sai do
  retângulo de área mínima das células em contato).
- O PCH é peça própria: gera os relógios, sequencia a energia, lê o ME e a BIOS
  da flash. O FPGA só orquestra a base (células, tradutores, lasers).
- Memória compartilhada **fecha pelo banco unificado** (sem CXL nas peças):
  48 GB que a GPU lê a 1,5 TB/s e a CPU lê como RAM (~96 ns). A emulação confere
  bit a bit CPU → GPU e GPU → CPU. LLM de 70B em 4 bits: teto ~38 tokens/s,
  contra ~4,5 do offload de um PC comum.
- Conceito como estava: ~8.900 erros no verificador. Com as decisões de
  `montagem.json` (tradutor sob a peça, relé MEMS na célula, plano de 2 oz,
  placa fria sob a base com vias térmicas em 5 % da área): 0 erros, e o boot
  emulado fica pronto em ~540 ms. Placa fria e vias térmicas: aceitas pelo dono
  (2026-10-28) desde que funcionem na prática; sem as vias, não fecham.
- Os números realistas de `docs/viabilidade.md` já estão no modelo: anel de
  25 pm/V, 2,5 pJ/bit por lado no tradutor, canais a ~200 GHz e ReBAR a
  ~1.200 ns. Em `enlace.json`, `anel` e `filtro` de uma configuração mesclam
  com os de `comum`.
- A interconexão dissipa ~149 W dentro da base; só com ar a base chega a
  ~267 °C. Com a placa fria, ~64 °C. Consumo ~166 W, ~11 pJ/bit: acima dos
  ~6,3 de uma ligação elétrica (aviso R14). Os lasers dos caminhos da ponte
  ficam acesos o tempo todo (pior caso).
- 64 λ por fibra **não fecha** no modelo físico (diafonia); a configuração
  `viavel` (16 λ/fibra a ~200 GHz, anel de raio 3,5 µm, 4 canais por laser) dá
  ~+1,3 dB em PAM3. Com 1 laser para cada 2 canais iria a ~+4,3 dB.
- Controle térmico por anel é obrigatório (< 1 K de janela sem ele).
- A 200 A com plano de 1 oz, ~21 pinos de VCCIN passam de 1 A; com 2 oz, nenhum.

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
