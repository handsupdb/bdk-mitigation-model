#!/usr/bin/env python3
"""Engine config codegen, Part 1: parse inputs, encode section map, print summary.

TypeScript emission comes in later micro-stages. Stdlib only.

Sources
  extracted/Inputs__values.tsv       cell_ref TAB content   (non-empty cells)
  tests/fixtures/golden/Inputs.json  {cell_ref: value} map  + "uncached" array

Note: extracted/*__values.tsv is gitignored; regenerate it first via
  .venv/bin/python extract_xlsx.py excel_mitigation_model.xlsx

Conventions
  blank cell  == ref absent from the fixture value map (a cached 0 is present)
  covered ref == row inside a section range AND column is a role column of
                 that section, or a comparison column (H/I/J)
"""
import json
import re
import sys

TSV_PATH = "extracted/Inputs__values.tsv"
FIXTURE_PATH = "tests/fixtures/golden/Inputs.json"

# name -> (first_row, last_row, {role: column}); C86/C130 are point totals
SECTIONS = [
    ("Character Attributes", 6, 17, {"label": "B", "value": "C"}),
    ("Runeforging", 19, 23, {"label": "B", "value": "C"}),
    ("Races", 25, 37, {"label": "B", "value": "C",
                       "race_label": "D", "race_value": "E"}),
    ("DK class talents", 39, 86, {"label": "B", "value": "C"}),
    ("Blood talents", 87, 130, {"label": "B", "value": "C"}),
    ("Hero Class", 131, 133, {"label": "B", "value": "C"}),
    ("Hero talents", 135, 143, {"label": "B", "value": "C"}),
    ("Conditional Variables", 145, 156, {"label": "B", "value": "C",
                                         "talent_var": "D"}),
    ("Tier Set", 158, 160, {"label": "B", "value": "C"}),
]
COMPARISON_COLS = ("H", "I", "J")  # H abs overrides, I differentials, J toggles
LABEL_VALUE_PAIRS = (("label", "value"), ("race_label", "race_value"))
REF_RE = re.compile(r"([A-Z]+)(\d+)$")


def col_row(ref):
    m = REF_RE.match(ref)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def load_tsv(path):
    cells = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line:
                ref, _, content = line.partition("\t")
                cells[ref] = content
    return cells


def main():
    tsv = load_tsv(TSV_PATH)
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        fixture = json.load(fh)
    uncached = list(fixture.get("uncached", []))
    fix = {k: v for k, v in fixture.items() if k != "uncached"}

    def blank(ref):
        return ref not in fix  # blank == absent; cached 0 is present

    row_sec = {r: i for i, (_, lo, hi, _) in enumerate(SECTIONS)
               for r in range(lo, hi + 1)}

    print(f"tsv refs={len(tsv)} fixture cells={len(fix)} uncached={len(uncached)}"
          f" J-cells={sum(1 for k in fix if col_row(k)[0] == 'J')}")
    for tag, refs in (("tsv-only", set(tsv) - set(fix) - set(uncached)),
                      ("fixture-only", set(fix) - set(tsv))):
        if refs:
            print(f"  MISMATCH {tag}: {sorted(refs)}")

    outside = {}
    for ref in fix:
        col, row = col_row(ref)
        sec = row_sec.get(row)
        if sec is None or (col not in SECTIONS[sec][3].values()
                           and col not in COMPARISON_COLS):
            outside.setdefault(col, []).append(row)

    for name, lo, hi, roles in SECTIONS:
        n = hi - lo + 1
        cnt = {role: sum(1 for r in range(lo, hi + 1)
                         if not blank(c + str(r)))
               for role, c in roles.items()}
        bh = sum(1 for r in range(lo, hi + 1) if blank("H" + str(r)))
        bi = sum(1 for r in range(lo, hi + 1) if blank("I" + str(r)))
        anom = [f"{roles[l]}{r} w/o {roles[v]}{r}"
                for l, v in LABEL_VALUE_PAIRS if l in roles
                for r in range(lo, hi + 1)
                if not blank(roles[l] + str(r)) and blank(roles[v] + str(r))]
        extra = "".join(f" {role}={cnt[role]}" for role in roles
                        if role not in ("label", "value"))
        print(f"{name:<21} r{lo:>3}-{hi:<3} labels={cnt['label']}/{n}"
              f" values={cnt['value']}/{n}{extra} blankH={bh}/{n} blankI={bi}/{n}"
              + (f" ANOM={anom}" if anom else ""))

    if outside:
        parts = [f"{c}:{len(rs)}({','.join(map(str, sorted(rs)))})"
                 if len(rs) <= 8 else f"{c}:{len(rs)}(rows {min(rs)}-{max(rs)})"
                 for c, rs in sorted(outside.items())]
        print("refs outside section map:", " ".join(parts))
    else:
        print("refs outside section map: none")
    if uncached:
        print("uncached:", " ".join(uncached))
    return 0


if __name__ == "__main__":
    sys.exit(main())
