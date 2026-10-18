#!/usr/bin/env python3
"""Build the semantic name->cell index into data/wow-12.1/game.json.

Adds an "index" section to game.json (constants and cellLiterals are
preserved verbatim; only the "index" key is added/replaced):

    "index": {
      "abilities": [ { "name", "row", "cells": { <col>: "<Sheet>!<col><row>" } } ],
      "talents":   [ { "tree", "name", "row", "cells": { ... } } ]
    }

Abilities  — Baseline sheet (canonical), rows 19-76. The label column is
detected among B..G as the column holding the most string literals in the
range; every numeric literal cell on a labelled row is a coefficient cell
of that ability.

Talents   — Inputs sheet. "Death Knight" tree rows 40-85 and "Blood" tree
rows 88-129: label = column B, rank cell = C, variable cell = D (a cell is
only emitted when its literal exists and is numeric). Hero rows 136-143
hold two sub-trees side by side: Deathbringer (label B, rank C) and
San'layn (label D, rank E) — column D there is the San'layn label column,
so hero entries carry no variable cell.

Run: .venv/bin/python tools/build_index.py
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_JSON_PATH = os.path.join(ROOT, "data", "wow-12.1", "game.json")

BASELINE = "Baseline"
INPUTS = "Inputs"

ABILITY_FIRST_ROW, ABILITY_LAST_ROW = 19, 76
LABEL_COL_CANDIDATES = "BCDEFG"  # label column is detected among these

# Inputs-sheet talent sections: (tree name, first row, last row).
TALENT_SECTIONS = [
    ("Death Knight", 40, 85),
    ("Blood", 88, 129),
]
HERO_FIRST_ROW, HERO_LAST_ROW = 136, 143
# Hero rows hold two sub-trees side by side: (tree, label col, rank col).
HERO_SUBTREES = [
    ("Deathbringer", "B", "C"),
    ("San'layn", "D", "E"),
]
RANK_COL = "C"      # rank cell column (Death Knight / Blood trees)
VARIABLE_COL = "D"  # variable cell column (Death Knight / Blood trees)

CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def is_str(value):
    return isinstance(value, str)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def col_sort_key(col):
    """Spreadsheet column order: A, B, ..., Z, AA, AB, ..."""
    return (len(col), col)


def cells_by_row(sheet_literals):
    """Map row number -> {col: literal} for one sheet's cellLiterals."""
    rows = {}
    for ref, value in sheet_literals.items():
        match = CELL_RE.match(ref)
        if match:
            rows.setdefault(int(match.group(2)), {})[match.group(1)] = value
    return rows


def detect_label_column(baseline_rows):
    """The candidate column holding the most string literals across the
    ability rows is the abilities label column."""
    counts = {
        col: sum(
            1
            for row in range(ABILITY_FIRST_ROW, ABILITY_LAST_ROW + 1)
            if is_str(baseline_rows.get(row, {}).get(col))
        )
        for col in LABEL_COL_CANDIDATES
    }
    label_col = max(LABEL_COL_CANDIDATES, key=lambda col: counts[col])
    return label_col, counts


def build_abilities(cell_literals):
    """Ability entries from the Baseline sheet, rows 19-76."""
    baseline_rows = cells_by_row(cell_literals[BASELINE])
    label_col, counts = detect_label_column(baseline_rows)

    abilities = []
    no_coefficients = []
    for row in range(ABILITY_FIRST_ROW, ABILITY_LAST_ROW + 1):
        label = baseline_rows.get(row, {}).get(label_col)
        if not is_str(label):
            continue
        cells = {
            col: "%s!%s%d" % (BASELINE, col, row)
            for col, value in baseline_rows.get(row, {}).items()
            if is_num(value)
        }
        cells = dict(sorted(cells.items(), key=lambda item: col_sort_key(item[0])))
        if not cells:
            no_coefficients.append("%s (row %d)" % (label, row))
        abilities.append({"name": label, "row": row, "cells": cells})

    duplicates = sorted(
        {a["name"] for a in abilities if [x["name"] for x in abilities].count(a["name"]) > 1}
    )
    anomalies = []
    if no_coefficients:
        anomalies.append(
            "%d abilities with no coefficient cells: %s"
            % (len(no_coefficients), ", ".join(no_coefficients))
        )
    if duplicates:
        anomalies.append("duplicate ability names: %s" % ", ".join(duplicates))
    coverage = counts[label_col]
    total_rows = ABILITY_LAST_ROW - ABILITY_FIRST_ROW + 1
    if coverage != total_rows:
        anomalies.append(
            "label column %s covers %d/%d rows" % (label_col, coverage, total_rows)
        )
    return abilities, label_col, counts, anomalies


def build_talents(cell_literals):
    """Talent entries from the Inputs sheet."""
    inputs_rows = cells_by_row(cell_literals[INPUTS])
    talents = []
    anomalies = []

    def add(tree, name, row, cells):
        talents.append(
            {"tree": tree, "name": name, "row": row, "cells": dict(sorted(cells.items(), key=lambda item: col_sort_key(item[0])))}
        )

    for tree, first_row, last_row in TALENT_SECTIONS:
        for row in range(first_row, last_row + 1):
            row_cells = inputs_rows.get(row, {})
            label = row_cells.get("B")
            if not is_str(label):
                anomalies.append("%s tree row %d has no label in column B" % (tree, row))
                continue
            cells = {}
            if is_num(row_cells.get(RANK_COL)):
                cells[RANK_COL] = "%s!%s%d" % (INPUTS, RANK_COL, row)
            if is_num(row_cells.get(VARIABLE_COL)):
                cells[VARIABLE_COL] = "%s!%s%d" % (INPUTS, VARIABLE_COL, row)
            add(tree, label, row, cells)

    for row in range(HERO_FIRST_ROW, HERO_LAST_ROW + 1):
        row_cells = inputs_rows.get(row, {})
        for tree, label_col, rank_col in HERO_SUBTREES:
            label = row_cells.get(label_col)
            if not is_str(label):
                anomalies.append("hero row %d has no %s label in column %s" % (row, tree, label_col))
                continue
            cells = {}
            if is_num(row_cells.get(rank_col)):
                cells[rank_col] = "%s!%s%d" % (INPUTS, rank_col, row)
            add(tree, label, row, cells)

    duplicates = sorted(
        {
            t["name"]
            for t in talents
            if [x["name"] for x in talents].count(t["name"]) > 1
        }
    )
    if duplicates:
        anomalies.append("duplicate talent names: %s" % ", ".join(duplicates))
    return talents, anomalies


def main():
    with open(GAME_JSON_PATH, "r", encoding="utf-8") as handle:
        original = handle.read()
    game = json.loads(original)

    abilities, label_col, label_counts, ability_anomalies = build_abilities(
        game["cellLiterals"]
    )
    talents, talent_anomalies = build_talents(game["cellLiterals"])

    game["index"] = {"abilities": abilities, "talents": talents}

    trailing_newline = original.endswith("\n")
    rewritten = json.dumps(game, indent=2) + ("\n" if trailing_newline else "")

    # Verify constants + cellLiterals are preserved byte-for-byte: the file
    # without the new "index" key must round-trip to the original content.
    without_index = {key: value for key, value in game.items() if key != "index"}
    round_trip = json.dumps(without_index, indent=2) + ("\n" if trailing_newline else "")
    preserved = round_trip == original

    with open(GAME_JSON_PATH, "w", encoding="utf-8") as handle:
        handle.write(rewritten)

    print("abilities: %d   talents: %d" % (len(abilities), len(talents)))
    print(
        "ability label column: %s (%d/%d rows; candidates: %s)"
        % (
            label_col,
            label_counts[label_col],
            ABILITY_LAST_ROW - ABILITY_FIRST_ROW + 1,
            ", ".join(
                "%s=%d" % (col, label_counts[col])
                for col in LABEL_COL_CANDIDATES
                if label_counts[col]
            ),
        )
    )
    print("constants + cellLiterals preserved byte-for-byte: %s" % preserved)

    by_tree = {}
    for talent in talents:
        by_tree[talent["tree"]] = by_tree.get(talent["tree"], 0) + 1
    print("talents per tree: %s" % ", ".join("%s=%d" % kv for kv in by_tree.items()))

    samples = []
    if abilities:
        samples.append(("ability", abilities[0]))
        most_cells = max(abilities, key=lambda a: len(a["cells"]))
        samples.append(("ability", most_cells))
    if talents:
        samples.append(("talent", talents[0]))
        with_variable = next(
            (t for t in talents if VARIABLE_COL in t["cells"]), None
        )
        if with_variable:
            samples.append(("talent", with_variable))
        samples.append(("talent", talents[-1]))
    for kind, entry in samples[:5]:
        print(
            "sample %-7s %s"
            % (
                kind,
                json.dumps(entry, ensure_ascii=False, sort_keys=False),
            )
        )

    anomalies = ability_anomalies + talent_anomalies
    if anomalies:
        print("anomalies:")
        for note in anomalies:
            print("  - %s" % note)
    else:
        print("anomalies: none")

    if not preserved:
        print("ERROR: round-trip check failed; file rewritten anyway", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
