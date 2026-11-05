"""Compara as alternativas da malha lado a lado e grava o relatório.

    python3 -m modulos.malha.comparar

Refaz a montagem real (sondagem, configuração, roteamento; ~20 s) e grava
`projetos/interconexao-optica/docs/malha-alternativas.md`.
"""
from modulos.conexoes.construir import construir
from modulos.dados import roteamento as DR
from modulos.malha import calor as CA
from modulos.malha import cenarios as CE
from modulos.malha import parametros as PA
from modulos.optica import enlace as E
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M
from modulos.sistema.base import PROJETO
from modulos.sistema.simular import _contatos

SAIDA = PROJETO / "docs" / "malha-alternativas.md"


def montagem_real():
    """(montagem, configuração, plano, config óptica) do sistema atual."""
    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    sond = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, sond), sond)
    viavel = E.carregar(m.projeto.get("config_optica", "viavel"))
    return m, cfg, DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"]), viavel


def plano_real():
    m, cfg, plano, viavel = montagem_real()
    return m.base, plano


def contexto_termico(m, cfg, plano, viavel):
    """(montagem, configuração, netlist, contatos, placa fria, vias): o sistema atual, sem malha."""
    pj = m.projeto
    nl = construir(m, cfg, plano, viavel, posicionamento=pj.get("tradutores", "sob_peca"),
                   chave=pj.get("chave_celula"))
    dist = _contatos(m, cfg, pj.get("chave_celula"), pj.get("cobre_plano_oz", 1))
    return m, cfg, nl, dist, pj.get("placa_fria_h_w_m2k"), pj.get("vias_termicas_fracao", 0.0)


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


def _custo_chave(ex):
    n = ex.get("chave_n")
    if not n:
        return ""
    return "retimer a cada " + " / ".join(f"{v} ({k})" for k, v in n.items()) + " segmentos"


def tabela(resultados):
    L = ["| Cenário | Saltos máx | Atraso máx (ns) | Potência (W) | Ocupação máx | R21 | R22 | "
         "Perda/trecho máx (dB) · retimers | Desalinh. máx (ps) | R23 | R24 | T máx base (°C) | "
         "GPU-MEM: saltos / atraso (ns) | Custo extra |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in resultados:
        s, ex = r["resumo"], r["extras"]
        t = r.get("temperatura_max_c")
        c = _custo_extra(ex)
        extra = "; ".join(x for x in ("" if c == "-" else c, _custo_chave(ex)) if x) or "-"
        L.append(f"| {r['nome']} | {s['saltos_max']} | {s['atraso_max_ns']:.2f} | {s['potencia_w']:.0f} | "
                 f"{s['ocupacao_max'] * 100:.0f} % | {s['erros_r21']} | {s['erros_r22']} | "
                 f"{s['trecho_db_max']:.2f} · {s['retemporizacoes_max']} | {s['desalinhamento_max_ps']:.1f} | "
                 f"{s['erros_r23']} | {s['erros_r24']} | {'-' if t is None else f'{t:.0f}'} | "
                 f"{ex['gpu_mem_saltos_max']} / {ex['gpu_mem_atraso_max_ns']:.2f} | {extra} |")
    return "\n".join(L)


def _parametros_usados(p):
    return f"""| Parâmetro | Valor | Tipo |
|---|---:|---|
| Passo do segmento | {p.passo_mm:g} mm | decisão |
| Faixas por ligação (por sentido) × taxa | {p.faixas_por_ligacao} × {p.gbps_por_faixa:g} Gb/s | derivado |
| Retemporização (retimer PCIe 5, baixa latência) | {p.retemporizacao_ns:g} ns, {p.pj_por_bit_salto:g} pJ/bit | datasheet / estimativa (pJ) |
| Cobre ({p.material}) | {p.ps_por_mm:g} ps/mm, {p.perda_db_por_mm:g} dB/mm a 16 GHz | derivado |
| Fator de perda da GDDR7 (PAM3) | {p.fator_perda_gddr7_pam3:g} | **estimativa** |
| Salto por chave | {p.salto_chave_ns:g} ns, {p.salto_chave_pj_por_bit:g} pJ/bit | **estimativa, sem fonte** |
| Orçamento de perda por trecho | {p.orcamento_perda_trecho_db:g} dB (PCIe 5, placa-base) | spec p/ PCIe; **estimativa p/ GDDR7 e DDR5** |
| Orçamento de atraso de ida (GDDR7 / DDR5 / PCIe) | {p.orcamento('GDDR7-32'):g} / {p.orcamento('DDR5-4800'):g} / {p.orcamento('PCIe5'):g} ns | GDDR7 **estimativa**; DDR5 derivado; PCIe spec |
| Limite de skew entre faixas (GDDR7 / DDR5 / PCIe 5) | {p.limite_skew_ps('GDDR7-32'):g} / {p.limite_skew_ps('DDR5-4800'):g} / {p.limite_skew_ps('PCIe5'):g} ps | **estimativa** (DDR5: spec via patente) |"""


def relatorio(resultados, p=None, t_sem_malha=None):
    p = p or PA.carregar()
    base_t = ("" if t_sem_malha is None else
              f"Sem malha, a base chega a {t_sem_malha:.0f} °C (sistema atual: placa fria e vias térmicas). ")
    return f"""# Malha: alternativas lado a lado

> Gerado por `python3 -m modulos.malha.comparar`. Não edite à mão.

Os números vêm de `malha.json` (`docs/malha-parametros.md` traz as fontes). **O que ainda é
estimativa**, sem fonte pública: o salto por chave (0,15 ns, 0,3 pJ/bit), o orçamento de atraso
da GDDR7, o orçamento de perda e o skew de GDDR7 e DDR5, o fator de perda do PAM3 e o pJ/bit do
retimer. Vale para comparar as alternativas entre si, não como previsão.

{_parametros_usados(p)}

Problema (ciclo 2): os enlaces de memória da GPU convergem nela e a rota XY empilha tudo
nas mesmas ligações. Regras: R21 conta fluxos acima do orçamento de atraso de ida do protocolo;
R22, ligações acima de 100 %; R23, fluxos cuja perda acumulada entre retemporizações passa do
orçamento; R24, fluxos cujas faixas chegam com diferença de atraso acima do limite de skew.

{tabela(resultados)}

{base_t}A coluna de temperatura soma o calor da malha ao do sistema atual (tradutores, lasers, peças);
é conservador, porque os tradutores existentes e a retransmissão da malha são em parte o mesmo trabalho.
Cada ligação reparte a potência meio a meio entre seus dois segmentos.

## Como cada alternativa foi montada

""" + "\n".join(f"- **{r['nome']}**: {r['descricao']}." for r in resultados) + """

## Premissas das alternativas

- **Capacidade:** 32 faixas × 32 Gb/s por ligação (por sentido). Memória é half-duplex, então o
  pior caso é o fluxo inteiro num sentido só; é conservador em relação ao modelo antigo (64).
- **Fibra gigante:** uma expressa por par origem-destino com 2 saltos ou mais, de capacidade
  igual à de uma ligação comum; custa um salto (retemporização + distância em linha reta).
- **Ligações largas:** a capacidade sobe em múltiplos da ligação comum, só onde passa de 100 %.
  "Faixas extras" é a soma do que foi acrescentado.
- **Peça grande:** a GPU ocupa a caixa dos segmentos dos seus tradutores; cada fluxo sai da
  face voltada para o destino. Saltos dentro da peça não custam atraso nem energia (premissa).
- **Rotas espalhadas:** metade do fluxo por XY, metade por YX; mesmos saltos, mesmo atraso.
  Na grade uniforme as duas metades têm o mesmo comprimento e o desalinhamento sai 0; ele só
  aparece com trilhas de comprimento diferente (R24 cobre esse caso, testado à parte).
- **Memória colada:** cada chip da GPU vai para um segmento vizinho do tradutor (fora da caixa
  da GPU, balanceando as ligações). A ponte continua onde está e passa a alcançar os chips
  novos, por isso o pior caso geral (coluna "Saltos máx") pode piorar: veja a coluna GPU-MEM,
  que é o caso de referência.
- **Salto por chave:** cada salto só desvia o sinal por chave (atraso e energia da estimativa);
  um retimer (5 ns, 3 pJ/bit) entra sempre que a perda acumulada do cobre passaria de 16 dB.
  N = 16 dB / (passo × dB/mm): com Megtron 6 são 32 segmentos (GDDR7: 45), mais do que a base
  inteira tem de largura; por isso a rota nunca precisa de retimer no meio. Os retimers dos
  extremos (tradutores de origem e destino) já estão no caminho direto e não entram na conta.
  Com FR4 (0,06 dB/mm) N cai para 10 (GDDR7: 15) e o pior caminho, de 7 saltos (7,3 dB), ainda não precisa de retimer; a regra só morde em malhas maiores ou perda maior (testado à parte). A chave não tem perda de inserção modelada (sem fonte).
- As colunas R21 a R24 são as contagens do verificador sobre cada cenário.
"""


def gerar():
    m, cfg, plano, viavel = montagem_real()
    resultados = CE.todos(plano, m.base)
    ctx = contexto_termico(m, cfg, plano, viavel)
    t0 = CA.temperatura_max(*ctx)
    for r in resultados:
        r["temperatura_max_c"] = CA.temperatura_max(*ctx, av=r)
    SAIDA.write_text(relatorio(resultados, t_sem_malha=t0), encoding="utf-8")
    return resultados


if __name__ == "__main__":
    gerar()
    print(f"gravado {SAIDA}")
