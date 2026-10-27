
import pytest

from modulos.conexoes.netlist import Netlist, Requisito, Sinal
from modulos.conexoes.verificador import REGRAS, verificar

CTX = {"margem_db": 3.0}
PADS = ["PCIe5-CML", "DDR5-DQ", "DDR5-DQS", "DDR5-CA"]
TERM = {"PCIe5-CML": "cml_ac", "DDR5-DQ": "odt", "DDR5-DQS": "odt", "DDR5-CA": "odt"}
LASER = [1310.0, 1310.8, 1311.6, 1312.4]


class _Rede:
    """Netlist mínima e completa: duas peças, PCIe num sentido, DQ/DQS bidirecionais e CA."""

    def __init__(self, **op):
        self.op = op
        self.n = n = Netlist()
        self.k = {}
        n.bloco("fonte:atx", "fonte"); n.porta("fonte:atx", "12v", "energia", "sai", tensao_v=12.0)
        for t in ("rail:12v", "rail:0v9"):
            n.bloco(t, "trilho"); n.porta(t, "rede", "energia", "bidir")
        n.ligar(("fonte:atx", "12v"), ("rail:12v", "rede"), "trilha")
        n.bloco("reg:0v9", "regulador", tensao_v=0.9, corrente_max_a=op.get("corrente_reg", 20.0))
        n.porta("reg:0v9", "vin", "energia", "entra"); n.porta("reg:0v9", "vout", "energia", "sai")
        n.porta("reg:0v9", "ctl", "controle", "entra")
        n.ligar(("reg:0v9", "vin"), ("rail:12v", "rede"), "trilha")
        n.ligar(("reg:0v9", "vout"), ("rail:0v9", "rede"), "trilha")

        n.bloco("ctl:fpga", "controlador", potencia_w=1.0, capacidades=["pch_minimo"])
        n.porta("ctl:fpga", "vdd", "energia", "entra")
        n.porta("ctl:fpga", "i3c0", "controle", "sai", max_dispositivos=op.get("max_disp", 32))
        n.porta("ctl:fpga", "i3c1", "controle", "sai")
        self._vdd("ctl:fpga")
        n.ligar(("reg:0v9", "ctl"), ("ctl:fpga", "i3c0"), "trilha")
        n.requisitos.append(Requisito("A", "pch_minimo", op.get("provedor", "ctl:fpga")))

        n.bloco("laser:0", "laser", lambdas_nm=LASER, potencia_w=0.5)
        for p in ("out0", "out1"):
            n.porta("laser:0", p, "optico", "sai")
        n.porta("laser:0", "vdd", "energia", "entra"); n.porta("laser:0", "ctl", "controle", "entra")
        self._vdd("laser:0")
        n.ligar(("laser:0", "ctl"), ("ctl:fpga", "i3c0"), "trilha")

        for lado, x, saida in (("A", 20.0, "out0"), ("B", op.get("x_chip_b", 80.0), "out1")):
            fl = f"fib:l{lado}"
            n.bloco(fl, "fibra", comprimento_mm=50.0)
            n.porta(fl, "a", "optico", "bidir"); n.porta(fl, "b", "optico", "bidir")
            n.ligar(("laser:0", saida), (fl, "a"), "fibra")
            c = f"tx:{lado}:0"
            n.bloco(c, "chip_tradutor", posicao=(x, 0.0), largura_mm=10.0, profundidade_mm=10.0,
                    vias_max=op.get("vias_max", 16) if lado == "A" else 16, potencia_w=1.0)
            n.porta(c, "vdd", "energia", "entra"); n.porta(c, "vddio", "energia", "entra")
            n.porta(c, "ctl", "controle", "entra"); n.porta(c, "laser", "optico", "entra")
            self._vdd(c); self._vdd(c, "vddio")
            n.ligar((c, "ctl"), ("ctl:fpga", "i3c0"), "trilha")
            n.ligar((c, "laser"), (fl, "b"), "fibra")
            det = f"{c}:det"
            n.bloco(det, "detector_sentido", pai=c, decisao_ps=500.0, potencia_w=0.1)
            n.porta(det, "ca0", "eletrico", "entra"); n.porta(det, "sentido", "controle", "sai")
            n.porta(det, "vdd", "energia", "entra")
            self._vdd(det)
        # fibras de dados: ida (A->B) e volta (B->A)
        for sentido, tx, rx in (("ida", "A", "B"), ("volta", "B", "A")):
            ct, cr = f"tx:{tx}:0", f"tx:{rx}:0"
            mux, dmx = f"{ct}:mux_{sentido}", f"{cr}:demux_{sentido}"
            at, ar = f"{ct}:ac_{sentido}", f"{cr}:ac_{sentido}"
            n.bloco(mux, "mux", pai=ct); n.porta(mux, "out", "optico", "sai")
            n.bloco(dmx, "demux", pai=cr); n.porta(dmx, "in", "optico", "entra")
            for a, lado in ((at, ct), (ar, cr)):
                n.bloco(a, "acoplador", pai=lado)
            n.porta(at, "chip", "optico", "entra"); n.porta(at, "fibra", "optico", "sai")
            n.porta(ar, "fibra", "optico", "entra"); n.porta(ar, "chip", "optico", "sai")
            f = f"fib:{sentido}"
            n.bloco(f, "fibra", comprimento_mm=60.0)
            n.porta(f, "a", "optico", "bidir"); n.porta(f, "b", "optico", "bidir")
            n.ligar((mux, "out"), (at, "chip"), "guia")
            n.ligar((at, "fibra"), (f, "a"), "fibra")
            n.ligar((f, "b"), (ar, "fibra"), "fibra")
            n.ligar((ar, "chip"), (dmx, "in"), "guia")
            self.k[sentido] = 0

        lam_ida = {"PEG": 1310.0, "DQ0": 1310.8, "DQS0": 1311.6, "CA0": 1312.4}
        lam_volta = {"DQ0": 1310.0, "DQS0": 1310.8}
        if op.get("lambda_fora_do_laser"):
            lam_ida["PEG"] = 1315.0
        self.y = 0.0
        self._sinal_uni("A:PEG_TX0", "B:PEG_RX0", "PCIe5", "PCIe5-CML", lam_ida["PEG"], rx_lam=op.get("rx_lam"))
        caA = self._sinal_uni("A:CA0", "B:CA0", "DDR5-4800", "DDR5-CA", lam_ida["CA0"])
        for nome in ("DQ0", "DQS0"):
            self._sinal_bidir(nome, lam_ida[nome], lam_volta[nome])
        n.ligar(("tx:A:0:det", "ca0"), ("cel:A:CA0", "base"), "trilha")
        if not op.get("sem_ca_b"):
            n.ligar(("tx:B:0:det", "ca0"), (caA, "e"), "trilha")

    # ------------------------------------------------------------------ peças
    def _vdd(self, bloco, porta="vdd"):
        self.n.ligar((bloco, porta), ("rail:0v9", "rede"), "trilha")

    def _lado_eletrico(self, pino, padrao, sentido, x):
        n = self.n
        n.bloco(pino, "pino", posicao=(x, self.y))
        n.porta(pino, "e", "eletrico", sentido, padrao)
        cel, tr = f"cel:{pino}", f"tr:{pino}"
        c_ff = self.op.get("c_ff", {}).get(pino, 30.0)
        n.bloco(cel, "celula", n_celulas=3, r_on_ohm=5.0, c_ff=c_ff)
        n.porta(cel, "pino", "eletrico", "bidir"); n.porta(cel, "base", "eletrico", "bidir")
        n.porta(cel, "ctl", "controle", "entra")
        n.ligar((pino, "e"), (cel, "pino"), "contato")
        n.ligar((cel, "ctl"), ("ctl:fpga", "i3c1"), "trilha")
        comp = self.op.get("trilha_mm", {}).get(pino, 15.0)
        n.bloco(tr, "trilha", comprimento_mm=comp, z_ohm=40.0, perda_db_mm_ghz=0.02)
        n.porta(tr, "a", "eletrico", "bidir"); n.porta(tr, "b", "eletrico", "bidir")
        n.ligar((cel, "base"), (tr, "a"), "trilha")
        return [(pino, "e"), (cel, "pino"), (cel, "base"), (tr, "a"), (tr, "b")]

    def _via(self, tipo, chip, lam, padrao, sentido_e):
        n = self.n
        i = len([b for b in n.filhos(chip) if b.tipo in ("via_tx", "via_rx")])
        v = f"{chip}:{'t' if tipo == 'via_tx' else 'r'}{i}"
        n.bloco(v, tipo, pai=chip, taxa_max_gbps=32.0, potencia_w=0.05)
        pads = [p for p in PADS if p not in self.op.get("sem_padrao", ())]
        attrs = {"padroes": pads}
        if tipo == "via_rx":
            attrs["terminacao"] = self.op.get("terminacao", {}).get(padrao, TERM[padrao])
        n.porta(v, "e", "eletrico", sentido_e, **attrs)
        n.porta(v, "luz", "optico", "sai" if tipo == "via_tx" else "entra", lambda_nm=lam)
        n.porta(v, "vdd", "energia", "entra"); n.porta(v, "ctl", "controle", "entra")
        self._vdd(v)
        n.ligar((v, "ctl"), (chip, "ctl"), "interno")
        if tipo == "via_tx":
            n.porta(v, "laser", "optico", "entra")
            n.ligar((v, "laser"), (chip, "laser"), "guia")
        return v

    def _optico(self, sentido, tx, rx, lam, padrao, rx_lam=None):
        n = self.n
        ct, cr = f"tx:{tx}:0", f"tx:{rx}:0"
        k = self.k[sentido]; self.k[sentido] += 1
        mux, dmx = f"{ct}:mux_{sentido}", f"{cr}:demux_{sentido}"
        at, ar, f = f"{ct}:ac_{sentido}", f"{cr}:ac_{sentido}", f"fib:{sentido}"
        n.porta(mux, f"in{k}", "optico", "entra"); n.porta(dmx, f"out{k}", "optico", "sai")
        vt = self._via("via_tx", ct, lam, padrao, "entra")
        vr = self._via("via_rx", cr, rx_lam or lam, padrao, "sai")
        n.ligar((vt, "luz"), (mux, f"in{k}"), "guia")
        n.ligar((dmx, f"out{k}"), (vr, "luz"), "guia")
        cam = [(vt, "e"), (vt, "luz"), (mux, f"in{k}"), (mux, "out"), (at, "chip"), (at, "fibra"),
               (f, "a"), (f, "b"), (ar, "fibra"), (ar, "chip"), (dmx, "in"), (dmx, f"out{k}"),
               (vr, "luz"), (vr, "e")]
        return vt, vr, cam

    def _sinal_uni(self, origem, destino, proto, padrao, lam, rx_lam=None):
        n = self.n
        self.y += 1.0
        a = self._lado_eletrico(origem, padrao, "sai", 0.0)
        b = self._lado_eletrico(destino, padrao, "entra", 100.0)
        vt, vr, meio = self._optico("ida", "A", "B", lam, padrao, rx_lam)
        n.ligar(a[-1], (vt, "e"), "trilha")
        n.ligar((vr, "e"), b[-1], "trilha")
        s = Sinal(f"{origem}->{destino}", proto, padrao.split("-")[-1], padrao, (origem, "e"),
                  (destino, "e"), ("ida",))
        s.caminhos["ida"] = a + meio + list(reversed(b))
        n.sinal(s)
        return vr

    def _sinal_bidir(self, nome, lam_ida, lam_volta):
        n = self.n
        self.y += 1.0
        padrao = "DDR5-DQS" if nome.startswith("DQS") else "DDR5-DQ"
        pa, pb = f"A:{nome}", f"B:{nome}"
        a = self._lado_eletrico(pa, padrao, "bidir", 0.0)
        b = self._lado_eletrico(pb, padrao, "bidir", 100.0)
        chaves = {}
        for lado, lado_e in (("A", a), ("B", b)):
            c = f"tx:{lado}:0:s_{nome}"
            n.bloco(c, "chave_sentido", pai=f"tx:{lado}:0", comutacao_ps=200.0)
            n.porta(c, "pino", "eletrico", "bidir"); n.porta(c, "tx", "eletrico", "sai")
            n.porta(c, "rx", "eletrico", "entra"); n.porta(c, "sentido", "controle", "entra")
            n.ligar(lado_e[-1], (c, "pino"), "trilha")
            n.ligar((c, "sentido"), (f"tx:{lado}:0:det", "sentido"), "interno")
            chaves[lado] = c
        vt, vr, meio = self._optico("ida", "A", "B", lam_ida, padrao)
        n.ligar((chaves["A"], "tx"), (vt, "e"), "interno"); n.ligar((vr, "e"), (chaves["B"], "rx"), "interno")
        vt2, vr2, meio2 = self._optico("volta", "B", "A", lam_volta, padrao)
        n.ligar((chaves["B"], "tx"), (vt2, "e"), "interno"); n.ligar((vr2, "e"), (chaves["A"], "rx"), "interno")
        s = Sinal(f"{pa}<->{pb}", "DDR5-4800", nome.rstrip("0123456789"), padrao, (pa, "e"), (pb, "e"),
                  ("ida", "volta"), grupo="A0")
        s.caminhos["ida"] = (a + [(chaves["A"], "pino"), (chaves["A"], "tx")] + meio
                             + [(chaves["B"], "rx"), (chaves["B"], "pino")] + list(reversed(b)))
        s.caminhos["volta"] = (b + [(chaves["B"], "pino"), (chaves["B"], "tx")] + meio2
                               + [(chaves["A"], "rx"), (chaves["A"], "pino")] + list(reversed(a)))
        n.sinal(s)


def rede(**op):
    return _Rede(**op).n


def _erros(net, ctx=CTX):
    return verificar(net, ctx).regras_com_erro()


def test_rede_minima_passa_em_tudo():
    rel = verificar(rede(), CTX)
    assert rel.ok, rel.resumo()
    assert not rel.violacoes, [v.mensagem for v in rel.violacoes]
    assert set(rel.resumo().split()) >= {"OK"}
    assert all(r in rel.resumo() for r in REGRAS)


def test_sem_contexto_usa_o_enlace_viavel():
    assert verificar(rede()).ok


def test_r01_salto_sem_ligacao():
    net = rede()
    s = net.sinais["A:PEG_TX0->B:PEG_RX0"]
    s.caminhos["ida"].remove(("fib:ida", "b"))
    assert _erros(net) == {"R01-caminho"}


def test_r01_sem_caminho_no_sentido():
    net = rede()
    del net.sinais["A:DQ0<->B:DQ0"].caminhos["volta"]
    assert _erros(net) == {"R01-caminho"}


def test_r02_dois_drivers():
    net = rede()
    net.blocos["tx:A:0:t0"].portas["e"].sentido = "sai"
    assert _erros(net) == {"R02-sentido"}


def test_r02_bidirecional_sem_comando():
    assert _erros(rede(sem_ca_b=True)) == {"R02-sentido"}


def test_r03_via_nao_suporta_padrao():
    assert _erros(rede(sem_padrao=("PCIe5-CML",))) == {"R03-padrao"}


def test_r03_terminacao_errada():
    assert _erros(rede(terminacao={"PCIe5-CML": "odt"})) == {"R03-padrao"}


def test_r03_nivel_diferente_sem_conversor():
    net = rede()
    net.blocos["B:CA0"].portas["e"].padrao = "CMOS-1V8"
    assert _erros(net) == {"R03-padrao"}


def test_r04_celula_lenta():
    assert _erros(rede(c_ff={"A:PEG_TX0": 1000.0})) == {"R04-banda"}


def test_r04_trilha_longa():
    assert _erros(rede(trilha_mm={"A:PEG_TX0": 40.0})) == {"R04-banda"}


def test_r05_lambda_diferente_na_recepcao():
    assert _erros(rede(rx_lam=1313.2)) == {"R05-optico"}


def test_r05_lambda_que_o_laser_nao_tem():
    net = _Rede(lambda_fora_do_laser=True).n
    net.blocos["tx:B:0:r0"].portas["luz"].atributos["lambda_nm"] = 1315.0
    assert _erros(net) == {"R05-optico"}


def test_r05_margem_negativa():
    assert _erros(rede(), {"margem_db": -1.0}) == {"R05-optico"}


def test_r05_lambda_repetido_na_fibra():
    net = rede()
    for v in ("tx:A:0:t1", "tx:B:0:r1"):
        net.blocos[v].portas["luz"].atributos["lambda_nm"] = 1310.0
    assert _erros(net) == {"R05-optico"}


def test_r06_regulador_sobrecarregado():
    assert _erros(rede(corrente_reg=1.0)) == {"R06-energia"}


def test_r07_barramento_cheio():
    assert _erros(rede(max_disp=3)) == {"R07-controle"}


def test_r08_chip_sobre_a_peca():
    assert _erros(rede(x_chip_b=100.0)) == {"R08-capacidade"}


def test_r08_chip_na_camada_de_fotonica_pode_ficar_sob_a_peca():
    net = rede(x_chip_b=100.0)
    for c in net.por_tipo("chip_tradutor"):
        c.atributos["camada"] = "fotonica"
    assert "R08-capacidade" not in _erros(net)


def test_r06_contato_acima_de_1a():
    ctx = {**CTX, "contatos": [{"peca": "A", "trilho": "VCCIN", "pinos_acima_1a": 3,
                                "pino_max_a": 1.2, "celula_max_a": 0.5}]}
    assert _erros(rede(), ctx) == {"R06-energia"}


def test_r08_vias_demais():
    assert _erros(rede(vias_max=4)) == {"R08-capacidade"}


def test_r09_grupo_desalinhado():
    assert _erros(rede(trilha_mm={"A:DQ0": 100.0})) == {"R09-tempo"}


def test_r09_atraso_acima_do_limite():
    assert _erros(rede(), {**CTX, "atraso_max_ps": {"PCIe5": 100.0}}) == {"R09-tempo"}


def test_r10_relogio_com_duas_fontes():
    net = rede()
    net.bloco("clk:ref", "relogio")
    net.porta("clk:ref", "out0", "eletrico", "sai", "HCSL-100M")
    net.porta("clk:ref", "vdd", "energia", "entra")
    net.ligar(("clk:ref", "vdd"), ("rail:0v9", "rede"), "trilha")
    net.ligar(("clk:ref", "out0"), ("cel:B:DQS0", "base"), "trilha")
    assert _erros(net) == {"R10-relogio"}


def test_r10_grupo_em_fibras_diferentes():
    net = rede()
    n = net
    n.bloco("fib:extra", "fibra", comprimento_mm=60.0)
    n.porta("fib:extra", "a", "optico", "bidir"); n.porta("fib:extra", "b", "optico", "bidir")
    s = net.sinais["A:DQS0<->B:DQS0"]
    cam = s.caminhos["ida"]
    i = cam.index(("fib:ida", "a"))
    cam[i:i + 2] = [("fib:extra", "a"), ("fib:extra", "b")]
    n.ligar(("tx:A:0:ac_ida", "fibra"), ("fib:extra", "a"), "fibra")
    n.ligar(("fib:extra", "b"), ("tx:B:0:ac_ida", "fibra"), "fibra")
    n.blocos["tx:A:0:ac_ida"].atributos["max_fibras"] = 2
    n.blocos["tx:B:0:ac_ida"].atributos["max_fibras"] = 2
    assert _erros(net) == {"R10-relogio"}


def test_r11_requisito_sem_provedor():
    assert _erros(rede(provedor=None)) == {"R11-requisito"}


def test_r11_provedor_sem_a_capacidade():
    net = rede()
    net.blocos["ctl:fpga"].atributos["capacidades"] = []
    assert _erros(net) == {"R11-requisito"}


def test_r12_tipo_desconhecido():
    net = rede()
    net.bloco("x:1", "foo")
    assert _erros(net) == {"R12-orfao"}


def test_r12_porta_obrigatoria_solta():
    net = rede()
    net.bloco("fib:solta", "fibra", comprimento_mm=10.0)
    net.porta("fib:solta", "a", "optico", "bidir"); net.porta("fib:solta", "b", "optico", "bidir")
    assert _erros(net) == {"R12-orfao"}


# ------------------------------------------------------------------ netlist real
@pytest.mark.lento
def test_netlist_real_fecha_com_tradutor_sob_a_peca_e_rele(netlist_real):
    rel = verificar(netlist_real)
    assert rel.ok, rel.resumo()
