# Motores de simulação: ferramentas externas como módulos

Aberto em: 2026-10-30 · Responsável: Claude (sessões e subagentes)

## Objetivo

Tirar o simulador do "muito simulado": cada área pode ser calculada por um
**motor** — o modelo Python atual ou uma ferramenta externa de precisão. Cada
motor é um módulo com a mesma entrada e saída do modelo que substitui, para
trocar um pelo outro e **comparar os dois** (validação cruzada).

## Etapas

- [ ] **0. Contrato de motor.** Interface comum (entrada, saída, versão da
  ferramenta, tempo de execução) e escolha do motor por área em `montagem.json`.
  Pronto: o modelo Python atual registrado como motor padrão de cada área, sem
  mudar nenhum resultado.
- [x] **1. RTL — Verilator + cocotb + Yosys** (`modulos/rtl/`, em andamento por
  subagente). Seletor de rank, mux de posse, emulador de manutenção (refresh e
  treino da GPU). Pronto: testes ciclo a ciclo passando, latências medidas
  substituindo as declaradas, verificador com 0 erros.
- [ ] **2. Memória — Ramulator 2 ou DRAMSys.** Conferir suporte a GDDR7 (senão
  GDDR6 ajustada). Banco unificado com tráfego de LLM. Pronto: banda, latência e
  refresh do banco comparados com `memoria_unificada.py`.
- [ ] **3. Elétrico — ngspice.** Relé da célula, trilha, terminação. Pronto: banda
  da célula (R04) e queda IR comparadas.
- [ ] **4. Eletromagnético — openEMS.** Trilha e via em 3D. Pronto: perda por
  mm·GHz medida no lugar dos 0,004 declarados.
- [ ] **5. Fotônica — gdsfactory + SAX, Meep no anel.** Pronto: anel, filtro e
  diafonia comparados com `modulos/optica`.
- [ ] **6. Térmico — Elmer FEM.** Pronto: base em 3D comparada com a difusão 2D.
- [ ] **7. Sistema — gem5 e Accel-Sim.** CPU e GPU reais lendo o banco. Pronto:
  tokens/s simulado comparado com o teto atual.

- [ ] **8. PC do dono como poder de cálculo.** i5-13600KF, 32 GB DDR5, RTX 5070
  (12 GB GDDR7), ligado à sessão pelo Remote Control (Linux ou WSL). Pronto: os
  motores pesados (gem5, openEMS, Meep, Accel-Sim) rodando lá, com o resultado
  voltando ao repositório.
- [ ] **9. Bancada com hardware no circuito.** A 5070 e o i5 rodam programas
  reais; uma camada de software no meio imita o banco unificado (mapas de
  endereço, posse dos ranks, latências medidas no RTL). Não acelera o PC: prova
  que o software dos dois lados funciona com as regras do banco e mede o que um
  programa real perde ou ganha. Inclui medir por tempo de acesso o mapa de
  endereços real da DDR5 do i5 e da GDDR7 da 5070 (métodos DRAMA e GPUHammer)
  e conferir a calibração da ponte com eles. Pronto: kernel CUDA real lendo o
  que a CPU gravou "pela ponte", com 0 erros e o tempo do banco aplicado.

- [ ] **10. Arquitetura revisada, ao lado da atual.** Da revisão em
  `projetos/interconexao-optica/docs/revisao-arquitetura.md`: base em núcleo de
  vidro com guias de luz embutidos, cobre nos saltos curtos, luz só nos longos,
  peças em adaptadores sobre grade padrão (sem célula chaveada), soquete LGA1700
  real com a mecânica modelada, lasers desligados no caminho sem dono, banco
  unificado mantido. Pronto: as duas versões geradas pelo mesmo simulador, com
  consumo, temperatura, margens, erros do verificador e bloqueios do
  `viabilidade.md` lado a lado.

Cada etapa: instalar, documentar no `CLAUDE.md`, teste no pytest (pulado com aviso
se a ferramenta faltar), job na CI quando couber, relatório gerado por script.

## Decisões

- 2026-10-30 — Dono: hardware (RTL) segue em paralelo; motores entram como
  módulos; ordem sugerida: memória primeiro, depois elétrico e EM.

## Histórico

- 2026-10-30 — Plano aberto. Etapa 1 já iniciada antes do plano.
- 2026-10-30 — Etapas 8 e 9 acrescentadas: PC do dono (hardware real) como poder de cálculo e como bancada no circuito.
- 2026-10-30 — Revisão da arquitetura registrada; etapa 10 aberta (modelar a versão revisada ao lado da atual).
- 2026-10-30 — Etapa 1 concluída (commits 4077d41, cbaf9d3, f3bee15): emulador de manutenção provado ciclo a ciclo; latências medidas no Yosys (seletor 375 ps, detector 275 ps, ponte CL54). Ficou de fora: LFSR, WCK2CK e treino de VREF/CA; RTL das filas e PHY da ponte.
