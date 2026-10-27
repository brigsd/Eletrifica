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
    assert req[("DIMM0", "SPD/I3C")] is None
    for ch in nl.por_tipo("chip_tradutor"):
        for cap in ("laser", "energia", "controle"):
            assert req.get((ch.id, cap)), (ch.id, cap)
