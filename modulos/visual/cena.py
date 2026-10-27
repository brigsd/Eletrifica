"""Exporta a cena do visualizador 3D: base, células, peças, fibras e linha do tempo.

Tudo sai da mesma simulação que gera o relatório: o mapeamento decide onde
cada peça está, a configuração decide a cor de cada célula, e as camadas de
corrente e temperatura vêm dos simuladores de energia e térmico.
"""
import json

import numpy as np
from PIL import Image

from modulos.componentes import obter
from modulos.sistema.base import DESLIGADA, F_ENERGIA, F_SINAL, F_TERRA, PROJETO

WEB = PROJETO / "web"

CORES_CELULA = {
    "livre": (32, 38, 46), "contato": (70, 78, 88), DESLIGADA: (70, 78, 88),
    F_SINAL: (57, 197, 187), F_ENERGIA: (232, 131, 58), F_TERRA: (108, 122, 137),
}

DESCRICAO = {
    "i5-13600KF": "Processador. Mantém o controle e fala os protocolos nativos (DDR5 e "
                  "PCIe). Recebe o núcleo de até 200 A por centenas de células de energia, "
                  "vindas do regulador multifásico ao lado.",
    "DDR5-DIMM": "Memória principal. Recebe 5 V estáveis e o regulador interno do módulo "
                 "(PMIC) faz o ajuste fino. Os 94 sinais do canal vão por luz até a CPU.",
    "GPU": "Placa de vídeo. A potência do núcleo chega pelo cabo da fonte; pela base "
           "passam terra, 3,3 V auxiliar e os sinais: PCIe 5.0 x16 até a CPU e 384 bits "
           "de GDDR7 até os chips de memória.",
    "GDDR7": "Chip de memória de vídeo, 32 bits a 32 Gb/s por pino em PAM3. Cada pino de "
             "dados ganha seu próprio canal óptico até a GPU.",
    "FPGA": "Orquestrador. Sonda as células, identifica as peças, configura cada célula, "
            "entrega firmware UEFI, relógios, sequência de energização e as funções de "
            "chipset que a CPU exige para ligar.",
}


def _png(caminho, rgb):
    Image.fromarray(np.ascontiguousarray(rgb[::-1]).astype(np.uint8)).save(caminho, optimize=True)


def textura_funcoes(base, configuracao, contato=None):
    rgb = np.empty((base.ny, base.nx, 3), np.uint8)
    rgb[:] = CORES_CELULA["livre"]
    if contato is not None:
        rgb[contato] = CORES_CELULA["contato"]
    for f in (F_SINAL, F_ENERGIA, F_TERRA):
        rgb[configuracao.funcao == f] = CORES_CELULA[f]
    return rgb


def textura_sondagem(base, celulas_em_contato):
    rgb = np.empty((base.ny, base.nx, 3), np.uint8)
    rgb[:] = CORES_CELULA["livre"]
    iy, ix = celulas_em_contato // base.nx, celulas_em_contato % base.nx
    rgb[iy, ix] = (220, 228, 236)
    return rgb


def textura_escala(base, valores, vmin, vmax, mascara=None, paleta="calor"):
    """Mapa contínuo; células fora da máscara ficam na cor da base livre."""
    v = np.clip((np.asarray(valores, float) - vmin) / max(vmax - vmin, 1e-12), 0, 1)
    if paleta == "calor":
        pontos = np.array([[25, 45, 80], [40, 110, 170], [240, 200, 70], [230, 80, 40]], float)
    else:
        pontos = np.array([[30, 40, 60], [60, 160, 200], [250, 240, 200]], float)
    x = v * (len(pontos) - 1)
    i = np.minimum(x.astype(int), len(pontos) - 2)
    f = (x - i)[..., None]
    rgb = (pontos[i] * (1 - f) + pontos[i + 1] * f).astype(np.uint8)
    if rgb.shape[:2] != (base.ny, base.nx):
        rgb = np.array(Image.fromarray(rgb).resize((base.nx, base.ny), Image.BILINEAR))
    if mascara is not None:
        rgb[~mascara] = CORES_CELULA["livre"]
    return rgb


def pecas(configuracao, metricas=None):
    out = []
    for p in configuracao.pecas:
        cat = obter(p.tipo)
        out.append({
            "nome": p.nome, "tipo": p.tipo, "titulo": cat.nome,
            "x": round(p.x, 3), "y": round(p.y, 3), "rot": round(p.rot, 3),
            "largura": cat.largura, "profundidade": cat.profundidade, "altura": cat.altura,
            "cor": cat.cor, "pinos": cat.contagem(),
            "trilhos": [{"nome": t.nome, "tensao": t.tensao, "corrente_max": t.corrente_max,
                         "origem": t.origem} for t in cat.trilhos.values()],
            "descricao": DESCRICAO.get(p.tipo, ""),
            "metricas": (metricas or {}).get(p.nome, {}),
        })
    return out


def exportar(base, configuracao, texturas, fibras=(), etapas=(), resumo=None, metricas=None,
             extras=None):
    """`texturas`: nome -> array RGB (ny, nx, 3). Grava PNGs e cena.json em web/."""
    WEB.mkdir(parents=True, exist_ok=True)
    nomes = {}
    for nome, rgb in texturas.items():
        arq = f"celulas-{nome}.png"
        _png(WEB / arq, rgb)
        nomes[nome] = f"web/{arq}"
    cena = {
        "base": {"largura": base.largura, "profundidade": base.profundidade,
                 "espessura": 2.0, "passo_celula": base.passo},
        "texturas": nomes,
        "pecas": pecas(configuracao, metricas),
        "fibras": list(fibras),
        "etapas": list(etapas),
        "resumo": resumo or {},
        **(extras or {}),
    }
    (WEB / "cena.json").write_text(json.dumps(cena, ensure_ascii=False, separators=(",", ":")))
    return cena
