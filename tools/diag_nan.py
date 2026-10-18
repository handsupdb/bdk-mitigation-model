#!/usr/bin/env python3
"""Diagnose NaN cells in the evaluated engine grid.

Inputs (read here, nothing else):
  tests/fixtures/grid_dump.json   {"<Sheet!Ref>": value} — the evaluated grid
  data/wow-12.1/formulas/*.tsv    cell_ref TAB formula
  tools/formula_ast.py            parse() / load_formulas() / STAT_SHEETS

Why "value is NaN" needs work: the dump is written by
tests/engine/grid.dump.test.ts via JSON.stringify, which serializes NaN —
and also blanks, null results and ±Infinity — as null.  The engine's
in-memory grid has 4,868 NaN cells, but the dump has 8,544 nulls.  So each
null-valued formula cell is classified through its parsed AST under the
engine's runtime semantics (src/engine/cells.ts, lazy.ts, compare.ts,
strmath.ts) to isolate the true NaN cells:

  - blank cells (no formula) and null results (IF / bare-ref passthrough of
    a blank) are not NaN;
  - 1/0-style divisions are ±Infinity, not NaN;
  - NaN is created by 0/0, 0*Infinity, non-numeric strings in arithmetic,
    SQRT of negatives — and propagated by anything that touches it.

Roots are NaN cells whose referenced cells (per the reference graph built
from the ASTs) contain no NaN: the places NaN is *created*, not propagated.
Strings and nulls among the refs are allowed (a string flowing into
arithmetic is a prime suspect).

Run: .venv/bin/python tools/diag_nan.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import formula_ast  # noqa: E402  (tools/formula_ast.py — parse/load_formulas/STAT_SHEETS)

GRID_PATH = ROOT / "tests" / "fixtures" / "grid_dump.json"
FORMULAS_DIR = ROOT / "data" / "wow-12.1" / "formulas"
MAX_RANGE_CELLS = 100_000  # same cap as tools/emit_module.py

# Value classes for the classifier.
NAN, INF, NINF = "nan", "inf", "ninf"
NULL, STR, BOOL, NUM, UNK = "null", "str", "bool", "num", "unknown"

BOOL_FUNCS = {"OR", "AND", "NOT", "ISBLANK"}  # engine: booleans (falsy in ifL)
CMP_OPS = {"=", "<>", ">", "<", ">=", "<="}   # engine: booleans

REF_RE = re.compile(r"^\$?([A-Za-z]+)\$?([0-9]+)$")


# --------------------------------------------------------------------------
# A1 helpers
# --------------------------------------------------------------------------

def col_num(letters: str) -> int:
    c = 0
    for ch in letters.upper():
        c = c * 26 + (ord(ch) - 64)
    return c


def col_letters(c: int) -> str:
    s = ""
    while c > 0:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def parse_ref(ref: str):
    m = REF_RE.match(ref.strip())
    if not m:
        return None
    return col_num(m.group(1)), int(m.group(2))


def range_members(start: str, end: str, cap: int = MAX_RANGE_CELLS):
    """Member refs of a rectangle (either corner order), or None if oversized."""
    a, b = parse_ref(start), parse_ref(end)
    if not a or not b:
        return []
    c1, r1 = a
    c2, r2 = b
    clo, chi = min(c1, c2), max(c1, c2)
    rlo, rhi = min(r1, r2), max(r1, r2)
    if (chi - clo + 1) * (rhi - rlo + 1) > cap:
        return None
    return [f"{col_letters(c)}{r}" for c in range(clo, chi + 1) for r in range(rlo, rhi + 1)]


def iter_nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_nodes(v)


# --------------------------------------------------------------------------
# Load inputs and build the reference graph
# --------------------------------------------------------------------------

def load_inputs():
    """Return (grid, formulas, asts, graph, parse_errors).

    grid:     {"Sheet!Ref": value} from the dump
    formulas: {"Sheet!Ref": formula text} ('='-prefixed)
    asts:     {"Sheet!Ref": parsed AST}
    graph:    {"Sheet!Ref": [referenced "Sheet!Ref", ...]} (ordered, deduped;
              same-sheet refs, range members, cross-sheet refs)
    """
    grid = json.loads(GRID_PATH.read_text(encoding="utf-8"))
    safe_to_real = {stem: real for real, stem in formula_ast.STAT_SHEETS.items()}

    formulas, asts, graph = {}, {}, {}
    parse_errors = []
    for path in sorted(FORMULAS_DIR.glob("*.tsv")):
        stem = path.name[:-4]
        real = safe_to_real.get(stem, stem)
        for ref, form in formula_ast.load_formulas(str(path)).items():
            key = f"{real}!{ref}"
            formulas[key] = form
            try:
                ast = formula_ast.parse(form, sheet=real)
            except Exception as exc:  # noqa: BLE001 — report, don't crash
                parse_errors.append(f"{key}: {exc}")
                continue
            asts[key] = ast
            refs, seen = [], set()
            for node in iter_nodes(ast):
                if node.get("type") == "ref":
                    target = f"{node.get('sheet') or real}!{node['ref']}"
                elif node.get("type") == "range":
                    sheet = node.get("sheet") or real
                    members = range_members(node["start"], node["end"])
                    if members is None:  # oversized: keep the raw range token
                        target = f'{sheet}!{node["start"]}:{node["end"]}'
                        if target not in seen:
                            seen.add(target)
                            refs.append(target)
                        continue
                    for m in members:
                        target = f"{sheet}!{m}"
                        if target not in seen:
                            seen.add(target)
                            refs.append(target)
                    continue
                else:
                    continue
                if target not in seen:
                    seen.add(target)
                    refs.append(target)
            graph[key] = refs
    return grid, formulas, asts, graph, parse_errors


# --------------------------------------------------------------------------
# Value classifier (engine semantics; class-level partial evaluation)
# --------------------------------------------------------------------------

def _js_number(s: str):
    """JS Number(s): numeric strings coerce; anything else is NaN."""
    t = s.strip()
    if t == "":
        return 0.0
    try:
        return float(t)
    except ValueError:
        return None


def _to_num(cls, val):
    """JS numeric coercion for arithmetic: null -> 0, '5' -> 5, 'x' -> NaN."""
    if cls == NULL:
        return NUM, 0.0
    if cls == STR:
        n = _js_number(val)
        return (NAN, None) if n is None else (NUM, n)
    if cls == BOOL:
        return UNK, None
    return cls, val


def _sign(cls, val):
    """+1 / -1 / 0 for known numerics; None when unknown (or not numeric)."""
    if cls == INF:
        return 1
    if cls == NINF:
        return -1
    if cls == NUM and val is not None:
        return 1 if val > 0 else (-1 if val < 0 else 0)
    return None


def _add(a, b):
    (ac, av), (bc, bv) = a, b
    if ac == NAN or bc == NAN:
        return (NAN, None)
    if ac in (INF, NINF) and bc in (INF, NINF):
        return (ac, None) if ac == bc else (NAN, None)  # Inf + (-Inf) = NaN
    if ac in (INF, NINF):
        return (ac, None)
    if bc in (INF, NINF):
        return (bc, None)
    if ac == UNK or bc == UNK:
        return (UNK, None)
    if av is not None and bv is not None:
        s = av + bv
        if math.isinf(s):
            return ((INF if s > 0 else NINF), None)
        return (NUM, s)
    return (NUM, None)


def _neg(a):
    ac, av = a
    if ac == INF:
        return (NINF, None)
    if ac == NINF:
        return (INF, None)
    if ac in (NAN, UNK):
        return (ac, None)
    return (NUM, None if av is None else -av)


def _mul(a, b):
    (ac, av), (bc, bv) = a, b
    if ac == NAN or bc == NAN:
        return (NAN, None)
    if ac in (INF, NINF) and bc in (INF, NINF):
        return ((INF if ac == bc else NINF), None)
    if ac in (INF, NINF) or bc in (INF, NINF):
        s = _sign(ac, av) if ac in (INF, NINF) else _sign(bc, bv)
        other = _sign(bc, bv) if ac in (INF, NINF) else _sign(ac, av)
        if other is None:
            return (UNK, None)
        if other == 0:
            return (NAN, None)  # 0 * Infinity
        return ((INF if s * other > 0 else NINF), None)
    if ac == UNK or bc == UNK:
        return (UNK, None)
    if av is not None and bv is not None:
        p = av * bv
        if math.isinf(p):
            return ((INF if p > 0 else NINF), None)
        return (NUM, p)
    return (NUM, None)


def _div(a, b):
    (ac, av), (bc, bv) = a, b
    if ac == NAN or bc == NAN:
        return (NAN, None)
    if bc in (INF, NINF):
        if ac in (INF, NINF):
            return (NAN, None)  # Inf / Inf
        if ac == UNK:
            return (UNK, None)
        return (NUM, 0.0)  # finite / Inf = 0
    if ac in (INF, NINF):
        if bc == UNK or bv is None:
            return (UNK, None)
        if bv == 0:
            return (ac, None)  # Inf / 0 = Inf
        s = _sign(ac, av) * _sign(bc, bv)
        return ((INF if s > 0 else NINF), None)
    if ac == UNK or bc == UNK:
        return (UNK, None)
    if bv == 0:
        if av is None or av == 0:
            return (NAN, None) if av == 0 else (UNK, None)  # 0/0 vs ?/0
        return ((INF if av > 0 else NINF), None)
    if av is not None:
        q = av / bv
        if math.isinf(q):
            return ((INF if q > 0 else NINF), None)
        return (NUM, q)
    return (NUM, None)


def _pow(a, b):
    (ac, av), (bc, bv) = a, b
    if ac == NAN or bc == NAN:
        return (NAN, None)
    if ac in (INF, NINF) or bc in (INF, NINF) or ac == UNK or bc == UNK:
        return (UNK, None)
    if av is None or bv is None:
        return (UNK, None)
    try:
        if av == 0 and bv < 0:
            return (INF, None)
        p = math.pow(av, bv)
        if math.isinf(p):
            return ((INF if p > 0 else NINF), None)
        return (NUM, p)
    except ValueError:  # negative base, fractional exponent -> NaN
        return (NAN, None)
    except OverflowError:
        return (INF, None)


class Classifier:
    """Classify cell/AST values as (class, known-value) under engine semantics."""

    def __init__(self, grid, formulas, asts):
        self.grid = grid
        self.formulas = formulas
        self.asts = asts
        self._cache = {}
        self._in_progress = set()

    def cell(self, key):
        """Classify a cell's value: (cls, known numeric value or None)."""
        if key in self._cache:
            return self._cache[key]
        if key not in self.grid:
            self._cache[key] = (NULL, None)  # absent from the grid = blank
            return self._cache[key]
        v = self.grid[key]
        if isinstance(v, str):
            self._cache[key] = (STR, v)
        elif isinstance(v, bool):
            self._cache[key] = (BOOL, None)
        elif isinstance(v, (int, float)):
            if isinstance(v, float) and v != v:
                self._cache[key] = (NAN, None)
            else:
                self._cache[key] = (NUM, float(v))
        elif v is None:
            # null in the dump: NaN, blank, null result or ±Infinity.
            if key not in self.formulas:
                self._cache[key] = (NULL, None)  # blank cell (no formula)
            elif key not in self.asts:
                self._cache[key] = (UNK, None)  # unparseable formula
            elif key in self._in_progress:
                self._cache[key] = (UNK, None)  # cyclic reference
            else:
                self._in_progress.add(key)
                try:
                    self._cache[key] = self.node(
                        self.asts[key], key.rsplit("!", 1)[0]
                    )
                finally:
                    self._in_progress.discard(key)
        else:
            self._cache[key] = (UNK, None)
        return self._cache[key]

    def node(self, node, sheet):
        """Classify an AST node's value: (cls, known numeric value or None)."""
        if not isinstance(node, dict):
            return (UNK, None)
        t = node.get("type")

        if t == "num":
            return (NUM, float(node["value"]))
        if t == "str":
            return (STR, node["value"])
        if t == "ref":
            return self.cell(f"{node.get('sheet') or sheet}!{node['ref']}")

        if t == "unop":
            c, v = _to_num(*self.node(node["operand"], sheet))
            op = node["op"]
            if op == "-":
                return _neg((c, v))
            if op == "+":
                return (c, v)
            if op == "%":
                return _div((c, v), (NUM, 100.0))
            return (UNK, None)

        if t == "binop":
            op = node["op"]
            if op == "&":
                return (STR, None)  # engine S(): always a string
            if op in CMP_OPS:
                return (BOOL, None)  # engine comparisons return booleans
            a = _to_num(*self.node(node["left"], sheet))
            b = _to_num(*self.node(node["right"], sheet))
            if op == "+":
                return _add(a, b)
            if op == "-":
                return _add(a, _neg(b))
            if op == "*":
                return _mul(a, b)
            if op == "/":
                return _div(a, b)
            if op == "^":
                return _pow(a, b)
            return (UNK, None)

        if t == "func":
            name = node.get("name")
            args = node.get("args", [])
            if name in BOOL_FUNCS:
                return (BOOL, None)
            if name == "IF":
                return self._if(args, sheet)
            return self._func(name, args, sheet)
        return (UNK, None)

    def _if(self, args, sheet):
        """ifL semantics: truthy only for non-zero numbers (NaN/±Inf truthy;
        booleans, strings and null are falsy).  A 2-arg IF's else branch is 0."""
        if not args:
            return (UNK, None)
        cc, cv = self.node(args[0], sheet)
        then = args[1] if len(args) > 1 else None
        if len(args) > 2:
            els = args[2]
        else:
            els = None if then is None else {"type": "num", "value": 0.0}
        if cc in (BOOL, NULL, STR):
            branch = els  # falsy -> else branch
        elif cc in (NAN, INF, NINF):
            branch = then  # non-zero numbers (incl. NaN, ±Inf) -> then branch
        elif cc == NUM and cv is not None:
            branch = then if cv != 0 else els
        else:  # unknown condition: result is one of the branches
            tc = self.node(then, sheet) if then is not None else (UNK, None)
            ec = self.node(els, sheet) if els is not None else (UNK, None)
            return tc if tc[0] == ec[0] else (UNK, None)
        if branch is None:
            return (NUM, 0.0)
        return self.node(branch, sheet)

    def _func(self, name, args, sheet):
        """Numeric functions.  `raw` keeps uncoerced classes: SUM/MIN/MAX
        ignore non-numbers (strings/blanks) rather than coercing them."""
        raw = []
        for arg in args:
            if isinstance(arg, dict) and arg.get("type") == "range":
                sheet2 = arg.get("sheet") or sheet
                for m in range_members(arg["start"], arg["end"]) or []:
                    raw.append(self.cell(f"{sheet2}!{m}"))
            else:
                raw.append(self.node(arg, sheet))

        if name in ("SUM", "MIN", "MAX"):
            if any(c == NAN for c, _ in raw):
                return (NAN, None)  # NaN is a number: it propagates
            if any(c == UNK for c, _ in raw):
                return (UNK, None)
            nums = [v for c, v in raw if c == NUM and v is not None]
            if name == "SUM":
                return (NUM, sum(nums))
            return (NUM, min(nums) if nums else 0.0) if name == "MIN" else (
                (NUM, max(nums) if nums else 0.0)
            )

        if name in ("EXP", "SQRT", "ABS", "INT"):
            if not raw:
                return (NUM, 0.0)
            c, v = _to_num(*raw[0])
            if c == NAN:
                return (NAN, None)
            if c == UNK:
                return (UNK, None)
            if c != NUM:
                return (NAN, None)  # Math.* of a non-number
            if name == "SQRT":
                if v is None:
                    return (UNK, None)  # sqrt of unknown sign
                if v < 0:
                    return (NAN, None)
                return (NUM, math.sqrt(v))
            if v is None:
                return (NUM, None)  # exp/abs/floor of any finite is finite
            if name == "EXP":
                try:
                    e = math.exp(v)
                except OverflowError:
                    return (INF, None)
                return ((INF, None) if math.isinf(e) else (NUM, e))
            if name == "ABS":
                return (NUM, abs(v))
            return (NUM, float(math.floor(v)))  # INT -> Math.floor

        if name == "ROUND":  # roundAway(x, d): non-numbers -> 0
            if not raw:
                return (NUM, 0.0)
            c, v = raw[0]
            if c == NAN:
                return (NAN, None)
            if c == NUM:
                return (NUM, None)
            if c == UNK:
                return (UNK, None)
            return (NUM, 0.0)

        if name == "N":  # n(x): numbers pass through (NaN too); else -> 0
            if not raw:
                return (NUM, 0.0)
            c, v = raw[0]
            if c == NAN:
                return (NAN, None)
            if c == NUM:
                return (NUM, v)
            if c == UNK:
                return (UNK, None)
            return (NUM, 0.0)

        if name == "COUNT":
            return (NUM, float(sum(1 for c, _ in raw if c == NUM)))
        if name == "AVERAGE":  # unused by this workbook; approximate
            if any(c == NAN for c, _ in raw):
                return (NAN, None)
            return (UNK, None)
        return (UNK, None)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def fmt_value(cls, grid_value):
    """One-line rendering of a referenced cell's value."""
    if grid_value is _ABSENT:
        return "<absent>"
    if grid_value is None:
        ann = {NULL: "blank", INF: "+Inf", NINF: "-Inf", NAN: "NaN", UNK: "?"}
        return f"null({ann.get(cls, cls)})"
    if isinstance(grid_value, str):
        s = grid_value if len(grid_value) <= 40 else grid_value[:40] + "…"
        return repr(s)
    if isinstance(grid_value, bool):
        return str(grid_value)
    if isinstance(grid_value, float) and grid_value != grid_value:
        return "NaN"
    if isinstance(grid_value, float) and grid_value.is_integer():
        return str(int(grid_value))
    return str(grid_value)


_ABSENT = object()


def main():
    grid, formulas, asts, graph, parse_errors = load_inputs()
    clf = Classifier(grid, formulas, asts)

    if parse_errors:
        print(f"warning: {len(parse_errors)} formula(s) failed to parse:")
        for msg in parse_errors[:10]:
            print(f"  {msg}")

    # NaN cells: grid entries whose value is NaN.  The dump encodes NaN as
    # null (so do blanks, null results and ±Infinity), so null-valued
    # formula cells are classified to isolate the true NaN cells.
    nan_cells = {
        key
        for key, value in grid.items()
        if (isinstance(value, float) and value != value)
        or (value is None and key in formulas and clf.cell(key)[0] == NAN)
    }

    # Breakdown of the dump's nulls (evidence the disambiguation is exact).
    null_breakdown = Counter()
    for key, value in grid.items():
        if value is None:
            if key not in formulas:
                null_breakdown["blank"] += 1
            else:
                null_breakdown[clf.cell(key)[0]] += 1
    nulls = sum(null_breakdown.values())

    print(f"grid dump: {GRID_PATH.relative_to(ROOT)} — {len(grid)} cells, "
          f"{nulls} null-valued")
    print(
        "null breakdown: "
        + " + ".join(
            f"{null_breakdown.get(k, 0)} {label}"
            for k, label in (
                (NAN, "NaN"), ("blank", "blank"), (NULL, "null-result"),
                (INF, "+Inf"), (NINF, "-Inf"), (UNK, "unresolved"),
            )
        )
    )
    print()

    per_sheet = Counter(key.rsplit("!", 1)[0] for key in nan_cells)
    print("NaN cells per sheet:")
    for sheet in sorted(per_sheet):
        print(f"  {sheet:<20}{per_sheet[sheet]:>6}")
    print(f"  {'total':<20}{len(nan_cells):>6}")
    print()

    # Roots: NaN cells whose referenced cells (per the graph) contain no NaN.
    roots = [
        key
        for key in sorted(nan_cells)
        if key in graph and not any(clf.cell(r)[0] == NAN for r in graph[key])
    ]
    groups = defaultdict(list)  # identical formulas (the 10 stat sheets repeat)
    for key in roots:
        groups[formulas[key]].append(key)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[1][0]))

    print(
        f"root NaN cells (referenced cells contain no NaN): "
        f"{len(roots)} cells, {len(ordered)} distinct formulas"
        + (f"; showing up to 15, grouped by identical formula" if len(ordered) > 15 else "")
    )
    for i, (form, cells) in enumerate(ordered[:15], 1):
        rep = cells[0]
        extra = ""
        if len(cells) > 1:
            others = ", ".join(cells[1:7])
            more = len(cells) - 1 - min(len(cells) - 1, 6)
            extra = f"  (same formula in {len(cells) - 1} more: {others}"
            extra += f", …{more} more)" if more > 0 else ")"
        print(f"  [{i}] {rep}{extra}")
        shown = form if len(form) <= 150 else form[:150] + "…"
        print(f"      formula: {shown}")
        refs = graph[rep]
        pairs = ", ".join(
            f"{r} → {fmt_value(clf.cell(r)[0], grid.get(r, _ABSENT))}"
            for r in refs[:12]
        )
        suffix = f"  … +{len(refs) - 12} more" if len(refs) > 12 else ""
        print(f"      refs ({len(refs)}): {pairs}{suffix}")
    if len(ordered) > 15:
        print(f"  … {len(ordered) - 15} more root formulas not shown")


if __name__ == "__main__":
    main()
