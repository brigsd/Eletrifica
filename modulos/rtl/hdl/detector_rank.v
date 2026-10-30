// Detector de rank: lê o primeiro ciclo de cada comando e decide qual dos dois chips
// atende. ACT: o bit mais alto da linha (linha[16]) escolhe o chip e fica guardado por
// banco; RD/WR/PRE: o rank aberto naquele banco; REF, MRS e treino (WRTR/RDTR) vão aos
// dois. A decisão é combinacional no primeiro ciclo e fica guardada para o segundo.
module detector_rank (
    input  wire        clk,
    input  wire        rst,
    input  wire [13:0] ca,
    output wire        primeiro,
    output wire [4:0]  cod,
    output wire [4:0]  banco,
    output wire        rank,         // chip escolhido para esta palavra
    output wire        difusao,      // vai aos dois chips
    output wire        nop           // palavra sem comando (NOP no primeiro ciclo)
);
`include "comandos.vh"
    wire [2:0] linha_alta;
    decod_ca dec (.clk(clk), .rst(rst), .ca(ca), .primeiro(primeiro), .cod(cod),
                  .banco(banco), .linha_alta(linha_alta));

    reg [31:0] aberto_rank;          // rank da linha aberta em cada banco
    reg        rank_q, dif_q;

    wire e_act = cod == CMD_ACT;
    wire e_dif = cod == CMD_REF || cod == CMD_MRS || cod == CMD_WRTR || cod == CMD_RDTR;
    wire rank_1 = e_act ? linha_alta[2] : aberto_rank[banco];

    assign rank    = primeiro ? rank_1 : rank_q;
    assign difusao = primeiro ? e_dif  : dif_q;
    assign nop     = primeiro && cod == CMD_NOP;

    always @(posedge clk) begin
        if (rst) begin
            aberto_rank <= 32'd0;
            rank_q <= 1'b0;
            dif_q  <= 1'b0;
        end else if (primeiro) begin
            rank_q <= rank_1;
            dif_q  <= e_dif;
            if (e_act) aberto_rank[banco] <= linha_alta[2];
        end
    end
endmodule
