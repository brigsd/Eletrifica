"""Simulação completa: liga a base do zero e grava relatório e cena 3D.

    python3 -m modulos.sistema.simular

Segue a ordem do conceito: sondagem, identificação, configuração, energia,
travamento dos anéis, relógios, treinamento de memória, enlaces. Cada etapa
usa o resultado da anterior; nada é desenhado à mão.
"""
import copy
import math
import re

import numpy as np

from modulos.conexoes.construir import construir
from modulos.conexoes import contexto as CX
from modulos.conexoes.verificador import REGRAS, aquecedores, consumo, verificar
from modulos.dados import comandos as CMD
from modulos.dados import ddr5 as DDR
from modulos.dados import emulador as DE
from modulos.dados import pcie as PCIE
from modulos.dados import latencia as DL
from modulos.dados import roteamento as DR
from modulos.energia import arvore, contatos, protecao, vrm
from modulos.optica import controle_termico as CT
from modulos.optica import enlace as E
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import mapeamento as M
from modulos.sistema.base import F_ENERGIA, PROJETO
from modulos.sistema.boot import emular
from modulos.sistema.celula import chave as chave_celula
from modulos.termico import difusao
from modulos.visual import cena as V
from modulos.visual import graficos as G

DOCS = PROJETO / "docs"
TEMPO_SONDA_US = 2.0          # por célula
TIPO_FIBRA = {"DDR5-4800": "DDR5", "GDDR7-32": "GDDR7", "PCIe5": "PCIe", "PCIe4": "AUX"}
R_FOLHA_1OZ_MOHM = 0.5 / 2          # dois planos de 1 oz em paralelo, como o modelo de energia usa

# do conceito até o projeto atual: cada linha muda uma decisão
CENARIOS = (   # nome, tradutores, chave da célula, cobre do plano (oz), placa fria (W/m²K; None = ar)
    ("conceito: tradutor ao lado, célula com MOSFET", "ao_lado", "mosfet_potencia", 1, None),
    ("tradutor sob a peça", "sob_peca", "mosfet_potencia", 1, None),
    ("+ relé MEMS na célula", "sob_peca", "rele_mems", 1, None),
    ("+ plano de energia com 2 oz", "sob_peca", "rele_mems", 2, None),
    ("+ placa fria sob a base", "sob_peca", "rele_mems", 2, 1000),
)


def _canal(cfg, gbps, simbolo):
    c = copy.deepcopy(cfg)
    c["gbps_por_pino"] = gbps
    return E.simular_canal(c, simbolo=simbolo)


def _perturbacao(t_us, salto_k=10.0, tau_us=200.0, inicio_us=600.0):
    return 0.0 if t_us < inicio_us else salto_k * (1 - math.exp(-(t_us - inicio_us) / tau_us))


def _fontes_calor(nl):
    """Calor que a interconexão dissipa na própria base: chips tradutores e lasers."""
    out = []
    for c in nl.por_tipo("chip_tradutor"):
        p = float(c.atributos.get("potencia_w", 0.0)) + sum(
            float(f.atributos.get("potencia_w", 0.0) or 0.0) for f in nl.filhos(c.id))
        out.append((c.posicao[0], c.posicao[1], c.atributos["largura_mm"], c.atributos["profundidade_mm"], p))
    for l in nl.por_tipo("laser"):
        out.append((l.posicao[0], l.posicao[1], 40.0, 25.0, float(l.atributos["potencia_eletrica_w"])))
    return out


def _termico(m, cfg, nl, dist, placa_fria):
    return difusao.simular(m.base, cfg, m.zonas, perdas_contatos_w=dist["perdas_w"],
                           fontes_extra=_fontes_calor(nl), h_inferior=placa_fria)


def _contatos(m, cfg, nome_chave, cobre_oz):
    d = contatos.distribuir(m.base, cfg, zona_vrm=m.zonas["vrm_cpu"],
                            r_on_mohm=chave_celula(nome_chave).r_on_ohm * 1e3,
                            r_folha_mohm=R_FOLHA_1OZ_MOHM / cobre_oz)
    d["chave"] = nome_chave
    return d


def _fibras_netlist(nl):
    """Fibras de dados (entre chips tradutores) e de laser (do módulo ao chip)."""
    out = []
    for k, f in enumerate(nl.por_tipo("fibra")):
        a = f.atributos
        rota = [(float(x), float(y)) for x, y in a.get("rota", [])]
        if len(rota) < 2:
            ponta = [nl.blocos[b].posicao for b in (a.get("de"), a.get("para")) if b in nl.blocos]
            rota = [(float(x), float(y)) for x, y in ponta]
        if len(rota) < 2:
            continue
        laser = f.id.startswith("fibl")
        alto = (2.5 + 0.3 * (k % 6)) if laser else (5.0 + 0.8 * (k % 14))
        pts = [[*rota[0], 1.0]] + [[x, y, alto] for x, y in rota[1:-1]] + [[*rota[-1], 1.0]]
        if len(pts) == 2:
            pts.insert(1, [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2, alto])
        out.append({"id": f.id, "tipo": "LASER" if laser else TIPO_FIBRA.get(a.get("protocolo"), "AUX"),
                    "de": a.get("de"), "para": a.get("para"),
                    "canais": len(a.get("lambdas_nm", [])), "raio": 0.35 if laser else 0.7,
                    "comprimento_mm": round(float(a.get("comprimento_mm", 0.0)), 1),
                    "pontos": [[round(c, 2) for c in p] for p in pts]})
    return out


def _cadeia_netlist(nl):
    """O que fica entre o pino e a fibra: chips tradutores, lasers e trilhas da base."""
    chips = []
    for c in nl.por_tipo("chip_tradutor"):
        a = c.atributos
        vias = [f for f in nl.filhos(c.id) if f.tipo in ("via_tx", "via_rx")]
        chips.append({"id": c.id, "peca": a.get("peca"), "x": round(c.posicao[0], 2),
                      "y": round(c.posicao[1], 2), "largura": a.get("largura_mm", 10.0),
                      "profundidade": a.get("profundidade_mm", 10.0),
                      "camada": a.get("camada", "superficie"), "vias": len(vias),
                      "vias_max": a.get("vias_max"), "potencia_w": round(float(a.get("potencia_w", 0.0)), 2)})
    lasers = [{"id": b.id, "x": round(b.posicao[0], 2), "y": round(b.posicao[1], 2),
               "linhas": b.atributos.get("linhas_acesas"),
               "potencia_w": b.atributos.get("potencia_eletrica_w")} for b in nl.por_tipo("laser")]
    trilhas = []
    for t in nl.por_tipo("trilha"):
        a = t.atributos
        if t.posicao is None or a.get("ate") is None:
            continue
        trilhas.append([round(float(t.posicao[0]), 2), round(float(t.posicao[1]), 2),
                        round(float(a["ate"][0]), 2), round(float(a["ate"][1]), 2),
                        1 if a.get("camada") == "sinal" else 0])
    return {"tradutores": chips, "lasers": lasers, "trilhas": trilhas}


def executar():
    R = {}
    m = B.carregar()

    # 1-3. sondagem, identificação, configuração ----------------------------
    ct = B.calcular_contatos(m.base, m.colocacoes)
    sond = M.sondar(m, ct)
    ids = M.identificar(m.base, sond)
    conf = M.conferir(m, ids)
    cfg = C.configurar(m.base, ids, sond)
    recusa = protecao.pode_energizar(int(sond.celula[0]), {"configuracao": None})
    R["mapeamento"] = {
        "celulas_em_contato": int(len(sond.celula)), "pontes": int(len(sond.pontes)),
        "tempo_sondagem_ms": len(sond.celula) * TEMPO_SONDA_US / 1e3,
        "pecas": len(ids), "tipos_certos": sum(l["tipo_real"] == l["tipo_achado"] for l in conf),
        "erro_max_mm": max(l["erro_mm"] for l in conf),
        "erro_max_graus": max(abs(l["erro_graus"]) for l in conf),
        "acerto_min": min(l["acerto"] for l in conf), "margem_min": min(l["margem"] for l in conf),
        "configuracao": cfg.resumo(), "recusa_sem_identificacao": recusa,
    }

    # 4-5. energia ------------------------------------------------------------
    R["arvore"] = arvore.balanco(cfg)
    pj = m.projeto
    dist = _contatos(m, cfg, pj.get("chave_celula"), pj.get("cobre_plano_oz", 1))
    deg = vrm.simular_degrau()
    curto = protecao.simular_curto()
    R["contatos"] = {k: dist[k] for k in ("pinos", "celulas", "pino_max_a", "pino_medio_a",
                                          "pinos_acima_1a", "celula_max_a", "queda_ir_mv", "perdas_w")}
    R["vrm"] = {k: deg[k] for k in ("undershoot_mv", "queda_total_mv", "assentamento_us",
                                    "desbalanco_fase_pct", "erro_reta_carga_mv", "eficiencia")}
    R["curto"] = {k: curto[k] for k in ("pico_a", "tempo_disparo_ns", "energia_chave_uj")}

    # 7. óptica -----------------------------------------------------------------
    cfgs = {n: E.carregar(n) for n in ("original", "ajustada", "viavel")}
    R["optica"] = {n: {"simples": E.calculo_simples(c), "fisico": E.orcamento(c)}
                   for n, c in cfgs.items()}
    R["varredura"] = E.varrer(cfgs["ajustada"])
    viavel = cfgs[pj.get("config_optica", "viavel")]
    canais = {"GDDR7": _canal(viavel, 32.0, "PAM3"), "PCIe5": _canal(viavel, 32.0, "NRZ"),
              "DDR5": _canal(viavel, 4.8, "NRZ")}
    R["canais"] = {k: {"ber": c.ber_estimada, "erros": c.erros_contados, "simbolos": c.simbolos,
                       "atraso_ps": c.atraso_ps, "olho_ui": c.largura_olho_ui, "rlm": c.rlm}
                   for k, c in canais.items()}
    R["janela"] = {s: CT.janela_termica(viavel, simbolo=s) for s in ("NRZ", "PAM3")}
    trav = CT.simular(viavel, _perturbacao, 2500.0, controle=True)
    livre = CT.simular(viavel, _perturbacao, 2500.0, controle=False)
    depois = trav["tempo_us"] > 1500
    R["travamento"] = {"travou_em_us": trav["travou_em_us"],
                       "perdas": trav["perdas_de_travamento"],
                       "erro_max_travado_pm": float(np.abs(trav["erro_pm"][trav["tempo_us"] > (trav["travou_em_us"] or 0) + 50]).max()),
                       "erro_final_pm": float(np.abs(trav["erro_pm"][depois]).mean()),
                       "erro_sem_controle_pm": float(np.abs(livre["erro_pm"]).max())}

    # 8-10. dados ---------------------------------------------------------------
    plano = DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"])
    plano_ded = DR.rotear(cfg, canais_por_fibra=viavel["canais_por_fibra"],
                          modo_bidirecional="dedicado")
    eo = max(c["atraso_ps"] for c in R["canais"].values())
    lat = DL.calcular(plano, atraso_eletro_optico_ps=eo)
    R["roteamento"] = {"comutado": plano.totais(), "dedicado": plano_ded.totais()}
    R["latencia"] = {e.enlace: {"dados_ps": e.atraso_dados_ps, "trilha_ps": e.trilha_mesma_posicao_ps,
                                "trilha_tipica_ps": e.trilha_tipica_ps,
                                "desalinhamento_ps": e.desalinhamento_grupo_ps,
                                "comutacao": e.comutacao}
                     for e in lat.enlaces}
    olho = canais["DDR5"].largura_olho_ui
    treinos = {d: DE.treinar(plano, lat, f"CPU-{d}", largura_olho_ui=olho) for d in ("DIMM0", "DIMM1")}
    movido = copy.deepcopy(cfg)
    movido.por_nome("DIMM0").y += 10.0
    p2 = DR.rotear(movido, canais_por_fibra=viavel["canais_por_fibra"])
    quebra = DE.verificar(treinos["DIMM0"], p2, DL.calcular(p2, atraso_eletro_optico_ps=eo), olho)
    modelo_ddr5 = DE.canal_ideal(canais["DDR5"].ber_estimada)
    modelo_g7 = DE.canal_ideal(canais["GDDR7"].ber_estimada)
    dados = bytes(range(64))
    raj = {"DDR5 escrita": DE.rajada_ddr5(plano, "CPU-DIMM0", "escrita", dados, modelo=modelo_ddr5),
           "DDR5 leitura": DE.rajada_ddr5(plano, "CPU-DIMM1", "leitura", dados, modelo=modelo_ddr5),
           "GDDR7 escrita": DE.rajada_gddr7(plano, plano.enlaces[2].id, "escrita", dados[:48],
                                            modelo=modelo_g7)}
    R["treino"] = {d: {"ok": t.convergiu, "pistas": len(t.pistas),
                       "janela_min_taps": min(p["janela_taps"] for p in t.pistas.values()),
                       "passo_ps": t.passo_ps} for d, t in treinos.items()}
    R["treino_apos_mover"] = quebra
    R["rajadas"] = {k: {"erros_bits": r.erros_bits, "sentido": r.sentido_decodificado}
                    for k, r in raj.items()}

    # 11. conexões: a netlist do sistema inteiro, o verificador e o boot -------------
    R["conexoes"] = []
    for nome, pos, ch, oz, placa in CENARIOS:
        nl = construir(m, cfg, plano, viavel, posicionamento=pos, chave=ch)
        d = _contatos(m, cfg, ch, oz)
        tc = _termico(m, cfg, nl, d, placa)
        rel = verificar(nl, CX.montar(m, cfg, nl, tc, [d]))
        exemplos = {}
        for v in rel.erros:
            exemplos.setdefault(v.regra, v.mensagem)
        R["conexoes"].append({"nome": nome, "posicionamento": pos, "chave": ch, "cobre_oz": oz,
                              "placa_fria": placa, "base_max_c": float(tc.regime.max()),
                              "por_regra": {k: rel.contagem(k, "erro") for k in REGRAS},
                              "erros": len(rel.erros), "exemplos": exemplos})
    nl = construir(m, cfg, plano, viavel, posicionamento=pj.get("tradutores", "sob_peca"),
                   chave=pj.get("chave_celula"))
    term = _termico(m, cfg, nl, dist, pj.get("placa_fria_h_w_m2k"))
    R["termico"] = {"max_c": float(term.regime.max()), "amb_c": term.t_amb,
                    "calor_interconexao_w": sum(f[4] for f in _fontes_calor(nl)),
                    "placa_fria": pj.get("placa_fria_h_w_m2k"),
                    "tradutores": {k: v["regime_c"] for k, v in term.tradutores.items()}}
    ctx = CX.montar(m, cfg, nl, term, [dist])
    rel = verificar(nl, ctx)
    aq = aquecedores(nl, ctx)
    R["consumo"] = consumo(nl, ctx)
    R["aquecedores"] = {"frio_w": sum(a["aquecedor_frio_w"] for a in aq.values()),
                        "sem_faixa": sum(not a["cobre"] for a in aq.values()),
                        "pede_max_nm": max(a["pede_nm"] for a in aq.values()),
                        "faixa_nm": next(iter(aq.values()))["faixa_nm"]}
    R["netlist"] = {**nl.resumo(), "erros": len(rel.erros), "avisos": len(rel.violacoes) - len(rel.erros),
                    "por_regra": {k: rel.contagem(k, "erro") for k in REGRAS}}
    ex = emular(nl, sim={"sondagem_us": R["mapeamento"]["tempo_sondagem_ms"] * 1e3,
                         "vrm_assentamento_us": deg["assentamento_us"],
                         "aneis_travamento_us": trav["travou_em_us"] or 200.0})
    R["protocolos"] = {
        "decodificacao": {p: {"decodifica": CMD.necessarios(p), "copia": CMD.copiados_sem_ler(p),
                              "latencia_ps": CMD.latencia_decodificacao_ps(p), "janela_ps": CMD.janela_ps(p)}
                          for p in ("DDR5-4800", "GDDR7-32")},
        "ddr5_espelhando": DDR.resumo(DDR.simular(espelhar=True)),
        "ddr5_sem_espelho": DDR.resumo(DDR.simular(espelhar=False)),
        "pcie": PCIE.avaliar_netlist(nl)}
    R["boot"] = {"ok": ex.ok, "parou_em": ex.parou_em, "tempos_ms": {k: v / 1e3 for k, v in ex.tempos.items()}}

    # cena 3D ---------------------------------------------------------------------
    corrente = dist["mapa_corrente"]
    tx = {"sondagem": V.textura_sondagem(m.base, sond.celula),
          "funcoes": V.textura_funcoes(m.base, cfg),
          "corrente": V.textura_escala(m.base, corrente, 0.0, float(corrente.max()),
                                       mascara=cfg.funcao == F_ENERGIA),
          "temperatura": V.textura_escala(m.base, term.regime, term.t_amb, float(term.regime.max()))}
    V.exportar(m.base, cfg, tx, fibras=_fibras_netlist(nl), etapas=_virgulas(_etapas(ex, R)),
               resumo=_virgulas(_resumo(R)), metricas=_virgulas(_metricas(R, cfg, dist)),
               extras=_cadeia_netlist(nl))

    # relatório -------------------------------------------------------------------
    DOCS.mkdir(exist_ok=True)
    _graficos(canais["GDDR7"], trav, livre, deg)
    (DOCS / "resultados.md").write_text(_relatorio(R))
    return R


def _etapas(ex, R):
    """As etapas vêm do boot emulado; aqui só entram os números das outras simulações."""
    extra = {
        "Núcleo da CPU": f" A 200 A o pino mais carregado leva {R['contatos']['pino_max_a']:.2f} A.",
        "Anéis travados": f" Erro residual de sintonia {R['travamento']['erro_final_pm']:.2f} pm.",
        "Pronto": f" Base a até {R['termico']['max_c']:.0f} °C em carga máxima.",
    }
    out = []
    for e in ex.etapas:
        e = dict(e)
        e["descricao"] = e["descricao"] + extra.get(e["nome"], "")
        e["energizadas"] = sorted(set(e.get("energizadas", [])))
        out.append(e)
    return out


def _ber(v):
    return "< 1e-30" if v < 1e-30 else f"{v:.1e}"


def _natural(s):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


def _virgula(texto):
    """Vírgula decimal fora de trechos de código."""
    partes = texto.split("`")
    for i in range(0, len(partes), 2):
        partes[i] = re.sub(r"(?<=\d)\.(?=\d)", ",", partes[i])
    return "`".join(partes)


def _virgulas(obj):
    if isinstance(obj, str):
        return _virgula(obj)
    if isinstance(obj, dict):
        return {k: _virgulas(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_virgulas(v) for v in obj]
    return obj


NOME_CFG = {"original": "original", "ajustada": "ajustada", "viavel": "viável"}


def _estado(ok):
    return "good" if ok else "bad"


def _resumo(R):
    o = R["optica"]
    v = R["canais"]
    return {
        "Peças identificadas": {"valor": f"{R['mapeamento']['tipos_certos']}/{R['mapeamento']['pecas']}",
                                "estado": _estado(R['mapeamento']['tipos_certos'] == R['mapeamento']['pecas'])},
        "Margem (doc., ajustada)": f"{o['ajustada']['simples']['margem_db']:+.1f} dB",
        "Margem física, 64 λ/fibra": {"valor": "não fecha", "estado": "bad"},
        "Margem física, viável": {"valor": f"{o['viavel']['fisico']['margem_db']:+.1f} dB",
                                  "estado": _estado(o['viavel']['fisico']['margem_db'] > 0)},
        "BER GDDR7 (PAM3)": _ber(v["GDDR7"]["ber"]),
        "Atraso eletro-óptico": f"{max(c['atraso_ps'] for c in v.values()):.0f} ps",
        "Fibras (comutado)": R["roteamento"]["comutado"]["fibras"],
        "Pinos > 1 A (CPU)": {"valor": R["contatos"]["pinos_acima_1a"],
                              "estado": _estado(R["contatos"]["pinos_acima_1a"] == 0)},
        "Base, máx.": f"{R['termico']['max_c']:.0f} °C",
        "Treino DDR5": {"valor": "converge" if all(t["ok"] for t in R["treino"].values()) else "falha",
                        "estado": _estado(all(t["ok"] for t in R["treino"].values()))},
        "Verificador de conexões": {"valor": f"{R['netlist']['erros']} erros",
                                    "estado": _estado(R["netlist"]["erros"] == 0)},
        "Boot emulado": {"valor": (f"pronto em {R['boot']['tempos_ms']['Pronto']:.0f} ms" if R["boot"]["ok"]
                                   else f"para em {R['boot']['parou_em']['etapa']}"),
                         "estado": _estado(R["boot"]["ok"])},
    }


def _metricas(R, cfg, dist):
    out = {}
    temps = R["termico"]["tradutores"]
    for p in cfg.pecas:
        d = {}
        if p.nome in temps:
            d["tradutor"] = f"{temps[p.nome]:.1f} °C em carga máxima"
        lat = [(k, v) for k, v in R["latencia"].items() if p.nome in k.split("-")]
        for k, v in lat[:4]:
            d[f"enlace {k}"] = f"{v['dados_ps']:.0f} ps (trilha: {v['trilha_ps']:.0f} ps)"
        out[p.nome] = d
    c = R["contatos"]
    out.setdefault("CPU", {}).update({
        "VCCIN a 200 A": f"pino máx. {c['pino_max_a']:.2f} A · {c['pinos_acima_1a']} acima de 1 A",
        "queda IR": f"{c['queda_ir_mv']:.1f} mV · perdas {c['perdas_w']:.1f} W"})
    return out


def _graficos(g7, trav, livre, deg):
    o = g7.olho
    t = np.array(o["t_ui"])
    tr = o["amostras_ua"][:120]
    svg = G.linhas([("", t, y) for y in tr], "Olho GDDR7 em PAM3 (configuração viável)",
                   "tempo (UI)", "corrente no receptor (µA)", alpha=0.18, espessura=1.2)
    (DOCS / "olho-gddr7.svg").write_text(svg)

    ms = lambda s: s["tempo_us"] / 1000
    svg = G.linhas([("com controle", ms(trav), trav["erro_pm"]),
                    ("sem controle", ms(livre), livre["erro_pm"])],
                   "Erro de sintonia do anel com +10 K de aquecimento local",
                   "tempo (ms)", "erro (pm)", y_lim=(-100, 600))
    (DOCS / "controle-termico.svg").write_text(svg)

    sel = np.nonzero(deg["t_us"] <= 120)[0][::20]
    svg = G.linhas([("", deg["t_us"][sel], deg["v"][sel] * 1000)],
                   "VCCIN no degrau de 30 → 180 A", "tempo (µs)", "tensão (mV)")
    (DOCS / "vrm-degrau.svg").write_text(svg)


NOME_REGRA = {"R01-caminho": "caminho", "R02-sentido": "sentido", "R03-padrao": "nível elétrico",
              "R04-banda": "banda", "R05-optico": "luz", "R06-energia": "energia",
              "R07-controle": "controle", "R08-capacidade": "capacidade", "R09-tempo": "tempo",
              "R10-relogio": "relógio", "R11-requisito": "requisito", "R12-orfao": "órfão",
              "R13-temperatura": "temperatura", "R14-consumo": "consumo",
              "R15-decodificacao": "decodificação", "R16-ajuste": "ajuste elétrico",
              "R17-pcie": "PCIe"}


def _secao_conexoes(R):
    nlr, cen, bt = R["netlist"], R["conexoes"], R["boot"]
    L = ["## Conexões — a netlist do sistema inteiro", "",
         f"Cada sinal é seguido salto a salto: pino → célula → trilha na base → chip tradutor → "
         f"modulador → fibra → filtro → receptor → driver de saída → trilha → célula → pino, "
         f"com laser, alimentação, controle e relógio de cada bloco ativo. São "
         f"{nlr['blocos']} blocos, {nlr['ligacoes']} ligações e {nlr['sinais']} sinais. "
         "O verificador (`modulos/conexoes/verificador.py`) confere 12 regras.", "",
         "Erros por regra, do conceito até o projeto atual:", "",
         "| Regra | " + " | ".join(c["nome"] for c in cen) + " |",
         "|---|" + "---|" * len(cen)]
    for k in REGRAS:
        if any(c["por_regra"][k] for c in cen):
            L.append(f"| {NOME_REGRA[k]} | " + " | ".join(str(c["por_regra"][k]) for c in cen) + " |")
    L.append("| **total** | " + " | ".join(f"**{c['erros']}**" for c in cen) + " |")
    L += ["", "O que cada decisão resolveu:", ""]
    conc = cen[0]["exemplos"]
    for k, msg in conc.items():
        L.append(f"- **{NOME_REGRA[k]}** (conceito): {msg}")
    L += ["",
          "- **Tradutor sob a peça:** com o chip ao lado, trilhas de até 120 mm na base estouram o "
          "atraso e o desalinhamento da GDDR7; numa camada de fotônica debaixo da peça, cada pino "
          "desce poucos milímetros até o seu chip.",
          "- **Relé MEMS na célula:** a célula do conceito usa a mesma chave para 1 A de energia e "
          "para sinal de 32 Gb/s. Uma chave de transistor com R_on baixo o bastante para a energia "
          "tem dezenas de pF desligada, e isso derruba a banda de todo sinal rápido. Um relé, quando "
          "aberto, é um vão de ar: 20 fF. Ele só pode mudar de estado sem corrente, e a "
          "configuração das células acontece antes de energizar.",
          "- **Plano de energia com 2 oz:** com 1 oz a corrente se concentra nos pinos de VCCIN "
          "perto do VRM e alguns passam de 1 A.",
          "- **Placa fria sob a base:** a interconexão dissipa dezenas de watts dentro da base; "
          "com o ar do gabinete, peças, células (relé até 85 °C) e anéis passam do limite, e o "
          "aquecedor não cobre a variação de temperatura.", "",
          "Folga de cada número escolhido: [`sensibilidade.md`](sensibilidade.md). "
          "Contato imperfeito (peça inclinada, sujeira, pino torto): [`defeitos.md`](defeitos.md).", ""]
    if bt["ok"]:
        L += [f"### Boot emulado na netlist: pronto em {bt['tempos_ms']['Pronto']:.0f} ms", "",
              "Máquina de estados com guarda em cada transição (`modulos/sistema/boot.py`):", "",
              "| Etapa | Concluída em |", "|---|---|"]
        L += [f"| {k} | {v:.2f} ms |" for k, v in bt["tempos_ms"].items()]
    else:
        L += [f"### Boot emulado: para em **{bt['parou_em']['etapa']}** — {bt['parou_em']['motivo']}"]
    pr = R["protocolos"]
    d5, g7 = pr["decodificacao"]["DDR5-4800"], pr["decodificacao"]["GDDR7-32"]
    com, sem = pr["ddr5_espelhando"], pr["ddr5_sem_espelho"]
    pc = pr["pcie"]
    pior = max(sem["por_situacao"].values(), key=lambda x: abs(x["erro_amplitude_mv"]), default=None)
    L += ["", "### O que o tradutor faz além de copiar", "",
          "- **Decodificação parcial.** Os dados são copiados sem decodificar. O comando, não: "
          "para saber o sentido dos pinos bidirecionais e acompanhar os ajustes elétricos, o "
          f"tradutor decodifica {', '.join(d5['decodifica'])} na DDR5 e {', '.join(g7['decodifica'])} "
          f"na GDDR7, e copia sem ler o resto ({', '.join(d5['copia'])}). Leva "
          f"{d5['latencia_ps'] / 1000:.1f} ns na DDR5 contra {d5['janela_ps'] / 1000:.0f} ns até o "
          f"primeiro dado, e {g7['latencia_ps'] / 1000:.1f} ns na GDDR7 contra {g7['janela_ps'] / 1000:.0f} ns.",
          f"- **Ajustes dinâmicos da DDR5.** A CPU muda terminação e força de saída por MRW durante o "
          f"uso. O tradutor de cada ponta espelha esses valores: com espelho, {com['divergem']} de "
          f"{com['comandos']} comandos divergem; sem espelho, {sem['divergem']} de {sem['comandos']}"
          + (f" (pior caso: programado {pior['programado']}, visto {pior['visto']}, "
             f"{pior['erro_amplitude_mv']:.0f} mV de amplitude)." if pior else "."),
          f"- **PCIe 5.** A detecção de receptor é controlada pelo FPGA (o tradutor só apresenta "
          f"terminação com a GPU identificada e a luz travada) e o ocioso elétrico atravessa a luz. "
          f"A equalização escolhe o preset {pc['olho']['preset']} com CTLE de {pc['olho']['ctle_db']} dB: "
          f"olho com {pc['olho']['altura_rel']:.2f} de altura e {pc['olho']['largura_ui']:.2f} UI de "
          f"largura; com um tradutor idealmente linear seria {pc['olho_linear']['altura_rel']:.2f} e "
          f"{pc['olho_linear']['largura_ui']:.2f} UI — a não linearidade do anel quase não pesa em NRZ.", ""]
    return L + [""]


def _relatorio(R):
    mp, o, c = R["mapeamento"], R["optica"], R["canais"]
    L = ["# Resultados da simulação", "",
         "Gerado por `python3 -m modulos.sistema.simular`. Não edite à mão.", "",
         "Conceito em [`conceito.md`](conceito.md). Visualizador 3D em "
         "[`../index.html`](../index.html).", ""]

    L += ["## Etapa 1 e 2 — acoplamento e mapeamento", "",
          f"- {mp['celulas_em_contato']} células em contato, {mp['pontes']} em ponte, "
          f"sondadas em {mp['tempo_sondagem_ms']:.0f} ms.",
          f"- **{mp['tipos_certos']} de {mp['pecas']} peças identificadas** só pelo padrão "
          f"terra/energia/sinal. Erro máximo de posição {mp['erro_max_mm'] * 1000:.1f} µm e "
          f"{mp['erro_max_graus']:.2f}°.",
          f"- Energizar antes da identificação é recusado: “{mp['recusa_sem_identificacao'][1]}”.",
          "- Trocar peças de lugar e girar a CPU 91° continua identificando certo "
          "(`tests/test_sistema.py`).", ""]

    a, ct, v, k = R["arvore"], R["contatos"], R["vrm"], R["curto"]
    L += ["## Etapa 3 — energia", "",
          f"- Fonte de 12 V: {a['carga_fonte_12v_w']:.0f} W ({a['corrente_fonte_12v_a']:.1f} A); "
          f"{a['pela_base_w']:.0f} W passam pela base, {a['pelo_cabo_w']:.0f} W pelo cabo da GPU.",
          f"- VCCIN a 200 A em {ct['pinos']} pinos e {ct['celulas']} células: média "
          f"{ct['pino_medio_a']:.2f} A por pino, máximo **{ct['pino_max_a']:.2f} A**; "
          f"**{ct['pinos_acima_1a']} pinos passam de 1 A**"
          f"{' (os mais perto do VRM)' if ct['pinos_acima_1a'] else ''}. "
          f"Célula mais carregada: {ct['celula_max_a']:.2f} A.",
          f"- Queda IR na base {ct['queda_ir_mv']:.1f} mV, perdas {ct['perdas_w']:.1f} W.",
          f"- VRM, degrau 30 → 180 A: queda total {v['queda_total_mv']:.0f} mV (reta de carga), "
          f"assenta em {v['assentamento_us']:.1f} µs, desbalanço entre fases "
          f"{v['desbalanco_fase_pct']:.1f} %, eficiência {v['eficiencia'] * 100:.1f} %.",
          f"- Curto numa célula: pico de {k['pico_a']:.0f} A, desarma em "
          f"**{k['tempo_disparo_ns']:.0f} ns**, {k['energia_chave_uj']:.1f} µJ na chave.", "",
          "![VRM](vrm-degrau.svg)", ""]

    tm = R["termico"]
    sem_placa = next(c for c in R["conexoes"] if c["placa_fria"] is None and c["cobre_oz"] == 2)
    aq, co = R["aquecedores"], R["consumo"]
    L += ["## Temperatura da base", "",
          f"A interconexão dissipa **{tm['calor_interconexao_w']:.0f} W** dentro da própria base "
          f"(chips tradutores e lasers). Só com o ar do gabinete a base chegaria a "
          f"{sem_placa['base_max_c']:.0f} °C. Com a placa fria sob a base "
          f"({tm['placa_fria']} W/m²K, líquido a {tm['amb_c']:.0f} °C), em carga máxima a base chega a "
          f"**{tm['max_c']:.0f} °C**.", "",
          f"- Aquecedor dos anéis: o local mais exigente pede {aq['pede_max_nm']:.2f} nm de "
          f"sintonia; o aquecedor dá {aq['faixa_nm']:.2f} nm. {aq['sem_faixa']} chips sem faixa. "
          f"A frio, os aquecedores gastam {aq['frio_w']:.1f} W.",
          f"- Consumo da interconexão: **{co['total_w']:.0f} W**, "
          f"{co['pj_bit']:.1f} pJ/bit sobre {co['banda_total_gbps'] / 1000:.1f} Tb/s; uma ligação "
          f"elétrica inteira custa ~{co['referencia_pj_bit']:.1f} pJ/bit. Partes: "
          + ", ".join(f"{k} {v:.1f} W" for k, v in co["partes_w"].items()) + ".", "",
          "Nos tradutores ópticos:", "", "| Peça | °C |", "|---|---|"]
    L += [f"| {n} | {t:.1f} |" for n, t in sorted(tm["tradutores"].items(), key=lambda kv: _natural(kv[0]))]
    L += [""]

    L += ["## Etapa 4 — enlace óptico", "",
          "| Configuração | Cálculo do documento | Modelo físico | BER |", "|---|---|---|---|"]
    for n in ("original", "ajustada", "viavel"):
        f = o[n]["fisico"]
        mf = f"{f['margem_db']:+.2f} dB" if math.isfinite(f["margem_db"]) else "não fecha"
        L.append(f"| {NOME_CFG[n]} | {o[n]['simples']['margem_db']:+.2f} dB | {mf} | {_ber(f['ber'])} |")
    L += ["",
          "- **64 comprimentos de onda por fibra não fecham.** Com anel de 10 µm o FSR é "
          f"{13.0:.0f} nm; 64 canais ficam a 0,2 nm, menos que a largura do filtro. A soma do "
          "vazamento dos vizinhos fica do tamanho do sinal, e a BER trava num piso que mais "
          "potência não remove.",
          "- **Configuração viável:** 16 λ por fibra e 1 laser de 10 mW para cada 4 canais.", "",
          "Varredura da configuração ajustada (margem em PAM3, dB):", "",
          "| Raio | " + " | ".join(f"{n} λ" for n in sorted({x['canais_por_fibra'] for x in R['varredura']})) + " |",
          "|---|" + "---|" * len({x['canais_por_fibra'] for x in R['varredura']})]
    for raio in sorted({x["raio_um"] for x in R["varredura"]}, reverse=True):
        lin = [x for x in R["varredura"] if x["raio_um"] == raio]
        lin.sort(key=lambda x: x["canais_por_fibra"])
        vals = [f"{x['margem_db']:+.2f}" if math.isfinite(x["margem_db"]) else "não fecha" for x in lin]
        L.append(f"| {raio} µm | " + " | ".join(vals) + " |")
    L += ["", "Canais simulados no tempo (configuração viável):", "",
          "| Sinal | BER | erros / bits | atraso eletro-óptico | olho |", "|---|---|---|---|---|"]
    for n, x in c.items():
        L.append(f"| {n} | {_ber(x['ber'])} | {x['erros']} / {x['simbolos']} | {x['atraso_ps']:.0f} ps | "
                 f"{x['olho_ui']:.2f} UI |")
    L += ["", "![Olho GDDR7](olho-gddr7.svg)", ""]

    j, tr = R["janela"], R["travamento"]
    L += ["### Controle térmico dos anéis", "",
          f"- Sem controle o enlace aguenta **{j['NRZ']['kelvin_ber_alvo']:.2f} K** (NRZ) e "
          f"**{j['PAM3']['kelvin_ber_alvo']:.2f} K** (PAM3) antes de perder a BER alvo.",
          f"- Com controle: trava em {tr['travou_em_us']:.0f} µs; sob +10 K o erro máximo é "
          f"{tr['erro_max_travado_pm']:.1f} pm e o residual {tr['erro_final_pm']:.2f} pm. "
          f"Sem controle chega a {tr['erro_sem_controle_pm']:.0f} pm.", "",
          "![Controle térmico](controle-termico.svg)", ""]

    L += _secao_conexoes(R)

    rc, rd = R["roteamento"]["comutado"], R["roteamento"]["dedicado"]
    L += ["## Etapa 5 — dados", "",
          f"- Canais ópticos: **{rc['canais']}** em **{rc['fibras']} fibras** com pinos bidirecionais "
          f"comutados; {rd['canais']} em {rd['fibras']} fibras com um canal por sentido.",
          "", "| Enlace | Atraso dos dados | Trilha elétrica na mesma posição | Placa-mãe comum |",
          "|---|---|---|---|"]
    vistos = set()
    for n, x in R["latencia"].items():
        chave = n.split("-")[0] + ("-MEM" if "MEM" in n else "-" + n.split("-")[1])
        if chave in vistos:
            continue
        vistos.add(chave)
        L.append(f"| {n} | {x['dados_ps']:.0f} ps | {x['trilha_ps']:.0f} ps | {x['trilha_tipica_ps']:.0f} ps |")
    t0, q = R["treino"], R["treino_apos_mover"]
    L += ["",
          f"- Treino DDR5: DIMM0 {'converge' if t0['DIMM0']['ok'] else 'falha'} "
          f"({t0['DIMM0']['pistas']} pistas, janela mínima {t0['DIMM0']['janela_min_taps']} passos de "
          f"{t0['DIMM0']['passo_ps']:.2f} ps), DIMM1 {'converge' if t0['DIMM1']['ok'] else 'falha'}.",
          f"- Mover o DIMM0 10 mm depois de treinado: **{q['falhas']} de {q['pistas']} pistas** "
          "saem do olho. Por isso a reconfiguração vem antes do treino.",
          "- Rajadas pelo canal simulado: " + ", ".join(
              f"{k} {'sem erro' if r['erros_bits'] == 0 else str(r['erros_bits']) + ' bits errados'}"
              for k, r in R["rajadas"].items()) + ".", ""]
    return _virgula("\n".join(L) + "\n")


if __name__ == "__main__":
    r = executar()
    print("resultados em", (DOCS / "resultados.md").relative_to(B.PROJETO.parent.parent))
