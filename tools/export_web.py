#!/usr/bin/env python3
"""Export the board for the interactive viewer published on GitHub Pages.

Writes web/board.json (geometry plus what each part does and how it is wired)
and web/board-texture.png (the bare board, used as the texture of its top face).
Everything comes from the same model the printed drawings use, so the page can
never drift away from them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render_3d as R
from gen_schematic import PARTS, RENAME, load_netlist

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

GROUPS = {
    "U1": "Controle", "DRV1": "Eixos", "DRV2": "Eixos", "M1": "Eixos", "M2": "Eixos",
    "J1": "Alimentacao", "U2": "Alimentacao", "C1": "Alimentacao", "C2": "Alimentacao",
    "C15": "Alimentacao", "C3": "Alimentacao", "C4": "Alimentacao",
    "C14": "Alimentacao", "D8": "Alimentacao", "R3": "Alimentacao",
    "Q1": "Laser", "R1": "Laser", "R2": "Laser", "CN1": "Laser",
}

INFO = {
    "U1": ("ESP32 DEVKIT V1",
           "O cerebro da placa. Gera os pulsos STEP e o sentido DIR de cada eixo, "
           "habilita os dois drivers por um unico pino EN, e controla a potencia do "
           "laser por PWM no GPIO13. Recebe 5 V no VIN e devolve 3,3 V, que alimenta "
           "a logica dos drivers. Usa 6 dos seus 30 pinos."),
    "DRV1": ("Driver de passo A4988 - eixo X",
             "Converte cada pulso de STEP em um passo do motor. Esta em passo inteiro: "
             "MS1, MS2 e MS3 estao ligados ao GND. RESET e SLEEP estao em 3,3 V, que e "
             "a ligacao que mantem o driver acordado. A corrente da bobina se ajusta no "
             "trimpot Vref do proprio modulo."),
    "DRV2": ("Driver de passo A4988 - eixo Y",
             "Identico ao do eixo X, na mesma configuracao de passo inteiro. Compartilha "
             "o pino EN com o outro driver, entao nao da para desabilitar um eixo sozinho."),
    "M1": ("Conector do motor X",
           "Saida das duas bobinas do motor de passo do eixo X: 1A/1B e 2A/2B. "
           "Quatro vias com passo de 2,54 mm."),
    "M2": ("Conector do motor Y",
           "Mesma coisa do eixo X, para o motor do eixo Y."),
    "J1": ("Jack DC de 12 V",
           "Entrada de alimentacao. Os 12 V vao direto para o VMOT dos dois drivers e "
           "para a entrada do regulador. O terceiro pino do jack, que e o contato de "
           "comutacao, nao esta ligado a nada. O corpo do jack avanca para fora da "
           "borda da placa."),
    "U2": ("Regulador LM7805",
           "Derruba os 12 V para 5 V. Alimenta o VIN do ESP32 e o positivo do laser. "
           "A queda de 7 V vira calor: cada 100 mA de consumo dissipam 0,7 W aqui, e "
           "nao existe area de dissipacao no layout."),
    "Q1": ("MOSFET IRFZ44N",
           "Chaveia o lado negativo do laser. ATENCAO: o source dele nao chega ao GND "
           "em nenhuma camada de cobre, entao o transistor nao fecha circuito e o laser "
           "nao acende. Alem disso o IRFZ44N nao e de nivel logico: os 3,3 V do GPIO "
           "mal passam do limiar de conducao."),
    "R1": ("Resistor 10 k",
           "Liga o gate do Q1 ao source, para o gate nao ficar solto quando o GPIO "
           "estiver em alta impedancia."),
    "R2": ("Resistor 10 k",
           "Em serie entre o GPIO13 e o gate do Q1. Com a capacitancia de entrada do "
           "IRFZ44N isso da uma constante de tempo perto de 15 us, o que limita "
           "bastante o PWM."),
    "CN1": ("Conector do laser",
            "Duas vias: o positivo vem do trilho de 5 V e o negativo passa pelo Q1."),
    "C1": ("Eletrolitico 100 uF",
           "Reservatorio no trilho de 12 V. Fica por baixo do driver do eixo Y."),
    "C2": ("Eletrolitico 100 uF",
           "Reservatorio no trilho de 12 V. Fica por baixo do driver do eixo X."),
    "C15": ("Eletrolitico 100 uF",
            "Reservatorio na entrada do regulador."),
    "C3": ("Capacitor 470 nF",
           "Capacitor de entrada do LM7805."),
    "C4": ("Capacitor 100 nF",
           "Capacitor de saida do LM7805. E o unico capacitor do trilho de 5 V: nao ha "
           "nenhum eletrolitico de reservatorio nesse trilho."),
    "C14": ("Capacitor 100 nF",
            "Desacoplamento no trilho de 12 V."),
    "R3": ("Resistor 10 k",
           "Em serie com o LED indicador. Com 12 V da cerca de 1 mA, o que acende "
           "fraco."),
    "D8": ("LED indicador",
           "Mostra que a placa esta alimentada. Ligado no trilho de 12 V atraves do R3."),
}


def nets_by_ref():
    raw = load_netlist()
    ref_of = {key: meta["ref"] for key, meta in PARTS.items()}
    out = {}
    for key, pins in raw.items():
        if key not in ref_of:
            continue
        for pin, net in pins.items():
            net = RENAME.get(net, net)
            if net.startswith("NET_"):
                net = "(sem ligacao)"
            out.setdefault(ref_of[key], []).append((int(pin), net))
    return {ref: sorted(v) for ref, v in out.items()}


def main():
    WEB.mkdir(exist_ok=True)
    geom = R.parts_geometry()
    nets = nets_by_ref()
    (bx0, by0), (bx1, by1) = R.art_bounds()

    parts = []
    for part in geom:
        ref = part["ref"]
        title, desc = INFO[ref]
        pin_rows = nets.get(ref, [])
        parts.append(dict(
            ref=ref, title=title, desc=desc,
            group=GROUPS.get(ref, "Outros"),
            solids=part["solids"],
            top=part["top"],
            pins=[dict(n=n, net=net) for n, net in pin_rows],
            pin_xy=[[round(x, 3), round(y, 3)] for x, y in part["pins"].values()],
        ))

    clearance = [dict(module=m, part=o, top=round(t, 2), gap=round(g, 2),
                      overlap=round(d, 2))
                 for m, o, t, g, d in R.clearance_report(geom) if d > 0]

    data = dict(
        board=dict(outline=[[round(x, 3), round(y, 3)] for x, y in R.outline()],
                   thickness=R.THICK,
                   texture_box=[bx0, by0, bx1, by1]),
        parts=parts,
        clearance=clearance,
    )
    (WEB / "board.json").write_text(json.dumps(data, separators=(",", ":")))
    print("escrito web/board.json", len(parts), "pecas")

    svg = R.render_top(geom, only="", width_px=40)
    (WEB / "board-texture.svg").write_text(svg)
    try:
        import cairosvg
        cairosvg.svg2png(url=str(WEB / "board-texture.svg"),
                        write_to=str(WEB / "board-texture.png"), output_width=2048)
        print("escrito web/board-texture.png")
    except ImportError:
        print("cairosvg ausente: converta a textura manualmente")


if __name__ == "__main__":
    main()
