#!/usr/bin/env python3
"""
extract_literals.py — freeze every data sheet's literal cells into game.json.

Usage: .venv/bin/python tools/extract_literals.py

Reads, per data sheet (all 14: Baseline, Inputs, Comparison, the ten +Stat
sheets, Outputs):
  data/wow-12.1/formulas/<safe>.tsv   every non-empty cell ('='-prefixed
                                      content = formula cell)
  extracted/<safe>__values.tsv        cached value of every non-empty cell
  data/wow-12.1/game.json             existing {constants: [...]} (preserved)

and (re)writes the "cellLiterals" section of data/wow-12.1/game.json:

  "cellLiterals": { "<Sheet>": { "<REF>": <value>, ... }, ... }

one entry per literal (non-formula) cell — every values-TSV cell whose ref is
not a formula cell, i.e. exactly the literal set tools/emit_module.py emits
as consts. emit_module reads its literals from this section, so regenerating
src/engine/generated/ needs only the tracked formulas TSVs + game.json, not
the untracked extracted/ values TSVs.

Typing mirrors emit_module.ts_literal (whose regexes are imported, so the two
can never drift), and emit_module.literal_to_string is the exact inverse:
  'True'/'False'          JSON true/false
  integer literals        JSON int
  other numeric literals  JSON float (json's repr round-trips exactly)
  anything else            JSON string (trailing '\r\n' — the TSV file's final
                          newline — stripped first, as ts_literal strips it)

Verified per cell BEFORE anything is written (any failure aborts, exit 1):
  - json.loads(json.dumps(value)) reproduces the value and its type exactly
  - ts_literal(original TSV content) == ts_literal(reconstructed string), so
    the module emitted from game.json is byte-identical to the one emitted
    from the values TSVs
  - every literal cell of the formulas TSV has a values-TSV entry
  - no literal is <NO_CACHED_VALUE>
  - the constants section survives the rewrite deep-equal

Deterministic: same inputs -> byte-identical game.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formula_ast
from emit_module import (DATA_SHEETS, FLOAT_RE, GAME_JSON_PATH, INT_RE,
                         NO_CACHED_VALUE, ROOT, load_tsv_cells, ts_literal)

FORMULAS_DIR = os.path.join(ROOT, "data", "wow-12.1", "formulas")
VALUES_DIR = os.path.join(ROOT, "extracted")


def classify(content):
    """TSV literal content -> JSON value, typed exactly like ts_literal."""
    s = content.rstrip("\r\n")
    if s == "True":
        return True
    if s == "False":
        return False
    if INT_RE.fullmatch(s):
        return int(s)
    if FLOAT_RE.fullmatch(s):
        return float(s)
    return s


def to_tsv_string(v):
    """JSON value -> the TSV-equivalent string (emit_module's inverse:
    bool -> 'True'/'False', int -> str, float -> repr, str as-is)."""
    if isinstance(v, bool):              # first: bool is an int subtype
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return v                             # str


def main():
    problems = []
    cell_literals = {}
    for real in DATA_SHEETS:
        safe = formula_ast.STAT_SHEETS.get(real, real)
        fpath = os.path.join(FORMULAS_DIR, f"{safe}.tsv")
        vpath = os.path.join(VALUES_DIR, f"{safe}__values.tsv")
        if not os.path.isfile(fpath):
            print(f"error: missing {fpath}", file=sys.stderr)
            return 1
        if not os.path.isfile(vpath):
            print(f"error: missing {vpath} — run extract_xlsx.py first",
                  file=sys.stderr)
            return 1
        formulas = {c.upper() for c in formula_ast.load_formulas(fpath)}
        values = load_tsv_cells(vpath)
        fcells = load_tsv_cells(fpath)
        literals = {c: v for c, v in values.items() if c not in formulas}

        for c in sorted(set(fcells) - set(formulas) - set(values)):
            problems.append(f"{real}!{c}: literal cell missing from the "
                            f"values TSV")
        for c in sorted(literals):
            if literals[c].rstrip("\r\n") == NO_CACHED_VALUE:
                problems.append(f"{real}!{c}: literal cell has no cached "
                                f"value")

        sheet = {}
        counts = {"int": 0, "float": 0, "str": 0, "bool": 0}
        for ref, content in literals.items():
            value = classify(content)
            rt = json.loads(json.dumps(value))
            if type(rt) is not type(value) or rt != value:
                problems.append(f"{real}!{ref}: JSON round-trip not exact: "
                                f"{value!r} -> {rt!r}")
            if ts_literal(content) != ts_literal(to_tsv_string(value)):
                problems.append(f"{real}!{ref}: emitted literal would change: "
                                f"{content!r} -> {to_tsv_string(value)!r}")
            sheet[ref] = value
            if isinstance(value, bool):
                counts["bool"] += 1
            elif isinstance(value, int):
                counts["int"] += 1
            elif isinstance(value, float):
                counts["float"] += 1
            else:
                counts["str"] += 1
        cell_literals[real] = sheet
        print(f"{real}: {len(sheet)} literals "
              f"(int={counts['int']} float={counts['float']} "
              f"str={counts['str']} bool={counts['bool']})")

    if problems:
        n = len(problems)
        print(f"error: {n} problem{'s' if n > 1 else ''} — "
              f"{os.path.relpath(GAME_JSON_PATH, ROOT)} not written:",
              file=sys.stderr)
        for p in problems[:20]:
            print(f"    {p}", file=sys.stderr)
        if n > 20:
            print(f"    ... +{n - 20} more", file=sys.stderr)
        return 1

    try:
        with open(GAME_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"error: cannot load {GAME_JSON_PATH}: {e}", file=sys.stderr)
        return 1
    if not isinstance(data.get("constants"), list):
        print(f"error: {GAME_JSON_PATH} has no constants section — refusing "
              f"to overwrite", file=sys.stderr)
        return 1
    old_constants = data["constants"]
    data["cellLiterals"] = cell_literals
    text = json.dumps(data, indent=2) + "\n"
    if json.loads(text)["constants"] != old_constants:
        print("error: constants section would change — refusing to write",
              file=sys.stderr)
        return 1
    with open(GAME_JSON_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    total = sum(len(s) for s in cell_literals.values())
    print(f"wrote {os.path.relpath(GAME_JSON_PATH, ROOT)}: cellLiterals for "
          f"{len(cell_literals)} sheets, {total} cells, "
          f"{os.path.getsize(GAME_JSON_PATH)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
