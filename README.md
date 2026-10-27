# Eletrifica

Laboratório de eletrônica: engenharia reversa de placas e simulação de
hardware, tudo gerado por script.

**→ [brigsd.github.io/Eletrifica](https://brigsd.github.io/Eletrifica/)** — página inicial com os visualizadores 3D.

## Projetos

| Projeto | O que é |
|---------|---------|
| [`projetos/cnc-laser/`](projetos/cnc-laser/) | Engenharia reversa de uma controladora CNC / laser com ESP32, a partir do Gerber |
| [`projetos/interconexao-optica/`](projetos/interconexao-optica/) | Emulador de uma base modular que troca a placa-mãe por células chaveadas e fibra óptica |

## Estrutura

```
modulos/      ferramentas, agrupadas por objetivo (cada pasta é um módulo Python)
  pcb/          Gerber -> netlist, esquemático, desenhos, 3D e visualizador
  componentes/  modelos das peças (CPU, DDR5, GPU, GDDR7, FPGA)
  sistema/      base de células, sondagem, identificação, simulação completa
  energia/      corrente nos contatos, VRM, proteção, árvore de alimentação
  termico/      temperatura da base
  optica/       anel, filtros, receptor, enlace no tempo, controle térmico
  dados/        protocolos, roteamento, latência, treino de memória
  visual/       cena 3D e gráficos
projetos/     um diretório por projeto: dados de origem, saídas geradas, visualizador
tests/        testes (pytest)
vendor/       código de terceiros versionado (three.js)
scratch/      rascunho, ignorado pelo git
index.html    página inicial do GitHub Pages
```

Tudo roda **da raiz**, como módulo:

```bash
pip install -r requirements.txt
python3 -m modulos.pcb.check_copper     # exemplo
python3 -m pytest                       # todos os testes
```

## Licença

**MIT** — ver [`LICENSE`](LICENSE), que também diz o que fica de fora (o Gerber
original e o código de terceiros listado em [`THIRD_PARTY.md`](THIRD_PARTY.md)).
