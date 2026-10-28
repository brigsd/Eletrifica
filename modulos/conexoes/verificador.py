"""Verificador de conexões do sistema (um ERC para a base inteira).

Lê só a netlist (`netlist.Netlist`) e diz, regra a regra, o que não fecha:
caminho, sentido, padrão elétrico, banda, luz, energia, controle, capacidade,
tempo, relógio, requisitos e sobras. Não conserta nada.

    from modulos.conexoes.verificador import verificar
    rel = verificar(netlist)          # rel.ok, rel.violacoes, rel.resumo()
"""
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from modulos.conexoes.netlist import TIPOS
from modulos.conexoes.padroes import PADROES
from modulos.dados.protocolos import PROTOCOLOS

REGRAS = ("R01-caminho", "R02-sentido", "R03-padrao", "R04-banda", "R05-optico",
          "R06-energia", "R07-controle", "R08-capacidade", "R09-tempo", "R10-relogio",
          "R11-requisito", "R12-orfao", "R13-temperatura", "R14-consumo",
          "R15-decodificacao", "R16-ajuste", "R17-pcie", "R18-memoria-compartilhada",
          "R19-posse", "R20-banco")

# capacidades que melhoram o sistema mas não impedem o boot (R18 avisa)
OPCIONAIS = {"memoria-compartilhada"}
# regiões da imagem da flash que cada firmware exige
REGIOES_FIRMWARE = {"firmware-UEFI": ("descritor", "BIOS"), "firmware-ME": ("descritor", "ME")}

# perda máxima das trilhas elétricas em cada lado do enlace, na frequência de Nyquist
ORCAMENTO_TRILHA_DB = {"PCIe5-CML": 8.0, "PCIe4-CML": 8.0, "GDDR7-DQ": 4.0, "GDDR7-EDC": 4.0,
                       "GDDR7-WCK": 4.0}
ORCAMENTO_TRILHA_PADRAO_DB = 6.0
ORCAMENTO_TRILHA_LENTO_DB = 20.0

# atraso total pino a pino tolerado por protocolo (ps)
ATRASO_MAX_PS = {"DDR5-4800": 1500.0, "GDDR7-32": 1000.0, "PCIe5": 10000.0,
                 "PCIe4": 10000.0, "AUX": 100000.0}
PS_POR_MM_FIBRA = 1.468 / 299_792_458.0 * 1e9   # ~4,9 ps/mm
PS_POR_MM_TRILHA = 6.8
ALCANCE_TREINO_UI = 2.0
MAX_DISPOSITIVOS_BARRAMENTO = 32

# blocos que não funcionam sem alimentação, mesmo sem porta declarada
PRECISAM_ENERGIA = {"chip_tradutor", "laser", "regulador", "controlador", "relogio",
                    "detector_sentido", "detector_rank", "conversor_nivel"}
# portas sem as quais o bloco não faz sentido
OBRIGATORIAS = {
    "pino": ("e",), "celula": ("pino", "base"), "trilha": ("a", "b"),
    "chip_tradutor": ("vdd", "ctl", "laser"),
    "via_tx": ("e", "luz", "laser", "vdd", "ctl"), "via_rx": ("luz", "e", "vdd", "ctl"),
    "chave_sentido": ("pino", "tx", "rx", "sentido"), "detector_sentido": ("sentido",),
    "acoplador": ("chip", "fibra"), "fibra": ("a", "b"), "regulador": ("vin", "vout"),
    "laser": ("vdd",),
    "seletor_rank": ("pino", "r0", "sel"), "mux_dono": ("pino", "sel"), "detector_rank": ("rank", "vdd"),
}
PASSIVOS_ELETRICOS = {"celula", "trilha"}            # ligam suas portas elétricas por dentro
PASSIVOS_OPTICOS = {"fibra", "divisor", "acoplador", "chip_tradutor"}
RELOGIO_PAPEIS = ("DQS",)


@dataclass
class Violacao:
    regra: str
    severidade: str      # "erro" | "aviso"
    alvo: str
    mensagem: str


@dataclass
class Relatorio:
    violacoes: list = field(default_factory=list)

    @property
    def por_regra(self):
        return Counter(v.regra for v in self.violacoes)

    def contagem(self, regra, severidade="erro"):
        return sum(1 for v in self.violacoes if v.regra == regra and v.severidade == severidade)

    @property
    def erros(self):
        return [v for v in self.violacoes if v.severidade == "erro"]

    @property
    def ok(self):
        return not self.erros

    def regras_com_erro(self):
        return {v.regra for v in self.erros}

    def resumo(self):
        linhas = []
        for r in REGRAS:
            e, a = self.contagem(r, "erro"), self.contagem(r, "aviso")
            exemplo = next((v.mensagem for v in self.violacoes if v.regra == r), "")
            linhas.append(f"{r:15s} {e:5d} erros {a:5d} avisos" + (f"  ex.: {exemplo}" if exemplo else ""))
        linhas.append(f"{'total':15s} {len(self.erros):5d} erros "
                      f"{len(self.violacoes) - len(self.erros):5d} avisos -> "
                      f"{'OK' if self.ok else 'REPROVADO'}")
        return "\n".join(linhas)


# --------------------------------------------------------------------- apoio
class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _porta(net, ponto):
    b = net.blocos.get(ponto[0])
    return b.portas.get(ponto[1]) if b else None


def _redes_eletricas(net):
    uf = _UF()
    for b in net.blocos.values():
        for nome, p in b.portas.items():
            if p.dominio == "eletrico":
                uf.find((b.id, nome))
        if b.tipo in PASSIVOS_ELETRICOS:
            el = [n for n, p in b.portas.items() if p.dominio == "eletrico"]
            for n in el[1:]:
                uf.union((b.id, el[0]), (b.id, n))
    for lig in net.ligacoes:
        pa, pb = _porta(net, lig.a), _porta(net, lig.b)
        if pa and pb and pa.dominio == "eletrico" and pb.dominio == "eletrico":
            uf.union(lig.a, lig.b)
    redes = defaultdict(list)
    for ponto in list(uf.p):
        redes[uf.find(ponto)].append(ponto)
    return uf, redes


def _alcance(net, inicio, dominio, atravessa):
    """Pontos (bloco, porta) alcançáveis por ligações do mesmo domínio, passando por
    dentro dos blocos cujo tipo está em `atravessa`."""
    vistos, pilha, blocos = set(), [tuple(inicio)], set()
    while pilha:
        pt = pilha.pop()
        if pt in vistos:
            continue
        vistos.add(pt)
        b = net.blocos.get(pt[0])
        if b is None:
            continue
        blocos.add(b.id)
        for lig in net.ligacoes_de(pt):
            outro = lig.b if lig.a == pt else lig.a
            p = _porta(net, outro)
            if p and p.dominio == dominio:
                pilha.append(outro)
        if b.tipo in atravessa:
            for n, p in b.portas.items():
                if p.dominio == dominio:
                    pilha.append((b.id, n))
    return vistos, blocos


def _f_nyquist_ghz(pad):
    if pad.codificacao == "relogio":
        return pad.taxa_gbps / 2
    baud = pad.taxa_gbps / (1.5 if pad.codificacao == "PAM3" else 1.0)
    return baud / 2


def _simbolo(pad):
    return "PAM3" if pad.codificacao == "PAM3" else "NRZ"


def _blocos_do_caminho(caminho):
    out = []
    for bid, _ in caminho:
        if not out or out[-1] != bid:
            out.append(bid)
    return out


def _pontas_esperadas(s, sentido):
    return (s.origem, s.destino) if sentido == "ida" else (s.destino, s.origem)


# --------------------------------------------------------------------- regras
def _r01(net, rel):
    R = "R01-caminho"
    for s in net.sinais.values():
        for sentido in s.sentidos:
            cam = s.caminhos.get(sentido)
            if not cam:
                rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id}: sem caminho no sentido {sentido}"))
                continue
            ini, fim = _pontas_esperadas(s, sentido)
            if tuple(cam[0]) != tuple(ini) or tuple(cam[-1]) != tuple(fim):
                rel.violacoes.append(Violacao(R, "erro", s.id,
                                              f"{s.id} ({sentido}): começa em {cam[0]} e termina em {cam[-1]}, "
                                              f"esperado {ini} -> {fim}"))
            for pt in cam:
                if _porta(net, pt) is None:
                    rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id}: porta inexistente {pt}"))
            for p, q in zip(cam, cam[1:]):
                if p[0] != q[0] and net.ligacao_entre(p, q) is None:
                    rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id} ({sentido}): {p} e {q} não estão ligados"))


def _r02(net, rel, redes):
    R = "R02-sentido"
    for s in net.sinais.values():
        for sentido, cam in s.caminhos.items():
            for i, (p, q) in enumerate(zip(cam, cam[1:])):
                pp, pq = _porta(net, p), _porta(net, q)
                if not pp or not pq:
                    continue
                if p[0] != q[0]:
                    if pp.sentido == "entra" or pq.sentido == "sai":
                        rel.violacoes.append(Violacao(R, "erro", s.id,
                                                      f"{s.id} ({sentido}): {p}[{pp.sentido}] -> {q}[{pq.sentido}]"))
                elif pp.sentido == "sai" or pq.sentido == "entra":
                    rel.violacoes.append(Violacao(R, "erro", s.id,
                                                  f"{s.id} ({sentido}): atravessa {p[0]} de {p[1]}[{pp.sentido}] "
                                                  f"para {q[1]}[{pq.sentido}]"))
        pad = PADROES.get(s.padrao)
        if pad and pad.bidirecional and len(s.sentidos) < 2:
            rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id}: pino bidirecional com caminho num sentido só"))
        optico = any(net.blocos.get(b) is not None and net.blocos[b].tipo in ("via_tx", "via_rx")
                     for cam in s.caminhos.values() for b in _blocos_do_caminho(cam))
        if len(s.sentidos) == 2 and optico:
            for sentido, cam in s.caminhos.items():
                chaves = [b for b in _blocos_do_caminho(cam) if net.blocos.get(b) and net.blocos[b].tipo == "chave_sentido"]
                if len(chaves) < 2:
                    rel.violacoes.append(Violacao(R, "erro", s.id,
                                                  f"{s.id} ({sentido}): bidirecional sem chave de sentido nas duas pontas"))
                for c in chaves:
                    ok = False
                    for lig in net.ligacoes_de((c, "sentido")):
                        outro = lig.b if lig.a == (c, "sentido") else lig.a
                        det = net.blocos.get(outro[0])
                        if det and det.tipo == "detector_sentido":
                            ok = any(net.ligacoes_de((det.id, n)) for n in det.portas if n.startswith("ca"))
                    if not ok:
                        rel.violacoes.append(Violacao(R, "erro", c,
                                                      f"{c}: chave de sentido sem detector lendo o comando (CA)"))
    for raiz, pontos in redes.items():
        portas = [(pt, _porta(net, pt)) for pt in pontos]
        drivers = [(pt, p) for pt, p in portas if p.sentido == "sai"]
        abertos = all(PADROES.get(p.padrao) and PADROES[p.padrao].terminacao == "dreno_aberto"
                      for _, p in drivers)
        if len(drivers) > 1 and not abertos:
            rel.violacoes.append(Violacao(R, "erro", drivers[0][0][0],
                                          f"rede com {len(drivers)} drivers: {[d[0] for d in drivers][:4]}"))
        tem_driver = any(p.sentido in ("sai", "bidir") for _, p in portas)
        entradas = [pt for pt, p in portas if p.sentido == "entra"]
        ligada = any(net.ligacoes_de(pt) for pt in pontos)
        if entradas and not tem_driver and ligada:
            rel.violacoes.append(Violacao(R, "erro", entradas[0][0], f"entrada sem driver: {entradas[:3]}"))


def _r03(net, rel):
    R = "R03-padrao"
    for s in net.sinais.values():
        pad = PADROES.get(s.padrao)
        if pad is None:
            rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id}: padrão desconhecido {s.padrao}"))
            continue
        for sentido, cam in s.caminhos.items():
            blocos = _blocos_do_caminho(cam)
            for bid in blocos:
                b = net.blocos.get(bid)
                if b is None or b.tipo not in ("via_tx", "via_rx"):
                    continue
                e = b.portas.get("e")
                suportados = (e.atributos.get("padroes") if e else None) or b.atributos.get("padroes")
                if not suportados or s.padrao not in suportados:
                    rel.violacoes.append(Violacao(R, "erro", bid, f"{bid} não suporta {s.padrao} ({s.id})"))
                term = (e.atributos.get("terminacao") if e else None) or b.atributos.get("terminacao")
                if b.tipo == "via_rx" and term and pad.terminacao in ("odt", "cml_ac", "hcsl") \
                        and term != pad.terminacao:
                    rel.violacoes.append(Violacao(R, "erro", bid,
                                                  f"{bid}: terminação {term}, o padrão {s.padrao} pede {pad.terminacao}"))
            # níveis ao longo do caminho
            anterior, conversor = None, False
            for pt in cam:
                b = net.blocos.get(pt[0])
                if b and b.tipo == "conversor_nivel":
                    conversor = True
                p = _porta(net, pt)
                if not p or p.dominio != "eletrico" or not p.padrao:
                    continue
                if p.padrao not in PADROES:
                    rel.violacoes.append(Violacao(R, "erro", pt[0], f"{pt}: padrão desconhecido {p.padrao}"))
                    continue
                if anterior and anterior != p.padrao and not conversor:
                    a, c = PADROES[anterior], PADROES[p.padrao]
                    tipo = "nível" if (a.tensao_v != c.tensao_v or a.modo != c.modo) else "padrão"
                    rel.violacoes.append(Violacao(R, "erro", s.id,
                                                  f"{s.id}: {tipo} muda de {anterior} para {p.padrao} em {pt} "
                                                  f"sem conversor_nivel"))
                anterior, conversor = p.padrao, False
            if pad.terminacao == "dreno_aberto":
                no_caminho = set(blocos)
                tem = any(b.tipo == "terminacao" and any(
                    (lig.b if lig.a[0] == b.id else lig.a)[0] in no_caminho
                    for n in b.portas for lig in net.ligacoes_de((b.id, n)))
                    for b in net.por_tipo("terminacao"))
                if not tem:
                    rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id}: dreno aberto sem resistor de pull-up"))


def _r04(net, rel, contexto=None):
    R = "R04-banda"
    orcamentos = {**ORCAMENTO_TRILHA_DB, **(contexto or {}).get("orcamento_trilha_db", {})}
    for s in net.sinais.values():
        pad = PADROES.get(s.padrao)
        if pad is None:
            continue
        fn = _f_nyquist_ghz(pad)
        orc = orcamentos.get(pad.nome, ORCAMENTO_TRILHA_PADRAO_DB) if pad.alta_velocidade \
            else orcamentos.get(pad.nome, ORCAMENTO_TRILHA_LENTO_DB)
        for sentido, cam in s.caminhos.items():
            perda, trecho = 0.0, 0
            for bid in _blocos_do_caminho(cam):
                b = net.blocos.get(bid)
                if b is None:
                    continue
                a = b.atributos
                if b.tipo == "celula":
                    n = max(a.get("n_celulas", 1), 1)
                    if "r_on_ohm" in a and "c_ff" in a:
                        r = a["r_on_ohm"] / n + pad.impedancia_ohm / 2
                        f3 = 1 / (2 * math.pi * r * a["c_ff"] * n * 1e-15) / 1e9
                        if f3 < fn:
                            rel.violacoes.append(Violacao(R, "erro", bid,
                                                          f"{bid}: banda {f3:.1f} GHz < {fn:.1f} GHz de {s.padrao}"))
                elif b.tipo == "trilha":
                    perda += a.get("perda_db_mm_ghz", 0.0) * a.get("comprimento_mm", 0.0) * fn
                elif b.tipo in ("via_tx", "via_rx"):
                    if perda > orc:
                        rel.violacoes.append(Violacao(R, "erro", s.id,
                                                      f"{s.id} ({sentido}): trilhas perdem {perda:.1f} dB "
                                                      f"a {fn:.1f} GHz, orçamento {orc:.1f} dB"))
                    perda, trecho = 0.0, trecho + 1
                    tmax = a.get("taxa_max_gbps")
                    if tmax is not None and tmax < pad.taxa_gbps:
                        rel.violacoes.append(Violacao(R, "erro", bid,
                                                      f"{bid}: {tmax} Gb/s < {pad.taxa_gbps} Gb/s de {s.padrao}"))
                    banda = a.get("banda_ghz")
                    if banda is not None and banda < fn:
                        rel.violacoes.append(Violacao(R, "erro", bid, f"{bid}: banda {banda} GHz < {fn:.1f} GHz"))
            if perda > orc:
                rel.violacoes.append(Violacao(R, "erro", s.id,
                                              f"{s.id} ({sentido}): trilhas perdem {perda:.1f} dB "
                                              f"a {fn:.1f} GHz, orçamento {orc:.1f} dB"))


_MARGENS_PADRAO = {}


def _margem(contexto, s, pad):
    m = (contexto or {}).get("margem_db")
    if isinstance(m, (int, float)):
        return float(m)
    if isinstance(m, dict):
        for k in (s.protocolo, s.padrao, _simbolo(pad), "padrao"):
            if k in m:
                return float(m[k])
    sim = _simbolo(pad)
    if sim not in _MARGENS_PADRAO:
        from modulos.optica import enlace as E
        _MARGENS_PADRAO[sim] = E.orcamento(E.carregar("viavel"), simbolo=sim)["margem_db"]
    return _MARGENS_PADRAO[sim]


def _r05(net, rel, contexto):
    R = "R05-optico"
    laser_ok = {}

    def lambdas_do_laser(via):
        if via in laser_ok:
            return laser_ok[via]
        _, blocos = _alcance(net, (via, "laser"), "optico", PASSIVOS_OPTICOS)
        lam = set()
        for bid in blocos:
            b = net.blocos[bid]
            if b.tipo == "laser":
                lam |= {round(x, 3) for x in b.atributos.get("lambdas_nm", [])}
        laser_ok[via] = lam
        return lam

    for b in net.por_tipo("via_tx"):
        luz = b.portas.get("luz")
        lam = luz.atributos.get("lambda_nm") if luz else None
        if lam is None:
            rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}: sem comprimento de onda"))
            continue
        disp = lambdas_do_laser(b.id) if "laser" in b.portas else set()
        if round(lam, 3) not in disp:
            rel.violacoes.append(Violacao(R, "erro", b.id,
                                          f"{b.id}: nenhum laser entrega {lam:.2f} nm na porta laser"))

    por_fibra = defaultdict(list)
    for s in net.sinais.values():
        pad = PADROES.get(s.padrao)
        for sentido, cam in s.caminhos.items():
            blocos = _blocos_do_caminho(cam)
            tipos = [net.blocos[x].tipo if x in net.blocos else None for x in blocos]
            if "via_tx" not in tipos:
                continue
            i_tx = tipos.index("via_tx")
            if "via_rx" not in tipos[i_tx:]:
                rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id} ({sentido}): via_tx sem via_rx depois"))
                continue
            i_rx = i_tx + tipos[i_tx:].index("via_rx")
            meio = Counter(tipos[i_tx + 1:i_rx])
            falta = [t for t, n in (("mux", 1), ("acoplador", 2), ("fibra", 1), ("demux", 1)) if meio[t] < n]
            if falta:
                rel.violacoes.append(Violacao(R, "erro", s.id, f"{s.id} ({sentido}): falta {falta} entre as vias"))
            ltx = net.blocos[blocos[i_tx]].portas.get("luz")
            lrx = net.blocos[blocos[i_rx]].portas.get("luz")
            lt = ltx.atributos.get("lambda_nm") if ltx else None
            lr = lrx.atributos.get("lambda_nm") if lrx else None
            if lt is None or lr is None or abs(lt - lr) > 0.01:
                rel.violacoes.append(Violacao(R, "erro", s.id,
                                              f"{s.id} ({sentido}): transmite em {lt} nm e recebe em {lr} nm"))
            for f in blocos[i_tx + 1:i_rx]:
                if net.blocos.get(f) and net.blocos[f].tipo == "fibra" and lt is not None:
                    por_fibra[f].append((round(lt, 3), blocos[i_tx], s.id))
            if pad is not None:
                extra = sum(net.blocos[x].atributos.get("perda_extra_db", 0.0) for x in blocos if x in net.blocos)
                m = _margem(contexto, s, pad) - extra
                if not (m > 0):
                    rel.violacoes.append(Violacao(R, "erro", s.id,
                                                  f"{s.id} ({sentido}): margem óptica {m:.2f} dB"))
    for f, usos in por_fibra.items():
        # ida e volta de um pino comutado usam o mesmo λ, nunca ao mesmo tempo; um modulador
        # que atende vários chips de um grupo (seletor de rank) é um λ só. Usos ligados por
        # sinal ou por modulador são um uso; dois grupos sem ligação colidem
        rep = []
        for lam in sorted({l for l, _, _ in usos}):
            uf = _UF()
            for l, via, sid in usos:
                if l == lam:
                    uf.union(("via", via), ("sinal", sid))
            if len({uf.find(k) for k in list(uf.p)}) > 1:
                rep.append(lam)
        if rep:
            rel.violacoes.append(Violacao(R, "erro", f, f"{f}: comprimento de onda repetido {rep[:4]}"))
    for f in net.por_tipo("fibra"):
        lam = [round(x, 3) for x in f.atributos.get("lambdas_nm", [])]
        if len(lam) != len(set(lam)):
            rel.violacoes.append(Violacao(R, "erro", f.id, f"{f.id}: lista de λ com repetição"))


def _fontes_de_energia(net):
    """Para cada ponto de energia, se ele chega a uma fonte (por regulador ou direto)."""
    uf = _UF()
    for b in net.blocos.values():
        ens = [n for n, p in b.portas.items() if p.dominio == "energia"]
        for n in ens:
            uf.find((b.id, n))
        if b.tipo == "trilho":
            for n in ens[1:]:
                uf.union((b.id, ens[0]), (b.id, n))
    for lig in net.ligacoes:
        pa, pb = _porta(net, lig.a), _porta(net, lig.b)
        if pa and pb and pa.dominio == "energia" and pb.dominio == "energia":
            uf.union(lig.a, lig.b)
    redes = defaultdict(list)
    for pt in list(uf.p):
        redes[uf.find(pt)].append(pt)
    return uf, redes


def _r06(net, rel):
    R = "R06-energia"
    uf, redes = _fontes_de_energia(net)
    alimentada = {}

    def rede_ok(raiz, pilha=()):
        if raiz in alimentada:
            return alimentada[raiz]
        if raiz in pilha:
            return False
        ok = False
        for bid, porta in redes[raiz]:
            b = net.blocos[bid]
            if b.tipo == "fonte" and b.portas[porta].sentido in ("sai", "bidir"):
                ok = True
            elif b.tipo == "regulador" and porta == "vout" and "vin" in b.portas:
                ok = ok or rede_ok(uf.find((bid, "vin")), pilha + (raiz,))
        alimentada[raiz] = ok
        return ok

    def portas_energia(b):
        return [n for n, p in b.portas.items() if p.dominio == "energia" and p.sentido != "sai"
                and not (b.tipo == "regulador" and n == "vout")]

    for b in net.blocos.values():
        if b.tipo in ("fonte", "trilho"):
            continue
        ens = portas_energia(b)
        if b.tipo in PRECISAM_ENERGIA and not ens:
            rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}: {b.tipo} sem porta de alimentação"))
            continue
        for n in ens:
            raiz = uf.find((b.id, n))
            ligado = len(redes[raiz]) > 1
            if not ligado or not rede_ok(raiz):
                rel.violacoes.append(Violacao(R, "erro", b.id,
                                              f"{b.id}.{n}: não chega a um regulador alimentado pela fonte"))
    # carga em cada regulador
    for reg in net.por_tipo("regulador"):
        if "vout" not in reg.portas:
            continue
        lim = reg.atributos.get("corrente_max_a")
        if lim is None:
            continue
        v = reg.atributos.get("tensao_v") or reg.portas["vout"].atributos.get("tensao_v") or 1.0
        carga = 0.0
        for bid, porta in redes[uf.find((reg.id, "vout"))]:
            if bid == reg.id:
                continue
            b = net.blocos[bid]
            p = b.portas[porta]
            if p.sentido == "sai" or b.tipo in ("trilho", "fonte"):
                continue
            if "corrente_a" in p.atributos:
                carga += p.atributos["corrente_a"]
            elif "corrente_a" in b.atributos:
                carga += b.atributos["corrente_a"]
            elif "potencia_w" in b.atributos:
                carga += b.atributos["potencia_w"] / (p.atributos.get("tensao_v") or v)
            elif b.tipo == "regulador" and porta == "vin" and "corrente_max_a" in b.atributos:
                vo = b.atributos.get("tensao_v", v)
                carga += b.atributos["corrente_max_a"] * vo / max(v, 1e-9) / b.atributos.get("eficiencia", 0.9)
        if carga > lim:
            rel.violacoes.append(Violacao(R, "erro", reg.id,
                                          f"{reg.id}: carga de {carga:.2f} A > {lim:.2f} A"))


CORRENTE_MAX_CONTATO_A = 1.0     # "cerca de 1 A por contato", do conceito


def _r06_contatos(rel, contexto):
    """Corrente por pino e por célula, vinda de modulos.energia.contatos.distribuir."""
    R = "R06-energia"
    from modulos.sistema.celula import chave
    for d in (contexto or {}).get("contatos", ()):
        ch = chave(d.get("chave"))
        alvo = f"{d['peca']}:{d['trilho']}"
        if d["pinos_acima_1a"]:
            rel.violacoes.append(Violacao(R, "erro", alvo,
                                          f"{alvo}: {d['pinos_acima_1a']} pinos acima de "
                                          f"{CORRENTE_MAX_CONTATO_A:.0f} A (máx. {d['pino_max_a']:.2f} A)"))
        if d["celula_max_a"] > ch.corrente_max_a:
            rel.violacoes.append(Violacao(R, "erro", alvo,
                                          f"{alvo}: célula com {d['celula_max_a']:.2f} A > "
                                          f"{ch.corrente_max_a:.2f} A da chave {ch.nome}"))


def _r07(net, rel):
    R = "R07-controle"
    controladores = {b.id for b in net.por_tipo("controlador")}
    uf = _UF()
    for b in net.blocos.values():
        cs = [n for n, p in b.portas.items() if p.dominio == "controle"]
        for n in cs:
            uf.find((b.id, n))
        if b.tipo in ("chip_tradutor", "controlador") and len(cs) > 1:
            for n in cs[1:]:
                uf.union((b.id, cs[0]), (b.id, n))
    for lig in net.ligacoes:
        pa, pb = _porta(net, lig.a), _porta(net, lig.b)
        if pa and pb and pa.dominio == "controle" and pb.dominio == "controle":
            uf.union(lig.a, lig.b)
    raizes_ok = {uf.find(pt) for pt in uf.p if pt[0] in controladores}
    for b in net.blocos.values():
        if b.tipo in ("controlador",):
            continue
        for n, p in b.portas.items():
            if p.dominio != "controle" or p.sentido == "sai":
                continue
            if b.tipo in ("chave_sentido", "detector_sentido", "seletor_rank"):
                continue          # sentido e rank vêm dos detectores, verificados em R02 e R20
            if uf.find((b.id, n)) not in raizes_ok:
                rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}.{n}: não chega a nenhum controlador"))
    for cid in controladores:
        c = net.blocos[cid]
        for n, p in c.portas.items():
            if p.dominio != "controle":
                continue
            disp = {(lig.b if lig.a == (cid, n) else lig.a)[0] for lig in net.ligacoes_de((cid, n))}
            lim = p.atributos.get("max_dispositivos", MAX_DISPOSITIVOS_BARRAMENTO)
            if len(disp) > lim:
                rel.violacoes.append(Violacao(R, "erro", cid,
                                              f"{cid}.{n}: {len(disp)} dispositivos no barramento, limite {lim}"))


def _retangulos_pecas(net, contexto):
    if contexto and contexto.get("pecas"):
        return dict(contexto["pecas"])
    pts = defaultdict(list)
    for b in net.por_tipo("pino"):
        if b.posicao is not None:
            pts[b.id.split(":")[0]].append(b.posicao)
    out = {}
    for peca, ps in pts.items():
        xs, ys = [p[0] for p in ps], [p[1] for p in ps]
        out[peca] = (min(xs), min(ys), max(xs), max(ys))
    return out


def _sobrepoe(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _r08(net, rel, contexto):
    R = "R08-capacidade"
    chips = net.por_tipo("chip_tradutor")
    rets = {}
    for c in chips:
        vias = [f for f in net.filhos(c.id) if f.tipo in ("via_tx", "via_rx")]
        lim = c.atributos.get("vias_max")
        if lim is not None and len(vias) > lim:
            rel.violacoes.append(Violacao(R, "erro", c.id, f"{c.id}: {len(vias)} vias, cabem {lim}"))
        pos = c.posicao or c.atributos.get("posicao")
        w, d = c.atributos.get("largura_mm"), c.atributos.get("profundidade_mm")
        if pos is not None and w and d:
            rets[c.id] = (pos[0] - w / 2, pos[1] - d / 2, pos[0] + w / 2, pos[1] + d / 2)
    camada = {c.id: c.atributos.get("camada", "superficie") for c in chips}
    ids = sorted(rets)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if camada[a] == camada[b] and _sobrepoe(rets[a], rets[b]):
                rel.violacoes.append(Violacao(R, "erro", a, f"{a} sobrepõe {b}"))
    for peca, r in _retangulos_pecas(net, contexto).items():
        for c, rc in rets.items():
            if camada[c] == "superficie" and _sobrepoe(r, rc):
                rel.violacoes.append(Violacao(R, "erro", c, f"{c} sobrepõe a peça {peca}"))
    for a in net.por_tipo("acoplador"):
        if "fibra" not in a.portas:
            continue
        fibras = {(lig.b if lig.a == (a.id, "fibra") else lig.a)[0]
                  for lig in net.ligacoes_de((a.id, "fibra"))}
        fibras = {f for f in fibras if f in net.blocos and net.blocos[f].tipo == "fibra"}
        lim = a.atributos.get("max_fibras", 1)
        if len(fibras) > lim:
            rel.violacoes.append(Violacao(R, "erro", a.id, f"{a.id}: {len(fibras)} fibras, cabe {lim}"))


def _atraso_ps(net, cam, ps_mm):
    t = 0.0
    for bid in _blocos_do_caminho(cam):
        b = net.blocos.get(bid)
        if b is None:
            continue
        a = b.atributos
        if b.tipo == "trilha":
            t += a.get("comprimento_mm", 0.0) * ps_mm
        elif b.tipo == "fibra":
            t += a.get("comprimento_mm", 0.0) * PS_POR_MM_FIBRA
        t += a.get("atraso_ps", 0.0)
    for p, q in zip(cam, cam[1:]):
        if p[0] != q[0]:
            lig = net.ligacao_entre(p, q)
            if lig:
                t += lig.atributos.get("atraso_ps", 0.0)
    return t


def atraso_caminho_ps(net, caminho, protocolo):
    """Atraso pino a pino de um caminho (trilhas, fibras e blocos ativos)."""
    pr = PROTOCOLOS.get(protocolo)
    return _atraso_ps(net, caminho, pr.ps_por_mm_trilha if pr else PS_POR_MM_TRILHA)


def _r09(net, rel, contexto):
    R = "R09-tempo"
    ctx = contexto or {}
    limites = {**ATRASO_MAX_PS, **ctx.get("atraso_max_ps", {})}
    alcance_ui = ctx.get("alcance_treinamento_ui", ALCANCE_TREINO_UI)
    atrasos = {}
    pontes = _pontes(net)
    for s in net.sinais.values():
        pr = PROTOCOLOS.get(s.protocolo)
        ps_mm = pr.ps_por_mm_trilha if pr else PS_POR_MM_TRILHA
        da_ponte = _peca_do_ponto(s.origem) in pontes or _peca_do_ponto(s.destino) in pontes
        for sentido, cam in s.caminhos.items():
            t = _atraso_ps(net, cam, ps_mm)
            atrasos[(s.id, sentido)] = t
            lim = limites.get(s.protocolo)
            if lim is not None:
                # o chip que a base emula declara RL maior: cobre o seletor de rank
                lim += max((net.blocos[b].atributos.get("latencia_declarada_extra_ps", 0.0)
                            for b in _blocos_do_caminho(cam)
                            if b in net.blocos and net.blocos[b].tipo == "seletor_rank"), default=0.0)
            if da_ponte:
                lim = None        # a ponte controla os próprios canais: o orçamento dela é o CL (R20)
            if lim is not None and t > lim:
                rel.violacoes.append(Violacao(R, "erro", s.id,
                                              f"{s.id} ({sentido}): {t:.0f} ps > {lim:.0f} ps"))
        if len(s.sentidos) == 2 and pr is not None and pr.folga_inversao_ns > 0:
            custo = 0.0
            for bid in _blocos_do_caminho(s.caminhos.get("ida", [])):
                b = net.blocos.get(bid)
                if b and b.tipo == "chave_sentido":
                    custo = max(custo, b.atributos.get("comutacao_ps", 0.0))
                    for lig in net.ligacoes_de((bid, "sentido")):
                        det = net.blocos.get((lig.b if lig.a == (bid, "sentido") else lig.a)[0])
                        if det and det.tipo == "detector_sentido":
                            custo = max(custo, b.atributos.get("comutacao_ps", 0.0)
                                        + det.atributos.get("decisao_ps", 0.0))
            if custo > pr.folga_inversao_ns * 1000:
                rel.violacoes.append(Violacao(R, "erro", s.id,
                                              f"{s.id}: inverter o sentido custa {custo:.0f} ps, "
                                              f"folga {pr.folga_inversao_ns * 1000:.0f} ps"))
    grupos = defaultdict(list)
    for s in net.sinais.values():
        if s.grupo:
            for sentido in s.caminhos:
                if (s.id, sentido) in atrasos:
                    grupos[(s.grupo, s.protocolo, sentido)].append(atrasos[(s.id, sentido)])
    for (g, proto, sentido), ts in grupos.items():
        pr = PROTOCOLOS.get(proto)
        if pr is None or len(ts) < 2:
            continue
        desal = max(ts) - min(ts)
        lim = alcance_ui * pr.ui_ps
        if desal > lim:
            rel.violacoes.append(Violacao(R, "erro", g,
                                          f"grupo {g} ({sentido}): desalinhamento {desal:.0f} ps > "
                                          f"{lim:.0f} ps que o treino alcança"))
    for proto, deriva in ctx.get("deriva_ps", {}).items():
        pr = PROTOCOLOS.get(proto)
        if pr and deriva > pr.tolerancia_desalinhamento_ps:
            rel.violacoes.append(Violacao(R, "erro", proto,
                                          f"{proto}: deriva depois do treino {deriva:.1f} ps > "
                                          f"{pr.tolerancia_desalinhamento_ps:.1f} ps"))


def _pontes(net):
    return {b.atributos.get("peca") for b in net.por_tipo("controlador")
            if "DIMM-emulado" in b.atributos.get("capacidades", ())}


def _peca_do_ponto(pt):
    return pt[0].split(":", 1)[0]


def _e_relogio(padrao):
    p = PADROES.get(padrao)
    return p is not None and (p.codificacao == "relogio" or p.nome.endswith(RELOGIO_PAPEIS))


def _r10(net, rel, uf, redes):
    R = "R10-relogio"
    fontes = Counter()
    revezam = defaultdict(set)        # ponto -> muxes de posse no caminho de cada fonte

    def mux_no_caminho(s):
        return next((b for b in _blocos_do_caminho(s.caminhos.get("ida", ()))
                     if b in net.blocos and net.blocos[b].tipo == "mux_dono"), None)
    for s in net.sinais.values():
        origem = net.blocos.get(s.origem[0])
        if origem is not None and origem.tipo == "relogio":
            continue          # já contado pela rede elétrica do gerador
        pontos = (tuple(s.origem), tuple(s.destino)) if len(s.sentidos) == 2 else (tuple(s.destino),)
        mux = mux_no_caminho(s)
        for pt in pontos:
            if mux and pt == tuple(s.destino):
                if mux in revezam[pt]:
                    continue      # outro controlador pelo mesmo mux: um de cada vez
                revezam[pt].add(mux)
            fontes[pt] += 1
    relogio_na_rede = Counter()
    for b in net.por_tipo("relogio"):
        for n, p in b.portas.items():
            if p.dominio == "eletrico" and p.sentido == "sai":
                relogio_na_rede[uf.find((b.id, n))] += 1
    for b in net.por_tipo("pino"):
        for n, p in b.portas.items():
            if p.dominio != "eletrico" or p.sentido == "sai" or not _e_relogio(p.padrao):
                continue
            total = fontes[(b.id, n)] + relogio_na_rede[uf.find((b.id, n))]
            if total != 1:
                rel.violacoes.append(Violacao(R, "erro", b.id,
                                              f"{b.id}: entrada de relógio com {total} fontes"))
    grupos = defaultdict(dict)
    for s in net.sinais.values():
        if not s.grupo:
            continue
        for sentido, cam in s.caminhos.items():
            fib = frozenset(x for x in _blocos_do_caminho(cam)
                            if x in net.blocos and net.blocos[x].tipo == "fibra")
            grupos[(s.grupo, sentido)][s.id] = fib
    for (g, sentido), por_sinal in grupos.items():
        if len(set(por_sinal.values())) > 1:
            rel.violacoes.append(Violacao(R, "erro", g,
                                          f"grupo síncrono {g} ({sentido}) dividido em fibras diferentes"))


def _r11(net, rel):
    R = "R11-requisito"
    for q in net.requisitos:
        alvo = f"{q.peca}:{q.capacidade}"
        if q.capacidade in OPCIONAIS:
            continue
        if not q.provedor:
            rel.violacoes.append(Violacao(R, "erro", alvo, f"{q.peca} precisa de {q.capacidade}: ninguém oferece"))
            continue
        b = net.blocos.get(q.provedor)
        if b is None:
            rel.violacoes.append(Violacao(R, "erro", alvo,
                                          f"{q.peca} precisa de {q.capacidade}: provedor {q.provedor} não existe"))
        elif q.capacidade not in b.atributos.get("capacidades", ()):
            rel.violacoes.append(Violacao(R, "erro", alvo,
                                          f"{q.provedor} não oferece {q.capacidade} (pedido por {q.peca})"))
        elif b.tipo == "flash" and q.capacidade in REGIOES_FIRMWARE:
            falta = [r for r in REGIOES_FIRMWARE[q.capacidade] if r not in b.atributos.get("regioes", ())]
            if falta:
                rel.violacoes.append(Violacao(R, "erro", alvo,
                                              f"{q.provedor} não tem a região {', '.join(falta)} "
                                              f"para {q.capacidade} (pedido por {q.peca})"))


def _r18(net, rel):
    """Memória compartilhada (banco unificado da base, ou CXL nas pontas) é opcional: sem ela o
    sistema liga e usa ReBAR."""
    R = "R18-memoria-compartilhada"
    for q in net.requisitos:
        if q.capacidade not in OPCIONAIS:
            continue
        b = net.blocos.get(q.provedor) if q.provedor else None
        if b is None or q.capacidade not in b.atributos.get("capacidades", ()):
            rel.violacoes.append(Violacao(R, "aviso", f"{q.peca}:{q.capacidade}",
                                          f"{q.peca} sem {q.capacidade}: nem banco unificado na base nem CXL "
                                          f"nas pontas; a memória do outro lado só é vista por ReBAR sobre "
                                          f"PCIe, sem coerência"))


def _r12(net, rel):
    R = "R12-orfao"
    for b in net.blocos.values():
        if b.tipo not in TIPOS:
            rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}: tipo desconhecido {b.tipo}"))
            continue
        for n in OBRIGATORIAS.get(b.tipo, ()):
            if n not in b.portas:
                rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}: falta a porta {n}"))
            elif not net.ligacoes_de((b.id, n)):
                rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}.{n}: porta sem ligação"))
        if b.tipo == "laser" and not any(n.startswith("out") and net.ligacoes_de((b.id, n)) for n in b.portas):
            rel.violacoes.append(Violacao(R, "erro", b.id, f"{b.id}: laser sem saída ligada"))
        if b.portas and not any(net.ligacoes_de((b.id, n)) for n in b.portas):
            rel.violacoes.append(Violacao(R, "aviso", b.id, f"{b.id}: bloco sem nenhuma ligação"))


# --------------------------------------------------------------------- entrada
# ------------------------------------------------------------- temperatura
_ANEL = {}


def _anel_e_termico():
    if not _ANEL:
        from modulos.optica import enlace as E
        cfg = E.carregar("viavel")
        _ANEL["anel"], _ANEL["termico"] = E._anel(cfg), cfg["termico"]
    return _ANEL["anel"], _ANEL["termico"]


def aquecedores(netlist, contexto=None):
    """Por chip tradutor: quanto o aquecedor do anel precisa sintonizar contra o que ele dá.

    O aquecedor só desloca a ressonância para o vermelho. Com o desvio de projeto ideal, o
    anel mais vermelho fica no alvo com o aquecedor desligado no calor máximo, e o mais azul
    precisa de deriva térmica + 2 x (3 sigma de fabricação) a frio. Se a faixa passar de um
    FSR, qualquer ordem de ressonância serve e sempre cobre.
    """
    from modulos.componentes import limites as L
    ctx = contexto or {}
    temps, t_min = ctx.get("temperaturas", {}), ctx.get("t_min_c")
    if t_min is None:
        return {}
    anel, tc = _anel_e_termico()
    sigma = tc["variacao_fabricacao_nm"] * L.SIGMAS_FABRICACAO
    pmax, desvio = tc["aquecedor_max_mw"], abs(tc["desvio_frio_nm"])
    eff = anel.aquecedor_nm_mw
    faixa = pmax * eff * L.AQUECEDOR_FAIXA_UTIL
    out = {}
    for c in netlist.por_tipo("chip_tradutor"):
        if c.id not in temps:
            continue
        dt = max(temps[c.id] - t_min, 0.0)
        deriva = anel.dlambda_dT_nm * dt
        pede = deriva + 2 * sigma
        aneis = sum(1 for f in netlist.filhos(c.id) if f.tipo in ("via_tx", "via_rx"))
        frio_mw = min((deriva + sigma) / eff, pmax)          # anel médio, desvio de projeto ideal
        out[c.id] = {"temperatura_c": temps[c.id], "delta_k": dt, "deriva_nm": deriva,
                     "pede_nm": pede, "faixa_nm": faixa, "fsr_nm": anel.fsr_nm,
                     "cobre": pede <= faixa or faixa >= anel.fsr_nm,
                     "desvio_necessario_nm": deriva + sigma, "desvio_atual_nm": desvio,
                     "desvio_atual_ok": deriva + sigma <= desvio and (desvio + sigma) <= faixa,
                     "aneis": aneis, "aquecedor_frio_mw_anel": frio_mw,
                     "aquecedor_frio_w": aneis * frio_mw * 1e-3}
    return out


def _r13(net, rel, contexto):
    R = "R13-temperatura"
    from modulos.componentes import limites as L
    ctx = contexto or {}
    temps = ctx.get("temperaturas")
    if not temps:
        return
    tipos = ctx.get("tipos_pecas", {})
    celulas = defaultdict(list)
    for k, t in temps.items():
        b = net.blocos.get(k)
        if b is None:
            if k not in tipos:
                continue
            lim, nome = L.limite_peca(tipos[k]), f"peça {k} ({tipos[k]})"
        elif b.tipo == "celula":
            lim = L.limite_celula(b.atributos.get("chave"))
            if t > lim:
                celulas[(b.atributos.get("peca", "?"), b.atributos.get("chave"), lim)].append(t)
            continue
        elif b.tipo == "chip_tradutor":
            lim, nome = L.CHIP_TRADUTOR_C, f"chip {k}"
        elif b.tipo == "laser":
            lim, nome = L.limite_laser(b.atributos.get("tec", True)), f"laser {k}"
        elif b.tipo == "regulador":
            lim, nome = L.REGULADOR_C, f"regulador {k}"
        else:
            continue
        if t > lim:
            rel.violacoes.append(Violacao(R, "erro", k, f"{nome}: {t:.1f} °C > {lim:.0f} °C"))
    for (peca, chave, lim), ts in sorted(celulas.items()):
        rel.violacoes.append(Violacao(R, "erro", f"cel:{peca}",
                                      f"{len(ts)} células sob {peca} acima de {lim:.0f} °C da chave "
                                      f"{chave} (máx. {max(ts):.1f} °C)"))
    tb = ctx.get("t_base_max_c")
    if tb is not None and tb > L.LCP_BASE_C:
        rel.violacoes.append(Violacao(R, "erro", "base", f"base a {tb:.1f} °C > {L.LCP_BASE_C:.0f} °C do LCP"))
    for cid, a in aquecedores(net, ctx).items():
        if not a["cobre"]:
            rel.violacoes.append(Violacao(R, "erro", cid,
                                          f"{cid}: aquecedor cobre {a['faixa_nm']:.2f} nm, o local pede "
                                          f"{a['pede_nm']:.2f} nm ({a['delta_k']:.0f} K de variação)"))
        elif not a["desvio_atual_ok"]:
            rel.violacoes.append(Violacao(R, "aviso", cid,
                                          f"{cid}: desvio a frio de projeto {a['desvio_atual_nm']:.2f} nm; "
                                          f"precisa de {a['desvio_necessario_nm']:.2f} nm"))


# ------------------------------------------------------------- consumo
# referência: ligação elétrica inteira (PHY dos dois lados + canal), pJ/bit típicos
REFERENCIA_PJ_BIT = {"DDR5-4800": 15.0, "GDDR7-32": 6.0, "PCIe5": 5.0, "PCIe4": 5.0}
REFERENCIA_PADRAO_PJ_BIT = 10.0
TIPOS_INTERCONEXAO = {"chip_tradutor", "via_tx", "via_rx", "detector_sentido", "chave_sentido",
                      "laser", "conversor_nivel"}
AQUECEDOR_NOMINAL_MW = 3.0        # se o construtor não disser outro


def consumo(netlist, contexto=None):
    """Potência da interconexão (o que vem além das E/S nativas das peças) e pJ/bit."""
    from modulos.componentes import limites as L
    from modulos.dados.protocolos import PAPEIS_DADOS
    try:
        from modulos.conexoes import construir as K
        nominal_mw = float(getattr(K, "AQUECEDOR_MW", AQUECEDOR_NOMINAL_MW))
    except Exception:
        nominal_mw = AQUECEDOR_NOMINAL_MW
    partes = Counter()
    aneis = 0
    for b in netlist.blocos.values():
        a = b.atributos
        p = float(a.get("potencia_eletrica_w", a.get("potencia_w", 0.0)) or 0.0)
        if b.tipo in TIPOS_INTERCONEXAO:
            partes["lasers" if b.tipo == "laser" else "tradutores"] += p
            if b.tipo in ("via_tx", "via_rx"):
                aneis += 1
        elif b.tipo == "controlador" and b.id.startswith("ctl:cel"):
            partes["controle das células"] += p
    # o chip já soma o aquecedor nominal de cada anel; troca pelo pior caso
    nominal_w = aneis * nominal_mw * 1e-3
    aq = aquecedores(netlist, contexto)
    if aq:
        medidos = sum(x["aneis"] for x in aq.values())
        pior_w = sum(x["aquecedor_frio_w"] for x in aq.values()) + (aneis - medidos) * nominal_mw * 1e-3
    else:
        _, tc = _anel_e_termico()
        pior_w = aneis * tc["aquecedor_max_mw"] * L.AQUECEDOR_FAIXA_UTIL * 1e-3
    partes["tradutores"] -= nominal_w
    partes["aquecedores (pior caso)"] = pior_w
    banda = Counter()
    pontes = _pontes(netlist)
    for s in netlist.sinais.values():
        pad = PADROES.get(s.padrao)
        if not (pad and pad.alta_velocidade and s.papel in PAPEIS_DADOS):
            continue
        # banco unificado: o segundo chip do grupo divide a luz do primeiro, e o que a ponte leva
        # aos chips é o mesmo dado do canal DDR5 da CPU; conta uma vez só
        if re.search(r"_R[1-9]\d*$", s.grupo or "") or (
                s.protocolo == "GDDR7-32" and {_peca_do_ponto(s.origem), _peca_do_ponto(s.destino)} & pontes):
            continue
        banda[s.protocolo] += pad.taxa_gbps
    total_w = sum(partes.values())
    gbps = sum(banda.values())
    ref = (sum(g * REFERENCIA_PJ_BIT.get(p, REFERENCIA_PADRAO_PJ_BIT) for p, g in banda.items()) / gbps
           if gbps else 0.0)
    return {"partes_w": {k: round(v, 3) for k, v in partes.items()}, "total_w": total_w,
            "banda_gbps": dict(banda), "banda_total_gbps": gbps,
            "pj_bit": total_w / gbps * 1e3 if gbps else 0.0, "referencia_pj_bit": ref,
            "aneis": aneis}


def _r14(net, rel, contexto):
    R = "R14-consumo"
    c = consumo(net, contexto)
    if not c["banda_total_gbps"]:
        return
    meta = (contexto or {}).get("meta_pj_bit")
    texto = (f"interconexão gasta {c['total_w']:.1f} W, {c['pj_bit']:.1f} pJ/bit além das E/S "
             f"nativas; uma ligação elétrica inteira custa ~{c['referencia_pj_bit']:.1f} pJ/bit")
    if meta is not None and c["pj_bit"] > meta:
        rel.violacoes.append(Violacao(R, "erro", "interconexao", f"{texto}; meta {meta:.1f} pJ/bit"))
    elif c["pj_bit"] > c["referencia_pj_bit"]:
        rel.violacoes.append(Violacao(R, "aviso", "interconexao", texto))


# ------------------------------------------------------------- protocolos
def _chaves_do_detector(net, det):
    out = []
    for lig in net.ligacoes_de((det.id, "sentido")):
        outro = lig.b if lig.a == (det.id, "sentido") else lig.a
        b = net.blocos.get(outro[0])
        if b is not None and b.tipo == "chave_sentido":
            out.append(b)
    return out


def _detector_da_chave(net, ch):
    for lig in net.ligacoes_de((ch.id, "sentido")):
        outro = lig.b if lig.a == (ch.id, "sentido") else lig.a
        b = net.blocos.get(outro[0])
        if b is not None and b.tipo == "detector_sentido":
            return b
    return None


def _le_registrador(det):
    return det is not None and any(x.startswith(("MRW", "MRS")) for x in det.atributos.get("decodifica", ()))


def _r15(net, rel):
    """O detector decodifica o que muda sentido e nível, a tempo do primeiro dado."""
    R = "R15-decodificacao"
    from modulos.dados import comandos as K
    for det in net.por_tipo("detector_sentido"):
        a = det.atributos
        chaves = _chaves_do_detector(net, det)
        protos = sorted({c.atributos.get("protocolo") for c in chaves} - {None}) or a.get("protocolos", [])
        dec = set(a.get("decodifica", ()))
        for p in protos:
            if p not in K.TABELA:
                continue
            falta = [x for x in K.necessarios(p) if x not in dec]
            if falta:
                rel.violacoes.append(Violacao(R, "erro", det.id,
                                              f"{det.id}: não decodifica {falta} de {p}; sem isso o "
                                              "sentido ou a terminação não acompanham o comando"))
            lat = a.get("latencia_decodificacao_ps")
            comut = max((c.atributos.get("comutacao_ps", 0.0) for c in chaves), default=0.0)
            if lat is None:
                rel.violacoes.append(Violacao(R, "erro", det.id, f"{det.id}: latência de decodificação não declarada"))
            elif lat + comut > K.janela_ps(p):
                rel.violacoes.append(Violacao(R, "erro", det.id,
                                              f"{det.id}: decodificar ({lat:.0f} ps) + comutar ({comut:.0f} ps) "
                                              f"passa da janela de {K.janela_ps(p):.0f} ps antes do primeiro dado"))
        if a.get("dados_decodificados"):
            rel.violacoes.append(Violacao(R, "aviso", det.id,
                                          f"{det.id} decodifica os dados; o conceito pede cópia sem decodificar"))


def _r16(net, rel):
    """Terminação e força que a peça programa: o tradutor cobre a faixa e acompanha o MRW."""
    R = "R16-ajuste"
    from modulos.dados import ddr5 as D
    for ch in net.por_tipo("chave_sentido"):
        a = ch.atributos
        prot = a.get("protocolo")
        if prot not in D.PERMITIDOS:
            continue
        perm = D.PERMITIDOS[prot]
        term, forca = a.get("terminacao_ajustavel"), a.get("forca_ajustavel")
        ft = [v for v in perm["terminacao"] if term is None or v not in term]
        ff = [v for v in perm["forca"] if forca is None or v not in forca]
        if ft or ff:
            rel.violacoes.append(Violacao(R, "erro", ch.id,
                                          f"{ch.id}: faixa não cobre o que {prot} programa "
                                          f"(terminação {ft or 'ok'}, força {ff or 'ok'})"))
        if a.get("papel_eletrico") == "parece_memoria":
            falta = [c for c in D.espelho(prot) if c not in a.get("espelha", ())]
            if falta:
                rel.violacoes.append(Violacao(R, "erro", ch.id, f"{ch.id}: não espelha {falta}"))
            if not _le_registrador(_detector_da_chave(net, ch)):
                rel.violacoes.append(Violacao(R, "erro", ch.id,
                                              f"{ch.id}: o detector não lê MRW; a terminação vista pela "
                                              "peça não segue o que ela programou"))
    for s in net.sinais.values():
        if s.protocolo not in D.PERMITIDOS or s.papel not in ("CA", "CS", "CK") or len(s.sentidos) != 1:
            continue
        via = next((net.blocos[b] for b, _ in s.caminhos.get("ida", ())
                    if b in net.blocos and net.blocos[b].tipo == "via_tx"), None)
        if via is None:
            continue
        det = net.blocos.get(via.atributos.get("ajuste_por"))
        if det is None or not _le_registrador(det):
            rel.violacoes.append(Violacao(R, "erro", via.id,
                                          f"{via.id}: o ODT de {s.papel} que a peça programa não é espelhado ({s.id})"))
        elif not set(D.PERMITIDOS[s.protocolo]["terminacao"]) <= set(via.atributos.get("terminacao_ajustavel", ())):
            rel.violacoes.append(Violacao(R, "erro", via.id, f"{via.id}: faixa de terminação de {s.papel} curta"))


def _r17(net, rel, contexto):
    """PCIe: detecção de receptor controlada, ocioso elétrico a tempo, olho aberto."""
    R = "R17-pcie"
    from modulos.dados import pcie as P
    vistos = set()
    for s, v in P.vias_pcie(net):
        if v.id in vistos:
            continue
        vistos.add(v.id)
        a = v.atributos
        if v.tipo == "via_tx" and a.get("deteccao_receptor") != "controlada":
            rel.violacoes.append(Violacao(R, "erro", v.id,
                                          f"{v.id}: detecção de receptor '{a.get('deteccao_receptor')}'; a terminação "
                                          "só pode aparecer quando o par existe e a luz travou"))
        if v.tipo == "via_rx":
            sq = a.get("squelch_ps")
            if sq is None or sq > P.LIMITE_SQUELCH_PS:
                rel.violacoes.append(Violacao(R, "erro", v.id,
                                              f"{v.id}: ocioso elétrico atravessa em {sq} ps; limite "
                                              f"{P.LIMITE_SQUELCH_PS:.0f} ps"))
    for prot in ("PCIe5", "PCIe4"):
        res = (contexto or {}).get("pcie", {}).get(prot) or P.avaliar_netlist(net, prot, comparar_linear=False)
        if res and not res["olho"]["aberto"]:
            o = res["olho"]
            rel.violacoes.append(Violacao(R, "erro", prot,
                                          f"{prot}: nenhum preset abre o olho (altura {o['altura_rel']:.2f}, "
                                          f"largura {o['largura_ui']:.2f} UI)"))


# ------------------------------------------------------------- banco unificado
def _pontas_gddr7(net):
    """Por sinal GDDR7: (ponto do lado do chip de memória, peça controladora)."""
    sinais = [s for s in net.sinais.values() if s.protocolo == "GDDR7-32"]
    controladores = {_peca_do_ponto(s.origem) for s in sinais if s.papel == "CA"}
    out = []
    for s in sinais:
        a, b = _peca_do_ponto(s.origem), _peca_do_ponto(s.destino)
        if a in controladores and b not in controladores:
            out.append((s, tuple(s.destino), a))
        elif b in controladores and a not in controladores:
            out.append((s, tuple(s.origem), b))
    return out


def _r19(net, rel):
    """Um chip que ouve mais de um controlador passa por um mux de posse comandado pelo FPGA,
    e cada chip do banco é alcançado pela GPU e pela ponte."""
    R = "R19-posse"
    muxes = net.por_tipo("mux_dono")
    if not muxes:
        return
    ctls, mux_do = defaultdict(set), defaultdict(set)
    for s, pt, ctl in _pontas_gddr7(net):
        ctls[pt].add(ctl)
        for bid in _blocos_do_caminho(next(iter(s.caminhos.values()))):
            if bid in net.blocos and net.blocos[bid].tipo == "mux_dono":
                mux_do[pt].add(bid)
    for pt, cs in sorted(ctls.items()):
        if len(cs) > 1 and len(mux_do[pt]) != 1:
            rel.violacoes.append(Violacao(R, "erro", pt[0],
                                          f"{pt[0]} ouve {len(cs)} controladores ({', '.join(sorted(cs))}) "
                                          f"sem um mux de posse só ({len(mux_do[pt])})"))
    for m in muxes:
        lados = m.atributos.get("controladores", [])
        if len(set(lados)) != len(lados) or len([n for n in m.portas if n.startswith("r")]) != len(lados):
            rel.violacoes.append(Violacao(R, "erro", m.id, f"{m.id}: entradas {lados} não batem com as portas"))
        dono = [lig for lig in net.ligacoes_de((m.id, "sel"))
                if (lig.a if lig.b == (m.id, "sel") else lig.b)[0] == m.pai]
        if not dono:
            rel.violacoes.append(Violacao(R, "erro", m.id, f"{m.id}: a posse não chega pelo controle do tradutor"))
    pontes = _pontes(net)
    por_chip = defaultdict(set)
    for pt, cs in ctls.items():
        por_chip[_peca_do_ponto(pt)] |= cs
    for chip, cs in sorted(por_chip.items()):
        if not (cs & pontes) or cs <= pontes:
            rel.violacoes.append(Violacao(R, "erro", chip,
                                          f"{chip} fora do banco: só {', '.join(sorted(cs))} chega a ele"))


def _r20(net, rel):
    """Banco unificado: o que a GPU endereça, o CL que a ponte declara, o seletor e o alinhamento."""
    R = "R20-banco"
    from modulos.dados import memoria_unificada as MU
    for c in net.por_tipo("controlador"):
        a = c.atributos
        if "DIMM-emulado" not in a.get("capacidades", ()):
            continue
        visto = a["ranks"] * a["chip_real_gb"]
        if visto > a["densidade_max_gb"]:
            rel.violacoes.append(Violacao(R, "erro", c.id,
                                          f"{c.id}: a GPU veria chips de {visto * 8:.0f} Gb; o maior que ela "
                                          f"endereça é {a['densidade_max_gb'] * 8:.0f} Gb"))
        if a["chips"] != a["canais"] * a["ranks"]:
            rel.violacoes.append(Violacao(R, "erro", c.id,
                                          f"{c.id}: {a['chips']} chips não fecham {a['canais']} canais "
                                          f"x {a['ranks']} ranks"))
        ida = volta = 0.0
        for s in net.sinais.values():
            if s.protocolo != "GDDR7-32" or _peca_do_ponto(s.origem) != a["peca"]:
                continue
            if s.papel in ("CA", "CK", "WCK"):
                ida = max(ida, atraso_caminho_ps(net, s.caminhos["ida"], s.protocolo))
            if "volta" in s.caminhos:
                volta = max(volta, atraso_caminho_ps(net, s.caminhos["volta"], s.protocolo))
        lat = MU.latencia_ponte(ida / 1000, volta / 1000)
        if not lat["cabe"]:
            rel.violacoes.append(Violacao(R, "erro", c.id,
                                          f"{c.id}: a leitura pela ponte leva {lat['leitura_ns']:.1f} ns = "
                                          f"CL{lat['cl']}; o DDR5 aceita até CL{lat['cl_max']}"))
        elif a.get("cl_declarado", 0) < lat["cl"]:
            rel.violacoes.append(Violacao(R, "erro", c.id,
                                          f"{c.id}: o SPD declara CL{a.get('cl_declarado')} e a ponte "
                                          f"precisa de CL{lat['cl']}"))
    for sel in net.por_tipo("seletor_rank"):
        a = sel.atributos
        portas = [n for n in sel.portas if n.startswith("r")]
        soltas = [n for n in portas if not net.ligacoes_de((sel.id, n))]
        if len(portas) != a.get("ranks", 1) or soltas:
            rel.violacoes.append(Violacao(R, "erro", sel.id,
                                          f"{sel.id}: {len(portas) - len(soltas)} chips de {a.get('ranks')}"))
        det = None
        for lig in net.ligacoes_de((sel.id, "sel")):
            b = net.blocos.get((lig.a if lig.b == (sel.id, "sel") else lig.b)[0])
            if b is not None and b.tipo == "detector_rank":
                det = b
        if det is None:
            rel.violacoes.append(Violacao(R, "erro", sel.id, f"{sel.id}: nenhum detector escolhe o chip"))
        else:
            falta = {"ACT:linha_alta", "banco"} - set(det.atributos.get("decodifica", ()))
            if falta:
                rel.violacoes.append(Violacao(R, "erro", det.id, f"{det.id}: não decodifica {sorted(falta)}"))
            if not any(n.startswith("ca") and net.ligacoes_de((det.id, n)) for n in det.portas):
                rel.violacoes.append(Violacao(R, "erro", det.id, f"{det.id}: não lê o comando"))
            if a.get("papel") == "CA" and det.atributos.get("latencia_ps", 0.0) > a.get("atraso_ps", 0.0):
                rel.violacoes.append(Violacao(R, "erro", sel.id,
                                              f"{sel.id}: o comando sai em {a['atraso_ps']:.0f} ps e o chip só é "
                                              f"escolhido em {det.atributos['latencia_ps']:.0f} ps"))
        if a.get("faixa_usada_ps", 0.0) > a.get("faixa_alinhamento_ps", float("inf")):
            rel.violacoes.append(Violacao(R, "erro", sel.id,
                                          f"{sel.id}: igualar os chips pede {a['faixa_usada_ps']:.0f} ps de "
                                          f"atraso; a linha dá {a['faixa_alinhamento_ps']:.0f} ps"))
    # medido: do mesmo pino do controlador, todos os chips do grupo chegam juntos
    tempos = defaultdict(list)
    for s, pt, ctl in _pontas_gddr7(net):
        ponta_ctl = tuple(s.origem) if _peca_do_ponto(s.origem) == ctl else tuple(s.destino)
        for sentido, cam in s.caminhos.items():
            if any(b in net.blocos and net.blocos[b].tipo == "seletor_rank" for b in _blocos_do_caminho(cam)):
                tempos[(ponta_ctl, sentido)].append(atraso_caminho_ps(net, cam, s.protocolo))
    for (pt, sentido), ts in tempos.items():
        if len(ts) > 1 and max(ts) - min(ts) > MU.TOLERANCIA_DESALINHAMENTO_PS:
            rel.violacoes.append(Violacao(R, "erro", pt[0],
                                          f"{pt[0]} ({sentido}): os chips do grupo chegam com "
                                          f"{max(ts) - min(ts):.1f} ps de diferença; tolerância "
                                          f"{MU.TOLERANCIA_DESALINHAMENTO_PS:.1f} ps"))


def verificar(netlist, contexto=None):
    """Roda as regras e devolve um Relatorio."""
    rel = Relatorio()
    uf, redes = _redes_eletricas(netlist)
    _r01(netlist, rel)
    _r02(netlist, rel, redes)
    _r03(netlist, rel)
    _r04(netlist, rel, contexto)
    _r05(netlist, rel, contexto)
    _r06(netlist, rel)
    _r06_contatos(rel, contexto)
    _r07(netlist, rel)
    _r08(netlist, rel, contexto)
    _r09(netlist, rel, contexto)
    _r10(netlist, rel, uf, redes)
    _r11(netlist, rel)
    _r12(netlist, rel)
    _r13(netlist, rel, contexto)
    _r14(netlist, rel, contexto)
    _r15(netlist, rel)
    _r16(netlist, rel)
    _r17(netlist, rel, contexto)
    _r18(netlist, rel)
    _r19(netlist, rel)
    _r20(netlist, rel)
    return rel
