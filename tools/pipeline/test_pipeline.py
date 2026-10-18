#!/usr/bin/env python
"""Network-free unit tests for the proposed-diff pipeline parsers.

Run (stdlib unittest only — no pytest, no network, no npm):

    .venv/bin/python tools/pipeline/test_pipeline.py

Deliberately NOT wired into `npm test` (vitest): the pipeline is a Python
side-tool, and npm test must stay Node-only. See tools/pipeline/README.md.

Fixtures (tests/fixtures/pipeline/, committed):
  * simc_spell_data_slice.inc  — ~48-line verbatim slice of the SimC midnight
    sc_spell_data.inc cache covering the 3 mapped Blood spells (Heart Strike,
    Blood Boil, Marrowrend) plus Consumption (both spell ids), a few unrelated
    spells, and nil placeholder rows.
  * wowhead_talents_sample.js  — trimmed WH.setPageData payload: 7 trees /
    14 nodes (warrior class tree, DK class tree, DK Frost + Blood spec trees,
    Deathbringer / San'layn / Rider-of-the-Apocalypse hero trees).

Covered: simc_data parsing (name -> id -> effect -> coefficient lookups,
1-based effectN indexing, alias handling, nil-row skipping, class-flags group
splitting), the network-free simc_diff helpers (tolerance classification,
arithmetic formula evaluation, cell-ref parsing, spellId pinning, verdicts),
and wowhead_diff parsing (page-data blocks, Blood DK tree discovery, node
counts, name matching, spellModifiers reversal, the full diff model).

NOT covered (needs the network or the full caches): simc_data.fetch /
wowhead_diff.fetch / fetch_tooltip (curl), and per_rank_progression (live
tooltip JSON). The fixture has no multi-rank matched talent, so build_diff
stays offline here.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "pipeline")
SIMC_FIXTURE = os.path.join(FIXTURE_DIR, "simc_spell_data_slice.inc")
WH_FIXTURE = os.path.join(FIXTURE_DIR, "wowhead_talents_sample.js")

sys.path.insert(0, HERE)
import simc_data  # noqa: E402
import simc_diff  # noqa: E402
import wowhead_diff  # noqa: E402


# -- simc_data: name -> id -> coefficient lookups --------------------------------


class SimcSpellDataParseTests(unittest.TestCase):
    """Parse the fixture slice directly (SimcSpellData, no fetch/lookup)."""

    @classmethod
    def setUpClass(cls):
        cls.data = simc_data.SimcSpellData(SIMC_FIXTURE)

    def test_build_and_declared_counts(self):
        # declaration lines are verbatim from the real 12.1.5.70448 file
        self.assertEqual(self.data.build, "12.1.5.70448")
        self.assertEqual(self.data.declared_spell_count, 31709)
        self.assertEqual(self.data.declared_effect_count, 53441)

    def test_row_counts(self):
        # 11 spell rows -> 8 unique names; 26 effect rows -> 24 kept
        # (2 nil placeholder rows with _spell_id == 0 are skipped)
        self.assertEqual(self.data.spell_rows, 11)
        self.assertEqual(len(self.data.spells), 8)
        self.assertEqual(self.data.effect_rows, 26)
        self.assertEqual(len(self.data.effects), 24)

    def test_name_to_id_first_occurrence_wins(self):
        self.assertEqual(self.data.spells["Heart Strike"], 206930)
        self.assertEqual(self.data.spells["Blood Boil"], 50842)
        self.assertEqual(self.data.spells["Marrowrend"], 195182)
        self.assertEqual(self.data.spells["Consumption"], 205223)

    def test_spell_aliases_keep_all_ids(self):
        self.assertEqual(self.data.spell_aliases["Heart Strike"],
                         [206930, 228645, 316575])
        self.assertEqual(self.data.spell_aliases["Marrowrend"],
                         [195182, 316746])

    def test_nil_placeholder_rows_skipped(self):
        self.assertNotIn((0, 0), self.data.effects)
        for spell_id, _index in self.data.effects:
            self.assertNotEqual(spell_id, 0)


class SimcLookupTests(unittest.TestCase):
    """lookup() on the fixture (module cache pointed at the fixture slice)."""

    @classmethod
    def setUpClass(cls):
        cls.saved = simc_data._DATA
        simc_data._DATA = simc_data.SimcSpellData(SIMC_FIXTURE)

    @classmethod
    def tearDownClass(cls):
        simc_data._DATA = cls.saved

    def test_mapped_spell_coefficients(self):
        # the 3 mapped abilities in tools/pipeline/simc_mapping.json
        self.assertAlmostEqual(
            simc_data.lookup("Heart Strike", 2)["ap_coeff"], 1.967)
        self.assertAlmostEqual(
            simc_data.lookup("Blood Boil", 1)["ap_coeff"], 1.64)
        self.assertAlmostEqual(
            simc_data.lookup("Marrowrend", 2)["ap_coeff"], 2.2065)

    def test_effect_index_is_1_based_effectn(self):
        row = simc_data.lookup("Blood Boil", 1)
        self.assertEqual(row["spell_id"], 50842)
        self.assertEqual(row["effect_index"], 1)
        self.assertEqual(row["file_index"], 0)  # file _index = effectN - 1
        with self.assertRaises(ValueError):
            simc_data.lookup("Blood Boil", 0)

    def test_percent_is_base_value_over_100(self):
        row = simc_data.lookup("Heart Strike", 3)
        self.assertEqual(row["base_value"], 5.0)
        self.assertAlmostEqual(row["percent"], 0.05)
        row5 = simc_data.lookup("Heart Strike", 5)
        self.assertEqual(row5["base_value"], -20.0)
        self.assertAlmostEqual(row5["percent"], -0.2)

    def test_class_flags_group_does_not_shift_positions(self):
        # the { 0, 0, 0, 0 } initializer must stay one token, else
        # trigger_spell_id (position 20) would read a group member (0)
        # instead of the field after it
        row = simc_data.lookup("Invisibility", 2)
        self.assertEqual(row["trigger_spell_id"], 35009)
        self.assertEqual(row["type"], 6)
        self.assertEqual(row["subtype"], 23)
        self.assertEqual(row["amplitude"], 1000.0)

    def test_effect_fields(self):
        row = simc_data.lookup("Blood Boil", 1)
        self.assertEqual(row["effect_id"], 43101)
        self.assertEqual(row["type"], 2)
        self.assertAlmostEqual(row["m_delta"], 0.05)
        self.assertEqual(row["radius_max"], 10.0)

    def test_unknown_spell_raises_keyerror(self):
        with self.assertRaises(KeyError):
            simc_data.lookup("Soul Reaper", 1)  # absent from the slice

    def test_missing_effect_raises_keyerror(self):
        with self.assertRaises(KeyError):
            simc_data.lookup("Blood Boil", 2)  # only effect 1 in the slice


# -- simc_diff: network-free helpers ---------------------------------------------


class SimcDiffHelperTests(unittest.TestCase):
    def test_classify_tolerance(self):
        self.assertEqual(simc_diff.classify(1.967, 1.967)[0], "match")
        self.assertEqual(simc_diff.classify(1.9670, 1.9675)[0], "match")
        self.assertEqual(simc_diff.classify(1.64, 1.5)[0], "CHANGED")
        self.assertEqual(simc_diff.classify(None, 1.0)[0], "unmapped")
        self.assertEqual(simc_diff.classify(1.0, None)[0], "unmapped")
        verdict, delta = simc_diff.classify(2.0, 1.0)
        self.assertEqual(verdict, "CHANGED")
        self.assertAlmostEqual(delta, 1.0)

    def test_eval_arithmetic(self):
        self.assertAlmostEqual(simc_diff.eval_arithmetic("1.4256*1.15"),
                               1.63944)
        self.assertAlmostEqual(simc_diff.eval_arithmetic("=1.4256*1.15"),
                               1.63944)
        self.assertAlmostEqual(simc_diff.eval_arithmetic("2^10"), 1024.0)
        self.assertAlmostEqual(simc_diff.eval_arithmetic("-3.5/2"), -1.75)
        self.assertAlmostEqual(simc_diff.eval_arithmetic("(1+2)*3"), 9.0)
        self.assertIsNone(simc_diff.eval_arithmetic("SUM(A1:B2)"))
        self.assertIsNone(simc_diff.eval_arithmetic("IF(A1,1,2)"))
        self.assertIsNone(simc_diff.eval_arithmetic(""))

    def test_parse_cell_ref(self):
        self.assertEqual(simc_diff.parse_cell_ref("Baseline!H25"),
                         ("Baseline", "H25"))
        self.assertEqual(simc_diff.parse_cell_ref("H25"),
                         ("Baseline", "H25"))
        self.assertEqual(simc_diff.parse_cell_ref("+Critical Strike!C3"),
                         ("+Critical Strike", "C3"))
        with self.assertRaises(ValueError):
            simc_diff.parse_cell_ref("not a cell ref")


class SimcDiffValueTests(unittest.TestCase):
    """resolve_our_value / resolve_simc_value / evaluate_entry, offline."""

    def setUp(self):
        # pin the SimC module cache at the fixture; empty the TSV cache so
        # resolve_our_value cannot touch the real (gitignored) extracted TSVs
        self._saved_data = simc_data._DATA
        self._saved_tsv = dict(simc_diff._TSV_CACHE)
        simc_data._DATA = simc_data.SimcSpellData(SIMC_FIXTURE)
        simc_diff._TSV_CACHE.clear()
        simc_diff._TSV_CACHE[("Baseline", "values")] = {}
        simc_diff._TSV_CACHE[("Baseline", "formulas")] = {}

    def tearDown(self):
        simc_data._DATA = self._saved_data
        simc_diff._TSV_CACHE.clear()
        simc_diff._TSV_CACHE.update(self._saved_tsv)

    @staticmethod
    def game(literals):
        return {"cellLiterals": {"Baseline": literals}}

    def test_resolve_our_value_literal(self):
        our = simc_diff.resolve_our_value(self.game({"H25": 1.64}),
                                          "Baseline!H25")
        self.assertAlmostEqual(our["value"], 1.64)
        self.assertIn("literal", our["source"])

    def test_resolve_our_value_unresolvable(self):
        our = simc_diff.resolve_our_value(self.game({}), "Baseline!H99")
        self.assertIsNone(our["value"])
        self.assertIn("unresolvable", our["source"])

    def test_resolve_simc_value_spellid_pins_the_damage_spell(self):
        # mapping note: the NAME 'Consumption' resolves first to 205223 (no
        # ap_coeff); spellId 1263825 pins the damage spell SimC's class
        # module uses
        by_name = simc_diff.resolve_simc_value(
            {"simcSpell": "Consumption", "effectIndex": 1, "field": "ap_coeff"})
        self.assertAlmostEqual(by_name["value"], 0.0)
        self.assertIn("205223", by_name["display"])

        by_id = simc_diff.resolve_simc_value(
            {"spellId": 1263825, "effectIndex": 1, "field": "ap_coeff"})
        self.assertAlmostEqual(by_id["value"], 6.251)
        self.assertIn("1263825", by_id["display"])
        self.assertIsNone(by_id["error"])

    def test_resolve_simc_value_errors(self):
        no_effect = simc_diff.resolve_simc_value({"simcSpell": "Blood Boil"})
        self.assertIsNone(no_effect["value"])
        self.assertIn("effectIndex", no_effect["error"])
        unknown = simc_diff.resolve_simc_value(
            {"simcSpell": "Blooddrinker", "effectIndex": 1, "field": "ap_coeff"})
        self.assertIsNone(unknown["value"])
        self.assertIn("lookup failed", unknown["error"])

    def test_evaluate_entry_verdicts(self):
        entry = {"ability": "Blood Boil", "simcSpell": "Blood Boil",
                 "effectIndex": 1, "field": "ap_coeff",
                 "ourCell": "Baseline!H25"}
        match = simc_diff.evaluate_entry(entry, self.game({"H25": 1.64}))
        self.assertEqual(match["verdict"], "match")
        changed = simc_diff.evaluate_entry(entry, self.game({"H25": 1.5}))
        self.assertEqual(changed["verdict"], "CHANGED")
        unmapped = simc_diff.evaluate_entry(
            dict(entry, ourCell=None), self.game({"H25": 1.64}))
        self.assertEqual(unmapped["verdict"], "unmapped")


# -- wowhead_diff: tree parsing and discovery ------------------------------------


class WowheadParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = wowhead_diff.load_page_data(WH_FIXTURE)

    def test_page_data_blocks(self):
        self.assertEqual(set(self.page),
                         {"trees", "specGuides", "guideURLs", "spellModifiers"})
        self.assertEqual(len(self.page["trees"]), 7)

    def test_tree_node_counts(self):
        counts = {t["id"]: len(wowhead_diff.tree_nodes(t))
                  for t in self.page["trees"]}
        self.assertEqual(counts, {1: 1, 6: 4, 251: 1, 250: 4,
                                  65568: 1, 65569: 2, 65567: 1})
        self.assertEqual(sum(counts.values()), 14)

    def test_tree_nodes_ordered_by_numeric_cell(self):
        cls_tree = next(t for t in self.page["trees"] if t["id"] == 6)
        cells = [n["cell"] for n in wowhead_diff.tree_nodes(cls_tree)]
        self.assertEqual(cells, [5, 9, 47, 53])

    def test_discover_trees_blood_dk(self):
        cls_tree, blood, heroes, notes = wowhead_diff.discover_trees(self.page)
        self.assertEqual(cls_tree["id"], 6)      # DK class tree
        self.assertEqual(blood["id"], 250)       # Blood spec via guide URL
        self.assertEqual([h["id"] for h in heroes], [65569, 65567])
        self.assertEqual([h["name"] for h in heroes],
                         ["Deathbringer", "San'layn"])
        # Blood discovered through the guide URL, not the id-250 fallback
        self.assertTrue(any("guide URL" in n for n in notes))
        self.assertFalse(any("fell back" in n for n in notes))
        # Rider of the Apocalypse (shownForSpecs [251, 252]) is excluded

    def test_reverse_spell_modifiers(self):
        rev = wowhead_diff.reverse_spell_modifiers(self.page)
        self.assertEqual(rev, {317133: [55233]})  # Vampiric Blood modifier


class WowheadAnalyzeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = wowhead_diff.load_page_data(WH_FIXTURE)
        cls.tree = {t["id"]: t for t in cls.page["trees"]}

    def test_class_tree_matching(self):
        res = wowhead_diff.analyze_tree(
            self.tree[6], "Death Knight",
            ["Icebound Fortitude", "Death Strike", "Wraith Walk"])
        self.assertEqual(res["node_count"], 4)
        self.assertEqual(len(res["matched_nodes"]), 3)
        self.assertEqual([e["names"] for e in res["new_nodes"]],
                         [["Enfeeble"]])
        # choice node: Wraith Walk matched, March of Darkness did not
        self.assertEqual(len(res["unmatched_options"]), 1)
        self.assertEqual(res["unmatched_options"][0]["unmatched"],
                         ["March of Darkness"])
        self.assertEqual(res["removed"], [])

    def test_blood_tree_matching(self):
        res = wowhead_diff.analyze_tree(
            self.tree[250], "Blood",
            ["Heart Strike", "Marrowrend", "Blood Boil", "Vampiric Blood"])
        self.assertEqual(res["node_count"], 4)
        self.assertEqual(len(res["matched_nodes"]), 4)
        self.assertEqual(res["new_nodes"], [])
        self.assertEqual(res["unmatched_options"], [])
        self.assertEqual(res["removed"], [])

    def test_removed_talents_flagged(self):
        res = wowhead_diff.analyze_tree(
            self.tree[250], "Blood",
            ["Heart Strike", "Tombstone"])  # Tombstone not in the slice
        self.assertEqual(res["removed"], ["Tombstone"])

    def test_hero_tree_matching(self):
        res = wowhead_diff.analyze_tree(
            self.tree[65569], "Deathbringer", ["Rune Carved Plates"])
        self.assertEqual(res["node_count"], 2)
        self.assertEqual(len(res["matched_nodes"]), 1)
        self.assertEqual([e["names"] for e in res["new_nodes"]],
                         [["Reaper's Mark"]])
        self.assertEqual(res["unmatched_options"][0]["unmatched"],
                         ["Pact of the Deathbringer"])

    def test_build_diff_model(self):
        # end-to-end (offline: no matched multi-rank talent in the fixture,
        # so per_rank_progression / fetch_tooltip is never called)
        game = {"index": {"talents": [
            {"name": "Icebound Fortitude", "tree": "Death Knight"},
            {"name": "Death Strike", "tree": "Death Knight"},
            {"name": "Wraith Walk", "tree": "Death Knight"},
            {"name": "Heart Strike", "tree": "Blood"},
            {"name": "Marrowrend", "tree": "Blood"},
            {"name": "Blood Boil", "tree": "Blood"},
            {"name": "Vampiric Blood", "tree": "Blood"},
            {"name": "Rune Carved Plates", "tree": "Deathbringer"},
            {"name": "Newly Turned", "tree": "San'layn"},
            {"name": "Vampiric Speed", "tree": "San'layn"},
        ]}}
        diff = wowhead_diff.build_diff(self.page, game)
        # only the 4 Blood-relevant trees are reported (warrior + Frost
        # spec trees are excluded by discovery)
        self.assertEqual([r["label"] for r in diff["trees"]],
                         ["Death Knight", "Blood", "Deathbringer", "San'layn"])
        self.assertEqual(sum(r["node_count"] for r in diff["trees"]), 11)
        self.assertEqual(diff["our_total"], 10)
        blood = diff["trees"][1]
        self.assertEqual(len(blood["matched_nodes"]), 4)
        self.assertEqual(blood["removed"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
