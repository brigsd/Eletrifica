"""Protocolos nativos que a base transporta sem decodificar.

`taxa_gbps` é a taxa de dados por pino; sinais de controle (comando, relógio,
reset) rodam a `taxa_controle_gbps`. Tolerância e latência de referência são
os números contra os quais o caminho óptico é comparado.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Protocolo:
    nome: str
    taxa_gbps: float             # dados, por pino
    codificacao: str             # "NRZ" | "PAM3"
    bits_por_simbolo: float
    bidirecional: bool           # os pinos de dados mudam de sentido
    tolerancia_desalinhamento_ps: float   # desvio dinâmico tolerado depois do treinamento
    ps_por_mm_trilha: float      # trilha elétrica de referência
    trilha_tipica_mm: float      # comprimento típico numa placa-mãe
    taxa_controle_gbps: float
    latencia_comando_ns: float   # do comando até os dados (CWL/CL); 0 = não se aplica
    folga_inversao_ns: float     # bolha mínima entre leitura e escrita no barramento

    @property
    def gbaud(self):
        return self.taxa_gbps / self.bits_por_simbolo

    @property
    def ui_ps(self):
        return 1000.0 / self.gbaud

    @property
    def atraso_trilha_tipica_ps(self):
        return self.ps_por_mm_trilha * self.trilha_tipica_mm


_TCK_DDR5 = 1 / 2.4   # ns, DDR5-4800

PROTOCOLOS = {
    "DDR5-4800": Protocolo("DDR5-4800", 4.8, "NRZ", 1, True, 0.1 * 208.3, 6.8, 60.0,
                           2.4, 38 * _TCK_DDR5, 4 * _TCK_DDR5),
    "PCIe5": Protocolo("PCIe5", 32.0, "NRZ", 1, False, 0.3 * 31.25, 6.8, 150.0,
                       0.1, 0.0, 0.0),
    "PCIe4": Protocolo("PCIe4", 16.0, "NRZ", 1, False, 0.3 * 62.5, 6.8, 120.0,
                       0.1, 0.0, 0.0),
    "GDDR7-32": Protocolo("GDDR7-32", 32.0, "PAM3", 1.5, True, 0.1 * 46.9, 6.8, 15.0,
                          4.0, 12.0, 1.0),
    "AUX": Protocolo("AUX", 0.1, "NRZ", 1, False, 1000.0, 6.8, 100.0,
                     0.1, 0.0, 0.0),
}

# sinais que são dados (rodam a taxa_gbps); o resto é controle
PAPEIS_DADOS = ("DQ", "DQS", "EDC", "TX", "RX", "DMI")
DIFERENCIAIS = ("DQS", "CK", "WCK", "TX", "RX", "REFCLK", "DMI")
BIDIRECIONAIS_AUX = ("SVID_DATA", "SMBUS_DATA", "PECI", "PROCHOT")


def papel(nome):
    """Extrai o papel do sinal pelo nome: DQ, DQS, CA, CK, TX, ..."""
    ultimo = nome.split("_")[-1]
    for p in ("DQS", "DQ", "WCK", "CK", "CA", "CS", "EDC", "TX", "RX", "RESET", "ALERT"):
        if ultimo.startswith(p):
            return p
    if nome.startswith("DMI"):
        return "DMI"
    if nome.startswith("REFCLK"):
        return "REFCLK"
    return nome
