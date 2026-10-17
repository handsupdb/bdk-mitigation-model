#!/usr/bin/env python3
"""Convert extracted/*__values.tsv into golden JSON fixtures for the test suite.

For every extracted/<safe_sheet>__values.tsv (produced by extract_xlsx.py),
writes tests/fixtures/golden/<safe_sheet>.json as a flat JSON object:

    { "<cell_ref>": <value>, ..., "uncached": ["<cell_ref>", ...] }

Value conversion:
  - "<NO_CACHED_VALUE>" marker -> cell ref goes into the "uncached" array
  - "True" / "False"          -> JSON boolean
  - integer literal           -> JSON number (int)
  - float literal             -> JSON number (float)
  - anything else             -> JSON string (TSV escape sequences unescaped)

Usage: .venv/bin/python tools/make_golden_fixtures.py
"""
import json
import os
import re
import sys

EXTRACTED_DIR = "extracted"
OUT_DIR = os.path.join("tests", "fixtures", "golden")

NO_CACHED = "<NO_CACHED_VALUE>"
INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_UNESCAPE = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}


def unescape(s: str) -> str:
    """Reverse extract_xlsx.py's sanitize() escaping of \t, \n, \r and \\."""
    return re.sub(r"\\([\\tnr])", lambda m: _UNESCAPE[m.group(1)], s)


def convert(content: str):
    """Convert one TSV cell-content string to a JSON-ready value."""
    if content == NO_CACHED:
        return NO_CACHED  # sentinel; caller routes the ref to "uncached"
    if content == "True":
        return True
    if content == "False":
        return False
    if INT_RE.match(content):
        return int(content)
    if FLOAT_RE.match(content):
        return float(content)
    return unescape(content)


def main() -> int:
    if not os.path.isdir(EXTRACTED_DIR):
        print(f"error: {EXTRACTED_DIR}/ not found — run extract_xlsx.py first",
              file=sys.stderr)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    total_entries = 0
    total_uncached = 0
    tsvs = sorted(
        f for f in os.listdir(EXTRACTED_DIR) if f.endswith("__values.tsv")
    )
    if not tsvs:
        print(f"error: no *__values.tsv files in {EXTRACTED_DIR}/", file=sys.stderr)
        return 1

    for fname in tsvs:
        sheet = fname[: -len("__values.tsv")]
        cells = {}
        uncached = []
        with open(os.path.join(EXTRACTED_DIR, fname), encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                ref, _, content = line.partition("\t")
                value = convert(content)
                if value is NO_CACHED:
                    uncached.append(ref)
                else:
                    cells[ref] = value
        cells["uncached"] = uncached

        out_path = os.path.join(OUT_DIR, f"{sheet}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cells, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")

        total_entries += len(cells) - 1
        total_uncached += len(uncached)
        print(f"  {sheet}: {len(cells) - 1} cells, {len(uncached)} uncached")

    print(f"Wrote {len(tsvs)} fixtures to {OUT_DIR}/ "
          f"({total_entries} cells, {total_uncached} uncached total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
