"""Quatro alternativas para a malha, medidas pelas mesmas regras (R21 atraso, R22 ocupação).

    1. fibra_gigante      ligações expressas que pulam vários segmentos de uma vez
    2. ligacoes_largas    capacidade por ligação ajustada onde precisa (e, opcional,
                          peça grande: a GPU ocupa vários segmentos)
    3. rotas_espalhadas   cada fluxo dividido entre XY e YX (mesmos saltos)
    4. memoria_colada     chips de memória vizinhos da GPU (fluxo de 1 salto)

Cada função parte do `plano` e da `base` reais e devolve o mesmo dicionário de
`montar.avaliar`, com `resumo` acrescido de `erros_r21`/`erros_r22` (o que o
verificador daria) e a chave `extras` (o que a alternativa custou). `combinar`
junta as alternativas na ordem: colada, peça grande, expressas, espalhadas, largas.

Custo e atraso vêm de `custo.py` e são ESTIMATIVAS; aqui nada os altera. A expressa
é um salto só (retemporização + distância em linha reta); a peça grande assume que
os saltos dentro da própria peça não custam nada (rede interna da GPU, premissa).
"""
import math
from dataclasses import replace

from modulos.conexoes.netlist import Netlist
from modulos.conexoes.verificador import verificar
from modulos.malha import montar as MO
from modulos.malha.rota import rota_xy
from modulos.malha.topologia import ligacao
from modulos.malha.trafego import Fluxo

PECA_GRANDE = "GPU"          # peça que ocupa vários segmentos na alternativa 2


def _contagem_erros(av):
    rel = verificar(Netlist(), {"malha": av})
    return rel.contagem("R21-malha-atraso"), rel.contagem("R22-malha-ocupacao")


def _fechar(nome, descricao, fluxos, malha, extras):
    av = MO.avaliar_fluxos(fluxos, malha)
    r21, r22 = _contagem_erros(av)
    av["resumo"]["erros_r21"] = r21
    av["resumo"]["erros_r22"] = r22
    gm = [d for d in av["fluxos"] if d["nome"].startswith("GPU-MEM")]
    if gm:
        extras["gpu_mem_saltos_max"] = max(d["saltos"] for d in gm)
        extras["gpu_mem_atraso_max_ns"] = max(d["atraso_ns"] for d in gm)
        extras["gpu_mem_erros_r21"] = sum(1 for d in gm if d["folga_ns"] < 0)
    av["nome"], av["descricao"], av["extras"] = nome, descricao, extras
    return av


def _caixa(plano, malha, peca):
    """Menor retângulo de segmentos que contém os tradutores da peça."""
    segs = []
    for e in plano.enlaces:
        if e.a == peca:
            segs.append(MO.segmento_de(malha, e.tradutor_a))
        if e.b == peca:
            segs.append(MO.segmento_de(malha, e.tradutor_b))
    if not segs:
        return None
    xs, ys = [s[0] for s in segs], [s[1] for s in segs]
    return (min(xs), min(ys), max(xs), max(ys))


def _dentro(caixa, s):
    return caixa[0] <= s[0] <= caixa[2] and caixa[1] <= s[1] <= caixa[3]


def _limitar(caixa, s):
    """Segmento da caixa mais perto de `s`: a face da peça voltada para o destino."""
    return (min(max(s[0], caixa[0]), caixa[2]), min(max(s[1], caixa[1]), caixa[3]))


def _pontas(plano, malha):
    """[[enlace, origem, destino, gbs]] como em `montar.fluxos_do_plano`, mutável."""
    base = MO.fluxos_do_plano(plano, malha)
    return [[e, f.origem, f.destino, f] for e, f in zip(plano.enlaces, base)]


def _colar(itens, malha, caixa):
    """Move cada chip MEMk para um vizinho do segmento do tradutor da GPU (1 salto)."""
    uso, chip = {}, {}
    for e, o, d, f in itens:
        if e.a != PECA_GRANDE or not e.b.startswith("MEM"):
            continue
        cand = [v for v in malha.vizinhos(o) if caixa is None or not _dentro(caixa, v)]
        cand = cand or malha.vizinhos(o)
        v = min(cand, key=lambda v: (uso.get(ligacao(o, v), 0), math.dist(v, d), v))
        uso[ligacao(o, v)] = uso.get(ligacao(o, v), 0) + 1
        chip[e.b] = v
    for it in itens:
        e = it[0]
        if e.b in chip and e.b.startswith("MEM"):
            it[2] = chip[e.b]       # a GPU e a ponte alcançam o chip onde ele agora está


def montar_fluxos(plano, base, *, expressas=False, peca_grande=False, espalhar=False,
                  colada=False, min_saltos=2, gbs_expressa=None):
    """Devolve (fluxos, malha, extras) do cenário pedido, ainda sem reservar."""
    malha = MO.malha_da_base(base)
    itens = _pontas(plano, malha)
    caixa = _caixa(plano, malha, PECA_GRANDE)
    extras = {}

    if colada:
        _colar(itens, malha, caixa)
    if peca_grande and caixa:
        for it in itens:
            e = it[0]
            if e.a == PECA_GRANDE:
                it[1] = _limitar(caixa, it[2])
            elif e.b == PECA_GRANDE:
                it[2] = _limitar(caixa, it[1])
        extras["caixa_gpu"] = caixa

    modo = "dividida" if espalhar else "xy"
    pares = {}
    if expressas:
        for e, o, d, f in itens:
            if len(rota_xy(malha, o, d)[0]) >= min_saltos:
                pares.setdefault(ligacao(o, d), []).append(e.id)
        for a, b in pares:
            malha = malha.com_expressa(a, b, gbs_expressa)
        extras["expressas"] = len(pares)
        extras["expressa_max_mm"] = max((malha.comprimento_mm(p) for p in pares), default=0.0)

    fluxos = []
    for e, o, d, f in itens:
        exp = ligacao(o, d) if ligacao(o, d) in pares else None
        fluxos.append(replace(f, origem=o, destino=d, rota=modo, expressa=exp))
    return fluxos, malha, extras


def _alargar(fluxos, malha):
    """Sobe a capacidade, em múltiplos da ligação comum, só nas ligações acima de 100 %."""
    from modulos.malha.trafego import reservar
    res = reservar(malha, fluxos)
    base = malha.capacidade_padrao_gbs()
    faixa_gbs = malha.gbps_por_faixa / 8
    largas, extras_faixas = 0, 0.0
    for lig, oc in res.acima_de_100:
        nova = math.ceil(oc - 1e-9) * malha.capacidade_gbs(lig)
        extras_faixas += (nova - malha.capacidade_gbs(lig)) / faixa_gbs
        malha = malha.com_capacidade(lig, nova)
        largas += 1
    return malha, {"ligacoes_largas": largas, "faixas_extras": extras_faixas,
                   "capacidade_padrao_gbs": base}


def combinar(plano, base, *, nome, descricao="", expressas=False, peca_grande=False,
             largas=False, espalhar=False, colada=False, min_saltos=2, gbs_expressa=None):
    fluxos, malha, extras = montar_fluxos(
        plano, base, expressas=expressas, peca_grande=peca_grande, espalhar=espalhar,
        colada=colada, min_saltos=min_saltos, gbs_expressa=gbs_expressa)
    if largas:
        malha, ex = _alargar(fluxos, malha)
        extras.update(ex)
    return _fechar(nome, descricao, fluxos, malha, extras)


# ------------------------------------------------------------------ as alternativas
def atual(plano, base):
    """Referência: rota XY, ligações iguais (o que `montar.avaliar` já dá)."""
    return combinar(plano, base, nome="Atual (XY)",
                    descricao="rota XY, 64 faixas por ligação, tudo igual")


def fibra_gigante(plano, base, min_saltos=2, gbs_expressa=None):
    """1. Uma expressa para cada par origem-destino com `min_saltos` ou mais saltos."""
    return combinar(plano, base, nome="1. Fibra gigante", expressas=True,
                    min_saltos=min_saltos, gbs_expressa=gbs_expressa,
                    descricao="expressa ponto a ponto para cada par distante; 1 salto")


def ligacoes_largas(plano, base, peca_grande=False):
    """2. Ligações alargadas só onde passam de 100 %; com `peca_grande`, a GPU ocupa vários segmentos."""
    return combinar(plano, base, largas=True, peca_grande=peca_grande,
                    nome="2. Ligações largas + peça grande" if peca_grande else "2. Ligações largas",
                    descricao="capacidade por ligação ajustada"
                              + ("; GPU recebe fluxos por todos os lados" if peca_grande else ""))


def rotas_espalhadas(plano, base):
    """3. Cada fluxo dividido meio a meio entre XY e YX."""
    return combinar(plano, base, espalhar=True, nome="3. Rotas espalhadas",
                    descricao="XY e YX meio a meio; mesmos saltos nas duas partes")


def memoria_colada(plano, base):
    """4. Chips de memória vizinhos da GPU: cada fluxo da GPU tem 1 salto."""
    return combinar(plano, base, colada=True, nome="4. Memória colada",
                    descricao="chip vizinho do tradutor da GPU (referência)")


COMBINACOES = [
    dict(nome="Peça grande", peca_grande=True,
         descricao="só a GPU em vários segmentos"),
    dict(nome="Peça grande + espalhadas", peca_grande=True, espalhar=True,
         descricao="GPU em vários segmentos, XY/YX"),
    dict(nome="Peça grande + espalhadas + largas", peca_grande=True, espalhar=True, largas=True,
         descricao="idem, com ligações alargadas onde sobra"),
    dict(nome="Fibra gigante + largas", expressas=True, largas=True,
         descricao="expressas e capacidade ajustada"),
    dict(nome="Peça grande + fibra gigante + largas", peca_grande=True, expressas=True,
         largas=True, descricao="as três juntas"),
    dict(nome="Colada + espalhadas + largas", colada=True, espalhar=True, largas=True,
         descricao="referência com a sobra ajustada"),
]


def todos(plano, base):
    """Todas as linhas da comparação, na ordem da tabela."""
    saida = [atual(plano, base), fibra_gigante(plano, base),
             ligacoes_largas(plano, base), ligacoes_largas(plano, base, peca_grande=True),
             rotas_espalhadas(plano, base), memoria_colada(plano, base)]
    saida += [combinar(plano, base, **c) for c in COMBINACOES]
    return saida
