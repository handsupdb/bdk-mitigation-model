#!/usr/bin/env python3
"""Generate tests/fixtures/pow_cases.json — a bit-exact spec for pow (^).

The TS engine's `**` must match the oracle's arithmetic: Python's `**`
(libm pow) reproduced Excel's cached workbook values exactly, while V8's
`**`/Math.pow diverges by ulps on fractional exponents (e.g.
(0.85)^(8*L9)), which the Outputs sheet's (stat-baseline)/10 cancellation
amplifies into 3 failing Pawn strings (Outputs C43/C69/C82).

Each case: {"a": <base>, "b": <exponent>, "expected_hex": "<a**b as
float.hex()>"} — the hex string is the bit-exact expected double.

Battery (>=300 cases):
  - the workbook's actual ^ operands: every ^ in
    data/wow-12.1/formulas/*.tsv, with base and exponent expressions
    evaluated from tests/fixtures/oracle_dump.json cell values (formula
    cells), falling back to the TSVs' literal constants (e.g. N51 = -1.0)
    and treating blank cells as 0 — the oracle's semantics;
  - neighborhoods of each workbook operand: +/-1,2 ulps and +/-1e-9,
    +/-1e-6;
  - a general grid: bases 0.5..2.0 (step 0.1) x exponents -10..10
    (step 0.5); integer exponents 2/3/8 over wider bases; edges (0^0, 1^x,
    x^0, x^1, negative base with integer exponent); deliberate error
    probes (negative base ** fractional exponent, 0 ** negative,
    overflow) — skipped and counted, not written.

Self-checks:
  - every ^-bearing formula that is plain arithmetic (+ - * / ^ with only
    exp/MIN/MAX/SUM) is recomputed from the same cell values and must
    reproduce the oracle dump's cached value bit-exactly;
  - the written JSON must reload to the exact same doubles, and each hex
    string must decode back to a**b of the reloaded operands.

Also prints how many cases V8's Math.pow / `**` miss by >=1 ulp (via
`node -e`, if a node binary can be found).

Usage (from repo root): .venv/bin/python tools/gen_pow_fixture.py
"""
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMULAS_DIR = ROOT / "data" / "wow-12.1" / "formulas"
ORACLE_PATH = ROOT / "tests" / "fixtures" / "oracle_dump.json"
OUT = ROOT / "tests" / "fixtures" / "pow_cases.json"

MIN_CASES = 300
MAX_RANGE_CELLS = 100_000      # same cap as tools/dump_oracle.py
BLANK_SENTINELS = ("", "<NO_CACHED_VALUE>")
NODE_CANDIDATES = ("/opt/homebrew/bin/node", "/usr/local/bin/node")


class CellError(Exception):
    """A cell/operand could not be resolved/evaluated as a number."""


# --------------------------------------------------------------- formula TSVs

def sheet_of(stem):
    """TSV stem -> sheet name ('_Critical_Strike' -> '+Critical Strike')."""
    return "+" + stem[1:].replace("_", " ") if stem.startswith("_") else stem


def load_tsvs():
    """{sheet: {ref: cell text}} in file/row order (text '=' -> formula)."""
    sheets = {}
    for path in sorted(FORMULAS_DIR.glob("*.tsv")):
        cells = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            ref, sep, text = line.partition("\t")
            if sep and ref:
                cells[ref] = text
        sheets[sheet_of(path.stem)] = cells
    return sheets


# ------------------------------------------------------------ ^ extraction

def extract_carets(formula):
    """(base_text, exp_text) for every ^ in a formula.

    Bare operand tokens are [A-Za-z0-9.$]+ — no '-': the base of
    '1-0.85^x' is 0.85, not 1-0.85. Parenthesized operands are taken whole
    (balanced). Excel's ^ is left-associative and unary minus binds
    tighter (-x^2 = (-x)^2), so chained ^ and unary-minus bases would make
    the extracted pairs differ from the actual pow() calls — neither
    occurs in the workbook; both are rejected here.
    """
    pairs = []
    for i, ch in enumerate(formula):
        if ch != "^":
            continue
        if i == 0 or i + 1 >= len(formula):
            raise CellError(f"dangling ^: {formula[:80]!r}")
        if formula[i - 1] == ")":                       # parenthesized base
            j, depth = i - 1, 0
            while j >= 0:
                if formula[j] == ")":
                    depth += 1
                elif formula[j] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if j < 0:
                raise CellError(f"unbalanced parens: {formula[:80]!r}")
            base = formula[j:i]
        else:                                          # bare base token
            j = i - 1
            while j >= 0 and (formula[j].isalnum() or formula[j] in ".$"):
                j -= 1
            base = formula[j + 1:i]
            if not base:
                raise CellError(f"empty ^ base: {formula[:80]!r}")
            k = j
            while k >= 0 and formula[k] == " ":
                k -= 1
            if k >= 0 and formula[k] == "-" and (k == 0 or formula[k - 1] in "+-*/(^,"):
                raise CellError(f"unary-minus ^ base: {formula[:80]!r}")
        if formula[i + 1] == "(":                       # parenthesized exponent
            j, depth = i + 1, 0
            while j < len(formula):
                if formula[j] == "(":
                    depth += 1
                elif formula[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(formula):
                raise CellError(f"unbalanced parens: {formula[:80]!r}")
            exp, after = formula[i + 1:j + 1], formula[j + 1:j + 2]
        else:                                          # bare exponent token
            j = i + 1
            while j < len(formula) and (formula[j].isalnum() or formula[j] in ".$"):
                j += 1
            exp, after = formula[i + 1:j], formula[j:j + 1]
            if not exp:
                raise CellError(f"empty ^ exponent: {formula[:80]!r}")
        if after == "^":
            raise CellError(f"chained ^: {formula[:80]!r}")
        pairs.append((base, exp))
    return pairs


# ---------------------------------------------------------- cell resolution

def resolve_cell(sheets, oracle, sheet, ref):
    """Numeric value of one cell, the oracle's semantics.

    Oracle dump first (formula cells; null = blank -> 0 in arithmetic),
    then the TSVs' literal constants (e.g. N51 = -1.0), then blank -> 0.
    Text cells raise CellError (text is not a number in arithmetic).
    """
    key = f"{sheet}!{ref}"
    if key in oracle:
        v = oracle[key]
        if v is None:
            return 0.0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CellError(f"{key} is text")
        return float(v)
    raw = sheets.get(sheet, {}).get(ref)
    if raw is None or raw in BLANK_SENTINELS:
        return 0.0                                      # blank cell
    if raw.startswith("="):
        raise CellError(f"{key}: formula missing from the oracle dump")
    try:
        return float(raw)
    except ValueError:
        raise CellError(f"{key} is text: {raw[:40]!r}") from None


def col_num(letters):
    n = 0
    for ch in letters.upper():
        if not "A" <= ch <= "Z":
            raise CellError(f"bad column {letters!r}")
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


RANGE_RE = re.compile(
    r"\$?([A-Za-z]{1,3})\$?([0-9]+):\$?([A-Za-z]{1,3})\$?([0-9]+)"
)


def expand_range(rng):
    """'Z19:Z36' -> ['Z19', ..., 'Z36'] (column-major, Excel order)."""
    m = RANGE_RE.fullmatch(rng)
    if not m:
        raise CellError(f"bad range {rng!r}")
    c1, r1, c2, r2 = col_num(m[1]), int(m[2]), col_num(m[3]), int(m[4])
    c1, c2 = min(c1, c2), max(c1, c2)
    r1, r2 = min(r1, r2), max(r1, r2)
    if (c2 - c1 + 1) * (r2 - r1 + 1) > MAX_RANGE_CELLS:
        raise CellError(f"range too large: {rng!r}")
    return [f"{col_letters(c)}{r}" for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]


# cell ref: optional 'quoted' or bare sheet qualifier, optional $s
REF_RE = re.compile(
    r"(?<![A-Za-z0-9_$.!])"
    r"(?:(?:'([^']+)'|([A-Za-z0-9_ .]+))!)?"
    r"\$?([A-Za-z]{1,3})\$?([0-9]+)"
    r"(?![A-Za-z0-9_$.!:])"
)


def ref_of(match, default_sheet):
    """(sheet, ref) of a REF_RE match."""
    sheet = (match[1] or match[2] or default_sheet).strip()
    return sheet, f"{match[3]}{match[4]}"


# --------------------------------------------------------- operand evaluation

def split_top(text):
    """Split on depth-0 commas."""
    args, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(text[start:i])
            start = i + 1
    args.append(text[start:])
    return args


def replace_sum(text, sheet, sheets, oracle):
    """Replace every SUM(...) call with its numeric value (the oracle's
    SUM: range args sum their numeric cells, blanks/text skipped)."""
    pos = 0
    while True:
        i = text.find("SUM(", pos)
        if i < 0:
            return text
        if i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_$"):
            pos = i + 1                                  # part of a longer word
            continue
        j, depth, k = i + 3, 0, i + 3                    # j = index of '('
        while k < len(text):
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= len(text):
            raise CellError(f"unbalanced SUM parens: {text[:80]!r}")
        total = 0.0
        for arg in split_top(text[j + 1:k]):
            arg = arg.strip()
            if RANGE_RE.fullmatch(arg):
                for ref in expand_range(arg):
                    try:
                        total += resolve_cell(sheets, oracle, sheet, ref)
                    except CellError:
                        pass                             # text skipped in SUM ranges
            elif REF_RE.fullmatch(arg):
                s, ref = ref_of(REF_RE.fullmatch(arg), sheet)
                total += resolve_cell(sheets, oracle, s, ref)
            else:
                try:
                    total += float(arg)
                except ValueError:
                    raise CellError(f"unsupported SUM arg: {arg[:40]!r}") from None
        repl = repr(total)
        text = text[:i] + repl + text[k + 1:]
        pos = i + len(repl)


# only numbers, operators, parens/commas/space, and exp/MIN/MAX may remain
ALLOWED_RE = re.compile(r"(?:[0-9eE+\-*/().,\s]|exp|MIN|MAX)*")


def eval_expr(text, sheet, sheets, oracle):
    """Evaluate an Excel arithmetic expression (+ - * / ^, exp/MIN/MAX/SUM)
    over cell refs to a float, using the oracle dump's cell values."""
    text = replace_sum(text, sheet, sheets, oracle)

    def sub(m):
        s, ref = ref_of(m, sheet)
        return repr(resolve_cell(sheets, oracle, s, ref))

    text = REF_RE.sub(sub, text).replace("^", "**")
    if not ALLOWED_RE.fullmatch(text):
        raise CellError(f"unsupported tokens: {text[:80]!r}")
    try:
        val = eval(  # noqa: S307 — whitelist above; refs already substituted
            text,
            {"__builtins__": {}},
            {"exp": math.exp, "MIN": min, "MAX": max},
        )
    except Exception as e:  # NameError/SyntaxError/ZeroDivision/Overflow/...
        raise CellError(f"{text[:80]!r}: {e}") from None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise CellError(f"non-numeric result: {text[:80]!r}")
    return float(val)


# ------------------------------------------------------------- workbook scan

def scan_workbook(sheets, oracle):
    """Every ^ occurrence -> (sheet, ref, base_text, exp_text, a, b);
    unresolvable ones -> (where, reason) skips."""
    occurrences, skips = [], []
    for sheet, cells in sheets.items():
        for ref, text in cells.items():
            if not text.startswith("=") or "^" not in text:
                continue
            body = text[1:]
            try:
                carets = extract_carets(body)
            except CellError as e:
                skips.append((f"{sheet}!{ref}", str(e)))
                continue
            for bt, et in carets:
                try:
                    a = eval_expr(bt, sheet, sheets, oracle)
                    b = eval_expr(et, sheet, sheets, oracle)
                except CellError as e:
                    skips.append((f"{sheet}!{ref}", f"{bt} ^ {et}: {e}"))
                    continue
                occurrences.append((sheet, ref, bt, et, a, b))
    return occurrences, skips


# ------------------------------------------------- oracle self-check (full cells)

UNSUPPORTED_RE = re.compile(r"[=<>%&]")   # comparisons / percent / concat
OTHER_FN_RE = re.compile(r"\b(?!exp\b|MIN\b|MAX\b|SUM\b)([A-Za-z][A-Za-z0-9.]*)\s*\(")


def self_check(sheets, oracle):
    """Recompute every ^-bearing formula that is plain arithmetic
    (+ - * / ^ with only exp/MIN/MAX/SUM) from the same cell values; each
    must reproduce the oracle dump's cached value bit-exactly."""
    checked, skipped, failures = 0, 0, []
    for sheet, cells in sheets.items():
        for ref, text in cells.items():
            if not text.startswith("=") or "^" not in text:
                continue
            body = text[1:]
            if UNSUPPORTED_RE.search(body) or OTHER_FN_RE.search(body):
                skipped += 1
                continue
            try:
                extract_carets(body)      # guards: no chained ^/unary-minus base
                got = eval_expr(body, sheet, sheets, oracle)
            except CellError:
                skipped += 1
                continue
            want = oracle.get(f"{sheet}!{ref}")
            if isinstance(want, bool) or not isinstance(want, (int, float)):
                skipped += 1
                continue
            checked += 1
            if got.hex() != float(want).hex():
                failures.append((f"{sheet}!{ref}", got, float(want)))
    return checked, skipped, failures


# ------------------------------------------------------------------- battery

def n_ulp(x, k):
    """x shifted k ulps toward +inf (k > 0) or -inf (k < 0)."""
    toward = math.inf if k > 0 else -math.inf
    for _ in range(abs(k)):
        x = math.nextafter(x, toward)
    return x


def build_battery(workbook_pairs):
    """Ordered, deduped (a, b) pairs: workbook operands, their ulp/decimal
    neighborhoods, the general grid, integer exponents, edges, and
    deliberate error probes."""
    pairs = []

    def add(a, b):
        pairs.append((float(a), float(b)))

    for a, b in workbook_pairs:
        add(a, b)
    for a, b in workbook_pairs:
        for d in (1e-9, 1e-6):
            add(a - d, b)
            add(a + d, b)
            add(a, b - d)
            add(a, b + d)
        for k in (1, 2, -1, -2):
            add(n_ulp(a, k), b)
            add(a, n_ulp(b, k))
    # general grid: bases 0.5..2.0 (step 0.1) x exponents -10..10 (step 0.5)
    for i in range(16):
        for j in range(41):
            add(0.5 + 0.1 * i, -10.0 + 0.5 * j)
    # integer exponents 2/3/8 over wider bases
    for base in (0.25, 0.5, 0.75, 0.85, 0.875, 1.0, 1.2, 1.5, 1.75, 2.0, 3.0, 10.0):
        for e in (2, 3, 8):
            add(base, e)
    # edges: 0^0, 1^x, x^0, x^1
    add(0.0, 0.0)
    add(0.0, 1.0)
    add(0.0, 2.0)
    add(0.0, 0.5)
    add(1.0, 0.0)
    add(1.0, 0.5)
    add(1.0, 1.0)
    add(1.0, 2.0)
    add(1.0, -1.0)
    add(1.0, 10.0)
    add(1.0, -10.0)
    for x in (0.5, 0.75, 0.85, 0.875, 1.2, 1.5, 2.0, 3.0, 10.0, -0.75, -2.0):
        add(x, 0.0)
        add(x, 1.0)
    # negative base with integer exponent
    for base in (-0.5, -0.75, -0.85, -0.875, -1.0, -1.2, -1.5, -2.0, -10.0):
        for e in (2, 3, 8):
            add(base, e)
    # deliberate error probes (skipped + counted when building cases)
    for a, b in ((-0.75, 4.125), (-2.0, 0.5), (-1.5, -3.5),
                 (0.0, -1.0), (0.0, -2.5), (2.0, 10000.0), (10.0, 400.0)):
        add(a, b)

    seen, uniq = set(), []
    for a, b in pairs:
        key = (a.hex(), b.hex())          # bit-exact dedupe (-0.0 != 0.0)
        if key not in seen:
            seen.add(key)
            uniq.append((a, b))
    return uniq


# ------------------------------------------------------------------ V8 check

NODE_JS = r"""const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
function fromHex(h) {
  if (h === 'inf') return Infinity;
  if (h === '-inf') return -Infinity;
  if (h === 'nan') return NaN;
  const m = /^(-?)0x([0-9a-f]+)\.([0-9a-f]+)p([+-]\d+)$/.exec(h);
  if (!m) throw new Error('bad hex: ' + h);
  return (m[1] === '-' ? -1 : 1) *
      parseInt(m[2] + m[3], 16) *
      Math.pow(2, parseInt(m[4], 10) - 4 * m[3].length);
}
const buf = new ArrayBuffer(8);
const f64 = new Float64Array(buf);
const u64 = new BigUint64Array(buf);
const bits = (x) => { f64[0] = x; return u64[0]; };
function check(fn) {
  let miss = 0, gt1 = 0, worst = 0, worstCase = null;
  for (const c of cases) {
    const e = fromHex(c.expected_hex);
    const g = fn(c.a, c.b);
    if (Number.isNaN(e) && Number.isNaN(g)) continue;
    const be = bits(e), bg = bits(g);
    if (be === bg) continue;
    miss++;
    const d = Number(bg < be ? be - bg : bg - be);
    if (d > 1) gt1++;
    if (d > worst) { worst = d; worstCase = { a: c.a, b: c.b, expected: e, got: g }; }
  }
  return { miss, gt1, worst, worstCase };
}
console.log(JSON.stringify({
  total: cases.length,
  mathPow: check((a, b) => Math.pow(a, b)),
  star: check((a, b) => a ** b),
}));
"""


def find_node():
    for cand in (shutil.which("node"),) + NODE_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    return None


def v8_report(path):
    """Count cases V8's Math.pow / `**` miss by >=1 ulp, via `node -e`."""
    node = find_node()
    if node is None:
        return None
    proc = subprocess.run([node, "-e", NODE_JS, str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"node check failed ({proc.returncode}): "
              f"{proc.stderr.strip()[:200]}")
        return None
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------- main

def main():
    sheets = load_tsvs()
    oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))

    occurrences, skips = scan_workbook(sheets, oracle)
    assert occurrences, "no ^ occurrences found in the formula TSVs"

    patterns = {}                          # (base_text, exp_text) -> [(a, b)]
    for _, _, bt, et, a, b in occurrences:
        patterns.setdefault((bt, et), []).append((a, b))
    workbook_pairs, seen = [], set()
    for _, _, _, _, a, b in occurrences:
        key = (a.hex(), b.hex())
        if key not in seen:
            seen.add(key)
            workbook_pairs.append((a, b))

    battery = build_battery(workbook_pairs)
    cases, errors = [], 0
    for a, b in battery:
        try:
            v = a ** b
        except (ZeroDivisionError, OverflowError):
            errors += 1                    # 0 ** negative, overflow
            continue
        if isinstance(v, complex):
            errors += 1                    # negative base ** fractional exponent
            continue
        cases.append({"a": a, "b": b, "expected_hex": float(v).hex()})
    assert len(cases) >= MIN_CASES, f"only {len(cases)} cases"

    # reload self-check: same doubles, and each hex decodes back to a**b
    text = json.dumps(cases, indent=2) + "\n"
    for case, back in zip(cases, json.loads(text)):
        assert repr(case["a"]) == repr(back["a"]), case
        assert repr(case["b"]) == repr(back["b"]), case
        assert float.fromhex(back["expected_hex"]).hex() \
            == (back["a"] ** back["b"]).hex(), case

    # oracle self-check: plain-arithmetic ^-formulas recomputed bit-exactly
    checked, skipped, failures = self_check(sheets, oracle)
    assert checked > 0, "self-check matched no formulas"
    assert not failures, f"self-check failures: {failures[:5]}"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    # ---- report ----
    print(f"wrote {OUT}: {len(cases)} cases ({errors} error/complex results skipped)")
    print(f"workbook ^ occurrences: {len(occurrences)} -> "
          f"{len(workbook_pairs)} distinct operand pairs, {len(skips)} unresolvable")
    for where, why in skips:
        print(f"  SKIP {where}: {why}")
    print(f"distinct ^ patterns ({len(patterns)}, {len(occurrences)} carets):")
    for (bt, et), pairs in sorted(patterns.items(),
                                  key=lambda kv: (-len(kv[1]), kv[0])):
        line = f"  {len(pairs):4d}x  {bt} ^ {et}"
        print(line if len(line) <= 160 else line[:157] + "...")
    print(f"distinct workbook operand pairs ({len(workbook_pairs)}):")
    for a, b in workbook_pairs:
        print(f"  a={a!r} b={b!r}")
    print(f"self-check: {checked} plain-arithmetic ^-formulas recomputed from "
          f"dump values — all {checked} match the oracle bit-exactly "
          f"({skipped} skipped: IF/comparisons/other functions)")

    v8 = v8_report(OUT)
    if v8:
        for name, label in (("mathPow", "V8 Math.pow"), ("star", "V8 **")):
            r = v8[name]
            wc = r["worstCase"]
            tail = ""
            if wc:
                tail = (f"; worst {r['worst']} ulps at a={wc['a']!r}, "
                        f"b={wc['b']!r} (expected {wc['expected']!r}, "
                        f"got {wc['got']!r})")
            print(f"{label}: {r['miss']}/{v8['total']} cases miss by >=1 ulp "
                  f"({r['gt1']} by >1 ulp){tail}")


if __name__ == "__main__":
    main()
