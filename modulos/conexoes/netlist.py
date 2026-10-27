"""Netlist do sistema inteiro: cada salto de cada sinal, tipado.

Um sinal lógico (pino da peça A -> pino da peça B) só existe se houver um
caminho explícito de blocos ligados um ao outro, porta com porta. Nada é
implícito: célula, trilha da base, tradutor, laser, fibra, filtro, receptor,
driver de saída, alimentação e controle de cada bloco ativo são blocos aqui.
O verificador (`verificador.py`) é quem diz se o caminho funciona.

Domínios de porta:
  "eletrico"  sinal elétrico; `padrao` é uma chave de padroes.PADROES
  "optico"    luz; atributos: lambdas_nm (lista), potencia_dbm
  "energia"   alimentação; atributos: tensao_v, corrente_a
  "controle"  barramento de controle lento (I3C/SPI do FPGA)

Sentido da porta: "entra" | "sai" | "bidir".
"""
from collections import defaultdict
from dataclasses import dataclass, field

# tipos de bloco conhecidos; o verificador reprova tipo desconhecido
TIPOS = {
    "pino",            # pino de uma peça (catálogo)
    "celula",          # célula chaveada da base, sob o pino
    "trilha",          # trilha elétrica na base
    "chip_tradutor",   # chip de fotônica de silício junto de uma peça
    "via_tx",          # pista de transmissão: driver + anel modulador (pai: chip_tradutor)
    "via_rx",          # pista de recepção: filtro + fotodetector + TIA + driver de saída (pai: chip)
    "chave_sentido",   # comuta uma pista bidirecional entre via_tx e via_rx
    "detector_sentido",  # lê o comando (CA) e decide o sentido dos pinos bidirecionais
    "mux", "demux",    # multiplexação por comprimento de onda (pode ser interna ao chip)
    "acoplador",       # chip <-> fibra
    "fibra",
    "laser",           # fonte de luz (pente de comprimentos de onda)
    "divisor",         # divide a luz de um laser entre várias fibras
    "regulador",       # gera um trilho a partir de outro
    "trilho",          # rede de alimentação na base
    "controlador",     # FPGA ou controlador de VRM: origem de controle
    "relogio",         # gerador de relógio de referência
    "terminacao",      # terminação ou resistor de pull-up
    "conversor_nivel",  # muda o nível de tensão de um sinal lento
    "flash",           # memória do firmware UEFI
    "fonte",           # fonte ATX (12 V) e seus cabos
}


@dataclass
class Porta:
    nome: str
    dominio: str
    sentido: str
    padrao: str = None
    atributos: dict = field(default_factory=dict)


@dataclass
class Bloco:
    id: str
    tipo: str
    portas: dict = field(default_factory=dict)        # nome -> Porta
    atributos: dict = field(default_factory=dict)
    posicao: tuple = None                             # (x, y) mm na base
    pai: str = None

    def porta(self, nome):
        return self.portas[nome]


@dataclass
class Ligacao:
    a: tuple            # (bloco, porta)
    b: tuple
    meio: str           # "contato" | "trilha" | "interno" | "fibra" | "guia"
    atributos: dict = field(default_factory=dict)     # comprimento_mm, perda_db, atraso_ps...


@dataclass
class Sinal:
    """Ligação lógica que o protocolo exige, de pino a pino."""
    id: str
    protocolo: str
    papel: str
    padrao: str
    origem: tuple       # (bloco do pino, porta)
    destino: tuple
    sentidos: tuple     # ("ida",) ou ("ida", "volta") para bidirecional
    grupo: str = ""     # grupo de byte / pista, para desalinhamento
    caminhos: dict = field(default_factory=dict)      # sentido -> [(bloco, porta), ...]


@dataclass
class Requisito:
    """Algo que uma peça precisa de outra para ligar (PCH, VR, relógio, firmware)."""
    peca: str
    capacidade: str
    provedor: str = None          # bloco que oferece; None = ninguém


class Netlist:
    def __init__(self):
        self.blocos = {}
        self.ligacoes = []
        self.sinais = {}
        self.requisitos = []
        self._viz = defaultdict(list)

    def bloco(self, id_, tipo, posicao=None, pai=None, **atributos):
        if id_ in self.blocos:
            raise ValueError(f"bloco repetido: {id_}")
        b = Bloco(id_, tipo, {}, atributos, posicao, pai)
        self.blocos[id_] = b
        return b

    def porta(self, bloco, nome, dominio, sentido, padrao=None, **atributos):
        p = Porta(nome, dominio, sentido, padrao, atributos)
        self.blocos[bloco].portas[nome] = p
        return p

    def ligar(self, a, b, meio, **atributos):
        lig = Ligacao(tuple(a), tuple(b), meio, atributos)
        self.ligacoes.append(lig)
        self._viz[lig.a].append(lig)
        self._viz[lig.b].append(lig)
        return lig

    def sinal(self, s):
        if s.id in self.sinais:
            raise ValueError(f"sinal repetido: {s.id}")
        self.sinais[s.id] = s
        return s

    def ligacoes_de(self, ponto):
        return self._viz.get(tuple(ponto), [])

    def ligacao_entre(self, a, b):
        for lig in self._viz.get(tuple(a), []):
            if {lig.a, lig.b} == {tuple(a), tuple(b)}:
                return lig
        return None

    def filhos(self, pai):
        return [b for b in self.blocos.values() if b.pai == pai]

    def por_tipo(self, tipo):
        return [b for b in self.blocos.values() if b.tipo == tipo]

    def resumo(self):
        cont = defaultdict(int)
        for b in self.blocos.values():
            cont[b.tipo] += 1
        return {"blocos": len(self.blocos), "ligacoes": len(self.ligacoes),
                "sinais": len(self.sinais), "por_tipo": dict(cont)}
