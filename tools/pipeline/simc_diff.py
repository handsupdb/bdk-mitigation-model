#!/usr/bin/env python
"""SimC proposed-diff report generator (hand-review only — never auto-applies).

Compares our workbook's ability coefficients against SimC midnight spell data
(wow build 12.1.5.70448, ``extracted/simc_sc_spell_data.inc``) using the curated
mapping ``tools/pipeline/simc_mapping.json``, writes a hand-review report to
``extracted/simc_proposed_diffs.md`` and prints it compactly. Nothing here
edits ``game.json`` or any sheet — every CHANGED line is a *proposal* for a
human to verify.

Mapping entry schema (one per ability):
    ability      our workbook ability name (Baseline label column G);
    simcSpell    spell name for simc_data.lookup;
    effectIndex  1-based effectN index (SimC convention; file _index = N - 1);
    field        parsed field to compare (ap_coeff / sp_coeff / base_value / …);
    ourCell      our cell holding the coefficient, e.g. "Baseline!H25"; null
                 when no cell in the ability's row matched (unmapped);
    ourConstant  alternative to ourCell: a game.json constants name (e.g.
                 "vbHealingAmpBase") when the value lives in a constant,
                 not a cell — resolved from game.json constants and diffed
                 like a cell value;
    transform    optional per-entry transform applied to the EXTERNAL value
                 (SimC field / hotfix column) to convert it into our
                 representation so the comparison is apples-to-apples;
                 "percentToMultiplier": external bonus percent (30 = +30%)
                 -> our multiplier (1 + 30/100 = 1.3); our value is never
                 transformed;
    spellId      optional: pin the exact spell when the name is ambiguous —
                 lookup() resolves names to the FIRST id (e.g. "Consumption"
                 -> 205223, which has no ap_coeff; the damage spell SimC's
                 class module uses is 1263825);
    note         optional curation note, surfaced in the report.

Our value sources for a cell (first match wins):
    1. data/wow-12.1/game.json cellLiterals[<sheet>][<cell>]  (literal cells);
    2. extracted/<Sheet>__values.tsv                          (cached values);
    3. extracted/<Sheet>__formulas.tsv, evaluated when the formula is pure
       arithmetic (numbers and + - * / ^ parentheses; Excel ^ = power).
When the entry carries ourConstant instead of ourCell, the value comes from
game.json constants[<name>].value (no cell/TSV lookup is involved).
IMPORTANT: the ability coefficient cells are Baseline column H ("Attack Power
Multiplier") FORMULA cells (e.g. H25 = 1.4256*1.15) — they are NOT present in
cellLiterals, so the values/formulas TSVs are required to read them.

Verdicts per entry:
    match     both values present and |our - simc| <= max(0.0005, 0.1%*|simc|);
    CHANGED   both present but beyond tolerance — a proposed diff to review;
    unmapped  no ourCell/ourConstant, our value unresolvable, or the
              spell/effect/field is absent from the SimC 12.1.5 data.

Curation rule for ourCell (used to build the initial mapping; re-runnable via
--discover): compare the SimC 12.1.5 value against every cell in that
ability's Baseline row (literals + cached values + evaluated formulas); the
cell whose value matches is the coefficient cell; if none matches, mark
unmapped.

NOTE: extracted/simc_research.md documents 11.2.7 (thewarwithin) values (Blood
Boil 0.647496, Heart Strike 0.570050, Soul Reaper 0.448800). The midnight
12.1.5 values are ~3x those (Blood Boil 1.64, Heart Strike 1.967, Soul Reaper
4.5) and our 12.1 workbook matches the midnight values — always compare
against simc_data.lookup(), never against the research doc's numbers.

CLI:
    .venv/bin/python tools/pipeline/simc_diff.py
    .venv/bin/python tools/pipeline/simc_diff.py --discover "Blood Boil" \
        --effect 1 --field ap_coeff
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import date
from typing import Dict, List, Optional, Tuple

try:  # package-style import (tools.pipeline) or direct script run
    from . import simc_data  # type: ignore
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import simc_data  # type: ignore

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING_PATH = os.path.join(REPO_ROOT, "tools", "pipeline", "simc_mapping.json")
GAME_PATH = os.path.join(REPO_ROOT, "data", "wow-12.1", "game.json")
EXTRACTED_DIR = os.path.join(REPO_ROOT, "extracted")
REPORT_PATH = os.path.join(EXTRACTED_DIR, "simc_proposed_diffs.md")

ABS_TOL = 0.0005
REL_TOL = 0.001  # 0.1%

_CELL_RE = re.compile(r"^([A-Z]{1,3})(\d+)$")
_CELL_REF_RE = re.compile(r"^(?:([^!]+)!)?([A-Z]{1,3}\d+)$")
_ARITH_RE = re.compile(r"^[=+\-*/^().\d\s]+$")
_NO_VALUE = "<NO_CACHED_VALUE>"

_TSV_CACHE: Dict[Tuple[str, str], Dict[str, str]] = {}


# -- workbook access ----------------------------------------------------------


def load_game(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _tsv_path(sheet: str, kind: str) -> str:
    # "+Critical Strike" -> "_Critical_Strike__values.tsv"
    name = sheet.replace("+", "_").replace(" ", "_")
    return os.path.join(EXTRACTED_DIR, f"{name}__{kind}.tsv")


def load_tsv(sheet: str, kind: str) -> Dict[str, str]:
    key = (sheet, kind)
    if key not in _TSV_CACHE:
        path = _tsv_path(sheet, kind)
        cells: Dict[str, str] = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    cell, sep, value = line.rstrip("\n").partition("\t")
                    cell = cell.strip()
                    if sep and _CELL_RE.match(cell):
                        cells[cell] = value
        _TSV_CACHE[key] = cells
    return _TSV_CACHE[key]


def parse_cell_ref(ref: str) -> Tuple[str, str]:
    m = _CELL_REF_RE.match(ref.strip())
    if not m:
        raise ValueError(f"bad cell ref {ref!r} (expected e.g. 'Baseline!H25')")
    return m.group(1) or "Baseline", m.group(2)


def eval_arithmetic(formula: str) -> Optional[float]:
    """Evaluate a pure-arithmetic spreadsheet formula; None otherwise."""
    s = formula.strip()
    if s.startswith("=") or s.startswith("+"):
        s = s[1:]
    if not s or not _ARITH_RE.match(s):
        return None
    try:
        tree = ast.parse(s.replace("^", "**"), mode="eval")
        return _eval_node(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_node(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Pow):
            return a ** b
    raise ValueError(f"non-arithmetic node {type(node).__name__}")


def resolve_our_value(game: dict, ref: str) -> dict:
    """Resolve one of our cells to a value (see module docstring for order)."""
    sheet, cell = parse_cell_ref(ref)
    formula = load_tsv(sheet, "formulas").get(cell)
    literal = game["cellLiterals"].get(sheet, {}).get(cell)
    if isinstance(literal, (int, float)) and not isinstance(literal, bool):
        return {"value": float(literal), "source": "literal (cellLiterals)",
                "formula": formula, "sheet": sheet, "cell": cell}
    raw = load_tsv(sheet, "values").get(cell)
    if raw is not None and raw.strip() not in ("", _NO_VALUE):
        try:
            return {"value": float(raw), "source": "cached value "
                    f"({os.path.basename(_tsv_path(sheet, 'values'))})",
                    "formula": formula, "sheet": sheet, "cell": cell}
        except ValueError:
            pass
    if formula:
        v = eval_arithmetic(formula)
        if v is not None:
            return {"value": v, "source": "evaluated formula", "formula": formula,
                    "sheet": sheet, "cell": cell}
    return {"value": None, "source": "unresolvable (no literal, cached value "
            "or arithmetic formula)", "formula": formula, "sheet": sheet,
            "cell": cell}


def resolve_our_constant(game: dict, name: str) -> dict:
    """Resolve one of our game.json constants (mapping ourConstant).

    game.json constants is a list of {name, value, meaning, occurrences}
    (the {{name}} placeholders in the formula TSVs); the value is diffed
    like a cell value. Same result shape as resolve_our_value.
    """
    for const in game.get("constants", []):
        if isinstance(const, dict) and const.get("name") == name:
            value = const.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                source = f"constant {name} (game.json constants)"
                if const.get("meaning"):
                    source += f" — {const['meaning']}"
                return {"value": float(value), "source": source,
                        "formula": None, "sheet": None, "cell": None}
            return {"value": None, "source": f"constant {name!r} has a "
                    f"non-numeric value {value!r}", "formula": None,
                    "sheet": None, "cell": None}
    return {"value": None, "source": f"constant {name!r} not found in "
            "game.json constants", "formula": None, "sheet": None,
            "cell": None}


# -- SimC access --------------------------------------------------------------


def resolve_simc_value(entry: dict) -> dict:
    """Resolve the SimC 12.1.5 value for a mapping entry (spellId wins)."""
    spell = entry.get("simcSpell") or entry.get("ability") or ""
    field = entry.get("field") or "ap_coeff"
    try:
        idx = int(entry["effectIndex"])
    except (KeyError, TypeError, ValueError):
        return {"value": None, "display": None,
                "error": "mapping entry has no usable effectIndex"}
    spell_id = entry.get("spellId")
    if spell_id is not None:
        data = simc_data.load()
        row = data.effects.get((int(spell_id), idx - 1))
        if row is None or field not in row:
            return {"value": None, "display": None,
                    "error": f"SimC 12.1.5 has no spell id {spell_id} "
                    f"effect {idx} field {field!r}"}
        name = next((n for n, ids in data.spell_aliases.items()
                     if int(spell_id) in ids), f"spell {spell_id}")
        return {"value": float(row[field]),
                "display": f"{name} #{spell_id} effectN({idx}) {field}",
                "error": None}
    try:
        row = simc_data.lookup(spell, idx)
    except (KeyError, ValueError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        return {"value": None, "display": None,
                "error": f"SimC 12.1.5 lookup failed: {msg}"}
    if field not in row:
        return {"value": None, "display": None,
                "error": f"SimC row for {spell!r} has no field {field!r}"}
    return {"value": float(row[field]),
            "display": f"{row['spell_name']} #{row['spell_id']} "
            f"effectN({idx}) {field}", "error": None}


# -- per-entry transforms ------------------------------------------------------

# Mapping key "transform": converts the EXTERNAL value (SimC field / hotfix
# column) into OUR representation so the comparison is apples-to-apples.
# Our value (cell or constant) is never transformed.
ENTRY_TRANSFORMS = {
    # SimC base_value stores a bonus PERCENT (30 = +30%); our game.json
    # constant is the corresponding MULTIPLIER (1.3 = 1 + 30/100) — e.g.
    # vbHealingAmpBase, used in Baseline formulas as a plain multiplier:
    # ({{vbHealingAmpBase}}+0.05*C92).
    "percentToMultiplier": lambda v: 1.0 + v / 100.0,
}


def apply_transform(entry: dict, ext: dict) -> dict:
    """Apply the entry's transform to an external (SimC/hotfix) value dict.

    Returns ext extended with: value = the transformed value in OUR
    representation (what our cell/constant is compared against), raw_value
    = the untransformed external value, transform = the transform name
    (None when the entry has none). An unknown transform name is a mapping
    error (value None + error); an unresolvable external value keeps its
    resolve error untouched.
    """
    name = entry.get("transform")
    out = dict(ext)
    out["raw_value"] = ext.get("value")
    out["transform"] = name or None
    if not name:
        return out
    fn = ENTRY_TRANSFORMS.get(name)
    if fn is None:
        out["value"] = None
        out["error"] = f"unknown mapping transform {name!r} (known: " \
                       f"{', '.join(sorted(ENTRY_TRANSFORMS))})"
        return out
    if ext.get("value") is None:
        return out  # nothing to transform; keep the resolve error
    out["value"] = fn(float(ext["value"]))
    return out


# -- comparison ---------------------------------------------------------------


def classify(our: Optional[float], simc: Optional[float]) -> Tuple[str, Optional[float]]:
    if our is None or simc is None:
        return "unmapped", None
    delta = our - simc
    tol = max(ABS_TOL, REL_TOL * abs(simc))
    return ("match" if abs(delta) <= tol else "CHANGED"), delta


def our_target(row: dict) -> str:
    """Display label for our value target: cell ref, constant, or em-dash."""
    if row.get("our_cell"):
        return row["our_cell"]
    if row.get("our_constant"):
        return f"constant {row['our_constant']}"
    return "—"


def fmt_ext(ext: dict, with_error: bool = True) -> str:
    """Format an external (SimC/hotfix) value dict, transform-aware.

    Shows the raw → transformed pair when a per-entry transform applied
    (e.g. "30 → 1.3 (percentToMultiplier)"). with_error=False keeps the
    compact prints' old shape (bare em-dash; the error is printed
    separately there).
    """
    if ext.get("value") is None:
        if with_error and ext.get("error"):
            return f"— ({ext['error']})"
        return "—"
    if ext.get("transform") and ext.get("raw_value") is not None:
        return (f"{fmt(ext['raw_value'])} → {fmt(ext['value'])} "
                f"({ext['transform']})")
    return fmt(ext["value"])


def evaluate_entry(entry: dict, game: dict) -> dict:
    ability = entry.get("ability", "?")
    our_cell = entry.get("ourCell")
    our_constant = entry.get("ourConstant")
    if our_cell:
        our = resolve_our_value(game, our_cell)
    elif our_constant:
        our = resolve_our_constant(game, our_constant)
    else:
        our = {"value": None, "source": "no ourCell/ourConstant (unmapped)",
               "formula": None, "sheet": None, "cell": None}
    simc = apply_transform(entry, resolve_simc_value(entry))
    verdict, delta = classify(our["value"], simc["value"])
    return {"ability": ability, "our_cell": our_cell,
            "our_constant": our_constant, "our": our, "simc": simc,
            "verdict": verdict, "delta": delta, "note": entry.get("note")}


def fmt(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.6g}"


def fmt_delta(d: Optional[float]) -> str:
    return "—" if d is None else f"{d:+.6g}"


# -- report -------------------------------------------------------------------


def build_report(rows: List[dict], mapping_path: str, report_path: str) -> str:
    build = simc_data.stats().get("build")
    n_match = sum(1 for r in rows if r["verdict"] == "match")
    n_changed = sum(1 for r in rows if r["verdict"] == "CHANGED")
    n_unmapped = sum(1 for r in rows if r["verdict"] == "unmapped")

    lines: List[str] = []
    lines.append("# SimC proposed diffs — hand-review report")
    lines.append("")
    lines.append(f"- Generated {date.today().isoformat()} by "
                 f"`tools/pipeline/simc_diff.py` from "
                 f"`{os.path.relpath(mapping_path, REPO_ROOT)}`")
    lines.append(f"- SimC data: branch `midnight`, wow build {build} "
                 "(`extracted/simc_sc_spell_data.inc`)")
    lines.append("- Our workbook: `data/wow-12.1/game.json` (cellLiterals) + "
                 "`extracted/<Sheet>__values.tsv` / `__formulas.tsv`")
    lines.append(f"- Match tolerance: |our − simc| ≤ max({ABS_TOL}, "
                 f"{REL_TOL:.1%} × |simc|)")
    lines.append("")
    lines.append("> **PROPOSALS ONLY — never auto-apply.** This report exists "
                 "for hand review; no tool writes these values back into "
                 "`game.json` or any sheet. Every CHANGED line must be "
                 "verified by a human before any edit is made.")
    lines.append(">")
    lines.append("> Note: our ability coefficients are Baseline column H "
                 '("Attack Power Multiplier") *formula* cells (e.g. '
                 "`H25 = 1.4256*1.15`); they are absent from `cellLiterals`, "
                 "so cached values / formulas TSVs are used to read them.")
    lines.append("")
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| Ability | Our target | Our value | SimC value | Δ (our−simc) "
                 "| SimC source | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        our_val = fmt(r["our"]["value"])
        if r["our"]["formula"]:
            our_val += f" (`{r['our']['formula']}`)"
        simc_val = fmt_ext(r["simc"])
        lines.append(
            f"| {r['ability']} | {our_target(r)} | {our_val} "
            f"| {simc_val} | {fmt_delta(r['delta'])} "
            f"| {r['simc']['display'] or '—'} | {r['verdict']} |")
    lines.append("")

    lines.append("## CHANGED — proposed diffs (hand-verify before any edit)")
    lines.append("")
    changed = [r for r in rows if r["verdict"] == "CHANGED"]
    if changed:
        for r in changed:
            lines.append(
                f"- **{r['ability']}**: our {our_target(r)} "
                f"{fmt(r['our']['value'])} → SimC {fmt(r['simc']['value'])} "
                f"({r['simc']['display']}); Δ {fmt_delta(r['delta'])}.")
    else:
        lines.append("None — every mapped entry is within tolerance.")
    lines.append("")

    lines.append("## Unmapped entries (no proposed diff)")
    lines.append("")
    unmapped = [r for r in rows if r["verdict"] == "unmapped"]
    if unmapped:
        for r in unmapped:
            why = r["note"] or "no cell in the ability's row matched the SimC value"
            simc_txt = (f"SimC {fmt(r['simc']['value'])} ({r['simc']['display']})"
                        if r["simc"]["value"] is not None
                        else f"SimC: {r['simc']['error']}")
            lines.append(f"- **{r['ability']}** — {why}. {simc_txt}.")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- {len(rows)} mapping entries: {n_match} match, "
                 f"{n_changed} CHANGED, {n_unmapped} unmapped.")
    lines.append(f"- Deviations beyond tolerance: "
                 + (", ".join(r["ability"] for r in changed) if changed else "none") + ".")
    lines.append("")
    return "\n".join(lines)


def print_compact(rows: List[dict], report_path: str) -> None:
    for r in rows:
        our = fmt(r["our"]["value"]) if r["our"]["value"] is not None else "—"
        if r["our_cell"] or r["our_constant"]:
            our = f"{our_target(r)} our {our}"
        simc = fmt_ext(r["simc"], with_error=False)
        if r["simc"]["display"]:
            simc += f" ({r['simc']['display']})"
        extra = ""
        if r["verdict"] == "unmapped":
            bits = []
            if not r["our_cell"] and not r["our_constant"]:
                bits.append("no ourCell/ourConstant")
            elif r["our"]["value"] is None:
                bits.append(f"our {r['our']['source']}")
            if r["simc"]["value"] is None and r["simc"]["error"]:
                bits.append(str(r["simc"]["error"])[:60])
            extra = " (" + "; ".join(bits) + ")" if bits else ""
        print(f"{r['ability']:<15} | {our} | simc {simc} | {r['verdict']}{extra}")
    n_match = sum(1 for r in rows if r["verdict"] == "match")
    n_changed = sum(1 for r in rows if r["verdict"] == "CHANGED")
    n_unmapped = sum(1 for r in rows if r["verdict"] == "unmapped")
    print(f"— {len(rows)} entries: {n_match} match, {n_changed} CHANGED, "
          f"{n_unmapped} unmapped | report: "
          f"{os.path.relpath(report_path, REPO_ROOT)}")


# -- curation helper ----------------------------------------------------------


def row_cells(game: dict, sheet: str, row: int) -> List[Tuple[str, Optional[float], str]]:
    """All numeric cells in one sheet row: (cell, value, source)."""
    out: Dict[str, Tuple[Optional[float], str]] = {}
    literals = game["cellLiterals"].get(sheet, {})
    for cell, lit in literals.items():
        m = _CELL_RE.match(cell)
        if m and int(m.group(2)) == row and isinstance(lit, (int, float)) \
                and not isinstance(lit, bool):
            out[cell] = (float(lit), "literal (cellLiterals)")
    for cell, raw in load_tsv(sheet, "values").items():
        m = _CELL_RE.match(cell)
        if not (m and int(m.group(2)) == row) or cell in out:
            continue
        if raw.strip() in ("", _NO_VALUE):
            continue
        try:
            out[cell] = (float(raw), "cached value")
        except ValueError:
            pass
    for cell, formula in load_tsv(sheet, "formulas").items():
        m = _CELL_RE.match(cell)
        if not (m and int(m.group(2)) == row) or cell in out:
            continue
        v = eval_arithmetic(formula)
        if v is not None:
            out[cell] = (v, f"formula `{formula}`")
    return [(cell, v, src) for cell, (v, src) in sorted(out.items())]


def cmd_discover(args: argparse.Namespace, game: dict) -> int:
    """Re-run the ourCell curation scan for one ability (see module docstring)."""
    abilities = {a["name"]: a for a in game["index"]["abilities"]}
    simc = resolve_simc_value({"simcSpell": args.simc_spell or args.discover,
                               "effectIndex": args.effect, "field": args.field})
    if simc["value"] is None:
        print(f"SimC: {simc['error']}")
        print("cannot scan without a SimC value")
        return 1
    print(f"SimC 12.1.5: {simc['display']} = {fmt(simc['value'])}")
    if args.discover not in abilities:
        print(f"{args.discover!r}: not in our workbook index.abilities "
              f"({len(abilities)} abilities) -> mark unmapped")
        return 0
    row = abilities[args.discover]["row"]
    print(f"Scanning Baseline row {row} (literals + cached values + "
          "evaluated formulas)...")
    tol = max(ABS_TOL, REL_TOL * abs(simc["value"]))
    hits = 0
    for cell, value, source in row_cells(game, "Baseline", row):
        if value is not None and abs(value - simc["value"]) <= tol:
            print(f"  MATCH {cell} = {fmt(value)} ({source})")
            hits += 1
    if not hits:
        print("  no matching cell -> mark unmapped")
    return 0


# -- CLI ----------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the SimC proposed-diff hand-review report.")
    parser.add_argument("--mapping", default=MAPPING_PATH,
                        help="curated mapping JSON (default: %(default)s)")
    parser.add_argument("--game", default=GAME_PATH,
                        help="our game.json (default: %(default)s)")
    parser.add_argument("--report", default=REPORT_PATH,
                        help="report to write (default: %(default)s)")
    parser.add_argument("--discover", metavar="ABILITY",
                        help="curation helper: scan that ability's Baseline "
                             "row for a cell matching the SimC value")
    parser.add_argument("--simc-spell",
                        help="spell name for --discover (default: the ability)")
    parser.add_argument("--effect", type=int, default=1,
                        help="1-based effectN index for --discover "
                             "(default: %(default)s)")
    parser.add_argument("--field", default="ap_coeff",
                        help="field for --discover (default: %(default)s)")
    args = parser.parse_args(argv)

    game = load_game(args.game)
    if args.discover:
        return cmd_discover(args, game)

    with open(args.mapping, encoding="utf-8") as fh:
        mapping = json.load(fh)
    if not isinstance(mapping, list):
        print(f"error: mapping {args.mapping} is not a JSON list", file=sys.stderr)
        return 1

    rows = [evaluate_entry(entry, game) for entry in mapping]
    report = build_report(rows, args.mapping, args.report)
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(report)
    print_compact(rows, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
