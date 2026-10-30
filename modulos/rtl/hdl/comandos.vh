// GERADO por python3 -m modulos.rtl.gerar a partir de modulos/dados/comandos.py.
// Não edite: mude a tabela em Python e gere de novo.
// Codificação de comando da GDDR7-32, 14 bits de CA por ciclo de CK.
localparam CA_W = 14;
localparam [4:0] CMD_ACT = 5'b00001;   // 2 ciclo(s)
localparam [4:0] CMD_MRS = 5'b00110;   // 2 ciclo(s)
localparam [4:0] CMD_WR = 5'b01010;   // 2 ciclo(s)
localparam [4:0] CMD_RD = 5'b01110;   // 2 ciclo(s)
localparam [4:0] CMD_WRTR = 5'b10010;   // 2 ciclo(s)
localparam [4:0] CMD_RDTR = 5'b10110;   // 2 ciclo(s)
localparam [4:0] CMD_REF = 5'b11001;   // 1 ciclo(s)
localparam [4:0] CMD_PRE = 5'b11011;   // 1 ciclo(s)
localparam [4:0] CMD_NOP = 5'b11111;   // 1 ciclo(s)
localparam integer RL_CHIP = 32;      // CK: CL de 12.0 ns
localparam integer WL_CHIP = 27;      // CK: CWL de 10.0 ns
localparam integer RL_EXTRA = 2;      // CK a mais que o chip emulado declara
function dois_ciclos(input [4:0] c);
    dois_ciclos = c == CMD_ACT || c == CMD_MRS || c == CMD_WR || c == CMD_RD || c == CMD_WRTR || c == CMD_RDTR;
endfunction
