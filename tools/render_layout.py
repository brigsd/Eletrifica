#!/usr/bin/env python3
"""Render the Gerber package as a PCB layout drawing.

Draws the board the way a layout view usually looks: silkscreen underneath,
copper traces over it, pads on top, board outline last. Every layer is rendered
through the same forced bounding box so they line up exactly when stacked.

    python3 tools/render_layout.py            # both faces on one drawing
    python3 tools/render_layout.py --split    # one drawing per face as well
"""
import argparse
import re
from pathlib import Path

from gerbonara import GerberFile

ROOT = Path(__file__).resolve().parent.parent
GERBER = ROOT / "gerber"
OUT = ROOT / "docs"

LAYERS = {
    "outline": "Gerber_BoardOutlineLayer.GKO",
    "silk": "Gerber_TopSilkscreenLayer.GTO",
    "top": "Gerber_TopLayer.GTL",
    "bottom": "Gerber_BottomLayer.GBL",
}

STYLE = {
    "board_fill": "#fbfbf7",
    "outline": "#9aa0a6",
    "silk": "#6b7280",
    "trace_top": "#1b2a6b",
    "trace_bottom": "#3559c7",
    "pour_top": "#e8ecf9",
    "pour_bottom": "#eef1fb",
    "pad": "#1f8a3b",
}

MARGIN = 1.5


def inner(svg_text):
    """Strip the <svg> wrapper, keeping the drawing content and its transform."""
    m = re.search(r"(<g transform=.*</g>)\s*</svg>\s*$", svg_text, re.S)
    return m.group(1) if m else ""


def load(name):
    return GerberFile.open(GERBER / LAYERS[name])


def bounds():
    """Box covering every layer, so nothing drawn outside the board edge is cut."""
    boxes = [load(n).bounding_box() for n in LAYERS]
    x0 = min(b[0][0] for b in boxes); y0 = min(b[0][1] for b in boxes)
    x1 = max(b[1][0] for b in boxes); y1 = max(b[1][1] for b in boxes)
    return ((x0 - MARGIN, y0 - MARGIN), (x1 + MARGIN, y1 + MARGIN))


def board_rect(box):
    """Outline bbox in SVG coordinates (the Gerber y axis points the other way)."""
    (bx0, by0), (bx1, by1) = load("outline").bounding_box()
    flip = box[0][1] + box[1][1]
    return (bx0, flip - by1), (bx1, flip - by0)


def render(layer, colour, box, keep=None):
    """Render one layer, optionally only the objects `keep` selects."""
    g = load(layer)
    if keep is not None:
        g.objects = [o for o in g.objects if keep(o)]
    if not g.objects:
        return ""
    return inner(str(g.to_svg(fg=colour, bg="none", force_bounds=box)))


def is_pad(o):
    return type(o).__name__ == "Flash"


def is_pour(o):
    """Region objects are the copper pours -- the ground planes on this board."""
    return type(o).__name__ == "Region"


def is_trace(o):
    return type(o).__name__ in ("Line", "Arc")


def build(faces, box, with_silk=True, pour=False):
    (x0, y0), (x1, y1) = box
    w, h = x1 - x0, y1 - y0
    (bx0, by0), (bx1, by1) = board_rect(box)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}" '
        f'width="{w * 26:.0f}" height="{h * 26:.0f}">',
        f'<rect x="{x0:.3f}" y="{y0:.3f}" width="{w:.3f}" height="{h:.3f}" fill="white"/>',
        f'<rect x="{bx0:.3f}" y="{by0:.3f}" width="{bx1 - bx0:.3f}" '
        f'height="{by1 - by0:.3f}" rx="1.0" fill="{STYLE["board_fill"]}"/>',
    ]
    if pour:
        for face in faces:
            parts.append(render(face, STYLE[f"pour_{face}"], box, keep=is_pour))
    for face in faces:
        parts.append(render(face, STYLE[f"trace_{face}"], box, keep=is_trace))
    for face in faces:
        parts.append(render(face, STYLE["pad"], box, keep=is_pad))
    if with_silk:
        parts.append(render("silk", STYLE["silk"], box))
    parts.append(render("outline", STYLE["outline"], box))
    parts.append("</svg>")
    return "\n".join(p for p in parts if p)


def write(path, svg):
    path.write_text(svg)
    try:
        import cairosvg

        cairosvg.svg2png(url=str(path), write_to=str(path.with_suffix(".png")),
                         output_width=2400, background_color="white")
    except ImportError:
        pass
    print("escrito", path.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", action="store_true",
                    help="tambem gera um desenho por face")
    ap.add_argument("--pour", action="store_true",
                    help="desenha os planos de cobre em tom claro")
    args = ap.parse_args()

    box = bounds()
    OUT.mkdir(exist_ok=True)
    write(OUT / "layout.svg", build(["bottom", "top"], box, pour=args.pour))
    if args.split:
        write(OUT / "layout-top.svg", build(["top"], box, pour=args.pour))
        write(OUT / "layout-bottom.svg", build(["bottom"], box, pour=args.pour))


if __name__ == "__main__":
    main()
