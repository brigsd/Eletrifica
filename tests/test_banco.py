import copy
import random

import pytest

from modulos.conexoes.verificador import verificar
from modulos.dados import memoria_unificada as MU
from modulos.sistema.boot import emular


# ---------------------------------------------------------------- emulador
@pytest.fixture(scope="module")
def emulado():
    return MU.simular()


def test_gf2_inversa_desfaz_o_mapa():
    rng = random.Random(3)
    m = MU.mapa_cpu_aleatorio(rng)
    for _ in range(200):
        a = rng.randrange(0, 48 * 2**30, MU.LINHA_CPU_B)
        assert m.endereco(m.campos(a)) == a


def test_calibracao_aprende_os_dois_mapas(emulado):
    c = emulado["calibracao"]
    assert c["ok"] and c["erros_gpu"] == c["erros_cpu"] == 0
    assert c["rank_contiguo"]
    assert not emulado["rank_misturado"]          # mapa fora da família: a calibração avisa


def test_a_gpu_le_o_que_a_cpu_gravou_e_vice_versa(emulado):
    i = emulado["integridade"]
    assert i["linhas"] > 1000 and i["erros"] == 0
    assert i["linhas_volta"] > 100 and i["erros_volta"] == 0


def test_sem_descarregar_a_cache_a_gpu_le_dado_velho(emulado):
    s = emulado["sem_protocolo"]
    assert s["lidas_velhas"] == s["linhas"]


def test_fora_da_posse_e_recusado(emulado):
    p = emulado["posse"]
    assert p["gpu_recusadas"] == p["cpu_recusadas"] == 50


def test_capacidade_cabe_no_padrao_e_a_ponte_cabe_no_cl(emulado):
    cap, lat = emulado["capacidade"], emulado["latencia"]
    assert cap["banco_gb"] == 48 and cap["chip_visto_gb"] <= MU.CHIP_MAX_GDDR7_GB
    assert lat["cabe"] and lat["cl"] <= MU.CL_MAX_DDR5
    assert not MU.latencia_ponte(ida_ns=6.0)["cabe"]       # longe demais: passa do CL66


def test_llm_70b_cabe_e_roda_perto_da_banda_da_gpu(emulado):
    m = next(x for x in emulado["llm"] if x["modelo"] == "70B em 4 bits")
    assert m["cabe_no_banco"]
    assert m["banco"] > 8 * m["offload_cpu"] and m["banco"] > 10 * m["offload_pcie"]
    grande = next(x for x in emulado["llm"] if x["modelo"] == "120B em 4 bits")
    assert not grande["cabe_no_banco"]


# ---------------------------------------------------------------- netlist
def test_banco_na_netlist_sem_erro(netlist_real):
    rel = verificar(netlist_real)
    assert rel.contagem("R19-posse") == rel.contagem("R20-banco") == 0
    assert rel.contagem("R18-memoria-compartilhada", "aviso") == 0
    n = {t: len(netlist_real.por_tipo(t)) for t in ("seletor_rank", "mux_dono", "detector_rank")}
    assert n == {"seletor_rank": 480, "mux_dono": 480, "detector_rank": 12}
    ponte = netlist_real.blocos["ctl:ponte"].atributos
    assert ponte["cl_declarado"] <= MU.CL_MAX_DDR5 and ponte["janela_gb"] == 48


def test_rank_1_usa_a_luz_do_rank_0(netlist_real):
    nl = netlist_real
    for s in nl.sinais.values():
        if not s.grupo.endswith("_R1"):
            continue
        vias = lambda sig: {b for b, _ in sig.caminhos["ida"] if nl.blocos[b].tipo in ("via_tx", "via_rx")}
        lider = next(x for x in nl.sinais.values() if x.grupo == s.grupo[:-3] and
                     x.origem == s.origem and x.papel == s.papel and x.id != s.id
                     and s.caminhos["ida"][0] == x.caminhos["ida"][0]) if s.papel == "CA" else None
        if lider:
            assert vias(s) == vias(lider)
            break


def test_mux_sem_posse_e_erro(netlist_real):
    nl = copy.deepcopy(netlist_real)
    m = nl.por_tipo("mux_dono")[0]
    nl.ligacoes = [l for l in nl.ligacoes if (m.id, "sel") not in (l.a, l.b)]
    nl._viz[(m.id, "sel")] = []
    assert any(m.id in v.mensagem for v in verificar(nl).erros if v.regra == "R19-posse")


def test_cl_declarado_curto_e_chip_grande_demais_sao_erro(netlist_real):
    nl = copy.deepcopy(netlist_real)
    a = nl.blocos["ctl:ponte"].atributos
    a["cl_declarado"] = MU.CL_DDR5_NATIVO
    a["chip_real_gb"] = 4.0                      # 2 x 32 Gb: a GPU teria de ver 64 Gb
    msgs = [v.mensagem for v in verificar(nl).erros if v.regra == "R20-banco"]
    assert any("CL" in m for m in msgs) and any("64 Gb" in m for m in msgs)


@pytest.mark.lento
def test_boot_calibra_o_banco_e_para_sem_a_ponte(netlist_real):
    ex = emular(netlist_real)
    assert ex.ok and "Banco unificado" in ex.tempos
    assert ex.tempos["Banco unificado"] > ex.tempos["PCIe e GDDR7"]
    ex = emular(netlist_real, falhas=("req:GPU:memoria-compartilhada",))
    assert not ex.ok and ex.parou_em["etapa"] == "Banco unificado"
