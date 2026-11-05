"""Compara as alternativas da malha lado a lado e grava o relatório.

    python3 -m modulos.malha.comparar

Refaz a montagem real (sondagem, configuração, roteamento; ~20 s) e grava
`projetos/interconexao-optica/docs/malha-alternativas.md`.
"""
from modulos.dados import roteamento as DR
from modulos.malha import cenarios as CE
from modulos.optica import enlace as E
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M
from modulos.sistema.base import PROJETO

SAIDA = PROJETO / "docs" / "malha-alternativas.md"


def plano_real():
    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    sond = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, sond), sond)
    viavel = E.carregar(m.projeto.get("config_optica", "viavel"))
    return m.base, DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"])


def _custo_extra(ex):
    partes = []
    if ex.get("expressas"):
        partes.append(f"{ex['expressas']} expressas (até {ex['expressa_max_mm']:.0f} mm)")
    if ex.get("ligacoes_largas"):
        partes.append(f"{ex['ligacoes_largas']} ligações alargadas (+{ex['faixas_extras']:.0f} faixas)")
    if ex.get("caixa_gpu"):
        x0, y0, x1, y1 = ex["caixa_gpu"]
        partes.append(f"GPU em {(x1 - x0 + 1) * (y1 - y0 + 1)} segmentos")
    return "; ".join(partes) or "-"


def tabela(resultados):
    L = ["| Cenário | Saltos máx | Atraso máx (ns) | Potência (W) | Ocupação máx | R21 | R22 | "
         "GPU-MEM: saltos / atraso (ns) | Custo extra |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in resultados:
        s, ex = r["resumo"], r["extras"]
        L.append(f"| {r['nome']} | {s['saltos_max']} | {s['atraso_max_ns']:.2f} | {s['potencia_w']:.0f} | "
                 f"{s['ocupacao_max'] * 100:.0f} % | {s['erros_r21']} | {s['erros_r22']} | "
                 f"{ex['gpu_mem_saltos_max']} / {ex['gpu_mem_atraso_max_ns']:.2f} | {_custo_extra(ex)} |")
    return "\n".join(L)


def relatorio(resultados):
    return f"""# Malha: alternativas lado a lado

> Gerado por `python3 -m modulos.malha.comparar`. Não edite à mão.

**Custo e atraso ainda são estimativas** (`modulos/malha/custo.py`: retemporização por
salto, ps por mm, pJ por bit por salto). Os números reais estão em pesquisa; a tabela
vale para comparar as alternativas entre si, não como previsão.

Problema (ciclo 2): os enlaces de memória da GPU convergem nela e a rota XY empilha tudo
nas mesmas ligações; o pior caminho passa do orçamento da GDDR7 (10 ns). R21 conta fluxos
acima do orçamento do protocolo; R22 conta ligações acima de 100 %.

{tabela(resultados)}

## Como cada alternativa foi montada

""" + "\n".join(f"- **{r['nome']}**: {r['descricao']}." for r in resultados) + """

## Premissas das alternativas

- **Fibra gigante:** uma expressa por par origem-destino com 2 saltos ou mais, de capacidade
  igual à de uma ligação comum; custa um salto (retemporização + distância em linha reta).
- **Ligações largas:** a capacidade sobe em múltiplos da ligação comum, só onde passa de 100 %.
  "Faixas extras" é a soma do que foi acrescentado.
- **Peça grande:** a GPU ocupa a caixa dos segmentos dos seus tradutores; cada fluxo sai da
  face voltada para o destino. Saltos dentro da peça não custam atraso nem energia (premissa).
- **Rotas espalhadas:** metade do fluxo por XY, metade por YX; mesmos saltos, mesmo atraso.
- **Memória colada:** cada chip da GPU vai para um segmento vizinho do tradutor (fora da caixa
  da GPU, balanceando as ligações). A ponte continua onde está e passa a alcançar os chips
  novos, por isso o pior caso geral (coluna "Saltos máx") pode piorar: veja a coluna GPU-MEM,
  que é o caso de referência.
- As colunas R21/R22 são as contagens do verificador sobre cada cenário.
"""


def gerar():
    base, plano = plano_real()
    resultados = CE.todos(plano, base)
    SAIDA.write_text(relatorio(resultados), encoding="utf-8")
    return resultados


if __name__ == "__main__":
    gerar()
    print(f"gravado {SAIDA}")
