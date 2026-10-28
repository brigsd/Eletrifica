"""Configuração das células a partir do que o mapeamento achou.

Só usa a identificação (tipo + pose + pino de cada célula), nunca a montagem
real. Célula sem pino atribuído, ou em ponte entre dois pinos, fica desligada.
Peça recusada (sinal sem contato, energia sem folga, ponte) ou desconhecida
não ganha nenhuma célula ligada.
"""
from dataclasses import dataclass, field

import numpy as np

from modulos.componentes import ENERGIA, SINAL, TERRA, obter
from modulos.sistema.base import CODIGO, DESLIGADA
from modulos.sistema.mapeamento import DESCONHECIDA

APELIDO = {"i5-13600KF": "CPU", "DDR5-DIMM": "DIMM", "GPU": "GPU", "GDDR7": "MEM",
           "FPGA": "FPGA", "PONTE-MEM": "PONTE"}

CORRENTE_POR_CONTATO_A = 1.0     # "cerca de 1 A por contato", do conceito
FATOR_CONCENTRACAO = 1.7         # pico/média por pino no VCCIN com plano de 2 oz (0,88/0,53 A)
PERDA_MAX_ENERGIA = 0.25         # perder mais que isso de um trilho recusa a peça
SINAIS_OPCIONAIS = {"TCK", "TDI", "TDO", "TMS", "TRST"}   # depuração: a peça liga sem eles

OK, DEGRADADO, RECUSADA = "ok", "degradado", "recusada"


@dataclass
class PecaConfigurada:
    nome: str
    tipo: str
    x: float
    y: float
    rot: float
    celulas_do_pino: dict = field(default_factory=dict)   # índice do pino -> células
    pinos_sem_contato: list = field(default_factory=list)  # índices do catálogo
    pontes: list = field(default_factory=list)  # [{"tipo", "redes": [(peça, net)], "celulas"}]
    avaliacao: dict = field(default_factory=dict)

    @property
    def peca(self):
        return obter(self.tipo)


@dataclass
class Configuracao:
    funcao: np.ndarray       # (ny, nx) DESLIGADA/F_SINAL/F_ENERGIA/F_TERRA
    peca: np.ndarray         # (ny, nx) índice em `pecas`, -1 = nenhuma
    pino: np.ndarray         # (ny, nx) índice do pino, -1 = nenhum
    pecas: list              # só as que podem energizar (ok ou degradado)
    recusadas: list = field(default_factory=list)       # PecaConfigurada, nada ligado
    desconhecidas: list = field(default_factory=list)   # {"x", "y", "celulas"}

    def por_nome(self, nome):
        return next(p for p in self.pecas if p.nome == nome)

    def resumo(self):
        f = self.funcao
        return {"sinal": int((f == 1).sum()), "energia": int((f == 2).sum()),
                "terra": int((f == 3).sum())}


def avaliar_peca(pc):
    """O que falta de contato numa peça e se ela pode ligar."""
    cat = pc.peca
    sem = set(pc.pinos_sem_contato)
    motivos, degradada = [], False

    energia = {}
    por_trilho = {}
    for j, p in enumerate(cat.pinos):
        if p.funcao == ENERGIA:
            por_trilho.setdefault(p.grupo, []).append(j)
    corrente_total = 0.0
    for trilho, pinos in sorted(por_trilho.items()):
        faltam = sum(j in sem for j in pinos)
        tr = cat.trilhos.get(trilho)
        imax = tr.corrente_max if tr and tr.origem == "base" else None
        if imax:
            corrente_total += imax
        capacidade = (len(pinos) - faltam) * CORRENTE_POR_CONTATO_A
        fracao = faltam / len(pinos)
        folga = imax is None or capacidade >= imax * FATOR_CONCENTRACAO
        energia[trilho] = {"pinos": len(pinos), "sem_contato": faltam, "fracao": fracao,
                           "capacidade_a": capacidade, "corrente_max_a": imax, "folga": folga}
        if faltam:
            if fracao > PERDA_MAX_ENERGIA or not folga:
                motivos.append(f"energia sem folga: {trilho} perdeu {faltam} de {len(pinos)} pinos")
            else:
                degradada = True

    terras = [j for j, p in enumerate(cat.pinos) if p.funcao == TERRA]
    faltam_terra = sum(j in sem for j in terras)
    cap_terra = (len(terras) - faltam_terra) * CORRENTE_POR_CONTATO_A
    if faltam_terra:
        if cap_terra < corrente_total * FATOR_CONCENTRACAO:
            motivos.append(f"terra sem folga: perdeu {faltam_terra} de {len(terras)} pinos")
        else:
            degradada = True

    indice = {p.nome: j for j, p in enumerate(cat.pinos)}
    sinais = {}
    for nome, itf in sorted(cat.interfaces.items()):
        faltando = [s for s in itf.sinais if s in indice and indice[s] in sem
                    and s not in SINAIS_OPCIONAIS]
        if faltando:
            sinais[nome] = faltando
            motivos.append(f"sinal sem contato na interface {nome}: {', '.join(faltando[:4])}"
                           + (" ..." if len(faltando) > 4 else ""))
    opcionais = [n for n in SINAIS_OPCIONAIS if n in indice and indice[n] in sem]
    if opcionais:
        degradada = True

    for pt in pc.pontes:
        redes = ", ".join(f"{a}.{b}" for a, b in pt["redes"][:4])
        if pt["tipo"] == "curto":
            motivos.append(f"ponte entre redes: {redes}")
        else:
            motivos.append(f"contato fora do lugar: células sob uma rede respondem por outra ({redes})")

    veredito = RECUSADA if motivos else (DEGRADADO if degradada else OK)
    return {"veredito": veredito, "motivos": motivos, "energia": energia,
            "terra": {"pinos": len(terras), "sem_contato": faltam_terra},
            "sinais_sem_contato": sinais, "pontes": list(pc.pontes)}


def _nomear(identificacoes):
    """CPU, GPU, FPGA; DIMM0, DIMM1; MEM0..MEM11, numerados da esquerda/baixo."""
    por_tipo = {}
    for i, ident in enumerate(identificacoes):
        por_tipo.setdefault(ident.tipo, []).append(i)
    nomes = [None] * len(identificacoes)
    for tipo, idx in por_tipo.items():
        base = APELIDO.get(tipo, tipo)
        if len(idx) == 1:
            nomes[idx[0]] = base
            continue
        idx.sort(key=lambda i: (round(identificacoes[i].x / 5), identificacoes[i].y))
        for n, i in enumerate(idx):
            nomes[i] = f"{base}{n}"
    return nomes


def configurar(base, identificacoes, sondagem):
    funcao = np.full((base.ny, base.nx), DESLIGADA, dtype=np.int8)
    peca = np.full((base.ny, base.nx), -1, dtype=np.int16)
    pino = np.full((base.ny, base.nx), -1, dtype=np.int32)
    conhecidas = [i for i in identificacoes if i.tipo != DESCONHECIDA]
    nome_de = {id(i): n for i, n in zip(conhecidas, _nomear(conhecidas))}
    indice_ident = {k: nome_de.get(id(i)) for k, i in enumerate(identificacoes)}

    pecas, recusadas, desconhecidas = [], [], []
    for ident in identificacoes:
        if ident.tipo == DESCONHECIDA:
            desconhecidas.append({"x": ident.x, "y": ident.y, "celulas": int(len(ident.celulas))})
            continue
        cat = obter(ident.tipo)
        pc = PecaConfigurada(nome_de[id(ident)], ident.tipo, ident.x, ident.y, ident.rot)
        pc.pinos_sem_contato = list(ident.pinos_sem_contato)
        pc.pontes = [{"tipo": pt["tipo"],
                      "redes": [(indice_ident.get(i) or DESCONHECIDA, net) for i, net in pt["redes"]],
                      "celulas": pt["celulas"]} for pt in ident.pontes]
        ok = ident.pino >= 0
        cel, pin = ident.celulas[ok], ident.pino[ok]
        for c, j in zip(cel, pin):
            pc.celulas_do_pino.setdefault(int(j), []).append(int(c))
        pc.avaliacao = avaliar_peca(pc)
        if pc.avaliacao["veredito"] == RECUSADA:
            recusadas.append(pc)
            continue
        k = len(pecas)
        iy, ix = cel // base.nx, cel % base.nx
        funcao[iy, ix] = [CODIGO[cat.pinos[j].funcao] for j in pin]
        peca[iy, ix] = k
        pino[iy, ix] = pin
        pecas.append(pc)
    if len(sondagem.pontes):
        iy, ix = sondagem.pontes // base.nx, sondagem.pontes % base.nx
        funcao[iy, ix] = DESLIGADA
        peca[iy, ix] = -1
        pino[iy, ix] = -1
    return Configuracao(funcao, peca, pino, pecas, recusadas, desconhecidas)
