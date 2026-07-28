#!/usr/bin/env python3
"""Generate the BOM and the netlist table from the same source the schematic uses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_schematic import PARTS, RENAME, load_netlist

ROOT = Path(__file__).resolve().parent.parent

DESC = {
    "J1": "Jack DC de alimentacao (12 V). O pino 3 e o terminal de comutacao do jack e nao esta ligado.",
    "D8": "LED indicador de alimentacao. Pad 1 e o anodo na placa.",
    "R3": "Resistor serie do LED indicador. Com 12 V da cerca de 1 mA.",
    "C1": "Reservatorio no trilho de 12 V.",
    "C2": "Reservatorio no trilho de 12 V.",
    "C15": "Reservatorio na entrada do regulador.",
    "C14": "Desacoplamento no trilho de 12 V.",
    "C3": "Capacitor de entrada do LM7805.",
    "U2": "Regulador linear 12 V -> 5 V. Alimenta o ESP32 (VIN) e o laser.",
    "C4": "Capacitor de saida do LM7805.",
    "U1": "Modulo ESP32 DEVKIT V1 (30 pinos). Gera STEP/DIR/EN e o PWM do laser.",
    "DRV1": "Driver de passo do eixo X. MS1-MS3 em GND e RESET+SLEEP em 3V3.",
    "DRV2": "Driver de passo do eixo Y. Mesma configuracao do eixo X.",
    "M1": "Conector do motor de passo do eixo X (bobinas 1A/1B e 2A/2B).",
    "M2": "Conector do motor de passo do eixo Y.",
    "R2": "Resistor serie no gate do Q1, vindo do GPIO13.",
    "R1": "Resistor de gate para source do Q1.",
    "Q1": "MOSFET canal N que chaveia o lado negativo do laser.",
    "CN1": "Conector do modulo laser. O positivo vem do trilho de 5 V.",
}

ORDER = ["J1", "U2", "C1", "C2", "C15", "C14", "C3", "C4", "R3", "D8",
         "U1", "DRV1", "DRV2", "M1", "M2", "R2", "R1", "Q1", "CN1"]


def main():
    nets = load_netlist()
    ref_of = {key: meta["ref"] for key, meta in PARTS.items()}
    meta_of = {meta["ref"]: meta for meta in PARTS.values()}
    pins_of = {ref_of[key]: pins for key, pins in nets.items() if key in ref_of}
    silk_of = {ref_of[key]: key[0] for key in PARTS}

    lines = ["# Lista de materiais", "",
             "Extraida da serigrafia da placa (`Gerber_TopSilkscreenLayer.GTO`).", "",
             "| Ref | Valor / part number | Nome na serigrafia | Pinos | Funcao |",
             "|-----|--------------------|--------------------|-------|--------|"]
    for ref in ORDER:
        m = meta_of[ref]
        lines.append(f"| {ref} | {m['value']} | `{silk_of[ref]}` | {len(pins_of[ref])} | {DESC[ref]} |")
    (ROOT / "docs" / "bom.md").write_text("\n".join(lines) + "\n")

    by_net = {}
    for ref, pins in pins_of.items():
        for pin, raw in pins.items():
            net = RENAME.get(raw, raw)
            if net.startswith("NET_"):
                continue
            by_net.setdefault(net, []).append(f"{ref}.{pin}")

    out = ["# Netlist da placa", "",
           "Extraida de `gerber/FlyingProbeTesting.json`, que traz o net de cada pad.",
           "Os nets `$1N1790`, `$1N1796` e `$1N2332` nao tem nome no arquivo original;",
           "foram renomeados para `GATE_Q1`, `SRC_Q1` e `LED_A`.", "",
           "| Net | Pinos | Ligacoes |", "|-----|-------|----------|"]
    for net in sorted(by_net, key=lambda n: (-len(by_net[n]), n)):
        members = sorted(by_net[net])
        out.append(f"| `{net}` | {len(members)} | {', '.join(members)} |")

    unused = sorted(
        (pin, PARTS[("ESP32 DEVKIT V1", 30)])
        for pin, raw in nets[("ESP32 DEVKIT V1", 30)].items() if raw.startswith("NET_"))
    out += ["", f"Pinos do ESP32 sem ligacao: {len(unused)} de 30.", ""]
    (ROOT / "docs" / "netlist.md").write_text("\n".join(out) + "\n")
    print("wrote docs/bom.md and docs/netlist.md")


if __name__ == "__main__":
    main()
