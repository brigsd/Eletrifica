"""Linha de base do sistema atual: os números de referência, gerados por cálculo.

    python3 -m modulos.sistema.linha_de_base

Usa as mesmas funções que `simular.py` (sem regravar nada do que ele grava) e
grava `projetos/interconexao-optica/docs/linha-de-base.md`.
"""
from modulos.conexoes import contexto as CX
from modulos.conexoes.construir import construir
from modulos.conexoes.verificador import REGRAS, consumo, verificar
from modulos.dados import memoria_unificada as MU
from modulos.dados import roteamento as DR
from modulos.energia import vrm
from modulos.optica import controle_termico as CT
from modulos.optica import enlace as E
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M
from modulos.sistema.boot import emular
from modulos.sistema.simular import TEMPO_SONDA_US, _contatos, _perturbacao
from modulos.sistema.base import PROJETO

SAIDA = PROJETO / "docs" / "linha-de-base.md"
MODELO_LLM = "70B em 4 bits"


def calcular():
    """Refaz a montagem atual e devolve os números de referência, sem gravar nada."""
    m = B.carregar()
    pj = m.projeto
    ct = B.calcular_contatos(m.base, m.colocacoes)
    sond = M.sondar(m, ct)
    ids = M.identificar(m.base, sond)
    cfg = C.configurar(m.base, ids, sond)
    viavel = E.carregar(pj.get("config_optica", "viavel"))
    plano = DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"])
    chave = pj.get("chave_celula")
    dist = _contatos(m, cfg, chave, pj.get("cobre_plano_oz", 1))
    deg = vrm.simular_degrau()
    trav = CT.simular(viavel, _perturbacao, 2500.0, controle=True)

    nl = construir(m, cfg, plano, viavel, posicionamento=pj.get("tradutores", "sob_peca"), chave=chave)
    term = CX.simular_termico(m, cfg, nl, dist, pj.get("placa_fria_h_w_m2k"), pj.get("vias_termicas_fracao", 0.0))
    ctx = CX.montar(m, cfg, nl, term, [dist])
    rel = verificar(nl, ctx)
    co = consumo(nl, ctx)
    ex = emular(nl, sim={"sondagem_us": len(sond.celula) * TEMPO_SONDA_US,
                         "vrm_assentamento_us": deg["assentamento_us"],
                         "aneis_travamento_us": trav["travou_em_us"] or 200.0})

    cap = MU.capacidade()
    llm = {x["modelo"]: x for x in MU.llm()}[MODELO_LLM]
    return {
        "verificador": {"erros": len(rel.erros), "avisos": len(rel.violacoes) - len(rel.erros),
                        "por_regra": {r: (rel.contagem(r, "erro"), rel.contagem(r, "aviso")) for r in REGRAS}},
        "boot": {"ok": ex.ok, "parou_em": ex.parou_em and ex.parou_em["etapa"],
                 "pronto_ms": ex.tempos["Pronto"] / 1e3 if "Pronto" in ex.tempos else None},
        "consumo": {"total_w": co["total_w"], "pj_bit": co["pj_bit"],
                    "banda_tbps": co["banda_total_gbps"] / 1000, "referencia_pj_bit": co["referencia_pj_bit"]},
        "termico": {"base_max_c": float(term.regime.max()), "ambiente_c": term.t_amb,
                    "placa_fria": pj.get("placa_fria_h_w_m2k"), "vias_termicas": pj.get("vias_termicas_fracao", 0.0)},
        "llm": {"modelo": MODELO_LLM, "gb": llm["gb"], "banco_tok_s": llm["banco"],
                "comum_tok_s": llm["offload_cpu"], "cabe_no_banco": llm["cabe_no_banco"]},
        "banco": {"capacidade_gb": cap["banco_gb"], "banda_gpu_gbps": cap["banda_gpu_gbps"],
                  "banda_cpu_gbps": cap["banda_cpu_gbps"], "vram_nativa_gb": cap["vram_nativa_gb"]},
        "montagem": {"chave": chave, "tradutores": pj.get("tradutores"), "cobre_oz": pj.get("cobre_plano_oz")},
    }


def _sim(x):
    return "sim" if x else "não"


def tabela(R):
    v, b, c, t = R["verificador"], R["boot"], R["consumo"], R["termico"]
    L = ["# Linha de base: sistema atual", "",
         "Gerado por `python3 -m modulos.sistema.linha_de_base`. Não edite à mão.", "",
         f"Montagem: `montagem.json` (chave `{R['montagem']['chave']}`, tradutores "
         f"`{R['montagem']['tradutores']}`, cobre de {R['montagem']['cobre_oz']} oz).", "",
         "| Medida | Valor |", "|---|---|",
         f"| Erros do verificador | {v['erros']} |",
         f"| Avisos do verificador | {v['avisos']} |",
         f"| Boot emulado ficou pronto | {_sim(b['ok'])} |",
         f"| Tempo do boot emulado | {b['pronto_ms']:.0f} ms |" if b["pronto_ms"] is not None
         else f"| Tempo do boot emulado | parou em {b['parou_em']} |",
         f"| Consumo da interconexão | {c['total_w']:.1f} W |",
         f"| Energia por bit | {c['pj_bit']:.1f} pJ/bit (referência elétrica {c['referencia_pj_bit']:.1f}) |",
         f"| Banda da interconexão | {c['banda_tbps']:.2f} Tb/s |",
         f"| Temperatura máxima da base | {t['base_max_c']:.1f} °C |",
         f"| Teto do LLM {R['llm']['modelo']} ({R['llm']['gb']:.0f} GB), banco unificado | "
         f"{R['llm']['banco_tok_s']:.1f} tok/s{'' if R['llm']['cabe_no_banco'] else ' (não cabe)'} |",
         f"| Teto do mesmo LLM, PC comum (offload na CPU) | {R['llm']['comum_tok_s']:.1f} tok/s |",
         f"| Capacidade do banco unificado | {R['banco']['capacidade_gb']:.0f} GB |",
         f"| Banda do banco para a GPU | {R['banco']['banda_gpu_gbps']:.0f} GB/s |",
         f"| Banda do banco para a CPU | {R['banco']['banda_cpu_gbps']:.1f} GB/s |", "",
         "## Verificador por regra", "",
         "| Regra | Erros | Avisos |", "|---|---|---|"]
    for r, (e, a) in v["por_regra"].items():
        L.append(f"| {r} | {e} | {a} |")
    return "\n".join(L) + "\n"


def gerar():
    R = calcular()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(tabela(R), encoding="utf-8")
    return R


if __name__ == "__main__":
    gerar()
    print(SAIDA)
