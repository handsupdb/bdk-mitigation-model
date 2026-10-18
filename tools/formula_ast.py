#!/usr/bin/env python3
"""
formula_ast.py — standalone Excel-formula parser for the transpiler pipeline.

Tokenizer + recursive-descent parser logic copied from extracted/verify_chains.py
(the evaluator/verifier there proved this grammar against every formula in all
13 data sheets of excel_mitigation_model.xlsx). Self-contained: no imports from
extracted/.

Handles: cell refs incl. $ anchors and quoted sheet names ('+Weapon DPS'!$N$15)
and unqualified sheet names (Inputs!C7); ranges A1:B2; strings with "" escapes;
numbers incl. scientific notation; % postfix; ^ (left-assoc, unary minus binds
tighter, per Excel); unary +/-; * / + -; & concatenation; comparisons
= <> < > <= >=; parentheses; TRUE/FALSE (as 1.0/0.0); function calls for the
known function set FN below (case-insensitive); empty call args (as 0.0).

parse(formula_str, sheet=None) -> nested-dict AST:
  {'type': 'num',   'value': float}
  {'type': 'str',   'value': str}
  {'type': 'ref',   'sheet': str|None, 'ref': 'A1'}        # $ stripped, col upper
  {'type': 'range', 'sheet': str|None, 'start': 'A1', 'end': 'B2'}
  {'type': 'binop', 'op': '+', 'left': ..., 'right': ...}
  {'type': 'unop',  'op': '-'|'%', 'operand': ...}
  {'type': 'func',  'name': 'SUM', 'args': [...]}
Unqualified refs get `sheet` (the containing sheet, e.g. the CLI <sheet> arg).

Limitations inherited from the proven verify_chains.py parser:
  - only whitelisted functions (FN); others (ROUNDUP, MOD, ...) -> SyntaxError
  - no named ranges / defined names (bare idents other than TRUE/FALSE fail)
  - no whole-column/row refs (A:A, 1:1), array constants {1,2}, 3-D refs,
    reference unions/intersections
  - a range tail's second sheet qualifier is ignored (Sheet1!A1:Sheet1!B2 ok)
  - booleans become num 1.0/0.0; empty args become num 0.0; unary + is a no-op

CLI: .venv/bin/python tools/formula_ast.py <sheet> <cell_ref>
  Loads extracted/<sheet>__formulas.tsv (+Stat sheets use leading-underscore
  filenames, e.g. '+Weapon DPS' -> _Weapon_DPS), parses that cell's formula,
  prints the AST as JSON, depth-capped at 8 and breadth-capped so the output
  stays <= 60 lines (subtrees that fit on one line are inlined; capped lists
  end with a '...+N' marker; '...' marks nodes cut by the depth cap).
  parse() itself is uncapped.
"""
import json
import os
import re
import sys

TSV_DIR = "extracted"

# +Stat sheets are stored with leading-underscore filenames (from verify_chains.py)
STAT_SHEETS = {
    "+Armor": "_Armor", "+Strength": "_Strength", "+Stamina": "_Stamina",
    "+Critical Strike": "_Critical_Strike", "+Haste": "_Haste",
    "+Versatility": "_Versatility", "+Mastery": "_Mastery", "+Leech": "_Leech",
    "+Avoidance": "_Avoidance", "+Weapon DPS": "_Weapon_DPS",
}

# ---------------------------------------------------------------- tokenizer
# (copied verbatim from extracted/verify_chains.py)
TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"]|"")*")
  | (?P<sheetref>'(?:[^']|'')*'!|[A-Za-z_][A-Za-z0-9_ ]*!)
  | (?P<ref>\$?[A-Za-z]{1,3}\$?[0-9]+)
  | (?P<ident>[A-Za-z][A-Za-z0-9_.]*)
  | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<op><>|<=|>=|[=<>+\-*/^%&(),:])
""", re.VERBOSE)


def tokenize(text):
    toks, i = [], 0
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m:
            raise SyntaxError(f"bad char {text[i]!r} at {i} in {text[:60]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        toks.append((kind, m.group()))
    return toks


# ---------------------------------------------------------------- parser
# Grammar copied from verify_chains.py; emits nested-dict AST nodes instead of
# its Node objects. Function-call handling (there a monkey-patch on primary)
# is integrated directly into primary().
FN = {"IF", "MIN", "MAX", "SUM", "ABS", "SQRT", "EXP", "INT", "ROUND",
      "AND", "OR", "NOT", "ISBLANK", "TRUE", "FALSE", "AVERAGE", "COUNT", "N"}


def split_ref(ref):
    m = re.match(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$", ref)
    if not m:
        raise SyntaxError(f"bad ref {ref!r}")
    return m.group(1).upper(), int(m.group(2))


class Parser:
    def __init__(self, toks, default_sheet=None):
        self.toks, self.i, self.sheet = toks, 0, default_sheet

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expect(self, val):
        k, v = self.next()
        if v != val:
            raise SyntaxError(f"expected {val!r} got {v!r}")

    def parse(self):
        e = self.expr()
        if self.i != len(self.toks):
            raise SyntaxError(f"trailing tokens {self.toks[self.i:]}")
        return e

    def expr(self):      # comparison level
        e = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.next()[1]
            e = {"type": "binop", "op": op, "left": e, "right": self.concat()}
        return e

    def concat(self):
        e = self.add()
        while self.peek()[1] == "&":
            self.next()
            e = {"type": "binop", "op": "&", "left": e, "right": self.add()}
        return e

    def add(self):
        e = self.mul()
        while self.peek()[1] in ("+", "-"):
            e = {"type": "binop", "op": self.next()[1], "left": e, "right": self.mul()}
        return e

    def mul(self):
        e = self.power()
        while self.peek()[1] in ("*", "/"):
            e = {"type": "binop", "op": self.next()[1], "left": e, "right": self.power()}
        return e

    def power(self):      # Excel: ^ left-assoc, unary minus binds tighter
        e = self.unary()
        while self.peek()[1] == "^":
            self.next()
            e = {"type": "binop", "op": "^", "left": e, "right": self.unary()}
        return e

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.next()[1]
            e = self.unary()
            return {"type": "unop", "op": "-", "operand": e} if op == "-" else e
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while self.peek()[1] == "%":
            self.next()
            e = {"type": "unop", "op": "%", "operand": e}
        return e

    def primary(self):
        kind, val = self.peek()
        if kind == "fn":                     # known function name followed by '('
            self.next()
            self.expect("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.expr())
                while self.peek()[1] == ",":
                    self.next()
                    if self.peek()[1] in (",", ")"):
                        args.append({"type": "num", "value": 0.0})   # empty arg
                    else:
                        args.append(self.expr())
            self.expect(")")
            return {"type": "func", "name": val, "args": args}
        if val == "(":
            self.next()
            e = self.expr()
            self.expect(")")
            return e
        if kind == "number":
            self.next()
            return {"type": "num", "value": float(val)}
        if kind == "string":
            self.next()
            return {"type": "str", "value": val[1:-1].replace('""', '"')}
        if kind == "sheetref":
            s = self.next()[1][:-1]                 # drop trailing '!'
            if s.startswith("'") and s.endswith("'") and len(s) >= 2:
                sheet = s[1:-1].replace("''", "'")  # quoted name: '+Weapon DPS'
            else:
                sheet = s.strip()
            kind, val = self.next()
            if kind != "ref":
                raise SyntaxError(f"expected ref after sheet name, got {val!r}")
            return self.maybe_range(sheet, val)
        if kind == "ref" or kind == "ident":
            self.next()
            if val.upper() in ("TRUE", "FALSE"):
                return {"type": "num", "value": 1.0 if val.upper() == "TRUE" else 0.0}
            return self.maybe_range(self.sheet, val)
        if kind is None:
            raise SyntaxError("unexpected end")
        raise SyntaxError(f"unexpected token {val!r}")

    def maybe_range(self, sheet, ref1):
        c1, r1 = split_ref(ref1)
        if self.peek()[1] == ":":
            self.next()
            kind, val = self.next()
            if kind == "sheetref":        # second qualifier ignored (as in source)
                kind, val = self.next()
            if kind != "ref":
                raise SyntaxError("bad range tail")
            c2, r2 = split_ref(val)
            return {"type": "range", "sheet": sheet,
                    "start": f"{c1}{r1}", "end": f"{c2}{r2}"}
        return {"type": "ref", "sheet": sheet, "ref": f"{c1}{r1}"}


def parse(formula_str, sheet=None):
    """Parse an Excel formula (leading '=' optional) into a nested-dict AST.
    `sheet` is the default sheet name applied to unqualified refs."""
    text = formula_str[1:] if formula_str.startswith("=") else formula_str
    toks = tokenize(text)
    # function detection: a 'ref'/'ident' token immediately followed by '(' whose
    # name is a known function (copied from verify_chains.parse_formula)
    fixed = []
    for idx, (k, v) in enumerate(toks):
        nxt = toks[idx + 1][1] if idx + 1 < len(toks) else None
        if k in ("ref", "ident") and nxt == "(" and v.upper() in FN:
            fixed.append(("fn", v.upper()))
        else:
            fixed.append((k, v))
    return Parser(fixed, sheet).parse()


# ---------------------------------------------------------------- TSV loading
# (repair logic copied from verify_chains.load_tsv; formulas only)
def load_formulas(path):
    """Load cell_ref -> formula string ('='-prefixed) from a __formulas.tsv."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    lines = raw.split("\n")
    repaired = []
    for ln in lines:
        if ln == "" and not repaired:
            continue
        if repaired and not re.match(r"^[A-Za-z]{1,3}[0-9]+\t", ln):
            repaired[-1] += "\n" + ln          # continuation of previous cell
        else:
            repaired.append(ln)
    formulas = {}
    for ln in repaired:
        if not ln:
            continue
        parts = ln.split("\t", 1)
        if len(parts) != 2:
            continue
        ref, content = parts
        content = content.replace("\\n", " ").strip()
        if content.startswith("="):
            formulas[ref] = content
    return formulas


# ---------------------------------------------------------------- CLI display caps
MAX_DEPTH = 8      # AST nesting levels shown (root = 1)
MAX_LINES = 60     # output line budget
CHILD_KEYS = ("left", "right", "operand", "args")


def cap(node, depth, max_depth, max_breadth):
    """Depth/breadth cap for display: nodes below max_depth -> '...'; lists cut
    to max_breadth items with a trailing '...+N' marker."""
    if depth > max_depth:
        return "..."
    if isinstance(node, list):
        out = [cap(x, depth, max_depth, max_breadth) for x in node[:max_breadth]]
        if len(node) > max_breadth:
            out.append(f"...+{len(node) - max_breadth}")
        return out
    if isinstance(node, dict):
        return {k: (cap(v, depth + 1, max_depth, max_breadth) if k in CHILD_KEYS else v)
                for k, v in node.items()}
    return node


WIDTH = 100        # max chars for a subtree inlined onto a single line


def render(node, pad=0):
    """JSON text for a capped AST; any subtree serializing to <= WIDTH chars
    is emitted on a single line, so deep chains stay well under MAX_LINES."""
    s = json.dumps(node)
    if len(s) <= WIDTH:
        return s
    ind, ind1 = " " * pad, " " * (pad + 1)
    if isinstance(node, list):
        return "[\n" + ",\n".join(ind1 + render(x, pad + 1) for x in node) \
            + "\n" + ind + "]"
    if isinstance(node, dict):
        body = ",\n".join(f"{ind1}{json.dumps(k)}: {render(v, pad + 1)}"
                          for k, v in node.items())
        return "{\n" + body + "\n" + ind + "}"
    return s


def render_ast(ast):
    """JSON text, depth-capped at MAX_DEPTH (8) and breadth-capped to fit
    MAX_LINES; depth is further trimmed only if breadth alone cannot."""
    text = ""
    for depth in (MAX_DEPTH, 6, 4, 3, 2):
        for breadth in (12, 8, 4, 2, 1):
            text = render(cap(ast, 1, depth, breadth))
            if text.count("\n") + 1 <= MAX_LINES:
                return text
    return text


# ---------------------------------------------------------------- CLI
def find_tsv(sheet):
    stem = STAT_SHEETS.get(sheet, sheet)
    name = f"{stem}__formulas.tsv"
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        TSV_DIR, name)
    cwd = os.path.join(TSV_DIR, name)
    return cwd if os.path.isfile(cwd) else here


def main(argv):
    if len(argv) != 3:
        print("usage: .venv/bin/python tools/formula_ast.py <sheet> <cell_ref>",
              file=sys.stderr)
        return 2
    sheet, cell = argv[1], argv[2].strip()
    path = find_tsv(sheet)
    try:
        formulas = load_formulas(path)
    except OSError as e:
        print(f"error: cannot read {path}: {e}", file=sys.stderr)
        return 1
    formula = formulas.get(cell) or formulas.get(cell.upper())
    if formula is None:
        print(f"error: {sheet}!{cell} not found or not a formula cell ({path})",
              file=sys.stderr)
        return 1
    try:
        ast = parse(formula, sheet=sheet)
    except SyntaxError as e:
        print(f"error: parse failed for {sheet}!{cell}: {e}", file=sys.stderr)
        return 1
    print(render_ast(ast))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
