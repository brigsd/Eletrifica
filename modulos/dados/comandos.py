"""Comandos no barramento CA e o que o tradutor precisa entender deles.

O tradutor copia os dados (DQ, DQS, WCK) para a luz sem decodificar. Mas os
pinos bidirecionais mudam de sentido conforme o comando, e a terminação e a
força de saída que a peça espera mudam por escrita em registrador de modo.
Então o detector de cada chip decodifica uma parte do CA: só o que muda
sentido ou nível elétrico. O resto do CA ele copia sem olhar.

Codificação simplificada no estilo das tabelas da JEDEC (JESD79-5 para DDR5,
JESD239 para GDDR7): o código do comando nos 5 primeiros bits do primeiro
ciclo, campos de endereço e de dado nos bits seguintes. Não é a tabela bit a
bit dos padrões.
"""
from dataclasses import dataclass

TCK_DDR5_NS = 1 / 2.4                 # DDR5-4800
TCK_GDDR7_NS = 1 / 2.667              # CK de comando da GDDR7 a 32 Gb/s

LATENCIAS = {                         # janela entre o comando e o primeiro dado
    "DDR5-4800": {"CWL_ns": 38 * TCK_DDR5_NS, "CL_ns": 40 * TCK_DDR5_NS,
                  "preambulo_ns": 2 * TCK_DDR5_NS, "tck_ns": TCK_DDR5_NS, "ciclos_comando": 2},
    "GDDR7-32": {"CWL_ns": 10.0, "CL_ns": 12.0, "preambulo_ns": 1.0,
                 "tck_ns": TCK_GDDR7_NS, "ciclos_comando": 2},
}
LOGICA_DECODIFICACAO_PS = 500.0       # comparadores + registro de sentido, depois do último ciclo

# registradores de modo que mudam nível elétrico de pino (e que o tradutor espelha)
MR_ELETRICOS = {
    "DDR5-4800": {5: "força de saída (DRV)", 32: "ODT de CK/CS", 33: "ODT de CA e DQS_RTT_PARK",
                  34: "RTT_PARK e RTT_WR", 35: "RTT_NOM_WR e RTT_NOM_RD"},
    "GDDR7-32": {3: "força de saída", 7: "ODT de DQ", 8: "ODT de CA/WCK"},
}


@dataclass(frozen=True)
class Tipo:
    nome: str
    codigo: int            # 5 bits do primeiro ciclo
    ciclos: int
    sentido_dq: str        # "escrita" (controlador -> memória), "leitura" (memória -> controlador), ""
    registrador: bool      # escreve registrador de modo


TABELA = {
    "DDR5-4800": [
        Tipo("ACT", 0b00000, 2, "", False),
        Tipo("MRW", 0b00101, 2, "", True),
        Tipo("MRR", 0b10101, 2, "leitura", False),
        Tipo("WR", 0b01101, 2, "escrita", False),
        Tipo("RD", 0b11101, 2, "leitura", False),
        Tipo("VREFCA", 0b00011, 1, "", False),
        Tipo("REFab", 0b10011, 1, "", False),
        Tipo("PREab", 0b01011, 1, "", False),
        Tipo("PREpb", 0b11011, 1, "", False),
        Tipo("NOP", 0b11111, 1, "", False),
    ],
    "GDDR7-32": [
        Tipo("ACT", 0b00001, 2, "", False),
        Tipo("MRS", 0b00110, 2, "", True),
        Tipo("WR", 0b01010, 2, "escrita", False),
        Tipo("RD", 0b01110, 2, "leitura", False),
        Tipo("WRTR", 0b10010, 2, "escrita", False),
        Tipo("RDTR", 0b10110, 2, "leitura", False),
        Tipo("REF", 0b11001, 1, "", False),
        Tipo("PRE", 0b11011, 1, "", False),
        Tipo("NOP", 0b11111, 1, "", False),
    ],
}


@dataclass
class Comando:
    nome: str
    sentido_dq: str
    registrador: tuple = None      # (endereço, dado) de MRW/MRS
    campos: dict = None


def _tipos(protocolo):
    return {t.codigo: t for t in TABELA[protocolo]}


def codificar(protocolo, nome, ma=0, op=0, banco=0, coluna=0, linha=None):
    """Palavras de CA (14 bits por ciclo) de um comando.

    ACT com `linha` (17 bits): os 3 bits altos da linha no primeiro ciclo (bits 10 a 12),
    os 14 baixos no segundo. Assim o bit mais alto da linha (o rank do banco unificado)
    chega no primeiro ciclo, junto com o banco. Comando de um ciclo leva o banco nos bits
    5 a 9 (o PRE é por banco). O RTL (modulos/rtl) usa esta mesma codificação."""
    t = next(x for x in TABELA[protocolo] if x.nome == nome)
    if t.registrador:
        return [t.codigo | (ma & 0xFF) << 5, op & 0xFF]
    if t.ciclos == 2:
        if nome == "ACT" and linha is not None:
            return [t.codigo | (banco & 0x1F) << 5 | ((linha >> 14) & 0x7) << 10, linha & 0x3FFF]
        return [t.codigo | (banco & 0x1F) << 5, coluna & 0x3FF]
    return [t.codigo | (banco & 0x1F) << 5]


def decodificar(protocolo, palavras):
    """Comandos de uma sequência de palavras de CA, na ordem."""
    tipos = _tipos(protocolo)
    out, i = [], 0
    while i < len(palavras):
        w = palavras[i]
        t = tipos.get(w & 0x1F)
        if t is None:
            out.append(Comando("DESCONHECIDO", "", None, {"palavra": w}))
            i += 1
            continue
        if t.ciclos == 2:
            seg = palavras[i + 1] if i + 1 < len(palavras) else 0
            if t.registrador:
                out.append(Comando(t.nome, t.sentido_dq, ((w >> 5) & 0xFF, seg & 0xFF)))
            else:
                campos = {"banco": (w >> 5) & 0x1F, "coluna": seg & 0x3FF}
                if t.nome == "ACT":
                    campos["linha"] = ((w >> 10) & 0x7) << 14 | (seg & 0x3FFF)
                out.append(Comando(t.nome, t.sentido_dq, None, campos))
            i += 2
        else:
            out.append(Comando(t.nome, t.sentido_dq, None, {"banco": (w >> 5) & 0x1F}))
            i += 1
    return out


def necessarios(protocolo):
    """O que o detector do tradutor tem de decodificar: comandos que mudam o sentido
    do DQ e as escritas nos registradores elétricos. O resto passa sem ser lido."""
    sentido = sorted(t.nome for t in TABELA[protocolo] if t.sentido_dq)
    regs = [t.nome for t in TABELA[protocolo] if t.registrador]
    mrs = ",".join(str(k) for k in sorted(MR_ELETRICOS[protocolo]))
    return sentido + [f"{r}:{mrs}" for r in regs]


def copiados_sem_ler(protocolo):
    return sorted(t.nome for t in TABELA[protocolo] if not t.sentido_dq and not t.registrador)


def latencia_decodificacao_ps(protocolo):
    """Do primeiro ciclo do comando até o sentido decidido."""
    L = LATENCIAS[protocolo]
    return L["ciclos_comando"] * L["tck_ns"] * 1000 + LOGICA_DECODIFICACAO_PS


def janela_ps(protocolo):
    """Tempo que o tradutor tem para decidir e comutar antes do primeiro dado."""
    L = LATENCIAS[protocolo]
    return (min(L["CWL_ns"], L["CL_ns"]) - L["preambulo_ns"]) * 1000
