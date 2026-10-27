"""Padrão elétrico de cada pino: nível, terminação, taxa e sentido.

É o que o lado elétrico de cada tradutor precisa reproduzir para a peça do
outro lado não perceber que há luz no meio.
"""
from dataclasses import dataclass

from modulos.dados.protocolos import papel


@dataclass(frozen=True)
class Padrao:
    nome: str
    modo: str            # "se" (single-ended) | "diff"
    tensao_v: float      # alimentação de E/S (VDDQ, VCCIO)
    codificacao: str     # "NRZ" | "PAM3" | "relogio" | "estatico"
    taxa_gbps: float     # por pino (relógio: 2x a frequência)
    terminacao: str      # "odt" | "cml_ac" | "hcsl" | "dreno_aberto" | "cmos"
    impedancia_ohm: float
    bidirecional: bool
    alta_velocidade: bool  # vai por luz; os lentos vão por trilha elétrica na base


PADROES = {p.nome: p for p in (
    Padrao("DDR5-DQ", "se", 1.1, "NRZ", 4.8, "odt", 40, True, True),
    Padrao("DDR5-DQS", "diff", 1.1, "NRZ", 4.8, "odt", 80, True, True),
    Padrao("DDR5-CA", "se", 1.1, "NRZ", 2.4, "odt", 40, False, True),
    Padrao("DDR5-CK", "diff", 1.1, "relogio", 4.8, "odt", 80, False, True),
    Padrao("PCIe5-CML", "diff", 0.9, "NRZ", 32.0, "cml_ac", 85, False, True),
    Padrao("PCIe4-CML", "diff", 0.9, "NRZ", 16.0, "cml_ac", 85, False, True),
    Padrao("HCSL-100M", "diff", 0.7, "relogio", 0.2, "hcsl", 85, False, False),
    Padrao("GDDR7-DQ", "se", 1.2, "PAM3", 32.0, "odt", 40, True, True),
    Padrao("GDDR7-EDC", "se", 1.2, "PAM3", 32.0, "odt", 40, False, True),
    Padrao("GDDR7-CA", "se", 1.2, "NRZ", 8.0, "odt", 40, False, True),
    Padrao("GDDR7-CK", "diff", 1.2, "relogio", 8.0, "odt", 80, False, True),
    Padrao("GDDR7-WCK", "diff", 1.2, "relogio", 32.0, "odt", 80, False, True),
    Padrao("CMOS-1V1", "se", 1.1, "estatico", 0.001, "cmos", 50, False, False),
    Padrao("CMOS-1V2", "se", 1.2, "estatico", 0.001, "cmos", 50, False, False),
    Padrao("CMOS-1V05", "se", 1.05, "NRZ", 0.05, "cmos", 50, False, False),
    Padrao("CMOS-1V8", "se", 1.8, "NRZ", 0.1, "cmos", 50, False, False),
    Padrao("OD-1V05", "se", 1.05, "NRZ", 0.05, "dreno_aberto", 50, False, False),
    Padrao("OD-1V05-BIDIR", "se", 1.05, "NRZ", 0.05, "dreno_aberto", 50, True, False),
    Padrao("I3C-1V0", "se", 1.0, "NRZ", 0.0125, "dreno_aberto", 50, True, False),
    Padrao("OD-1V1", "se", 1.1, "estatico", 0.001, "dreno_aberto", 50, False, False),
    Padrao("SVID", "se", 1.0, "NRZ", 0.05, "dreno_aberto", 50, False, False),
    Padrao("SVID-DATA", "se", 1.0, "NRZ", 0.05, "dreno_aberto", 50, True, False),
)}

_AUX = {
    "SVID_CLK": "SVID", "SVID_DATA": "SVID-DATA", "SVID_ALERT": "SVID",
    "BCLK": "HCSL-100M", "SMBUS_DATA": "OD-1V05-BIDIR", "SMBUS_CLK": "OD-1V05",
    "PECI": "OD-1V05-BIDIR", "PROCHOT": "OD-1V05-BIDIR", "CATERR": "OD-1V05",
    "THERMTRIP": "OD-1V05",
}


def padrao_do_pino(protocolo, nome):
    """Nome do padrão elétrico de um pino, pelo protocolo da interface e o nome."""
    p = papel(nome)
    if protocolo == "DDR5-4800":
        if nome.endswith(("HSCL", "HSDA")):
            return "I3C-1V0"
        return {"DQ": "DDR5-DQ", "DQS": "DDR5-DQS", "CA": "DDR5-CA", "CS": "DDR5-CA",
                "CK": "DDR5-CK", "RESET": "CMOS-1V1", "ALERT": "OD-1V1"}[p]
    if protocolo in ("PCIe5", "PCIe4"):
        if p == "REFCLK":
            return "HCSL-100M"
        return "PCIe5-CML" if protocolo == "PCIe5" else "PCIe4-CML"
    if protocolo == "GDDR7-32":
        return {"DQ": "GDDR7-DQ", "EDC": "GDDR7-EDC", "CA": "GDDR7-CA", "CK": "GDDR7-CK",
                "WCK": "GDDR7-WCK", "RESET": "CMOS-1V2"}[p]
    if protocolo == "AUX":
        if nome.startswith("CTL_"):
            return "CMOS-1V8"
        return _AUX.get(nome, "CMOS-1V05")
    raise KeyError(f"protocolo sem padrão elétrico: {protocolo}")
