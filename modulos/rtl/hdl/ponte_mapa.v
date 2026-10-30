// Núcleo da ponte: o endereço DDR5 que chega pelos pinos (subcanal, coluna, banco, rank,
// linha) vira o local GDDR7 no layout da GPU, com os mapas aprendidos no boot. É a mesma
// conta de memoria_unificada.Banco._ponte_local:
//   L = h·2^28 | Minv_cpu · bits ;  n = L >> 2 ;  t = n mod 3 ;  m = n div 3 ;
//   y = M_gpu · m  ->  coluna, q, banco, linha ;  canal = 4·grupos[t] + q
// As matrizes são GF(2): cada bit de saída é a paridade (árvore de XOR) da entrada
// mascarada pela linha da matriz. São carregadas pelo FPGA no fim da calibração.
// Um registro na saída.
module ponte_mapa (
    input  wire        clk,
    // carga das matrizes aprendidas
    input  wire        carga,
    input  wire [1:0]  carga_qual,   // 0: inversa da CPU, 1: GPU, 2: grupos
    input  wire [4:0]  carga_idx,
    input  wire [27:0] carga_dado,
    // campos DDR5 dos pinos
    input  wire        sub,
    input  wire [6:0]  coluna,
    input  wire [4:0]  banco,
    input  wire        rank,
    input  wire [15:0] linha,
    // local GDDR7
    output reg  [3:0]  g_canal,
    output reg  [3:0]  g_banco,
    output reg  [16:0] g_linha,
    output reg  [2:0]  g_coluna,
    output reg  [7:0]  g_byte
);
    reg [27:0] minv [0:27];
    reg [25:0] mgpu [0:25];
    reg [1:0]  grupo [0:2];
    always @(posedge clk)
        if (carga) begin
            if (carga_qual == 2'd0) minv[carga_idx] <= carga_dado;
            if (carga_qual == 2'd1) mgpu[carga_idx] <= carga_dado[25:0];
            if (carga_qual == 2'd2) grupo[carga_idx[1:0]] <= carga_dado[1:0];
        end

    wire [27:0] bits = {linha[13:0], rank, banco, coluna, sub};
    reg  [27:0] l;
    reg  [25:0] y;
    integer k;
    wire [29:0] L = {linha[15:14], l};
    wire [27:0] n = L[29:2];
    wire [27:0] m28 = n / 28'd3;
    wire [25:0] m = m28[25:0];
    wire [27:0] t28 = n % 28'd3;
    wire [1:0]  t = t28[1:0];
    always @(*) begin
        for (k = 0; k < 28; k = k + 1) l[k] = ^(bits & minv[k]);
        y = 26'd0;
        for (k = 0; k < 26; k = k + 1) y[k] = ^(m & mgpu[k]);
    end
    always @(posedge clk) begin
        g_coluna <= y[2:0];
        g_canal  <= {grupo[t], y[4:3]};
        g_banco  <= y[8:5];
        g_linha  <= y[25:9];
        g_byte   <= {L[1:0], 6'd0};
    end
endmodule
