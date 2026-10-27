# Lista de materiais

Extraida da serigrafia da placa (`Gerber_TopSilkscreenLayer.GTO`).

| Ref | Valor / part number | Nome na serigrafia | Pinos | Funcao |
|-----|--------------------|--------------------|-------|--------|
| J1 | Jack DC 12V | `DC_CARGADOR` | 3 | Jack DC de alimentacao (12 V). O pino 3 e o terminal de comutacao do jack e nao esta ligado. |
| U2 | LM7805 | `U2` | 3 | Regulador linear 12 V -> 5 V. Alimenta o ESP32 (VIN) e o laser. |
| C1 | 100uF | `C1` | 2 | Reservatorio no trilho de 12 V. |
| C2 | 100uF | `C2` | 2 | Reservatorio no trilho de 12 V. |
| C15 | 100uF | `C15` | 2 | Reservatorio na entrada do regulador. |
| C14 | 100nF | `C14` | 2 | Desacoplamento no trilho de 12 V. |
| C3 | 470nF | `C3` | 2 | Capacitor de entrada do LM7805. |
| C4 | 100nF | `C4` | 2 | Capacitor de saida do LM7805. |
| R3 | 10k | `R3` | 2 | Resistor serie do LED indicador. Com 12 V da cerca de 1 mA. |
| D8 | LED | `D8` | 2 | LED indicador de alimentacao. Pad 1 e o anodo na placa. |
| U1 | ESP32 DEVKIT V1 | `ESP32 DEVKIT V1` | 30 | Modulo ESP32 DEVKIT V1 (30 pinos). Gera STEP/DIR/EN e o PWM do laser. |
| DRV1 | A4988 - eixo X | `EJE X` | 16 | Driver de passo do eixo X. MS1-MS3 em GND e RESET+SLEEP em 3V3. |
| DRV2 | A4988 - eixo Y | `XA2_EJE_Y` | 16 | Driver de passo do eixo Y. Mesma configuracao do eixo X. |
| M1 | Motor X | `EJE X` | 4 | Conector do motor de passo do eixo X (bobinas 1A/1B e 2A/2B). |
| M2 | Motor Y | `EJE Y` | 4 | Conector do motor de passo do eixo Y. |
| R2 | 10k | `R2` | 2 | Resistor serie no gate do Q1, vindo do GPIO13. |
| R1 | 10k | `R1` | 2 | Resistor de gate para source do Q1. |
| Q1 | IRFZ44N | `Q1` | 3 | MOSFET canal N que chaveia o lado negativo do laser. |
| CN1 | LASER | `CN1` | 2 | Conector do modulo laser. O positivo vem do trilho de 5 V. |
