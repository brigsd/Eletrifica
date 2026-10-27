import shutil

import pytest

pytest.importorskip("cairosvg")
pytest.importorskip("gerbonara")


@pytest.mark.lento
def test_cobre_reproduz_netlist_e_acha_defeito_do_q1():
    from modulos.pcb.check_copper import verificar

    r = verificar(log=lambda *a: None)
    assert r["ilhas"] == 43
    assert r["falsos_cortes"] == 0
    assert r["falsos_curtos"] == 0
    assert r["q1_source_pads"] == ["Q1_3", "R1_1"]
    assert r["q1_source_no_gnd"] is False


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="precisa do kicad-cli")
def test_esquematico_bate_com_netlist():
    from modulos.pcb.verify_netlist import main

    assert main() == 0
