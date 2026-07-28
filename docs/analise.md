# Análise do circuito

Placa: **controladora CNC / gravadora a laser de 2 eixos com ESP32**, dupla face,
70,5 × 54,6 mm, 19 componentes, 43 nets.

---

## Como o circuito funciona

### 1. Entrada e regulação

O jack `DC_CARGADOR` traz **12 V**, que alimentam diretamente o `VMOT` dos dois
drivers de passo. O trilho de 12 V tem três eletrolíticos de 100 µF (C1, C2, C15)
e um cerâmico de 100 nF (C14).

O **LM7805** (U2) derruba 12 V para **5 V**, com C3 (470 nF) na entrada e C4
(100 nF) na saída. O trilho de 5 V alimenta o `VIN` do ESP32 e o positivo do laser.

O **3,3 V** não é gerado na placa: sai do regulador interno do próprio módulo
ESP32 (pino 3V3) e alimenta o `VDD` lógico dos dois drivers.

`D8` + `R3` (10 k) formam o indicador de alimentação, ligado no trilho de 12 V.

### 2. Controle

O **ESP32 DEVKIT V1** usa 6 dos seus 30 pinos:

| Pino | GPIO | Sinal |
|------|------|-------|
| 8  | GPIO25 | `STEP` — eixo X |
| 9  | GPIO26 | `DIR` — eixo X |
| 12 | GPIO12 | `STEP_2` — eixo Y |
| 7  | GPIO33 | `DIR_2` — eixo Y |
| 10 | GPIO27 | `EN` — habilita **os dois** drivers |
| 13 | GPIO13 | PWM do laser |

Os outros 24 pinos ficam sem ligação.

### 3. Drivers de passo

Dois módulos de 16 pinos tipo **A4988**, um por eixo. A configuração é idêntica
nos dois e foi lida da netlist:

- `MS1`, `MS2`, `MS3` → **GND** ⇒ modo **passo inteiro**, sem micropasso
- `RESET` + `SLEEP` → **3,3 V** ⇒ driver habilitado (ligação padrão)
- `VMOT` → 12 V, `VDD` → 3,3 V
- Bobinas `1A`/`1B` e `2A`/`2B` vão para os conectores `EJE X` e `EJE Y`

### 4. Saída do laser

`GPIO13` → `R2` (10 k) → gate do **IRFZ44N** (Q1). `R1` (10 k) liga o gate ao
source. O dreno do Q1 é o `LASER_NEG`, que vai ao pino 1 do `CN1`; o pino 2 do
`CN1` é o **+5 V**. Ou seja, o laser é alimentado em 5 V e o MOSFET chaveia o
lado negativo.

---

## Achados

### 🔴 1. O source do Q1 não tem retorno para o GND

**Este é um defeito de projeto da placa, não do esquemático.**

O net do source do Q1 (chamado `$1N1796` no arquivo original, renomeado aqui para
`SRC_Q1`) contém **exatamente dois pads**: `Q1` pino 3 e `R1` pino 1. Ele não
toca o GND em nenhuma das duas camadas de cobre, nem através de via.

Sem esse retorno o IRFZ44N não tem circuito de dreno-source fechado: **o laser
nunca acende**, independentemente do que o firmware faça com o GPIO13.

Isso foi verificado por dois caminhos independentes, que concordam:

1. **`FlyingProbeTesting.json`** — o arquivo de teste que acompanha o Gerber,
   gerado pelo CAM a partir da placa, lista o net de cada pad. `SRC_Q1` tem 2 pads.
2. **Geometria do cobre** (`tools/check_copper.py`) — rasteriza as duas camadas
   a partir das aberturas do Gerber, rotula as ilhas de cobre conectadas e une as
   faces nos furos metalizados e nas 9 vias. Esse método **não lê nenhum nome de
   net**, só coordenadas. Resultado: 43 ilhas para os 43 nets da placa, com
   **0 falsos cortes e 0 falsos curtos**, e a ilha do `Q1` pino 3 contém apenas
   `Q1_3` e `R1_1`.

Como o segundo método reproduz a netlist inteira sem um único erro, o resultado
sobre o `SRC_Q1` tem o mesmo grau de confiança que o resto da netlist.

**Correção:** ligar o pino 3 (source) do Q1 ao GND.

> Vale confirmar com um multímetro em modo continuidade entre o pino 3 do Q1 e
> qualquer ponto de GND antes de alterar a placa — é um teste de 10 segundos.

### 🟡 2. O IRFZ44N não é um MOSFET de nível lógico

Observação de datasheet, não da netlist. O IRFZ44N tem `Vgs(th)` entre 2,0 e
4,0 V e o `Rds(on)` de 17,5 mΩ é especificado com **`Vgs` = 10 V**. Acionado pelos
3,3 V de um GPIO do ESP32, ele opera perto do limiar: conduz pouco e esquenta.

Mesmo depois de corrigir o problema 1, vale trocar por um MOSFET de nível lógico
(IRLZ44N, IRL540N, AOD4184) ou acrescentar um driver de gate.

### 🟡 3. R2 = 10 k em série com o gate

O IRFZ44N tem cerca de 1,5 nF de capacitância de entrada. Com 10 k em série a
constante de tempo fica na casa de 15 µs. Serve para ligar/desligar, mas limita
bastante o PWM — o que é justamente o modo como se controla potência de laser.
Algo entre 100 Ω e 220 Ω seria mais adequado.

### 🟡 4. O laser é alimentado pelo LM7805

O `CN1` pino 2 está no trilho de 5 V, saída do LM7805. A queda é de 7 V (12 → 5),
então **cada 100 mA de laser dissipam 0,7 W no regulador**. Um módulo laser
comum de 500 mA levaria o LM7805 a 3,5 W — muito além do que um TO-220 sem
dissipador aguenta. Não há área de dissipação no layout.

### 🟡 5. Trilho de 5 V sem capacitor de reservatório

Os três eletrolíticos de 100 µF estão todos no trilho de 12 V. O 5 V tem apenas
C4 = 100 nF. Com o ESP32 fazendo picos de corrente de Wi-Fi nesse mesmo trilho,
convém acrescentar um eletrolítico de 100–470 µF na saída do LM7805.

### 🟡 6. GPIO12 é pino de strapping

`STEP_2` (eixo Y) está no **GPIO12**, que no ESP32 é o strapping `MTDI`: se
estiver em nível alto no reset, ele configura o `VDD_SDIO` para 1,8 V e o módulo
não dá boot. A entrada `STEP` do A4988 é de alta impedância e não deve puxar o
pino para cima, então na prática deve funcionar — mas se a placa apresentar boot
intermitente, é o primeiro lugar para olhar.

### 🔵 7. Observações menores

- `R3` = 10 k no LED de 12 V dá cerca de **1 mA** — funciona com LED moderno, mas fica fraco.
- O pino 3 do jack DC (contato de comutação) não está ligado.
- `EN` é comum aos dois drivers: não dá para desabilitar um eixo isoladamente.
- Modo passo inteiro fixo: para mudar micropasso é preciso cortar as ligações de MS1–MS3 para o GND.
- A corrente das bobinas é ajustada pelo trimpot `Vref` de cada módulo A4988, fora do escopo da placa.

---

## Confiança de cada informação

| Informação | Origem | Confiança |
|------------|--------|-----------|
| Conexões (todos os 43 nets) | `FlyingProbeTesting.json` + geometria do cobre, conferidos entre si | Verificado por 2 métodos |
| Valores e part numbers | Serigrafia (`Gerber_TopSilkscreenLayer.GTO`) | Lido diretamente |
| Polaridade de D8 e dos eletrolíticos | Chanfro e marca `+` na serigrafia | Lido diretamente |
| Pinagem do A4988 e do ESP32 | Deduzida da netlist e conferida contra a pinagem padrão dos módulos | Alta — as 16 e 30 ligações batem sem exceção |
| Achados 2 a 6 | Datasheets dos componentes | Análise de projeto, não medição |
