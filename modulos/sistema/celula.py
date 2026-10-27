"""A chave de cada célula: uma especificação só, usada pela energia e pelos sinais.

O conceito pede célula de função selecionável: a mesma chave leva até ~1 A de
alimentação ou um sinal de dezenas de Gb/s. O que decide se isso cabe é a
figura de mérito da chave, R_on x C_off: R_on baixo para a energia, C_off baixo
para o sinal. Cada tecnologia tem uma figura de mérito típica.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Chave:
    nome: str
    r_on_ohm: float
    c_off_ff: float            # capacitância da chave aberta, vista pelo contato
    corrente_max_a: float
    comuta_com_corrente: bool  # False: só pode mudar de estado sem carga
    descricao: str

    @property
    def figura_merito_fs(self):
        return self.r_on_ohm * self.c_off_ff


CHAVES = {c.nome: c for c in (
    Chave("mosfet_potencia", 0.025, 60_000.0, 1.0, True,
          "MOSFET de potência de baixa tensão; R_on x C_oss ~1,5 ps"),
    Chave("rf_soi", 0.025, 4_800.0, 1.0, True,
          "chave RF em SOI dimensionada para 25 mΩ; R_on x C_off ~120 fs"),
    Chave("rele_mems", 0.050, 20.0, 1.0, False,
          "relé eletromecânico por célula, contato ôhmico; aberto é um vão de ar"),
)}

PADRAO = "mosfet_potencia"     # é o que o conceito descreve


def chave(nome=None):
    return CHAVES[nome or PADRAO]
