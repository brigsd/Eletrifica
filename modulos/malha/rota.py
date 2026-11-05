"""Rota determinística por dimensão: anda primeiro em X, depois em Y.

Cada salto passa por um segmento intermediário; a rota é a lista de ligações
percorridas, na ordem. Mesma origem e destino dão rota vazia (zero saltos).
"""
import math

from modulos.malha.topologia import ligacao


def rota_xy(malha, origem, destino):
    """Devolve (ligacoes, saltos) do caminho de origem até destino."""
    for s in (origem, destino):
        if not malha.contem(s):
            raise ValueError(f"segmento {s} fora da malha {malha.colunas}x{malha.linhas}")
    ligacoes = []
    x, y = origem
    tx, ty = destino
    while x != tx:
        prox = (x + (1 if tx > x else -1), y)
        ligacoes.append(ligacao((x, y), prox))
        x, y = prox
    while y != ty:
        prox = (x, y + (1 if ty > y else -1))
        ligacoes.append(ligacao((x, y), prox))
        x, y = prox
    return ligacoes, len(ligacoes)


def _verificar(malha, origem, destino):
    for s in (origem, destino):
        if not malha.contem(s):
            raise ValueError(f"segmento {s} fora da malha {malha.colunas}x{malha.linhas}")


def rota_yx(malha, origem, destino):
    """Como `rota_xy`, mas anda primeiro em Y, depois em X (outro caminho mínimo)."""
    _verificar(malha, origem, destino)
    ligacoes = []
    x, y = origem
    tx, ty = destino
    while y != ty:
        prox = (x, y + (1 if ty > y else -1))
        ligacoes.append(ligacao((x, y), prox))
        x, y = prox
    while x != tx:
        prox = (x + (1 if tx > x else -1), y)
        ligacoes.append(ligacao((x, y), prox))
        x, y = prox
    return ligacoes, len(ligacoes)


def caminhos(malha, origem, destino, modo="xy"):
    """Lista de (ligacoes, fracao) do fluxo. Modos: "xy", "yx" ou "dividida".

    "dividida" parte o fluxo meio a meio entre XY e YX; os dois são caminhos
    mínimos, com o mesmo número de saltos (o atraso é igual nas duas partes).
    Se origem e destino estão na mesma linha ou coluna, só há um caminho.
    """
    if modo == "xy":
        return [(rota_xy(malha, origem, destino)[0], 1.0)]
    if modo == "yx":
        return [(rota_yx(malha, origem, destino)[0], 1.0)]
    if modo == "dividida":
        a, b = rota_xy(malha, origem, destino)[0], rota_yx(malha, origem, destino)[0]
        if a == b:
            return [(a, 1.0)]
        return [(a, 0.5), (b, 0.5)]
    raise ValueError(f"modo de rota desconhecido: {modo!r}")


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def rota_com_expressa(malha, origem, destino, expressa, modo="xy"):
    """Caminho que usa a ligação expressa: origem -> ponta -> (expressa) -> ponta -> destino.

    A ponta mais perto da origem é a entrada. Devolve [(ligacoes, fracao)], onde a
    expressa aparece como uma ligação só na lista (1 salto).
    """
    _verificar(malha, origem, destino)
    exp = ligacao(*expressa)
    if exp not in malha.expressas:
        raise ValueError(f"{exp} não é uma ligação expressa desta malha")
    p, q = exp
    if _dist(origem, p) + _dist(q, destino) > _dist(origem, q) + _dist(p, destino):
        p, q = q, p
    saida = []
    for ant, frac_a in caminhos(malha, origem, p, modo):
        for post, frac_b in caminhos(malha, q, destino, modo):
            saida.append((ant + [exp] + post, frac_a * frac_b))
    return saida
