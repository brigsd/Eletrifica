#!/usr/bin/env python3
"""Compare the generated schematic's netlist against the board's own netlist.

Exports the netlist from the .kicad_sch with kicad-cli and checks, net by net,
that every connection in FlyingProbeTesting.json is present in the schematic and
that the schematic invents no connection the board does not have.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ksym
from gen_schematic import PARTS, RENAME, load_netlist

ROOT = Path(__file__).resolve().parent.parent
SCH = ROOT / "hardware" / "esp32-cnc-laser.kicad_sch"

# symbol pin -> board pad, for the parts whose numbering had to be remapped
INV_PINS = {meta["ref"]: {v: k for k, v in meta["pinmap"].items()}
            for meta in PARTS.values() if "pinmap" in meta}


def schematic_nets():
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tmp:
        out = Path(tmp.name)
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr",
                    "--output", str(out), str(SCH)], check=True, capture_output=True)
    tree = ksym.parse(out.read_text())
    nets = {}
    for node in tree:
        if not (isinstance(node, list) and node and node[0] == "nets"):
            continue
        for net in node[1:]:
            name = None
            members = set()
            for c in net:
                if isinstance(c, list) and c[0] == "name":
                    name = ksym.unquote(c[1])
                if isinstance(c, list) and c[0] == "node":
                    ref = pin = None
                    for f in c:
                        if isinstance(f, list) and f[0] == "ref":
                            ref = ksym.unquote(f[1])
                        if isinstance(f, list) and f[0] == "pin":
                            pin = ksym.unquote(f[1])
                    if ref and not ref.startswith("#PWR"):
                        members.add((ref, INV_PINS.get(ref, {}).get(pin, pin)))
            if name:
                nets[name.lstrip("/")] = members
    return nets


def board_nets():
    raw = load_netlist()
    ref_of = {key: meta["ref"] for key, meta in PARTS.items()}
    nets = {}
    for key, pins in raw.items():
        if key not in ref_of:
            continue
        for pin, net in pins.items():
            net = RENAME.get(net, net)
            if net.startswith("NET_"):
                continue
            nets.setdefault(net, set()).add((ref_of[key], pin))
    return nets


def main():
    board, sch = board_nets(), schematic_nets()
    ok = True
    print(f"{'net':14s} {'pinos placa':>11s} {'pinos esquematico':>18s}  status")
    print("-" * 60)
    for net in sorted(board):
        b, s = board[net], sch.get(net, set())
        if b == s:
            status = "OK"
        else:
            status = "DIVERGE"
            ok = False
        print(f"{net:14s} {len(b):>11d} {len(s):>18d}  {status}")
        if b != s:
            for extra in sorted(s - b):
                print(f"    a mais no esquematico: {extra}")
            for missing in sorted(b - s):
                print(f"    faltando no esquematico: {missing}")
    extra_nets = {n for n in set(sch) - set(board)
                  if sch[n] and not n.startswith("unconnected-")}
    if extra_nets:
        ok = False
        print("\nnets presentes so no esquematico:", sorted(extra_nets))
    print("\nRESULTADO:", "netlists identicas" if ok else "HA DIVERGENCIA")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
