#!/usr/bin/env python3
"""
formula_ts.py — AST -> TypeScript expression emitter, SLICE 2
(functions, ranges, comparisons, %).

Consumes the nested-dict AST from tools/formula_ast.py parse() and emits a
single-line TypeScript expression string:

    emit_ts(ast, sheet=None, call_refs=frozenset(), module_sheet=None) -> str

`sheet` is the containing sheet name (the same value passed to parse()); the
AST alone cannot distinguish same-sheet from cross-sheet refs, because
unqualified refs carry the containing sheet's name. `call_refs` is a set of
same-sheet cell refs (uppercase, as the parser emits them) whose cells will
be emitted as memoized functions later; a same-sheet ref to one of them
emits as a call <ref>() instead of a bare <ref>.

Mapping (anything else fails loudly, naming the offender):
  num   -> literal (integral floats without '.0')
  str   -> double-quoted escaped JS string
  ref   -> same-sheet: bare identifier (cell refs like T42 are valid JS
           identifiers), or <ref>() when the ref's cell is in call_refs
           (cyclic cells become memoized functions); cross-sheet:
           G('Sheet','Ref') grid-lookup call
  range -> cross-sheet (or module_sheet None): R('Sheet','A1','B2'); corners
           must be static literal cell refs. A range whose sheet ==
           module_sheet (the sheet of the module being emitted) instead
           expands to the bare identifier list, corner-to-corner (columns
           outer / rows inner) — the module's own cells are written to the
           grid only after its consts are computed, so an R() grid lookup
           would read nulls; the list is only valid spliced into a call's
           argument list (which is how ranges are used):
           SUM(AA19:AA41) -> sum(AA19, AA20, ..., AA41)
  binop + - * / -> JS operators with minimal precedence-correct parens
         ^ -> ** (the parser already encodes Excel's left-assoc ^; JS ** is
              right-assoc and rejects an unparenthesized unary left operand,
              so **/unary left children are grouped)
         & -> S(a,b,...) concat helper (the parser's left-assoc & chain
              flattened; string concatenation is associative)
         = <> > < >= <= -> EQ/NE/GT/LT/GE/LE(a,b) comparison helpers
  unop  - -> prefix minus (non-atomic operands grouped)
         % -> operand/100 (the parser encodes Excel's postfix % as a unop
              whose operand is the group % applies to; emitted as a division
              with JS */ precedence, grouping any lower-prec operand)
  func  -> whitelist: SUM->sum, MAX->max, MIN->min,
           IF->ifL(c, () => a, () => b) — LAZY: ifL (to be defined in TS
           later) treats a number != 0 as truthy and evaluates only the
           taken branch, so both branches emit as () => thunks; a 2-arg IF
           omits the else branch, and the omitted FALSE coerces to 0 in
           arithmetic, so it emits ifL(c, () => a, () => 0),
           ISBLANK->isBlank(x), N->n(x), SQRT->Math.sqrt, ABS->Math.abs,
           EXP->excelExp (bit-exact Excel exp, from '../exactmath'),
           INT->Math.floor, NOT->not, ROUND->roundAway(x,d),
           OR->orN, AND->andN; fixed-arity names are arity-checked (IF
           takes 2 or 3 args); any other name -> NotImplementedError(name).
           Multi-argument SUM is special: Excel adds PER-ARGUMENT subtotals
           (each RANGE argument its own 0-started sum, each scalar argument
           coerced to a number, the subtotals added left-to-right), so it
           emits per-argument terms joined by ' + ' — sum(<cells>) per RANGE
           argument, n(<expr>) per scalar — NOT one flat sum(...) across all
           arguments (a different addition grouping; 1-ulp divergence on
           cancellation-heavy sums, e.g. +Haste!T51). Single-argument SUM
           stays sum(<cells>) — the groupings coincide there. MIN/MAX are
           unchanged (one flat min/max across all arguments).

CLI: .venv/bin/python tools/formula_ts.py <sheet> <cell_ref>
  Parses that cell's formula via formula_ast and prints the emitted TS
  expression.
"""
import json
import re
import sys

try:                                    # run as a script: tools/ on sys.path
    from formula_ast import find_tsv, load_formulas, parse, split_ref
except ImportError:                     # imported as tools.formula_ts
    from tools.formula_ast import (find_tsv, load_formulas, parse,
                                   split_ref)

# ---------------------------------------------------------------- emitter
ATOM = 100        # literals, refs, G()/S() calls — never need grouping
UNARY = 15        # JS unary minus
POWER = 14        # JS ** (right-assoc; Excel ^ is left-assoc)
MULDIV = 13       # JS * /
ADDSUB = 12       # JS + -
BIN_PREC = {"*": MULDIV, "/": MULDIV, "+": ADDSUB, "-": ADDSUB}
CMP_TS = {"=": "EQ", "<>": "NE", ">": "GT", "<": "LT",
          ">=": "GE", "<=": "LE"}
FUNC_TS = {"SUM": "sum", "MAX": "max", "MIN": "min", "IF": "ifL",
           "ISBLANK": "isBlank", "N": "n", "SQRT": "Math.sqrt",
           "ABS": "Math.abs", "EXP": "excelExp", "INT": "Math.floor",
           "NOT": "not", "ROUND": "roundAway", "OR": "orN",
           "AND": "andN"}
FUNC_ARITY = {"ISBLANK": 1, "N": 1, "EXP": 1, "INT": 1,
              "NOT": 1, "ROUND": 2}  # rest variadic; IF (2 or 3 args) is
                                     # special-cased lazy in _emit

REF_RE = re.compile(r"^[A-Z]{1,3}[0-9]+$")   # bare-identifier-safe cell ref


def _col_num(col):    # column letters -> 1-based index ('AA' -> 27)
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _col_name(n):     # 1-based column index -> letters (27 -> 'AA')
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _expand_range(start, end):
    """Range corners -> bare cell refs, corner-to-corner (columns outer,
    rows inner): AA19:AA41 -> AA19..AA41; B2:A1 -> A1, A2, B1, B2."""
    (c1, r1), (c2, r2) = split_ref(start), split_ref(end)
    lo_c, hi_c = sorted((_col_num(c1), _col_num(c2)))
    lo_r, hi_r = sorted((r1, r2))
    return [f"{_col_name(c)}{r}"
            for c in range(lo_c, hi_c + 1) for r in range(lo_r, hi_r + 1)]


def _q(s):     # double-quoted escaped JS string literal
    return json.dumps(s)


def _q1(s):    # single-quoted literal (sheet names / refs inside G())
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _num(v):
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"formula_ts: non-finite number literal {v!r}")
    if v == int(v) and abs(v) < 1e16:
        return str(int(v))
    return repr(v)


def _flatten_amp(node):
    """Flatten the parser's left-assoc & chain into S(...) argument leaves
    (concatenation is associative, so flattening both sides is safe)."""
    if node.get("type") == "binop" and node["op"] == "&":
        return _flatten_amp(node["left"]) + _flatten_amp(node["right"])
    return [node]


def _emit(node, sheet, call_refs=frozenset(), module_sheet=None):
    """Emit one AST node -> (text, precedence). Raises NotImplementedError
    loudly, naming the offender, on anything beyond the SLICE 2 mapping.
    call_refs: same-sheet cell refs to emit as <ref>() calls (see emit_ts).
    module_sheet: sheet of the module being emitted; a range on that sheet
    expands to its bare identifier list (see emit_ts)."""
    t = node.get("type") if isinstance(node, dict) else None
    if t == "num":
        return _num(node["value"]), ATOM
    if t == "str":
        return _q(node["value"]), ATOM
    if t == "ref":
        s, r = node.get("sheet"), node["ref"]
        if not REF_RE.match(r):
            raise ValueError(f"formula_ts: ref {r!r} is not a "
                             f"bare-identifier-safe cell ref")
        if s is None or s == sheet:
            if r in call_refs:
                # cyclic cell: it will be emitted as a memoized function,
                # so referencing it is a call, not a bare identifier read
                return f"{r}()", ATOM
            return r, ATOM                    # cell refs are valid JS idents
        return f"G({_q1(s)},{_q1(r)})", ATOM
    if t == "binop":
        return _emit_binop(node, sheet, call_refs, module_sheet)
    if t == "unop":
        op = node["op"]
        if op == "-":
            s, p = _emit(node["operand"], sheet, call_refs, module_sheet)
            return "-" + (f"({s})" if p < ATOM else s), UNARY
        if op == "%":
            # The parser encodes Excel's postfix % as a unop whose operand
            # is the group % applies to; emit it as a /100 division (JS */
            # precedence), grouping any lower-prec operand so the emitted
            # JS binds exactly as the AST does.
            s, p = _emit(node["operand"], sheet, call_refs, module_sheet)
            return (f"({s})" if p < MULDIV else s) + "/100", MULDIV
        raise NotImplementedError(op)
    if t == "func":
        name = node["name"]
        ts = FUNC_TS.get(name)
        if ts is None:
            raise NotImplementedError(name)
        args = list(node.get("args") or [])
        if name == "IF":
            # LAZY IF: ifL(c, () => a, () => b). Only the taken branch
            # evaluates (ifL, to be defined in TS later, treats a number
            # != 0 as truthy), so both branches emit as () => thunks; the
            # condition stays eager. A 2-arg IF omits the else branch; the
            # omitted FALSE coerces to 0 in Excel arithmetic, so the else
            # thunk returns 0.
            if len(args) not in (2, 3):
                raise ValueError(f"formula_ts: IF takes 2 or 3 "
                                 f"arg(s), got {len(args)}")
            cond = _emit(args[0], sheet, call_refs, module_sheet)[0]
            branches = [_emit(a, sheet, call_refs, module_sheet)[0]
                        for a in args[1:]]
            if len(branches) == 1:
                branches.append("0")
            return (f"{ts}({cond}, "
                    + ", ".join(f"() => {b}" for b in branches)
                    + ")"), ATOM
        if name == "SUM" and len(args) > 1:
            # Excel's SUM(a, b, ...) adds PER-ARGUMENT subtotals: each
            # RANGE argument sums its own cells (its own 0-started,
            # per-step-rounded accumulation) and each scalar argument
            # coerces to a number, then the subtotals add left-to-right
            # (the oracle: total = 0.0; total += subtotal per argument).
            # One flat sum(...) across all arguments instead keeps a
            # single running total across range boundaries — a different
            # addition grouping that diverges by 1 ulp on cancellation-
            # heavy sums (e.g. +Haste!T51). Single-argument SUM keeps the
            # flat sum(<cells>): the groupings coincide there. Precedence
            # is ADDSUB (the terms join with ' + '), so any parent operator
            # groups the whole SUM as one operand.
            terms = []
            for a in args:
                text = _emit(a, sheet, call_refs, module_sheet)[0]
                if a.get("type") == "range":
                    terms.append(f"sum({text})")
                else:
                    terms.append(f"n({text})")
            return " + ".join(terms), ADDSUB
        want = FUNC_ARITY.get(name)
        if want is not None and len(args) != want:
            raise ValueError(f"formula_ts: {name} takes {want} "
                             f"arg(s), got {len(args)}")
        return ts + "(" + ",".join(_emit(a, sheet, call_refs,
                                         module_sheet)[0]
                                   for a in args) + ")", ATOM
    if t == "range":
        s = node.get("sheet") or sheet
        corners = []
        for k in ("start", "end"):
            c = node.get(k)
            if not isinstance(c, str) or not REF_RE.match(c):
                raise ValueError(f"formula_ts: range corner {k}={c!r} is "
                                 f"not a static literal cell ref")
            corners.append(c)
        if module_sheet is not None and s == module_sheet:
            # Same-sheet range in the module being emitted: the module's
            # own cells are written to the grid only after its consts are
            # computed, so an R() grid lookup would read nulls. Splice the
            # bare identifier list instead (valid only as a call's argument
            # list, which is how ranges are used); cells in call_refs keep
            # their <ref>() call form (they are memoized functions).
            return ", ".join(f"{c}()" if c in call_refs else c
                             for c in _expand_range(*corners)), ATOM
        return f"R({_q1(s)},{_q1(corners[0])},{_q1(corners[1])})", ATOM
    raise NotImplementedError(t if t else "unknown")


def _emit_binop(node, sheet, call_refs=frozenset(), module_sheet=None):
    op = node["op"]
    if op in BIN_PREC:
        p = BIN_PREC[op]
        ls, lp = _emit(node["left"], sheet, call_refs, module_sheet)
        rs, rp = _emit(node["right"], sheet, call_refs, module_sheet)
        if lp < p:                 # left-assoc: lower-prec left needs grouping
            ls = f"({ls})"
        if rp <= p:                 # same-prec right needs grouping (a-(b+c), a/(b*c))
            rs = f"({rs})"
        return f"{ls} {op} {rs}", p
    if op == "^":
        ls, lp = _emit(node["left"], sheet, call_refs, module_sheet)
        rs, rp = _emit(node["right"], sheet, call_refs, module_sheet)
        # JS ** is right-assoc and rejects an unparenthesized unary left
        # operand; the AST already encodes Excel's left-assoc ^, so group any
        # **/unary left child and any lower-prec right child.
        if lp <= POWER or node["left"].get("type") == "unop":
            ls = f"({ls})"
        if rp < POWER:
            rs = f"({rs})"
        return f"{ls} ** {rs}", POWER
    if op == "&":
        leaves = _flatten_amp(node)
        return "S(" + ",".join(_emit(x, sheet, call_refs, module_sheet)[0]
                               for x in leaves) + ")", ATOM
    if op in CMP_TS:
        # Comparison helpers are calls (ATOM): operands never need grouping.
        ls, _ = _emit(node["left"], sheet, call_refs, module_sheet)
        rs, _ = _emit(node["right"], sheet, call_refs, module_sheet)
        return f"{CMP_TS[op]}({ls},{rs})", ATOM
    raise NotImplementedError(op)


def emit_ts(ast, sheet=None, call_refs=frozenset(), module_sheet=None):
    """AST (from formula_ast.parse(formula, sheet=S)) -> TypeScript expression
    string. Pass the same containing-sheet name S so same-sheet refs emit as
    bare identifiers and cross-sheet refs as G('Sheet','Ref') lookups.

    call_refs: set of same-sheet cell refs (uppercase, as the parser emits
    them) whose cells will be emitted as memoized functions later (cyclic
    cells); each same-sheet ref to one of them emits as a call <ref>()
    instead of a bare <ref>. Cross-sheet refs are never affected.

    module_sheet: name of the sheet whose module is being emitted. A range
    on that sheet expands to its bare identifier list (corner-to-corner,
    columns outer / rows inner) instead of an R() grid call — the module's
    own cells are written to the grid only after its consts are computed,
    so an R() lookup would read nulls. The list is only valid spliced into
    a call's argument list (which is how ranges are used); expanded cells
    in call_refs keep their <ref>() call form. Ranges on any other sheet
    (cross-sheet, or module_sheet None) keep R('Sheet','A1','B2')."""
    return _emit(ast, sheet, call_refs, module_sheet)[0]


# ---------------------------------------------------------------- CLI
def main(argv):
    if len(argv) != 3:
        print("usage: .venv/bin/python tools/formula_ts.py <sheet> <cell_ref>",
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
        expr = emit_ts(ast, sheet=sheet)
    except SyntaxError as e:
        print(f"error: parse failed for {sheet}!{cell}: {e}", file=sys.stderr)
        return 1
    except NotImplementedError as e:
        print(f"error: emit failed for {sheet}!{cell}: "
              f"{e.args[0]!r} is beyond SLICE 2 (functions, ranges, "
              f"comparisons, %)",
              file=sys.stderr)
        return 1
    print(expr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
