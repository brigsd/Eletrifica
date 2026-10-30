// Emulador de manutenção: enquanto um rank é da ponte, o chip dele não ouve a GPU. Mas a
// GPU continua achando que o chip é dela e manda refresh, MRS e treino periódico. A base:
//  - absorve o REF e conta quantos o chip ficou devendo (até 15; o padrão deixa adiar 8) (a ponte faz esses refreshes
//    no chip e avisa por `ponte_ref`);
//  - guarda o MRS numa sombra (16 registradores) e levanta `mrs_pendente`, para a ponte
//    reaplicar ao devolver o rank;
//  - responde o treino: a FIFO de treino recebe o que o WRTR escreve (no WL) e o RDTR
//    lê de volta no RL que a GPU espera (RL_CHIP + RL_EXTRA), quando nenhum rank é da GPU;
//  - conta como violação ACT/RD/WR/PRE da GPU num rank que não é dela.
// Simplificação do JESD239: FIFO de treino de 4 entradas, sem os padrões LFSR, sem
// WCK2CK e sem o treino de VREF/CA; ver docs/rtl.md.
module emulador_manutencao #(parameter W = 32, parameter BL = 2) (
    input  wire          clk,
    input  wire          rst,
    input  wire [13:0]   ca,
    input  wire          primeiro,
    input  wire [4:0]    cod,
    input  wire          rank,
    input  wire          difusao,
    input  wire [1:0]    dono,
    input  wire [W-1:0]  dq_gpu_in,      // escrita da GPU (WRTR)
    input  wire [1:0]    ponte_ref,      // a ponte deu um REF no chip r
    input  wire [1:0]    mrs_restaurado,
    output reg  [3:0]    ref_devido0,
    output reg  [3:0]    ref_devido1,
    output reg  [1:0]    mrs_pendente,
    output reg  [7:0]    violacoes,
    output reg  [W-1:0]  emu_dq,
    output reg           emu_valido
);
`include "comandos.vh"
    localparam integer RL_GPU = RL_CHIP + RL_EXTRA;
    localparam integer PR = RL_GPU + BL;
    localparam integer PW = WL_CHIP + BL;
    localparam integer BI = (BL > 1) ? $clog2(BL) : 1;

    // ---- refresh
    wire ref_gpu = primeiro && cod == CMD_REF;
    wire inc0 = ref_gpu && dono[0] && ref_devido0 != 4'hF, dec0 = ponte_ref[0] && ref_devido0 != 4'd0;
    wire inc1 = ref_gpu && dono[1] && ref_devido1 != 4'hF, dec1 = ponte_ref[1] && ref_devido1 != 4'd0;
    always @(posedge clk) begin
        if (rst) begin
            ref_devido0 <= 4'd0;
            ref_devido1 <= 4'd0;
        end else begin
            if (inc0 && !dec0) ref_devido0 <= ref_devido0 + 4'd1;
            if (dec0 && !inc0) ref_devido0 <= ref_devido0 - 4'd1;
            if (inc1 && !dec1) ref_devido1 <= ref_devido1 + 4'd1;
            if (dec1 && !inc1) ref_devido1 <= ref_devido1 - 4'd1;
        end
    end

    // ---- MRS na sombra
    reg [7:0] mr [0:15];
    reg       mrs_seg;
    reg [3:0] mrs_end;
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            mrs_seg <= 1'b0;
            mrs_pendente <= 2'b00;
            for (i = 0; i < 16; i = i + 1) mr[i] <= 8'd0;
        end else begin
            mrs_seg <= primeiro && cod == CMD_MRS && dono != 2'b00;
            if (primeiro && cod == CMD_MRS) mrs_end <= ca[8:5];
            if (mrs_seg) mr[mrs_end] <= ca[7:0];
            mrs_pendente <= (mrs_pendente | ({2{mrs_seg}} & dono)) & ~mrs_restaurado;
        end
    end

    // ---- violação de posse
    wire comum = cod == CMD_ACT || cod == CMD_RD || cod == CMD_WR || cod == CMD_PRE;
    always @(posedge clk)
        if (rst) violacoes <= 8'd0;
        else if (primeiro && comum && !difusao && dono[rank] && violacoes != 8'hFF)
            violacoes <= violacoes + 8'd1;

    // ---- FIFO de treino
    reg [BL*W-1:0] fifo [0:3];
    reg [1:0] wptr, rptr;
    reg [PW-1:0] wpipe;
    reg [PR-1:0] rpipe;
    reg [PR-1:0] epipe;           // a resposta é do emulador (decidido no RDTR)
    wire wrtr = primeiro && cod == CMD_WRTR;
    wire rdtr = primeiro && cod == CMD_RDTR;
    integer j;
    reg cap, cap_ult, resp, resp_ult, resp_emu;
    reg [BI-1:0] cap_beat, resp_beat;
    always @(*) begin
        cap = 1'b0; cap_ult = 1'b0; cap_beat = 0;
        resp = 1'b0; resp_ult = 1'b0; resp_beat = 0; resp_emu = 1'b0;
        for (j = 0; j < BL; j = j + 1) begin
            if (wpipe[WL_CHIP-1+j]) begin cap = 1'b1; cap_beat = j[BI-1:0]; cap_ult = (j == BL-1); end
            if (rpipe[RL_GPU-2+j])  begin resp = 1'b1; resp_beat = j[BI-1:0]; resp_ult = (j == BL-1); resp_emu = epipe[RL_GPU-2+j]; end
        end
    end
    always @(posedge clk) begin
        if (rst) begin
            wptr <= 2'd0; rptr <= 2'd0;
            wpipe <= {PW{1'b0}}; rpipe <= {PR{1'b0}}; epipe <= {PR{1'b0}};
            emu_valido <= 1'b0; emu_dq <= {W{1'b0}};
            for (i = 0; i < 4; i = i + 1) fifo[i] <= {BL{32'hA55A0000 | i}};
        end else begin
            wpipe <= {wpipe[PW-2:0], wrtr};
            rpipe <= {rpipe[PR-2:0], rdtr};
            epipe <= {epipe[PR-2:0], dono == 2'b11};
            if (cap) begin
                fifo[wptr][cap_beat*W +: W] <= dq_gpu_in;
                if (cap_ult) wptr <= wptr + 2'd1;
            end
            // responde só quando nenhum chip do par é da GPU; o ponteiro anda sempre
            emu_valido <= resp && resp_emu;
            emu_dq <= resp ? fifo[rptr][resp_beat*W +: W] : {W{1'b0}};
            if (resp && resp_ult) rptr <= rptr + 2'd1;
        end
    end
endmodule
