"""Memória compartilhada entre CPU e GPU: o que a montagem permite e as alternativas.

Sem CXL nas duas pontas (i5-13600KF e a GPU não têm), a CPU só enxerga a memória
da GPU por uma BAR redimensionável (ReBAR) sobre o PCIe: sem coerência, com o
custo de protocolo do PCIe e o caminho óptico da base. Compara com a DDR5 local
e com memória unificada no encapsulamento.

    from modulos.dados.memoria_compartilhada import comparar
    linhas = comparar(netlist)
"""
from modulos.conexoes.verificador import OPCIONAIS, atraso_caminho_ps

# PCIe 5.0 x16
PCIE_GT_S = 32.0
PCIE_VIAS = 16
PCIE_CODIFICACAO = 128 / 130
MPS_B = 256                    # carga máxima de um TLP
CABECALHO_TLP_B = 16           # 4 DW, endereço de 64 bits
ENQUADRAMENTO_B = 8            # token STP + LCRC
FRACAO_DLLP = 0.04             # ACK e atualização de crédito
LEITURA_PCIE_NS = 800.0        # leitura não postada: complexo raiz, endpoint e a GDDR7 do outro lado

# DDR5 local: 2 canais de 64 bits
DDR5_MT_S = 4800
DDR5_CANAIS = 2
DDR5_BITS_CANAL = 64
EFICIENCIA_DDR5 = 0.85         # refresh, troca leitura/escrita, página fechada
LEITURA_DDR5_NS = 90.0         # carga até uso, controlador e DRAM

# memória unificada no encapsulamento (LPDDR5X ao lado do die, CPU e GPU no mesmo controlador)
UNIFICADA_MT_S = 8533
UNIFICADA_BITS = 128
EFICIENCIA_UNIFICADA = 0.85
LEITURA_UNIFICADA_NS = 110.0


def _caminho_ps(netlist, protocolo, pecas):
    """Maior atraso pino a pino entre as duas peças, num sentido."""
    ts = [atraso_caminho_ps(netlist, cam, protocolo)
          for s in netlist.sinais.values() if s.protocolo == protocolo
          and {s.origem[0].split(":", 1)[0], s.destino[0].split(":", 1)[0]} == set(pecas)
          for cam in s.caminhos.values()]
    return max(ts, default=0.0)


def _coerente(netlist):
    for q in netlist.requisitos:
        if q.capacidade in OPCIONAIS:
            b = netlist.blocos.get(q.provedor) if q.provedor else None
            return b is not None and q.capacidade in b.atributos.get("capacidades", ())
    return False


def comparar(netlist):
    pico_pcie = PCIE_VIAS * PCIE_GT_S * PCIE_CODIFICACAO / 8
    efic_pcie = MPS_B / (MPS_B + CABECALHO_TLP_B + ENQUADRAMENTO_B) * (1 - FRACAO_DLLP)
    voo_pcie = _caminho_ps(netlist, "PCIe5", ("CPU", "GPU"))
    pico_ddr = DDR5_CANAIS * DDR5_BITS_CANAL * DDR5_MT_S / 8 / 1000
    voo_ddr = max(_caminho_ps(netlist, "DDR5-4800", ("CPU", d)) for d in ("DIMM0", "DIMM1"))
    pico_uni = UNIFICADA_BITS * UNIFICADA_MT_S / 8 / 1000
    cxl = _coerente(netlist)
    return {
        "rebar_pcie": {
            "nome": "GPU vista pela CPU (CXL)" if cxl else "GPU vista pela CPU (ReBAR, PCIe 5 x16)",
            "banda_pico_gb_s": pico_pcie, "banda_gb_s": pico_pcie * efic_pcie,
            "latencia_ns": LEITURA_PCIE_NS + 2 * voo_pcie / 1000, "caminho_ns": voo_pcie / 1000,
            "coerente": cxl, "nesta_montagem": voo_pcie > 0},
        "ddr5_local": {
            "nome": "DDR5 local (2 canais DDR5-4800)",
            "banda_pico_gb_s": pico_ddr, "banda_gb_s": pico_ddr * EFICIENCIA_DDR5,
            "latencia_ns": LEITURA_DDR5_NS + 2 * voo_ddr / 1000, "caminho_ns": voo_ddr / 1000,
            "coerente": True, "nesta_montagem": voo_ddr > 0},
        "unificada": {
            "nome": f"Unificada no encapsulamento (LPDDR5X-{UNIFICADA_MT_S}, {UNIFICADA_BITS} bits)",
            "banda_pico_gb_s": pico_uni, "banda_gb_s": pico_uni * EFICIENCIA_UNIFICADA,
            "latencia_ns": LEITURA_UNIFICADA_NS, "caminho_ns": 0.0,
            "coerente": True, "nesta_montagem": False},
    }
