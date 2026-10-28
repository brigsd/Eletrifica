"""Boot da base como máquina de estados por eventos, em cima da netlist do sistema.

Nada aqui conhece ids fixos: quem alimenta quem, quem controla quem e de onde
vem a luz de cada tradutor saem da topologia da netlist (ligações por domínio).
Cada transição tem uma guarda; guarda que falha para o boot com o motivo e o
bloco culpado.

    from modulos.sistema.boot import emular
    ex = emular(netlist, sim={"aneis_travamento_us": 200.0}, falhas=("laser:0",))

Falhas injetáveis: id de bloco (fica morto), "lig:A|B" (corta as ligações
entre os blocos A e B), "req:PECA:CAPACIDADE" (requisito fica sem provedor),
"regiao:BLOCO:NOME" (a região da flash fica apagada), "sondagem" (a sondagem
não termina).

Com chipset (o provedor do DMI declara plataforma PCH), a sequência é a da
Intel: standby da base e do PCH, RSMRST#, o ME lido da flash, SLP_S3#, trilhos
principais, PWROK, PROCPWRGD, SVID, PLTRST# e a BIOS lida pela DMI.
"""
from dataclasses import dataclass, field

from modulos.dados import comandos as CMD
from modulos.dados import ddr5 as DDR5
from modulos.dados import memoria_unificada as MU
from modulos.dados import pcie as PC
from modulos.conexoes.verificador import REGIOES_FIRMWARE

# tempos típicos (µs); `sim` sobrescreve os que foram medidos
PADRAO = {
    "tempo_sonda_por_celula_us": 2.0,
    "sondagem_us": None,               # None = células x tempo por célula
    "identificacao_us": 2_000.0,
    "configuracao_celulas_us": 1_000.0,
    "fonte_us": 100_000.0,             # PS_ON -> PWR_OK de uma fonte ATX
    "partida_suave_us": 1_000.0,       # por regulador
    "firmware_us": 50_000.0,           # FPGA lê e confere o firmware (sem chipset)
    "rsmrst_us": 100.0,
    "me_us": 30_000.0,                 # ME lê descritor e região ME e libera o boot
    "slp_s3_us": 100.0,
    "procpwrgd_us": 100.0,             # SYS_PWROK -> PROCPWRGD no PCH
    "bios_dmi_us": 20_000.0,           # vetor de reset e SEC/PEI pela DMI até a SPI
    "config_chip_us": 200.0,           # chip tradutor pelo barramento de controle
    "laser_us": 500.0,
    "aneis_travamento_us": 200.0,      # modulos.optica.controle_termico
    "refclk_us": 1_000.0,
    "pwrok_us": 100.0,
    "svid_latencia_us": 50.0,
    "vid_boot_v": 1.10,
    "slew_mv_us": 10.0,                # modulos.energia.vrm
    "vrm_assentamento_us": 9.8,        # modulos.energia.vrm
    "pltrst_us": 1_000.0,
    "treino_memoria_us": 200_000.0,
    "treino_pcie_us": 100_000.0,
    "treino_gddr7_us": 50_000.0,
    "sondas_banco_us": 100.0,          # kernel de calibração da GPU e sondas da CPU
    "calibracao_banco_us": None,       # None = varredura do banco pela ponte
}

PASSIVOS_OPTICOS = {"fibra", "divisor", "acoplador", "mux", "demux"}
PASSIVOS_ELETRICOS = {"trilha", "celula", "conversor_nivel", "terminacao"}
TIPO_ENLACE = {"DDR5-4800": "DDR5", "PCIe5": "PCIe", "GDDR7-32": "GDDR7",
               "PCIe4": "AUX", "AUX": "AUX"}


@dataclass
class Execucao:
    eventos: list = field(default_factory=list)     # (t_us, alvo, estado, detalhe)
    etapas: list = field(default_factory=list)
    ok: bool = False
    parou_em: dict = None                           # {"etapa", "motivo", "bloco"}
    tempos: dict = field(default_factory=dict)      # etapa -> t_us

    def evento(self, t, alvo, estado, detalhe=""):
        self.eventos.append((float(t), alvo, estado, detalhe))


class _Parou(Exception):
    def __init__(self, etapa, motivo, bloco=None):
        super().__init__(motivo)
        self.etapa, self.motivo, self.bloco = etapa, motivo, bloco


class _Uniao:
    def __init__(self):
        self.pai = {}

    def achar(self, a):
        self.pai.setdefault(a, a)
        while self.pai[a] != a:
            self.pai[a] = self.pai[self.pai[a]]
            a = self.pai[a]
        return a

    def unir(self, a, b):
        ra, rb = self.achar(a), self.achar(b)
        if ra != rb:
            self.pai[ra] = rb


class _Topologia:
    """Leitura da netlist por domínio, já com as falhas aplicadas."""

    def __init__(self, nl, falhas):
        self.nl = nl
        self.falhas = set(falhas)
        self.cortes = {tuple(sorted(f[4:].split("|", 1))) for f in self.falhas if f.startswith("lig:")}
        self.ligacoes = [l for l in nl.ligacoes
                         if tuple(sorted((l.a[0], l.b[0]))) not in self.cortes]
        self.apagadas = {tuple(f[7:].rsplit(":", 1)) for f in self.falhas if f.startswith("regiao:")}
        self.uniao = {d: self._unir(d) for d in ("energia", "controle", "optico", "eletrico")}

    def dominio(self, ponto):
        b = self.nl.blocos.get(ponto[0])
        p = b.portas.get(ponto[1]) if b else None
        return p.dominio if p else None

    def _unir(self, dominio):
        u = _Uniao()
        for l in self.ligacoes:
            if self.dominio(l.a) == dominio and self.dominio(l.b) == dominio:
                u.unir(l.a, l.b)
        passivos = {"optico": PASSIVOS_OPTICOS, "eletrico": PASSIVOS_ELETRICOS}.get(dominio, ())
        for b in self.nl.blocos.values():
            if b.tipo in passivos:
                pts = [(b.id, n) for n, p in b.portas.items() if p.dominio == dominio]
                for p in pts[1:]:
                    u.unir(pts[0], p)
        return u

    def rede(self, dominio, ponto):
        return self.uniao[dominio].achar(tuple(ponto))

    def portas(self, bloco, dominio, sentidos=("entra", "sai", "bidir")):
        b = self.nl.blocos[bloco]
        return [(bloco, n) for n, p in b.portas.items()
                if p.dominio == dominio and p.sentido in sentidos]

    def portas_com_filhos(self, bloco, dominio, sentidos):
        out = self.portas(bloco, dominio, sentidos)
        for f in self.nl.filhos(bloco):
            out += self.portas(f.id, dominio, sentidos)
        return out

    def vivo(self, bloco):
        return bloco in self.nl.blocos and bloco not in self.falhas

    def regioes(self, bloco):
        return {r for r in self.nl.blocos[bloco].atributos.get("regioes", ())
                if (bloco, r) not in self.apagadas}

    def salto_cortado(self, caminho):
        for p, q in zip(caminho, caminho[1:]):
            if p[0] != q[0] and tuple(sorted((p[0], q[0]))) in self.cortes:
                return p, q
        return None


def _peca_do_pino(b):
    return b.atributos.get("peca") or b.id.split(":", 1)[0]


def _ms(t_us):
    if t_us < 1_000:
        return f"{t_us:.0f} µs"
    return f"{t_us / 1000:.1f} ms".replace(".", ",")


def _ltssm(nl, blocos, sinais, pecas, t_trava):
    """Estado do tradutor que cada transmissor PCIe enxerga, e o LTSSM em cima dele."""
    vias = PC.vias_pcie(nl, "PCIe5")
    por_peca = {}
    for s, v in vias:
        chip = blocos.get(v.pai)
        if chip is None:
            continue
        por_peca.setdefault(chip.atributos.get("peca"), []).append(v)
    squelch = max((v.atributos.get("squelch_ps", float("inf")) for _, v in vias if v.tipo == "via_rx"),
                  default=0.0)
    pontas = sorted(p for p in por_peca if any(v.tipo == "via_tx" for v in por_peca[p]))
    lados, culpado = [], None
    for peca in pontas[:2]:
        tx = [v for v in por_peca.get(peca, []) if v.tipo == "via_tx"]
        politicas = {v.atributos.get("deteccao_receptor") for v in tx}
        politica = politicas.pop() if len(politicas) == 1 else None
        if politica != "controlada" and culpado is None and tx:
            culpado = tx[0].id
        outra = [p for p in pontas if p != peca]
        lados.append(PC.LadoTradutor(politica, all(o in pecas for o in outra),
                                     all(v.pai in t_trava for v in tx), squelch))
    olho = PC.avaliar_netlist(nl, "PCIe5", comparar_linear=False)["olho"]
    r = PC.ltssm(lados[0], lados[1] if len(lados) > 1 else lados[0], olho)
    return {"ltssm": r, "olho": olho, "bloco": culpado or (pontas[0] if pontas else "PCIe")}


def emular(netlist, sim=None, falhas=()):
    cfg = dict(PADRAO)
    cfg.update({k: v for k, v in (sim or {}).items() if v is not None})
    ex = Execucao()
    try:
        _executar(netlist, cfg, _Topologia(netlist, falhas), ex)
        ex.ok = True
    except _Parou as p:
        ex.parou_em = {"etapa": p.etapa, "motivo": p.motivo, "bloco": p.bloco}
        t = ex.eventos[-1][0] if ex.eventos else 0.0
        ex.evento(t, p.bloco or p.etapa, "parou", p.motivo)
        anterior = ex.etapas[-1] if ex.etapas else {}
        ex.etapas.append({"nome": f"Parou: {p.etapa}", "t": _ms(t), "camada": "funcoes",
                          "descricao": p.motivo,
                          "energizadas": anterior.get("energizadas", []),
                          "enlaces_ativos": anterior.get("enlaces_ativos", [])})
    ex.eventos.sort(key=lambda e: e[0])
    return ex


def _executar(nl, cfg, top, ex):
    blocos = nl.blocos
    tipo = lambda t: [b.id for b in nl.por_tipo(t)]
    pinos = nl.por_tipo("pino")
    pecas = sorted({_peca_do_pino(b) for b in pinos})

    def etapa(nome, t, camada, descricao, energizadas=(), enlaces=(), transparente=False):
        ex.tempos[nome] = t
        e = {"nome": nome, "t": _ms(t), "camada": camada, "descricao": descricao,
             "energizadas": sorted(energizadas), "enlaces_ativos": sorted(enlaces)}
        if transparente:
            e["transparente"] = True
        ex.etapas.append(e)

    # ---- requisitos ------------------------------------------------------------
    def requisitos(peca=None, cap=None):
        return [r for r in nl.requisitos
                if (peca is None or r.peca == peca) and (cap is None or r.capacidade == cap)]

    def req_ok(r):
        if f"req:{r.peca}:{r.capacidade}" in top.falhas or r.provedor is None:
            return False, f"{r.peca} precisa de {r.capacidade} e ninguém provê"
        if not top.vivo(r.provedor):
            return False, f"o provedor de {r.capacidade} ({r.provedor}) não responde"
        return True, ""

    def exigir(etapa_, cap, pecas_=None, obrigatorio=True):
        alvos = pecas_ if pecas_ is not None else sorted({r.peca for r in requisitos(cap=cap)})
        for peca in alvos:
            rs = requisitos(peca, cap)
            if not rs:
                if obrigatorio:
                    raise _Parou(etapa_, f"{peca} precisa de {cap} e a netlist não declara provedor", peca)
                continue
            for r in rs:
                ok, motivo = req_ok(r)
                if not ok:
                    raise _Parou(etapa_, motivo, r.provedor or peca)

    def pecas_com(cap):
        return sorted({r.peca for r in requisitos(cap=cap)} & set(pecas))

    # ---- 1-3. sondagem, identificação, configuração ----------------------------
    celulas = nl.por_tipo("celula")
    n_cel = sum(int(b.atributos.get("n_celulas", 1)) for b in celulas)
    t = cfg["sondagem_us"] or n_cel * cfg["tempo_sonda_por_celula_us"]
    if "sondagem" in top.falhas:
        raise _Parou("Sondagem", "a sondagem não terminou: nenhuma célula foi identificada")
    ex.evento(0.0, "base", "sondando", f"{n_cel} células")
    etapa("Sondagem", 0.0, "sondagem", f"Sinal de teste fraco em {n_cel} células; nada energizado.",
          transparente=True)
    ex.evento(t, "base", "sondada")
    etapa("Identificação", t, "sondagem", f"{len(pecas)} peças reconhecidas pelo padrão terra/energia/sinal.")
    t += cfg["identificacao_us"]
    ex.evento(t, "base", "identificada", ", ".join(pecas))
    t += cfg["configuracao_celulas_us"]
    for c in celulas:
        ex.evento(t, c.id, "configurada")
    etapa("Configuração", t, "funcoes", f"{len(celulas)} grupos de células configurados; só agora podem energizar.",
          transparente=True)

    # ---- 4. fonte -----------------------------------------------------------------
    fontes = [f for f in tipo("fonte") if top.vivo(f)]
    if not fontes:
        raise _Parou("Fonte", "nenhuma fonte de 12 V viva na netlist", (tipo("fonte") or [None])[0])
    t_fonte = t + cfg["fonte_us"]
    for f in fontes:
        ex.evento(t_fonte, f, "power-good", "12 V")

    # ---- energia: redes, motoristas e regiões ----------------------------------
    pg = {}                                          # regulador -> t power-good (None = nunca)

    def t_rede(ponto):
        """Instante em que a rede de energia do ponto fica boa (None = nunca)."""
        raiz = top.rede("energia", ponto)
        melhores = []
        for b in blocos.values():
            if b.tipo not in ("fonte", "regulador"):
                continue
            for p in top.portas(b.id, "energia", ("sai",)):
                if top.rede("energia", p) == raiz:
                    if b.tipo == "fonte" and top.vivo(b.id):
                        melhores.append(t_fonte)
                    elif b.tipo == "regulador" and pg.get(b.id) is not None:
                        melhores.append(pg[b.id])
        return min(melhores) if melhores else None

    def t_alimentado(bloco, filhos=False):
        entradas = (top.portas_com_filhos(bloco, "energia", ("entra",)) if filhos
                    else top.portas(bloco, "energia", ("entra",)))
        if not entradas:
            return None
        ts = [t_rede(p) for p in entradas]
        return None if any(x is None for x in ts) else max(ts)

    def motoristas(ponto):
        raiz = top.rede("energia", ponto)
        return [b.id for b in nl.por_tipo("regulador")
                if any(top.rede("energia", p) == raiz for p in top.portas(b.id, "energia", ("sai",)))]

    controladores = tipo("controlador")
    flash = tipo("flash")
    # o orquestrador é quem controla os chips tradutores; sem eles, quem lê a flash
    provs = [r.provedor for r in requisitos(cap="controle") if r.provedor in controladores]
    fpga = max(set(provs), key=provs.count) if provs else None
    for c in ([] if fpga else controladores):
        rc = {top.rede("controle", p) for p in top.portas(c, "controle")}
        re_ = {top.rede("eletrico", p) for p in top.portas(c, "eletrico")}
        for f in flash:
            if ({top.rede("controle", p) for p in top.portas(f, "controle")} & rc or
                    {top.rede("eletrico", p) for p in top.portas(f, "eletrico")} & re_):
                fpga = c
    if fpga is None:
        prov = [r.provedor for r in requisitos(cap="firmware-UEFI") if r.provedor in controladores]
        fpga = prov[0] if prov else (controladores[0] if controladores else None)
    if fpga is None:
        raise _Parou("Standby", "não há controlador (FPGA) na netlist")
    pch = next((r.provedor for r in requisitos(cap="PCH/DMI") if r.provedor in blocos
                and blocos[r.provedor].atributos.get("plataforma") == "PCH"), None)
    peca_pch = blocos[pch].atributos.get("peca") if pch else None
    peca_fpga = blocos[fpga].atributos.get("peca")
    cpus = pecas_com("VR-SVID")

    standby, fila = set(), [fpga] + flash + ([pch] if pch else [])
    while fila:
        b = fila.pop()
        for p in top.portas(b, "energia", ("entra",)):
            for r in motoristas(p):
                if r not in standby:
                    standby.add(r)
                    fila.append(r)

    vr = [r.provedor for r in requisitos(cap="VR-SVID") if r.provedor in blocos]
    svid = set()
    for v in vr:
        if blocos[v].tipo == "regulador":
            svid.add(v)
        rv = {top.rede("controle", p) for p in top.portas(v, "controle", ("sai",))}
        for r in tipo("regulador"):
            if {top.rede("controle", p) for p in top.portas(r, "controle")} & rv:
                svid.add(r)
    principais = [r for r in tipo("regulador") if r not in standby and r not in svid]

    def subir(regs, t_habilita):
        pend = list(regs)
        while pend:
            avancou = False
            for r in list(pend):
                if not top.vivo(r):
                    pg[r] = None
                    ex.evento(t_habilita, r, "sem power-good", "falha injetada")
                    pend.remove(r)
                    avancou = True
                    continue
                tv = t_alimentado(r)
                if tv is not None:
                    pg[r] = max(tv, t_habilita) + cfg["partida_suave_us"]
                    tens = blocos[r].atributos.get("tensao_v")
                    ex.evento(pg[r], r, "power-good", f"{tens} V" if tens else "")
                    pend.remove(r)
                    avancou = True
            if not avancou:
                for r in pend:
                    pg[r] = None
                    ex.evento(t_habilita, r, "sem entrada", "o trilho de entrada nunca fica bom")
                break

    # ---- 5. standby e FPGA ------------------------------------------------------
    subir(standby, t_fonte)
    t_fpga = t_alimentado(fpga)
    if t_fpga is None or not top.vivo(fpga):
        culpado = next((r for r in standby if pg.get(r) is None), fpga)
        raise _Parou("Standby", f"o FPGA ({fpga}) não recebe alimentação de standby", culpado)
    ex.evento(t_fpga, fpga, "ligado")
    pecas_fpga = [p for p in pecas if p.upper().startswith("FPGA")]

    # ---- sinais: pontas, caminho e conferência -----------------------------------
    def pecas_do_sinal(s):
        return {s.origem[0].split(":", 1)[0], s.destino[0].split(":", 1)[0]}

    def chips_do_sinal(s):
        out = set()
        for cam in s.caminhos.values():
            for b, _ in cam:
                blk = blocos.get(b)
                if blk is None:
                    continue
                if blk.tipo == "chip_tradutor":
                    out.add(b)
                elif blk.pai and blocos.get(blk.pai) and blocos[blk.pai].tipo == "chip_tradutor":
                    out.add(blk.pai)
        return out

    def conferir_sinais(etapa_, sinais, travados=None):
        for s in sinais:
            if not s.caminhos or not all(s.caminhos.get(sd) for sd in s.sentidos):
                raise _Parou(etapa_, f"o sinal {s.id} não tem caminho completo", s.id)
            for cam in s.caminhos.values():
                corte = top.salto_cortado(cam)
                if corte:
                    raise _Parou(etapa_, f"o sinal {s.id} perdeu a ligação {corte[0][0]} – {corte[1][0]}", s.id)
            for c in chips_do_sinal(s):
                if travados is not None and c not in travados:
                    raise _Parou(etapa_, f"o sinal {s.id} passa pelo chip {c}, que não travou", c)

    def pino_nome(ponto):
        b = blocos.get(ponto[0])
        return b.atributos.get("pino") if b is not None and b.tipo == "pino" else None

    def sinais_do_pch(nome, outra):
        """Sinais entre o pino `nome` do PCH e a peça `outra`."""
        out = []
        for s in nl.sinais.values():
            for a, b in ((s.origem, s.destino), (s.destino, s.origem)):
                if (a[0].split(":", 1)[0] == peca_pch and pino_nome(a) == nome
                        and b[0].split(":", 1)[0] == outra):
                    out.append(s)
        return out

    def handshake(etapa_, nome, outra):
        ss = sinais_do_pch(nome, outra)
        if not ss:
            raise _Parou(etapa_, f"{nome} não está ligado entre {peca_pch} e {outra}", pch)
        conferir_sinais(etapa_, ss)

    def regioes_ok(etapa_, cap, efeito):
        for r in requisitos(cap=cap):
            if r.provedor in blocos and blocos[r.provedor].tipo == "flash":
                falta = [x for x in REGIOES_FIRMWARE[cap] if x not in top.regioes(r.provedor)]
                if falta:
                    raise _Parou(etapa_, f"a flash {r.provedor} não tem a região {', '.join(falta)}: {efeito}",
                                 r.provedor)
                if t_alimentado(r.provedor) is None:
                    raise _Parou(etapa_, f"a flash do firmware ({r.provedor}) está sem alimentação", r.provedor)

    if not pch:
        etapa("Fonte e standby", t_fpga, "funcoes", f"12 V da fonte e trilhos de standby; {fpga} ligado.",
              energizadas=pecas_fpga)
        # ---- 6. firmware e RSMRST# ----------------------------------------------
        exigir("Firmware", "firmware-UEFI")
        for f in flash:
            if t_alimentado(f) is None:
                raise _Parou("Firmware", f"a flash do firmware ({f}) está sem alimentação", f)
        t_fw = t_fpga + cfg["firmware_us"]
        ex.evento(t_fw, fpga, "firmware carregado")
        t_rsm = t_fw + cfg["rsmrst_us"]
        ex.evento(t_rsm, fpga, "RSMRST# solto")
        t_lib = t_rsm
    else:
        t_pch = t_alimentado(pch)
        if t_pch is None:
            sem = [p for p in top.portas(pch, "energia", ("entra",)) if t_rede(p) is None]
            raise _Parou("Standby", f"o PCH ({pch}) não recebe alimentação de standby",
                         next((m for p in sem for m in motoristas(p)), pch))
        pecas_fpga = pecas_fpga + [peca_pch]
        t_stby = max(t_fpga, t_pch)
        ex.evento(t_pch, pch, "standby", "PMC e ME no poço de standby")
        etapa("Fonte e standby", t_stby, "funcoes",
              f"12 V da fonte e trilhos de standby; {fpga} e o PMC do {peca_pch} ligados.",
              energizadas=pecas_fpga)
        # ---- 6. RSMRST#, ME e SLP_S3# --------------------------------------------
        handshake("RSMRST#", "RSMRST_IN", peca_fpga)
        t_rsm = t_stby + cfg["rsmrst_us"]
        ex.evento(t_rsm, fpga, "RSMRST# solto", f"o {peca_fpga} conferiu a base e libera o {peca_pch}")
        if not top.vivo(pch):
            raise _Parou("RSMRST#", f"o {peca_fpga} soltou RSMRST# e o {peca_pch} ({pch}) não responde", pch)
        exigir("ME", "firmware-ME", [peca_pch])
        spi = [s for s in nl.sinais.values()
               if any(blocos.get(x[0]) is not None and blocos[x[0]].tipo == "flash" for x in (s.origem, s.destino))
               and peca_pch in pecas_do_sinal(s)]
        if not spi:
            raise _Parou("ME", f"o {peca_pch} não tem SPI até a flash", pch)
        conferir_sinais("ME", spi)
        regioes_ok("ME", "firmware-ME", "o ME não sobe e o PCH segura SLP_S3#")
        t_me = t_rsm + cfg["me_us"]
        ex.evento(t_me, pch, "ME pronto", "descritor e região ME lidos da flash pela SPI")
        etapa("ME do chipset", t_me, "funcoes",
              f"O {peca_pch} lê o descritor e a região ME da flash pela SPI; o ME libera o boot.",
              energizadas=pecas_fpga)
        handshake("SLP_S3#", "SLP_S3_OUT", peca_fpga)
        t_lib = t_me + cfg["slp_s3_us"]
        ex.evento(t_lib, pch, "SLP_S3# solto", f"o {peca_fpga} habilita os reguladores principais")

    # ---- 7. reguladores principais ---------------------------------------------
    subir(principais, t_lib)
    bons = [pg[r] for r in principais if pg.get(r) is not None]
    t_trilhos = max(bons + [t_lib])
    energ = {}

    def t_energia_peca(peca):
        for r in requisitos(peca, "energia"):
            if r.provedor in pg:
                return pg[r.provedor]
            if r.provedor in blocos:
                if blocos[r.provedor].tipo == "fonte":
                    return t_fonte if top.vivo(r.provedor) else None
                ps = top.portas(r.provedor, "energia")
                return t_rede(ps[0]) if ps else None
        return t_trilhos

    for p in pecas:
        te = t_energia_peca(p)
        if te is not None and te <= t_trilhos:
            energ[p] = te
    etapa("Trilhos principais", t_trilhos, "funcoes",
          f"{sum(pg.get(r) is not None for r in principais)} de {len(principais)} reguladores principais com power-good.",
          energizadas=list(energ) + pecas_fpga)

    # ---- 8. chips tradutores ------------------------------------------------------
    rede_fpga = {top.rede("controle", p) for p in top.portas(fpga, "controle")}
    chips = tipo("chip_tradutor")
    t_cfg = {}
    for c in chips:
        if not top.vivo(c):
            raise _Parou("Tradutores", f"o chip tradutor {c} não responde", c)
        tp = t_alimentado(c, filhos=True)
        if tp is None:
            sem = [p for p in top.portas_com_filhos(c, "energia", ("entra",)) if t_rede(p) is None]
            culpado = next((m for p in sem for m in motoristas(p)), c)
            raise _Parou("Tradutores", f"o chip tradutor {c} está sem alimentação", culpado)
        ctl = top.portas_com_filhos(c, "controle", ("entra", "bidir"))
        if not ctl or not ({top.rede("controle", p) for p in ctl} & rede_fpga):
            raise _Parou("Tradutores", f"o chip tradutor {c} não tem caminho de controle até o {fpga}", c)
        t_cfg[c] = max(tp, t_lib) + cfg["config_chip_us"]
        ex.evento(t_cfg[c], c, "configurado", "polarização, aquecedores e monitores")
    t_chips = max(t_cfg.values(), default=t_trilhos)

    # ---- 9. lasers e anéis --------------------------------------------------------
    t_laser = {}
    for l in tipo("laser"):
        tp = t_alimentado(l)
        if not top.vivo(l) or tp is None:
            t_laser[l] = None
            ex.evento(t_chips, l, "apagado", "falha injetada" if not top.vivo(l) else "sem alimentação")
            continue
        t_laser[l] = max(tp, t_lib) + cfg["laser_us"]
        ex.evento(t_laser[l], l, "aceso")
    etapa("Tradutores e lasers", max([t_chips] + [v for v in t_laser.values() if v]), "funcoes",
          f"{len(chips)} chips tradutores configurados pelo {fpga}; "
          f"{sum(v is not None for v in t_laser.values())} de {len(t_laser)} lasers acesos.",
          energizadas=list(energ) + pecas_fpga)

    saidas_laser = {}
    for l in t_laser:
        for p in top.portas(l, "optico", ("sai", "bidir")):
            saidas_laser.setdefault(top.rede("optico", p), set()).add(l)
    t_trava = {}
    for c in chips:
        entradas = [p for p in top.portas_com_filhos(c, "optico", ("entra", "bidir"))
                    if p[1].startswith("laser")]
        fontes_luz = set()
        for p in entradas:
            fontes_luz |= saidas_laser.get(top.rede("optico", p), set())
        if not fontes_luz:
            raise _Parou("Anéis", f"nenhuma luz de laser chega ao chip {c}", c)
        apagados = sorted(l for l in fontes_luz if t_laser[l] is None)
        if apagados:
            raise _Parou("Anéis", f"os anéis do chip {c} não travam: o laser {apagados[0]} está apagado",
                          apagados[0])
        t_trava[c] = max([t_cfg[c]] + [t_laser[l] for l in fontes_luz]) + cfg["aneis_travamento_us"]
        ex.evento(t_trava[c], c, "anéis travados")
    t_aneis = max(t_trava.values(), default=t_chips)
    etapa("Anéis travados", t_aneis, "temperatura",
          f"Aquecedores varrem e travam os anéis dos {len(chips)} chips.",
          energizadas=list(energ) + pecas_fpga)

    # ---- 10. relógio de referência ------------------------------------------------
    t_clk = None
    for k in tipo("relogio"):
        tp = t_alimentado(k)
        if top.vivo(k) and tp is not None:
            tk = max(tp, t_lib) + cfg["refclk_us"]
            t_clk = tk if t_clk is None else min(t_clk, tk)
            ex.evento(tk, k, "estável", "100 MHz")
    if t_clk is None:
        raise _Parou("Relógio", "nenhum relógio de referência vivo e alimentado",
                     (tipo("relogio") or [None])[0])
    exigir("Relógio", "BCLK")

    # ---- 11. PWROK -----------------------------------------------------------------
    sem_pg = [r for r in principais if pg.get(r) is None]
    if sem_pg:
        raise _Parou("PWROK", f"PWROK segurado: o regulador {sem_pg[0]} não deu power-good", sem_pg[0])
    exigir("PWROK", "sequenciamento-PWROK")
    t_pwrok = max(t_trilhos, t_aneis, t_clk) + cfg["pwrok_us"]
    if pch:
        handshake("PWROK", "SYS_PWROK", peca_fpga)
        ex.evento(t_pwrok, fpga, "SYS_PWROK", "trilhos, tradutores, anéis e relógio prontos")
        for cpu in cpus:
            handshake("PWROK", "PWROK", cpu)
        t_pwrok += cfg["procpwrgd_us"]
        ex.evento(t_pwrok, pch, "PROCPWRGD")
    else:
        ex.evento(t_pwrok, fpga, "PWROK")

    # ---- 12. VCCIN pelo SVID ----------------------------------------------------
    exigir("Núcleo da CPU", "VR-SVID", cpus)
    t_vcc = t_pwrok
    for r in sorted(svid):
        if blocos[r].tipo != "regulador":
            continue
        if not top.vivo(r):
            raise _Parou("Núcleo da CPU", f"o regulador {r} não sobe o VCCIN", r)
        tv = t_alimentado(r)
        if tv is None:
            raise _Parou("Núcleo da CPU", f"o regulador {r} está sem entrada", r)
        rampa = cfg["vid_boot_v"] * 1000 / cfg["slew_mv_us"]
        pg[r] = max(tv, t_pwrok) + cfg["svid_latencia_us"] + rampa + cfg["vrm_assentamento_us"]
        ex.evento(pg[r], r, "power-good", f"VID de boot {cfg['vid_boot_v']:.2f} V pelo SVID")
        t_vcc = max(t_vcc, pg[r])
    for p in pecas:
        te = t_energia_peca(p)
        if te is not None:
            energ[p] = te
    todas = sorted(set(energ) | set(pecas_fpga))
    etapa("Núcleo da CPU", t_vcc, "corrente",
          f"PWROK; a CPU pede o VID de boot pelo SVID e o VCCIN sobe a {cfg['slew_mv_us']:.0f} mV/µs.",
          energizadas=todas, transparente=True)

    # ---- 13. PLTRST# ----------------------------------------------------------------
    exigir("PLTRST", "PCH/DMI", cpus)
    sinais_cpu = [s for s in nl.sinais.values() if pecas_do_sinal(s) & set(cpus)]
    # a DMI só treina depois do PLTRST#; com chipset ela é conferida na leitura da BIOS
    dmi = [s for s in sinais_cpu if pch and peca_pch in pecas_do_sinal(s) and s.protocolo != "AUX"]
    if pch:
        for cpu in cpus:
            handshake("PLTRST", "PLTRST", cpu)
    conferir_sinais("PLTRST", [s for s in sinais_cpu if s not in dmi], t_trava)
    clk_rede = {top.rede("eletrico", p) for k in tipo("relogio") if top.vivo(k)
                for p in top.portas(k, "eletrico", ("sai", "bidir"))}
    for cpu in cpus:
        pinos_cpu = [b for b in pinos if _peca_do_pino(b) == cpu]
        chega = any(top.rede("eletrico", pt) in clk_rede
                    for b in pinos_cpu for pt in top.portas(b.id, "eletrico"))
        if not chega:
            raise _Parou("PLTRST", f"o relógio de referência não chega a nenhum pino da {cpu}", cpu)
    t_plt = t_vcc + cfg["pltrst_us"]
    ex.evento(t_plt, pch or fpga, "PLTRST# solto")
    etapa("Relógio e reset", t_plt, "funcoes",
          (f"Relógio de 100 MHz do {peca_pch} estável; o {peca_pch} solta PROCPWRGD e PLTRST#." if pch else
           "Relógio de 100 MHz estável, PWROK e PLTRST# soltos: a CPU começa a executar o firmware."),
          energizadas=todas, enlaces=["AUX"])
    t_rst = t_plt
    if pch:
        # ---- 13b. BIOS pela DMI ---------------------------------------------------
        if not dmi:
            raise _Parou("BIOS pela DMI", f"não há DMI entre {', '.join(cpus)} e {peca_pch}", pch)
        conferir_sinais("BIOS pela DMI", dmi, t_trava)
        exigir("BIOS pela DMI", "firmware-UEFI", cpus)
        regioes_ok("BIOS pela DMI", "firmware-UEFI", "a CPU não acha o vetor de reset")
        t_rst = t_plt + cfg["bios_dmi_us"]
        for cpu in cpus:
            ex.evento(t_rst, cpu, "BIOS lida", f"vetor de reset pela DMI até a SPI do {peca_pch}")
        etapa("BIOS pela DMI", t_rst, "funcoes",
              f"A DMI treina; a CPU busca o vetor de reset e o início da BIOS pela DMI, e o {peca_pch} "
              f"lê a região BIOS da flash pela SPI.", energizadas=todas, enlaces=["AUX"])

    # ---- 14. treino de memória --------------------------------------------------------
    ddr = [s for s in nl.sinais.values() if s.protocolo == "DDR5-4800"]
    dimms = sorted({p for s in ddr for p in pecas_do_sinal(s)} - set(cpus))
    exigir("Treino da memória", "SPD/I3C", dimms)
    conferir_sinais("Treino da memória", ddr, t_trava)
    if not ddr:
        raise _Parou("Treino da memória", "não há nenhum sinal DDR5 na netlist", (cpus or [None])[0])
    esp = DDR5.avaliar_netlist(nl)
    if esp["problemas"]:
        bloco, motivo = esp["problemas"][0]
        raise _Parou("Treino da memória", motivo, bloco)
    n_mrw = sum(1 for c in CMD.decodificar("DDR5-4800", DDR5.sequencia_padrao()) if c.registrador)
    ex.evento(t_rst, fpga, "MRW espelhados",
              f"{n_mrw} MRW de terminação e força acompanhados por {esp['chaves']} chaves do lado do controlador")
    t_mem = t_rst + cfg["treino_memoria_us"]
    for d in dimms:
        ex.evento(t_mem, d, "treinado")
    etapa("Treino da memória", t_mem, "funcoes",
          f"A CPU programa terminação e força por MRW (os tradutores do lado dela espelham), varre o "
          f"atraso do DQS em cada pista de {len(dimms)} módulos e grava o centro da janela.",
          energizadas=todas, enlaces=["AUX", "DDR5"])

    # ---- 15. PCIe e GDDR7 ------------------------------------------------------------
    enlaces = {"AUX", "DDR5"}
    t_fim = t_mem
    pcie = [s for s in nl.sinais.values() if s.protocolo == "PCIe5"]
    if pcie:
        gpus = sorted(({p for s in pcie for p in pecas_do_sinal(s)} & set(pecas)) - set(cpus))
        exigir("PCIe", "raiz-PCIe", gpus, obrigatorio=False)
        exigir("PCIe", "12V-cabo", gpus, obrigatorio=False)
        conferir_sinais("PCIe", pcie, t_trava)
        res = _ltssm(nl, blocos, pcie, set(pecas), t_trava)
        if not res["ltssm"].ok:
            raise _Parou("PCIe", f"LTSSM parou em {res['ltssm'].parou_em}: {res['ltssm'].motivo}",
                         res["bloco"])
        t_pcie = res["ltssm"].total_ms * 1e3
        t_fim = max(t_fim, t_mem + t_pcie)
        for g in gpus:
            ex.evento(t_mem + t_pcie, g, "enlace PCIe ativo",
                      f"Gen5 x16, preset {res['olho']['preset']}, CTLE {res['olho']['ctle_db']} dB")
        enlaces.add("PCIe")
    g7 = [s for s in nl.sinais.values() if s.protocolo == "GDDR7-32"]
    if g7:
        conferir_sinais("GDDR7", g7, t_trava)
        t_g7 = t_mem + (t_pcie if pcie else 0.0) + cfg["treino_gddr7_us"]
        t_fim = max(t_fim, t_g7)
        ex.evento(t_g7, "GDDR7", "treinada")
        enlaces.add("GDDR7")
    etapa("PCIe e GDDR7", t_fim, "funcoes",
          "Enlace PCIe até a GPU e treino da GDDR7 em PAM3." if pcie or g7 else "Sem PCIe nem GDDR7 nesta montagem.",
          energizadas=todas, enlaces=enlaces)

    # ---- 16. banco unificado ------------------------------------------------------------
    ponte = next((b for b in nl.por_tipo("controlador")
                  if "DIMM-emulado" in b.atributos.get("capacidades", ())), None)
    if ponte is not None:
        exigir("Banco unificado", "memoria-compartilhada", sorted(set(cpus) | set(pecas_com("raiz-PCIe"))))
        if t_alimentado(ponte.id) is None:
            raise _Parou("Banco unificado", f"a lógica da ponte ({ponte.id}) está sem alimentação",
                         next((m for p in top.portas(ponte.id, "energia", ("entra",)) for m in motoristas(p)),
                              ponte.id))
        if not ({top.rede("controle", p) for p in top.portas(ponte.id, "controle")} & rede_fpga):
            raise _Parou("Banco unificado", f"a ponte não tem controle até o {fpga}", ponte.id)
        exigir("Banco unificado", "posse-do-banco", pecas_com("posse-do-banco"))
        for m in nl.por_tipo("mux_dono"):
            if m.pai not in t_trava:
                raise _Parou("Banco unificado", f"o mux de posse {m.id} está num tradutor que não travou", m.pai)
        a = ponte.atributos
        t_cal = cfg["calibracao_banco_us"] or MU.tempo_calibracao_us(a["chips"], a["chip_real_gb"])
        t_banco = t_fim + cfg["sondas_banco_us"] + t_cal
        ex.evento(t_fim + cfg["sondas_banco_us"], ponte.id, "sondas gravadas",
                  f"{MU.BITS_M + 3} sondas da GPU e {MU.BITS_L} da CPU")
        ex.evento(t_banco, ponte.id, "mapas aprendidos", "varredura do banco e conferência por sondas aleatórias")
        for r in range(a["ranks"]):
            ex.evento(t_banco, f"rank {r}", "posse da GPU", f"{a['canais']} chips")
        enlaces.add("BANCO")
        t_fim = t_banco
        etapa("Banco unificado", t_fim, "funcoes",
              f"A ponte aprende os mapas de endereço da GPU e da CPU por sondas e varre o banco em "
              f"{_ms(t_cal)}; o {peca_fpga} dá os {a['ranks']} ranks à GPU. A CPU vê os "
              f"{a['janela_gb']:.0f} GB como um DIMM de CL{a['cl_declarado']}; a GPU, como a VRAM dela.",
              energizadas=todas, enlaces=enlaces)
    ex.evento(t_fim, "sistema", "pronto")
    etapa("Pronto", t_fim, "temperatura", f"Sistema ligado em {_ms(t_fim)}.",
          energizadas=todas, enlaces=enlaces)
