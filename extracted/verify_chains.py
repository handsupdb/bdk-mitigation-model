#!/usr/bin/env python3
"""
verify_chains.py — Excel-formula evaluator + full verification of the 13 data
sheets of excel_mitigation_model.xlsx (Baseline, Comparison, 10 +Stat sheets,
Outputs) against their cached values — numeric cells at <=1e-9 relative
 tolerance, text-valued cells (Outputs Pawn strings, '(x.xx%)') by exact string
 comparison.

Approach: parse every formula from extracted/<Sheet>__formulas.tsv into an AST,
resolve cell references on demand (memoized, cycle-detecting) against the
Inputs sheet literals, and compare every computed formula cell to its
cached value from extracted/<Sheet>__values.tsv.

This empirically proves (a) the workbook is a DAG (no circular references,
matching the empty <calcPr/> in xl/workbook.xml), and (b) a single-pass
topological evaluation reproduces Excel's cached results exactly.

Usage: .venv/bin/python extracted/verify_chains.py
"""
import re, sys, math
from decimal import Decimal, ROUND_HALF_UP

TSV_DIR = "extracted"

# ---------------------------------------------------------------- loading
def load_tsv(path):
    """Load cell_ref -> content. Repairs embedded newlines; returns (formulas, values)."""
    formulas, values = {}, {}
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
        else:
            values[ref] = content
    return formulas, values

STAT_SHEETS = {
    "+Armor": "_Armor", "+Strength": "_Strength", "+Stamina": "_Stamina",
    "+Critical Strike": "_Critical_Strike", "+Haste": "_Haste",
    "+Versatility": "_Versatility", "+Mastery": "_Mastery", "+Leech": "_Leech",
    "+Avoidance": "_Avoidance", "+Weapon DPS": "_Weapon_DPS",
}
SHEETS = ["Baseline", "Inputs", "Comparison"] + list(STAT_SHEETS.keys()) + ["Outputs"]
F, V = {}, {}
for s in SHEETS:
    stem = STAT_SHEETS.get(s, s)
    F[s], _ = load_tsv(f"{TSV_DIR}/{stem}__formulas.tsv")
    _, V[s] = load_tsv(f"{TSV_DIR}/{stem}__values.tsv")

# ---------------------------------------------------------------- tokenizer
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

# ---------------------------------------------------------------- AST / parser
class Node: pass
class Num(Node):
    def __init__(self, v): self.v = v
class Str(Node):
    def __init__(self, v): self.v = v
class Ref(Node):
    def __init__(self, sheet, col, row): self.sheet, self.col, self.row = sheet, col, row
class Range(Node):
    def __init__(self, sheet, c1, r1, c2, r2): self.sheet, self.c1, self.r1, self.c2, self.r2 = sheet, c1, r1, c2, r2
class Bin(Node):
    def __init__(self, op, l, r): self.op, self.l, self.r = op, l, r
class Neg(Node):
    def __init__(self, e): self.e = e
class Pct(Node):
    def __init__(self, e): self.e = e
class Call(Node):
    def __init__(self, name, args): self.name, self.args = name, args

class Parser:
    def __init__(self, toks, default_sheet):
        self.toks, self.i, self.sheet = toks, 0, default_sheet
    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)
    def next(self):
        t = self.peek(); self.i += 1; return t
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
            e = Bin(op, e, self.concat())
        return e
    def concat(self):
        e = self.add()
        while self.peek()[1] == "&":
            self.next()
            e = Bin("&", e, self.add())
        return e
    def add(self):
        e = self.mul()
        while self.peek()[1] in ("+", "-"):
            e = Bin(self.next()[1], e, self.mul())
        return e
    def mul(self):
        e = self.power()
        while self.peek()[1] in ("*", "/"):
            e = Bin(self.next()[1], e, self.power())
        return e
    def power(self):      # Excel: ^ left-assoc, unary minus binds tighter
        e = self.unary()
        while self.peek()[1] == "^":
            self.next()
            e = Bin("^", e, self.unary())
        return e
    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.next()[1]
            e = self.unary()
            return Neg(e) if op == "-" else e
        return self.postfix()
    def postfix(self):
        e = self.primary()
        while self.peek()[1] == "%":
            self.next()
            e = Pct(e)
        return e
    def primary(self):
        kind, val = self.peek()
        if val == "(":
            self.next()
            e = self.expr()
            self.expect(")")
            return e
        if kind == "number":
            self.next()
            return Num(float(val))
        if kind == "string":
            self.next()
            return Str(val[1:-1].replace('""', '"'))
        if kind == "sheetref":
            s = self.next()[1][:-1]                 # drop trailing '!'
            if s.startswith("'") and s.endswith("'") and len(s) >= 2:
                sheet = s[1:-1].replace("''", "'")  # quoted name: '+Armor', '+Weapon DPS'
            else:
                sheet = s.strip()
            kind, val = self.next()
            if kind != "ref":
                raise SyntaxError(f"expected ref after sheet name, got {val!r}")
            return self.maybe_range(sheet, val)
        if kind == "ref" or kind == "ident":
            self.next()
            if val.upper() in ("TRUE", "FALSE"):
                return Num(1.0 if val.upper() == "TRUE" else 0.0)
            return self.maybe_range(self.sheet, val)
        if kind is None:
            raise SyntaxError("unexpected end")
        # function call?
        if self.peek()[1] == "(":
            pass
        raise SyntaxError(f"unexpected token {val!r}")
    def maybe_range(self, sheet, ref1):
        c1, r1 = split_ref(ref1)
        if self.peek()[1] == ":":
            self.next()
            kind, val = self.next()
            if kind == "sheetref":
                kind, val = self.next()
            if kind != "ref":
                raise SyntaxError("bad range tail")
            c2, r2 = split_ref(val)
            return Range(sheet, c1, r1, c2, r2)
        return Ref(sheet, c1, r1)

def split_ref(ref):
    m = re.match(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$", ref)
    if not m:
        raise SyntaxError(f"bad ref {ref!r}")
    return m.group(1).upper(), int(m.group(2))

# handle function names (identifiers followed by '(') — extend tokenizer usage:
# we treat any ref-shaped token followed by '(' as a function name.
def parse_formula(text, sheet):
    toks = tokenize(text[1:] if text.startswith("=") else text)
    # function detection: a 'ref' token immediately followed by '(' whose letters
    # are a known function name
    FN = {"IF", "MIN", "MAX", "SUM", "ABS", "SQRT", "EXP", "INT", "ROUND",
          "AND", "OR", "NOT", "ISBLANK", "TRUE", "FALSE", "AVERAGE", "COUNT", "N"}
    fixed = []
    for idx, (k, v) in enumerate(toks):
        nxt = toks[idx + 1][1] if idx + 1 < len(toks) else None
        if k in ("ref", "ident") and nxt == "(" and v.upper() in FN:
            fixed.append(("fn", v.upper()))
        else:
            fixed.append((k, v))
    p = Parser(fixed, sheet)
    return p.parse()

# monkey-patch primary to support fn calls
def _primary(self):
    kind, val = self.peek()
    if kind == "fn":
        self.next()
        self.expect("(")
        args = []
        if self.peek()[1] != ")":
            args.append(self.expr())
            while self.peek()[1] == ",":
                self.next()
                if self.peek()[1] == "," or self.peek()[1] == ")":
                    args.append(Num(0.0))     # empty arg
                else:
                    args.append(self.expr())
        self.expect(")")
        return Call(val, args)
    return Parser._orig_primary(self)
Parser._orig_primary = Parser.primary
Parser.primary = _primary

# ---------------------------------------------------------------- evaluator
class EvalError(Exception): pass
class CycleError(Exception):
    def __init__(self, chain):
        self.chain = chain
        super().__init__("cycle: " + " -> ".join(chain))

memo = {}
in_progress = []
cell_depth = {}

def col_to_num(c):
    n = 0
    for ch in c:
        n = n * 26 + (ord(ch) - 64)
    return n

def num_to_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def raw_value(sheet, ref):
    return V[sheet].get(ref)

def get_cell(sheet, ref):
    """Return evaluated value: float | str | None(blank)."""
    key = (sheet, ref)
    if key in memo:
        return memo[key]
    if key in in_progress:
        raise CycleError([f"{s}!{r}" for s, r in in_progress] + [f"{sheet}!{ref}"])
    formula = F[sheet].get(ref)
    if formula is None:
        raw = V[sheet].get(ref, None)
        if raw is None or raw == "" or raw == "<NO_CACHED_VALUE>":
            val = None
        else:
            try:
                val = float(raw)
            except ValueError:
                val = raw
        memo[key] = val
        return val
    in_progress.append(key)
    try:
        ast = parse_formula(formula, sheet)
        val = eval_node(ast, sheet)
    finally:
        in_progress.pop()
    memo[key] = val
    return val

def to_num(v, ctx=""):
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            raise EvalError(f"#VALUE! ({v!r} in {ctx})")
    return float(v)

def eval_node(n, sheet):
    if isinstance(n, Num):
        return n.v
    if isinstance(n, Str):
        return n.v
    if isinstance(n, Ref):
        return get_cell(n.sheet, f"{n.col}{n.row}")
    if isinstance(n, Range):
        vals = []
        c1, c2 = col_to_num(n.c1), col_to_num(n.c2)
        for c in range(min(c1, c2), max(c1, c2) + 1):
            for r in range(min(n.r1, n.r2), max(n.r1, n.r2) + 1):
                v = get_cell(n.sheet, f"{num_to_col(c)}{r}")
                if isinstance(v, str):
                    continue          # SUM/MIN/MAX over ranges skip text
                vals.append(to_num(v))
        return vals
    if isinstance(n, Neg):
        return -to_num(eval_node(n.e, sheet))
    if isinstance(n, Pct):
        return to_num(eval_node(n.e, sheet)) / 100.0
    if isinstance(n, Bin):
        if n.op == "&":
            return as_str(eval_node(n.l, sheet)) + as_str(eval_node(n.r, sheet))
        if n.op in ("=", "<>", "<", ">", "<=", ">="):
            a, b = eval_node(n.l, sheet), eval_node(n.r, sheet)
            if isinstance(a, str) or isinstance(b, str):
                a, b = as_str(a), as_str(b)
                if n.op == "=":  return a == b
                if n.op == "<>": return a != b
                if n.op == "<":  return a < b
                if n.op == ">":  return a > b
                if n.op == "<=": return a <= b
                return a >= b
            a, b = to_num(a), to_num(b)
            if n.op == "=":  return a == b
            if n.op == "<>": return a != b
            if n.op == "<":  return a < b
            if n.op == ">":  return a > b
            if n.op == "<=": return a <= b
            return a >= b
        a, b = to_num(eval_node(n.l, sheet)), to_num(eval_node(n.r, sheet))
        if n.op == "+": return a + b
        if n.op == "-": return a - b
        if n.op == "*": return a * b
        if n.op == "/":
            if b == 0: raise EvalError("#DIV/0!")
            return a / b
        if n.op == "^":
            return a ** b
        raise EvalError(f"bad op {n.op}")
    if isinstance(n, Call):
        return eval_call(n, sheet)
    raise EvalError("unknown node")

def excel_num_str(x):
    """Excel's number->text coercion (General format) as used by '&' concatenation.
    Empirically reverse-engineered from Outputs' cached Pawn strings:
    take the SHORTEST ROUND-TRIP decimal (repr), then round to 15 significant
    digits HALF-AWAY-FROM-ZERO — NOT the correctly-rounded 15 digits of the
    exact binary value. Proof: Outputs!D9 = 0.004392465626901725 (exact expansion
    ...01724887... correctly rounds to ...0172) but Excel's cached Pawn string
    has Stamina=0.00439246562690173 (= repr ...01725 rounded half-up).
    Decimal notation for 1e-4 <= |x| < 1e15; scientific (uppercase E, signed
    exponent, 15 sig digits) outside that range; 0 -> '0'; integers plain
    (MasteryRating=1). The >= 1e15 branch is unverified (no such values)."""
    if x == 0:
        return "0"
    a = abs(x)
    if a < 1e-4 or a >= 1e15:
        mant, _, exp = repr(x).partition("e")
        exp = int(exp)
        q = Decimal(mant).quantize(Decimal("1E-14"), rounding=ROUND_HALF_UP)
        if abs(q) >= 10:                  # 9.99... rounded up to 10.
            q = q.scaleb(-1)
            exp += 1
        s = format(abs(q), "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return ("-" if x < 0 else "") + f"{s}E{exp:+d}"
    d = Decimal(repr(x))
    q = d.quantize(Decimal(1).scaleb(d.adjusted() - 14), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s

def as_str(v):
    if v is None: return ""
    if isinstance(v, bool): return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return excel_num_str(v)
    return str(v)

def eval_call(n, sheet):
    name, args = n.name, n.args
    if name == "IF":
        cond = eval_node(args[0], sheet)
        if isinstance(cond, str):
            cond = cond != ""
        elif cond is None:
            cond = False
        elif not isinstance(cond, bool):
            cond = to_num(cond) != 0
        if cond:
            return eval_node(args[1], sheet)
        return eval_node(args[2], sheet) if len(args) > 2 else False
    if name in ("MIN", "MAX"):
        vals = []
        for a in args:
            v = eval_node(a, sheet)
            if isinstance(v, list):
                vals.extend(x for x in v if x is not None)
            else:
                vals.append(to_num(v))
        return min(vals) if name == "MIN" else max(vals)
    if name == "SUM":
        total = 0.0
        for a in args:
            v = eval_node(a, sheet)
            if isinstance(v, list):
                total += sum(x for x in v if x is not None)
            else:
                total += to_num(v)
        return total
    if name == "ABS":
        return abs(to_num(eval_node(args[0], sheet)))
    if name == "SQRT":
        return math.sqrt(to_num(eval_node(args[0], sheet)))
    if name == "EXP":
        return math.exp(to_num(eval_node(args[0], sheet)))
    if name == "INT":
        return float(math.floor(to_num(eval_node(args[0], sheet))))
    if name == "ROUND":
        x = to_num(eval_node(args[0], sheet))
        d = int(to_num(eval_node(args[1], sheet))) if len(args) > 1 else 0
        p = 10 ** d
        return float(math.copysign(math.floor(abs(x) * p + 0.5), x) / p)
    if name == "AND":
        return all(truthy(eval_node(a, sheet)) for a in args)
    if name == "OR":
        return any(truthy(eval_node(a, sheet)) for a in args)
    if name == "NOT":
        return not truthy(eval_node(args[0], sheet))
    if name == "ISBLANK":
        a = args[0]
        if isinstance(a, Ref):
            return get_cell(a.sheet, f"{a.col}{a.row}") is None
        return eval_node(a, sheet) is None
    if name == "N":
        v = eval_node(args[0], sheet)
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, str) or v is None:
            return 0.0            # Excel N(): text/blank -> 0
        return to_num(v)
    if name in ("TRUE", "FALSE"):
        return name == "TRUE"
    raise EvalError(f"unsupported function {name}")

def truthy(v):
    if isinstance(v, bool): return v
    if v is None: return False
    if isinstance(v, str): return v != ""
    return to_num(v) != 0

# ---------------------------------------------------------------- dependency depth
def deps_of(ast, out):
    if isinstance(ast, Ref):
        out.add((ast.sheet, f"{ast.col}{ast.row}"))
    elif isinstance(ast, Range):
        c1, c2 = col_to_num(ast.c1), col_to_num(ast.c2)
        for c in range(min(c1, c2), max(c1, c2) + 1):
            for r in range(min(ast.r1, ast.r2), max(ast.r1, ast.r2) + 1):
                out.add((ast.sheet, f"{num_to_col(c)}{r}"))
    elif isinstance(ast, (Neg, Pct)):
        deps_of(ast.e, out)
    elif isinstance(ast, Bin):
        deps_of(ast.l, out); deps_of(ast.r, out)
    elif isinstance(ast, Call):
        for a in ast.args:
            deps_of(a, out)

def depth_of(sheet, ref, seen=None):
    key = (sheet, ref)
    if key in cell_depth:
        return cell_depth[key]
    if seen is None:
        seen = set()
    if key in seen:
        return 0
    seen.add(key)
    formula = F[sheet].get(ref)
    if formula is None:
        cell_depth[key] = 0
        return 0
    try:
        ast = parse_formula(formula, sheet)
    except Exception:
        cell_depth[key] = 0
        return 0
    dset = set()
    deps_of(ast, dset)
    d = 0
    for (s2, r2) in dset:
        if (s2, r2) == key:
            continue
        d = max(d, depth_of(s2, r2, seen))
    cell_depth[key] = d + 1
    return d + 1

# ---------------------------------------------------------------- driver
def main():
    # natural sort by column then row
    def sortkey(ref):
        m = re.match(r"([A-Z]+)([0-9]+)", ref)
        return (col_to_num(m.group(1)), int(m.group(2)))

    grand = {}
    for sheet in SHEETS:
        if sheet == "Inputs":
            continue
        cells = sorted(F[sheet].keys(), key=sortkey)
        exact = near = mismatch = nocache = errors = 0
        str_exact = str_mismatch = 0
        mismatches, error_list = [], []
        for ref in cells:
            cached_raw = V[sheet].get(ref, None)
            if cached_raw is None or cached_raw == "<NO_CACHED_VALUE>":
                nocache += 1
                continue
            try:
                comp = get_cell(sheet, ref)
            except (CycleError, EvalError, SyntaxError, RecursionError) as e:
                errors += 1
                error_list.append((ref, repr(e)[:140]))
                continue
            try:
                cached = float(cached_raw)
                cached_is_num = True
            except ValueError:
                cached_is_num = False
            if cached_is_num and isinstance(comp, float) and not isinstance(comp, bool):
                delta = abs(comp - cached)
                tol = max(1e-9, abs(cached) * 1e-9)
                if delta <= tol:
                    exact += 1
                elif delta <= max(1e-6, abs(cached) * 1e-6):
                    near += 1
                    mismatches.append(("NEAR", ref, comp, cached, delta))
                else:
                    mismatch += 1
                    mismatches.append(("MISMATCH", ref, comp, cached, delta))
            else:
                # exact string comparison (text-cached cells: Pawn strings, '(x.xx%)')
                comp_str = as_str(comp) if comp is not None else ""
                if comp_str == cached_raw:
                    str_exact += 1
                else:
                    str_mismatch += 1
                    mismatches.append(("STRMM", ref, comp_str, cached_raw, None))
        grand[sheet] = (len(cells), exact, str_exact, str_mismatch, near, mismatch,
                        nocache, errors, mismatches, error_list)

    print(f"{'sheet':<20} {'cells':>6} {'exact':>6} {'strOK':>6} {'strMM':>6} {'near':>5} {'MISMATCH':>9} {'nocache':>8} {'errors':>7}")
    for sheet, (n, e, se, sm, nr, mm, nc, er, mm_list, er_list) in grand.items():
        print(f"{sheet:<20} {n:>6} {e:>6} {se:>6} {sm:>6} {nr:>5} {mm:>9} {nc:>8} {er:>7}")
        for kind, ref, comp, cached, d in mm_list[:8]:
            if kind == "STRMM":
                print(f"    STRMM {sheet}!{ref}:")
                print(f"      computed={str(comp)[:110]!r}")
                print(f"      cached  ={str(cached)[:110]!r}")
            else:
                print(f"    {kind} {sheet}!{ref}: computed={comp!r} cached={cached!r} delta={d:.3g}")
        for ref, e in er_list[:8]:
            print(f"    ERROR {sheet}!{ref}: {e}")

    # ---- the four required chains, with checkpoints (Baseline)
    checkpoints = {
        "(i) armor DR": [
            ("C5", "Inputs!C7 mirror"), ("H5", "base armor"), ("J6", "mod strength"),
            ("E116", "BloodiedBlade eff str"), ("D157", "2set eff str"),
            ("J5", "modified armor"), ("L5", "armor DR")],
        "(ii) total parry": [
            ("D8", "crit rating + bonus"), ("E8", "diminished crit rating"),
            ("H8", "crit chance"), ("J8", "crit mult"), ("L8", "parry from crit"),
            ("L6", "parry from str"), ("L13", "total parry"), ("L14", "attack avoidance")],
        "(iii) DS casts/sec": [
            ("J9", "haste mult"), ("L9", "rune regen"), ("T38", "DRW casts"),
            ("L15", "BoneShield drain"), ("T57", "MR casts"), ("F127", "DoM rune rate"),
            ("T51", "HS casts"), ("O42", "DS net RP cost"), ("T42", "DS casts/sec"),
            ("T25", "BB casts"), ("T74", "VS casts"), ("E127", "DoM uptime"),
            ("S76", "VB eff CD"), ("T76", "VB casts")],
        "(iv) Mitigation Factor": [
            ("T10", "taken DTPS anchor"), ("T6", "phys ST"), ("T8", "mag ST"),
            ("Q6", "post-IBF"), ("P6", "post-DRW"), ("O6", "unmit phys ST"),
            ("O8", "unmit mag ST"), ("O10", "UDTPS"),
            ("L7", "mod health"), ("V8", "AMS heal"), ("V10", "AMS total"),
            ("W10", "other healing"), ("X10", "EHRPS"), ("N15", "Mitigation Factor")],
    }
    print("\n=== REQUIRED CHAIN CHECKPOINTS (computed vs cached) ===")
    for chain, pts in checkpoints.items():
        print(f"--- {chain} ---")
        for ref, label in pts:
            comp = get_cell("Baseline", ref)
            cached_raw = V["Baseline"].get(ref, "")
            print(f"  {ref:>4} {label:<24} computed={comp!r:>24} cached={cached_raw}")

    # ---- flagged-issue bug evidence: Outputs current vs corrected
    print("\n=== OUTPUTS BUG EVIDENCE (current vs corrected) ===")
    # (a) Unreliable-EHP block rows 72-81: D72:D81 normalize with MAX($C$59:$C$68)
    #     (the R&C block's max) instead of the block's own MAX($C$72:$C$81).
    raw_u = {r: get_cell("Outputs", f"C{r}") for r in range(72, 82)}
    mx_rc = max(get_cell("Outputs", f"C{r}") for r in range(59, 69))
    mx_u = max(raw_u.values())
    print(f"(a) Unreliable EHP rows 72-81: used MAX($C$59:$C$68)={mx_rc!r}; "
          f"own-block MAX($C$72:$C$81)={mx_u!r}")
    lab = {72: "Armor", 73: "Strength", 74: "Stamina", 75: "CritRating",
           76: "HasteRating", 77: "Versatility", 78: "MasteryRating",
           79: "Leech", 80: "Avoidance", 81: "Dps"}
    cor_d = {}
    for r in range(72, 82):
        cur = get_cell("Outputs", f"D{r}")
        cor = raw_u[r] / mx_u
        cor_d[lab[r]] = cor
        print(f"    D{r} {lab[r]:<13} current={cur!r:<24} corrected={cor!r}")
    pawn_u = ('( Pawn: v1: "BDK EHP(u)": Leech=' + as_str(cor_d["Leech"])
              + ', CritRating=' + as_str(cor_d["CritRating"])
              + ', Dps=' + as_str(cor_d["Dps"])
              + ', Strength=' + as_str(cor_d["Strength"])
              + ', HasteRating=' + as_str(cor_d["HasteRating"])
              + ', MasteryRating=' + as_str(cor_d["MasteryRating"])
              + ', Stamina=' + as_str(cor_d["Stamina"])
              + ', Armor=' + as_str(cor_d["Armor"])
              + ', Versatility=' + as_str(cor_d["Versatility"]) + ' )')
    print(f"    C82 current (cached): {V['Outputs'].get('C82')}")
    print(f"    C82 corrected:         {pawn_u}")
    # (b) Mitigation block C16: Weapon-DPS delta divided by 10 although the
    #     +Weapon DPS probe increments only +1 (Inputs!C16+1, porting_spec §3).
    stat_n15 = get_cell("+Weapon DPS", "N15")
    base_n15 = get_cell("Baseline", "N15")
    c16_cur = get_cell("Outputs", "C16")
    c16_cor = stat_n15 - base_n15            # per +1 weapon DPS (no /10)
    print(f"(b) C16 Weapon-DPS raw weight: current={c16_cur!r} corrected={c16_cor!r} "
          f"(x10; IF else-branch live: N(+WeaponDPS!N15)={stat_n15!r}, "
          f"N(Baseline!N15)={base_n15!r})")
    others = [get_cell("Outputs", f"C{r}") for r in range(7, 16)]
    d16_cur = get_cell("Outputs", "D16")
    d16_cor = c16_cor / max(others + [c16_cor])
    print(f"    D16 normalized: current={d16_cur!r} corrected={d16_cor!r} "
          f"(block max {max(others + [c16_cur])!r} -> {max(others + [c16_cor])!r})")
    print(f"    C17 Pawn Dps= value: current={as_str(d16_cur)} corrected={as_str(d16_cor)}")

    # ---- empirical evaluation order (dependency depth layers) — Baseline only
    cells = sorted(F["Baseline"].keys(), key=sortkey)
    depths = {}
    for ref in cells:
        depths[ref] = depth_of("Baseline", ref)
    with open(f"{TSV_DIR}/eval_order.txt", "w") as f:
        f.write("# Empirical topological layers: depth = 1 + max(depth of refs)\n")
        f.write("# Cells at depth d can be evaluated once all depth < d cells are done.\n")
        byd = {}
        for ref, d in depths.items():
            byd.setdefault(d, []).append(ref)
        for d in sorted(byd):
            f.write(f"\n== depth {d} ({len(byd[d])} cells) ==\n")
            f.write(" ".join(sorted(byd[d], key=sortkey)) + "\n")
    print(f"\nwrote {TSV_DIR}/eval_order.txt (max depth {max(depths.values())})")

if __name__ == "__main__":
    main()
