"""Banco unificado: a CPU e a GPU usam os mesmos chips de memória, sem cópia.

A GPU tem uma porta rápida só: a de memória (12 canais GDDR7, ~1,5 TB/s). O
PCIe que a liga à CPU (~64 GB/s) é o barramento lento do offloading. Então o
banco compartilhado entra pela porta de memória da GPU, e a base faz o que uma
placa-mãe não faz, porque está no meio de cada pino:

- multiplica os chips por canal: a GPU enxerga chips de 32 Gb (o maior do padrão
  GDDR7), cada um feito de dois chips reais de 16 Gb. O seletor escolhe o chip
  pelo bit mais alto da linha, lido do comando, como o RCD de um LRDIMM. Na luz o
  segundo chip não carrega o canal;
- liga a CPU aos mesmos chips: o canal B da CPU vai para uma ponte que se
  apresenta como um DIMM DDR5 de 48 GB, com CL maior declarado no SPD, e grava no
  layout que a GPU vai ler;
- aprende os dois mapas de endereço no boot, por sondas, e confere com sondas
  aleatórias. Os mapas são da família conhecida desses controladores: XOR de bits
  e, nos 12 canais da GPU, o resto da divisão por 3;
- dá cada rank (os 12 chips da mesma posição) a um dono por vez. Enquanto um rank
  é da CPU, a base absorve o refresh e responde o treino que a GPU manda para ele.

    from modulos.dados.memoria_unificada import simular
    r = simular()
"""
import math
import random
from collections import Counter
from dataclasses import dataclass

from modulos.dados.comandos import LATENCIAS, TCK_DDR5_NS
from modulos.rtl import medidas as RTL

# --- banco ------------------------------------------------------------------
CANAIS_GPU = 12
RANKS = 2                      # chips reais atrás de cada chip que a GPU enxerga
CHIP_REAL_GB = 2.0             # 16 Gb
CHIP_MAX_GDDR7_GB = 4.0        # 32 Gb: o maior chip do padrão; a GPU não endereça além disso
CHUNK_GPU_B = 256              # bloco contíguo num chip, no entrelaçamento da GPU
LINHA_CPU_B = 64               # linha de cache da CPU
SETOR_GPU_B = 32
BANDA_CANAL_GPU_GBPS = 32 * 32.0 / 8     # 32 pinos a 32 Gb/s
BANDA_CANAL_DDR5_GBPS = 64 * 4.8 / 8     # DDR5-4800, 64 bits
EFICIENCIA_DDR5 = 0.85
CANAIS_CPU_NO_BANCO = 1        # o canal A fica com o DIMM da CPU; o B vai para a ponte
DIMM_CPU_GB = 16.0
LEITURA_DDR5_LOCAL_NS = 90.0   # carga até uso numa DDR5 comum (o mesmo do ReBAR)

# --- campos de endereço -------------------------------------------------------
# GPU: n = endereço / 256; t = n mod 3 escolhe o trio de canais, m = n div 3 (26 bits) passa
# por XOR e vira coluna (3), canal dentro do trio (2), banco (4) e linha (17; a de cima é o rank)
BITS_M = 26
CAMPOS_GPU = (("coluna", 3), ("q", 2), ("banco", 4), ("linha", 17))
BIT_RANK = 16                  # dentro da linha de 17 bits
# CPU, canal B sem entrelaçamento: linha de cache L = h * 2^28 + l; l (28 bits) passa por XOR
# e vira subcanal, coluna, banco (grupo e banco), rank do DIMM e linha; h (0 a 2) é o topo
# da linha de um DIMM de 24 Gb por chip
BITS_L = 28
CAMPOS_CPU = (("sub", 1), ("coluna", 7), ("banco", 5), ("rank", 1), ("linha", 14))

# --- ponte DDR5 -> GDDR7 ---------------------------------------------------------
PONTE_PHY_DDR5_NS = 1.5        # receber o comando ou devolver o burst DDR5, cada sentido
PONTE_MAPA_NS = RTL.PONTE_MAPA_NS   # medido no RTL (ponte_mapa.v): árvores de XOR e divisão por 3
PONTE_FILA_NS = 1.0            # declarado: fila e arbitragem, fora do RTL
PONTE_LOGICA_NS = PONTE_MAPA_NS + PONTE_FILA_NS   # era 2,0 declarado
PONTE_PHY_GDDR7_NS = 1.0       # cada sentido
TRCD_GDDR7_NS = 12.0
RL_GDDR7_NS = LATENCIAS["GDDR7-32"]["CL_ns"]
CL_DDR5_NATIVO = 40
CL_MAX_DDR5 = 66               # maior CL que os registradores do DDR5 aceitam (CL22 a CL66)
PORTAS_GDDR7_PONTE = CANAIS_GPU

# --- seletor de rank, do lado da GPU ---------------------------------------------
SELETOR_CA_PS = RTL.SELETOR_CA_PS   # medido no RTL: 1 registro (era 250 declarado)
SELETOR_DQ_PS = RTL.SELETOR_DQ_PS   # medido no RTL: o mux de leitura é registrado (era 50 declarado)
PASSO_ALINHAMENTO_PS = 1.0     # linha de atraso que iguala a chegada dos dois chips
FAIXA_ALINHAMENTO_PS = 250.0
RL_EXTRA_TCK = RTL.RL_EXTRA_TCK   # o chip emulado declara RL maior: os 2 registros do seletor (provado no cocotb)
RL_EXTRA_PS = RL_EXTRA_TCK * LATENCIAS["GDDR7-32"]["tck_ns"] * 1000
TOLERANCIA_DESALINHAMENTO_PS = 0.1 * 1000 / (32.0 / 1.5)   # 0,1 UI da GDDR7 em PAM3

# --- troca de dono ------------------------------------------------------------
TROCA_MUX_NS = 5.0             # o FPGA vira o mux dos 12 chips do rank
INVALIDAR_L2_GPU_US = 20.0
DESCARGA_CPU_GBPS = 30.0       # clflushopt de linhas sujas, limitado pelo canal da ponte
TREFI_GDDR7_US = 1.9

# --- LLM: cada token lê o modelo inteiro --------------------------------------
BANDA_PCIE_EFETIVA_GBPS = 55.0
MODELOS = (("34B em 4 bits", 34, 0.57), ("70B em 4 bits", 70, 0.57),
           ("34B em 8 bits", 34, 1.06), ("120B em 4 bits", 120, 0.57))
VRAM_NATIVA_GB = CANAIS_GPU * CHIP_REAL_GB


# ------------------------------------------------------------------ GF(2)
def _paridade(x):
    return bin(x).count("1") & 1


def _aplicar(linhas, x):
    """y = M x em GF(2); linhas[k] é a máscara de entrada do bit k de saída."""
    y = 0
    for k, m in enumerate(linhas):
        if _paridade(x & m):
            y |= 1 << k
    return y


def _linhas_das_colunas(colunas, n):
    return [sum(((c >> k) & 1) << i for i, c in enumerate(colunas)) for k in range(n)]


def _inversa(linhas, n):
    """Inversa em GF(2) por eliminação de Gauss; None se a matriz é singular."""
    a = [[linhas[k], 1 << k] for k in range(n)]
    for col in range(n):
        piv = next((r for r in range(col, n) if (a[r][0] >> col) & 1), None)
        if piv is None:
            return None
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r != col and (a[r][0] >> col) & 1:
                a[r][0] ^= a[col][0]
                a[r][1] ^= a[col][1]
    return [a[k][1] for k in range(n)]


def _juntar(campos, v):
    x, d = 0, 0
    for nome, n in campos:
        x |= (v[nome] & ((1 << n) - 1)) << d
        d += n
    return x


def _separar(campos, x):
    out, d = {}, 0
    for nome, n in campos:
        out[nome] = (x >> d) & ((1 << n) - 1)
        d += n
    return out


# ------------------------------------------------------------------ mapas
@dataclass(frozen=True)
class Local:
    """Onde um byte mora, do jeito que a GPU vê: chip de 32 Gb (canal), banco, linha de 17 bits."""
    canal: int
    banco: int
    linha: int
    coluna: int
    byte: int

    @property
    def rank(self):
        return self.linha >> BIT_RANK

    @property
    def chave(self):
        """O chip real e a posição dentro dele."""
        return (self.canal, self.rank, self.banco, self.linha & ((1 << BIT_RANK) - 1), self.coluna)


class MapaGPU:
    """Endereço do banco (bytes) -> Local. `grupos[t]` é o trio de canais do resto t."""

    def __init__(self, linhas, grupos):
        self.linhas, self.grupos = list(linhas), tuple(grupos)

    def local(self, o):
        n, byte = divmod(o, CHUNK_GPU_B)
        m, t = divmod(n, 3)
        v = _separar(CAMPOS_GPU, _aplicar(self.linhas, m))
        return Local(4 * self.grupos[t] + v["q"], v["banco"], v["linha"], v["coluna"], byte)

    def rank_contiguo(self):
        """O rank depende só do bit mais alto de m: cada rank é uma metade contínua do banco."""
        topo = sum(n for _, n in CAMPOS_GPU[:-1]) + BIT_RANK
        return self.linhas[topo] == 1 << (BITS_M - 1)


class MapaCPU:
    """Endereço na janela do canal B (bytes) -> campos DDR5 que aparecem nos pinos."""

    def __init__(self, linhas):
        self.linhas = list(linhas)
        self._inv = None

    def campos(self, a):
        L, byte = divmod(a, LINHA_CPU_B)
        h, l = divmod(L, 1 << BITS_L)
        v = _separar(CAMPOS_CPU, _aplicar(self.linhas, l))
        v["linha"] |= h << 14
        v["byte"] = byte
        return v

    def endereco(self, v):
        """O inverso: dos campos que chegam pelos pinos ao endereço da janela."""
        if self._inv is None:
            self._inv = _inversa(self.linhas, BITS_L)
        h = v["linha"] >> 14
        bits = _juntar(CAMPOS_CPU, {**v, "linha": v["linha"] & ((1 << 14) - 1)})
        return ((h << BITS_L) | _aplicar(self._inv, bits)) * LINHA_CPU_B + v.get("byte", 0)


def mapa_gpu_aleatorio(rng, rank_no_topo=True):
    """Um mapa da família da GPU: bits baixos permutados, banco e canal com XOR de bits da linha."""
    baixos = list(range(9))
    rng.shuffle(baixos)
    linhas = [1 << baixos[k] for k in range(9)] + [1 << k for k in range(9, BITS_M)]
    for k in range(3, 9):                           # q e banco
        linhas[k] |= rng.getrandbits(16) << 9       # XOR com bits da linha, menos o de cima
    if not rank_no_topo:
        linhas[9 + BIT_RANK] |= 1 << baixos[3]      # o rank mistura com um bit baixo
    grupos = list(range(3))
    rng.shuffle(grupos)
    return MapaGPU(linhas, grupos)


def mapa_cpu_aleatorio(rng):
    """Um mapa da família da CPU: subcanal e banco com XOR de bits da linha, como os da Intel."""
    baixos = list(range(14))
    rng.shuffle(baixos)
    linhas = [1 << baixos[k] for k in range(14)] + [1 << k for k in range(14, BITS_L)]
    for k in [0] + list(range(8, 13)):              # subcanal e banco
        linhas[k] |= rng.getrandbits(14) << 14
    return MapaCPU(linhas)


# ------------------------------------------------------------------ banco
class Banco:
    """Os 24 chips reais, o seletor de cada canal da GPU, a ponte da CPU e o dono de cada rank.

    `gpu` e `cpu` são os mapas verdadeiros, que só os controladores conhecem; a ponte usa
    os que a calibração aprendeu."""

    def __init__(self, mapa_gpu, mapa_cpu):
        self.gpu, self.cpu = mapa_gpu, mapa_cpu
        self.dados = {}                    # Local.chave sem byte -> bytearray(256)
        self.dono = ["GPU"] * RANKS
        self.aprendido_gpu = self.aprendido_cpu = None
        self.cache_cpu = {}                # linha -> bytes, escritas ainda não descarregadas
        self.eventos = Counter()

    # chips
    def _bloco(self, chave):
        if chave not in self.dados:
            self.dados[chave] = bytearray(CHUNK_GPU_B)
        return self.dados[chave]

    def _ler(self, loc, n):
        return bytes(self._bloco(loc.chave)[loc.byte:loc.byte + n])

    def _gravar(self, loc, dados):
        self._bloco(loc.chave)[loc.byte:loc.byte + len(dados)] = dados

    # GPU: controlador -> seletor do canal -> chip do rank
    def gpu_gravar(self, o, dados):
        loc = self.gpu.local(o)
        if self.dono[loc.rank] != "GPU":
            self.eventos["gpu_fora_da_posse"] += 1
            return False
        self._gravar(loc, dados)
        return True

    def gpu_ler(self, o, n=SETOR_GPU_B):
        loc = self.gpu.local(o)
        if self.dono[loc.rank] != "GPU":
            self.eventos["gpu_fora_da_posse"] += 1
            return None
        return self._ler(loc, n)

    # CPU: núcleo -> cache -> canal B -> ponte -> chip
    def cpu_gravar(self, a, dados):
        self.cache_cpu[a // LINHA_CPU_B] = bytes(dados)

    def cpu_ler(self, a):
        linha = a // LINHA_CPU_B
        if linha in self.cache_cpu:
            return self.cache_cpu[linha]
        return self._ponte_ler(linha)

    def _ponte_local(self, linha):
        v = self.cpu.campos(linha * LINHA_CPU_B)            # o que o controlador põe nos pinos
        return self.aprendido_gpu.local(self.aprendido_cpu.endereco(v))

    def _ponte_gravar(self, linha, dados):
        loc = self._ponte_local(linha)
        if self.dono[loc.rank] != "CPU":
            self.eventos["cpu_fora_da_posse"] += 1
            return False
        self._gravar(loc, dados)
        self.eventos["ponte_escritas"] += 1
        return True

    def _ponte_ler(self, linha):
        loc = self._ponte_local(linha)
        if self.dono[loc.rank] != "CPU":
            self.eventos["cpu_fora_da_posse"] += 1
            return None
        self.eventos["ponte_leituras"] += 1
        return self._ler(loc, LINHA_CPU_B)

    def rank_da_linha(self, linha):
        return self.aprendido_gpu.local(linha * LINHA_CPU_B).rank

    def descarregar_cpu(self, rank=None):
        """clflushopt das linhas sujas (todas, ou só as que caem no rank)."""
        n = 0
        for linha in sorted(self.cache_cpu):
            if rank is None or self.rank_da_linha(linha) == rank:
                self._ponte_gravar(linha, self.cache_cpu.pop(linha))
                n += 1
        return n

    def entregar(self, rank, para, protocolo=True):
        """Troca o dono do rank. Com o protocolo: a CPU descarrega o que é do rank antes de
        entregar e invalida o que tem dele ao receber; a GPU invalida o L2 do rank."""
        if self.dono[rank] == para:
            return {"linhas_descarregadas": 0, "tempo_us": 0.0}
        n = 0
        if protocolo and para == "GPU":
            n = self.descarregar_cpu(rank)
        if protocolo and para == "CPU":
            for linha in [l for l in self.cache_cpu if self.rank_da_linha(l) == rank]:
                del self.cache_cpu[linha]
        self.dono[rank] = para
        self.eventos[f"entregas_para_{para}"] += 1
        tempo_us = (n * LINHA_CPU_B / (DESCARGA_CPU_GBPS * 1e3) + TROCA_MUX_NS / 1e3
                    + (INVALIDAR_L2_GPU_US if para == "GPU" else 0.0))
        return {"linhas_descarregadas": n, "tempo_us": tempo_us}


def tempo_calibracao_us(chips, chip_gb, portas=PORTAS_GDDR7_PONTE):
    """A ponte varre o banco inteiro atrás das etiquetas das sondas da GPU."""
    return chips * chip_gb * 2**30 / (portas * BANDA_CANAL_GPU_GBPS * 1e9) * 1e6


# ------------------------------------------------------------------ calibração
def _etiqueta(i):
    return (b"CAL!" + i.to_bytes(4, "little")) * (SETOR_GPU_B // 8)


def calibrar(banco, rng, conferencias=64):
    """O boot ensina à ponte os dois mapas.

    GPU: um kernel grava uma etiqueta em cada sonda (um bit de m por vez, e os restos 1 e 2);
    a ponte toma o banco e procura as etiquetas. CPU: a CPU grava sondas na janela e a ponte,
    que termina o DDR5, anota os campos de cada uma. Depois, sondas aleatórias dos dois lados
    conferem a previsão."""
    sondas = [(i, CHUNK_GPU_B * 3 * (1 << i)) for i in range(BITS_M)]
    sondas += [(BITS_M, CHUNK_GPU_B * 1), (BITS_M + 1, CHUNK_GPU_B * 2), (BITS_M + 2, 0)]
    for i, o in sondas:
        banco.gpu_gravar(o, _etiqueta(i))
    achados = {}
    for chave, bloco in banco.dados.items():                 # a ponte varre o banco
        for b in range(0, CHUNK_GPU_B, SETOR_GPU_B):
            s = bytes(bloco[b:b + SETOR_GPU_B])
            if s[:4] == b"CAL!" and s == _etiqueta(int.from_bytes(s[4:8], "little")):
                canal, rank, banco_, linha, coluna = chave
                achados[int.from_bytes(s[4:8], "little")] = Local(
                    canal, banco_, linha | (rank << BIT_RANK), coluna, b)

    def vetor(loc):
        return _juntar(CAMPOS_GPU, {"coluna": loc.coluna, "q": loc.canal % 4,
                                    "banco": loc.banco, "linha": loc.linha})
    zero = achados[BITS_M + 2]
    colunas = [vetor(achados[i]) ^ vetor(zero) for i in range(BITS_M)]
    grupos = [zero.canal // 4, achados[BITS_M].canal // 4, achados[BITS_M + 1].canal // 4]
    banco.aprendido_gpu = MapaGPU(_linhas_das_colunas(colunas, BITS_M), grupos)
    banco.dados.clear()

    erros_gpu = 0
    for _ in range(conferencias):
        o = rng.randrange(0, int(CANAIS_GPU * RANKS * CHIP_REAL_GB * 2**30), SETOR_GPU_B)
        if banco.aprendido_gpu.local(o) != banco.gpu.local(o):
            erros_gpu += 1

    janela = int(CANAIS_GPU * RANKS * CHIP_REAL_GB * 2**30)
    sondas_cpu = [LINHA_CPU_B * (1 << j) for j in range(BITS_L)]
    campos = [banco.cpu.campos(a) for a in sondas_cpu]       # o que a ponte vê nos pinos
    colunas_cpu = [_juntar(CAMPOS_CPU, v) for v in campos]
    banco.aprendido_cpu = MapaCPU(_linhas_das_colunas(colunas_cpu, BITS_L))
    erros_cpu = 0
    for _ in range(conferencias):
        a = rng.randrange(0, janela, LINHA_CPU_B)
        if banco.aprendido_cpu.endereco(banco.cpu.campos(a)) != a:
            erros_cpu += 1
    banco_bytes = CANAIS_GPU * RANKS * CHIP_REAL_GB * 2**30
    return {"sondas_gpu": len(sondas), "sondas_cpu": len(sondas_cpu),
            "conferencias": conferencias, "erros_gpu": erros_gpu, "erros_cpu": erros_cpu,
            "rank_contiguo": banco.aprendido_gpu.rank_contiguo(),
            "varredura_ms": banco_bytes / (PORTAS_GDDR7_PONTE * BANDA_CANAL_GPU_GBPS * 1e9) * 1e3,
            "ok": erros_gpu == 0 and erros_cpu == 0}


# ------------------------------------------------------------------ números
def capacidade():
    chip_visto = RANKS * CHIP_REAL_GB
    return {"chips": CANAIS_GPU * RANKS, "chip_visto_gb": chip_visto,
            "cabe_no_padrao": chip_visto <= CHIP_MAX_GDDR7_GB,
            "banco_gb": CANAIS_GPU * chip_visto, "rank_gb": CANAIS_GPU * CHIP_REAL_GB,
            "banda_gpu_gbps": CANAIS_GPU * BANDA_CANAL_GPU_GBPS,
            "banda_cpu_gbps": CANAIS_CPU_NO_BANCO * BANDA_CANAL_DDR5_GBPS,
            "vram_nativa_gb": VRAM_NATIVA_GB, "dimm_cpu_gb": DIMM_CPU_GB}


def latencia_ponte(ida_ns=0.6, volta_ns=None):
    """Leitura da CPU pela ponte, de dentro do "DIMM": vira o CL que o SPD declara.
    `ida_ns` e `volta_ns`: comando da ponte até o chip e dado do chip até a ponte, pino a pino."""
    volta_ns = ida_ns if volta_ns is None else volta_ns
    ida = PONTE_PHY_DDR5_NS + PONTE_LOGICA_NS + PONTE_PHY_GDDR7_NS + ida_ns
    leitura = ida + RL_GDDR7_NS + volta_ns + PONTE_PHY_GDDR7_NS + PONTE_PHY_DDR5_NS
    ativacao = ida + TRCD_GDDR7_NS
    cl, trcd = math.ceil(leitura / TCK_DDR5_NS), math.ceil(ativacao / TCK_DDR5_NS)
    return {"leitura_ns": leitura, "ativacao_ns": ativacao, "cl": cl, "trcd": trcd,
            "cl_max": CL_MAX_DDR5, "cl_nativo": CL_DDR5_NATIVO,
            "folga_ns": (CL_MAX_DDR5 - cl) * TCK_DDR5_NS,
            "extra_ns": (cl - CL_DDR5_NATIVO) * TCK_DDR5_NS,
            "carga_uso_ns": LEITURA_DDR5_LOCAL_NS + (cl - CL_DDR5_NATIVO) * TCK_DDR5_NS,
            "cabe": cl <= CL_MAX_DDR5 and trcd <= CL_MAX_DDR5}


def seletor(diferenca_fibra_mm=0.0, ps_por_mm=1.468 / 299_792_458.0 * 1e9):
    """O que o seletor de rank soma do lado da GPU, e se os dois chips chegam alinhados."""
    residual = PASSO_ALINHAMENTO_PS / 2
    return {"ca_ps": SELETOR_CA_PS, "dq_ps": SELETOR_DQ_PS,
            "faixa_atraso_ps": diferenca_fibra_mm * ps_por_mm,
            "residual_ps": residual, "tolerancia_ps": TOLERANCIA_DESALINHAMENTO_PS,
            "alinhado": residual <= TOLERANCIA_DESALINHAMENTO_PS}


def tokens_por_s(gb, rapida_gb, banda_rapida, banda_lenta):
    """Teto: cada token lê o modelo inteiro; o que não cabe na memória rápida sai da lenta."""
    if gb <= rapida_gb:
        return banda_rapida / gb
    return 1.0 / (rapida_gb / banda_rapida + (gb - rapida_gb) / banda_lenta)


def llm():
    cap = capacidade()
    bg, banco = cap["banda_gpu_gbps"], cap["banco_gb"]
    dimm = CANAIS_CPU_NO_BANCO * 0 + 2 * BANDA_CANAL_DDR5_GBPS
    linhas = []
    for nome, bilhoes, bytes_param in MODELOS:
        gb = bilhoes * bytes_param
        linhas.append({
            "modelo": nome, "gb": gb,
            "offload_cpu": tokens_por_s(gb, VRAM_NATIVA_GB, bg, dimm),
            "offload_pcie": tokens_por_s(gb, VRAM_NATIVA_GB, bg, BANDA_PCIE_EFETIVA_GBPS),
            "banco": tokens_por_s(gb, banco, bg, BANDA_PCIE_EFETIVA_GBPS),
            "cabe_no_banco": gb <= banco,
            "carga_s": gb / (cap["banda_cpu_gbps"] * EFICIENCIA_DDR5)})
    return linhas


# ------------------------------------------------------------------ simulação
def _dados(rng, n):
    return bytes(rng.getrandbits(8) for _ in range(n))


def integridade(banco, rng, linhas=2000):
    """A CPU grava o "modelo" pela ponte, entrega os dois ranks e a GPU lê os mesmos bytes."""
    for r in range(RANKS):
        banco.entregar(r, "CPU")
    janela = int(CANAIS_GPU * RANKS * CHIP_REAL_GB * 2**30)
    escrito = {}
    for _ in range(linhas):
        a = rng.randrange(0, janela, LINHA_CPU_B)
        escrito[a] = _dados(rng, LINHA_CPU_B)
        banco.cpu_gravar(a, escrito[a])
    tempos = [banco.entregar(r, "GPU") for r in range(RANKS)]
    erros = 0
    for a, d in escrito.items():
        lido = b"".join(banco.gpu_ler(a + k) or b"" for k in range(0, LINHA_CPU_B, SETOR_GPU_B))
        erros += lido != d
    # e o caminho de volta: a GPU grava, entrega, a CPU lê
    volta = {}
    for _ in range(linhas // 4):
        o = rng.randrange(0, janela, LINHA_CPU_B)
        volta[o] = _dados(rng, LINHA_CPU_B)
        for k in range(0, LINHA_CPU_B, SETOR_GPU_B):
            banco.gpu_gravar(o + k, volta[o][k:k + SETOR_GPU_B])
    for r in range(RANKS):
        banco.entregar(r, "CPU")
    erros_volta = sum(banco.cpu_ler(o) != d for o, d in volta.items())
    return {"linhas": len(escrito), "erros": erros, "linhas_volta": len(volta),
            "erros_volta": erros_volta,
            "entrega_us": max(t["tempo_us"] for t in tempos),
            "descarregadas": sum(t["linhas_descarregadas"] for t in tempos)}


def sem_protocolo(banco, rng, linhas=200):
    """Mesma escrita, mas entregando o rank sem descarregar a cache: a GPU lê o que era antes."""
    for r in range(RANKS):
        banco.entregar(r, "CPU")
    janela = int(CANAIS_GPU * RANKS * CHIP_REAL_GB * 2**30)
    escrito = {}
    for _ in range(linhas):
        a = rng.randrange(0, janela, LINHA_CPU_B)
        escrito[a] = _dados(rng, LINHA_CPU_B)
        banco.cpu_gravar(a, escrito[a])
    for r in range(RANKS):
        banco.entregar(r, "GPU", protocolo=False)
    velhos = sum(b"".join(banco.gpu_ler(a + k) or b"" for k in range(0, LINHA_CPU_B, SETOR_GPU_B)) != d
                 for a, d in escrito.items())
    banco.cache_cpu.clear()
    return {"linhas": len(escrito), "lidas_velhas": velhos}


def posse(banco, rng):
    """Cada lado só toca o rank que é dele; o resto é recusado e contado."""
    banco.entregar(0, "GPU")
    banco.entregar(1, "CPU")
    antes = Counter(banco.eventos)
    metade = int(CANAIS_GPU * CHIP_REAL_GB * 2**30)
    for _ in range(50):
        banco.gpu_ler(rng.randrange(metade, 2 * metade, SETOR_GPU_B))       # rank 1 é da CPU
        banco._ponte_ler(rng.randrange(0, metade, LINHA_CPU_B) // LINHA_CPU_B)   # rank 0 é da GPU
    d = banco.eventos - antes
    refresh = CANAIS_GPU / (TREFI_GDDR7_US * 1e-6)
    return {"gpu_recusadas": d["gpu_fora_da_posse"], "cpu_recusadas": d["cpu_fora_da_posse"],
            "refresh_absorvidos_por_s": refresh}


def simular(semente=0, ida_ns=0.6, volta_ns=None, diferenca_fibra_mm=0.0):
    rng = random.Random(semente)
    banco = Banco(mapa_gpu_aleatorio(rng), mapa_cpu_aleatorio(rng))
    cal = calibrar(banco, rng)
    out = {"capacidade": capacidade(), "calibracao": cal,
           "latencia": latencia_ponte(ida_ns, volta_ns), "seletor": seletor(diferenca_fibra_mm),
           "llm": llm()}
    out["integridade"] = integridade(banco, rng)
    out["sem_protocolo"] = sem_protocolo(banco, rng)
    out["posse"] = posse(banco, rng)
    # um mapa fora da família (rank misturado com bit baixo): a calibração avisa
    rng2 = random.Random(semente + 1)
    b2 = Banco(mapa_gpu_aleatorio(rng2, rank_no_topo=False), mapa_cpu_aleatorio(rng2))
    out["rank_misturado"] = calibrar(b2, rng2)["rank_contiguo"]
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(simular(), indent=1, ensure_ascii=False, default=str))
