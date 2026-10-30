// Mux de posse: cada rank (os chips da mesma posição) tem um dono, a GPU (0) ou a ponte (1).
// O FPGA pede a troca; ela só acontece quando o chip está parado: nenhum comando no meio,
// nenhum dado em voo (RL/WL + burst), nenhum banco aberto e nenhum refresh correndo.
// Depois da troca o mux leva ao chip o CA (e o dado de escrita) do novo dono, e `pronto`
// pulsa um ciclo para o FPGA.
module mux_posse #(parameter W = 32, parameter BL = 2, parameter TRFC = 747, parameter TMRD = 8) (
    input  wire          clk,
    input  wire          rst,
    input  wire [13:0]   gpu_ca0,     // do seletor de rank
    input  wire [13:0]   gpu_ca1,
    input  wire [13:0]   ponte_ca0,
    input  wire [13:0]   ponte_ca1,
    input  wire [W-1:0]  gpu_dq,      // escrita da GPU, ainda sem o registro do seletor
    input  wire [W-1:0]  ponte_dq0,
    input  wire [W-1:0]  ponte_dq1,
    input  wire          pedido,      // do FPGA
    input  wire          pedido_rank,
    input  wire          pedido_dono,
    output reg  [1:0]    dono,
    output reg           pronto,
    output wire [1:0]    ocupado,
    output wire [13:0]   chip_ca0,
    output wire [13:0]   chip_ca1,
    output wire [W-1:0]  chip_dq0,
    output wire [W-1:0]  chip_dq1
);
`include "comandos.vh"
    reg [W-1:0] gpu_dq_q;
    always @(posedge clk) gpu_dq_q <= gpu_dq;

    assign chip_ca0 = dono[0] ? ponte_ca0 : gpu_ca0;
    assign chip_ca1 = dono[1] ? ponte_ca1 : gpu_ca1;
    assign chip_dq0 = dono[0] ? ponte_dq0 : gpu_dq_q;
    assign chip_dq1 = dono[1] ? ponte_dq1 : gpu_dq_q;

    wire [1:0] livre;
    genvar r;
    generate for (r = 0; r < 2; r = r + 1) begin : chip
        wire [13:0] ca = (r == 0) ? chip_ca0 : chip_ca1;
        wire prim;
        wire [4:0] cod, banco;
        wire [2:0] la;
        decod_ca dec (.clk(clk), .rst(rst), .ca(ca), .primeiro(prim), .cod(cod), .banco(banco),
                      .linha_alta(la));
        reg [31:0] abertos;
        reg [4:0]  voo_alto, voo_baixo;
        reg        sem_voo, sem_abertos;     // registrados: tiram a comparação do caminho da troca
        wire carrega = prim && (cod == CMD_RD || cod == CMD_RDTR || cod == CMD_WR || cod == CMD_WRTR
                                || cod == CMD_REF || cod == CMD_MRS);
        wire [31:0] abertos_prox = (prim && cod == CMD_ACT) ? (abertos | (32'd1 << banco)) :
                                   (prim && cod == CMD_PRE) ? (abertos & ~(32'd1 << banco)) : abertos;
        always @(posedge clk) begin
            if (rst) begin
                abertos <= 32'd0;
                voo_alto <= 5'd0;
                voo_baixo <= 5'd0;
                sem_voo <= 1'b1;
                sem_abertos <= 1'b1;
            end else begin
                abertos <= abertos_prox;
                // = (abertos_prox == 0), sem passar pelo mux do ACT
                sem_abertos <= !(prim && cod == CMD_ACT) &&
                               (abertos & ~((prim && cod == CMD_PRE) ? (32'd1 << banco) : 32'd0)) == 32'd0;
                sem_voo <= !carrega && voo_alto == 5'd0 && voo_baixo <= 5'd1;
                // contador em duas metades de 5 bits: o empréstimo da de baixo para a de
                // cima vem de um registro, e o caminho fica no tamanho de um contador de 5 bits
                if (prim && (cod == CMD_RD || cod == CMD_RDTR))
                    {voo_alto, voo_baixo} <= RL_CHIP + BL;
                else if (prim && (cod == CMD_WR || cod == CMD_WRTR))
                    {voo_alto, voo_baixo} <= WL_CHIP + BL;
                else if (prim && cod == CMD_REF)
                    {voo_alto, voo_baixo} <= TRFC;
                else if (prim && cod == CMD_MRS)
                    {voo_alto, voo_baixo} <= TMRD;
                else if (voo_baixo != 5'd0)
                    voo_baixo <= voo_baixo - 5'd1;
                else if (voo_alto != 5'd0) begin
                    voo_alto <= voo_alto - 5'd1;
                    voo_baixo <= 5'd31;
                end
            end
        end
        assign livre[r] = prim && cod == CMD_NOP && sem_abertos && sem_voo;
    end endgenerate
    assign ocupado = ~livre;

    reg pend, pend_rank, pend_dono;
    always @(posedge clk) begin
        if (rst) begin
            dono <= 2'b00;
            pronto <= 1'b0;
            pend <= 1'b0;
            pend_rank <= 1'b0;
            pend_dono <= 1'b0;
        end else begin
            pronto <= 1'b0;
            if (pedido && !pend) begin
                pend <= 1'b1;
                pend_rank <= pedido_rank;
                pend_dono <= pedido_dono;
            end else if (pend && livre[pend_rank]) begin
                dono[pend_rank] <= pend_dono;
                pend <= 1'b0;
                pronto <= 1'b1;
            end
        end
    end
endmodule
