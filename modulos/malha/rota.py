"""Rota determinística por dimensão: anda primeiro em X, depois em Y.

Cada salto passa por um segmento intermediário; a rota é a lista de ligações
percorridas, na ordem. Mesma origem e destino dão rota vazia (zero saltos).
"""
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
