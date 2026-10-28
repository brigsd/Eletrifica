"""Árvore de alimentação: da fonte de 12 V até cada trilho de cada peça."""

# conversor que alimenta cada trilho a partir dos 12 V (eficiência típica de cada tipo)
CONVERSOR = {
    ("i5-13600KF", "VCCIN"): ("VRM multifásico 8 fases", 0.92),
    ("i5-13600KF", "VCC_SA"): ("buck 1 fase", 0.88),
    ("i5-13600KF", "VCC1P8"): ("buck 1 fase", 0.86),
    ("i5-13600KF", "VDD2"): ("buck 1 fase", 0.88),
    ("DDR5-DIMM", "VIN_BULK"): ("buck 12->5 V", 0.94),
    ("GPU", "NUCLEO"): ("VRM do próprio módulo (cabo)", 0.90),
    ("GPU", "P3V3_AUX"): ("buck 12->3,3 V", 0.90),
    ("GDDR7", "VDD"): ("buck 1,2 V compartilhado", 0.88),
    ("GDDR7", "VDDQ"): ("buck 1,2 V compartilhado", 0.88),
    ("FPGA", "VCCINT"): ("buck 0,85 V", 0.87),
    ("FPGA", "VCCAUX"): ("buck 1,8 V", 0.88),
    ("FPGA", "MGTAVCC"): ("buck 0,9 V de baixo ruído (transceptores)", 0.85),
    ("FPGA", "MGTAVTT"): ("buck 1,2 V de baixo ruído (transceptores)", 0.85),
    ("PCH", "VCCSTBY"): ("buck 1,05 V de standby", 0.85),
    ("PCH", "VCCPRIM"): ("buck 1,05 V", 0.88),
}


def balanco(configuracao, carga="max", eficiencia_fonte=0.92, perdas_contatos_w=0.0):
    """carga: "max" ou "tipica". A potência de cada peça se divide entre os seus
    trilhos na proporção de tensão x corrente máxima."""
    trilhos = []
    for pc in configuracao.pecas:
        cat = pc.peca
        p_peca = cat.potencia_max if carga == "max" else cat.potencia_tipica
        pesos = {n: t.tensao * t.corrente_max for n, t in cat.trilhos.items()}
        soma = sum(pesos.values())
        for nome, t in cat.trilhos.items():
            p = p_peca * pesos[nome] / soma
            conv, eta = CONVERSOR[(cat.tipo, nome)]
            trilhos.append({"peca": pc.nome, "trilho": nome, "tensao_v": t.tensao,
                            "corrente_a": p / t.tensao, "potencia_w": p,
                            "acima_do_maximo": p / t.tensao > t.corrente_max,
                            "via": "cabo" if t.origem == "cabo" else "base",
                            "conversor": conv, "eficiencia": eta,
                            "entrada_12v_w": p / eta})
    p_carga = sum(t["potencia_w"] for t in trilhos)
    p_12v = sum(t["entrada_12v_w"] for t in trilhos) + perdas_contatos_w
    return {
        "trilhos": trilhos,
        "potencia_cargas_w": p_carga,
        "perdas_conversores_w": p_12v - p_carga - perdas_contatos_w,
        "perdas_contatos_w": perdas_contatos_w,
        "carga_fonte_12v_w": p_12v,
        "corrente_fonte_12v_a": p_12v / 12.0,
        "pela_base_w": sum(t["entrada_12v_w"] for t in trilhos if t["via"] == "base"),
        "pelo_cabo_w": sum(t["entrada_12v_w"] for t in trilhos if t["via"] == "cabo"),
        "tomada_w": p_12v / eficiencia_fonte,
        "eficiencia_total": p_carga / (p_12v / eficiencia_fonte),
    }
