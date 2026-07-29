# Código de terceiros

Duas coisas neste repositório não são deste projeto: a biblioteca 3D usada pelo
visualizador e alguns símbolos de esquemático do KiCad. Estão listadas aqui com
a versão e a licença de cada uma.

As bibliotecas Python usadas pelos scripts (`gerbonara`, `cairosvg`, `numpy`,
`scipy`, `pillow`) **não** estão no repositório — vêm por `pip` a partir do
`requirements.txt` e não foram copiadas para cá.

---

## 1. three.js — em `web/`

| | |
|---|---|
| Projeto | [three.js](https://threejs.org/) |
| Versão | r128 (`three@0.128.0`) |
| Arquivos | `web/three.min.js` · `web/OrbitControls.js` |
| Licença | MIT |

`OrbitControls.js` vem de `examples/js/controls/` do mesmo pacote.

**Por que está versionado aqui em vez de vir de CDN:** a página não busca nada
de fora. Não quebra se um CDN sair do ar ou mudar de política, funciona offline,
e o que foi testado é exatamente o que vai para o ar.

### Licença MIT

```
The MIT License

Copyright © 2010-2021 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

---

## 2. Símbolos do KiCad — dentro de `hardware/esp32-cnc-laser.kicad_sch`

| | |
|---|---|
| Projeto | [KiCad Symbols](https://kicad.github.io/symbols/) |
| Copyright | KiCad Community |
| Licença | CC-BY-SA 4.0 **com exceção** (texto abaixo) |

Um arquivo `.kicad_sch` sempre carrega dentro de si a definição dos símbolos que
usa, na seção `lib_symbols`. `tools/gen_schematic.py` copia essas definições da
instalação local do KiCad para o arquivo gerado — é o que faz o esquemático
abrir em qualquer máquina, sem depender de quais bibliotecas estão instaladas.

**Doze símbolos vêm do KiCad:**

`Device:R` · `Device:C` · `Device:C_Polarized` · `Device:LED` ·
`Device:Q_NMOS_GDS` · `Regulator_Linear:LM7805_TO220` ·
`Connector_Generic:Conn_01x02` · `Conn_01x03` · `Conn_01x04` ·
`power:+12V` · `power:+5V` · `power:GND`

**Dois foram desenhados para este projeto**, porque não existem na biblioteca do
KiCad — são gerados por `rect_symbol()` em `tools/gen_schematic.py`:

`Module:ESP32_DEVKIT_V1` (30 pinos) · `Module:A4988` (16 pinos)

### A exceção da licença

A CC-BY-SA normalmente exigiria que trabalhos derivados fossem publicados sob a
mesma licença. A biblioteca do KiCad traz uma renúncia explícita a isso para
projetos eletrônicos:

> To the extent that the creation of electronic designs that use 'Licensed
> Material' can be considered to be 'Adapted Material', then the copyright
> holder waives article 3 of the license with respect to these designs and any
> generated files which use data provided as part of the 'Licensed Material'.

Ou seja: usar esses símbolos **não obriga** este projeto a adotar CC-BY-SA.

---

## Licença deste projeto

**MIT** — ver [`LICENSE`](LICENSE).

Ela cobre o que foi criado aqui: os scripts em `tools/`, o visualizador, e os
desenhos e documentos gerados em `docs/` e `hardware/`.

**Não cobre o `gerber/`.** Aquele pacote é o projeto original da placa e
pertence a quem a desenhou — está no repositório como material de origem da
engenharia reversa. O `LICENSE` diz isso explicitamente.
