"""Proteção por célula: e-fuse contra curto e a regra de não energizar antes de identificar."""
import numpy as np

from modulos.sistema.base import F_ENERGIA


def simular_curto(v_trilho=1.25, r_on_mohm=25.0, r_curto_mohm=2.0, l_laco_nh=0.5,
                  limite_a=2.0, t_deteccao_ns=100.0, t_desligar_ns=50.0,
                  t_total_ns=1000.0, dt_ps=10.0, t_curto_ns=50.0):
    """Curto de uma célula de energia para o terra; o e-fuse da célula abre."""
    dt = dt_ps * 1e-12
    n = int(t_total_ns * 1e3 / dt_ps)
    t = np.arange(n) * dt
    L = l_laco_nh * 1e-9
    g_on = 1.0 / (r_on_mohm * 1e-3)
    i = 0.0
    i_s, g_s = np.empty(n), np.empty(n)
    t_alarme = t_corte = None
    e_chave = e_curto = 0.0
    for k in range(n):
        if t_alarme is None and i > limite_a:
            t_alarme = t[k]
        g = g_on
        if t_alarme is not None:
            frac = (t[k] - t_alarme - t_deteccao_ns * 1e-9) / (t_desligar_ns * 1e-9)
            g = g_on * float(np.clip(1 - frac, 1e-9, 1))
        r_chave = 1.0 / g
        r_curto = r_curto_mohm * 1e-3 if t[k] >= t_curto_ns * 1e-9 else 1e3
        r_tot = r_chave + r_curto
        i_inf = v_trilho / r_tot
        i = i_inf + (i - i_inf) * np.exp(-r_tot * dt / L)   # exato por passo: aguenta R enorme
        e_chave += i * i * r_chave * dt
        e_curto += i * i * r_curto * dt
        if t_corte is None and t_alarme is not None and i < 0.01:
            t_corte = t[k]
        i_s[k], g_s[k] = i, g
    inicio = t_curto_ns * 1e-9
    return {
        "t_ns": t * 1e9, "i": i_s,
        "pico_a": float(i_s.max()),
        "tempo_disparo_ns": float((t_corte - inicio) * 1e9) if t_corte else float("inf"),
        "energia_chave_uj": float(e_chave * 1e6), "energia_curto_uj": float(e_curto * 1e6),
    }


def pode_energizar(celula, estado):
    """Só energiza célula identificada como energia. `estado`: {"configuracao": Configuracao | None}."""
    cfg = estado.get("configuracao")
    if cfg is None:
        return False, "nenhuma peça identificada ainda"
    nx = cfg.funcao.shape[1]
    iy, ix = divmod(int(celula), nx)
    if cfg.funcao[iy, ix] != F_ENERGIA:
        return False, "célula não é de energia na configuração"
    if cfg.peca[iy, ix] < 0:
        return False, "célula sem peça atribuída"
    return True, "ok"
