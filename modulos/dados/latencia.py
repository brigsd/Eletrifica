"""Atraso de cada enlace óptico, desalinhamento dentro dos grupos e custo de inverter o sentido.

Pino bidirecional comutado: o tradutor do lado da memória só sabe o sentido
lendo o comando no barramento CA (leitura ou escrita). Isso custa o voo do CA
mais a captura do comando, e precisa caber antes de os dados chegarem
(latência de comando). Na inversão, o barramento óptico precisa esvaziar
antes de o outro lado transmitir: voo dos dados + chaveamento do tradutor,
que precisa caber na bolha que o protocolo já deixa entre leitura e escrita.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from modulos.dados.protocolos import PROTOCOLOS

C_MM_PS = 0.299792458        # mm por ps no vácuo
CICLOS_COMANDO = 2           # DDR5 e GDDR7: comando em dois ciclos de CA


@dataclass
class LatenciaEnlace:
    enlace: str
    protocolo: str
    atraso_min_ps: float
    atraso_max_ps: float
    trilha_mesma_posicao_ps: float   # trilha elétrica com a mesma distância (Manhattan)
    trilha_tipica_ps: float          # placa-mãe comum
    atraso_dados_ps: float           # pior pino de dados (DQ/TX/RX)
    desalinhamento_grupo_ps: float   # estático, pior grupo: o treinamento corrige
    alcance_treinamento_ps: float
    deriva_dinamica_ps: float        # o que muda depois do treinamento
    tolerancia_ps: float
    comutacao: dict = field(default_factory=dict)

    @property
    def treinavel(self):
        return self.desalinhamento_grupo_ps <= self.alcance_treinamento_ps

    @property
    def dentro_tolerancia(self):
        return self.deriva_dinamica_ps <= self.tolerancia_ps


@dataclass
class Latencias:
    por_canal: np.ndarray            # ps, na ordem de plano.canais
    enlaces: list

    def enlace(self, id_):
        return next(e for e in self.enlaces if e.enlace == id_)


def _manhattan(plano, a, b):
    pa, pb = plano.poses[a], plano.poses[b]
    return abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])


def calcular(plano, atraso_eletro_optico_ps=100.0, n_g=1.468, dispersao_ps_nm_km=0.5,
             espacamento_nm=0.2, chaveamento_ps=300.0, variacao_eo_ps=2.0,
             deriva_dinamica_ps=0.0, alcance_treinamento_ui=2.0, semente=0):
    rng = np.random.default_rng(semente)
    eo = atraso_eletro_optico_ps + variacao_eo_ps * rng.standard_normal(len(plano.canais))
    por_canal = np.empty(len(plano.canais))
    for i, c in enumerate(plano.canais):
        f = plano.fibras[c.fibra]
        # rank > 0: a luz para no tradutor do chip do rank 0; dali é trilha curta até o vizinho
        L_mm = f.distancia_ate[c.destino if c.destino in f.distancia_ate else c.lider]
        disp = dispersao_ps_nm_km * (L_mm * 1e-6) * c.lambda_idx * espacamento_nm
        por_canal[i] = eo[i] + L_mm * n_g / C_MM_PS + disp

    enlaces = []
    for e in plano.enlaces:
        pr = PROTOCOLOS[e.protocolo]
        idx = np.array(e.canais)
        atrasos = por_canal[idx]
        grupos = {}
        for i in idx:
            c = plano.canais[i]
            grupos.setdefault((c.grupo, c.sentido), []).append(por_canal[i])
        desal = max((max(v) - min(v) for v in grupos.values() if len(v) > 1), default=0.0)
        dist = _manhattan(plano, e.a, e.b)
        dados = [i for i in idx if plano.canais[i].papel in ("DQ", "TX", "RX", "DMI")]
        le = LatenciaEnlace(e.id, e.protocolo, float(atrasos.min()), float(atrasos.max()),
                            dist * pr.ps_por_mm_trilha, pr.atraso_trilha_tipica_ps,
                            float(por_canal[dados].max()) if dados else float(atrasos.max()),
                            float(desal), alcance_treinamento_ui * pr.ui_ps,
                            deriva_dinamica_ps, pr.tolerancia_desalinhamento_ps)
        duplos = [i for i in idx if plano.canais[i].sentido == "duplo"
                  and plano.canais[i].papel in ("DQ", "DQS")]
        if duplos and pr.folga_inversao_ns > 0:
            ca = [i for i in idx if plano.canais[i].papel == "CA"]
            voo_dados = float(por_canal[duplos].max())
            voo_ca = float(por_canal[ca].max())
            captura = CICLOS_COMANDO * 1000.0 / pr.taxa_controle_gbps
            decod = voo_ca + captura
            bolha = voo_dados + chaveamento_ps
            folga = pr.folga_inversao_ns * 1000.0
            tck = 1000.0 / pr.taxa_controle_gbps
            extra = max(0, math.ceil((bolha - folga) / tck))
            le.comutacao = {
                "decodificacao_ps": decod,
                "latencia_comando_ps": pr.latencia_comando_ns * 1000.0,
                "decodificacao_escondida": decod < pr.latencia_comando_ns * 1000.0,
                "custo_bolha_ps": bolha,
                "folga_inversao_ps": folga,
                "cabe_na_bolha": bolha <= folga,
                "ciclos_extra_por_inversao": extra,
            }
        enlaces.append(le)
    return Latencias(por_canal, enlaces)
