// Decodificador do barramento CA da GDDR7: separa o primeiro ciclo de cada comando
// (onde estão código, banco e os bits altos da linha) do segundo.
module decod_ca (
    input  wire        clk,
    input  wire        rst,
    input  wire [13:0] ca,
    output wire        primeiro,     // esta palavra é o primeiro ciclo de um comando
    output wire [4:0]  cod,          // código do comando (válido no primeiro ciclo)
    output wire [4:0]  banco,
    output wire [2:0]  linha_alta    // linha[16:14] do ACT
);
`include "comandos.vh"
    reg segundo;
    assign primeiro   = !segundo;
    assign cod        = ca[4:0];
    assign banco      = ca[9:5];
    assign linha_alta = ca[12:10];
    always @(posedge clk)
        if (rst) segundo <= 1'b0;
        else     segundo <= primeiro && dois_ciclos(ca[4:0]);
endmodule
