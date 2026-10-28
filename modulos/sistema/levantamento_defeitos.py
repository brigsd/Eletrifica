"""Roda cada defeito de contato e grava docs/defeitos.md.

    python3 -m modulos.sistema.levantamento_defeitos     # ~2 min
"""
import copy
import re

from modulos.componentes import ENERGIA
from modulos.sistema import base as B
from modulos.sistema import configuracao as C
from modulos.sistema import defeitos as D
from modulos.sistema import mapeamento as M
from modulos.sistema.base import PROJETO


def _so(m0, *ids):
    m = copy.deepcopy(m0)
    m.colocacoes = [m0.por_id(i) for i in ids]
    return m


def _rodar(m, contatos=None, curtos=()):
    ct = contatos if contatos is not None else B.calcular_contatos(m.base, m.colocacoes)
    s = M.sondar(m, ct, curtos=curtos)
    ids = M.identificar(m.base, s)
    return ids, C.configurar(m.base, ids, s)


def _linha(nome, ids, cfg):
    achou = ", ".join(sorted(i.tipo for i in ids)) or "nada"
    pecas = cfg.pecas + cfg.recusadas
    vered = "; ".join(f"{p.nome}: {p.avaliacao['veredito']}" for p in pecas)
    if cfg.desconhecidas:
        vered += ("; " if vered else "") + f"{len(cfg.desconhecidas)} desconhecida(s), nada ligado"
    motivos = [x for p in cfg.recusadas for x in p.avaliacao["motivos"]][:2]
    return {"defeito": nome, "identificou": achou, "veredito": vered, "motivo": " / ".join(motivos)}


def levantar():
    m0 = B.carregar()
    cpu = _so(m0, "CPU")
    ct = B.calcular_contatos(cpu.base, cpu.colocacoes)
    pinos = cpu.colocacoes[0].peca.pinos
    pwrok = next(i for i, p in enumerate(pinos) if p.nome == "PWROK")
    casos = [("nenhum", lambda: _rodar(cpu, ct))]
    for f in (0.05, 0.20):
        casos.append((f"{f:.0%} do VCCIN sem contato",
                      lambda f=f: _rodar(cpu, D.sem_contato(cpu, ct, "CPU", f, funcao=ENERGIA,
                                                            grupo="VCCIN")[0])))
    casos.append(("1 sinal (PWROK) sem contato", lambda: _rodar(cpu, D.tirar_pinos(ct, 0, [pwrok]))))
    for g in (0.1, 0.2, 0.5):
        casos.append((f"inclinada {g}° (canto levantado)",
                      lambda g=g: _rodar(cpu, D.inclinar(cpu, ct, "CPU", g)[0])))
    casos.append(("partícula condutiva entre sinal e terra",
                  lambda: _rodar(cpu, *D.particula(cpu.base, cpu, ct, "CPU", 1))))
    for d in (0.1, 0.45):
        casos.append((f"pino torto {d} mm",
                      lambda d=d: _rodar(cpu, D.entortar_pino(cpu.base, cpu, ct, "CPU", 300, d, 0.0))))
    casos.append(("peça fora do catálogo ao lado", lambda: _rodar(D.peca_estranha(cpu, 60.0, 60.0))))
    casos.append(("metade da CPU fora da base", lambda: _rodar(D.deslocar(cpu, "CPU", x=15.0))))
    dois = _so(m0, "M0", "M3")
    casos.append(("duas GDDR7 com corpos encostados",
                  lambda: _rodar(D.encostar(dois, "M0", "M3", folga_corpo_mm=0.0))))
    casos.append(("duas GDDR7 com pinos a 0,45 mm",
                  lambda: _rodar(D.encostar(dois, "M0", "M3", distancia_pinos_mm=0.45))))
    return [_linha(nome, *f()) for nome, f in casos]


def gravar(linhas):
    L = ["# Contato imperfeito", "",
         "Gerado por `python3 -m modulos.sistema.levantamento_defeitos`. Não edite à mão.", "",
         "Cada defeito altera a verdade física antes da sondagem (`modulos/sistema/defeitos.py`); "
         "a base só vê o que a sondagem devolve. Peça **recusada** ou **desconhecida** não ganha "
         "nenhuma célula ligada; **degradada** liga com menos folga de corrente.", "",
         "| Defeito | Identificou | Veredito | Motivo |", "|---|---|---|---|"]
    for x in linhas:
        L.append(f"| {x['defeito']} | {x['identificou']} | {x['veredito']} | {x['motivo'] or '—'} |")
    texto = "\n".join(L) + "\n"
    (PROJETO / "docs" / "defeitos.md").write_text(re.sub(r"(?<=\d)\.(?=\d)", ",", texto))


if __name__ == "__main__":
    gravar(levantar())
    print("gravado em", (PROJETO / "docs" / "defeitos.md").relative_to(PROJETO.parent.parent))
