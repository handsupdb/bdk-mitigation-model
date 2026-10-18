#!/usr/bin/env python3
"""
templatize.py — apply the constants templatization proposed by
tools/propose_constants.py (extracted/constants_proposal.json) to
data/wow-12.1/formulas/*.tsv and write data/wow-12.1/game.json.

This pass applies UNAMBIGUOUS entries only: a substitution is kept iff its
value maps to exactly one documented name. Every substitution whose value has
multiple candidate names (0.05, 0.2, 0.3, 0.7, 0.85, 2, 3, 5, 6, 8, 10, 0.06,
0.075, 0.08, 0.15) is skipped and its literals stay untouched.

Each kept substitution (sheet, cell, literal, name) rewrites only that cell's
formula: every number token in it whose float value equals `literal` becomes
{{name}}. A number token counts only at token boundaries — the characters
adjacent to it must not be a digit, '.', identifier character, or '$' (so
refs like C92 or $J$9 are never touched) — and matches inside quoted strings
("..." with "" escapes) or existing {{...}} templates never count.

Outputs:
  data/wow-12.1/formulas/<stem>.tsv  rewritten in place; line/cell structure
    preserved, only substituted formulas change
  data/wow-12.1/game.json            MERGE: the existing file (if any) is
    loaded and only the "constants" key is replaced — every other key
    (e.g. cellLiterals, written by tools/extract_literals.py) is preserved;
    {"constants": [{name, value, meaning, occurrences}]} — applied
    unambiguous entries only, sorted by name; occurrences = number of
    applied substitution records for that constant

Idempotent: re-running on already-templated TSVs changes nothing. A
substitution whose {{name}} is already present in the cell (applied by a
previous run) counts as applied — toward occurrences and the constants
section — without touching the formula, so the rewritten game.json is
byte-identical and no other key is dropped.

Safety gate (aborts with NO writes if it fails): for every modified formula,
resolving each {{name}} back to its value must reproduce a formula that
parses with tools/formula_ast and whose token stream (numbers compared by
float value) is identical to the original's — this catches any corruption
of refs, strings, operators, or structure. After writing, every formula file
is reloaded and its formula count must be unchanged.

Run: .venv/bin/python tools/templatize.py
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formula_ast  # noqa: E402  (sibling module in tools/)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMULA_DIR = os.path.join(ROOT, "data", "wow-12.1", "formulas")
PROPOSAL_PATH = os.path.join(ROOT, "extracted", "constants_proposal.json")
GAME_JSON_PATH = os.path.join(ROOT, "data", "wow-12.1", "game.json")

# Number token — same shape as the number alternative in formula_ast.TOKEN_RE.
NUM_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# Quoted Excel string with "" escapes — same as the formula_ast tokenizer.
STRING_RE = re.compile(r'"(?:[^"]|"")*"')
# {{...}} template; constant names contain no braces.
TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
# A number is a standalone token only if neither neighbor is one of these:
# digits, '.', identifier characters, '$' (anchored refs like $J$9).
ADJACENT = set("0123456789.$_"
               "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
LINE_RE = re.compile(r"^([A-Za-z]{1,3}[0-9]+)\t")


def cell_key(cell):
    """Sort key for A1-style refs: by row number, then column letters."""
    m = CELL_RE.match(cell.upper())
    return (int(m.group(2)), m.group(1)) if m else (0, cell.upper())


def skip_spans(text):
    """Spans (start, end) of quoted strings and {{...}} templates — regions
    where number tokens must never be substituted."""
    return ([m.span() for m in STRING_RE.finditer(text)] +
            [m.span() for m in TEMPLATE_RE.finditer(text)])


def replace_literal(formula, literal, name):
    """Replace every token-boundary occurrence of numeric `literal` in
    `formula` with {{name}}. Returns (new_formula, n_tokens_replaced)."""
    spans = skip_spans(formula)
    out, last, n = [], 0, 0
    for m in NUM_RE.finditer(formula):
        s, e = m.span()
        if any(s < b and e > a for a, b in spans):
            continue                      # inside a string or {{...}}
        if s and formula[s - 1] in ADJACENT:
            continue                      # e.g. the 10 in C92 / O10%
        if e < len(formula) and formula[e] in ADJACENT:
            continue                      # e.g. the 1 in 1.45's tail
        if float(m.group()) != literal:
            continue
        out.append(formula[last:s])
        out.append("{{" + name + "}}")
        last = e
        n += 1
    out.append(formula[last:])
    return "".join(out), n


def template_present(formula, name):
    """True iff {{name}} occurs in `formula` outside quoted strings — i.e.
    this substitution was already applied to the cell by a previous run."""
    tmpl = "{{" + name + "}}"
    strings = [m.span() for m in STRING_RE.finditer(formula)]
    pos = formula.find(tmpl)
    while pos != -1:
        if not any(a <= pos < b for a, b in strings):
            return True
        pos = formula.find(tmpl, pos + 1)
    return False


def load_norm(content):
    """Normalize raw TSV cell content the way formula_ast.load_formulas does
    (literal backslash-n -> space, strip) so it is parseable."""
    return content.replace("\\n", " ").strip()


def token_stream(formula):
    """(kind, value) token list; number tokens compared by float value."""
    text = formula[1:] if formula.startswith("=") else formula
    return [(k, float(v) if k == "number" else v)
            for k, v in formula_ast.tokenize(text)]


def verify_cell(sheet, cell, original, new, name_value):
    """True iff resolving every {{name}} in `new` back to its value yields a
    formula that parses and whose token stream is identical to the original
    formula's (numbers by float value)."""
    orig = load_norm(original)

    def resolve(m):
        name = m.group(1)
        if name not in name_value:
            raise KeyError(name)
        return repr(name_value[name])

    try:
        # resolve BOTH sides: `original` may itself contain {{...}} templates
        # applied by a previous run (partial re-templating); on a fresh run
        # resolving orig is a no-op.
        resolved_orig = TEMPLATE_RE.sub(resolve, orig)
        resolved = TEMPLATE_RE.sub(resolve, load_norm(new))
        formula_ast.parse(resolved, sheet=sheet)   # grammar-level check
        return token_stream(resolved_orig) == token_stream(resolved)
    except (KeyError, SyntaxError):
        return False


def formula_counts():
    """Per-file formula counts via formula_ast.load_formulas (structure check)."""
    counts = {}
    for fname in sorted(os.listdir(FORMULA_DIR)):
        if fname.endswith(".tsv"):
            path = os.path.join(FORMULA_DIR, fname)
            counts[fname] = len(formula_ast.load_formulas(path))
    return counts


def main():
    with open(PROPOSAL_PATH, encoding="utf-8") as f:
        proposal = json.load(f)
    draft = proposal["gameJsonDraft"]
    subs = proposal["substitutions"]

    # value -> all documented names for it (draft entry name + candidates)
    value_names = {}
    for entry in draft:
        v = float(entry["value"])
        names = [entry["name"]] + [c["name"] for c in entry.get("candidates", [])]
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)
        value_names[v] = uniq
    name_value = {names[0]: v for v, names in value_names.items()
                  if len(names) == 1}

    # ---- 1. keep only substitutions whose value maps to exactly ONE name ----
    kept, skipped_ambiguous = [], 0
    flag_disagreements, anomalies = [], []
    for rec in subs:
        v = float(rec["literal"])
        names = value_names.get(v)
        if names is None:
            anomalies.append(f"{rec['sheet']}!{rec['cell']}: literal {v} "
                             f"not present in gameJsonDraft")
            continue
        if len(names) > 1:
            skipped_ambiguous += 1
            if not rec.get("ambiguous"):
                flag_disagreements.append(
                    f"{rec['sheet']}!{rec['cell']}: value {v} has multiple "
                    f"names but record is not flagged ambiguous")
            continue
        if rec.get("ambiguous"):
            flag_disagreements.append(
                f"{rec['sheet']}!{rec['cell']}: record flagged ambiguous but "
                f"value {v} maps to one name")
        if rec["name"] != names[0]:
            anomalies.append(f"{rec['sheet']}!{rec['cell']}: record name "
                             f"{rec['name']} != single candidate {names[0]}")
            continue
        kept.append(rec)

    by_sheet = defaultdict(lambda: defaultdict(list))  # sheet -> cell -> [(literal, name)]
    for rec in kept:
        by_sheet[rec["sheet"]][rec["cell"]].append(
            (float(rec["literal"]), rec["name"]))

    # ---- 2. apply substitutions cell-by-cell (in memory until the gate passes)
    pre_counts = formula_counts()
    applied_records = 0
    tokens_replaced = 0
    cells_modified = 0
    already_applied = 0
    per_sheet_applied = Counter()
    applied_by_value = Counter()
    zero_token = []      # (sheet, cell, literal, name, reason)
    verify_fail = []
    pending = []         # (path, text) written only after verification passes

    for sheet in sorted(by_sheet):
        stem = formula_ast.STAT_SHEETS.get(sheet, sheet)
        path = os.path.join(FORMULA_DIR, stem + ".tsv")
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        line_of = {}
        for i, ln in enumerate(lines):
            m = LINE_RE.match(ln)
            if m:
                line_of[m.group(1)] = i          # last wins, as load_formulas
        changed = False
        for cell in sorted(by_sheet[sheet], key=cell_key):
            i = line_of.get(cell)
            if i is None:
                zero_token.append((sheet, cell, None, None,
                                   "cell not found in tsv"))
                continue
            head, _, content = lines[i].partition("\t")
            if not content.startswith("="):
                zero_token.append((sheet, cell, None, None,
                                   "cell content is not a formula"))
                continue
            new = content
            cell_applied, cell_tokens, cell_values = 0, 0, []
            for literal, name in by_sheet[sheet][cell]:
                if template_present(content, name):
                    # already applied by a previous run — counts as applied
                    # (occurrences), formula left untouched
                    already_applied += 1
                    cell_applied += 1
                    cell_values.append(literal)
                    continue
                new, n = replace_literal(new, literal, name)
                if n:
                    cell_applied += 1
                    cell_tokens += n
                    cell_values.append(literal)
                else:
                    zero_token.append((sheet, cell, literal, name,
                                       "0 tokens matched"))
            if not cell_applied:
                continue
            if new != content:
                if not verify_cell(sheet, cell, content, new, name_value):
                    verify_fail.append((sheet, cell))
                    continue
                lines[i] = head + "\t" + new
                changed = True
                cells_modified += 1
            applied_records += cell_applied
            tokens_replaced += cell_tokens
            per_sheet_applied[sheet] += cell_applied
            for literal in cell_values:
                applied_by_value[literal] += 1
        if changed:
            pending.append((path, "\n".join(lines)))

    if verify_fail:
        print("VERIFICATION FAILED — no files written:", file=sys.stderr)
        for sheet, cell in verify_fail[:20]:
            print(f"  {sheet}!{cell}", file=sys.stderr)
        return 1

    for path, text in pending:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    post_counts = formula_counts()
    if post_counts != pre_counts:
        print("STRUCTURE CHECK FAILED — formula counts changed:",
              file=sys.stderr)
        for fname in sorted(pre_counts):
            if post_counts.get(fname) != pre_counts[fname]:
                print(f"  {fname}: {pre_counts[fname]} -> "
                      f"{post_counts.get(fname)}", file=sys.stderr)
        return 1

    # ---- 3. game.json from the applied unambiguous entries only ----
    constants, occ_mismatch = [], []
    for entry in draft:
        v = float(entry["value"])
        names = value_names[v]
        if len(names) != 1:
            continue
        n = applied_by_value.get(v, 0)
        if not n:
            continue
        if n != entry["occurrences"]:
            occ_mismatch.append(f"{names[0]}: draft occurrences "
                                f"{entry['occurrences']} != applied {n}")
        constants.append({"name": names[0], "value": v,
                          "meaning": entry["meaning"], "occurrences": n})
    constants.sort(key=lambda c: c["name"])
    # MERGE into the existing game.json: replace only the "constants" key,
    # preserve every other key (e.g. cellLiterals from
    # tools/extract_literals.py) so re-running never drops them.
    try:
        with open(GAME_JSON_PATH, encoding="utf-8") as f:
            game = json.load(f)
        if not isinstance(game, dict):
            raise ValueError("top level is not a JSON object")
    except FileNotFoundError:
        game = {}                      # first run — no file to merge into
    except ValueError as e:
        print(f"error: cannot load {GAME_JSON_PATH}: {e} — not overwritten",
              file=sys.stderr)
        return 1
    old_other = {k: v for k, v in game.items() if k != "constants"}
    game["constants"] = constants
    text = json.dumps(game, indent=2) + "\n"
    if {k: v for k, v in json.loads(text).items() if k != "constants"} \
            != old_other:
        print("error: merge would change other game.json keys — "
              "not written", file=sys.stderr)
        return 1
    with open(GAME_JSON_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    # ---------------- report ----------------
    amb_values = sorted(v for v, ns in value_names.items() if len(ns) > 1)
    print(f"proposal: {len(subs)} substitution records — "
          f"{len(kept)} kept (unambiguous value), {skipped_ambiguous} "
          f"skipped (ambiguous value)")
    print(f"ambiguous values left untouched ({len(amb_values)}): "
          + ", ".join(f"{v:g}" for v in amb_values))
    print(f"applied substitutions: {applied_records} records "
          f"({tokens_replaced} number tokens replaced, {cells_modified} "
          f"cells modified, {len(pending)} files rewritten)")
    if already_applied:
        print(f"already templated by a previous run: {already_applied} "
              f"records (counted as applied, formulas untouched)")
    print("per-sheet applied substitution counts:")
    for sheet in sorted(per_sheet_applied):
        print(f"  {sheet}: {per_sheet_applied[sheet]}")
    if zero_token:
        print(f"substitutions matching 0 tokens: {len(zero_token)} "
              f"(expected none):")
        for sheet, cell, lit, name, why in zero_token[:20]:
            print(f"  {sheet}!{cell} literal={lit} name={name}: {why}")
    else:
        print("substitutions matching 0 tokens: none")
    for label, items in (("ambiguous-flag disagreements", flag_disagreements),
                         ("structural anomalies", anomalies),
                         ("occurrences mismatches vs draft", occ_mismatch)):
        if items:
            print(f"{label} ({len(items)}):")
            for item in items[:20]:
                print(f"  {item}")
    print(f"verification: {cells_modified} modified formulas re-parsed with "
          f"templates resolved to values — all token-identical to originals; "
          f"formula counts unchanged ({sum(pre_counts.values())} formulas)")
    print(f"wrote {os.path.relpath(GAME_JSON_PATH, ROOT)}: {len(constants)} "
          f"constants (applied unambiguous entries only, sorted by name; "
          f"{len(old_other)} other key(s) preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
