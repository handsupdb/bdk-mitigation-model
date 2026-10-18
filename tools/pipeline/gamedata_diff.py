#!/usr/bin/env python
"""Game-files (DBCache.bin hotfix) proposed-diff report generator (hand-review only).

Parses the live WoW hotfix cache ``DBCache.bin`` (outer XFTH container — see
``extracted/xfth_research.md`` for the verified format research), filters the
SpellEffect hotfix rows, and compares the hotfixed values against our workbook
through the SAME curated mapping ``tools/pipeline/simc_mapping.json`` used by
``simc_diff.py`` — spell resolution is identical (explicit ``spellId`` wins,
otherwise the spell name resolves to the first id in the SimC spell data), so
the SimC source and the game-files source always agree on the spell id. Writes
a hand-review report to ``extracted/gamedata_proposed_diffs.md`` and prints it
compactly. Nothing here edits ``game.json`` or any sheet.

DBCache.bin layout (XFTH v9, round-trip-verified against the live cache):

* 44-byte header ``<4sII32s``: magic ``XFTH``, u32 version, u32 build, 32-byte
  verify hash (never validated, as in SimC's own parser).
* Then flat entries until EOF. v9 entry header ``<4siiIIIIB3s`` (32 B): magic,
  i32 region_id, i32 index, u32 unique_id (push id), u32 sig (DB2 table hash),
  i32 record_id, u32 length, u8 state, 3 B pad — followed by ``length`` bytes
  of DB2 row data. Older containers: v8 ``<4siIIIIB3s`` (28 B, no region_id);
  v<8 and 9.1.0 ``<4siIIIB3s`` (24 B, no region_id/unique_id).

Entry states: 1 = ENABLED (the only rows used); 0 = DISABLED and 2 = REMOVED
(reported and skipped); 3/4 = observed in the wild with length 0, meaning
unknown (reported and skipped).

SpellEffect hotfix rows (sig 0xF04238A5) are key-block records: the row data
is the inline columns plus the 4-byte parent key SpellID appended LAST. The
inline layout is build-sensitive, so rows are decoded by record length:

* 136 B — build 68256 (12.0.7 Midnight), verified: 132 inline + 4 B SpellID;
* 134 B — 11.2.x: DifficultyID is i32, shifting offsets +2 after it;
* any other length is reported and skipped (re-derive from WDBD then).

mapping ``field`` (SimC spelleffect_data_t member) -> SpellEffect DB2 column
(field order in SimC's dbc_extract3 generator: coefficient->_m_coeff,
delta->_m_delta, bonus->_m_unk, sp_coefficient->_sp_coeff,
ap_coefficient->_ap_coeff; cross-verified empirically — cache
BonusCoefficientFromAP=1.0 == SimC ap_coeff=1.0 for Jadefire Stomp #1248815):

    ap_coeff   -> BonusCoefficientFromAP   (offset 60 in the 136 B layout)
    sp_coeff   -> EffectBonusCoefficient   (offset 24)
    m_coeff    -> Coefficient              (offset 68)
    base_value -> EffectBasePointsF        (offset 84)

The cache is an OVERLAY, not a full data source: it only carries rows Blizzard
hotfixed since the last full push, so a mapped spell being ``not-in-cache`` is
a normal outcome, not an error. A staleness warning is emitted whenever the
cache build differs from the installed build parsed from ``.build.info`` (the
retail row, Product ``wow``; the file lives at
``/Applications/World of Warcraft/.build.info`` — one level ABOVE ``_retail_``
— so both paths are tried).

Verdicts per mapping entry:

    match        our value and the hotfix value are within tolerance
                 (|our - hotfix| <= max(0.0005, 0.1% * |hotfix|));
    CHANGED     both present but beyond tolerance — a proposed diff to review;
    not-in-cache no enabled SpellEffect hotfix row for that spell+effect in
                 the cache overlay (or the spell/field could not be resolved
                 — the reason is shown);
    unmapped    a hotfix value exists but our cell is missing/unresolvable.

CLI:
    .venv/bin/python tools/pipeline/gamedata_diff.py
    .venv/bin/python tools/pipeline/gamedata_diff.py --cache /path/DBCache.bin
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from datetime import date
from typing import Dict, List, Optional, Tuple

try:  # package-style import (tools.pipeline) or direct script run
    from . import simc_data, simc_diff  # type: ignore
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import simc_data  # type: ignore
    import simc_diff  # type: ignore

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING_PATH = os.path.join(REPO_ROOT, "tools", "pipeline", "simc_mapping.json")
GAME_PATH = os.path.join(REPO_ROOT, "data", "wow-12.1", "game.json")
REPORT_PATH = os.path.join(REPO_ROOT, "extracted", "gamedata_proposed_diffs.md")
DEFAULT_CACHE = "/Applications/World of Warcraft/_retail_/Cache/ADB/enUS/DBCache.bin"
# .build.info sits one level ABOVE _retail_ on current installs; try the
# documented _retail_ path first, then the parent.
BUILD_INFO_CANDIDATES = [
    "/Applications/World of Warcraft/_retail_/.build.info",
    "/Applications/World of Warcraft/.build.info",
]

# SpellEffect DB2 table hash (verified in the live 12.0.7 cache via the
# consecutive-record-id / same-spell heuristic — see xfth_research.md §3).
SPELLEFFECT_SIG = 0xF04238A5

# Entry state byte -> label (SimC HotfixType: 0 DISABLED, 1 ENABLED, 2 REMOVED;
# 3/4 observed with length 0 — unknown).
STATE_LABELS = {0: "disabled", 1: "enabled", 2: "removed"}

# XFTH entry header per container version: struct format + size.
# v9: magic, region_id, index, unique_id, sig, record_id, length, state, pad
# v8: same without region_id; v<8 (and 9.1.0): no region_id/unique_id.
ENTRY_HEADERS = {
    9: ("<4siiIIIIB3s", 32),
    8: ("<4siIIIIB3s", 28),
    7: ("<4siIIIB3s", 24),
}

# SpellEffect hotfix row layouts keyed by record length (inline columns +
# the 4-byte parent key SpellID appended last). Offsets are little-endian
# positions inside the row data.
SPELLEFFECT_LAYOUTS = {
    136: {  # build 68256 (12.0.7) — verified against the live cache
        "EffectIndex": 4,
        "Effect": 8,
        "EffectBonusCoefficient": 24,
        "BonusCoefficientFromAP": 60,
        "PvpMultiplier": 64,
        "Coefficient": 68,
        "Variance": 72,
        "EffectBasePointsF": 84,
        "SpellID": 132,
    },
    134: {  # 11.2.x — DifficultyID i32 shifts offsets +2 after it
        "EffectIndex": 6,
        "Effect": 10,
        "EffectBonusCoefficient": 26,
        "BonusCoefficientFromAP": 62,
        "PvpMultiplier": 66,
        "Coefficient": 70,
        "Variance": 74,
        "EffectBasePointsF": 86,
        "SpellID": 130,
    },
}

# mapping `field` (SimC spelleffect_data_t member) -> SpellEffect DB2 column
SIMC_FIELD_TO_COLUMN = {
    "ap_coeff": "BonusCoefficientFromAP",
    "sp_coeff": "EffectBonusCoefficient",
    "m_coeff": "Coefficient",
    "base_value": "EffectBasePointsF",
}

# Integer (non-f32) columns in the layouts above.
_INT_COLUMNS = {"EffectIndex"}          # i32
_UINT_COLUMNS = {"Effect", "SpellID"}   # u32


# -- DBCache.bin (XFTH) parsing ------------------------------------------------


def parse_dbcache(path: str) -> dict:
    """Parse DBCache.bin: 44-byte XFTH header + flat entries until EOF."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 44:
        raise ValueError(
            f"{path}: {len(raw)} bytes — too small for an XFTH header (44 bytes)")
    magic, version, build, verify_hash = struct.unpack_from("<4sII32s", raw, 0)
    if magic != b"XFTH":
        raise ValueError(
            f"{path}: bad container magic {magic!r} (expected b'XFTH') — "
            "not a DBCache.bin hotfix cache")
    if version not in ENTRY_HEADERS:
        raise ValueError(
            f"{path}: unsupported XFTH container version {version} "
            f"(supported: 8, 9, and <=7)")
    fmt, size = ENTRY_HEADERS[version]
    unpack = struct.Struct(fmt).unpack_from
    off = 44
    entries: List[dict] = []
    while off < len(raw):
        if off + size > len(raw):
            raise ValueError(
                f"{path}: truncated entry header at offset {off} "
                f"({len(raw) - off} bytes left) — cache corrupt")
        fields = unpack(raw, off)
        if fields[0] != b"XFTH":
            raise ValueError(
                f"{path}: bad entry magic {fields[0]!r} at offset {off} — "
                "cache corrupt or the format changed")
        if version == 9:
            (_m, region_id, index, unique_id, sig, record_id,
             length, state, _pad) = fields
        elif version == 8:
            (_m, index, unique_id, sig, record_id, length, state, _pad) = fields
            region_id = None
        else:
            (_m, index, sig, record_id, length, state, _pad) = fields
            region_id = unique_id = None
        off += size
        if off + length > len(raw):
            raise ValueError(
                f"{path}: truncated entry data at offset {off} "
                f"(needs {length} bytes, {len(raw) - off} left) — cache corrupt")
        entries.append({
            "offset": off - size,
            "region_id": region_id, "index": index, "unique_id": unique_id,
            "sig": sig, "record_id": record_id, "state": state,
            "length": length, "data": raw[off:off + length],
        })
        off += length
    return {"path": path, "version": version, "build": build,
            "verify_hash": verify_hash, "entries": entries,
            "size": len(raw), "end_offset": off}


def state_label(state: int) -> str:
    return STATE_LABELS.get(state, "unknown")


def decode_spelleffect(entry: dict) -> dict:
    """Decode one enabled SpellEffect hotfix row by its record length."""
    layout = SPELLEFFECT_LAYOUTS.get(entry["length"])
    if layout is None:
        raise ValueError(
            f"unsupported SpellEffect row length {entry['length']} "
            f"(known layouts: {sorted(SPELLEFFECT_LAYOUTS)} B — re-derive "
            "offsets from WoWDBDefs if the build changed)")
    data = entry["data"]
    row: Dict[str, object] = {"record_id": entry["record_id"]}
    for column, offset in layout.items():
        if column in _INT_COLUMNS:
            row[column] = struct.unpack_from("<i", data, offset)[0]
        elif column in _UINT_COLUMNS:
            row[column] = struct.unpack_from("<I", data, offset)[0]
        else:
            row[column] = struct.unpack_from("<f", data, offset)[0]
    return row


def spelleffect_rows(cache: dict) -> dict:
    """Split SpellEffect entries by state; decode the enabled ones.

    Returns {"by_state": {label: [entries]}, "rows": [(spell_id, effect_index)
    -> decoded row], "decode_errors": [...], "layouts_used": set()}.
    """
    by_state: Dict[str, List[dict]] = {}
    rows: Dict[Tuple[int, int], dict] = {}
    decode_errors: List[str] = []
    superseded: List[str] = []
    layouts_used = set()
    for e in cache["entries"]:
        if e["sig"] != SPELLEFFECT_SIG:
            continue
        label = state_label(e["state"])
        by_state.setdefault(label, []).append(e)
        if label != "enabled":
            continue  # disabled/removed/unknown: reported, skipped
        try:
            row = decode_spelleffect(e)
        except ValueError as exc:
            decode_errors.append(f"record {e['record_id']}: {exc}")
            continue
        layouts_used.add(e["length"])
        key = (int(row["SpellID"]), int(row["EffectIndex"]))
        if key in rows:
            # the same spell+effect hotfixed more than once; entries are
            # appended chronologically, so the LAST one wins
            superseded.append(
                f"spell {key[0]} effect {key[1] + 1}: record "
                f"{rows[key]['record_id']} superseded by record "
                f"{row['record_id']}")
        rows[key] = row
    return {"by_state": by_state, "rows": rows,
            "decode_errors": decode_errors, "superseded": superseded,
            "layouts_used": layouts_used}


# -- spell resolution (same rule as simc_diff.resolve_simc_value) --------------


def resolve_spell_id(entry: dict) -> Tuple[Optional[int], Optional[str]]:
    """Resolve a mapping entry to a spell id.

    Identical to simc_diff.py's resolution so both sources agree: an explicit
    ``spellId`` wins; otherwise the spell name resolves to the FIRST id in
    the SimC spell data (simc_data._resolve_spell).
    """
    spell_id = entry.get("spellId")
    if spell_id is not None:
        try:
            return int(spell_id), None
        except (TypeError, ValueError):
            return None, f"mapping entry has a non-numeric spellId {spell_id!r}"
    name = entry.get("simcSpell") or entry.get("ability") or ""
    if not name:
        return None, "mapping entry has no simcSpell/ability/spellId"
    try:
        _canonical, sid = simc_data._resolve_spell(simc_data.load(), name)
    except KeyError as exc:
        msg = exc.args[0] if exc.args else str(exc)
        return None, f"spell name {name!r} unresolved: {msg}"
    return sid, None


def resolve_hotfix_value(entry: dict,
                         rows: Dict[Tuple[int, int], dict]) -> dict:
    """Resolve the hotfix-cache value for one mapping entry."""
    field = entry.get("field") or "ap_coeff"
    column = SIMC_FIELD_TO_COLUMN.get(field)
    if column is None:
        return {"value": None, "display": None,
                "error": f"unknown mapping field {field!r} (known: "
                         f"{', '.join(sorted(SIMC_FIELD_TO_COLUMN))})"}
    try:
        idx = int(entry["effectIndex"])
    except (KeyError, TypeError, ValueError):
        return {"value": None, "display": None,
                "error": "mapping entry has no usable effectIndex"}
    if idx < 1:
        return {"value": None, "display": None,
                "error": f"effectIndex is 1-based (SimC effectN); got {idx}"}
    spell_id, err = resolve_spell_id(entry)
    if spell_id is None:
        return {"value": None, "display": None, "error": err}
    # cache EffectIndex is the DB2 0-based _index = SimC effectN(idx) - 1
    row = rows.get((spell_id, idx - 1))
    if row is None:
        return {"value": None, "display": None,
                "error": f"no enabled SpellEffect hotfix row for spell "
                         f"{spell_id} effect {idx} in the cache overlay"}
    return {"value": float(row[column]),
            "display": f"spell {spell_id} effectN({idx}) {field} "
                       f"({column})", "error": None}


def evaluate_entry(entry: dict, game: dict,
                   rows: Dict[Tuple[int, int], dict]) -> dict:
    ability = entry.get("ability", "?")
    our_cell = entry.get("ourCell")
    if our_cell:
        our = simc_diff.resolve_our_value(game, our_cell)
    else:
        our = {"value": None, "source": "no ourCell (unmapped)",
               "formula": None, "sheet": None, "cell": None}
    hotfix = resolve_hotfix_value(entry, rows)
    if hotfix["value"] is None:
        verdict, delta = "not-in-cache", None
    elif our["value"] is None:
        verdict, delta = "unmapped", None
    else:
        verdict, delta = simc_diff.classify(our["value"], hotfix["value"])
    return {"ability": ability, "our_cell": our_cell, "our": our,
            "hotfix": hotfix, "verdict": verdict, "delta": delta,
            "note": entry.get("note")}


# -- installed build (.build.info) ---------------------------------------------


def parse_build_info(candidates: List[str]) -> Optional[dict]:
    """Parse the installed retail build from .build.info (Product 'wow')."""
    for path in candidates:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        if not lines:
            continue
        header = [col.split("!")[0].strip() for col in lines[0].split("|")]
        col = {name: i for i, name in enumerate(header)}
        rows = [ln.split("|") for ln in lines[1:]]
        row = None
        if "Product" in col:
            row = next((r for r in rows if len(r) > col["Product"]
                        and r[col["Product"]].strip() == "wow"), None)
        if row is None:  # fall back to the first well-formed row
            row = next((r for r in rows if len(r) == len(header)), None)
        if row is None:
            continue
        version = (row[col["Version"]].strip()
                   if "Version" in col and len(row) > col["Version"] else "")
        build = None
        tail = version.rsplit(".", 1)[-1] if version else ""
        if tail.isdigit():
            build = int(tail)
        return {"path": path, "version": version, "build": build}
    return None


def staleness(cache_build: int, info: Optional[dict]) -> dict:
    """Compare the cache build against the installed build."""
    if info is None:
        return {"verdict": "unknown",
                "detail": "no .build.info found (tried: "
                          + "; ".join(BUILD_INFO_CANDIDATES) + ")"}
    if info["build"] is None:
        return {"verdict": "unknown",
                "detail": f".build.info at {info['path']} has no parseable "
                          "Version/build"}
    installed = info["build"]
    if cache_build == installed:
        return {"verdict": "current",
                "detail": f"cache build {cache_build} == installed build "
                          f"{installed} ({info['version']})"}
    if cache_build < installed:
        return {"verdict": "STALE",
                "detail": f"cache build {cache_build} predates installed "
                          f"build {installed} ({info['version']}) — hotfix "
                          "values may lag the live game; log into WoW once "
                          "to refresh the cache"}
    return {"verdict": "NEWER",
            "detail": f"cache build {cache_build} is newer than installed "
                      f"build {installed} ({info['version']}) — unexpected; "
                      "the cache may be from another install"}


# -- report --------------------------------------------------------------------


def _spell_names() -> Dict[int, List[str]]:
    """spell id -> SimC spell names (for annotating cache coverage)."""
    names: Dict[int, List[str]] = {}
    for name, ids in simc_data.load().spell_aliases.items():
        for sid in ids:
            names.setdefault(sid, []).append(name)
    return names


def build_report(cache: dict, se: dict, rows: List[dict], stal: dict,
                 info: Optional[dict], mapping_path: str,
                 report_path: str) -> str:
    n_match = sum(1 for r in rows if r["verdict"] == "match")
    n_changed = sum(1 for r in rows if r["verdict"] == "CHANGED")
    n_nic = sum(1 for r in rows if r["verdict"] == "not-in-cache")
    n_unmapped = sum(1 for r in rows if r["verdict"] == "unmapped")

    by_state = se["by_state"]
    state_bits = ", ".join(
        f"{len(v)} {k}" for k, v in sorted(by_state.items(),
                                           key=lambda kv: -len(kv[1])))
    eof_ok = cache["end_offset"] == cache["size"]
    eof_txt = ("parsed to exact EOF" if eof_ok
               else "PARSE ENDED EARLY — SUSPICIOUS")

    lines: List[str] = []
    lines.append("# Game-files (DBCache.bin hotfix) proposed diffs — "
                 "hand-review report")
    lines.append("")
    lines.append(f"- Generated {date.today().isoformat()} by "
                 f"`tools/pipeline/gamedata_diff.py` from "
                 f"`{os.path.relpath(mapping_path, REPO_ROOT)}`")
    lines.append(f"- Hotfix cache: `{cache['path']}` — XFTH v{cache['version']}, "
                 f"**build {cache['build']}**, {len(cache['entries'])} entries, "
                 f"{cache['size']:,} B ({eof_txt})")
    lines.append("- Our workbook: `data/wow-12.1/game.json` (cellLiterals) + "
                 "`extracted/<Sheet>__values.tsv` / `__formulas.tsv` "
                 "(same value sources as `simc_diff.py`)")
    lines.append(f"- Match tolerance: |our − hotfix| ≤ max("
                 f"{simc_diff.ABS_TOL}, {simc_diff.REL_TOL:.1%} × |hotfix|)")
    lines.append("")
    lines.append("> **PROPOSALS ONLY — never auto-apply.** This report exists "
                 "for hand review; no tool writes these values back into "
                 "`game.json` or any sheet. Every CHANGED line must be "
                 "verified by a human before any edit is made.")
    lines.append(">")
    lines.append("> The cache is an **overlay**: it only carries rows Blizzard "
                 "hotfixed since the last full data push, so `not-in-cache` "
                 "is a normal verdict, not an error. Base values for "
                 "non-hotfixed spells come from the full DB2/SimC data "
                 "(`simc_diff.py`), not from this cache.")
    lines.append("")

    # staleness
    lines.append("## Cache staleness")
    lines.append("")
    if info:
        lines.append(f"- Installed build (`.build.info`, retail row Product "
                     f"`wow`): **{info['build']}** ({info['version']}) — "
                     f"`{info['path']}`")
    lines.append(f"- Cache build: **{cache['build']}**")
    warn = stal["verdict"] in ("STALE", "NEWER")
    lines.append(f"- Verdict: **{stal['verdict']}** — {stal['detail']}")
    if warn:
        lines.append("")
        lines.append(f"> **STALENESS WARNING:** {stal['detail']} Treat every "
                     "value below as provisional until the cache is "
                     "refreshed in-game and this report is re-run.")
    lines.append("")

    # SpellEffect section
    lines.append("## SpellEffect hotfix rows "
                 f"(sig 0x{SPELLEFFECT_SIG:08X})")
    lines.append("")
    lines.append(f"- Entries by state: {state_bits}.")
    for label in ("disabled", "removed", "unknown"):
        entries = by_state.get(label, [])
        if entries:
            ids = ", ".join(str(e["record_id"]) for e in entries[:12])
            more = "" if len(entries) <= 12 else f" (+{len(entries) - 12} more)"
            why = {"disabled": "state 0 — reported and skipped",
                   "removed": "state 2 — reported and skipped",
                   "unknown": "states 3/4 — unknown, reported and skipped"}[label]
            lines.append(f"- {label}: record ids {ids}{more} ({why}).")
    enabled = by_state.get("enabled", [])
    lines.append(f"- Enabled rows decoded: {len(se['rows'])} unique spell+effect "
                 f"keys from {len(enabled)} entries (layouts used: "
                 f"{', '.join(f'{n} B' for n in sorted(se['layouts_used']))}).")
    if se["superseded"]:
        lines.append("- Superseded duplicate hotfixes (entries are appended "
                     "chronologically, so the LAST entry in file order wins): "
                     + "; ".join(se["superseded"]) + ".")
    if se["decode_errors"]:
        lines.append(f"- Decode errors (skipped): "
                     f"{'; '.join(se['decode_errors'])}")
    spells = sorted({sid for sid, _idx in se["rows"]})
    lines.append(f"- Distinct hotfixed spells: {len(spells)}.")
    lines.append("")

    # coverage
    lines.append("### Hotfix coverage (what the cache DOES touch)")
    lines.append("")
    names = _spell_names()
    per_spell: Dict[int, List[int]] = {}
    for sid, idx in se["rows"]:
        per_spell.setdefault(sid, []).append(idx)
    lines.append("| SpellID | SimC name (12.1.5) | hotfixed EffectIndex (0-based) |")
    lines.append("|---|---|---|")
    for sid in spells:
        name = ", ".join(sorted(set(names.get(sid, [])))) or "— (not in SimC data)"
        idxs = ", ".join(str(i) for i in sorted(per_spell[sid]))
        lines.append(f"| {sid} | {name} | {idxs} |")
    lines.append("")

    # verdicts
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| Ability | Our cell | Our value | Hotfix value | Δ (our−hotfix) "
                 "| Hotfix source | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        our_val = simc_diff.fmt(r["our"]["value"])
        if r["our"]["formula"]:
            our_val += f" (`{r['our']['formula']}`)"
        hot_val = simc_diff.fmt(r["hotfix"]["value"])
        if r["hotfix"]["value"] is None and r["hotfix"]["error"]:
            hot_val = f"— ({r['hotfix']['error']})"
        lines.append(
            f"| {r['ability']} | {r['our_cell'] or '—'} | {our_val} "
            f"| {hot_val} | {simc_diff.fmt_delta(r['delta'])} "
            f"| {r['hotfix']['display'] or '—'} | {r['verdict']} |")
    lines.append("")

    # CHANGED
    lines.append("## CHANGED — proposed diffs (hand-verify before any edit)")
    lines.append("")
    changed = [r for r in rows if r["verdict"] == "CHANGED"]
    if changed:
        for r in changed:
            lines.append(
                f"- **{r['ability']}**: our {r['our_cell']} "
                f"{simc_diff.fmt(r['our']['value'])} → hotfix "
                f"{simc_diff.fmt(r['hotfix']['value'])} "
                f"({r['hotfix']['display']}); Δ "
                f"{simc_diff.fmt_delta(r['delta'])}.")
    else:
        lines.append("None — no mapped value deviates from the hotfix cache "
                     "(or nothing mapped is hotfixed).")
    lines.append("")

    # not-in-cache / unmapped
    lines.append("## not-in-cache / unmapped entries (no proposed diff)")
    lines.append("")
    rest = [r for r in rows if r["verdict"] in ("not-in-cache", "unmapped")]
    if rest:
        for r in rest:
            why = r["hotfix"]["error"] or "no enabled hotfix row"
            our_txt = (f"our {r['our_cell']} "
                       f"{simc_diff.fmt(r['our']['value'])}"
                       if r["our"]["value"] is not None
                       else "our value unresolvable"
                       + (f" ({r['our']['source']})" if not r["our_cell"] else ""))
            lines.append(f"- **{r['ability']}** — {why}. {our_txt}.")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- {len(rows)} mapping entries: {n_match} match, "
                 f"{n_changed} CHANGED, {n_nic} not-in-cache, "
                 f"{n_unmapped} unmapped.")
    lines.append(f"- Cache: build {cache['build']}, "
                 f"{len(cache['entries'])} entries, {len(se['rows'])} enabled "
                 f"SpellEffect rows over {len(spells)} spells; staleness: "
                 f"{stal['verdict']}.")
    lines.append(f"- Deviations beyond tolerance: "
                 + (", ".join(r["ability"] for r in changed) if changed
                    else "none") + ".")
    lines.append("")
    return "\n".join(lines)


def print_compact(cache: dict, se: dict, rows: List[dict], stal: dict,
                  report_path: str) -> None:
    eof_ok = cache["end_offset"] == cache["size"]
    print(f"DBCache.bin: XFTH v{cache['version']}, build {cache['build']}, "
          f"{len(cache['entries'])} entries, {cache['size']:,} B"
          + (" — exact EOF" if eof_ok else " — ENDED EARLY (suspicious)"))
    print(f"staleness: {stal['verdict']} — {stal['detail']}")
    by_state = se["by_state"]
    bits = ", ".join(f"{len(v)} {k}" for k, v in
                     sorted(by_state.items(), key=lambda kv: -len(kv[1])))
    print(f"SpellEffect 0x{SPELLEFFECT_SIG:08X}: {bits}; "
          f"{len(se['rows'])} unique spell+effect keys from "
          f"{len(by_state.get('enabled', []))} enabled entries"
          + (f"; {len(se['superseded'])} superseded (last wins)"
             if se["superseded"] else ""))
    for r in rows:
        our = simc_diff.fmt(r["our"]["value"]) \
            if r["our"]["value"] is not None else "—"
        if r["our_cell"]:
            our = f"{r['our_cell']} our {our}"
        hot = simc_diff.fmt(r["hotfix"]["value"]) \
            if r["hotfix"]["value"] is not None else "—"
        if r["hotfix"]["display"]:
            hot += f" ({r['hotfix']['display']})"
        extra = ""
        if r["verdict"] == "not-in-cache" and r["hotfix"]["error"]:
            extra = f" ({str(r['hotfix']['error'])[:70]})"
        print(f"{r['ability']:<15} | {our} | hotfix {hot} | "
              f"{r['verdict']}{extra}")
    n_match = sum(1 for r in rows if r["verdict"] == "match")
    n_changed = sum(1 for r in rows if r["verdict"] == "CHANGED")
    n_nic = sum(1 for r in rows if r["verdict"] == "not-in-cache")
    n_unmapped = sum(1 for r in rows if r["verdict"] == "unmapped")
    print(f"— {len(rows)} entries: {n_match} match, {n_changed} CHANGED, "
          f"{n_nic} not-in-cache, {n_unmapped} unmapped | report: "
          f"{os.path.relpath(report_path, REPO_ROOT)}")


# -- CLI ------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the DBCache.bin (hotfix) proposed-diff "
                    "hand-review report.")
    parser.add_argument("--cache", default=DEFAULT_CACHE,
                        help="DBCache.bin to parse (default: %(default)s)")
    parser.add_argument("--build-info", default=None,
                        help=".build.info for the staleness check (default: "
                             "try " + " then ".join(BUILD_INFO_CANDIDATES))
    parser.add_argument("--mapping", default=MAPPING_PATH,
                        help="curated mapping JSON (default: %(default)s)")
    parser.add_argument("--game", default=GAME_PATH,
                        help="our game.json (default: %(default)s)")
    parser.add_argument("--report", default=REPORT_PATH,
                        help="report to write (default: %(default)s)")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.cache):
        print(f"error: hotfix cache not found: {args.cache}\n"
              "  (default is the live retail cache; pass --cache /path/to/"
              "DBCache.bin to override; the file only exists after WoW has "
              "downloaded hotfix data on this machine)",
              file=sys.stderr)
        return 1
    try:
        cache = parse_dbcache(args.cache)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    candidates = [args.build_info] if args.build_info else BUILD_INFO_CANDIDATES
    info = parse_build_info(candidates)
    stal = staleness(cache["build"], info)

    with open(args.mapping, encoding="utf-8") as fh:
        mapping = json.load(fh)
    if not isinstance(mapping, list):
        print(f"error: mapping {args.mapping} is not a JSON list",
              file=sys.stderr)
        return 1

    se = spelleffect_rows(cache)
    game = simc_diff.load_game(args.game)
    rows = [evaluate_entry(entry, game, se["rows"]) for entry in mapping]

    report = build_report(cache, se, rows, stal, info, args.mapping,
                          args.report)
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(report)
    print_compact(cache, se, rows, stal, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
