"""Modelos das peças: contatos, função de cada pino, trilhos de energia e interfaces.

As pinagens são sintéticas: respeitam encapsulamento, passo, contagem de pinos
e a proporção entre energia, terra e sinal de cada peça, mas a posição de cada
sinal não é a do datasheet do fabricante.
"""
from dataclasses import dataclass, field

TERRA, ENERGIA, SINAL = "terra", "energia", "sinal"


@dataclass
class Pino:
    nome: str
    funcao: str
    grupo: str          # trilho (VCCIN) ou interface (DDR5_A)
    x: float            # mm, referencial da peça, centro em (0, 0)
    y: float


@dataclass
class Trilho:
    nome: str
    tensao: float       # V
    corrente_max: float  # A
    origem: str         # "base": chega pelas células; "cabo": cabo da fonte


@dataclass
class Interface:
    nome: str
    protocolo: str      # chave em modulos.dados.protocolos.PROTOCOLOS
    par: str            # tipo da peça do outro lado
    sinais: list = field(default_factory=list)   # nomes dos pinos


@dataclass
class Componente:
    tipo: str
    nome: str
    largura: float      # mm (eixo x)
    profundidade: float  # mm (eixo y)
    altura: float       # mm
    diametro_pad: float  # mm
    pinos: list
    trilhos: dict
    interfaces: dict
    potencia_tipica: float   # W
    potencia_max: float      # W
    fracao_calor_base: float  # parte do calor que vai para a base, o resto vai ao dissipador
    cor: str
    cxl: bool = False         # hospeda memória compartilhada por CXL (CXL.mem/CXL.cache)
    capacidade_gb: float = 0.0       # memória: quanto o chip ou o módulo guarda
    densidade_max_gb: float = 0.0    # controlador GDDR7: o maior chip que ele endereça

    def pino(self, nome):
        return self._indice()[nome]

    def _indice(self):
        if not hasattr(self, "_idx"):
            self._idx = {p.nome: p for p in self.pinos}
        return self._idx

    def contagem(self):
        out = {}
        for p in self.pinos:
            out[p.funcao] = out.get(p.funcao, 0) + 1
        return out


def _grade(nx, ny, passo):
    """Posições (ix, iy, x, y) de uma grade centrada."""
    x0 = -(nx - 1) * passo / 2
    y0 = -(ny - 1) * passo / 2
    for iy in range(ny):
        for ix in range(nx):
            yield ix, iy, x0 + ix * passo, y0 + iy * passo


class _Contador:
    """Dá nomes sequenciais por grupo: VSS_0, VSS_1, ..."""

    def __init__(self):
        self.n = {}

    def __call__(self, grupo):
        i = self.n.get(grupo, 0)
        self.n[grupo] = i + 1
        return f"{grupo}_{i}"


def _sinais_ddr5(prefixo):
    """Um canal DDR5 (dois subcanais de 32 bits) visto do controlador."""
    out = []
    for sub in "AB":
        out += [f"{prefixo}_{sub}_DQ{i}" for i in range(32)]
        out += [f"{prefixo}_{sub}_DQS{i}" for i in range(4)]
        out += [f"{prefixo}_{sub}_CA{i}" for i in range(7)]
        out += [f"{prefixo}_{sub}_CS{i}" for i in range(2)]
        out += [f"{prefixo}_{sub}_CK"]
    out += [f"{prefixo}_RESET", f"{prefixo}_ALERT"]
    return out


def _sinais_pcie(prefixo, pistas):
    out = []
    for i in range(pistas):
        out += [f"{prefixo}_TX{i}", f"{prefixo}_RX{i}"]
    return out


def _sinais_gddr7(chip):
    return ([f"G{chip}_DQ{i}" for i in range(32)]
            + [f"G{chip}_CA{i}" for i in range(5)]
            + [f"G{chip}_CK", f"G{chip}_WCK", f"G{chip}_EDC", f"G{chip}_RESET"])


def i5_13600kf():
    """Intel Core i5-13600KF, LGA1700: 1700 contatos a 0,8 mm, núcleo de 200 A."""
    nx, ny, passo = 54, 44, 0.8
    nome = _Contador()
    ddr_a, ddr_b = iter(_sinais_ddr5("DDR5_A")), iter(_sinais_ddr5("DDR5_B"))
    pcie = iter(_sinais_pcie("PEG", 16) + _sinais_pcie("PCIE4", 4)
                + ["REFCLK_PEG", "REFCLK_PCIE4"] + [f"DMI_{i}" for i in range(16)])
    aux = iter(["SVID_CLK", "SVID_DATA", "SVID_ALERT", "PWROK", "PLTRST", "PROCHOT",
                "THERMTRIP", "BCLK", "CATERR", "TCK", "TDI", "TDO", "TMS", "TRST",
                "SMBUS_CLK", "SMBUS_DATA", "VIDSCK", "PECI", "RSMRST", "SLP_S3"])
    pinos = []

    def add(funcao, grupo, x, y, nm=None):
        pinos.append(Pino(nm or nome(grupo), funcao, grupo, x, y))

    trilho_aux = iter(["VCC_SA"] * 40 + ["VCC1P8"] * 20 + ["VDD2"] * 40)
    for ix, iy, x, y in _grade(nx, ny, passo):
        if 14 <= ix <= 39 and 9 <= iy <= 34:
            continue                                   # vão central do LGA1700
        xadrez = (ix + iy) % 2 == 0
        if 5 <= iy <= 38 and (ix <= 5 or ix >= 48):    # bandas laterais: DDR5
            fonte = ddr_a if ix <= 5 else ddr_b
            interf = "DDR5_A" if ix <= 5 else "DDR5_B"
            if (ix + iy) % 3 == 0:
                add(TERRA, "VSS", x, y)
            else:
                s = next(fonte, None)
                if s:
                    add(SINAL, interf, x, y, s)
                else:
                    add(ENERGIA, "VDD2", x, y)
        elif 5 <= iy <= 38:                            # núcleo: VCCIN e VSS em xadrez
            add(ENERGIA if xadrez else TERRA, "VCCIN" if xadrez else "VSS", x, y)
        elif iy <= 4:                                  # borda de baixo: PCIe e DMI
            s = None if xadrez else next(pcie, None)
            if s:
                grupo = "PEG" if s.startswith(("PEG", "REFCLK_PEG")) else "PCH"
                add(SINAL, grupo, x, y, s)
            else:
                add(TERRA, "VSS", x, y)
        else:                                          # borda de cima: trilhos auxiliares
            if xadrez:
                t = next(trilho_aux, None)
                add(ENERGIA, t, x, y) if t else add(TERRA, "VSS", x, y)
            else:
                s = next(aux, None)
                add(SINAL, "AUX", x, y, s) if s else add(TERRA, "VSS", x, y)
    assert len(pinos) == 1700, len(pinos)

    sinais = lambda g: [p.nome for p in pinos if p.grupo == g]
    return Componente(
        tipo="i5-13600KF", nome="Intel Core i5-13600KF (LGA1700)",
        largura=45.0, profundidade=37.5, altura=4.4, diametro_pad=0.50,
        pinos=pinos,
        trilhos={"VCCIN": Trilho("VCCIN", 1.25, 200.0, "base"),
                 "VCC_SA": Trilho("VCC_SA", 1.05, 12.0, "base"),
                 "VCC1P8": Trilho("VCC1P8", 1.8, 3.0, "base"),
                 "VDD2": Trilho("VDD2", 1.1, 8.0, "base")},
        interfaces={"DDR5_A": Interface("DDR5_A", "DDR5-4800", "DDR5-DIMM", sinais("DDR5_A")),
                    "DDR5_B": Interface("DDR5_B", "DDR5-4800", "DDR5-DIMM", sinais("DDR5_B")),
                    "PEG": Interface("PEG", "PCIe5", "GPU", sinais("PEG")),
                    # DMI 4.0 x8 até o chipset; PCIe 4.0 x4 é uma porta raiz da própria CPU
                    "DMI": Interface("DMI", "PCIe4", "PCH",
                                     [n for n in sinais("PCH") if n.startswith("DMI")]),
                    "PCIE4": Interface("PCIE4", "PCIe4", "FPGA",
                                       [n for n in sinais("PCH") if not n.startswith("DMI")]),
                    "AUX": Interface("AUX", "AUX", "PCH", sinais("AUX"))},
        potencia_tipica=125.0, potencia_max=181.0, fracao_calor_base=0.06,
        cor="#9aa4ad", cxl=False)


def ddr5_dimm():
    """Módulo DDR5 UDIMM deitado: 288 contatos em duas fileiras de 144 a 0,85 mm."""
    pinos, nome = [], _Contador()
    sinais = iter(_sinais_ddr5("DDR5") + ["HSCL", "HSDA"])     # HSCL/HSDA: barramento do SPD
    for fileira, y in ((0, -0.9), (1, 0.9)):
        x0 = -143 * 0.85 / 2
        for i in range(144):
            x = x0 + i * 0.85
            if i < 3:
                pinos.append(Pino(nome("VIN_BULK"), ENERGIA, "VIN_BULK", x, y))
            elif i % 3 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
            else:
                s = next(sinais, None)
                if s:
                    pinos.append(Pino(s, SINAL, "SPD" if s in ("HSCL", "HSDA") else "DDR5", x, y))
                else:
                    pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
    pinos_y = 31.25 / 2 - 3.0           # contatos junto de uma borda longa
    for p in pinos:
        p.y += -pinos_y
    sinais_nomes = [p.nome for p in pinos if p.grupo == "DDR5"]
    return Componente(
        tipo="DDR5-DIMM", nome="DDR5-4800 UDIMM 16 GB",
        largura=133.35, profundidade=31.25, altura=3.8, diametro_pad=0.55,
        pinos=pinos,
        trilhos={"VIN_BULK": Trilho("VIN_BULK", 5.0, 2.5, "base")},
        interfaces={"DDR5": Interface("DDR5", "DDR5-4800", "i5-13600KF", sinais_nomes),
                    "SPD": Interface("SPD", "DDR5-4800", "FPGA", ["HSCL", "HSDA"])},
        potencia_tipica=6.0, potencia_max=10.0, fracao_calor_base=0.25,
        cor="#2c6e49", capacidade_gb=16.0)


def gpu():
    """Pacote da GPU com 384 bits de GDDR7 e PCIe 5.0 x16; potência pelo cabo."""
    nx, ny, passo = 50, 50, 0.8
    nome = _Contador()
    mem = iter([s for c in range(12) for s in _sinais_gddr7(c)])
    peg = iter(_sinais_pcie("PEG", 16) + ["REFCLK_PEG"])
    pinos = []
    for ix, iy, x, y in _grade(nx, ny, passo):
        borda = min(ix, iy, nx - 1 - ix, ny - 1 - iy)
        xadrez = (ix + iy) % 2 == 0
        if borda <= 7:                                 # anel externo: GDDR7 e PCIe
            if (ix + iy) % 4 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
                continue
            s = next(mem, None)
            g = "GDDR7"
            if s is None:
                s, g = next(peg, None), "PEG"
            if s:
                pinos.append(Pino(s, SINAL, g, x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif 18 <= ix <= 31 and 18 <= iy <= 31:
            continue                                   # centro: alimentação vem do cabo, sem bolas
        elif borda <= 9 and xadrez:
            pinos.append(Pino(nome("P3V3_AUX"), ENERGIA, "P3V3_AUX", x, y))
        else:
            pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
    sinais = lambda g: [p.nome for p in pinos if p.grupo == g]
    return Componente(
        tipo="GPU", nome="GPU com barramento GDDR7 de 384 bits",
        largura=42.5, profundidade=42.5, altura=3.0, diametro_pad=0.45,
        pinos=pinos,
        trilhos={"NUCLEO": Trilho("NUCLEO", 1.05, 300.0, "cabo"),
                 "P3V3_AUX": Trilho("P3V3_AUX", 3.3, 3.0, "base")},
        interfaces={"GDDR7": Interface("GDDR7", "GDDR7-32", "GDDR7", sinais("GDDR7")),
                    "PEG": Interface("PEG", "PCIe5", "i5-13600KF", sinais("PEG"))},
        potencia_tipica=220.0, potencia_max=300.0, fracao_calor_base=0.04,
        cor="#3d3f45", cxl=False, densidade_max_gb=4.0)


def gddr7():
    """Chip GDDR7 de 32 bits, FBGA 266 a 0,7 mm."""
    nx, ny, passo = 14, 19, 0.7
    nome = _Contador()
    sinais = iter(_sinais_gddr7("X"))
    pinos = []
    for ix, iy, x, y in _grade(nx, ny, passo):
        if 7 <= iy <= 11:                              # faixa central: alimentação
            if (ix + iy) % 2 == 0:
                pinos.append(Pino(nome("VDD"), ENERGIA, "VDD", x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif (ix + iy) % 3 == 0:
            pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        else:
            s = next(sinais, None)
            if s:
                pinos.append(Pino(s, SINAL, "GDDR7", x, y))
            elif (ix + iy) % 2 == 0:
                pinos.append(Pino(nome("VDDQ"), ENERGIA, "VDDQ", x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
    assert len(pinos) == 266
    return Componente(
        tipo="GDDR7", nome="GDDR7 32 Gb/s, 16 Gb",
        largura=12.0, profundidade=14.0, altura=1.1, diametro_pad=0.35,
        pinos=pinos,
        trilhos={"VDD": Trilho("VDD", 1.2, 3.0, "base"),
                 "VDDQ": Trilho("VDDQ", 1.2, 2.0, "base")},
        interfaces={"GDDR7": Interface("GDDR7", "GDDR7-32", "GPU",
                                       [p.nome for p in pinos if p.funcao == SINAL])},
        potencia_tipica=2.5, potencia_max=4.0, fracao_calor_base=0.5,
        cor="#1d1f24", capacidade_gb=2.0)


def _sinais_transceptores():
    """O FPGA é um dispositivo PCIe 4.0 x4 na porta raiz da CPU (controle e telemetria da base).
    O TX de um lado é o RX do outro. O DMI não vem para cá: ele é do chipset."""
    return [f"PCIE4_{d}{i}" for i in range(4) for d in ("TX", "RX")] + ["REFCLK_XCVR"]


def fpga():
    """FPGA orquestrador, BGA 1156 a 1,0 mm, com transceptores na borda de baixo."""
    nx, ny, passo = 34, 34, 1.0
    nome = _Contador()
    ctl = iter([f"CTL_{i}" for i in range(200)])
    xcvr = iter(_sinais_transceptores())
    trilho_xcvr = iter(["MGTAVCC", "MGTAVTT"] * 30)
    pinos = []
    for ix, iy, x, y in _grade(nx, ny, passo):
        borda = min(ix, iy, nx - 1 - ix, ny - 1 - iy)
        if iy <= 4:                                    # transceptores, blindados por VSS
            if (ix + iy) % 2 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
                continue
            s = next(xcvr, None)
            if s:
                pinos.append(Pino(s, SINAL, "XCVR", x, y))
                continue
            t = next(trilho_xcvr, None)
            if t:
                pinos.append(Pino(nome(t), ENERGIA, t, x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif borda <= 4:
            if (ix + iy) % 3 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
            else:
                s = next(ctl, None)
                if s:
                    pinos.append(Pino(s, SINAL, "CTL", x, y))
                else:
                    pinos.append(Pino(nome("VCCAUX"), ENERGIA, "VCCAUX", x, y))
        elif (ix + iy) % 2 == 0:
            pinos.append(Pino(nome("VCCINT"), ENERGIA, "VCCINT", x, y))
        else:
            pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
    return Componente(
        tipo="FPGA", nome="FPGA orquestrador",
        largura=35.0, profundidade=35.0, altura=3.2, diametro_pad=0.50,
        pinos=pinos,
        trilhos={"VCCINT": Trilho("VCCINT", 0.85, 25.0, "base"),
                 "VCCAUX": Trilho("VCCAUX", 1.8, 4.0, "base"),
                 "MGTAVCC": Trilho("MGTAVCC", 0.9, 3.0, "base"),
                 "MGTAVTT": Trilho("MGTAVTT", 1.2, 2.0, "base")},
        interfaces={"CTL": Interface("CTL", "AUX", "i5-13600KF",
                                     [p.nome for p in pinos if p.grupo == "CTL"]),
                    "XCVR": Interface("XCVR", "PCIe4", "i5-13600KF",
                                      [p.nome for p in pinos if p.grupo == "XCVR"])},
        potencia_tipica=18.0, potencia_max=30.0, fracao_calor_base=0.3,
        cor="#6b4f9e")


# sinais do chipset, por interface (o lado da CPU tem os mesmos nomes, salvo RSMRST/SLP_S3)
PCH_SINAIS = {
    "DMI": [f"DMI_{i}" for i in range(16)],
    "AUXCPU": ["PWROK", "PLTRST", "RSMRST_CPU", "SLP_S3_CPU", "THERMTRIP", "CATERR", "PROCHOT",
               "PECI", "SMBUS_CLK", "SMBUS_DATA"],
    "SPD": ["SPD0_HSCL", "SPD0_HSDA", "SPD1_HSCL", "SPD1_HSDA"],
    "CLK": ["CLKOUT_BCLK", "CLKOUT_PEG_CPU", "CLKOUT_PEG_GPU", "CLKOUT_PCIE4_CPU", "CLKOUT_XCVR"],
    "PM": ["RSMRST_IN", "SYS_PWROK", "SLP_S3_OUT", "SMB_FPGA_CLK", "SMB_FPGA_DATA"],
    "SPI": ["SPI_CLK", "SPI_CS0", "SPI_MOSI", "SPI_MISO"],
}
PCH_PROTOCOLO = {"DMI": "PCIe4", "AUXCPU": "AUX", "SPD": "DDR5-4800", "CLK": "AUX", "PM": "AUX",
                 "SPI": "AUX"}
PCH_PAR = {"DMI": "i5-13600KF", "AUXCPU": "i5-13600KF", "SPD": "DDR5-DIMM", "CLK": "i5-13600KF",
           "PM": "FPGA", "SPI": "flash"}


def pch():
    """Chipset Intel série 700 (B760), FCBGA a 0,8 mm: DMI 4.0 x8, SPI, I3C do SPD, relógios,
    gerência de energia e o ME. Só a camada de baixo de bolas é modelada."""
    nx, ny, passo = 30, 29, 0.8
    nome = _Contador()
    sinais = iter([(g, s) for g, lista in PCH_SINAIS.items() for s in lista])
    pinos = []
    for ix, iy, x, y in _grade(nx, ny, passo):
        borda = min(ix, iy, nx - 1 - ix, ny - 1 - iy)
        xadrez = (ix + iy) % 2 == 0
        if borda <= 2:                                 # anel externo: sinais, blindados por VSS
            if (ix + iy) % 3 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
                continue
            gs = next(sinais, None)
            if gs:
                pinos.append(Pino(gs[1], SINAL, gs[0], x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif borda <= 5:                               # poço de standby (Sx): sempre ligado
            pinos.append(Pino(nome("VCCSTBY"), ENERGIA, "VCCSTBY", x, y) if xadrez
                         else Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif 12 <= ix <= 17 and 12 <= iy <= 16:
            continue                                   # vão central sem bolas
        else:                                          # núcleo: poço principal (S0)
            pinos.append(Pino(nome("VCCPRIM"), ENERGIA, "VCCPRIM", x, y) if xadrez
                         else Pino(nome("VSS"), TERRA, "VSS", x, y))
    return Componente(
        tipo="PCH", nome="Intel B760 (chipset série 700)",
        largura=25.0, profundidade=24.0, altura=1.8, diametro_pad=0.45,
        pinos=pinos,
        trilhos={"VCCSTBY": Trilho("VCCSTBY", 1.05, 2.0, "base"),
                 "VCCPRIM": Trilho("VCCPRIM", 1.05, 6.0, "base")},
        interfaces={g: Interface(g, PCH_PROTOCOLO[g], PCH_PAR[g], list(lista))
                    for g, lista in PCH_SINAIS.items()},
        potencia_tipica=6.0, potencia_max=8.0, fracao_calor_base=0.3,
        cor="#5a7d9a")


def ponte_mem():
    """Ponte do banco unificado, chip do laboratório: do lado da CPU se apresenta como um DIMM
    DDR5; do outro tem 12 portas GDDR7 até os chips do banco. BGA de 1600 bolas a 0,8 mm."""
    nx, ny, passo = 40, 40, 0.8
    nome = _Contador()
    # o RESET dos chips do banco é só da GPU
    sinais = iter(_sinais_ddr5("DDR5") + ["HSCL", "HSDA"]
                  + [s for c in range(12) for s in _sinais_gddr7(c) if not s.endswith("_RESET")])
    trilho_io = iter(["VDDQ_DDR5"] * 40 + ["VDDQ_G7"] * 160)
    pinos = []
    for ix, iy, x, y in _grade(nx, ny, passo):
        borda = min(ix, iy, nx - 1 - ix, ny - 1 - iy)
        xadrez = (ix + iy) % 2 == 0
        if borda <= 6:                                 # anel externo: os sinais das duas PHYs
            if (ix + iy) % 4 == 0:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
                continue
            s = next(sinais, None)
            if s:
                g = "SPD" if s in ("HSCL", "HSDA") else ("DDR5" if s.startswith("DDR5") else "GDDR7")
                pinos.append(Pino(s, SINAL, g, x, y))
            else:
                pinos.append(Pino(nome("VSS"), TERRA, "VSS", x, y))
        elif borda <= 9:                               # E/S das PHYs
            t = next(trilho_io, None) if xadrez else None
            pinos.append(Pino(nome(t), ENERGIA, t, x, y) if t else Pino(nome("VSS"), TERRA, "VSS", x, y))
        else:                                          # lógica: mapas, filas e posse
            pinos.append(Pino(nome("VCCINT"), ENERGIA, "VCCINT", x, y) if xadrez
                         else Pino(nome("VSS"), TERRA, "VSS", x, y))
    sinais_de = lambda g: [p.nome for p in pinos if p.grupo == g]
    return Componente(
        tipo="PONTE-MEM", nome="Ponte do banco unificado (DDR5 para GDDR7)",
        largura=33.0, profundidade=33.0, altura=2.4, diametro_pad=0.45,
        pinos=pinos,
        trilhos={"VCCINT": Trilho("VCCINT", 0.85, 12.0, "base"),
                 "VDDQ_DDR5": Trilho("VDDQ_DDR5", 1.1, 1.5, "base"),
                 "VDDQ_G7": Trilho("VDDQ_G7", 1.2, 6.0, "base")},
        interfaces={"DDR5": Interface("DDR5", "DDR5-4800", "i5-13600KF", sinais_de("DDR5")),
                    "SPD": Interface("SPD", "DDR5-4800", "PCH", ["HSCL", "HSDA"]),
                    "GDDR7": Interface("GDDR7", "GDDR7-32", "GDDR7", sinais_de("GDDR7"))},
        potencia_tipica=12.0, potencia_max=20.0, fracao_calor_base=0.3,
        cor="#b5651d", densidade_max_gb=4.0)


CATALOGO = {f().tipo: f for f in (i5_13600kf, ddr5_dimm, gpu, gddr7, fpga, pch, ponte_mem)}

_cache = {}


def obter(tipo):
    if tipo not in _cache:
        _cache[tipo] = CATALOGO[tipo]()
    return _cache[tipo]
