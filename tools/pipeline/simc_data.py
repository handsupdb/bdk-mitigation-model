#!/usr/bin/env python
"""SimC spell-data fetcher/parser for the proposed-diff pipeline.

Source: simulationcraft/simc, branch ``midnight`` (wow build 12.1.5.70448),
``engine/dbc/generated/sc_spell_data.inc`` (~29.6 MB). ``fetch()`` downloads it
with curl to ``extracted/simc_sc_spell_data.inc`` and skips the download when a
cached copy larger than 20 MB is already present.

File layout (positions verified against the file itself and
engine/dbc/spell_data.hpp — see the position table below):

* ``__spell_data`` rows: ``{ "Name", id, ... }``  ->  spell name -> spell id.
  Duplicate names exist (e.g. "Heart Strike" -> 206930/228645/316575); the first
  occurrence wins and all ids are kept in ``spell_aliases``.
* ``__spelleffect_data`` rows: positional initializers in spelleffect_data_t
  member order. 1-based positions: 11 = sp_coeff, 12 = ap_coeff,
  16 = base_value. Midnight rows carry 2 extra trailing fields beyond the 29
  documented in spell_data.hpp; the positions above are unaffected. Rows with
  ``_spell_id == 0`` are nil placeholders (612 in build 12.1.5.70448) and are
  skipped; the remaining 52829 unique ``(spell_id, _index)`` keys match the
  file's own ``__spelleffect_id_index`` size.
* Effect indices: the file's ``_index`` field is 0-based, while SimC's
  ``spell_data_t::effectN( idx )`` is 1-based (``effects()[ idx - 1 ]``, with an
  assert that idx > 0). This module follows the 1-based effectN convention in
  ``lookup`` and the CLI, i.e. file ``_index`` = ``effect_index - 1``.
  NOTE: extracted/simc_research.md labels effects with the 0-based file index
  ("eff0"/"eff1"), so the doc's "eff1" is this module's effect 2.

Accessor semantics (spell_data.hpp): ``percent()`` = base_value / 100;
``mastery_value()`` = sp_coeff / 100; ``resource(RP)`` = base_value * 10 (RP is
stored in tenths). ``lookup`` exposes ``percent`` = base_value / 100.

CLI:
    .venv/bin/python tools/pipeline/simc_data.py <spell_name> <effect_index>
"""

import argparse
import difflib
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_PATH = os.path.join(REPO_ROOT, "extracted", "simc_sc_spell_data.inc")
SPELL_DATA_URL = (
    "https://raw.githubusercontent.com/simulationcraft/simc/midnight/"
    "engine/dbc/generated/sc_spell_data.inc"
)
MIN_CACHE_BYTES = 20 * 1024 * 1024  # a cached copy larger than this is trusted

# 1-based field positions inside __spelleffect_data rows (spelleffect_data_t
# member order: _id, _spell_id, _index, _type, _subtype, _scaling_type,
# _attribute, _m_coeff, _m_delta, _m_unk, _sp_coeff, _ap_coeff, _amplitude,
# _radius, _radius_max, _base_value, _misc_value, _misc_value_2,
# _class_flags[4], _trigger_spell_id, ...).
POS_ID = 1
POS_SPELL_ID = 2
POS_INDEX = 3
POS_TYPE = 4
POS_SUBTYPE = 5
POS_SCALING_TYPE = 6
POS_M_COEFF = 8
POS_M_DELTA = 9
POS_SP_COEFF = 11
POS_AP_COEFF = 12
POS_AMPLITUDE = 13
POS_RADIUS = 14
POS_RADIUS_MAX = 15
POS_BASE_VALUE = 16
POS_MISC_VALUE = 17
POS_MISC_VALUE_2 = 18
POS_TRIGGER_SPELL_ID = 20

# Spell names may contain escaped quotes (e.g. `\"Well Fed\"`).
_SPELL_ROW_RE = re.compile(r'^\{\s*"((?:[^"\\]|\\.)*)"\s*,\s*(\d+)\s*,')
_BUILD_RE = re.compile(r"wow build level (\S+)")
_DECLARED_RE = re.compile(r"\[(\d+)\]")


def _split_top_level(body: str) -> List[str]:
    """Split an initializer body on top-level commas only.

    Braced groups (e.g. the _class_flags[4] initializer ``{ 0, 0, 0, 0 }``)
    stay whole, so token positions line up with the positional fields. (A
    plain comma split breaks on the group's inner commas; a regex tokenizer
    emits a spurious whitespace token before the group and shifts positions.)
    """
    fields: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in body:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            fields.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        fields.append(tail)
    return fields


def fetch(force: bool = False) -> str:
    """Download sc_spell_data.inc to CACHE_PATH unless a >20 MB copy exists."""
    if (
        not force
        and os.path.isfile(CACHE_PATH)
        and os.path.getsize(CACHE_PATH) > MIN_CACHE_BYTES
    ):
        return CACHE_PATH
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    subprocess.run(["curl", "-sSL", "-o", CACHE_PATH, SPELL_DATA_URL], check=True)
    size = os.path.getsize(CACHE_PATH)
    if size <= MIN_CACHE_BYTES:
        raise RuntimeError(
            f"fetched file is unexpectedly small ({size} bytes): {CACHE_PATH}"
        )
    return CACHE_PATH


class SimcSpellData:
    """Parsed view of sc_spell_data.inc: name->id plus effect rows."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.build: Optional[str] = None
        self.declared_spell_count: Optional[int] = None
        self.declared_effect_count: Optional[int] = None
        self.spells: Dict[str, int] = {}  # name -> id (first occurrence wins)
        self.spell_aliases: Dict[str, List[int]] = {}  # name -> all ids
        self.spell_rows = 0  # total __spell_data rows parsed
        self.effect_rows = 0  # total __spelleffect_data rows parsed
        # (spell_id, 0-based file _index) -> parsed fields
        self.effects: Dict[Tuple[int, int], Dict[str, object]] = {}
        self._parse()

    # -- parsing -----------------------------------------------------------

    def _parse(self) -> None:
        section: Optional[str] = None  # "spell" | "effect" | None
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("//"):
                    m = _BUILD_RE.search(s)
                    if m and self.build is None:
                        self.build = m.group(1)
                    continue
                if s.startswith("static "):
                    if "spell_data_t __spell_data" in s:
                        section = "spell"
                        m = _DECLARED_RE.search(s)
                        self.declared_spell_count = int(m.group(1)) if m else None
                    elif "spelleffect_data_t __spelleffect_data" in s:
                        section = "effect"
                        m = _DECLARED_RE.search(s)
                        self.declared_effect_count = int(m.group(1)) if m else None
                    else:
                        section = None  # some other array; stop trusting rows
                    continue
                if s == "};":
                    section = None
                    continue
                if not s.startswith("{"):
                    continue
                if section == "spell":
                    self._parse_spell_row(s)
                elif section == "effect":
                    self._parse_effect_row(s)

    def _parse_spell_row(self, s: str) -> None:
        m = _SPELL_ROW_RE.match(s)
        if not m:
            return
        name, spell_id = m.group(1), int(m.group(2))
        self.spell_rows += 1
        self.spell_aliases.setdefault(name, []).append(spell_id)
        if name not in self.spells:
            self.spells[name] = spell_id

    def _parse_effect_row(self, s: str) -> None:
        try:
            body = s[s.index("{") + 1 : s.rindex("}")]
        except ValueError:
            return
        tokens = _split_top_level(body)
        self.effect_rows += 1
        if len(tokens) < POS_TRIGGER_SPELL_ID:
            return
        try:
            effect_id = int(tokens[POS_ID - 1])
            spell_id = int(tokens[POS_SPELL_ID - 1])
            if spell_id == 0:
                return  # nil placeholder rows (612 in build 12.1.5.70448)
            file_index = int(tokens[POS_INDEX - 1])
            row = {
                "effect_id": effect_id,
                "spell_id": spell_id,
                "file_index": file_index,  # 0-based _index as stored in the file
                "type": int(tokens[POS_TYPE - 1]),
                "subtype": int(tokens[POS_SUBTYPE - 1]),
                "scaling_type": int(tokens[POS_SCALING_TYPE - 1]),
                "m_coeff": float(tokens[POS_M_COEFF - 1]),
                "m_delta": float(tokens[POS_M_DELTA - 1]),
                "sp_coeff": float(tokens[POS_SP_COEFF - 1]),
                "ap_coeff": float(tokens[POS_AP_COEFF - 1]),
                "amplitude": float(tokens[POS_AMPLITUDE - 1]),
                "radius": float(tokens[POS_RADIUS - 1]),
                "radius_max": float(tokens[POS_RADIUS_MAX - 1]),
                "base_value": float(tokens[POS_BASE_VALUE - 1]),
                "misc_value": int(tokens[POS_MISC_VALUE - 1]),
                "misc_value_2": int(tokens[POS_MISC_VALUE_2 - 1]),
                "trigger_spell_id": int(tokens[POS_TRIGGER_SPELL_ID - 1]),
            }
        except ValueError:
            return
        self.effects[(spell_id, file_index)] = row


# -- module-level API ---------------------------------------------------------

_DATA: Optional[SimcSpellData] = None


def load(path: Optional[str] = None) -> SimcSpellData:
    """Fetch (unless cached) and parse the spell data; cached in-process."""
    global _DATA
    if _DATA is None or (path is not None and path != _DATA.path):
        _DATA = SimcSpellData(path if path is not None else fetch())
    return _DATA


def _resolve_spell(data: SimcSpellData, spell_name: str) -> Tuple[str, int]:
    """Resolve a spell name to (canonical name, id); first occurrence wins."""
    if spell_name in data.spells:
        return spell_name, data.spells[spell_name]
    lowered = spell_name.lower()
    for name, spell_id in data.spells.items():
        if name.lower() == lowered:
            return name, spell_id
    close = difflib.get_close_matches(spell_name, list(data.spells), n=5)
    hint = f"; close matches: {close}" if close else ""
    raise KeyError(f"unknown spell {spell_name!r}{hint}")


def lookup(spell_name: str, effect_index: int) -> Dict[str, object]:
    """Return the parsed fields for one spell effect.

    ``effect_index`` is 1-based, matching SimC's ``effectN( idx )``; the file's
    0-based ``_index`` is ``effect_index - 1``.
    """
    if effect_index < 1:
        raise ValueError(f"effect_index is 1-based (SimC effectN); got {effect_index}")
    data = load()
    canonical, spell_id = _resolve_spell(data, spell_name)
    row = data.effects.get((spell_id, effect_index - 1))
    if row is None:
        available = sorted(i + 1 for sid, i in data.effects if sid == spell_id)
        raise KeyError(
            f"spell {spell_name!r} (id {spell_id}) has no effect {effect_index}; "
            f"available effect indices: {available}"
        )
    out = dict(row)
    out["spell_name"] = canonical
    out["effect_index"] = effect_index
    out["percent"] = out["base_value"] / 100.0  # spell_data_t::percent()
    return out


def stats() -> Dict[str, object]:
    """Parse statistics: spell/effect counts, declared counts, build, path."""
    data = load()
    return {
        "spell_count": len(data.spells),  # unique spell names
        "spell_row_count": data.spell_rows,  # total __spell_data rows
        "effect_count": len(data.effects),
        "effect_row_count": data.effect_rows,  # total __spelleffect_data rows
        "declared_spell_count": data.declared_spell_count,
        "declared_effect_count": data.declared_effect_count,
        "build": data.build,
        "path": data.path,
    }


# -- CLI ----------------------------------------------------------------------

_PRINT_ORDER = [
    "spell_name", "spell_id", "effect_index", "file_index", "effect_id",
    "type", "subtype", "scaling_type",
    "m_coeff", "m_delta", "sp_coeff", "ap_coeff",
    "amplitude", "radius", "radius_max",
    "base_value", "percent", "misc_value", "misc_value_2", "trigger_spell_id",
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Look up SimC spell-effect data (branch midnight)."
    )
    parser.add_argument("spell_name", help="spell name, e.g. 'Heart Strike'")
    parser.add_argument(
        "effect_index", type=int,
        help="1-based effect index (SimC effectN); file _index = effect_index - 1",
    )
    args = parser.parse_args(argv)

    try:
        row = lookup(args.spell_name, args.effect_index)
    except (KeyError, ValueError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {msg}", file=sys.stderr)
        return 1

    data = load()
    dupes = [
        i for i in data.spell_aliases.get(row["spell_name"], [])
        if i != row["spell_id"]
    ]
    if dupes:
        print(
            f"note: name {row['spell_name']!r} also matches spell ids {dupes} "
            f"(using first occurrence)"
        )
    for field in _PRINT_ORDER:
        print(f"{field:<16} {row[field]}")
    st = stats()
    print(
        f"parse stats: {st['spell_row_count']} spell rows "
        f"({st['spell_count']} unique names), {st['effect_count']} effects "
        f"({st['effect_row_count']} rows; declared "
        f"{st['declared_spell_count']}/{st['declared_effect_count']}), "
        f"build {st['build']}, source {st['path']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
