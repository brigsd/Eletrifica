"""RTL do banco unificado: testes cocotb no Verilator (modulos/rtl/cocotb) e síntese no Yosys."""
import shutil

import pytest

from modulos.rtl import gerar, sim


def test_comandos_vh_bate_com_a_tabela():
    """O .vh versionado é o que a tabela de comandos.py gera."""
    assert (gerar.HDL / "comandos.vh").read_text(encoding="utf-8") == gerar.texto()


def _exigir_simulador():
    falta = sim.disponivel()
    if falta:
        pytest.skip(f"RTL não simulado: {falta}")


@pytest.mark.lento
@pytest.mark.parametrize("top", sorted(sim.BANCADA))
def test_cocotb(top):
    """Cada banco de testes cocotb roda inteiro e passa (ver modulos/rtl/cocotb/tb_*.py)."""
    _exigir_simulador()
    testes, falhas = sim.rodar(top)
    assert testes > 0 and falhas == 0, f"{top}: {falhas} de {testes} testes falharam (build/rtl/{top})"


@pytest.mark.lento
def test_sintese_bate_com_as_medidas():
    """Os níveis lógicos que o modelo usa (modulos/rtl/medidas.py) são os que o Yosys mede agora,
    e cada bloco do tradutor fecha num CK da GDDR7."""
    from modulos.rtl import medidas, sintese

    if sintese.disponivel():
        pytest.skip(f"síntese não rodada: {sintese.disponivel()}")
    r = sintese.sintetizar_tudo()
    assert {b: x["asic"]["niveis"] for b, x in r.items()} == medidas.NIVEIS
    for b in ("detector_rank", "seletor_rank", "mux_posse", "emulador_manutencao", "par_rank"):
        assert r[b]["asic"]["fecha_no_tck"], b


def test_constantes_vem_do_rtl():
    """O modelo usa o que o RTL mediu, não números soltos."""
    from modulos.conexoes import construir as C
    from modulos.dados import memoria_unificada as MU
    from modulos.rtl import medidas

    assert C.LATENCIA_RANK_PS == medidas.DETECTOR_RANK_PS
    assert MU.SELETOR_CA_PS == medidas.SELETOR_CA_PS and MU.SELETOR_DQ_PS == medidas.SELETOR_DQ_PS
    assert MU.RL_EXTRA_TCK == medidas.RL_EXTRA_TCK == 2
    assert MU.PONTE_LOGICA_NS == medidas.PONTE_MAPA_NS + MU.PONTE_FILA_NS
