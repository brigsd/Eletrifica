#!/usr/bin/env python3
"""Generate a KiCad schematic from the board's flying-probe netlist.

The netlist (component, pin, net for every pad) is read straight out of
FlyingProbeTesting.json that ships with the Gerber package, so the connectivity
in the schematic is the board's real connectivity -- nothing is inferred.
Component values and part numbers come from the top silkscreen layer.
"""
import json
import sys
import uuid
from math import cos, radians, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ksym

ROOT = Path(__file__).resolve().parent.parent
GERBER = ROOT / "gerber"
OUT = ROOT / "hardware" / "esp32-cnc-laser.kicad_sch"
NS = uuid.UUID("6f1d4e8a-2b7c-4a19-9d3e-5c8a0b1f7e42")


def uid(key):
    return str(uuid.uuid5(NS, key))


# --------------------------------------------------------------------------
# Board data: how each silkscreen part maps to a schematic symbol.
# key = (silkscreen name, pin count) because two parts share the name "EJE X".
# --------------------------------------------------------------------------
PARTS = {
    ("DC_CARGADOR", 3): dict(ref="J1", lib="Connector_Generic:Conn_01x03",
                             value="Jack DC 12V", at=(38, 42), mirror="y"),
    ("R3", 2):          dict(ref="R3", lib="Device:R", value="10k", at=(32, 66), angle=180),
    ("D8", 2):          dict(ref="D8", lib="Device:LED", value="LED", at=(32, 86), angle=90,
                         pinmap={"1": "2", "2": "1"}),  # pad1=anodo na placa
    ("C1", 2):          dict(ref="C1", lib="Device:C_Polarized", value="100uF", at=(74, 58)),
    ("C2", 2):          dict(ref="C2", lib="Device:C_Polarized", value="100uF", at=(90, 58)),
    ("C15", 2):         dict(ref="C15", lib="Device:C_Polarized", value="100uF", at=(106, 58)),
    ("C14", 2):         dict(ref="C14", lib="Device:C", value="100nF", at=(122, 58)),
    ("C3", 2):          dict(ref="C3", lib="Device:C", value="470nF", at=(138, 58)),
    ("U2", 3):          dict(ref="U2", lib="Regulator_Linear:LM7805_TO220",
                             value="LM7805", at=(166, 42)),
    ("C4", 2):          dict(ref="C4", lib="Device:C", value="100nF", at=(188, 58)),
    ("ESP32 DEVKIT V1", 30): dict(ref="U1", lib="Module:ESP32_DEVKIT_V1",
                                  value="ESP32 DEVKIT V1", at=(254, 95)),
    ("EJE X", 16):      dict(ref="DRV1", lib="Module:A4988", value="A4988 - eixo X", at=(342, 62)),
    ("EJE X", 4):       dict(ref="M1", lib="Connector_Generic:Conn_01x04",
                             value="Motor X", at=(392, 62)),
    ("XA2_EJE_Y", 16):  dict(ref="DRV2", lib="Module:A4988", value="A4988 - eixo Y", at=(342, 162)),
    ("EJE Y", 4):       dict(ref="M2", lib="Connector_Generic:Conn_01x04",
                             value="Motor Y", at=(392, 162)),
    ("R2", 2):          dict(ref="R2", lib="Device:R", value="10k", at=(60, 200), angle=180),
    ("R1", 2):          dict(ref="R1", lib="Device:R", value="10k", at=(95, 218), angle=180),
    ("Q1", 3):          dict(ref="Q1", lib="Device:Q_NMOS_GDS", value="IRFZ44N", at=(130, 215)),
    ("CN1", 2):         dict(ref="CN1", lib="Connector_Generic:Conn_01x02",
                             value="LASER", at=(180, 200)),
}

# Symbols big enough that Reference/Value must sit outside the body.
BIG = {
    "Module:ESP32_DEVKIT_V1": (-22.9, 22.9),
    "Module:A4988": (-14.0, 14.0),
    "Regulator_Linear:LM7805_TO220": (-13.0, -9.0),
    "Connector_Generic:Conn_01x03": (-8.0, 8.0),   # J1 is mirrored;
                                                   # KiCad flips field justify with it
}
MODULES = {"Module:ESP32_DEVKIT_V1", "Module:A4988"}

# Nets carried by a power symbol rather than a text label.
POWER = {"+12V": "power:+12V", "+5V": "power:+5V",
         "+3V3": "power:+3V3", "GND": "power:GND"}

# The board leaves three nets unnamed ($1N....); give them readable names.
RENAME = {"$1N1790": "GATE_Q1", "$1N1796": "SRC_Q1", "$1N2332": "LED_A",
          "12V": "+12V", "5V": "+5V", "3.3V": "+3V3"}

PIN_NAMES = {
    "Module:ESP32_DEVKIT_V1": [
        "EN", "GPIO36/VP", "GPIO39/VN", "GPIO34", "GPIO35", "GPIO32", "GPIO33", "GPIO25",
        "GPIO26", "GPIO27", "GPIO14", "GPIO12", "GPIO13", "GND", "VIN",
        "3V3", "GND", "GPIO15", "GPIO2", "GPIO4", "GPIO16/RX2", "GPIO17/TX2", "GPIO5",
        "GPIO18", "GPIO19", "GPIO21", "GPIO3/RX0", "GPIO1/TX0", "GPIO22", "GPIO23",
    ],
    "Module:A4988": [
        "DIR", "STEP", "SLEEP", "RESET", "MS3", "MS2", "MS1", "ENABLE",
        "VMOT", "GND", "2B", "2A", "1A", "1B", "VDD", "GND",
    ],
}


# --------------------------------------------------------------------------
# Symbol construction
# --------------------------------------------------------------------------
def rect_symbol(name, pin_names, half_w, pitch=2.54, stub=2.54):
    """Build a DIP-style rectangular symbol: pins 1..n/2 down the left side,
    the rest back up the right side (counter-clockwise, like a real package)."""
    n = len(pin_names)
    per_side = n // 2
    span = (per_side - 1) * pitch
    half_h = span / 2 + pitch
    body_w = half_w
    lines = [
        f'(symbol "{name}" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)',
        f'  (property "Reference" "U" (at 0 {half_h + 2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
        f'  (property "Value" "{name.split(":")[-1]}" (at 0 {-half_h - 2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
        f'  (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'  (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'  (symbol "{name.split(":")[-1]}_0_1"',
        f'    (rectangle (start {-body_w:.2f} {half_h:.2f}) (end {body_w:.2f} {-half_h:.2f})',
        f'      (stroke (width 0.254) (type default)) (fill (type background))))',
        f'  (symbol "{name.split(":")[-1]}_1_1"',
    ]
    pins = {}
    for i, pname in enumerate(pin_names, start=1):
        if i <= per_side:
            y = span / 2 - (i - 1) * pitch
            x = -body_w - stub
            angle = 0
        else:
            j = i - per_side - 1
            y = -span / 2 + j * pitch
            x = body_w + stub
            angle = 180
        etype = "power_in" if pname in ("GND", "VIN", "3V3", "VMOT", "VDD") else "passive"
        lines.append(
            f'    (pin {etype} line (at {x:.2f} {y:.2f} {angle}) (length {stub:.2f})'
            f' (name "{pname}" (effects (font (size 1.016 1.016))))'
            f' (number "{i}" (effects (font (size 1.016 1.016)))))'
        )
        pins[str(i)] = (x, y)
    lines.append("  )")
    lines.append(")")
    return "\n".join("    " + ln for ln in lines), pins


def stock_symbol(lib_id):
    lib, name = lib_id.split(":")
    sym = ksym.resolve(lib, name)
    sym = [c for c in sym]
    sym[1] = f'"{lib_id}"'
    return "    " + ksym.dump(sym, 2), ksym.pins(sym)


# --------------------------------------------------------------------------
# Netlist
# --------------------------------------------------------------------------
def load_netlist():
    data = json.loads((GERBER / "FlyingProbeTesting.json").read_text())
    fields = data["pins"]["fields"]
    idx = {n: i for i, n in enumerate(fields)}
    comps = {}
    for row in data["pins"]["rows"]:
        if row[idx["LAYER"]] != "T":
            continue
        pin_name = row[idx["PIN_NAME"]]
        if pin_name.startswith("PAD"):
            continue
        ref, pin = pin_name.rsplit("_", 1)
        cx = row[idx["PIN_X"]]
        comps.setdefault(ref, {}).setdefault(pin, row[idx["NET_NAME"]])
    # split the two parts that share the name "EJE X" by pin count
    out = {}
    for ref, pins in comps.items():
        out[(ref, len(pins))] = pins
    # "EJE X" collided: rebuild it from raw rows, separating by x coordinate
    ejex = {}
    for row in data["pins"]["rows"]:
        if row[idx["LAYER"]] != "T":
            continue
        if row[idx["PIN_NAME"]].rsplit("_", 1)[0] != "EJE X":
            continue
        pin = row[idx["PIN_NAME"]].rsplit("_", 1)[1]
        group = "drv" if row[idx["PIN_X"]] > 500 else "mot"
        ejex.setdefault(group, {})[pin] = row[idx["NET_NAME"]]
    out[("EJE X", 16)] = ejex["drv"]
    out[("EJE X", 4)] = ejex["mot"]
    return out


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------
def place_pin(origin, rel, angle, mirror):
    px, py = rel
    if mirror == "y":
        px = -px
    a = radians(angle)
    rx = px * cos(a) - py * sin(a)
    ry = px * sin(a) + py * cos(a)
    return round(origin[0] + rx, 4), round(origin[1] - ry, 4)


def main():
    nets = load_netlist()
    lib_defs, pinmaps = [], {}

    for lib_id in sorted({p["lib"] for p in PARTS.values()}):
        if lib_id in PIN_NAMES:
            half_w = 16.51 if "ESP32" in lib_id else 12.7
            text, pins = rect_symbol(lib_id, PIN_NAMES[lib_id], half_w)
        else:
            text, pins = stock_symbol(lib_id)
        lib_defs.append(text)
        pinmaps[lib_id] = pins
    for lib_id in sorted(set(POWER.values())):
        text, pins = stock_symbol(lib_id)
        lib_defs.append(text)
        pinmaps[lib_id] = pins

    body = []

    def add_symbol(lib_id, ref, value, at, angle=0, mirror=None, key=None, power=False):
        u = uid(key or ref)
        mir = f" (mirror {mirror})" if mirror else ""
        if power:
            # power symbols: hide the reference, keep the net name visible
            rpos, vpos, just, rhide = (at[0], at[1]), (at[0], at[1]), "left", " hide"
        elif lib_id in BIG:
            rdy, vdy = BIG[lib_id]
            rpos, vpos, just, rhide = (at[0], at[1] + rdy), (at[0], at[1] + vdy), None, ""
        elif mirror == "y":
            rpos, vpos, just, rhide = (at[0] - 5.0, at[1] - 2.4), (at[0] - 5.0, at[1] + 2.4), "right", ""
        else:
            rpos, vpos, just, rhide = (at[0] + 5.0, at[1] - 2.4), (at[0] + 5.0, at[1] + 2.4), "left", ""
        jt = f' (justify {just})' if just else ''
        body.append(
            f'  (symbol (lib_id "{lib_id}") (at {at[0]} {at[1]} {angle}){mir} (unit 1)\n'
            f'    (in_bom yes) (on_board yes) (dnp no) (uuid "{u}")\n'
            f'    (property "Reference" "{ref}" (at {rpos[0]} {rpos[1]} 0)'
            f' (effects (font (size 1.27 1.27)){jt}{rhide}))\n'
            f'    (property "Value" "{value}" (at {vpos[0]} {vpos[1]} 0)'
            f' (effects (font (size 1.27 1.27)){jt}))\n'
            f'    (instances (project "esp32-cnc-laser"\n'
            f'      (path "/{uid("root")}" (reference "{ref}") (unit 1))))\n'
            f'  )'
        )

    def wire(a, b):
        body.append(
            f'  (wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]}))\n'
            f'    (stroke (width 0) (type default)) (uuid "{uid(f"w{a}{b}")}"))'
        )

    def label(pos, text, angle=0):
        rot, just = {0: (0, "left"), 180: (0, "right"),
                     90: (90, "left"), 270: (90, "right")}[angle]
        body.append(
            f'  (label "{text}" (at {pos[0]} {pos[1]} {rot})\n'
            f'    (effects (font (size 1.27 1.27)) (justify {just} bottom))'
            f' (uuid "{uid(f"l{pos}{text}")}"))'
        )

    def nc(pos):
        body.append(f'  (no_connect (at {pos[0]} {pos[1]}) (uuid "{uid(f"nc{pos}")}"))')

    def text_note(pos, txt, size=1.8):
        body.append(
            f'  (text "{txt}" (at {pos[0]} {pos[1]} 0)\n'
            f'    (effects (font (size {size} {size})) (justify left)) (uuid "{uid(f"t{pos}{txt[:20]}")}"))'
        )

    def frame(x0, y0, x1, y1, title):
        for a, b in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
            body.append(
                f'  (polyline (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]}))\n'
                f'    (stroke (width 0.2) (type dash)) (uuid "{uid(f"f{a}{b}")}"))'
            )
        text_note((x0 + 2, y0 + 4), title, 2.5)

    # ---- direct wires we draw instead of labelling (local clusters) --------
    direct_nets = {"LED_A", "GATE_Q1", "SRC_Q1"}
    ref_of = {key: meta["ref"] for key, meta in PARTS.items()}
    DIRECT = {}
    for key, pinnets in nets.items():
        if key not in ref_of:
            continue
        for pin, raw in pinnets.items():
            net = RENAME.get(raw, raw)
            if net in direct_nets:
                DIRECT.setdefault(net, {})[ref_of[key]] = pin

    pwr_n = [0]
    abs_pins = {}
    for (name, npins), meta in PARTS.items():
        lib_id = meta["lib"]
        add_symbol(lib_id, meta["ref"], meta["value"], meta["at"],
                   meta.get("angle", 0), meta.get("mirror"), key=f"{name}{npins}")
        inv = {v: k for k, v in meta.get("pinmap", {}).items()}
        for pin, rel in pinmaps[lib_id].items():
            abs_pins[(meta["ref"], inv.get(pin, pin))] = place_pin(
                meta["at"], rel, meta.get("angle", 0), meta.get("mirror"))

    NATURAL_UP = {"+12V", "+5V", "+3V3"}

    def side_of(origin, pos):
        dx, dy = pos[0] - origin[0], pos[1] - origin[1]
        if abs(dx) >= abs(dy) - 1e-6:
            return "R" if dx > 0 else "L"
        return "D" if dy > 0 else "U"

    def junction(pt, key):
        body.append(f'  (junction (at {pt[0]} {pt[1]}) (diameter 0) (color 0 0 0 0)'
                    f' (uuid "{uid(key)}"))')

    for (name, npins), meta in PARTS.items():
        ref, origin = meta["ref"], meta["at"]
        pinnets = nets[(name, npins)]

        groups = {}
        for pin, raw in sorted(pinnets.items(), key=lambda kv: int(kv[0])):
            net = RENAME.get(raw, raw)
            if net in direct_nets:
                continue
            pos = abs_pins[(ref, pin)]
            if net.startswith("NET_"):
                nc(pos)
                continue
            groups.setdefault((net, side_of(origin, pos)), []).append((pin, pos))

        use_labels = meta["lib"] in MODULES
        for (net, side), members in groups.items():
            pts = [pos for _, pos in members]
            if net not in POWER or use_labels:
                for pin, pos in members:
                    ang = {"R": 0, "L": 180, "U": 90, "D": 270}[side]
                    end_pt = ((pos[0] + 3.81, pos[1]) if side == "R" else
                              (pos[0] - 3.81, pos[1]) if side == "L" else
                              (pos[0], pos[1] - 3.81) if side == "U" else
                              (pos[0], pos[1] + 3.81))
                    wire(pos, end_pt)
                    label(end_pt, net, ang)
                continue

            up = net in NATURAL_UP
            pwr_n[0] += 1
            sym_key = f"pwr{ref}{net}{side}"

            if side in ("L", "R"):
                rail_x = pts[0][0] + (3.81 if side == "R" else -3.81)
                ys = sorted(pt[1] for pt in pts)
                for pt in pts:
                    wire(pt, (rail_x, pt[1]))
                if len(pts) > 1:
                    wire((rail_x, ys[0]), (rail_x, ys[-1]))
                    for y in ys[1:-1]:
                        junction((rail_x, y), f"j{sym_key}{y}")
                tip_y = ys[0] - 5.08 if up else ys[-1] + 5.08
                wire((rail_x, ys[0] if up else ys[-1]), (rail_x, tip_y))
                anchor, ang = (rail_x, tip_y), 0
            else:
                pt = pts[0]
                end_pt = (pt[0], pt[1] - 3.81) if side == "U" else (pt[0], pt[1] + 3.81)
                wire(pt, end_pt)
                anchor = end_pt
                ang = 0 if (up and side == "U") or (not up and side == "D") else 180

            add_symbol(POWER[net], f"#PWR{pwr_n[0]:02d}", net, anchor, ang,
                       key=sym_key, power=True)

    def dpin(net, ref):
        return abs_pins[(ref, DIRECT[net][ref])]

    a, b = dpin("LED_A", "R3"), dpin("LED_A", "D8")
    wire(a, b)
    label((a[0], (a[1] + b[1]) / 2), "LED_A", 90)

    r2, r1g, gate = dpin("GATE_Q1", "R2"), dpin("GATE_Q1", "R1"), dpin("GATE_Q1", "Q1")
    # split the gate run at R1's tap so three wire ends meet at one point
    wire(r2, (r2[0], gate[1]))
    wire((r2[0], gate[1]), (r1g[0], gate[1]))
    wire((r1g[0], gate[1]), gate)
    wire(r1g, (r1g[0], gate[1]))
    junction((r1g[0], gate[1]), "j-gate")
    label(((r2[0] + r1g[0]) / 2, gate[1]), "GATE_Q1")

    r1s, src = dpin("SRC_Q1", "R1"), dpin("SRC_Q1", "Q1")
    low = max(r1s[1], src[1]) + 6.35
    wire(r1s, (r1s[0], low))
    wire((r1s[0], low), (src[0], low))
    wire((src[0], low), src)
    label((r1s[0] + 10, low), "SRC_Q1")

    frame(18, 22, 200, 100, "1 - ENTRADA 12 V E REGULACAO 5 V")
    frame(208, 22, 302, 142, "2 - CONTROLADOR")
    frame(308, 22, 408, 112, "3 - EIXO X")
    frame(308, 118, 408, 212, "4 - EIXO Y")
    frame(18, 172, 246, 244, "5 - SAIDA LASER")

    for i, line in enumerate([
        "Esquematico obtido por engenharia reversa do pacote Gerber de 2 camadas.",
        "A conectividade vem de FlyingProbeTesting.json, que lista o net de cada pad da placa;",
        "valores e part numbers vem da serigrafia (Gerber_TopSilkscreenLayer.GTO). Nada foi inferido.",
        "",
        "ATENCAO - o source do Q1 (net SRC_Q1) nao chega ao GND em nenhuma das duas camadas de cobre.",
        "Sem esse retorno o IRFZ44N nao conduz e o laser nunca acende. Ver docs/analise.md.",
    ]):
        text_note((20, 254 + i * 5), line, 2.0)

    header = f'''(kicad_sch (version 20230121) (generator "gerber2sch")
  (uuid "{uid("root")}")
  (paper "A3")
  (title_block
    (title "Controladora CNC / Laser 2 eixos - ESP32")
    (date "")
    (rev "A")
    (company "Engenharia reversa a partir do Gerber")
    (comment 1 "Netlist extraida de FlyingProbeTesting.json")
    (comment 2 "Valores lidos da serigrafia (Gerber_TopSilkscreenLayer.GTO)")
  )
  (lib_symbols
{chr(10).join(lib_defs)}
  )
'''
    footer = f'''
  (sheet_instances
    (path "/" (page "1"))
  )
)
'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + "\n".join(body) + footer)
    print(f"wrote {OUT}  ({len(body)} elements)")


if __name__ == "__main__":
    main()
