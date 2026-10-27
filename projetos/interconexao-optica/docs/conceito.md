# Conceito: Protótipo de Interconexão Modular Óptica

Transcrição do documento de conceito do dono do projeto
([original](https://claude.ai/artifact/3NMHV7qQad9bxKu82cApAJ)) e do documento de
passagem que o acompanhou. É a especificação que os simuladores em `modulos/`
seguem; os resultados estão em [`resultados.md`](resultados.md).

## Objetivo

Substituir a placa-mãe convencional por uma base moldável e modular, em que CPU,
GPU e memória podem ser encaixadas em qualquer posição. O aparelho identifica
cada componente, alimenta cada um de forma dinâmica e transporta os dados por
fibra óptica, convertendo os sinais elétricos nativos em luz e de volta.

Referência: Intel i5-13600KF (LGA1700), memória DDR5, GPU com GDDR7.
Arquitetura preparada para DDR6.

## Arquitetura em camadas

| Camada | Função | Materiais propostos |
|--------|--------|---------------------|
| Acoplamento | Contato com os pinos de cada componente, sem curto entre vizinhos | Elastômero condutivo anisotrópico de silicone com microfios banhados a ouro, mais finos e densos que os contatos |
| Energia | Levar corrente a cada contato de alimentação | Microfilamentos de cobre para ~1 A por contato, plano de cobre contínuo, chaves de potência de baixa capacitância por célula |
| Tradução | Converter sinal elétrico em luz e de volta, junto de cada componente | Moduladores e fotodetectores em fotônica de silício, copiando o sinal de cada pino sem decodificar |
| Transporte | Levar os dados entre componentes | Fibra óptica com multiplexação por comprimento de onda |
| Isolamento e suporte | Separar condutores e dar flexibilidade | Polímero de cristal líquido (LCP) com filamentos de terra intercalados |
| Orquestração | Identificar, configurar e gerenciar tudo | FPGA de alto desempenho, reguladores digitais e chip de firmware UEFI |

## Encaixe do processador (i5-13600KF, LGA1700)

1. **Contato** — elastômero com vários microfios por contato; dispensa
   alinhamento perfeito e cria redundância.
2. **Fixação** — moldura de pressão uniforme, compatível com os furos de coolers LGA1700.
3. **Mapeamento** — antes de energizar, sinais de teste fracos detectam os padrões
   de terra e alimentação, comparados com a pinagem publicada.
4. **Configuração das células** — energia, terra, DDR5, PCIe e sinais auxiliares.
5. **Inicialização** — firmware UEFI, relógios de referência (100 MHz para PCIe),
   sequência de energização, reset e funções mínimas de chipset.

## Energia

- **CPU**: 12 V da fonte, regulador multifásico junto do processador, controlado
  pelo protocolo de tensão do próprio chip (SVID), capacitores de desacoplamento
  sob o encaixe. Mais de 200 A distribuídos por centenas de contatos, ~1 A cada.
- **DDR5**: entrada estável (5 V); o PMIC do módulo faz o ajuste fino.
- **GPU**: cabos de alimentação da fonte.
- **Segurança**: nenhum setor é energizado antes da identificação; limitação de
  corrente e desligamento imediato em caso de curto.

## Comunicação

- O processador mantém o controle e fala seus protocolos nativos (DDR5, PCIe).
- O aparelho roteia cada sinal até o destino e fornece a infraestrutura de inicialização.
- A reconfiguração entre CPU e RAM acontece antes da inicialização, porque o
  treinamento de memória depende de caminho estável.
- Memória compartilhada entre componentes mediada pelo FPGA via CXL.

## Enlace óptico da GDDR7 (paralelismo)

Um pino, um canal: 384 pinos de dados a 32 Gb/s (~1,5 TB/s) em 6 fibras com 64
comprimentos de onda cada. Tradutor sem decodificação, atraso abaixo de 1 ns em
poucos centímetros. Moduladores em anel de ~10 µm, com aquecedor e controle
térmico em malha fechada.

Cálculo de enlace do documento (valores típicos de literatura):

| Critério | Configuração original | Configuração ajustada |
|----------|----------------------|-----------------------|
| Banda total | 1,54 TB/s em 6 fibras | igual |
| Atraso | 0,34 ns | igual |
| Lasers | 1 laser de 10 mW para 64 canais | 1 laser de 10 mW para cada 16 canais |
| Perdas totais | 10 dB | 7,5 dB |
| Margem de potência | −6,1 dB (reprovado) | +2,5 dB (aprovado) |
| Tolerância térmica | ±1 °C sem controle | controle ativo por anel |

`modulos.optica.enlace.calculo_simples` reproduz esse cálculo exatamente.

## Plano de validação

| Etapa | Teste | Critério de aprovação |
|-------|-------|----------------------|
| 1. Acoplamento | Encaixar componentes em posições variadas | Todos os contatos reconhecidos, resistência estável |
| 2. Mapeamento | Trocar componentes de lugar e reiniciar | Identificação correta em todas as posições |
| 3. Energia | Ligar a CPU sob carga variável | Tensão estável, sem desligamentos |
| 4. Enlace óptico | Transmitir dados entre dois tradutores pela fibra | Taxa de erros e atraso dentro do limite da DDR5 |
| 5. Sistema completo | CPU, GPU e RAM ao mesmo tempo | Desempenho comparável a uma placa-mãe comum |

Prioridade: etapa 4, que concentra o maior risco técnico.
