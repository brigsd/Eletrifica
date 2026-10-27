"""Gráficos SVG estáticos para os relatórios, legíveis em tema claro e escuro.

Cores por papel (superfície, texto, grade, série 1, série 2), com as versões
escuras trocadas por `prefers-color-scheme` dentro do próprio SVG.
"""
import math

ESTILO = """
<style>
  .sup { fill: #fcfcfb; } .grade { stroke: #e4e3df; } .l1 { stroke: #2a78d6; } .l2 { stroke: #eb6834; }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 12px; fill: #52514e; }
  .titulo { font-size: 14px; font-weight: 600; fill: #0b0b0b; } .rot { fill: #0b0b0b; }
  @media (prefers-color-scheme: dark) {
    .sup { fill: #1a1a19; } .grade { stroke: #33322f; } .l1 { stroke: #3987e5; } .l2 { stroke: #d95926; }
    text { fill: #c3c2b7; } .titulo, .rot { fill: #f0efec; }
  }
</style>"""

SLOTS = ("l1", "l2")


def _passos(v0, v1, n=5):
    if v1 <= v0:
        v1 = v0 + 1
    bruto = (v1 - v0) / n
    mag = 10 ** math.floor(math.log10(bruto))
    passo = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= bruto), default=10 * mag)
    ini = math.floor(v0 / passo) * passo
    out, v = [ini], ini
    while v < v1 - passo * 1e-9:
        v += passo
        out.append(round(v, 10))
    return out


def _fmt(v):
    if v == 0:
        return "0"
    if abs(v) >= 100 or float(v).is_integer():
        return f"{v:.0f}".replace("-", "−")
    return f"{v:.2g}".replace(".", ",").replace("-", "−")


def linhas(series, titulo, rotulo_x, rotulo_y, largura=640, altura=300, y_lim=None,
           x_lim=None, alpha=1.0, espessura=2.0):
    """series: lista de (nome, xs, ys). Até duas séries nomeadas; com mais, desenha
    todas na cor da série 1 (uso: diagrama de olho)."""
    legenda = len(series) == 2
    me, md, mt, mb = 58, 18, (58 if legenda else 40), 46
    w, h = largura - me - md, altura - mt - mb
    xs_all = [x for _, xs, _ in series for x in xs]
    ys_all = [y for _, _, ys in series for y in ys]
    x0, x1 = x_lim or (min(xs_all), max(xs_all))
    yt = _passos(*(y_lim or (min(ys_all), max(ys_all))))
    y0, y1 = (y_lim if y_lim else (yt[0], yt[-1]))
    xt = _passos(x0, x1)
    xt = [v for v in xt if x0 - 1e-9 <= v <= x1 + 1e-9]
    yt = [v for v in yt if y0 - 1e-9 <= v <= y1 + 1e-9]
    X = lambda v: me + (v - x0) / (x1 - x0) * w
    Y = lambda v: mt + h - (v - y0) / (y1 - y0) * h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
           f'width="{largura}" height="{altura}" role="img" aria-label="{titulo}">', ESTILO,
           f'<rect class="sup" width="{largura}" height="{altura}" rx="8"/>',
           f'<text class="titulo" x="{me}" y="24">{titulo}</text>']
    for v in yt:
        out.append(f'<line class="grade" x1="{me}" x2="{me + w}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" '
                   f'stroke-width="1"/>')
        out.append(f'<text x="{me - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
    for v in xt:
        out.append(f'<text x="{X(v):.1f}" y="{mt + h + 18}" text-anchor="middle">{_fmt(v)}</text>')
    out.append(f'<text x="{me + w / 2}" y="{altura - 8}" text-anchor="middle">{rotulo_x}</text>')
    out.append(f'<text x="14" y="{mt + h / 2}" text-anchor="middle" '
               f'transform="rotate(-90 14 {mt + h / 2})">{rotulo_y}</text>')

    nomeadas = len(series) <= 2
    for k, (nome, xs, ys) in enumerate(series):
        cor = SLOTS[k] if nomeadas else SLOTS[0]
        pts = " ".join(f"{X(x):.1f},{Y(min(max(y, y0), y1)):.1f}"
                       for x, y in zip(xs, ys) if x0 <= x <= x1)
        out.append(f'<polyline class="{cor}" points="{pts}" fill="none" '
                   f'stroke-width="{espessura}" stroke-linejoin="round" opacity="{alpha}"/>')
    if legenda:
        lx = me
        for k, (nome, _, _) in enumerate(series):
            out.append(f'<line class="{SLOTS[k]}" x1="{lx}" x2="{lx + 16}" y1="40" y2="40" '
                       f'stroke-width="3" stroke-linecap="round"/>')
            out.append(f'<text class="rot" x="{lx + 22}" y="44">{nome}</text>')
            lx += 7 * len(nome) + 46
    out.append("</svg>")
    return "\n".join(out)
