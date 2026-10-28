import pytest

from modulos.conexoes.construir import _contorno, construir
from modulos.dados.roteamento import rotear
from modulos.optica import enlace as E
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M


@pytest.fixture(scope="module")
def montado():
    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, s), s)
    opt = E.carregar("viavel")
    plano = rotear(cfg, canais_por_fibra=opt["canais_por_fibra"])
    return cfg, plano, construir(m, cfg, plano, opt)


def test_todo_pino_de_sinal_vira_sinal_com_caminho(montado):
    cfg, _, nl = montado
    pontas = {s.origem[0] for s in nl.sinais.values()} | {s.destino[0] for s in nl.sinais.values()}
    # as saídas de relógio do PCH ficam no meio do caminho: a origem é o gerador interno
    pontas |= {b for s in nl.sinais.values() if s.papel == "REFCLK" for b, _ in s.caminhos["ida"]}
    faltando = []
    for pc in cfg.pecas:
        if pc.nome == "FPGA":       # banco genérico de E/S: só os pinos usados entram
            continue
        for itf in pc.peca.interfaces.values():
            for nome in itf.sinais:
                if f"{pc.nome}:{nome}" not in pontas:
                    faltando.append(f"{pc.nome}:{nome}")
    assert faltando == []
    assert all(s.caminhos.get(sent) for s in nl.sinais.values() for sent in s.sentidos)


def test_caminhos_ligados_porta_a_porta(montado):
    _, _, nl = montado
    for s in nl.sinais.values():
        for sentido, cam in s.caminhos.items():
            ini, fim = (s.origem, s.destino) if sentido == "ida" else (s.destino, s.origem)
            assert cam[0] == ini and cam[-1] == fim, s.id
            for x, y in zip(cam, cam[1:]):
                for b, p in (x, y):
                    assert p in nl.blocos[b].portas, (s.id, b, p)
                if x[0] != y[0]:
                    assert nl.ligacao_entre(x, y) is not None, (s.id, x, y)


def test_sinal_rapido_passa_por_tradutor_e_fibra(montado):
    _, _, nl = montado
    s = nl.sinais["CPU.DDR5_A_A_DQ0->DIMM0.DDR5_A_DQ0"] if "CPU.DDR5_A_A_DQ0->DIMM0.DDR5_A_DQ0" in nl.sinais \
        else next(x for x in nl.sinais.values() if x.papel == "DQ" and x.protocolo == "DDR5-4800")
    for sentido in ("ida", "volta"):
        tipos = [nl.blocos[b].tipo for b, _ in s.caminhos[sentido]]
        for t in ("celula", "trilha", "chave_sentido", "via_tx", "mux", "acoplador", "fibra",
                  "demux", "via_rx"):
            assert t in tipos, (sentido, t)


def test_nenhum_chip_tradutor_sobre_peca(montado):
    cfg, _, nl = montado
    for ch in nl.por_tipo("chip_tradutor"):
        x, y = ch.posicao
        w, d = ch.atributos["largura_mm"] / 2, ch.atributos["profundidade_mm"] / 2
        for pc in cfg.pecas:
            xs = [q[0] for q in _contorno(pc)]
            ys = [q[1] for q in _contorno(pc)]
            invade = x + w > min(xs) and x - w < max(xs) and y + d > min(ys) and y - d < max(ys)
            assert not invade, (ch.id, pc.nome)


def test_bloco_ativo_tem_energia_e_controle(montado):
    _, _, nl = montado
    for b in nl.blocos.values():
        for nome, p in b.portas.items():
            if p.dominio == "energia" and p.sentido == "entra":
                assert nl.ligacoes_de((b.id, nome)), (b.id, nome)
        if "ctl" in b.portas:
            assert nl.ligacoes_de((b.id, "ctl")), b.id


def test_laser_chega_a_todo_chip_com_os_lambdas_certos(montado):
    _, _, nl = montado
    for ch in nl.por_tipo("chip_tradutor"):
        ligs = nl.ligacoes_de((ch.id, "laser"))
        fibras = [l.a[0] if l.b[0] == ch.id else l.b[0] for l in ligs if l.meio == "fibra"]
        assert fibras, ch.id
        for f in fibras:
            div = next(l.a[0] for l in nl.ligacoes_de((f, "a")))
            assert nl.blocos[div].tipo == "divisor"
            fonte = next(l.a[0] for l in nl.ligacoes_de((div, "in")))
            assert nl.blocos[fonte].tipo == "laser"
        precisa = {round(nl.blocos[v.id].atributos["lambda_nm"], 4)
                   for v in nl.filhos(ch.id) if v.tipo == "via_tx"}
        assert precisa <= set(ch.portas["laser"].atributos["lambdas_nm"]), ch.id


def test_bidirecional_tem_chave_e_detector_nas_duas_pontas(montado):
    _, _, nl = montado
    bidir = [s for s in nl.sinais.values() if len(s.sentidos) == 2 and s.padrao.startswith(("DDR5", "GDDR7"))]
    assert bidir
    for s in bidir[:50]:
        chaves = [b for b, _ in s.caminhos["ida"] if nl.blocos[b].tipo == "chave_sentido"]
        assert len(set(chaves)) == 2, s.id
        for ch in set(chaves):
            ctl = nl.ligacoes_de((ch, "sentido"))
            assert ctl and nl.blocos[ctl[0].a[0]].tipo == "detector_sentido"
            det = ctl[0].a[0]
            assert nl.blocos[det].atributos["entradas_ca"] > 0, det


def test_requisitos_honestos(montado):
    _, _, nl = montado
    req = {(r.peca, r.capacidade): r.provedor for r in nl.requisitos}
    for cap in ("PCH/DMI", "VR-SVID", "BCLK", "firmware-UEFI", "sequenciamento-PWROK"):
        assert ("CPU", cap) in req
    # o chipset é quem atende a CPU e o SPD; o FPGA só orquestra a base
    assert req[("CPU", "PCH/DMI")] == req[("CPU", "sequenciamento-PWROK")] == "ctl:pch"
    assert req[("CPU", "BCLK")] == "clk:pch"
    assert req[("DIMM0", "SPD/I3C")] == req[("DIMM1", "SPD/I3C")] == "ctl:pch"
    assert req[("CPU", "firmware-UEFI")] == req[("PCH", "firmware-ME")] == "flash:uefi"
    assert nl.blocos["flash:uefi"].atributos["regioes"] == ["descritor", "ME", "BIOS"]
    assert "PCH/DMI" not in nl.blocos["ctl:fpga"].atributos["capacidades"]
    assert req[("GPU", "memoria-compartilhada-CXL")] is None      # opcional: i5 e GPU sem CXL
    for ch in nl.por_tipo("chip_tradutor"):
        for cap in ("laser", "energia", "controle"):
            assert req.get((ch.id, cap)), (ch.id, cap)
        assert req[(ch.id, "controle")] == "ctl:fpga"
    # todo provedor declara o que oferece
    for r in nl.requisitos:
        if r.capacidade == "memoria-compartilhada-CXL":
            continue
        assert r.provedor and r.capacidade in nl.blocos[r.provedor].atributos.get("capacidades", ()), r


def test_dmi_vai_ao_pch_e_pcie4_aos_transceptores_do_fpga(montado):
    _, _, nl = montado
    pcie4 = [s for s in nl.sinais.values() if s.protocolo == "PCIe4" and s.papel != "REFCLK"]
    pecas = lambda s: {s.origem[0].split(":")[0], s.destino[0].split(":")[0]}
    dmi = [s for s in pcie4 if "DMI" in s.id]
    assert len(dmi) == 16 and all(pecas(s) == {"CPU", "PCH"} for s in dmi)
    assert {s.id.split("->")[0] for s in pcie4 if pecas(s) == {"CPU", "FPGA"}} >= {"CPU.PCIE4_TX0"}
    for s in pcie4:
        pontas = {s.origem[0], s.destino[0]}
        assert not any(p.startswith("FPGA:CTL_") for p in pontas), s.id
        assert all(nl.blocos[p].portas["e"].padrao == "PCIe4-CML" for p in pontas), s.id
        tipos = {nl.blocos[b].tipo for b, _ in s.caminhos["ida"]}
        assert "fibra" in tipos, s.id


def test_cada_entrada_de_relogio_tem_uma_fonte(montado):
    _, _, nl = montado
    fontes = {}
    for s in nl.sinais.values():
        if s.padrao == "HCSL-100M":
            fontes.setdefault(s.destino, []).append(s.origem)
    assert {d[0] for d in fontes} >= {"CPU:BCLK", "CPU:REFCLK_PEG", "GPU:REFCLK_PEG", "FPGA:REFCLK_XCVR"}
    assert all(len(v) == 1 and v[0][0] == "clk:pch" for v in fontes.values())
    # do gerador do chipset para a bola CLKOUT e dela por trilha
    s = next(x for x in nl.sinais.values() if x.destino == ("CPU:BCLK", "e"))
    assert [b for b, _ in s.caminhos["ida"]][:2] == ["clk:pch", "PCH:CLKOUT_BCLK"]
    assert "clk:ref" not in nl.blocos


def test_spd_do_dimm_ao_pch_por_trilha_com_um_pullup(montado):
    _, _, nl = montado
    for k, dimm in enumerate(("DIMM0", "DIMM1")):
        for pino in ("HSCL", "HSDA"):
            s = next(x for x in nl.sinais.values() if x.destino == (f"{dimm}:{pino}", "e"))
            assert s.origem == (f"PCH:SPD{k}_{pino}", "e"), s.id
            tipos = {nl.blocos[b].tipo for b, _ in s.caminhos["ida"]}
            # I3C de 1,0 V nas duas pontas: sem conversor, um pull-up só
            assert "conversor_nivel" not in tipos and "fibra" not in tipos, s.id
            assert f"pu:PCH:SPD{k}_{pino}" in nl.blocos and f"pu:{dimm}:{pino}" not in nl.blocos
        assert len(nl.sinais[next(k for k in nl.sinais if k.endswith(f"{dimm}.HSDA"))].sentidos) == 2


def test_celula_usa_a_chave_unica(montado):
    from modulos.sistema.celula import chave
    _, _, nl = montado
    ch = chave()
    for c in nl.por_tipo("celula"):
        assert c.atributos["r_on_ohm"] == ch.r_on_ohm and c.atributos["c_ff"] == ch.c_off_ff
        assert c.atributos["chave"] == ch.nome


def test_controle_hierarquico(montado):
    _, _, nl = montado
    fpga = nl.blocos["ctl:fpga"]
    for nome, p in fpga.portas.items():
        if p.dominio != "controle":
            continue
        disp = {(l.b if l.a == ("ctl:fpga", nome) else l.a)[0] for l in nl.ligacoes_de(("ctl:fpga", nome))}
        assert len(disp) <= 32, nome
        assert not any(nl.blocos[d].tipo == "celula" for d in disp), nome
    for c in nl.por_tipo("celula"):
        dono = nl.ligacoes_de((c.id, "ctl"))[0].a[0]
        assert dono.startswith("ctl:cel:"), c.id


def test_reguladores_cabem_a_carga(montado):
    _, _, nl = montado
    for rg in nl.por_tipo("regulador"):
        a = rg.atributos
        assert a["corrente_max_a"] >= a.get("carga_a", 0.0), rg.id


def test_grupo_de_controle_gddr7_numa_fibra(montado):
    _, _, nl = montado
    fibras = {}
    for s in nl.sinais.values():
        if s.protocolo == "GDDR7-32" and s.grupo.endswith("_CTRL"):
            fib = frozenset(b for b, _ in s.caminhos["ida"] if nl.blocos[b].tipo == "fibra")
            fibras.setdefault(s.grupo, set()).add(fib)
    assert fibras and all(len(v) == 1 for v in fibras.values())


def test_tradutores_sob_a_peca(montado):
    cfg, plano, _ = montado
    nl = construir(B.carregar(), cfg, plano, E.carregar("viavel"),
                   chave="rele_mems", posicionamento="sob_peca")
    chips = nl.por_tipo("chip_tradutor")
    assert all(c.atributos["camada"] == "fotonica" for c in chips)
    pecas = {p.nome: p for p in cfg.pecas}
    for ch in chips:
        xs = [q[0] for q in _contorno(pecas[ch.atributos["peca"]])]
        ys = [q[1] for q in _contorno(pecas[ch.atributos["peca"]])]
        x, y = ch.posicao
        assert min(xs) - 10 <= x <= max(xs) + 10 and min(ys) - 10 <= y <= max(ys) + 10, ch.id
    for i, a in enumerate(chips):
        for b in chips[i + 1:]:
            assert abs(a.posicao[0] - b.posicao[0]) >= 10 or abs(a.posicao[1] - b.posicao[1]) >= 10
    cel = nl.por_tipo("celula")[0]
    assert cel.atributos["chave"] == "rele_mems"
