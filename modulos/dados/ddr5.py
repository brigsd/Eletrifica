"""Ajustes elétricos que a CPU programa na memória, e quem precisa espelhá-los.

A CPU escreve, por MRW, a terminação (RTT_WR, RTT_NOM, RTT_PARK, ODT de CA,
CK e DQS) e a força de saída do DRAM. Numa placa comum é o próprio DRAM que
obedece. Com a base no meio, a CPU enxerga o tradutor do lado dela: ele tem de
parecer o DRAM (terminar como o RTT programado quando a CPU escreve, dirigir
com a força programada quando a CPU lê, estacionar em RTT_PARK no ocioso). O
tradutor do lado do DIMM tem de parecer o controlador para o DRAM, com valores
que não passam pelo barramento e ficam fixos desde o treino.

O efeito de não espelhar é estimado por divisor resistivo e coeficiente de
reflexão na linha de Z0.
"""
from dataclasses import dataclass, field

from modulos.dados import comandos as K

Z0_OHM = 40.0                     # trilha single-ended da base
VDDQ_MV = {"DDR5-4800": 1100.0, "GDDR7-32": 1200.0}
CPU_FORCA_OHM = 34.0              # driver do controlador (configuração interna da CPU)
CPU_ODT_OHM = 40.0                # terminação do controlador nas leituras
FIXO_SEM_ESPELHO = {"terminacao": 40.0, "forca": 34.0}   # tradutor que não lê MRW

RTT = {0: None, 1: 240.0, 2: 120.0, 3: 80.0, 4: 60.0, 5: 48.0, 6: 40.0, 7: 34.0}
DRV = {0: 34.0, 1: 40.0, 2: 48.0}

# registrador -> [(campo, bit inicial, tabela de códigos)]
CAMPOS = {
    "DDR5-4800": {5: [("DRV", 1, DRV)],
                  32: [("CK_ODT", 0, RTT), ("CS_ODT", 3, RTT)],
                  33: [("CA_ODT", 0, RTT), ("DQS_RTT_PARK", 3, RTT)],
                  34: [("RTT_PARK", 0, RTT), ("RTT_WR", 3, RTT)],
                  35: [("RTT_NOM_WR", 0, RTT), ("RTT_NOM_RD", 3, RTT)]},
    "GDDR7-32": {3: [("DRV", 0, {0: 40.0, 1: 48.0})],
                 7: [("RTT_DQ", 0, {0: None, 1: 120.0, 2: 60.0, 3: 40.0})],
                 8: [("CA_ODT", 0, {0: None, 1: 120.0, 2: 60.0, 3: 40.0})]},
}

# o que o padrão deixa a CPU programar: as faixas do tradutor têm de cobrir isto
PERMITIDOS = {
    p: {"terminacao": sorted({v for mr in c.values() for nome, _, tab in mr if nome != "DRV"
                              for v in tab.values()}, key=lambda v: (v is None, v or 0)),
        "forca": sorted({v for mr in c.values() for nome, _, tab in mr if nome == "DRV"
                         for v in tab.values()})}
    for p, c in CAMPOS.items()
}

# campos que o tradutor do lado do controlador espelha, por situação do barramento
ESPELHO_LADO_CONTROLADOR = {"escrita": "RTT_WR", "leitura": "DRV", "ocioso": "RTT_PARK",
                            "CA": "CA_ODT", "CK": "CK_ODT", "DQS": "DQS_RTT_PARK"}


def espelho(protocolo):
    """Campos que o tradutor do lado do controlador tem de espelhar neste protocolo."""
    campos = {n for mr in CAMPOS[protocolo].values() for n, _, _ in mr}
    if protocolo == "DDR5-4800":
        return sorted(set(ESPELHO_LADO_CONTROLADOR.values()) & campos)
    return sorted(campos)


def codigo(protocolo, mr, **valores):
    """Byte de OP de um MRW com os valores pedidos (em Ω, None = desligado)."""
    op = 0
    for nome, bit, tab in CAMPOS[protocolo][mr]:
        if nome in valores:
            inv = {v: k for k, v in tab.items()}
            op |= inv[valores[nome]] << bit
    return op


def aplicar_mr(protocolo, estado, ma, op):
    for nome, bit, tab in CAMPOS[protocolo].get(ma, ()):
        cod = (op >> bit) & 0b111
        if cod in tab:
            estado[nome] = tab[cod]
    return estado


@dataclass
class Passo:
    comando: str
    situacao: str               # escrita | leitura | ocioso
    programado: dict            # o que o DRAM apresentaria numa placa comum
    visto_cpu: dict             # o que o tradutor apresenta à CPU
    visto_dram: dict
    eletrico: dict = field(default_factory=dict)
    diverge: bool = False


def sequencia_padrao(protocolo="DDR5-4800"):
    """Treino típico: programa terminação e força, escreve, lê, e muda o RTT_WR em uso."""
    c = lambda n, **kw: K.codificar(protocolo, n, **kw)
    return (c("MRW", ma=34, op=codigo(protocolo, 34, RTT_PARK=60.0, RTT_WR=80.0))
            + c("MRW", ma=35, op=codigo(protocolo, 35, RTT_NOM_WR=120.0, RTT_NOM_RD=None))
            + c("MRW", ma=5, op=codigo(protocolo, 5, DRV=34.0))
            + c("MRW", ma=33, op=codigo(protocolo, 33, CA_ODT=80.0, DQS_RTT_PARK=60.0))
            + c("WR", banco=1, coluna=8) + c("RD", banco=1, coluna=8) + c("NOP")
            + c("MRW", ma=34, op=codigo(protocolo, 34, RTT_PARK=60.0, RTT_WR=240.0))
            + c("WR", banco=2, coluna=16) + c("RD", banco=2, coluna=16))


def _divisor(zs, zt):
    if zt is None:
        return 1.0
    return zt / (zs + zt)


def _gamma(z):
    return 1.0 if z is None else (z - Z0_OHM) / (z + Z0_OHM)


def _apresentado(estado, situacao):
    """Terminação e força que o DRAM apresentaria ao controlador nesta situação."""
    if situacao == "escrita":
        return {"terminacao": estado.get("RTT_WR"), "forca": None}
    if situacao == "leitura":
        return {"terminacao": None, "forca": estado.get("DRV")}
    return {"terminacao": estado.get("RTT_PARK"), "forca": None}


def _eletrico(protocolo, situacao, ap):
    vddq = VDDQ_MV[protocolo]
    if situacao == "escrita":
        return {"amplitude_mv": vddq * _divisor(CPU_FORCA_OHM, ap["terminacao"]),
                "gamma": _gamma(ap["terminacao"])}
    if situacao == "leitura":
        return {"amplitude_mv": vddq * _divisor(ap["forca"], CPU_ODT_OHM), "gamma": _gamma(ap["forca"])}
    return {"amplitude_mv": 0.0, "gamma": _gamma(ap["terminacao"])}


def simular(palavras=None, protocolo="DDR5-4800", espelhar=True):
    """Passa a sequência de CA pelo detector do tradutor e compara, a cada comando, o que a
    CPU enxerga com o que um DRAM programado igual apresentaria."""
    palavras = sequencia_padrao(protocolo) if palavras is None else palavras
    estado, passos = {}, []
    for cmd in K.decodificar(protocolo, palavras):
        if cmd.registrador:
            aplicar_mr(protocolo, estado, *cmd.registrador)
        situacao = cmd.sentido_dq or "ocioso"
        prog = _apresentado(estado, situacao)
        if espelhar:
            visto = dict(prog)
        else:
            visto = {"terminacao": None if situacao == "leitura" else FIXO_SEM_ESPELHO["terminacao"],
                     "forca": FIXO_SEM_ESPELHO["forca"] if situacao == "leitura" else None}
        dram = {"terminacao": CPU_ODT_OHM if situacao == "leitura" else None,
                "forca": CPU_FORCA_OHM if situacao == "escrita" else None}
        e_prog, e_visto = _eletrico(protocolo, situacao, prog), _eletrico(protocolo, situacao, visto)
        el = {"amplitude_programada_mv": e_prog["amplitude_mv"], "amplitude_vista_mv": e_visto["amplitude_mv"],
              "gamma_programado": e_prog["gamma"], "gamma_visto": e_visto["gamma"],
              "erro_amplitude_mv": e_visto["amplitude_mv"] - e_prog["amplitude_mv"]}
        passos.append(Passo(cmd.nome, situacao, prog, visto, dram, el, visto != prog))
    return passos


def resumo(passos):
    div = [p for p in passos if p.diverge]
    por_situacao = {}
    for p in div:
        atual = por_situacao.get(p.situacao)
        if atual is None or abs(p.eletrico["erro_amplitude_mv"]) > abs(atual.eletrico["erro_amplitude_mv"]):
            por_situacao[p.situacao] = p

    def ohm(d):
        v = d["terminacao"] if d["terminacao"] is not None or d["forca"] is None else d["forca"]
        return "aberto" if v is None else f"{v:.0f} Ω"
    return {"comandos": len(passos), "divergem": len(div),
            "pior_erro_amplitude_mv": max((abs(p.eletrico["erro_amplitude_mv"]) for p in div), default=0.0),
            "pior_erro_gamma": max((abs(p.eletrico["gamma_visto"] - p.eletrico["gamma_programado"])
                                    for p in div), default=0.0),
            "por_situacao": {s: {"comando": p.comando, "programado": ohm(p.programado),
                                 "visto": ohm(p.visto_cpu),
                                 "erro_amplitude_mv": p.eletrico["erro_amplitude_mv"],
                                 "gamma_programado": p.eletrico["gamma_programado"],
                                 "gamma_visto": p.eletrico["gamma_visto"]}
                             for s, p in por_situacao.items()}}


def avaliar_netlist(netlist):
    """Para cada chave de sentido de DDR5/GDDR7 do lado do controlador: ela espelha os campos
    necessários, cobre as faixas do padrão e é comandada por um detector que lê MRW?"""
    problemas, chaves = [], 0
    for ch in netlist.por_tipo("chave_sentido"):
        a = ch.atributos
        prot = a.get("protocolo")
        if prot not in CAMPOS or a.get("papel_eletrico") != "parece_memoria":
            continue
        chaves += 1
        falta = [c for c in espelho(prot) if c not in a.get("espelha", ())]
        det = _detector_de(netlist, ch.id)
        le_mrw = det is not None and any(x.startswith(("MRW", "MRS")) for x in det.atributos.get("decodifica", ()))
        if falta and not set(falta) <= {"CA_ODT", "CK_ODT"}:
            problemas.append((ch.id, f"{ch.id} não espelha {falta}"))
        if not le_mrw:
            problemas.append((ch.id, f"{ch.id}: o detector não decodifica MRW, a terminação não acompanha a CPU"))
    passos = simular(espelhar=not problemas)
    return {"chaves": chaves, "problemas": problemas, "resumo": resumo(passos)}


def _detector_de(netlist, chave):
    for lig in netlist.ligacoes_de((chave, "sentido")):
        outro = lig.b if lig.a == (chave, "sentido") else lig.a
        b = netlist.blocos.get(outro[0])
        if b is not None and b.tipo == "detector_sentido":
            return b
    return None
