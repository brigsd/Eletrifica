// Núcleo da ponte: o endereço DDR5 que chega pelos pinos (subcanal, coluna, banco, rank,
// linha) vira o local GDDR7 no layout da GPU, com os mapas aprendidos no boot. É a mesma
// conta de memoria_unificada.Banco._ponte_local:
//   L = h·2^28 | Minv_cpu · bits ;  n = L >> 2 ;  t = n mod 3 ;  m = n div 3 ;
//   y = M_gpu · m  ->  coluna, q, banco, linha ;  canal = 4·grupos[t] + q
// As matrizes são GF(2): cada bit de saída é a paridade (árvore de XOR) da entrada
// mascarada pela linha da matriz. São carregadas pelo FPGA no fim da calibração.
// Um registro na saída. A divisão por 3 é a divisão longa com o resto como estado de
// 3 valores, resolvida por prefixo paralelo (Kogge-Stone): profundidade log2(N), não N.
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
    wire [27:0] m28;
    wire [1:0]  t;
    div3 #(.N(28)) d3 (.n(n), .q(m28), .r(t));
    wire [25:0] m = m28[25:0];
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

// n / 3 e n % 3 por prefixo paralelo. Cada bit (do mais alto ao mais baixo) é uma função
// de 3 estados r -> (2r + b) mod 3; o resto antes de cada bit é a composição das funções
// dos bits acima, aplicada a 0. Cada função cabe em 6 bits: {f(2), f(1), f(0)}.
module div3 #(parameter N = 28) (
    input  wire [N-1:0] n,
    output wire [N-1:0] q,
    output wire [1:0]   r
);
    function [5:0] comp(input [5:0] a, input [5:0] b);   // primeiro a, depois b
        integer k;
        reg [1:0] x;
        begin
            comp = 6'd0;
            for (k = 0; k < 3; k = k + 1) begin
                x = a[2*k +: 2];
                comp[2*k +: 2] = (x == 2'd0) ? b[1:0] : (x == 2'd1) ? b[3:2] : b[5:4];
            end
        end
    endfunction
    localparam integer L = $clog2(N);
    wire [5:0] p [0:L][0:N-1];
    genvar i, l;
    generate
        for (i = 0; i < N; i = i + 1) begin : folha            // dígito i = bit N-1-i
            assign p[0][i] = n[N-1-i] ? {2'd2, 2'd0, 2'd1} : {2'd1, 2'd2, 2'd0};
        end
        for (l = 1; l <= L; l = l + 1) begin : nivel
            for (i = 0; i < N; i = i + 1) begin : no
                if (i >= (1 << (l-1)))
                    assign p[l][i] = comp(p[l-1][i - (1 << (l-1))], p[l-1][i]);
                else
                    assign p[l][i] = p[l-1][i];
            end
        end
        for (i = 0; i < N; i = i + 1) begin : quociente
            wire [1:0] antes = (i == 0) ? 2'd0 : p[L][i-1][1:0];
            assign q[N-1-i] = antes == 2'd2 || (antes == 2'd1 && n[N-1-i]);
        end
    endgenerate
    assign r = p[L][N-1][1:0];
endmodule
