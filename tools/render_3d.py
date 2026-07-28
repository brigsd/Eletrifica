#!/usr/bin/env python3
"""Draw the board as an isometric 3D view.

What comes from the Gerber package and is therefore exact: the board outline,
the copper and silkscreen artwork, and the position and orientation of every
component (taken from the centroid of its own pads).

What does NOT come from the Gerber, because a Gerber has no such thing: the
height and the body shape of each part. Those are the usual dimensions for each
package, listed in BODIES below. So the layout is exact and the parts are
representative -- this is a drawing to look at, not a mechanical model.

    python3 tools/render_3d.py
"""
import json
import math
import re
from pathlib import Path

from gerbonara import GerberFile

ROOT = Path(__file__).resolve().parent.parent
GERBER = ROOT / "gerber"
OUT = ROOT / "docs"

MIL = 39.3701
THICK = 1.6                      # board thickness, mm
COS30, SIN30 = math.cos(math.radians(30)), math.sin(math.radians(30))
SCALE = 13                       # pixels per mm

PALETTE = {
    "board_top": "#1f6b3a",
    "board_side": "#14502a",
    "board_edge": "#0d3a1e",
    "silk": "#eef4f0",
    "pad": "#d9b24c",
    "trace": "#57c98a",
}

# w = size along the part's long axis, d = across it, h = height above the board
BODIES = {
    "U1":   dict(kind="module", w=48.0, d=25.4, h=1.6, stand=8.5,
                 top=(18.0, 20.0, 3.0), colour="#20303f", label="ESP32"),
    "DRV1": dict(kind="module", w=20.3, d=15.5, h=1.6, stand=8.5,
                 top=(9.0, 9.0, 2.4), colour="#8b1e2d", label="A4988"),
    "DRV2": dict(kind="module", w=20.3, d=15.5, h=1.6, stand=8.5,
                 top=(9.0, 9.0, 2.4), colour="#8b1e2d", label="A4988"),
    # the jack body reaches out over the board edge, well behind its own pins
    "J1":   dict(kind="box", w=14.0, d=9.0, h=11.0, colour="#1b1b1b", label="12V",
                 offset=(-3.6, 0.0)),
    "M1":   dict(kind="box", w=10.2, d=5.8, h=8.5, colour="#e8e2d0", label="MOT X"),
    "M2":   dict(kind="box", w=10.2, d=5.8, h=8.5, colour="#e8e2d0", label="MOT Y"),
    "CN1":  dict(kind="box", w=6.4, d=6.0, h=8.5, colour="#e8e2d0", label="LASER"),
    "U2":   dict(kind="to220", w=10.2, d=4.6, h=16.0, colour="#23272b", label="7805"),
    "Q1":   dict(kind="to220", w=10.2, d=4.6, h=16.0, colour="#23272b", label="IRFZ44N"),
    "C1":   dict(kind="cyl", dia=6.3, h=11.0, colour="#2b3a8c"),
    "C2":   dict(kind="cyl", dia=6.3, h=11.0, colour="#2b3a8c"),
    "C15":  dict(kind="cyl", dia=6.3, h=11.0, colour="#2b3a8c"),
    "C3":   dict(kind="box", w=7.0, d=3.2, h=8.0, colour="#204a86"),
    "C4":   dict(kind="box", w=5.0, d=3.0, h=6.5, colour="#204a86"),
    "C14":  dict(kind="box", w=5.0, d=3.0, h=6.5, colour="#204a86"),
    "R1":   dict(kind="axial", dia=2.3, body=6.5, colour="#c8a06a"),
    "R2":   dict(kind="axial", dia=2.3, body=6.5, colour="#c8a06a"),
    "R3":   dict(kind="axial", dia=2.3, body=6.5, colour="#c8a06a"),
    "D8":   dict(kind="cyl", dia=5.0, h=8.6, colour="#cc2222"),
}

# silkscreen name + pad count -> reference, matching the schematic
REFS = {
    ("ESP32 DEVKIT V1", 30): "U1", ("EJE X", 16): "DRV1", ("XA2_EJE_Y", 16): "DRV2",
    ("EJE X", 4): "M1", ("EJE Y", 4): "M2", ("DC_CARGADOR", 3): "J1",
    ("CN1", 2): "CN1", ("U2", 3): "U2", ("Q1", 3): "Q1",
    ("C1", 2): "C1", ("C2", 2): "C2", ("C15", 2): "C15", ("C3", 2): "C3",
    ("C4", 2): "C4", ("C14", 2): "C14", ("R1", 2): "R1", ("R2", 2): "R2",
    ("R3", 2): "R3", ("D8", 2): "D8",
}


# ---------------------------------------------------------------- geometry
VIEW = {"angle": 0.0, "ox": 35.0, "oy": 27.0}


def spin(x, y):
    """Turn the board under a fixed camera, so several views can be compared."""
    a = math.radians(VIEW["angle"])
    dx, dy = x - VIEW["ox"], y - VIEW["oy"]
    return (VIEW["ox"] + dx * math.cos(a) - dy * math.sin(a),
            VIEW["oy"] + dx * math.sin(a) + dy * math.cos(a))


def project(x, y, z):
    """Isometric view from above. sx uses (y - x) so the screen basis stays
    right-handed -- with (x - y) the board comes out mirrored."""
    xr, yr = spin(x, y)
    return ((yr - xr) * COS30, (xr + yr) * SIN30 - z)


def depth_of(x, y):
    xr, yr = spin(x, y)
    return xr + yr


def outline():
    segs = [((o.x1, o.y1), (o.x2, o.y2))
            for o in GerberFile.open(GERBER / "Gerber_BoardOutlineLayer.GKO").objects]
    pts, cur = [segs[0][0]], segs[0][1]
    used = {0}
    while len(used) < len(segs):
        for i, (a, b) in enumerate(segs):
            if i in used:
                continue
            if math.dist(a, cur) < 1e-6:
                pts.append(cur); cur = b; used.add(i); break
            if math.dist(b, cur) < 1e-6:
                pts.append(cur); cur = a; used.add(i); break
        else:
            break
    pts.append(cur)
    return pts


def pads_by_part():
    data = json.loads((GERBER / "FlyingProbeTesting.json").read_text())
    idx = {n: i for i, n in enumerate(data["pins"]["fields"])}
    groups = {}
    for row in data["pins"]["rows"]:
        if row[idx["LAYER"]] != "T":
            continue
        name = row[idx["PIN_NAME"]]
        if name.startswith("PAD"):
            continue
        ref, pin = name.rsplit("_", 1)
        xy = (row[idx["PIN_X"]] / MIL, row[idx["PIN_Y"]] / MIL)
        # two different parts are silkscreened "EJE X": the driver sits well to
        # the right of the motor header, so the x coordinate separates them
        key = (ref, "drv" if ref == "EJE X" and xy[0] > 12 else "a")
        groups.setdefault(key, {})[pin] = xy
    out = {}
    for (ref, _), pins in groups.items():
        out.setdefault((ref, len(pins)), pins)
    return out


def placement(pins, body=None):
    xs = [p[0] for p in pins.values()]
    ys = [p[1] for p in pins.values()]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    horizontal = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    ox, oy = (body or {}).get("offset", (0.0, 0.0))
    if not horizontal:
        ox, oy = oy, ox
    return cx + ox, cy + oy, horizontal


# ---------------------------------------------------------------- shading
def shade(hex_colour, factor):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    f = lambda v: max(0, min(255, int(v * factor)))
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


class Scene:
    def __init__(self):
        self.faces = []

    def add(self, pts3, colour, depth, stroke=None, width=0.05):
        flat = " ".join(f"{px:.3f},{py:.3f}" for px, py in (project(*p) for p in pts3))
        self.faces.append((depth, flat, colour, stroke, width))

    def box(self, cx, cy, z0, w, d, h, colour):
        x0, x1 = cx - w / 2, cx + w / 2
        y0, y1 = cy - d / 2, cy + d / 2
        z1 = z0 + h
        depth = depth_of(cx, cy)
        self.add([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
                 shade(colour, 0.80), depth - 0.2)
        self.add([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
                 shade(colour, 0.62), depth - 0.1)
        self.add([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
                 shade(colour, 1.0), depth)

    def cylinder(self, cx, cy, z0, dia, h, colour, sides=18):
        r, z1 = dia / 2, z0 + h
        ring = [(cx + r * math.cos(2 * math.pi * i / sides),
                 cy + r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
        depth = depth_of(cx, cy)
        for i in range(sides):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % sides]
            mx, my = (ax + bx) / 2, (ay + by) / 2
            rel = depth_of(mx, my) - depth
            if rel < 0:                      # back half is hidden by the front half
                continue
            lit = 0.55 + 0.35 * (rel + r) / (2 * r)
            self.add([(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)],
                     shade(colour, lit), depth - 0.3 + rel / 100)
        self.add([(x, y, z1) for x, y in ring], shade(colour, 1.05), depth)

    def svg_faces(self):
        for depth, pts, fill, stroke, width in sorted(self.faces, key=lambda f: f[0]):
            extra = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ""
            yield f'<polygon points="{pts}" fill="{fill}"{extra}/>'


# ---------------------------------------------------------------- artwork
def art_bounds():
    """One box covering every layer, so all of them share a flip axis."""
    boxes = [GerberFile.open(GERBER / f).bounding_box() for f in
             ("Gerber_TopLayer.GTL", "Gerber_TopSilkscreenLayer.GTO",
              "Gerber_BoardOutlineLayer.GKO")]
    return ((min(b[0][0] for b in boxes) - 1, min(b[0][1] for b in boxes) - 1),
            (max(b[1][0] for b in boxes) + 1, max(b[1][1] for b in boxes) + 1))


def layer_group(filename, colour, z, box):
    g = GerberFile.open(GERBER / filename)
    if not g.objects:
        return ""
    flip = box[0][1] + box[1][1]
    svg = str(g.to_svg(fg=colour, bg="none", force_bounds=box))
    m = re.search(r"(<g transform=.*</g>)\s*</svg>\s*$", svg, re.S)
    if not m:
        return ""
    # content arrives in SVG coords (u, v) = (x, flip - y). Sample the very same
    # projection the solid geometry uses at three points and read the affine off
    # it -- that way the artwork can never drift away from the parts.
    def at(u, v):
        return project(u, flip - v, z)

    ox, oy = at(0, 0)
    ax, ay = at(1, 0)
    bx, by = at(0, 1)
    a, b = ax - ox, ay - oy
    c, d = bx - ox, by - oy
    return (f'<g transform="matrix({a:.6f} {b:.6f} {c:.6f} {d:.6f} {ox:.6f} {oy:.6f})">'
            f"{m.group(1)}</g>")


def render_view(angle, label_all=False, only=None):
    poly = outline()
    parts = pads_by_part()
    xs_p = [q[0] for q in poly]; ys_p = [q[1] for q in poly]
    VIEW["angle"] = angle
    VIEW["ox"] = (min(xs_p) + max(xs_p)) / 2
    VIEW["oy"] = (min(ys_p) + max(ys_p)) / 2

    scene = Scene()
    top = THICK
    cx0 = sum(xs_p) / len(poly)
    cy0 = sum(ys_p) / len(poly)
    for i in range(len(poly) - 1):
        (ax, ay), (bx, by) = poly[i], poly[i + 1]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if depth_of(mx, my) < depth_of(cx0, cy0):   # far wall, hidden by the slab
            continue
        scene.add([(ax, ay, 0), (bx, by, 0), (bx, by, top), (ax, ay, top)],
                  PALETTE["board_side"], -1000 + depth_of(mx, my))
    scene.add([(x, y, top) for x, y in poly], PALETTE["board_top"], -999,
              stroke=PALETTE["board_edge"], width=0.08)

    board_faces = list(scene.svg_faces())
    abox = art_bounds()
    art = [
        layer_group("Gerber_TopLayer.GTL", PALETTE["trace"], top, abox),
        layer_group("Gerber_TopSilkscreenLayer.GTO", PALETTE["silk"], top, abox),
    ]
    scene.faces.clear()

    labels = []
    for key, ref in REFS.items():
        pins = parts.get(key)
        if not pins:
            print("sem pads:", key)
            continue
        if only is not None and ref != only:
            continue
        body = BODIES[ref]
        cx, cy, horiz = placement(pins, body)
        kind = body["kind"]
        crown = top
        if kind == "cyl":
            scene.cylinder(cx, cy, top, body["dia"], body["h"], body["colour"])
            crown = top + body["h"]
        elif kind == "axial":
            w, d = (body["body"], body["dia"]) if horiz else (body["dia"], body["body"])
            scene.box(cx, cy, top, w, d, body["dia"], body["colour"])
            crown = top + body["dia"]
        elif kind == "to220":
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            scene.box(cx, cy, top + 2.5, w, d, body["h"], body["colour"])
            crown = top + 2.5 + body["h"]
        elif kind == "module":
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            for px, py in pins.values():
                scene.box(px, py, top, 0.7, 0.7, body["stand"], "#b8b8b8")
            scene.box(cx, cy, top + body["stand"], w, d, body["h"], "#1d5c34")
            tw, td, th = body["top"]
            if not horiz:
                tw, td = td, tw
            scene.box(cx, cy, top + body["stand"] + body["h"], tw, td, th, body["colour"])
            crown = top + body["stand"] + body["h"] + th
        else:
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            scene.box(cx, cy, top, w, d, body["h"], body["colour"])
            crown = top + body["h"]
        caption = ref if label_all else body.get("label")
        if caption:
            labels.append((cx, cy, crown, caption))

    part_faces = list(scene.svg_faces())
    text = []
    for cx, cy, cz, caption in labels:
        px, py = project(cx, cy, cz)
        # paint-order is not honoured by every renderer, so the halo is a
        # separate stroke-only copy drawn underneath the filled text
        common = (f'x="{px:.2f}" y="{py - 1.6:.2f}" font-size="2.4" '
                  f'font-family="DejaVu Sans" font-weight="bold" text-anchor="middle"')
        text.append(f'<text {common} fill="none" stroke="#ffffff" '
                    f'stroke-width="0.9" stroke-linejoin="round">{caption}</text>')
        text.append(f'<text {common} fill="#1a2730">{caption}</text>')

    xs, ys = [], []
    for x, y in poly:
        for z in (0, 26):
            px, py = project(x, y, z)
            xs.append(px); ys.append(py)
    pad = 2.5
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    w, h = x1 - x0, y1 - y0
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.2f} {y0:.2f} '
            f'{w:.2f} {h:.2f}" width="{w * SCALE:.0f}" height="{h * SCALE:.0f}">'
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="#f4f6f8"/>' + "".join(board_faces) + "".join(art)
            + "".join(part_faces) + "".join(text) + "</svg>")


def render_plan(geom=None, only=None, width_px=22):
    """Top-down check: part bodies drawn translucent over the silkscreen.
    A body that does not land on its own silkscreen outline is misplaced.
    `only` restricts the drawing to a single reference; use "" for the bare board."""
    geom = geom if geom is not None else parts_geometry()
    box = art_bounds()
    (bx0, by0), (bx1, by1) = box
    flip = by0 + by1
    w, h = bx1 - bx0, by1 - by0

    def to_svg(x, y):
        return x, flip - y

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{bx0:.2f} {by0:.2f} '
           f'{w:.2f} {h:.2f}" width="{w * width_px:.0f}" height="{h * width_px:.0f}">'
           f'<rect x="{bx0:.2f}" y="{by0:.2f}" width="{w:.2f}" height="{h:.2f}" fill="white"/>']

    for fn, colour in (("Gerber_TopLayer.GTL", "#c9d6e8"),
                       ("Gerber_TopSilkscreenLayer.GTO", "#333333")):
        g = GerberFile.open(GERBER / fn)
        svg = str(g.to_svg(fg=colour, bg="none", force_bounds=box))
        m = re.search(r"(<g transform=.*</g>)\s*</svg>\s*$", svg, re.S)
        if m:
            out.append(m.group(1))

    for part in geom:
        if only is not None and part["ref"] != only:
            continue
        ref, cx, cy, horiz = part["ref"], part["cx"], part["cy"], part["horiz"]
        body = BODIES[ref]
        if body["kind"] == "cyl":
            px, py = to_svg(cx, cy)
            out.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{body["dia"] / 2:.2f}" '
                       f'fill="#e0362c" fill-opacity="0.30" stroke="#b0231a" '
                       f'stroke-width="0.18"/>')
        else:
            if body["kind"] == "axial":
                bw, bd = body["body"], body["dia"]
            else:
                bw, bd = body["w"], body["d"]
            if not horiz:
                bw, bd = bd, bw
            px, py = to_svg(cx - bw / 2, cy + bd / 2)
            out.append(f'<rect x="{px:.2f}" y="{py:.2f}" width="{bw:.2f}" '
                       f'height="{bd:.2f}" fill="#e0362c" fill-opacity="0.30" '
                       f'stroke="#b0231a" stroke-width="0.18"/>')
        lx, ly = to_svg(cx, cy)
        for fill, stroke, sw in (("none", "#ffffff", 0.8), ("#8a1008", "none", 0)):
            extra = f' stroke="{stroke}" stroke-width="{sw}"' if stroke != "none" else ""
            out.append(f'<text x="{lx:.2f}" y="{ly + 0.7:.2f}" font-size="2" '
                       f'font-family="DejaVu Sans" font-weight="bold" '
                       f'text-anchor="middle" fill="{fill}"{extra}>{ref}</text>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------- one part at a time
def parts_geometry():
    """Every part reduced to plain boxes and cylinders, so the isometric, plan
    and elevation views all draw from one single description."""
    parts = pads_by_part()
    out = []
    for key, ref in REFS.items():
        pins = parts.get(key)
        if not pins:
            continue
        body = BODIES[ref]
        cx, cy, horiz = placement(pins, body)
        kind = body["kind"]
        solids = []
        if kind == "cyl":
            solids.append(dict(shape="cyl", cx=cx, cy=cy, z=THICK,
                               dia=body["dia"], h=body["h"], colour=body["colour"]))
        elif kind == "axial":
            w, d = (body["body"], body["dia"]) if horiz else (body["dia"], body["body"])
            solids.append(dict(shape="box", cx=cx, cy=cy, z=THICK, w=w, d=d,
                               h=body["dia"], colour=body["colour"]))
        elif kind == "to220":
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            solids.append(dict(shape="box", cx=cx, cy=cy, z=THICK + 2.5, w=w, d=d,
                               h=body["h"], colour=body["colour"]))
        elif kind == "module":
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            for px, py in pins.values():
                solids.append(dict(shape="box", cx=px, cy=py, z=THICK, w=0.7, d=0.7,
                                   h=body["stand"], colour="#b8b8b8"))
            solids.append(dict(shape="box", cx=cx, cy=cy, z=THICK + body["stand"],
                               w=w, d=d, h=body["h"], colour="#1d5c34"))
            tw, td, th = body["top"]
            if not horiz:
                tw, td = td, tw
            solids.append(dict(shape="box", cx=cx, cy=cy,
                               z=THICK + body["stand"] + body["h"],
                               w=tw, d=td, h=th, colour=body["colour"]))
        else:
            w, d = (body["w"], body["d"]) if horiz else (body["d"], body["w"])
            solids.append(dict(shape="box", cx=cx, cy=cy, z=THICK, w=w, d=d,
                               h=body["h"], colour=body["colour"]))
        top_z = max(sd["z"] + sd.get("h", 0) for sd in solids)
        out.append(dict(ref=ref, cx=cx, cy=cy, horiz=horiz, pins=pins,
                        solids=solids, top=top_z))
    return out


# camera axes for the four straight-on side views
ELEVATIONS = {
    "frente": dict(title="VISTA FRONTAL  (olhando de Y-)",
                   sx=lambda x, y: x, depth=lambda x, y: -y),
    "tras":   dict(title="VISTA TRASEIRA  (olhando de Y+)",
                   sx=lambda x, y: -x, depth=lambda x, y: y),
    "esq":    dict(title="VISTA ESQUERDA  (olhando de X-)",
                   sx=lambda x, y: y, depth=lambda x, y: -x),
    "dir":    dict(title="VISTA DIREITA  (olhando de X+)",
                   sx=lambda x, y: -y, depth=lambda x, y: x),
}


def render_elevation(which, geom, only=None, width=560, height=260):
    """Straight-on side view: the camera sits at board level, not above it.
    Heights read true here, which an isometric view can never give you."""
    cam = ELEVATIONS[which]
    poly = outline()
    xs = [cam["sx"](x, y) for x, y in poly]
    bx0, bx1 = min(xs), max(xs)

    items = []
    # the board itself, seen edge-on
    items.append((-1e9, f'<rect x="{bx0:.2f}" y="{-THICK:.2f}" width="{bx1 - bx0:.2f}" '
                        f'height="{THICK:.2f}" fill="#1f6b3a" stroke="#0d3a1e" '
                        f'stroke-width="0.15"/>'))
    for part in geom:
        dim = only is not None and part["ref"] != only
        for sd in part["solids"]:
            half = (sd["dia"] / 2 if sd["shape"] == "cyl"
                    else (sd["w"] if which in ("frente", "tras") else sd["d"]) / 2)
            cxs = cam["sx"](sd["cx"], sd["cy"])
            x0 = cxs - half
            colour = sd["colour"]
            opacity = 0.12 if dim else 1.0
            items.append((cam["depth"](sd["cx"], sd["cy"]),
                          f'<rect x="{x0:.2f}" y="{-(sd["z"] + sd["h"]):.2f}" '
                          f'width="{half * 2:.2f}" height="{sd["h"]:.2f}" '
                          f'fill="{colour}" fill-opacity="{opacity}" '
                          f'stroke="#000000" stroke-opacity="{opacity * 0.45:.2f}" '
                          f'stroke-width="0.12"/>'))
        if not dim:
            cxs = cam["sx"](part["cx"], part["cy"])
            items.append((1e9, f'<text x="{cxs:.2f}" y="{-(part["top"] + 1.4):.2f}" '
                               f'font-size="2.6" font-family="DejaVu Sans" '
                               f'font-weight="bold" text-anchor="middle" '
                               f'fill="#1a2730">{part["ref"]}</text>'))

    top_z = max([p["top"] for p in geom] + [THICK]) + 6
    pad = 2
    vx, vw = bx0 - pad, (bx1 - bx0) + 2 * pad
    vy, vh = -top_z, top_z + THICK + pad
    body = "".join(el for _, el in sorted(items, key=lambda it: it[0]))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx:.2f} {vy:.2f} '
            f'{vw:.2f} {vh:.2f}" width="{width}" height="{height}">'
            f'<rect x="{vx:.2f}" y="{vy:.2f}" width="{vw:.2f}" height="{vh:.2f}" '
            f'fill="#fafbfc"/>'
            f'<line x1="{vx:.2f}" y1="0" x2="{vx + vw:.2f}" y2="0" '
            f'stroke="#c7d0d6" stroke-width="0.12"/>{body}</svg>')


def nest(svg, x, y, w, h):
    """Drop a finished drawing into a bigger sheet, keeping its aspect ratio."""
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    body = svg[svg.index(">", svg.index("<svg")) + 1: svg.rindex("</svg>")]
    return (f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{vb}" '
            f'preserveAspectRatio="xMidYMid meet">{body}</svg>')


def caption(x, y, txt, size=26, weight="bold", fill="#1a2730"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-family="DejaVu Sans" '
            f'font-weight="{weight}" fill="{fill}">{txt}</text>')


def render_sheet():
    """One sheet: the placement plan, plus the board seen from four corners."""
    W, H = 2400, 1960
    plan_w, plan_h = 1480, 1150
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="#ffffff"/>',
           caption(40, 52, "Controladora CNC / Laser ESP32 - prancha de vistas", 34),
           caption(40, 84, "Posicoes vindas do Gerber. Alturas e formatos dos corpos "
                           "sao os tipicos de cada encapsulamento.", 20, "normal", "#5a6b76")]

    out.append(caption(40, 132, "1 - VISTA DE TOPO / POSICIONAMENTO", 24))
    out.append(f'<rect x="40" y="146" width="{plan_w}" height="{plan_h}" fill="none" '
               f'stroke="#c7d0d6" stroke-width="2"/>')
    out.append(nest(render_plan(), 40, 146, plan_w, plan_h))

    lx = 40 + plan_w + 40
    out.append(caption(lx, 132, "LEGENDA", 24))
    rows = [
        ("U1", "ESP32 DEVKIT V1 - modulo de 30 pinos"),
        ("DRV1 / DRV2", "Drivers de passo A4988 - eixos X e Y"),
        ("M1 / M2", "Conectores dos motores X e Y"),
        ("U2", "Regulador LM7805 - 12 V para 5 V"),
        ("Q1", "MOSFET IRFZ44N - chaveia o laser"),
        ("CN1", "Conector do modulo laser"),
        ("J1", "Jack DC de 12 V"),
        ("C1 / C2 / C15", "Eletroliticos de 100 uF"),
        ("C3 / C4 / C14", "470 nF e 100 nF"),
        ("R1 / R2 / R3", "Resistores de 10 k"),
        ("D8", "LED indicador de alimentacao"),
    ]
    y = 190
    for ref, desc in rows:
        out.append(caption(lx, y, ref, 21))
        out.append(caption(lx + 190, y, desc, 19, "normal", "#3b4a55"))
        y += 34
    y += 18
    out.append(caption(lx, y, "OBSERVACAO", 21, "bold", "#8a1008"))
    y += 30
    for line in ["C1 e C2 ficam por baixo dos drivers A4988:",
                 "os modulos sobem cerca de 8,5 mm nos pinos,",
                 "entao os eletroliticos cabem debaixo deles.",
                 "",
                 "O corpo do jack J1 avanca para fora da borda",
                 "da placa, atras dos proprios pinos."]:
        out.append(caption(lx, y, line, 18, "normal", "#3b4a55"))
        y += 26

    views = [(0, "2 - CANTO FRONTAL"), (90, "3 - GIRADO 90 GRAUS"),
             (180, "4 - GIRADO 180 GRAUS"), (270, "5 - GIRADO 270 GRAUS")]
    vw, vh = 560, 500
    for i, (angle, title) in enumerate(views):
        x = 40 + i * (vw + 32)
        out.append(caption(x, 1360, title, 22))
        out.append(f'<rect x="{x}" y="1375" width="{vw}" height="{vh}" fill="#fafbfc" '
                   f'stroke="#c7d0d6" stroke-width="2"/>')
        out.append(nest(render_view(angle, label_all=True), x, 1375, vw, vh))
    out.append("</svg>")
    return "".join(out)


def render_step(geom, only, title, subtitle):
    """One page of the placement walk-through: the bare board plus a single
    part, seen from the top and from all four sides."""
    W, H = 1900, 1500
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="#ffffff"/>',
           caption(36, 46, title, 30),
           caption(36, 78, subtitle, 19, "normal", "#5a6b76")]

    pw, ph = 1180, 920
    out.append(caption(36, 118, "TOPO", 21))
    out.append(f'<rect x="36" y="130" width="{pw}" height="{ph}" fill="none" '
               f'stroke="#c7d0d6" stroke-width="2"/>')
    out.append(nest(render_plan(geom, only), 36, 130, pw, ph))

    ix = 36 + pw + 30
    iw, ih = 600, 470
    out.append(caption(ix, 118, "PERSPECTIVA", 21))
    out.append(f'<rect x="{ix}" y="130" width="{iw}" height="{ih}" fill="#fafbfc" '
               f'stroke="#c7d0d6" stroke-width="2"/>')
    out.append(nest(render_view(0, label_all=True, only=only), ix, 130, iw, ih))

    ey, eh = 1090, 170
    for i, which in enumerate(("frente", "tras", "esq", "dir")):
        col, row = i % 2, i // 2
        x = 36 + col * (930)
        y = ey + row * (eh + 52)
        out.append(caption(x, y - 10, ELEVATIONS[which]["title"], 19))
        out.append(f'<rect x="{x}" y="{y}" width="900" height="{eh}" fill="none" '
                   f'stroke="#c7d0d6" stroke-width="2"/>')
        out.append(nest(render_elevation(which, geom, only), x, y, 900, eh))
    out.append("</svg>")
    return "".join(out)


def save(path, svg):
    path.write_text(svg)
    try:
        import cairosvg
        cairosvg.svg2png(url=str(path), write_to=str(path.with_suffix(".png")),
                         output_width=1900, background_color="white")
    except ImportError:
        pass
    print("escrito", path.relative_to(ROOT))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", action="store_true",
                    help="gera as quatro vistas, rotuladas com a referencia de cada peca")
    ap.add_argument("--plan", action="store_true",
                    help="vista de topo com os corpos sobre a serigrafia, para conferir")
    ap.add_argument("--sheet", action="store_true",
                    help="prancha com a vista de topo e quatro angulos")
    ap.add_argument("--steps", action="store_true",
                    help="uma pagina por peca: placa nua, depois cada peca sozinha")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    save(OUT / "board-3d.svg", render_view(0))
    if args.steps:
        geom = parts_geometry()
        order = ["U1", "DRV1", "DRV2", "M1", "M2", "J1", "CN1", "U2", "Q1",
                 "C1", "C2", "C15", "C3", "C4", "C14", "R1", "R2", "R3", "D8"]
        geom = sorted(geom, key=lambda g: order.index(g["ref"]))
        steps = OUT / "posicionamento"
        steps.mkdir(exist_ok=True)
        save(steps / "00-placa-nua.svg",
             render_step(geom, "", "PASSO 0 - PLACA NUA",
                         "So o cobre e a serigrafia. Nenhuma peca colocada ainda."))
        for i, part in enumerate(geom, start=1):
            ref = part["ref"]
            save(steps / f"{i:02d}-{ref}.svg",
                 render_step(geom, ref, f"PASSO {i} - {ref}",
                             "Placa nua mais uma unica peca, para conferir a posicao "
                             "sem as outras atrapalhando."))
    if args.sheet:
        save(OUT / "board-views.svg", render_sheet())
    if args.plan:
        save(OUT / "board-plan-check.svg", render_plan())
    if args.views:
        for angle in (0, 90, 180, 270):
            save(OUT / f"board-3d-{angle:03d}.svg", render_view(angle, label_all=True))


if __name__ == "__main__":
    main()
