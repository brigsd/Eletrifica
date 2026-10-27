"""Minimal S-expression reader for KiCad .kicad_sym libraries.

Used to lift stock symbol definitions out of the system KiCad libraries so the
generated schematic embeds everything it needs and opens on any machine.
"""
from pathlib import Path

SYMDIR = Path("/usr/share/kicad/symbols")


def tokenize(text):
    tokens, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    buf.append(text[j:j + 2])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append('"' + "".join(buf) + '"')
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def parse(text):
    tokens = tokenize(text)
    pos = 0

    def node():
        nonlocal pos
        assert tokens[pos] == "("
        pos += 1
        out = []
        while tokens[pos] != ")":
            out.append(node() if tokens[pos] == "(" else tokens[pos])
            if tokens[pos - 1] != ")" and tokens[pos] != "(" and out and out[-1] == tokens[pos]:
                pos += 1
        pos += 1
        return out

    # simpler: iterative
    pos = 0

    def node2():
        nonlocal pos
        tok = tokens[pos]
        if tok == "(":
            pos += 1
            out = []
            while tokens[pos] != ")":
                out.append(node2())
            pos += 1
            return out
        pos += 1
        return tok

    return node2()


def dump(node, indent=0):
    if isinstance(node, str):
        return node
    pad = "  " * indent
    inner = " ".join(
        dump(c, indent + 1) if isinstance(c, str) else "\n" + "  " * (indent + 1) + dump(c, indent + 1)
        for c in node
    )
    return "(" + inner + ")"


def unquote(s):
    return s[1:-1] if isinstance(s, str) and s.startswith('"') else s


_cache = {}


def load_lib(name):
    if name not in _cache:
        _cache[name] = parse((SYMDIR / f"{name}.kicad_sym").read_text())
    return _cache[name]


def find_symbol(lib, symname):
    for child in load_lib(lib):
        if isinstance(child, list) and child and child[0] == "symbol" and unquote(child[1]) == symname:
            return child
    raise KeyError(f"{lib}:{symname}")


def resolve(lib, symname):
    """Return a symbol definition with any (extends ...) flattened in."""
    sym = [c for c in find_symbol(lib, symname)]
    parent = None
    for c in sym:
        if isinstance(c, list) and c and c[0] == "extends":
            parent = unquote(c[1])
    if parent is None:
        return sym
    base = resolve(lib, parent)
    sym = [c for c in sym if not (isinstance(c, list) and c and c[0] == "extends")]
    for c in base:
        if isinstance(c, list) and c and c[0] == "symbol":
            renamed = [x for x in c]
            renamed[1] = '"' + unquote(c[1]).replace(parent, symname, 1) + '"'
            sym.append(renamed)
    return sym


def pins(sym):
    """Map pin number -> (x, y) connection point, in symbol space."""
    out = {}

    def walk(node):
        if not isinstance(node, list):
            return
        if node and node[0] == "pin":
            at = num = None
            for c in node:
                if isinstance(c, list) and c and c[0] == "at":
                    at = (float(c[1]), float(c[2]))
                if isinstance(c, list) and c and c[0] == "number":
                    num = unquote(c[1])
            if at and num:
                out[num] = at
        for c in node:
            walk(c)

    walk(sym)
    return out
