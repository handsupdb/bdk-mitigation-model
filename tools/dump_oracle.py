#!/usr/bin/env python3
"""
tools/dump_oracle.py — dump the oracle's computed cell values and diff them
against the TS engine's grid dump.

The oracle is extracted/verify_chains.py: a from-scratch Excel-formula
evaluator that computes every formula cell of the 13 calc sheets (Baseline,
Comparison, the 10 +Stat probe sheets, Outputs) from the Inputs literals —
proven exact against the workbook's cached values (9,598 exact matches).
This script imports it (nothing else is modified) and reuses its evaluation:

  1. Evaluate every formula cell via verify_chains.get_cell() and dump
     {"<Sheet>!<ref>": value} to tests/fixtures/oracle_dump.json — numbers at
     full precision (json emits repr(), the shortest round-tripping decimal;
     the reload is verified bit-exact via float.hex()), strings as strings,
     blanks as null. Cells whose evaluation raises (none currently) are
     skipped and reported.

  2. Diff against tests/fixtures/grid_dump.json (the TS engine's dump, written
     by tests/engine/grid.dump.test.ts) for every key present in BOTH dumps:
       - numbers -> symmetric relative difference |a-b|/max(|a|,|b|),
                    divergent when rel > 1e-12
       - strings -> exact equality
       - other   (null/bool/type mixes) -> JSON-representation equality
     Report: total compared, divergent counts, and the first 10 divergent
     cells with the formula from data/wow-12.1/formulas/<sheet>.tsv
     (truncated to 120 chars).

  3. BIT-EXACT diff of the same keys. The rel-tol pass can look clean while
     sub-1e-12 ulp noise exists upstream (it did: 0 numeric divergent at
     1e-12, yet 3 Outputs strings differed on value noise). Numbers compare
     float.hex() of the parsed doubles (exact bit equality; -0.0 != 0.0),
     strings compare exactly. The differing cells are then ordered by
     DEPENDENCY order — a reference graph built with tools/formula_ast over
     data/wow-12.1/formulas/*.tsv (the same pattern as tools/diag_nan.py),
     topologically sorted (iterative DFS post-order; cycles — none expected,
     the oracle evaluates without CycleError — are cut at the back-edge) —
     and the first 10 are reported: the earliest places bit-exactness breaks.
     Each shows sheet!ref, oracle value, engine value, rel diff, formula
     (truncated to 120 chars), whether its formula calls EXP (suspect: V8
     Math.exp vs Python math.exp ulp differences), and whether it is a root
     divergence (no referenced cell differs) or downstream of differing refs.

  4. Print the report; exit 0 (divergences are reported, not fatal).

Run: .venv/bin/python tools/dump_oracle.py
(The script chdirs to the repo root itself because verify_chains loads its
extracted/*.tsv inputs via relative paths.)
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)  # verify_chains reads extracted/*.tsv by relative path
sys.path.insert(0, str(ROOT / "extracted"))
sys.path.insert(0, str(ROOT / "tools"))

import verify_chains as vc  # noqa: E402  (the proven oracle)
import formula_ast  # noqa: E402  (tools/formula_ast.py — parse/load_formulas/STAT_SHEETS)

ORACLE_PATH = ROOT / "tests" / "fixtures" / "oracle_dump.json"
GRID_PATH = ROOT / "tests" / "fixtures" / "grid_dump.json"
FORMULAS_DIR = ROOT / "data" / "wow-12.1" / "formulas"

REL_TOL = 1e-12        # numeric divergence threshold (relative)
MAX_REPORT = 10        # first N divergent cells to print
FORMULA_TRUNC = 120    # formula display truncation
VALUE_TRUNC = 160      # string-value display truncation
MAX_RANGE_CELLS = 100_000  # same cap as tools/diag_nan.py / tools/emit_module.py


# ---------------------------------------------------------------- oracle dump

def evaluate_oracle() -> tuple[dict, list]:
    """Every formula cell of the 13 calc sheets -> {"<Sheet>!<ref>": value}."""
    out: dict[str, object] = {}
    errors: list[tuple[str, str]] = []
    for sheet in vc.SHEETS:
        if sheet == "Inputs":  # literal source sheet, not a calc sheet
            continue
        for ref in vc.F[sheet]:
            key = f"{sheet}!{ref}"
            try:
                out[key] = vc.get_cell(sheet, ref)
            except Exception as e:  # CycleError/EvalError/SyntaxError/...
                errors.append((key, repr(e)[:120]))
    return out, errors


def write_dump(oracle: dict) -> tuple[int, int]:
    """Write oracle_dump.json and verify the JSON round-trips every value.

    Returns (cell count, double count). Raises AssertionError on any
    precision loss, so a silent corruption can never pass through.
    """
    with open(ORACLE_PATH, "w", encoding="utf-8") as f:
        json.dump(oracle, f, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)  # NaN/Inf would be invalid JSON: fail loudly
        f.write("\n")
    with open(ORACLE_PATH, encoding="utf-8") as f:
        reloaded = json.load(f)
    doubles = 0
    for key, v in oracle.items():
        r = reloaded[key]
        if isinstance(v, float):
            doubles += 1
            if not isinstance(r, float) or r.hex() != v.hex():  # bit-exact
                raise AssertionError(
                    f"round-trip lost precision: {key} {v!r} -> {r!r}")
        elif type(v) is not type(r) or v != r:
            raise AssertionError(
                f"round-trip changed value: {key} {v!r} -> {r!r}")
    return len(oracle), doubles


# ---------------------------------------------------------------- diff

def is_num(v) -> bool:
    """JSON number (int/float) — bool is excluded despite being an int subtype."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def rel_diff(a: float, b: float) -> float:
    """Symmetric relative difference |a-b|/max(|a|,|b|); 0.0 when equal."""
    if a == b:
        return 0.0
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom if denom else math.inf


_formula_cache: dict[str, dict] = {}


def formulas_for(sheet: str) -> dict:
    """ref -> formula, from data/wow-12.1/formulas/<stem>.tsv (display only)."""
    if sheet not in _formula_cache:
        stem = vc.STAT_SHEETS.get(sheet, sheet)
        path = FORMULAS_DIR / f"{stem}.tsv"
        _formula_cache[sheet] = vc.load_tsv(str(path))[0] if path.is_file() else {}
    return _formula_cache[sheet]


def fmt(v) -> str:
    """Compact display form: repr, with long strings truncated."""
    s = repr(v)
    return s if len(s) <= VALUE_TRUNC else s[: VALUE_TRUNC - 3] + "..."


# ------------------------------------------------- reference graph (formula_ast)
# (mirrors tools/diag_nan.py load_inputs(): same A1 helpers, same walk)

REF_RE = re.compile(r"^\$?([A-Za-z]+)\$?([0-9]+)$")


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


def build_graph():
    """Reference graph over data/wow-12.1/formulas/*.tsv (diag_nan.py pattern).

    Returns (formulas, graph, funcs, parse_errors):
      formulas: {"Sheet!Ref": formula text} ('='-prefixed; real sheet names)
      graph:    {"Sheet!Ref": [referenced "Sheet!Ref", ...]} (ordered, deduped;
                same-sheet refs, range members, cross-sheet refs)
      funcs:    {"Sheet!Ref": set of function names the formula calls}
    """
    safe_to_real = {stem: real for real, stem in formula_ast.STAT_SHEETS.items()}
    formulas, graph, funcs = {}, {}, {}
    parse_errors: list[str] = []
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
            names, refs, seen = set(), [], set()
            for node in iter_nodes(ast):
                if node.get("type") == "func":
                    names.add(node.get("name"))
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
            funcs[key] = names
    return formulas, graph, funcs, parse_errors


def topo_order(graph: dict) -> dict:
    """Dependency-first ordering: iterative DFS post-order over the graph.

    Every key lands after all its (reachable) references; deterministic
    (sorted roots and neighbors). Back-edges — cycles, none expected: the
    oracle evaluates every cell without CycleError — are cut at the edge so
    the ordering always completes. Returns {key: index}.
    """
    order: dict[str, int] = {}
    state: dict[str, int] = {}  # 1 = visiting, 2 = done
    for root in sorted(graph):
        if state.get(root):
            continue
        state[root] = 1
        stack = [(root, iter(sorted(graph.get(root, ()))))]
        while stack:
            key, deps = stack[-1]
            pushed = False
            for dep in deps:
                if state.get(dep):  # done, or visiting (cycle): skip
                    continue
                state[dep] = 1
                stack.append((dep, iter(sorted(graph.get(dep, ())))))
                pushed = True
                break
            if not pushed:
                stack.pop()
                state[key] = 2
                order[key] = len(order)
    return order


def has_exp(key: str, formulas: dict, funcs: dict) -> bool:
    """Does the cell's formula call EXP? AST func names when parsed, else text."""
    if key in funcs:
        return "EXP" in funcs[key]
    sheet, _, ref = key.rpartition("!")
    form = formulas.get(key) or formulas_for(sheet).get(ref) or ""
    return bool(re.search(r"\bEXP\s*\(", form, re.IGNORECASE))


# ---------------------------------------------------------------- main

def main() -> int:
    oracle, errors = evaluate_oracle()
    cells, doubles = write_dump(oracle)

    with open(GRID_PATH, encoding="utf-8") as f:
        grid = json.load(f)

    common = sorted(k for k in oracle if k in grid)

    # ---- pass 1: relative-tolerance diff (the original behavior) ----
    num_cmp = num_div = str_cmp = str_div = oth_cmp = oth_div = 0
    max_rel = 0.0
    divergent: list[tuple[str, object, object, str]] = []
    for k in common:
        ov, ev = oracle[k], grid[k]
        if is_num(ov) and is_num(ev):
            num_cmp += 1
            rel = rel_diff(float(ov), float(ev))
            max_rel = max(max_rel, rel)
            if rel > REL_TOL:
                num_div += 1
                divergent.append((k, ov, ev, f"rel={rel:.6g}"))
        elif isinstance(ov, str) and isinstance(ev, str):
            str_cmp += 1
            if ov != ev:
                str_div += 1
                divergent.append((k, ov, ev, "string mismatch"))
        else:
            oth_cmp += 1
            if json.dumps(ov) != json.dumps(ev):
                oth_div += 1
                divergent.append((k, ov, ev, f"type mismatch: "
                                 f"{type(ov).__name__} vs {type(ev).__name__}"))
    total_div = num_div + str_div + oth_div

    print("=== ORACLE DUMP ===")
    print(f"  wrote {cells} cells ({doubles} doubles, JSON round-trip "
          f"bit-exact) -> {ORACLE_PATH.relative_to(ROOT)}")
    for key, err in errors:
        print(f"  EVAL ERROR {key}: {err}")
    print(f"  engine dump: {len(grid)} cells ({GRID_PATH.relative_to(ROOT)})")

    print(f"\n=== ORACLE vs ENGINE GRID DIFF (keys in both; rel tol {REL_TOL:g}) ===")
    print(f"  compared: {len(common)}  "
          f"(oracle-only: {len(oracle) - len(common)}, "
          f"engine-only: {len(grid) - len(common)})")
    print(f"  numeric : {num_cmp} compared, {num_div} divergent "
          f"(rel > {REL_TOL:g}; max rel {max_rel:.3g})")
    print(f"  strings : {str_cmp} compared, {str_div} divergent (exact equality)")
    print(f"  other   : {oth_cmp} compared, {oth_div} divergent (null/bool/type)")
    print(f"  TOTAL DIVERGENT: {total_div}")

    print(f"\n  first {MAX_REPORT} divergent cells:")
    shown = divergent[:MAX_REPORT]
    for i, (k, ov, ev, why) in enumerate(shown, 1):
        sheet, _, ref = k.partition("!")
        formula = formulas_for(sheet).get(ref) or "<no formula>"
        if len(formula) > FORMULA_TRUNC:
            formula = formula[:FORMULA_TRUNC] + "..."
        print(f"  {i:>2}. {k}  [{why}]")
        print(f"      oracle : {fmt(ov)}")
        print(f"      engine : {fmt(ev)}")
        print(f"      formula: {formula}")
    if not shown:
        print("      none — every compared cell agrees")
    elif total_div > MAX_REPORT:
        print(f"  ... and {total_div - MAX_REPORT} more")

    # ---- pass 2: bit-exact diff, dependency-ordered ----
    formulas, graph, funcs, parse_errors = build_graph()
    order = topo_order(graph)

    bit_match = bit_differ = 0
    per_cat = {"numeric": [0, 0], "string": [0, 0], "other": [0, 0]}  # [match, differ]
    differing: list[tuple[str, object, object, str]] = []
    for k in common:
        ov, ev = oracle[k], grid[k]
        if is_num(ov) and is_num(ev):
            cat = "numeric"
            a, b = float(ov), float(ev)
            eq = a.hex() == b.hex()
            if eq:
                why = ""
            elif a == 0.0 == b:  # same zero, different sign: -0.0 vs 0
                why = ("rel=0; -0.0 vs 0 (sign of zero — the engine dump's "
                       "JSON.stringify collapses -0 to 0, so possibly an "
                       "artifact, not a real divergence)")
            else:
                why = f"rel={rel_diff(a, b):.3g}"
        elif isinstance(ov, str) and isinstance(ev, str):
            cat = "string"
            eq = ov == ev
            why = "" if eq else "string mismatch"
        else:
            cat = "other"
            eq = json.dumps(ov) == json.dumps(ev)
            why = "" if eq else "type/value mismatch"
        per_cat[cat][0 if eq else 1] += 1
        if eq:
            bit_match += 1
        else:
            bit_differ += 1
            differing.append((k, ov, ev, why))

    diff_set = {d[0] for d in differing}
    no_graph = sorted(k for k in diff_set if k not in graph)
    # dependency order; cells with no parsed formula (deps unknown) sort last
    differing.sort(key=lambda d: (order[d[0]] if d[0] in graph else len(order), d[0]))

    print("\n=== BIT-EXACT DIFF (float.hex() of parsed doubles; strings exact) ===")
    print(f"  compared: {len(common)}   bit-exact matches: {bit_match}   "
          f"differing: {bit_differ}")
    print(f"  numeric : {per_cat['numeric'][0]} bit-exact, "
          f"{per_cat['numeric'][1]} differing (ulp-level, sub-{REL_TOL:g})")
    print(f"  string  : {per_cat['string'][0]} exact, {per_cat['string'][1]} differing")
    print(f"  other   : {per_cat['other'][0]} equal, {per_cat['other'][1]} differing")
    print(f"  reference graph: {len(graph)} formula cells "
          f"({len(parse_errors)} parse errors)"
          + (f"; {len(no_graph)} differing cells not in graph (ordered last): "
             + ", ".join(no_graph[:5]) if no_graph else ""))
    for msg in parse_errors[:5]:
        print(f"    parse error: {msg}")

    exp_count = sum(1 for d in differing if has_exp(d[0], formulas, funcs))
    print(f"\n  differing cells in DEPENDENCY ORDER (first = earliest divergence);")
    print(f"  EXP called in {exp_count} of {bit_differ} differing formulas:")
    shown = differing[:MAX_REPORT]
    for i, (k, ov, ev, why) in enumerate(shown, 1):
        sheet, _, ref = k.rpartition("!")
        formula = formulas.get(k) or formulas_for(sheet).get(ref) or "<no formula>"
        if len(formula) > FORMULA_TRUNC:
            formula = formula[:FORMULA_TRUNC] + "..."
        refs = graph.get(k, ())
        ndiff = sum(1 for r in refs if r in diff_set)
        origin = ("root (no differing refs)" if ndiff == 0
                  else f"downstream ({ndiff} differing refs)")
        exp = "EXP=yes" if has_exp(k, formulas, funcs) else "EXP=no"
        print(f"  {i:>2}. {k}  [{why}]  {exp}  {origin}")
        print(f"      oracle : {fmt(ov)}")
        print(f"      engine : {fmt(ev)}")
        print(f"      formula: {formula}")
    if not shown:
        print("      none — every compared cell is bit-exact")
    elif bit_differ > MAX_REPORT:
        print(f"  ... and {bit_differ - MAX_REPORT} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
