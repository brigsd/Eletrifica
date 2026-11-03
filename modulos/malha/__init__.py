"""Vetor minhoca: malha de segmentos iguais, com dados de vizinho em vizinho.

Cada segmento tem um tradutor com controle local. A rota entre dois segmentos é
decidida no tradutor, salto a salto, por regra fixa (primeiro X, depois Y). Como
as memórias exigem atraso fixo, a rota é reservada no boot: circuito fixo, sem fila.
"""
