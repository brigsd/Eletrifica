"""VRM multifásico da CPU, modelo médio (sem ondulação de chaveamento).

Controle em modo corrente com posicionamento adaptativo de tensão (AVP): a
referência de corrente é (VID - Vout) / R_LL, o que dá exatamente a reta de
carga em regime. Cada fase segue sua parte com a dinâmica limitada pela
indutância; o sensor de corrente é a DCR nominal, então uma DCR real diferente
desbalanceia as fases. O VID muda pelo SVID com taxa limitada.
"""
import numpy as np


def simular_degrau(fases=8, vin=12.0, vid=1.25, r_ll_mohm=1.1, l_nh=150.0,
                   dcr_mohm=0.5, desvio_dcr=0.10, c_uf=3880.0, esr_mohm=0.3,
                   tau_corrente_us=2.0, i0=30.0, i1=180.0, t_degrau_us=50.0,
                   di_dt_a_us=1000.0, t_total_us=250.0, dt_ns=2.0,
                   svid=None, slew_mv_us=10.0, fsw_khz=500.0, rdson_mohm=1.0,
                   t_comut_ns=8.0, qg_nc=30.0, v_drv=5.0, semente=0):
    """svid: lista de (t_us, novo_vid) aplicada com taxa `slew_mv_us`."""
    rng = np.random.default_rng(semente)
    dcr = dcr_mohm * 1e-3 * (1 + desvio_dcr * rng.standard_normal(fases))
    ganho_sensor = (dcr_mohm * 1e-3) / dcr          # corrente real / corrente pedida
    L, C, esr, rll = l_nh * 1e-9, c_uf * 1e-6, esr_mohm * 1e-3, r_ll_mohm * 1e-3
    dt, tau = dt_ns * 1e-9, tau_corrente_us * 1e-6
    n = int(t_total_us * 1e3 / dt_ns)
    t = np.arange(n) * dt

    ramp = max(abs(i1 - i0) / (di_dt_a_us * 1e6), dt)
    td = t_degrau_us * 1e-6
    carga = np.clip((t - td) / ramp, 0, 1) * (i1 - i0) + i0

    alvos = sorted(svid or [])
    vid_t = np.empty(n)
    v_ref, alvo = vid, vid
    passo_slew = slew_mv_us * 1e-3 / 1e-6 * dt
    k = 0
    for i in range(n):
        while k < len(alvos) and t[i] >= alvos[k][0] * 1e-6:
            alvo = alvos[k][1]; k += 1
        v_ref += np.clip(alvo - v_ref, -passo_slew, passo_slew)
        vid_t[i] = v_ref

    il = np.full(fases, i0 / fases) * ganho_sensor
    vc = vid - rll * i0                     # parte do regime
    v = np.empty(n); itot = np.empty(n); ifase = np.empty((n, fases))
    for i in range(n):
        vout = vc + esr * (il.sum() - carga[i])
        iref = (vid_t[i] - vout) / rll
        alvo_fase = iref / fases * ganho_sensor
        di = (alvo_fase - il) / tau
        di = np.clip(di, -vout / L, (vin - vout) / L)
        il = il + di * dt
        vc += (il.sum() - carga[i]) / C * dt
        v[i] = vout; itot[i] = il.sum(); ifase[i] = il

    alvo_final = vid_t[-1] - rll * i1
    depois = t >= td
    v_antes = v[np.searchsorted(t, td) - 1]
    v_regime = v[-1]
    undershoot = float(v_regime - v[depois].min())
    fora = np.nonzero(depois & (np.abs(v - v_regime) > 5e-3))[0]
    assentamento_us = float((t[fora[-1]] - td) * 1e6) if len(fora) else 0.0

    i_fase = ifase[-1]
    fsw = fsw_khz * 1e3
    p_cond = float((i_fase ** 2 * (rdson_mohm * 1e-3 + dcr)).sum())
    p_com = float((0.5 * vin * i_fase * 2 * t_comut_ns * 1e-9 * fsw).sum()
                  + fases * qg_nc * 1e-9 * v_drv * fsw)
    p_saida = float(v[-1] * carga[-1])
    return {
        "t_us": t * 1e6, "v": v, "i_carga": carga, "i_total": itot, "vid": vid_t,
        "i_fase_final": i_fase, "desbalanco_fase_pct": float((i_fase.max() / i_fase.mean() - 1) * 100),
        "undershoot_mv": undershoot * 1e3, "assentamento_us": assentamento_us,
        "queda_total_mv": float(v_antes - v[depois].min()) * 1e3,
        "v_final": float(v_regime), "v_alvo_final": float(alvo_final),
        "erro_reta_carga_mv": float(v_regime - alvo_final) * 1e3,
        "perdas_w": p_cond + p_com, "eficiencia": p_saida / (p_saida + p_cond + p_com),
        "potencia_saida_w": p_saida,
    }
