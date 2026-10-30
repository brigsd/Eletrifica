// Seletor de rank: põe o comando no chip escolhido e NOP no outro (um registro: 1 CK),
// e faz o mux de leitura do DQ (outro registro: 1 CK). Os dois CK são o RL_EXTRA que o
// chip emulado declara à GPU, então o dado chega exatamente em RL_CHIP + RL_EXTRA.
module seletor_rank #(parameter W = 32, parameter BL = 2) (
    input  wire          clk,
    input  wire          rst,
    input  wire [13:0]   ca,
    input  wire          primeiro,
    input  wire [4:0]    cod,
    input  wire          rank,
    input  wire          difusao,
    input  wire [1:0]    dono,       // 1 = rank com a ponte
    output reg  [13:0]   ca_r0,
    output reg  [13:0]   ca_r1,
    input  wire [W-1:0]  dq_r0,      // leitura vinda de cada chip
    input  wire [W-1:0]  dq_r1,
    output reg  [W-1:0]  dq_gpu,
    output reg           dq_valido
);
`include "comandos.vh"
    localparam [13:0] NOP_CA = {9'd0, CMD_NOP};
    localparam integer RL_GPU = RL_CHIP + RL_EXTRA;
    localparam integer P = RL_GPU + BL;

    always @(posedge clk) begin
        if (rst) begin
            ca_r0 <= NOP_CA;
            ca_r1 <= NOP_CA;
        end else begin
            ca_r0 <= (difusao || rank == 1'b0) ? ca : NOP_CA;
            ca_r1 <= (difusao || rank == 1'b1) ? ca : NOP_CA;
        end
    end

    // quem devolve a leitura: o rank do RD; no RDTR, o primeiro rank da GPU (se nenhum
    // for dela, quem responde é o emulador de manutenção)
    wire lido = primeiro && ((cod == CMD_RD && !dono[rank]) || (cod == CMD_RDTR && dono != 2'b11));
    wire fonte = (cod == CMD_RDTR) ? dono[0] : rank;
    reg [P-1:0] vpipe;
    reg [P-1:0] rpipe;
    always @(posedge clk) begin
        if (rst) begin
            vpipe <= {P{1'b0}};
            rpipe <= {P{1'b0}};
        end else begin
            vpipe <= {vpipe[P-2:0], lido};
            rpipe <= {rpipe[P-2:0], fonte};
        end
    end
    // estágio k vale no ciclo t+1+k; o registro de saída carrega em t+RL_GPU-1+j
    integer j;
    reg sel_v, sel_r;
    always @(*) begin
        sel_v = 1'b0;
        sel_r = 1'b0;
        for (j = 0; j < BL; j = j + 1)
            if (vpipe[RL_GPU-2+j]) begin
                sel_v = 1'b1;
                sel_r = rpipe[RL_GPU-2+j];
            end
    end
    always @(posedge clk) begin
        if (rst) begin
            dq_gpu <= {W{1'b0}};
            dq_valido <= 1'b0;
        end else begin
            dq_gpu <= sel_r ? dq_r1 : dq_r0;
            dq_valido <= sel_v;
        end
    end
endmodule
