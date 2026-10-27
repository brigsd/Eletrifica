"""Emulação de tráfego: rajadas de memória atravessando o plano óptico, e treinamento.

O canal físico entra como parâmetro: uma função (símbolos, canal) -> símbolos.
O padrão é um canal ideal com erros aleatórios na taxa pedida. O módulo de
óptica pode trocar isso pelo enlace simulado de verdade.

Em modo comutado o tradutor do lado da memória decide o sentido dos DQ lendo
o comando que chega pelo CA. Se o comando chega corrompido, o sentido fica
errado e a rajada se perde inteira.
"""
from dataclasses import dataclass

import numpy as np

from modulos.dados.protocolos import PROTOCOLOS

# comandos de dois ciclos no CA (bits por pino, ciclo a ciclo); só precisam ser distintos
COMANDOS_DDR5 = {"escrita": [1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0],
                 "leitura": [1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 1]}
COMANDOS_GDDR7 = {"escrita": [0, 1, 1, 0, 1, 1, 0, 0, 1, 0],
                  "leitura": [0, 1, 1, 1, 0, 0, 1, 1, 0, 1]}


def canal_ideal(ber=0.0, semente=0):
    """Canal com erros independentes: cada símbolo vira outro nível com probabilidade `ber`."""
    rng = np.random.default_rng(semente)

    def modelo(simbolos, canal):
        simbolos = np.asarray(simbolos)
        if ber <= 0:
            return simbolos.copy()
        niveis = 3 if canal.codificacao == "PAM3" else 2
        erro = rng.random(simbolos.shape) < ber
        troca = rng.integers(1, niveis, simbolos.shape)
        return np.where(erro, (simbolos + troca) % niveis, simbolos)
    return modelo


@dataclass
class ResultadoRajada:
    enlace: str
    operacao: str
    sentido_decodificado: str
    enviados: bytes
    recebidos: bytes
    erros_bits: int
    canais_usados: int

    @property
    def ok(self):
        return self.erros_bits == 0


# ---------------------------------------------------------------- utilidades
def _bits(dados):
    return np.unpackbits(np.frombuffer(bytes(dados), dtype=np.uint8))


def _bytes(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()


def _canal_de(plano, enlace, pino_a, sentido_dados):
    """Canal que leva o pino no sentido pedido ("ida": a->b, "volta": b->a)."""
    e = plano.enlace(enlace)
    cands = [plano.canais[i] for i in e.canais if plano.canais[i].pino_origem == pino_a]
    for c in cands:
        if c.sentido == "duplo" or c.sentido == sentido_dados:
            return c
    raise KeyError(f"{pino_a} sem canal no sentido {sentido_dados}")


def _decodificar_comando(recebido, tabela):
    for nome, codigo in tabela.items():
        if list(recebido) == codigo:
            return nome
    return "invalido"


def _enviar_comando(plano, enlace, prefixo_ca, n_ca, tabela, operacao, modelo):
    codigo = np.array(tabela[operacao]).reshape(2, n_ca)     # ciclo x pino
    recebido = np.empty_like(codigo)
    for p in range(n_ca):
        c = _canal_de(plano, enlace, f"{prefixo_ca}{p}", "ida")
        recebido[:, p] = modelo(codigo[:, p], c)
    return _decodificar_comando(recebido.reshape(-1), tabela)


def _transmitir_dq(plano, enlace, pinos, matriz, operacao, decodificado, modelo):
    """matriz: pino x símbolos. Devolve o que chega do outro lado."""
    sentido = "ida" if operacao == "escrita" else "volta"
    saida = np.empty_like(matriz)
    for k, pino in enumerate(pinos):
        c = _canal_de(plano, enlace, pino, sentido)
        if c.sentido == "duplo" and decodificado != operacao:
            # tradutor do lado da memória ficou no sentido errado: nada chega
            saida[k] = 0
            continue
        saida[k] = modelo(matriz[k], c)
    return saida


# ---------------------------------------------------------------- DDR5
def rajada_ddr5(plano, enlace, operacao, dados, subcanal="A", modelo=None):
    """Rajada BL16 num subcanal de 32 bits: 64 bytes."""
    modelo = modelo or canal_ideal()
    dados = bytes(dados)
    if len(dados) != 64:
        raise ValueError("BL16 x 32 DQ = 64 bytes")
    e = plano.enlace(enlace)
    interface = plano.canais[e.canais[0]].pino_origem.split("_")
    prefixo = f"{interface[0]}_{interface[1]}_{subcanal}_"
    decod = _enviar_comando(plano, enlace, prefixo + "CA", 7, COMANDOS_DDR5, operacao, modelo)
    palavras = _bits(dados).reshape(16, 32)          # batida x DQ
    pinos = [f"{prefixo}DQ{i}" for i in range(32)]
    recebido = _transmitir_dq(plano, enlace, pinos, palavras.T, operacao, decod, modelo)
    recebidos = _bytes(recebido.T.reshape(-1))
    erros = int((_bits(dados) != _bits(recebidos)).sum())
    return ResultadoRajada(enlace, operacao, decod, dados, recebidos, erros, 32 + 7)


# ---------------------------------------------------------------- GDDR7
def _pam3_codificar(bits):
    """3 bits -> 2 símbolos de 3 níveis (8 das 9 combinações)."""
    v = bits.reshape(-1, 3) @ np.array([4, 2, 1])
    return np.column_stack([v // 3, v % 3]).reshape(-1)


def _pam3_decodificar(trits):
    t = trits.reshape(-1, 2)
    v = t[:, 0] * 3 + t[:, 1]
    invalido = v > 7
    v = np.minimum(v, 7)
    bits = ((v[:, None] >> np.array([2, 1, 0])) & 1).reshape(-1)
    return bits, int(invalido.sum())


def rajada_gddr7(plano, enlace, operacao, dados, modelo=None):
    """Rajada num chip de 32 DQ; cada DQ leva len(dados)*8/32 bits, múltiplo de 3."""
    modelo = modelo or canal_ideal()
    dados = bytes(dados)
    bits = _bits(dados)
    if len(bits) % (32 * 3):
        raise ValueError("o número de bits por DQ precisa ser múltiplo de 3 (ex.: 48 bytes)")
    e = plano.enlace(enlace)
    g = plano.canais[e.canais[0]].pino_origem.split("_")[0]
    decod = _enviar_comando(plano, enlace, f"{g}_CA", 5, COMANDOS_GDDR7, operacao, modelo)
    por_dq = bits.reshape(-1, 32).T                   # DQ x bits
    simbolos = np.array([_pam3_codificar(b) for b in por_dq])
    pinos = [f"{g}_DQ{i}" for i in range(32)]
    recebido = _transmitir_dq(plano, enlace, pinos, simbolos, operacao, decod, modelo)
    rec_bits = np.array([_pam3_decodificar(s)[0] for s in recebido])
    recebidos = _bytes(rec_bits.T.reshape(-1))
    erros = int((bits != _bits(recebidos)).sum())
    return ResultadoRajada(enlace, operacao, decod, dados, recebidos, erros, 32 + 5)


# ---------------------------------------------------------------- treinamento
@dataclass
class Treino:
    enlace: str
    ui_ps: float
    passo_ps: float
    pistas: dict             # pino -> {"tap", "janela_taps", "chegada_ps"}
    convergiu: bool


def _chegadas_leitura(plano, latencias, enlace, pinos):
    """Momento em que cada DQ chega ao controlador numa leitura: CA de ida + DQ de volta."""
    e = plano.enlace(enlace)
    idx = {(plano.canais[i].pino_origem, plano.canais[i].sentido): i for i in e.canais}
    ca = max(latencias.por_canal[i] for i in e.canais if plano.canais[i].papel == "CA")
    out = {}
    for p in pinos:
        i = idx.get((p, "duplo"), idx.get((p, "volta")))
        out[p] = ca + latencias.por_canal[i]
    return out


def _pistas_dados(plano, enlace):
    e = plano.enlace(enlace)
    return sorted({plano.canais[i].pino_origem for i in e.canais
                   if plano.canais[i].papel == "DQ"})


def treinar(plano, latencias, enlace, largura_olho_ui=0.6, passo_ui=1 / 64, modelo=None,
            janela_minima_taps=4, n_bits=32, semente=1):
    """Varre o atraso de amostragem de cada DQ e grava o centro da janela que passa.

    `largura_olho_ui` pode ser um número ou um dict pino -> UI (vindo da óptica).
    """
    modelo = modelo or canal_ideal()
    rng = np.random.default_rng(semente)
    e = plano.enlace(enlace)
    pr = PROTOCOLOS[e.protocolo]
    ui = pr.ui_ps
    passo = ui * passo_ui
    pinos = _pistas_dados(plano, enlace)
    chegada = _chegadas_leitura(plano, latencias, enlace, pinos)
    fim = max(chegada.values()) + 2 * ui
    taps = np.arange(0, fim, passo)
    padrao = rng.integers(0, 2, n_bits)
    pistas, ok = {}, True
    for p in pinos:
        w = largura_olho_ui[p] if isinstance(largura_olho_ui, dict) else largura_olho_ui
        c = _canal_de(plano, enlace, p, "volta")
        rel = taps - chegada[p]
        dentro = (rel >= 0) & (np.abs(rel - ui / 2) < w * ui / 2)
        passa = np.zeros(len(taps), bool)
        for k in np.nonzero(dentro)[0]:
            passa[k] = np.array_equal(modelo(padrao, c), padrao)
        # maior janela contígua
        melhor, ini, atual = (0, 0), None, 0
        for k, v in enumerate(np.append(passa, False)):
            if v and ini is None:
                ini = k
            if not v and ini is not None:
                if k - ini > melhor[0]:
                    melhor = (k - ini, ini)
                ini = None
        janela, comeco = melhor
        tap = comeco + janela // 2
        pistas[p] = {"tap": int(tap), "janela_taps": int(janela), "chegada_ps": float(chegada[p])}
        ok &= janela >= janela_minima_taps
    return Treino(enlace, ui, passo, pistas, bool(ok))


def verificar(treino, plano, latencias, largura_olho_ui=0.6):
    """Com os taps já treinados, quantas pistas ainda amostram dentro do olho."""
    pinos = list(treino.pistas)
    chegada = _chegadas_leitura(plano, latencias, treino.enlace, pinos)
    falhas = []
    for p in pinos:
        w = largura_olho_ui[p] if isinstance(largura_olho_ui, dict) else largura_olho_ui
        t = treino.pistas[p]["tap"] * treino.passo_ps
        rel = t - chegada[p]
        if not (rel >= 0 and abs(rel - treino.ui_ps / 2) < w * treino.ui_ps / 2):
            falhas.append(p)
    return {"pistas": len(pinos), "falhas": len(falhas), "pinos_falhos": falhas}
