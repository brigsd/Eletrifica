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
- [ ] **1. RTL — Verilator + cocotb + Yosys** (`modulos/rtl/`, em andamento por
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

Cada etapa: instalar, documentar no `CLAUDE.md`, teste no pytest (pulado com aviso
se a ferramenta faltar), job na CI quando couber, relatório gerado por script.

## Decisões

- 2026-10-30 — Dono: hardware (RTL) segue em paralelo; motores entram como
  módulos; ordem sugerida: memória primeiro, depois elétrico e EM.

## Histórico

- 2026-10-30 — Plano aberto. Etapa 1 já iniciada antes do plano.
