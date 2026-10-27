"""Onde cabe cada coisa na base: busca de área livre fora das peças."""
import math


class Ocupacao:
    """Retângulos alinhados aos eixos já ocupados na base (mm)."""

    def __init__(self, largura, profundidade, margem_mm=1.0):
        self.largura, self.profundidade, self.margem = largura, profundidade, margem_mm
        self.retangulos = []           # (x0, y0, x1, y1, dono)

    def ocupar_poligono(self, pontos, dono):
        xs, ys = [p[0] for p in pontos], [p[1] for p in pontos]
        self.retangulos.append((min(xs), min(ys), max(xs), max(ys), dono))

    def ocupar(self, cx, cy, w, h, dono):
        self.retangulos.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, dono))

    def livre(self, cx, cy, w, h):
        m = self.margem
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        if x0 < m or y0 < m or x1 > self.largura - m or y1 > self.profundidade - m:
            return False
        for a0, b0, a1, b1, _ in self.retangulos:
            if x0 < a1 + m and x1 > a0 - m and y0 < b1 + m and y1 > b0 - m:
                return False
        return True

    def colocar(self, alvo, w, h, dono, passo=0.5, raio_max=120.0):
        """Centro livre mais próximo de `alvo`; ocupa e devolve (x, y)."""
        ax, ay = alvo
        r = 0.0
        while r <= raio_max:
            n = max(1, int(2 * math.pi * r / passo))
            candidatos = [(ax + r * math.cos(2 * math.pi * i / n),
                           ay + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
            for cx, cy in candidatos:
                if self.livre(cx, cy, w, h):
                    self.ocupar(cx, cy, w, h, dono)
                    return round(cx, 2), round(cy, 2)
            r += passo
        raise RuntimeError(f"sem lugar livre para {dono} perto de {alvo}")

    def sobre(self, cx, cy, w, h, tipo_dono=None):
        """Donos dos retângulos que este retângulo invade (sem margem)."""
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        return [d for a0, b0, a1, b1, d in self.retangulos
                if x0 < a1 and x1 > a0 and y0 < b1 and y1 > b0]


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
