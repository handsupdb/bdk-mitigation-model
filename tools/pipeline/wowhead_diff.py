#!/usr/bin/env python
"""Wowhead proposed-diff report generator (talent trees + spell tooltips).

Compares our workbook's talent index (``data/wow-12.1/game.json``
``index.talents`` — 102 talents keyed by name + tree) against Wowhead's live
modern talent-calc data (12.1.5-era, ``nether.wowhead.com/data/
talents-dragonflight``, cached at ``extracted/wowhead_talents.js``), writes a
hand-review report to ``extracted/wowhead_proposed_diffs.md`` and prints it
compactly. Nothing here edits ``game.json`` or any sheet — every line is a
*proposal* for a human to verify. (www.wowhead.com is WAF-blocked for curl;
nether endpoints need no UA — see extracted/wowhead_research.md.)

Tree discovery — all from the Wowhead payload, no hardcoded tree ids:
  * class tree  : the playerClass 6 (Death Knight), type 1 tree (id 6);
  * Blood spec  : the class's type 2 tree whose spec id resolves through
                  ``specGuides`` + ``guideURLs`` to a ``/classes/<class>/blood/``
                  guide URL (id 250; falls back to 250 with a warning);
  * hero trees  : the class's type 3 trees with any node's ``shownForSpecs``
                  containing the Blood spec id (Deathbringer 65569, San'layn
                  65567). This is the same signal Wowhead's own talent-calc JS
                  uses (TalentCalcDragonflight.js filters hero trees by node
                  ``shownForSpecs``); do NOT rely on ``heroTreeChoices`` key
                  order — its spec-node keys are not spec ids and their order
                  is not spec-id order (verified: warrior/paladin descend,
                  hunter does not).

Payload layout (``WH.setPageData("wow.talentCalcDragonflight.live.X", <json>)``
blocks; ``trees`` is 1.46 MB): ``trees[id]`` has ``playerClass``, ``type``
(1=class, 2=spec, 3=hero), ``name`` (hero trees only), ``checkpoints`` and
``talents`` — a dict of grid ``cell`` -> list of node entries with ``node``,
``type`` (1=active, 2=passive, 3=choice, 5=capstone), ``requiredPoints``,
``requires``/``requiresNodes`` (tree links), ``requiredLevel``,
``defaultSpecs``, hero-tree ``shownForSpecs``, and ``spells`` (per-rank
entries: ``spell``, ``definition``, ``name``, ``points``,
``descriptionSearch`` — plain-text tooltip description including
coefficients — ``hasRankDescription``).

Report sections:
  (a) Wowhead 12.1.5 nodes NOT in our index, split into two categories:
      * known-unmodeled — on the curated list
        ``tools/pipeline/wowhead_known_unmodeled.json``: talents present in
        the Wowhead trees but not modeled in our Inputs sheet. Our Inputs
        sheet only lists the build-SELECTED hero talents, so the rest of the
        hero trees always looked "new" — that index artifact is tracked in
        the list (and reported as expected noise), keeping NEW clean.
      * NEW — genuinely new/renamed nodes (review). A node matches when ANY
        of its spell names is in our index for that tree; unmatched choice
        options inside matched nodes are listed separately.
  (b) our index talents NOT in the Wowhead trees (removed/renamed); names
      absent from the entire payload (all classes) are flagged as likely
      removed/renamed; entries on the list's removed_known section (e.g.
      Death's Bargain) are marked removed-known.
  (c) per-rank values for matched multi-rank talents (``points`` > 1) —
      best-effort and TEXT-DERIVED: the per-rank arrays from the base spell's
      ``/tooltip/spell/{id}?locale=0`` JSON ``spells`` field where
      ``spellModifiers`` maps the talent to a base spell (e.g. Vampiric Blood
      55233 -> {"317133": [["30","35",""], ["10 sec","12 sec",""]]}), plus the
      node's ``descriptionSearch`` rank text (which carries both ranks' values
      for ``hasRankDescription`` spells). Rank indexing in the ``spells``
      arrays is ambiguous (slot 0 may be the unmodified value), so both
      signals are shown for human interpretation. Our workbook stores talent
      point allocations (``Inputs!C/D``), not per-rank values, so no
      12.1-vs-12.1.5 value comparison is possible — treat (c) as reference
      data and verify numbers against SimC before editing anything.

CLI:
    .venv/bin/python tools/pipeline/wowhead_diff.py
    .venv/bin/python tools/pipeline/wowhead_diff.py --refresh   # re-download
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from typing import Dict, FrozenSet, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_PATH = os.path.join(REPO_ROOT, "extracted", "wowhead_talents.js")
GAME_PATH = os.path.join(REPO_ROOT, "data", "wow-12.1", "game.json")
REPORT_PATH = os.path.join(REPO_ROOT, "extracted", "wowhead_proposed_diffs.md")
KNOWN_UNMODELED_PATH = os.path.join(
    REPO_ROOT, "tools", "pipeline", "wowhead_known_unmodeled.json")
TALENTS_URL = "https://nether.wowhead.com/data/talents-dragonflight?dv=41&db=1791976965"
TOOLTIP_URL = "https://nether.wowhead.com/tooltip/spell/{spell_id}?locale=0"
MIN_CACHE_BYTES = 1_000_000  # a cached copy larger than this is trusted

PLAYER_CLASS = 6              # Death Knight
DEFAULT_BLOOD_SPEC_ID = 250   # fallback if guide-URL discovery fails
CLASS_TREE_TYPE = 1
SPEC_TREE_TYPE = 2
HERO_TREE_TYPE = 3
NODE_TYPE_LABELS = {1: "active", 2: "passive", 3: "choice", 5: "capstone"}

_PAGE_DATA_RE = re.compile(r'WH\.setPageData\("([^"]+)",')
_GUIDE_BLOOD_RE = re.compile(r"/classes/[^/]+/blood(?:/|$)")

_TOOLTIP_CACHE: Dict[int, Optional[dict]] = {}


# -- fetch / parse -------------------------------------------------------------


def fetch(refresh: bool = False) -> str:
    """Download talents-dragonflight to CACHE_PATH unless a >1 MB copy exists."""
    if (
        not refresh
        and os.path.isfile(CACHE_PATH)
        and os.path.getsize(CACHE_PATH) > MIN_CACHE_BYTES
    ):
        return CACHE_PATH
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    subprocess.run(["curl", "-sSL", "-o", CACHE_PATH, TALENTS_URL], check=True)
    if not (os.path.isfile(CACHE_PATH) and os.path.getsize(CACHE_PATH) > MIN_CACHE_BYTES):
        raise RuntimeError(f"downloaded {CACHE_PATH} is unexpectedly small")
    return CACHE_PATH


def load_page_data(path: str) -> Dict[str, object]:
    """Parse the WH.setPageData("wow.talentCalcDragonflight.live.X", <json>) blocks."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    decoder = json.JSONDecoder()
    parts = _PAGE_DATA_RE.split(raw)
    # parts = [preamble, key, body, key, body, ...]; each body ends with ");"
    page: Dict[str, object] = {}
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].rsplit(".", 1)[-1]  # wow.talentCalcDragonflight.live.trees
        body = parts[i + 1].lstrip()
        try:
            page[key], end = decoder.raw_decode(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"cannot parse WH.setPageData block {key!r}: {exc}")
        rest = body[end:].strip()
        if rest and rest != ");":
            raise RuntimeError(
                f"unexpected trailing content in block {key!r}: {rest[:40]!r}")
    return page


def fetch_tooltip(spell_id: int) -> Optional[dict]:
    """Fetch one /tooltip/spell JSON (cached per run); None on failure."""
    if spell_id not in _TOOLTIP_CACHE:
        try:
            proc = subprocess.run(
                ["curl", "-sSL", TOOLTIP_URL.format(spell_id=spell_id)],
                capture_output=True, text=True, check=True, timeout=30)
            _TOOLTIP_CACHE[spell_id] = json.loads(proc.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError):
            _TOOLTIP_CACHE[spell_id] = None
    return _TOOLTIP_CACHE[spell_id]


# -- tree discovery ------------------------------------------------------------


def tree_nodes(tree: dict) -> List[dict]:
    """Flat node list of one tree, ordered by numeric cell then list order."""
    cells = tree.get("talents", {})
    def cell_key(cell: str) -> Tuple[int, str]:
        return (int(cell) if cell.isdigit() else 0, cell)
    nodes: List[dict] = []
    for cell in sorted(cells, key=cell_key):
        nodes.extend(cells[cell])
    return nodes


def _guide_url(page: dict, spec_id: int) -> Optional[str]:
    guides = {g["specid"]: g["id"] for g in page.get("specGuides", [])}
    gid = guides.get(spec_id)
    if gid is None:
        return None
    return page.get("guideURLs", {}).get(str(gid))


def _slug_title(slug: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in slug.split("-"))


def discover_trees(page: dict) -> Tuple[dict, dict, List[dict], List[str]]:
    """Return (class_tree, blood_spec_tree, hero_trees, notes) for Blood DK."""
    notes: List[str] = []
    trees: List[dict] = page["trees"]
    class_trees = [t for t in trees
                   if t.get("playerClass") == PLAYER_CLASS and t.get("type") == CLASS_TREE_TYPE]
    if len(class_trees) != 1:
        raise RuntimeError(f"expected one class tree for playerClass {PLAYER_CLASS}, "
                            f"found {len(class_trees)}")
    class_tree = class_trees[0]

    spec_trees = [t for t in trees
                  if t.get("playerClass") == PLAYER_CLASS and t.get("type") == SPEC_TREE_TYPE]
    blood = None
    blood_url = None
    class_label = "Death Knight"
    for t in spec_trees:
        url = _guide_url(page, t["id"])
        if url and _GUIDE_BLOOD_RE.search(url):
            blood, blood_url = t, url
            break
    if blood is None:
        blood = next((t for t in spec_trees if t["id"] == DEFAULT_BLOOD_SPEC_ID), None)
        if blood is None:
            raise RuntimeError("cannot discover the Blood spec tree "
                               f"(tried {len(spec_trees)} spec trees)")
        notes.append(f"guide-URL discovery failed; fell back to spec id "
                     f"{DEFAULT_BLOOD_SPEC_ID}")
    else:
        parts = blood_url.split("/")
        # /guide/classes/<class-slug>/<spec-slug>/...
        class_label = _slug_title(parts[3]) if len(parts) > 4 else "Death Knight"
        notes.append(f"Blood spec id {blood['id']} via guide URL {blood_url}")

    heroes = []
    for t in trees:
        if t.get("playerClass") != PLAYER_CLASS or t.get("type") != HERO_TREE_TYPE:
            continue
        if any(blood["id"] in n.get("shownForSpecs", []) for n in tree_nodes(t)):
            heroes.append(t)
    if not heroes:
        raise RuntimeError(f"no hero trees with shownForSpecs containing "
                            f"spec {blood['id']}")
    notes.append("hero trees via node shownForSpecs: "
                 + ", ".join(f"{t['name']} {t['id']}" for t in heroes))
    return class_tree, blood, heroes, notes


# -- diff ----------------------------------------------------------------------


def reverse_spell_modifiers(page: dict) -> Dict[int, List[int]]:
    """{modifier spell id: [base spell ids]} from spellModifiers."""
    rev: Dict[int, List[int]] = {}
    for base, mods in (page.get("spellModifiers") or {}).items():
        for mod in mods or []:
            try:
                rev.setdefault(int(mod), []).append(int(base))
            except (TypeError, ValueError):
                continue
    return rev


def per_rank_progression(spell_id: int, base_ids: List[int]) -> Tuple[Optional[str], str]:
    """(formatted per-rank progression or None, source label) from the base
    spell's tooltip `spells` field, e.g. '30 -> 35; 10 sec -> 12 sec'."""
    for base in base_ids:
        tip = fetch_tooltip(base)
        if not tip:
            continue
        rows = (tip.get("spells") or {}).get(str(spell_id))
        if not rows:
            continue
        parts = []
        for row in rows:
            vals = [str(v) for v in row if str(v).strip()]
            if len(vals) >= 2:
                parts.append(" -> ".join(vals))
        if parts:
            return ("; ".join(parts),
                    f"{tip.get('name')} ({base}) tooltip `spells` field")
    return None, ""


def load_known_unmodeled(path: str = KNOWN_UNMODELED_PATH
                         ) -> Tuple[FrozenSet[Tuple[str, str]],
                                    FrozenSet[Tuple[str, str]]]:
    """(known_unmodeled, removed_known) sets of (name, tree) pairs from the
    curated list of talents present in the Wowhead 12.1.5 trees but not
    modeled in our Inputs sheet (plus our index names already known to be
    absent from the Wowhead trees). See the JSON's note field."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    unmodeled = frozenset(
        (e["name"], e["tree"]) for e in data.get("unmodeled", []))
    removed_known = frozenset(
        (e["name"], e["tree"]) for e in data.get("removed_known", []))
    return unmodeled, removed_known


def analyze_tree(tree: dict, label: str, our_names: List[str],
                 known_unmodeled: FrozenSet[Tuple[str, str]] = frozenset(),
                 removed_known: FrozenSet[Tuple[str, str]] = frozenset()) -> dict:
    """Name-match one Wowhead tree against our index talents for that tree.

    A node with no name in our index is known-unmodeled when every spell
    name is on the known_unmodeled list for this tree (expected — not
    modeled in our Inputs sheet), else NEW (genuinely new/renamed — review).
    Removed entries on the removed_known list are reported as removed_known
    in addition to removed.
    """
    our = set(our_names)
    nodes = tree_nodes(tree)
    wh_names: set = set()
    matched: List[dict] = []
    known_unmodeled_nodes: List[dict] = []
    new_nodes: List[dict] = []
    unmatched_options: List[dict] = []
    multi_rank: List[dict] = []
    for n in nodes:
        spells = n.get("spells", [])
        names = [s.get("name", "") for s in spells]
        wh_names.update(names)
        entry = {"node": n.get("node"), "cell": n.get("cell"),
                 "type": NODE_TYPE_LABELS.get(n.get("type"), f"type{n.get('type')}"),
                 "names": names}
        hits = [x for x in names if x in our]
        if hits:
            matched.append(entry)
            miss = [x for x in names if x not in our]
            if miss:
                unmatched_options.append(dict(entry, unmatched=miss, matched=hits))
        elif names and all((x, label) in known_unmodeled for x in names):
            known_unmodeled_nodes.append(entry)
        else:
            new_nodes.append(entry)
        for s in spells:
            try:
                points = int(s.get("points") or 1)
            except (TypeError, ValueError):
                points = 1
            if s.get("name") in our and points > 1:
                multi_rank.append({
                    "name": s.get("name"), "spell": s.get("spell"), "points": points,
                    "rank_text": (s.get("descriptionSearch") or "").strip()})
    return {
        "label": label, "wh_id": tree.get("id"), "wh_type": tree.get("type"),
        "node_count": len(nodes), "wh_spell_count": len(wh_names),
        "wh_spell_names": wh_names, "our_count": len(our_names),
        "matched_nodes": matched, "known_unmodeled_nodes": known_unmodeled_nodes,
        "new_nodes": new_nodes,
        "unmatched_options": unmatched_options, "multi_rank": multi_rank,
        "removed": sorted(our - wh_names),
        "removed_known": sorted(
            n for n in (our - wh_names) if (n, label) in removed_known),
    }


def build_diff(page: dict, game: dict,
               known: Optional[Tuple[FrozenSet[Tuple[str, str]],
                                     FrozenSet[Tuple[str, str]]]] = None) -> dict:
    """Run the full tree discovery + name match; returns the report model.

    known: optional (known_unmodeled, removed_known) (name, tree) sets;
    loaded from KNOWN_UNMODELED_PATH when omitted.
    """
    if known is None:
        known = load_known_unmodeled()
    known_unmodeled, removed_known = known
    class_tree, blood, heroes, notes = discover_trees(page)
    our_by_tree: Dict[str, List[str]] = {}
    for t in game["index"]["talents"]:
        our_by_tree.setdefault(t["tree"], []).append(t["name"])

    results = [analyze_tree(class_tree, "Death Knight",
                            our_by_tree.get("Death Knight", []),
                            known_unmodeled, removed_known),
               analyze_tree(blood, "Blood", our_by_tree.get("Blood", []),
                            known_unmodeled, removed_known)]
    for t in heroes:
        results.append(analyze_tree(t, t.get("name") or f"hero-{t['id']}",
                                    our_by_tree.get(t.get("name") or "", []),
                                    known_unmodeled, removed_known))

    # every spell name in the whole payload (all classes), for (b) flags
    everywhere: set = set()
    for t in page["trees"]:
        for n in tree_nodes(t):
            for s in n.get("spells", []):
                everywhere.add(s.get("name", ""))

    rev = reverse_spell_modifiers(page)
    for res in results:
        for e in res["multi_rank"]:
            prog, src = per_rank_progression(e["spell"], rev.get(e["spell"], []))
            e["progression"], e["source"] = prog, src
        for name in res["removed"]:
            res.setdefault("removed_absent_everywhere", {})[name] = name not in everywhere

    return {"trees": results, "notes": notes,
            "our_total": len(game["index"]["talents"])}


# -- report --------------------------------------------------------------------


def _quote(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return f'"{text}"' + ("…" if len(text) > limit else "")


def build_report(diff: dict) -> str:
    trees = diff["trees"]
    tot = lambda key: sum(t[key] for t in trees)  # noqa: E731
    lines: List[str] = []
    lines.append("# Wowhead proposed diffs — talent trees (hand-review only)")
    lines.append("")
    lines.append(f"_Generated {date.today().isoformat()} by "
                 "`tools/pipeline/wowhead_diff.py`. Wowhead live talent-calc data "
                 f"(`{TALENTS_URL}`, cached at "
                 "`extracted/wowhead_talents.js`) vs our 12.1 workbook talent "
                 f"index (`data/wow-12.1/game.json` index.talents, "
                 f"{diff['our_total']} talents). Nothing here edits game.json — "
                 "every line is a proposal for human review._")
    lines.append("")
    lines.append("## Tree discovery (from the Wowhead payload)")
    lines.append("")
    for res, t in zip(trees, ("class", "spec", "hero", "hero")):
        lines.append(f"- {res['label']} — tree id {res['wh_id']} ({t}, "
                      f"{res['node_count']} nodes)")
    for note in diff["notes"]:
        lines.append(f"- {note}")
    lines.append("- Node types: 1=active, 2=passive, 3=choice, 5=capstone.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| tree | WH id | kind | WH nodes | WH spell names | ours | "
                 "matched nodes | known-unmodeled | NEW nodes | removed ours |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    kinds = ("class", "spec", "hero", "hero")
    for res, kind in zip(trees, kinds):
        lines.append(f"| {res['label']} | {res['wh_id']} | {kind} | "
                     f"{res['node_count']} | {res['wh_spell_count']} | {res['our_count']} | "
                     f"{len(res['matched_nodes'])} | "
                     f"{len(res['known_unmodeled_nodes'])} | {len(res['new_nodes'])} | "
                     f"{len(res['removed'])} |")
    lines.append(f"| **total** | | | **{tot('node_count')}** | "
                 f"**{tot('wh_spell_count')}** | **{tot('our_count')}** | "
                 f"**{sum(len(t['matched_nodes']) for t in trees)}** | "
                 f"**{sum(len(t['known_unmodeled_nodes']) for t in trees)}** | "
                 f"**{sum(len(t['new_nodes']) for t in trees)}** | "
                 f"**{sum(len(t['removed']) for t in trees)}** |")
    lines.append("")

    lines.append("## (a) Wowhead 12.1.5 nodes NOT in our index")
    lines.append("")
    any_known = False
    for res in trees:
        if not res["known_unmodeled_nodes"]:
            continue
        any_known = True
        lines.append(f"### known-unmodeled — {res['label']} — "
                     f"{len(res['known_unmodeled_nodes'])} node(s)")
        lines.append("")
        for e in res["known_unmodeled_nodes"]:
            lines.append(f"- cell {e['cell']}, node {e['node']}, {e['type']} — "
                         + " / ".join(e["names"]))
        lines.append("")
    if any_known:
        lines.append("known-unmodeled = on the curated list "
                     "`tools/pipeline/wowhead_known_unmodeled.json` — present in "
                     "the Wowhead trees, not modeled in our Inputs sheet (our "
                     "Inputs sheet only lists the build-SELECTED hero talents). "
                     "Expected index artifact, not a 12.1.5 change.")
        lines.append("")
    any_new = False
    for res in trees:
        if not res["new_nodes"]:
            continue
        any_new = True
        lines.append(f"### NEW — {res['label']} — {len(res['new_nodes'])} node(s)")
        lines.append("")
        for e in res["new_nodes"]:
            lines.append(f"- cell {e['cell']}, node {e['node']}, {e['type']} — "
                         + " / ".join(e["names"]))
        lines.append("")
    if not any_new:
        lines.append("### NEW — genuinely new/renamed (review)")
        lines.append("")
        if any_known:
            lines.append("None — every node not in our index is known-unmodeled "
                        "(see above).")
        else:
            lines.append("None — every node in all four trees matched our index "
                        "by name.")
        lines.append("")
    opts = [e for res in trees for e in res["unmatched_options"]]
    if opts:
        lines.append("Unmatched choice options inside matched nodes (the other "
                     "option is in our index):")
        lines.append("")
        for e in opts:
            lines.append(f"- {e['names'][0] if len(e['names']) == 1 else ' / '.join(e['unmatched'])}"
                         f" ({e['type']}, {e['node']}) — node options: "
                         + " / ".join(e["names"]))
        lines.append("")
    lines.append("CAVEAT: our hero-tree index only covers the talents the current "
                 "build selects, so hero nodes absent from our Inputs sheet are "
                 "tracked as known-unmodeled in `tools/pipeline/"
                 "wowhead_known_unmodeled.json` instead of surfacing as NEW. Keep "
                 "that list in sync with the Inputs sheet: when a talent becomes "
                 "modeled, remove it there; when a NEW node is reviewed and "
                 "accepted as expected, add it there.")
    lines.append("")

    lines.append("## (b) Our index talents NOT in the Wowhead 12.1.5 trees "
                 "(removed/renamed — review)")
    lines.append("")
    removed = [(res, name) for res in trees for name in res["removed"]]
    if removed:
        for res, name in removed:
            absent = res.get("removed_absent_everywhere", {}).get(name)
            flag = (" — no spell by this name anywhere in the Wowhead payload "
                    "(all classes) -> likely removed or renamed in 12.1.5"
                    if absent else "")
            mark = (" — removed-known (tracked in `tools/pipeline/"
                    "wowhead_known_unmodeled.json`)"
                    if name in res["removed_known"] else "")
            lines.append(f"- **{name}** ({res['label']}){mark}{flag}.")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## (c) Per-rank values for matched multi-rank talents "
                 "(TEXT-DERIVED — review)")
    lines.append("")
    multi = [(res, e) for res in trees for e in res["multi_rank"]]
    if multi:
        lines.append("| talent | tree | pts | per-rank values (text-derived) | source |")
        lines.append("|---|---|---|---|---|")
        for res, e in multi:
            if e["progression"]:
                val = f"tooltip spells: {e['progression']}. Rank text: {_quote(e['rank_text'])}"
                src = e["source"] + " + node `descriptionSearch`"
            else:
                val = f"rank text: {_quote(e['rank_text'])}"
                src = "node `descriptionSearch` (per-rank arrays not exposed via tooltip)"
            lines.append(f"| {e['name']} | {res['label']} | {e['points']} | {val} | {src} |")
        lines.append("")
        lines.append("All (c) values are TEXT-DERIVED (tooltip/description text), "
                     "not numeric spell data. Rank indexing in the tooltip "
                     "`spells` arrays is ambiguous (slot 0 may be the unmodified "
                     "value — e.g. Vampiric Blood 30/35 vs rank text +5%/+10%), "
                     "so both signals are shown. Our workbook stores talent point "
                     "allocations (Inputs!C/D), not per-rank values, so no "
                     "12.1-vs-12.1.5 value comparison is possible — verify "
                     "against SimC (tools/pipeline/simc_diff.py) before editing.")
    else:
        lines.append("None — no matched talent has more than one rank.")
    lines.append("")
    return "\n".join(lines)


def print_compact(diff: dict, report_path: str) -> None:
    trees = diff["trees"]
    desc = " | ".join(f"{t['label']} {t['wh_id']} ({t['node_count']} nodes)"
                      for t in trees)
    n_nodes = sum(t["node_count"] for t in trees)
    n_matched = sum(len(t["matched_nodes"]) for t in trees)
    n_known = sum(len(t["known_unmodeled_nodes"]) for t in trees)
    n_new = sum(len(t["new_nodes"]) for t in trees)
    n_removed = sum(len(t["removed"]) for t in trees)
    n_removed_known = sum(len(t["removed_known"]) for t in trees)
    n_ours_matched = diff["our_total"] - n_removed
    per_tree = ", ".join(
        f"{t['label']} {len(t['matched_nodes'])}/{t['node_count']}"
        for t in trees)
    print(f"trees: {desc} -> {n_nodes} nodes vs our {diff['our_total']} talents")
    print(f"matched {n_matched}/{n_nodes} nodes ({per_tree}), "
          f"{n_ours_matched}/{diff['our_total']} talents")
    print(f"known-unmodeled {n_known} | NEW {n_new} | removed {n_removed} "
          f"({n_removed_known} removed-known)")
    known_list = [(t["label"], e) for t in trees
                  for e in t["known_unmodeled_nodes"]]
    print(f"KNOWN-UNMODELED (in the Wowhead trees, not modeled in our Inputs "
          f"sheet; {min(10, len(known_list))} of {len(known_list)} shown):")
    for tree, e in known_list[:10]:
        print(f"  - {' / '.join(e['names'])} ({tree}, {e['type']})")
    if len(known_list) > 10:
        print(f"  ... +{len(known_list) - 10} more in the report")
    new_list = [e for t in trees for e in t["new_nodes"]]
    print(f"NEW (genuinely new/renamed — review; {min(10, len(new_list))} "
          f"of {len(new_list)} shown):")
    for e in new_list[:10]:
        tree = next(t["label"] for t in trees if e in t["new_nodes"])
        print(f"  - {' / '.join(e['names'])} ({tree}, {e['type']})")
    if len(new_list) > 10:
        print(f"  ... +{len(new_list) - 10} more in the report")
    removed_list = [(t["label"], name, name in t["removed_known"])
                    for t in trees for name in t["removed"]]
    print(f"REMOVED (our talents not in Wowhead trees; "
          f"{min(10, len(removed_list))} of {len(removed_list)} shown):")
    for tree, name, known in removed_list[:10]:
        print(f"  - {name} ({tree})" + (" — removed-known" if known else ""))
    if len(removed_list) > 10:
        print(f"  ... +{len(removed_list) - 10} more in the report")
    multi = [(t, e) for t in trees for e in t["multi_rank"]]
    n_prog = sum(1 for _, e in multi if e["progression"])
    print(f"per-rank (text-derived): {len(multi)} matched multi-rank talents — "
          f"{n_prog} with tooltip `spells` arrays, {len(multi) - n_prog} text-only "
          f"| report: {os.path.relpath(report_path, REPO_ROOT)}")


# -- CLI -----------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Wowhead talent-tree proposed-diff report.")
    parser.add_argument("--refresh", action="store_true",
                        help="re-download the talent-calc data even if cached")
    parser.add_argument("--game", default=GAME_PATH,
                        help="our game.json (default: %(default)s)")
    parser.add_argument("--report", default=REPORT_PATH,
                        help="report to write (default: %(default)s)")
    args = parser.parse_args(argv)

    cache = fetch(refresh=args.refresh)
    page = load_page_data(cache)
    with open(args.game, encoding="utf-8") as fh:
        game = json.load(fh)
    if "talents" not in game.get("index", {}):
        raise RuntimeError(f"{args.game} has no index.talents")

    diff = build_diff(page, game)
    report = build_report(diff)
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(report)
    print_compact(diff, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
