#!/usr/bin/env python3
"""
transpile.py — transpile excel_mitigation_model.xlsx (14 data sheets) to code.

SLICE 1 — data copy + in-sheet dependency graph + topo order (no codegen yet):

  1. Copy each data sheet's formula TSV (extracted/<safe>__formulas.tsv) to
     data/wow-12.1/formulas/<safe>.tsv. The copies are tracked data (the
     extracted/ TSVs are gitignored, regenerable via extract_xlsx.py);
     data/wow-12.1/formulas/ is the patch-edit surface the transpiler reads
     from now on.
  2. Per sheet: parse every formula (formula_ast.parse), build the in-sheet
     dependency graph (formula cell -> same-sheet referenced cells; ranges
     expanded to their rectangle; cross-sheet refs tallied separately), and
     topo-sort the formula cells dependencies-first (Kahn). Literals =
     cells in extracted/<safe>__values.tsv that are not formula cells.
  3. Print per sheet: formula count, literal count, topo layer count,
     cross-sheet dependency summary, cycle count, parse-failure count.
  4. Exit 0 unless hard anomalies (parse failures, unknown target sheets,
     oversized ranges, literal cells missing from the values TSV, stalls).

CYCLES (known data property, reported not fatal): the STATIC graph (all IF
branches, ranges fully expanded) of the Comparison sheet contains exactly 3
two-cycles — C5<->H5, C6<->H6, C7<->H7 — mutual IF-fallbacks gated on the same
ISBLANK(Inputs!Hn) condition; each cell references the other only in the
branch where the other does not reference it back, so the LIVE (branch-
following) graph is acyclic and Excel's cached values verify exactly (see
extracted/verify_chains.py, whose IF evaluation short-circuits and whose
depth pass masks back-edges — which is why it never reported these).
Topo order breaks each cyclic SCC deterministically: within an SCC, only
dependency edges that point to lexicographically EARLIER cells are kept
(for this data that removes C5->H5, C6->H6, C7->H7 and yields the
live-correct order, since Inputs!H7:H9 are non-blank: live Cn = Inputs
value, Hn = Cn/...). The codegen slice must still handle these 3 pairs
explicitly (branch-aware ordering or lazy emission).

Data sheets (14; Instructions is documentation, not data):
  Baseline, Inputs, Comparison, the 10 +Stat sheets, Outputs.

Usage: .venv/bin/python tools/transpile.py
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formula_ast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACTED_DIR = os.path.join(ROOT, "extracted")
FORMULAS_DIR = os.path.join(ROOT, "data", "wow-12.1", "formulas")

STAT_SHEETS = formula_ast.STAT_SHEETS          # real name -> safe stem
DATA_SHEETS = ["Baseline", "Inputs", "Comparison"] + list(STAT_SHEETS) + ["Outputs"]
KNOWN_SHEETS = set(DATA_SHEETS) | {"Instructions"}
MAX_RANGE_CELLS = 100_000


# ---------------------------------------------------------------- TSV loading
def load_tsv_cells(path):
    """cell_ref -> raw content for every row of a __formulas/__values TSV,
    with the same embedded-newline repair as formula_ast.load_formulas."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    repaired = []
    for ln in raw.split("\n"):
        if ln == "" and not repaired:
            continue
        if repaired and not re.match(r"^[A-Za-z]{1,3}[0-9]+\t", ln):
            repaired[-1] += "\n" + ln          # continuation of previous cell
        else:
            repaired.append(ln)
    cells = {}
    for ln in repaired:
        if not ln:
            continue
        parts = ln.split("\t", 1)
        if len(parts) == 2:
            cells[parts[0].upper()] = parts[1]
    return cells


# ---------------------------------------------------------------- ref helpers
def col_to_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def num_to_col(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def expand_range(start, end):
    """Every cell ref in the rectangle start..end, or None if it exceeds
    MAX_RANGE_CELLS (caller records an anomaly)."""
    c1, r1 = formula_ast.split_ref(start)
    c2, r2 = formula_ast.split_ref(end)
    n1, n2 = col_to_num(c1), col_to_num(c2)
    lo_c, hi_c = min(n1, n2), max(n1, n2)
    lo_r, hi_r = min(r1, r2), max(r1, r2)
    if (hi_c - lo_c + 1) * (hi_r - lo_r + 1) > MAX_RANGE_CELLS:
        return None
    return [f"{num_to_col(c)}{r}"
            for r in range(lo_r, hi_r + 1)
            for c in range(lo_c, hi_c + 1)]


def iter_ref_nodes(node):
    """Yield every ref/range node of an AST (they have no child expressions)."""
    if isinstance(node, dict):
        if node.get("type") in ("ref", "range"):
            yield node
            return
        for v in node.values():
            yield from iter_ref_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_ref_nodes(v)


# ---------------------------------------------------------------- per-sheet
def analyze_sheet(sheet, formulas, known_cells):
    """Parse every formula; build in-sheet deps + cross-sheet tallies.

    formulas: cell -> formula string. Returns dict with:
      deps           formula cell -> set of same-sheet referenced cells
      cross          target sheet -> [ref hits, range hits]
      parse_failures (cell, message) pairs
      oversized      (cell, 'A1:B2') ranges too large to expand
      unknown        (cell, target sheet) refs to sheets that do not exist
    """
    deps = {c: set() for c in formulas}
    cross = {}
    parse_failures, oversized, unknown = [], [], []
    for cell in sorted(formulas):
        try:
            ast = formula_ast.parse(formulas[cell], sheet=sheet)
        except SyntaxError as e:
            parse_failures.append((cell, str(e)))
            continue
        for node in iter_ref_nodes(ast):
            target = node["sheet"]
            if node["type"] == "ref":
                if target == sheet:
                    deps[cell].add(node["ref"].upper())
                else:
                    hit = cross.setdefault(target, [0, 0])
                    hit[0] += 1
                    if target not in KNOWN_SHEETS:
                        unknown.append((cell, target))
            else:                              # range
                if target == sheet:
                    cells = expand_range(node["start"], node["end"])
                    if cells is None:
                        oversized.append((cell, f"{node['start']}:{node['end']}"))
                        deps[cell].update(
                            (node["start"].upper(), node["end"].upper()))
                    else:
                        deps[cell].update(c for c in cells if c in known_cells)
                else:
                    hit = cross.setdefault(target, [0, 0])
                    hit[1] += 1
                    if target not in KNOWN_SHEETS:
                        unknown.append((cell, target))
    return {"deps": deps, "cross": cross, "parse_failures": parse_failures,
            "oversized": oversized, "unknown": unknown}


def find_sccs(formulas, fdeps):
    """Tarjan SCCs over the static formula graph (list of components)."""
    index, low, onstk, stk, comps, counter = {}, {}, {}, [], [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stk.append(v)
        onstk[v] = True
        for w in sorted(fdeps.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif onstk.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stk.pop()
                onstk[w] = False
                comp.append(w)
                if w == v:
                    break
            comps.append(comp)

    for v in sorted(formulas):
        if v not in index:
            visit(v)
    return comps


def break_cycles(fdeps, comps):
    """Cycle cells + deterministic cycle-breaking: within each cyclic SCC
    (>1 cell, or a self-edge), keep only dep edges that point to
    lexicographically EARLIER cells, so kept edges run later->earlier and
    the SCC becomes a DAG ordered by cell name. Mutates fdeps; returns
    (cycle_cells, removed_edges). Downstream-of-cycle cells are not
    cycle cells."""
    cycle_cells, removed = set(), []
    for comp in comps:
        cs = set(comp)
        if len(comp) == 1 and comp[0] not in fdeps.get(comp[0], ()):
            continue                              # trivial SCC
        cycle_cells.update(cs)
        for c in comp:
            for d in sorted(fdeps[c]):
                if d in cs and c <= d:             # points later (or self)
                    fdeps[c].discard(d)
                    removed.append((c, d))
    return cycle_cells, removed


def topo_order(formulas, fdeps):
    """Kahn topo order over formula cells, dependencies first, in rounds.

    layer[c] = the round at which c is emitted; every dep of c is emitted
    in an earlier round. fdeps must be acyclic (break_cycles first).
    Returns (order, layer, stalled): stalled lists cells that could not be
    ordered (a bug marker after cycle-breaking; expect [])."""
    rdeps = {c: set() for c in formulas}
    for c, ds in fdeps.items():
        for d in ds:
            rdeps[d].add(c)
    remaining = {c: set(ds) for c, ds in fdeps.items()}
    order, layer = [], {}
    unprocessed = set(formulas)
    round_no = 0
    while unprocessed:
        round_no += 1
        ready = sorted(c for c in unprocessed if not remaining[c])
        if not ready:                          # stall: input not acyclic
            return order, layer, sorted(unprocessed)
        for c in ready:
            order.append(c)
            layer[c] = round_no
            unprocessed.discard(c)
        for c in ready:                        # release dependents
            for dep in rdeps[c]:
                if dep in unprocessed:
                    remaining[dep].discard(c)
    return order, layer, []


# ---------------------------------------------------------------- driver
def main():
    print("transpile.py slice 1: data copy + dependency graph + topo order")

    # [1] copy formula TSVs -> data/wow-12.1/formulas/ (patch-edit surface)
    os.makedirs(FORMULAS_DIR, exist_ok=True)
    total_bytes = 0
    for sheet in DATA_SHEETS:
        stem = STAT_SHEETS.get(sheet, sheet)
        src = os.path.join(EXTRACTED_DIR, f"{stem}__formulas.tsv")
        if not os.path.isfile(src):
            print(f"error: missing {src} — run extract_xlsx.py first",
                  file=sys.stderr)
            return 1
        shutil.copyfile(src, os.path.join(FORMULAS_DIR, f"{stem}.tsv"))
        total_bytes += os.path.getsize(src)
    print(f"[1] copied {len(DATA_SHEETS)} formula TSVs -> "
          f"data/wow-12.1/formulas/ ({total_bytes:,} bytes)")

    # [2] per-sheet graph stats (formulas parsed from the copied TSVs)
    print("[2] per-sheet dependency graph + topo order:")
    print(f"{'sheet':<17}{'formulas':>9}{'literals':>9}{'layers':>7}"
          f"{'cyc':>4}{'err':>4}  cross-sheet refs")
    tot_f = tot_l = tot_x = max_layers = 0
    failures, notes = [], []
    for sheet in DATA_SHEETS:
        stem = STAT_SHEETS.get(sheet, sheet)
        fpath = os.path.join(FORMULAS_DIR, f"{stem}.tsv")
        vpath = os.path.join(EXTRACTED_DIR, f"{stem}__values.tsv")
        formulas = {k.upper(): v
                    for k, v in formula_ast.load_formulas(fpath).items()}
        tsv_cells = load_tsv_cells(fpath)
        values = load_tsv_cells(vpath)
        literals = set(values) - set(formulas)
        known_cells = set(tsv_cells) | set(values)
        orphan_literals = set(tsv_cells) - set(formulas) - set(values)

        rep = analyze_sheet(sheet, formulas, known_cells)
        fdeps = {c: {d for d in ds if d in formulas}
                 for c, ds in rep["deps"].items()}
        cycle_cells, removed_edges = break_cycles(fdeps, find_sccs(formulas, fdeps))
        order, layer, stalled = topo_order(formulas, fdeps)
        layers = max(layer.values()) if layer else 0
        cross_txt = ", ".join(
            f"{t}: {n[0] + n[1]}" + (f" ({n[1]} ranges)" if n[1] else "")
            for t, n in sorted(rep["cross"].items())) or "-"
        print(f"{sheet:<17}{len(formulas):>9}{len(literals):>9}{layers:>7}"
              f"{len(cycle_cells):>4}{len(rep['parse_failures']):>4}  {cross_txt}")

        tot_f += len(formulas)
        tot_l += len(literals)
        tot_x += sum(n[0] + n[1] for n in rep["cross"].values())
        max_layers = max(max_layers, layers)
        if cycle_cells:
            edges = ", ".join(f"{c}->{d}" for c, d in sorted(removed_edges))
            notes.append(
                f"{sheet}: {len(cycle_cells)} cells on static cycles "
                f"[{', '.join(sorted(cycle_cells))}] — mutual IF-fallbacks "
                f"(see module docstring); topo broke back-edges: {edges}")
        if stalled:
            failures.append(f"{sheet}: topo stalled on {len(stalled)} cells "
                            f"after cycle-breaking (e.g. {stalled[:6]})")
        for cell, msg in rep["parse_failures"]:
            failures.append(f"{sheet}!{cell}: parse failed: {msg}")
        for cell, rng in rep["oversized"]:
            failures.append(
                f"{sheet}!{cell}: range {rng} exceeds {MAX_RANGE_CELLS} cells")
        for cell, tgt in rep["unknown"]:
            failures.append(f"{sheet}!{cell}: references unknown sheet {tgt!r}")
        for cell in sorted(orphan_literals):
            failures.append(f"{sheet}!{cell}: literal cell missing from values TSV")

    print(f"[3] totals: {tot_f} formulas, {tot_l} literals, {tot_x} cross-sheet "
          f"ref occurrences, max topo layers {max_layers}")
    if notes:
        print(f"[4] cycle notes ({len(notes)}):")
        for n in notes:
            print(f"    {n}")
    if failures:
        print(f"[5] anomalies ({len(failures)}):")
        for a in failures[:40]:
            print(f"    {a}")
        if len(failures) > 40:
            print(f"    ... +{len(failures) - 40} more")
        return 1
    print("[5] anomalies: none (0 parse failures, 0 unknown sheets, "
          "0 oversized ranges, 0 orphan literals, 0 stalls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
