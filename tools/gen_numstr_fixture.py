#!/usr/bin/env python3
"""Generate tests/fixtures/numstr_cases.json — golden cases for Excel's
number->text coercion (General format, '&' concatenation), as implemented by
the empirically proven excel_num_str() in extracted/verify_chains.py.

Each case: {"x": <number>, "expected": "<string>"}. Every JSON number is
verified to round-trip the exact double (json.loads of the dumped text must
yield a value with an identical repr); any offender is stored as a string with
a "note" field instead (none expected: json.dumps emits the shortest
round-trip repr for floats).

Usage (from repo root): .venv/bin/python tools/gen_numstr_fixture.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extracted.verify_chains import excel_num_str  # noqa: E402  (path set above)

OUT = ROOT / "tests" / "fixtures" / "numstr_cases.json"


def down(x):  # -1 ulp neighbor
    return math.nextafter(x, -math.inf)


def up(x):  # +1 ulp neighbor
    return math.nextafter(x, math.inf)


# --- test inputs ------------------------------------------------------------
INPUTS = [
    # Provenance: Outputs!D9. repr's 16th significant digit is 5, so Excel's
    # half-away-from-zero rounding of the SHORTEST ROUND-TRIP repr gives
    # ...0173, not the correctly-rounded ...0172 of the exact binary value.
    0.004392465626901725,

    # Integers (rendered plain, no decimal point)
    0, 1, 2, 7, 10, 42, 100, 999, 1000, 12345, 1000000, 1234567890123,

    # Simple decimals
    1.5, 3966.55, 0.1, 0.5, 2.25, 0.25, 100.5, 123.456, 3.14159,
    2.718281828459045,  # 16th sig digit 5 -> half-up to 2.71828182845905
    0.3333333333333333, 99999.9,

    # Long-precision values from the workbook
    0.9996620210884503, 3720571.088, 1.6307412964988721e-06, 5.07528516668376e-13,

    # 15th-significant-digit boundary: repr's 16th significant digit is
    # exactly 5 (half-away-from-zero rounds the 15th digit UP), plus the
    # +/-1-ulp neighbors (16th digit 4/8/3 -> rounds down or up normally).
    down(0.004392465626901725), up(0.004392465626901725),
    1.000000000000005, down(1.000000000000005), up(1.000000000000005),
    0.1000000000000005, down(0.1000000000000005), up(0.1000000000000005),
    1234567890123.455, down(1234567890123.455), up(1234567890123.455),
    0.9999999999999999,  # 16 nines -> carries to '1'
    9.999999999999999e-05,  # sci branch: mantissa carries to '1E-4'

    # Magnitude boundaries around the 1e-4 decimal/scientific cutover
    1e-3, 1e-4, 9.99e-5, 1.00001e-4, 1e-5, 0.000123456789012345, 0.00025,

    # Large magnitudes (still decimal notation, |x| < 1e15)
    1e12, 1234567890123.45, 999999999999.999, 123456789012345.6,
    99999999999999.99,  # repr is ...98; 16th digit 8 -> carries to 1e14

    # Negatives (mirrors of the interesting positives)
    -0.004392465626901725, -1.5, -3966.55, -0.1, -2.5,
    -0.9996620210884503, -3720571.088, -1.6307412964988721e-06,
    -5.07528516668376e-13, -1e-3, -1e-4, -9.99e-5, -1e-5, -1e12,
    -1234567890123.45, -0.9999999999999999, -5, -100,

    # Signed zeros
    0.0, -0.0,
]

# The four long-precision workbook values whose expected strings are printed.
LONG_PRECISION = [
    0.9996620210884503, 3720571.088, 1.6307412964988721e-06, 5.07528516668376e-13,
]


def roundtrips(x, y):
    """True if the JSON-reloaded y is exactly the original number x."""
    if type(x) is not type(y):
        return False
    if isinstance(x, float):
        return repr(x) == repr(y)  # exact double identity (keeps -0.0 apart)
    return x == y


def main():
    cases = [{"x": x, "expected": excel_num_str(x)} for x in INPUTS]

    # Verify every JSON number round-trips the exact double; offenders are
    # stored as strings with a note instead.
    reloaded = json.loads(json.dumps(cases))
    notes = []
    for case, back in zip(cases, reloaded):
        if not roundtrips(case["x"], back["x"]):
            notes.append(case)
            case["note"] = ("JSON number did not round-trip the exact double; "
                            "x stored as string")
            case["x"] = repr(case["x"])

    text = json.dumps(cases, indent=2) + "\n"
    # Re-verify after any fallback (strings always round-trip).
    for case, back in zip(cases, json.loads(text)):
        assert roundtrips(case["x"], back["x"]), (case, back)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    print(f"wrote {OUT}: {len(cases)} cases")
    if notes:
        print(f"NOTE: {len(notes)} x values stored as strings (no JSON round-trip)")
    else:
        print("all JSON numbers round-trip the exact double")
    print("long-precision expected strings:")
    for x in LONG_PRECISION:
        exp = next(c["expected"] for o, c in zip(INPUTS, cases)
                   if type(o) is type(x) and o == x)
        print(f"  {x!r} -> {exp!r}")


if __name__ == "__main__":
    main()
