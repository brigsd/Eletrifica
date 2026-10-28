"""Limites térmicos típicos, no lado da base (onde o simulador térmico mede).

Valores de folha de dados típicos de cada classe de componente; a temperatura
comparada é a da base no local, não a de junção.
"""

PECA_C = {                      # temperatura máxima no local da peça
    "i5-13600KF": 100.0,        # TjMax Intel de 13ª geração
    "GPU": 90.0,
    "GDDR7": 105.0,
    "DDR5-DIMM": 85.0,          # faixa normal JEDEC; 95 °C só com refresh dobrado
    "FPGA": 100.0,              # grau estendido
}
PECA_PADRAO_C = 85.0

ELASTOMERO_SILICONE_C = 150.0   # elastômero condutivo anisotrópico
LCP_BASE_C = 125.0              # multicamada de LCP estável até ~125 °C (docs/viabilidade.md)
CHIP_TRADUTOR_C = 100.0         # fotônica de silício com driver CMOS no mesmo chip
LASER_SEM_TEC_C = 70.0          # DFB não refrigerado
LASER_COM_TEC_C = 75.0          # carcaça de módulo com TEC
REGULADOR_C = 125.0             # MOSFETs e controlador do VRM

CELULA_C = {                    # pela chave da célula (modulos.sistema.celula)
    "rele_mems": 85.0,
    "rf_soi": 125.0,
    "mosfet_potencia": 150.0,
}
CELULA_PADRAO_C = 85.0

# aquecedor do anel: fração da potência máxima usada como faixa de sintonia,
# e quantos desvios-padrão da variação de fabricação a faixa tem de cobrir
AQUECEDOR_FAIXA_UTIL = 0.8
SIGMAS_FABRICACAO = 3.0


def limite_peca(tipo):
    """A peça e o elastômero debaixo dela: vale o mais baixo."""
    return min(PECA_C.get(tipo, PECA_PADRAO_C), ELASTOMERO_SILICONE_C)


def limite_celula(chave):
    return CELULA_C.get(chave, CELULA_PADRAO_C)


def limite_laser(com_tec=True):
    return LASER_COM_TEC_C if com_tec else LASER_SEM_TEC_C
