"""Independent connectivity check by rasterising the copper layers.

Renders each copper layer to a fine bitmap (0.02 mm/pixel) using the Gerber
apertures themselves, labels the connected copper regions, then ties the two
layers together at the plated through-holes. Only geometry is used -- the net
names in FlyingProbeTesting.json are never read, only the pad coordinates.
"""
import json, re, pathlib

import cairosvg
import numpy as np
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parent.parent
GERBER = ROOT / "gerber"
WORK = ROOT / "build"
WORK.mkdir(exist_ok=True)

SCALE = 120.0          # pixels per mm (~0.008 mm/pixel)
W_MM, H_MM = 70.5, 54.6

def layer_svg(name):
    """gerbonara renders a layer to SVG; we only need its drawing content."""
    from gerbonara import GerberFile
    out = WORK / f"{name}.svg"
    if not out.exists():
        out.write_text(str(GerberFile.open(GERBER / FILES[name]).to_svg()))
    return out


FILES = {"copper_top": "Gerber_TopLayer.GTL", "copper_bot": "Gerber_BottomLayer.GBL"}


def inner(p):
    s = pathlib.Path(p).read_text()
    return re.search(r'<g transform="[^"]*">(.*)</g>', s, re.S).group(1)

def raster(src_svg, name):
    """Paint one copper layer black on white and return a boolean copper mask."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_MM * SCALE}" '
           f'height="{H_MM * SCALE}" viewBox="0 0 {W_MM} {H_MM}" style="background:white">'
           f'<g transform="translate(0 {H_MM}) scale(1 -1)">'
           f'<g fill="#000" stroke="none">{inner(src_svg)}</g></g></svg>')
    flat = WORK / f"raster_{name}.svg"
    png = WORK / f"raster_{name}.png"
    flat.write_text(svg)
    cairosvg.svg2png(url=str(flat), write_to=str(png), background_color="white")
    from PIL import Image
    return np.array(Image.open(png).convert("L")) < 128

def to_px(x, y):
    return int(round((H_MM - y) * SCALE)), int(round(x * SCALE))   # row, col

top = raster(layer_svg("copper_top"), "top")
bot = raster(layer_svg("copper_bot"), "bot")
lt, nt = ndimage.label(top, structure=np.ones((3, 3)))
lb, nb = ndimage.label(bot, structure=np.ones((3, 3)))
print(f"regioes de cobre: top={nt} bottom={nb}  (a placa tem 43 nets)")

def drill_points(path):
    """Every plated hole, including the two ends of a G85 slot."""
    pts = []
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line.startswith("X"):
            continue
        for m in re.finditer(r"X(-?[\d.]+)Y(-?[\d.]+)", line):
            pts.append((float(m.group(1)), float(m.group(2))))
    return pts

VIAS = drill_points(f"{GERBER}/Drill_PTH_Through_Via.DRL")
HOLES = drill_points(f"{GERBER}/Drill_PTH_Through.DRL")
print(f"furos no arquivo de drill: {len(HOLES)} pads + {len(VIAS)} vias")

data = json.load(open(f"{GERBER}/FlyingProbeTesting.json"))
F = data["pins"]["fields"]; I = {n: i for i, n in enumerate(F)}
pads = {}
thru = HOLES + VIAS
for r in data["pins"]["rows"]:
    xy = (r[I["PIN_X"]] / 39.3701, r[I["PIN_Y"]] / 39.3701)
    nm = r[I["PIN_NAME"]]
    if not nm.startswith("PAD"):
        pads[f"{nm}@{xy[0]:.2f},{xy[1]:.2f}"] = xy

parent = {}
def find(a):
    parent.setdefault(a, a)
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb

# every plated hole shorts the top region to the bottom region at that point
joined = 0
for x, y in thru:
    rr, cc = to_px(x, y)
    if not (0 <= rr < lt.shape[0] and 0 <= cc < lt.shape[1]): continue
    a, b = lt[rr, cc], lb[rr, cc]
    if a and b:
        union(("T", int(a)), ("B", int(b))); joined += 1
print("furos que unem as duas faces:", joined)

def region(xy):
    rr, cc = to_px(*xy)
    if lt[rr, cc]: return ("T", int(lt[rr, cc]))
    if lb[rr, cc]: return ("B", int(lb[rr, cc]))
    return None

groups = {}
for nm, xy in pads.items():
    reg = region(xy)
    if reg: groups.setdefault(find(reg), []).append(nm)

q1 = find(region(next(v for k, v in pads.items() if k.startswith("Q1_3@"))))
print(f"\nIlha do Q1 pino 3 (source) contem {len(groups[q1])} pads:")
print("  ", sorted(g.split("@")[0] for g in groups[q1]))
gnd = find(region(next(v for k, v in pads.items() if k.startswith("U2_2@"))))
print(f"\nIlha do GND (pino 2 do LM7805) contem {len(groups[gnd])} pads")
print("Q1.3 esta na mesma ilha que o GND?", "SIM" if q1 == gnd else "NAO")
print(f"\nTotal de ilhas que contem pads: {len(groups)}")

# ---- cross-check the geometry against the netlist file --------------------
netof = {}
for r in data["pins"]["rows"]:
    nm = r[I["PIN_NAME"]]
    if not nm.startswith("PAD"):
        xy = (r[I["PIN_X"]] / 39.3701, r[I["PIN_Y"]] / 39.3701)
        netof[f"{nm}@{xy[0]:.2f},{xy[1]:.2f}"] = r[I["NET_NAME"]]

pad_island = {nm: find(region(xy)) for nm, xy in pads.items() if region(xy)}
by_net = {}
for nm, net in netof.items():
    if nm in pad_island:
        by_net.setdefault(net, set()).add(pad_island[nm])
split = {n: v for n, v in by_net.items() if len(v) > 1}

island_nets = {}
for nm, isl in pad_island.items():
    island_nets.setdefault(isl, set()).add(netof[nm])
merged = {i: v for i, v in island_nets.items() if len(v) > 1}

print(f"\n--- confronto geometria x arquivo de netlist ---")
print(f"nets cujos pads caem em mais de uma ilha (falso corte): {len(split)}")
for n, v in sorted(split.items()):
    print(f"   {n}: {len(v)} ilhas")
print(f"ilhas que misturam nets diferentes (falso curto): {len(merged)}")
for i, v in sorted(merged.items(), key=lambda kv: str(kv[0])):
    print(f"   {sorted(v)}")
