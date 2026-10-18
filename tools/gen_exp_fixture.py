#!/usr/bin/env python3
"""Generate tests/fixtures/exp_cases.json — a bit-exact spec for exp().

The TS engine needs an exp that matches the oracle's arithmetic: Python's
math.exp reproduced Excel's cached workbook values exactly, while V8's
Math.exp differs by an ulp on some inputs (e.g. the +Stat V83 cells
124747/6*(1.13*(1-exp(-2*J9*6/60)))*J8*J10: Excel/Python 9639.658385038161
vs the V8 engine's 9639.658385038165).

Each case: {"x": <number>, "expected_hex": "<math.exp(x) as float.hex()>"} —
the hex string is the bit-exact expected double.

Battery (>=200 cases):
  - the workbook's actual exp inputs: x = -2*J9*6/60 from every sheet's J9 in
    tests/fixtures/grid_dump.json (all near -0.305), plus values very close
    to them (+/-1..3 ulp neighbors, small decimal offsets, 3/4-decimal
    roundings);
  - dense coverage of [-1, 1]: k/200 for k = -200..200 (step 0.005, which
    includes -0.305 itself);
  - samples across [-10, 10]: k/4 for k = -40..40 (step 0.25);
  - extremes: +/-20, +/-0.001, +/-1e-6, 0.

Usage (from repo root): .venv/bin/python tools/gen_exp_fixture.py
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRID_PATH = ROOT / "tests" / "fixtures" / "grid_dump.json"
OUT = ROOT / "tests" / "fixtures" / "exp_cases.json"

MIN_CASES = 200


def n_ulp(x, k):
    """x shifted k ulps toward +inf (k > 0) or -inf (k < 0)."""
    toward = math.inf if k > 0 else -math.inf
    for _ in range(abs(k)):
        x = math.nextafter(x, toward)
    return x


def workbook_exp_inputs():
    """(ref, x) pairs for x = -2*J9*6/60 from every sheet's J9 in the grid
    dump — the exp argument of the +Stat V83 cells. * and / evaluate
    left-to-right, identically in Excel, the TS engine, and here, so the
    argument bits match the workbook's exactly."""
    grid = json.loads(GRID_PATH.read_text(encoding="utf-8"))
    pairs = []
    for ref in sorted(k for k in grid if k.endswith("!J9")):
        v = grid[ref]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue  # defensive: J9 is a number on every sheet that has one
        pairs.append((ref, -2 * v * 6 / 60))
    return pairs


def build_battery(workbook_xs):
    """Ordered, deduped x values: workbook inputs first, then near-workbook
    probes, the [-1, 1] grid, the [-10, 10] samples, and the extremes."""
    xs = []

    def add(*vals):
        xs.extend(vals)

    # 1. The workbook's actual inputs, then values very close to them (the
    #    Python-vs-V8 divergence lives in this neighborhood).
    add(*workbook_xs)
    for x in workbook_xs:
        add(*(n_ulp(x, k) for k in (-3, -2, -1, 1, 2, 3)))
        for d in (1e-3, 1e-4, 1e-6, 1e-9, 1e-12):
            add(x + d, x - d)
        add(round(x, 4), round(x, 3))

    # 2. Dense coverage of [-1, 1] (step 0.005; includes -0.305 itself).
    add(*(k / 200 for k in range(-200, 201)))

    # 3. Samples across [-10, 10] (step 0.25).
    add(*(k / 4 for k in range(-40, 41)))

    # 4. Extremes.
    add(20, -20, 0.001, -0.001, 1e-6, -1e-6, 0)

    seen = set()
    uniq = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def main():
    per_sheet = workbook_exp_inputs()
    assert per_sheet, "no <Sheet>!J9 entries found in the grid dump"

    workbook_xs = []
    for _, x in per_sheet:
        if x not in workbook_xs:
            workbook_xs.append(x)

    xs = build_battery(workbook_xs)
    cases = [{"x": x, "expected_hex": math.exp(x).hex()} for x in xs]
    assert len(cases) >= MIN_CASES, f"only {len(cases)} cases"

    # Self-check: the written JSON must reload to the exact same doubles,
    # and each hex string must decode back to math.exp of the reloaded x
    # (json.dumps emits the shortest round-trip repr for floats).
    text = json.dumps(cases, indent=2) + "\n"
    for case, back in zip(cases, json.loads(text)):
        assert repr(case["x"]) == repr(back["x"]), case
        assert float.fromhex(back["expected_hex"]) == math.exp(back["x"]), case

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    print(f"wrote {OUT}: {len(cases)} cases")
    print(f"workbook exp inputs (x = -2*J9*6/60, {len(per_sheet)} sheets with a J9):")
    for ref, x in per_sheet:
        print(f"  {ref}: x={x!r} -> {math.exp(x).hex()}")


if __name__ == "__main__":
    main()
