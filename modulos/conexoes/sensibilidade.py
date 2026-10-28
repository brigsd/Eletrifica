"""Quanto o "0 erros" depende dos números escolhidos.

Para cada parâmetro, piora o valor em escala multiplicativa até o verificador
(ou a margem óptica) reprovar, e refina por bisseção. A folga é quanto o
número pode piorar antes de quebrar algo.

    python3 -m modulos.conexoes.sensibilidade
"""
import copy
import dataclasses
import math
from dataclasses import dataclass

from modulos.conexoes import construir as K
from modulos.conexoes import verificador as V
from modulos.energia import contatos
from modulos.optica import enlace as E
from modulos.sistema.celula import chave as chave_celula

ESCADA = (1.05, 1.1, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0, 30.0, 100.0)
PASSOS_BISSECAO = 4
POSICIONAMENTO = "sob_peca"
CHAVE = "rele_mems"
R_FOLHA_2OZ_MOHM = 0.125


@dataclass
class Item:
    parametro: str
    grupo: str
    atual: float
    sentido: str            # "aumentar" ou "diminuir": o lado que piora
    avaliar: object         # valor -> conjunto de regras que reprovam (vazio = passa)
    inteiro: bool = False

    def piorado(self, fator):
        v = self.atual * fator if self.sentido == "aumentar" else self.atual / fator
        return max(1, round(v)) if self.inteiro else v


def _buscar(item):
    """Menor fator de piora que reprova: escada e depois bisseção em log."""
    ok, ruim, regras = 1.0, None, None
    for f in ESCADA:
        r = item.avaliar(item.piorado(f))
        if r:
            ruim, regras = f, r
            break
        ok = f
    if ruim is None:
        return None, None
    for _ in range(PASSOS_BISSECAO):
        meio = math.sqrt(ok * ruim)
        if item.inteiro and item.piorado(meio) in (item.piorado(ok), item.piorado(ruim)):
            break
        r = item.avaliar(item.piorado(meio))
        if r:
            ruim, regras = meio, r
        else:
            ok = meio
    return ruim, regras


class _Contexto:
    """Constrói e verifica o projeto atual; avalia variações contra o resultado nominal."""

    def __init__(self, sistema_real):
        self.m, self.cfg, self.plano, self.opt = sistema_real
        self.ch = chave_celula(CHAVE)
        self.contatos = self._contatos(self.ch.r_on_ohm)
        self.nl = self._netlist()
        self.base = self._contagem(V.verificar(self.nl, self._ctx()))

    def _contatos(self, r_on_ohm):
        d = contatos.distribuir(self.m.base, self.cfg, zona_vrm=self.m.zonas["vrm_cpu"],
                                r_on_mohm=r_on_ohm * 1e3, r_folha_mohm=R_FOLHA_2OZ_MOHM)
        d["chave"] = CHAVE
        return d

    def _netlist(self, chave=None, parametros=None):
        return K.construir(self.m, self.cfg, self.plano, self.opt, chave=chave or self.ch,
                           posicionamento=POSICIONAMENTO, parametros=parametros)

    def _ctx(self, contatos_=None, **extra):
        return {"contatos": [contatos_ or self.contatos], **extra}

    @staticmethod
    def _contagem(rel):
        out = {}
        for v in rel.erros:
            out[v.regra] = out.get(v.regra, 0) + 1
        return out

    def novas(self, rel):
        """Regras com mais erros que no nominal."""
        c = self._contagem(rel)
        return {r for r, n in c.items() if n > self.base.get(r, 0)}

    # avaliadores -------------------------------------------------------------
    def construtor(self, nome, transforma=lambda v: v):
        def avaliar(v):
            try:
                nl = self._netlist(parametros={nome: transforma(v)})
            except RuntimeError as e:          # não coube na base
                return {f"construção: {e}"[:60]}
            return self.novas(V.verificar(nl, self._ctx()))
        return avaliar

    def contexto(self, chave_ctx, padroes):
        def avaliar(v):
            ctx = self._ctx(**{chave_ctx: {p: v for p in padroes}})
            return self.novas(V.verificar(self.nl, ctx))
        return avaliar

    def chave(self, campo):
        def avaliar(v):
            ch = dataclasses.replace(self.ch, **{campo: v})
            nl = self._netlist(chave=ch)
            ct = self._contatos(ch.r_on_ohm) if campo == "r_on_ohm" else self.contatos
            return self.novas(V.verificar(nl, self._ctx(ct)))
        return avaliar


def _optico(cfg, caminho, simbolo="PAM3"):
    def avaliar(v):
        c = copy.deepcopy(cfg)
        alvo = c
        for k in caminho[:-1]:
            alvo = alvo[k]
        alvo[caminho[-1]] = v
        try:
            m = E.orcamento(c, simbolo=simbolo)["margem_db"]
        except ValueError:                     # Q além do que a perda do anel permite
            return {"anel irrealizável"}
        return set() if math.isfinite(m) and m > 0 else {"margem óptica"}
    return avaliar


def _valor(cfg, caminho):
    for k in caminho:
        cfg = cfg[k]
    return cfg


def itens(ctx, opcoes=None):
    """Parâmetros cobertos. `opcoes` restringe pelo nome do parâmetro."""
    orc = V.ORCAMENTO_TRILHA_DB
    g7 = [p for p in orc if p.startswith("GDDR7")]
    opt = ctx.opt
    lista = [
        Item("vias por chip", "construtor", K.VIAS_MAX, "diminuir", ctx.construtor("VIAS_MAX"), True),
        Item("lado do chip (mm)", "construtor", K.CHIP_MM[0], "aumentar",
             ctx.construtor("CHIP_MM", lambda v: (v, v))),
        Item("perda da trilha (dB/mm/GHz)", "construtor", K.PERDA_DB_MM_GHZ, "aumentar",
             ctx.construtor("PERDA_DB_MM_GHZ")),
        Item("pJ/bit de transmissão", "construtor", K.PJ_BIT_TX, "aumentar", ctx.construtor("PJ_BIT_TX")),
        Item("pJ/bit de recepção", "construtor", K.PJ_BIT_RX, "aumentar", ctx.construtor("PJ_BIT_RX")),
        Item("orçamento de trilha GDDR7 (dB)", "verificador", orc[g7[0]], "diminuir",
             ctx.contexto("orcamento_trilha_db", g7)),
        Item("orçamento de trilha PCIe5 (dB)", "verificador", orc["PCIe5-CML"], "diminuir",
             ctx.contexto("orcamento_trilha_db", ["PCIe5-CML"])),
        Item("atraso máximo GDDR7 (ps)", "verificador", V.ATRASO_MAX_PS["GDDR7-32"], "diminuir",
             ctx.contexto("atraso_max_ps", ["GDDR7-32"])),
        Item("C_off do relé (fF)", "célula", ctx.ch.c_off_ff, "aumentar", ctx.chave("c_off_ff")),
        Item("R_on do relé (Ω), para cima", "célula", ctx.ch.r_on_ohm, "aumentar", ctx.chave("r_on_ohm")),
        Item("R_on do relé (Ω), para baixo", "célula", ctx.ch.r_on_ohm, "diminuir", ctx.chave("r_on_ohm")),
    ]
    for nome, caminho, sentido in (("potência do laser (mW)", ("laser_mw",), "diminuir"),
                                   ("ruído do TIA (pA/√Hz)", ("receptor", "tia_pa_rthz"), "aumentar"),
                                   ("Q do anel, para baixo", ("anel", "q_carregado"), "diminuir"),
                                   ("Q do anel, para cima", ("anel", "q_carregado"), "aumentar"),
                                   ("eficiência do anel (pm/V)", ("anel", "eficiencia_pm_v"), "diminuir"),
                                   ("perdas passivas (dB)", ("perdas_db",), "aumentar")):
        lista.append(Item(nome, "óptica", _valor(opt, caminho), sentido, _optico(opt, caminho)))
    if opcoes:
        lista = [i for i in lista if i.parametro in opcoes]
    return lista


def varrer(sistema_real, parametros=None):
    """Uma linha por parâmetro, da menor para a maior folga."""
    ctx = _Contexto(sistema_real)
    linhas = []
    for it in itens(ctx, parametros):
        fator, regras = _buscar(it)
        linhas.append({
            "parametro": it.parametro, "grupo": it.grupo, "valor_atual": it.atual,
            "valor_que_reprova": it.piorado(fator) if fator else None,
            "fator": fator, "folga_pct": (fator - 1) * 100 if fator else None,
            "regra_que_quebra": ", ".join(sorted(regras)) if regras else None,
            "sentido": it.sentido,
        })
    linhas.sort(key=lambda l: (l["folga_pct"] is None, l["folga_pct"] or 0))
    return {"linhas": linhas, "erros_nominais": ctx.base}


def _num(v):
    if v is None:
        return "—"
    if isinstance(v, int) or float(v).is_integer():
        s = f"{v:.0f}"
    elif abs(v) >= 100:
        s = f"{v:.0f}"
    elif abs(v) >= 1:
        s = f"{v:.2f}"
    else:
        s = f"{v:.3g}"
    return s.replace(".", ",")


def tabela_md(linhas):
    if isinstance(linhas, dict):
        linhas = linhas["linhas"]
    out = ["| Parâmetro | Atual | Reprova em | Folga | Quebra |", "|---|---|---|---|---|"]
    for l in linhas:
        if l["fator"] is None:
            folga = f"> {_num((ESCADA[-1] - 1) * 100)} %"
            reprova = f"não reprova até ×{_num(ESCADA[-1])}"
        else:
            folga = f"{_num(l['folga_pct'])} %"
            if l["folga_pct"] < 20:
                folga = f"**{folga}**"
            reprova = _num(l["valor_que_reprova"])
        out.append(f"| {l['parametro']} | {_num(l['valor_atual'])} | {reprova} | {folga} | "
                   f"{l['regra_que_quebra'] or '—'} |")
    return "\n".join(out)


if __name__ == "__main__":
    from modulos.dados import roteamento as DR
    from modulos.sistema import base as B, configuracao as C, mapeamento as M

    m = B.carregar()
    ct = B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct)
    cfg = C.configurar(m.base, M.identificar(m.base, s), s)
    opt = E.carregar("viavel")
    plano = DR.rotear(cfg, canais_por_fibra=opt["canais_por_fibra"])
    r = varrer((m, cfg, plano, opt))
    print("erros no nominal:", r["erros_nominais"] or "nenhum")
    print(tabela_md(r))
