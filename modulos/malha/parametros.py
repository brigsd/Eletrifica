"""Parâmetros da malha, lidos de `projetos/interconexao-optica/malha.json`.

Um carregador único. Se o arquivo faltar, vale `FALLBACK` (os antigos valores de
`custo.py` e `montar.py`, todos ESTIMATIVAS). Testes rápidos passam `FALLBACK` (ou
um `Parametros` próprio) explicitamente, para não depender do JSON.

Sentido do orçamento: `orcamento_ns` é o atraso EXTRA DE IDA. O atraso de um fluxo
da malha (`ResultadoFluxo.atraso_ns`) é o de ida; os dois se comparam direto.
"""
import json
from dataclasses import dataclass, field, replace
from functools import lru_cache

from modulos.caminhos import PROJETOS

CAMINHO = PROJETOS / "interconexao-optica" / "malha.json"


@dataclass(frozen=True)
class Parametros:
    passo_mm: float = 25.0
    faixas_por_ligacao: int = 64
    gbps_por_faixa: float = 32.0
    retemporizacao_ns: float = 1.5
    ps_por_mm: float = 7.0
    pj_por_bit_salto: float = 2.0
    perda_db_por_mm: float = 0.020
    fator_perda_gddr7_pam3: float = 0.7
    salto_chave_ns: float = 0.15
    salto_chave_pj_por_bit: float = 0.3
    orcamento_perda_trecho_db: float = 16.0
    orcamento_ns: dict = field(default_factory=lambda: {
        "GDDR7-32": 10.0, "DDR5-4800": 15.0, "PCIe5": 100.0, "PCIe4": 100.0})
    orcamento_ns_padrao: float = 20.0
    skew_max_ps: dict = field(default_factory=lambda: {
        "GDDR7-32": 4.7, "DDR5-4800": 20.8, "PCIe5": 9.4, "PCIe4": 18.75})
    skew_treinavel_ps: dict = field(default_factory=lambda: {"DDR5-4800": 208.0})
    material: str = "fallback"
    origem: str = "fallback"

    def orcamento(self, protocolo):
        return self.orcamento_ns.get(protocolo, self.orcamento_ns_padrao)

    def perda_db_mm(self, protocolo=""):
        """dB/mm do cobre; a GDDR7 (PAM3) usa o fator de Nyquist menor."""
        f = self.fator_perda_gddr7_pam3 if str(protocolo).startswith("GDDR7") else 1.0
        return self.perda_db_por_mm * f

    def limite_skew_ps(self, protocolo):
        """Skew entre partes de um fluxo: o treinável, ou o residual máximo se o treinável faltar.

        None quando o protocolo não tem nenhum dos dois (sem checagem)."""
        t = self.skew_treinavel_ps.get(protocolo)
        return t if t is not None else self.skew_max_ps.get(protocolo)


FALLBACK = Parametros()


def _ler(caminho, material=None):
    d = json.loads(caminho.read_text(encoding="utf-8"))
    mat = material or d.get("material_padrao", "megtron6")
    return Parametros(
        passo_mm=float(d["passo_mm"]),
        faixas_por_ligacao=int(d["faixas_por_ligacao"]),
        gbps_por_faixa=float(d["gbps_por_faixa"]),
        retemporizacao_ns=float(d["retemporizacao_ns"]),
        ps_por_mm=float(d["ps_por_mm"][mat]),
        pj_por_bit_salto=float(d["pj_por_bit_salto"]),
        perda_db_por_mm=float(d["perda_db_por_mm"][mat]),
        fator_perda_gddr7_pam3=float(d.get("fator_perda_gddr7_pam3", 1.0)),
        salto_chave_ns=float(d.get("salto_chave_ns", FALLBACK.salto_chave_ns)),
        salto_chave_pj_por_bit=float(d.get("salto_chave_pj_por_bit", FALLBACK.salto_chave_pj_por_bit)),
        orcamento_perda_trecho_db=float(d.get("orcamento_perda_trecho_db", FALLBACK.orcamento_perda_trecho_db)),
        orcamento_ns={k: float(v) for k, v in d["orcamento_ns"].items()},
        skew_max_ps={k: float(v) for k, v in d["skew_max_ps"].items() if v is not None},
        skew_treinavel_ps={k: float(v) for k, v in d["skew_treinavel_ps"].items() if v is not None},
        material=mat,
        origem=str(caminho),
    )


@lru_cache(maxsize=None)
def _padrao(material):
    return _ler(CAMINHO, material) if CAMINHO.exists() else FALLBACK


def carregar(caminho=None, material=None):
    """Parâmetros do `malha.json` (ou `caminho`). Arquivo ausente -> `FALLBACK`."""
    if caminho is None:
        return _padrao(material)
    caminho = type(CAMINHO)(caminho)
    return _ler(caminho, material) if caminho.exists() else FALLBACK


def com(p=None, **mudancas):
    """Cópia dos parâmetros (ou dos carregados) com campos trocados."""
    return replace(p or carregar(), **mudancas)
