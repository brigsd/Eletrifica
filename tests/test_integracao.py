import json
import math

import pytest

from modulos.sistema.base import PROJETO


@pytest.mark.lento
def test_simulacao_completa():
    from modulos.sistema.simular import executar

    r = executar()
    assert r["mapeamento"]["tipos_certos"] == r["mapeamento"]["pecas"] == 17
    assert not math.isfinite(r["optica"]["ajustada"]["fisico"]["margem_db"])
    assert r["optica"]["viavel"]["fisico"]["margem_db"] > 0
    assert all(c["erros"] == 0 for c in r["canais"].values())
    assert all(t["ok"] for t in r["treino"].values())
    assert r["treino_apos_mover"]["falhas"] > 0
    assert all(x["erros_bits"] == 0 for x in r["rajadas"].values())

    cena = json.loads((PROJETO / "web" / "cena.json").read_text())
    assert len(cena["pecas"]) == 17 and cena["fibras"] and len(cena["etapas"]) >= 8
    for arq in cena["texturas"].values():
        assert (PROJETO / arq).exists()
    assert (PROJETO / "docs" / "resultados.md").exists()
