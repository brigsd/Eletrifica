// O que fica no tradutor sob o rank 0 de um par de chips GDDR7: detector e seletor de
// rank, mux de posse e emulador de manutenção. Do lado da GPU, um chip de 32 Gb; do
// lado dos chips, dois de 16 Gb; do lado da ponte, um CA e um DQ por chip.
module par_rank #(parameter W = 32, parameter BL = 2, parameter TRFC = 747) (
    input  wire          clk,
    input  wire          rst,
    // GPU
    input  wire [13:0]   gpu_ca,
    input  wire [W-1:0]  gpu_dq_w,
    output wire [W-1:0]  gpu_dq_r,
    output wire          gpu_dq_valido,
    // ponte
    input  wire [13:0]   ponte_ca0,
    input  wire [13:0]   ponte_ca1,
    input  wire [W-1:0]  ponte_dq0,
    input  wire [W-1:0]  ponte_dq1,
    input  wire [1:0]    ponte_ref,
    input  wire [1:0]    mrs_restaurado,
    // FPGA
    input  wire          pedido,
    input  wire          pedido_rank,
    input  wire          pedido_dono,
    output wire [1:0]    dono,
    output wire          pronto,
    output wire [1:0]    ocupado,
    output wire [3:0]    ref_devido0,
    output wire [3:0]    ref_devido1,
    output wire [1:0]    mrs_pendente,
    output wire [7:0]    violacoes,
    // chips
    output wire [13:0]   chip_ca0,
    output wire [13:0]   chip_ca1,
    output wire [W-1:0]  chip_dq_w0,
    output wire [W-1:0]  chip_dq_w1,
    input  wire [W-1:0]  chip_dq_r0,
    input  wire [W-1:0]  chip_dq_r1
);
    wire prim, rank, dif, nop;
    wire [4:0] cod, banco;
    detector_rank det (.clk(clk), .rst(rst), .ca(gpu_ca), .primeiro(prim), .cod(cod), .banco(banco),
                       .rank(rank), .difusao(dif), .nop(nop));
    wire [13:0] sel_ca0, sel_ca1;
    wire [W-1:0] sel_dq;
    wire sel_v;
    seletor_rank #(.W(W), .BL(BL)) sel (.clk(clk), .rst(rst), .ca(gpu_ca), .primeiro(prim), .cod(cod),
                       .rank(rank), .difusao(dif), .dono(dono), .ca_r0(sel_ca0), .ca_r1(sel_ca1),
                       .dq_r0(chip_dq_r0), .dq_r1(chip_dq_r1), .dq_gpu(sel_dq), .dq_valido(sel_v));
    mux_posse #(.W(W), .BL(BL), .TRFC(TRFC)) mux (.clk(clk), .rst(rst), .gpu_ca0(sel_ca0), .gpu_ca1(sel_ca1),
                       .ponte_ca0(ponte_ca0), .ponte_ca1(ponte_ca1), .gpu_dq(gpu_dq_w),
                       .ponte_dq0(ponte_dq0), .ponte_dq1(ponte_dq1), .pedido(pedido),
                       .pedido_rank(pedido_rank), .pedido_dono(pedido_dono), .dono(dono), .pronto(pronto),
                       .ocupado(ocupado), .chip_ca0(chip_ca0), .chip_ca1(chip_ca1),
                       .chip_dq0(chip_dq_w0), .chip_dq1(chip_dq_w1));
    wire [W-1:0] emu_dq;
    wire emu_v;
    emulador_manutencao #(.W(W), .BL(BL)) emu (.clk(clk), .rst(rst), .ca(gpu_ca), .primeiro(prim),
                       .cod(cod), .rank(rank), .difusao(dif), .dono(dono), .dq_gpu_in(gpu_dq_w),
                       .ponte_ref(ponte_ref), .mrs_restaurado(mrs_restaurado), .ref_devido0(ref_devido0),
                       .ref_devido1(ref_devido1), .mrs_pendente(mrs_pendente), .violacoes(violacoes),
                       .emu_dq(emu_dq), .emu_valido(emu_v));
    assign gpu_dq_r = emu_v ? emu_dq : sel_dq;
    assign gpu_dq_valido = emu_v | sel_v;
endmodule
