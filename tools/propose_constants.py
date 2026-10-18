#!/usr/bin/env python3
"""
propose_constants.py — PROPOSAL ONLY. No data file is read-modified; the only
outputs are this tool's stdout and the new extracted/constants_proposal.json.

Purpose: groundwork for a structured data/wow-12.1/game.json holding
patch-sensitive constants. Scans every formula in data/wow-12.1/formulas/*.tsv
(parsed with tools/formula_ast), collects numeric literals per (sheet, cell),
and matches them by exact float equality against the constants table
transcribed from extracted/analysis_baseline_notes.md §6. Only literals that
match a documented constant are proposed for later {{name}} templating
(conservative); everything else is left untouched.

Output extracted/constants_proposal.json:
  gameJsonDraft     one entry per distinct constant value:
                    {name, value, meaning, occurrences}; when one value
                    carries multiple documented meanings the entry is flagged
                    (ambiguous: true) and lists all candidates
  substitutions     [{sheet, cell, literal, name}] — proposed templating
                    sites, one record per unique (sheet, cell, literal);
                    ambiguous values also carry candidates (name list)
  unmatchedFrequent top 20 numeric literals NOT matched to any constant
                    ({value, count}; count = total literal occurrences)

Known blind spots (by design, reported on stdout):
  - plain-value cells are not formulas and are not scanned (e.g. Inputs!C156
    = 3966.55), so such constants can legitimately show occurrences = 0
  - TRUE/FALSE and empty function args parse as num 1.0/0.0 and are counted
    like ordinary literals (affects only unmatched frequency stats)
  - documented constants written in formulas as expressions (7/100 for 0.07,
    0.5*0.15 for 0.075, 1/0.94 kept as 0.94) do not literal-match and stay
    untouched unless the exact float appears elsewhere
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formula_ast  # noqa: E402  (sibling module in tools/)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMULA_DIR = os.path.join(ROOT, "data", "wow-12.1", "formulas")
OUT_PATH = os.path.join(ROOT, "extracted", "constants_proposal.json")

# file stem -> real workbook sheet name (reverse of formula_ast.STAT_SHEETS)
STEM_TO_SHEET = {stem: sheet for sheet, stem in formula_ast.STAT_SHEETS.items()}

# ---------------------------------------------------------------------------
# Constants table transcribed from extracted/analysis_baseline_notes.md §6.
# (value, camelCase name, meaning incl. documented cell(s))
# ---------------------------------------------------------------------------
CONSTANTS = [
    # armor / attributes
    (3966.55, "armorDrConstantK", "Armor DR constant K (armor/(armor+K)) for level-90 target (Inputs!C156 plain value; Baseline!C154 refs it)"),
    (1.45, "sheetArmorMultiplier", "Sheet-armor multiplier, Blood Presence/plate (J5)"),
    (1.8, "armorPerStrength", "Armor per point strength, Reinforced Bones/Bone Shield armor (J5)"),
    (20.0, "hpPerStamina", "HP per stamina (J7)"),
    (1.4, "bloodPresenceStamMultiplier", "Blood Presence 40% stam, divided out (H7)"),
    (1.05, "bloodPresenceStamBonus", "Blood Presence 5% stam, divided out (H7)"),
    # parry
    (622.0, "parryFromStrengthBase", "Parry-from-strength base (L6, L13, F116, E157)"),
    (19130.0, "parryFromStrengthDivisor", "Parry-from-strength divisor (L6, L13, F116, E157)"),
    (0.94, "parryDrCoefficient", "Parry DR curve coefficient, written 1/0.94 (L13, F116, E157)"),
    # rating conversions
    (4600.0, "critRatingPerPercent", "Rating to % conversion: crit (H8)"),
    (4400.0, "hasteRatingPerPercent", "Rating to % conversion: haste (H9)"),
    (5400.0, "versRatingPerPercent", "Rating to % conversion: versatility (H10)"),
    (2300.0, "masteryRatingPerPercent", "Rating to % conversion: mastery (H11)"),
    (6900.0, "leechRatingPerPercent", "Rating to % conversion: leech (H12)"),
    (3680.0, "avoidanceRatingPerPercent", "Rating to % conversion: avoidance (H13)"),
    (5200.0, "parryFromCritRatingPerPercent", "Rating to % conversion: parry-from-crit (L8)"),
    # base percentages / suppression
    (0.16, "baseBloodShieldMastery", "Base Blood Shield mastery 16% (H11)"),
    (0.05, "baseCritChance", "Base crit 5% (H8)"),
    (0.03, "baseDodgeParryChance", "Base dodge & parry 3% (H14, L13)"),
    (0.015, "avoidanceSuppressionPerLevel", "Avoidance suppression per boss level above player (L14, F116, E157; L14 uses C153-90, F116/E157 use C153-80)"),
    # proc / uptime models
    (1.13, "rppmBadLuckProtection", "RPPM bad-luck-protection multiplier (many cells; S32/S44/S73 comments)"),
    (0.75, "procChance25", "Uptime model proc chance 25% (uptime = 1-(1-p)^events)"),
    (0.85, "procChance15", "Uptime model proc chance 15% (uptime = 1-(1-p)^events)"),
    (0.875, "procChance12_5", "Uptime model proc chance 12.5% (uptime = 1-(1-p)^events)"),
    # enemy / timing
    (0.7, "enemyArmorDamageFactor", "Enemy armor: 30% reduction on physical damage dealt (K-col)"),
    (1.5, "gcdSeconds", "GCD seconds (Q-col)"),
    (3.0, "runeRegenRunes", "Rune regen: 3 runes per 10s, scaled by haste (L9)"),
    (10.0, "runeRegenCycleSeconds", "Rune regen cycle: 10s (L9)"),
    # Death Strike economy & heal
    (45.0, "dsRpCost", "Death Strike RP cost 45 (O42)"),
    (5.0, "ossuaryRpRefund", "Ossuary RP refund 5 (O42)"),
    (5.0, "impDsRpRefund", "Improved Death Strike RP refund 5 (O42)"),
    (5.0, "dsRecentDamageWindowSeconds", "DS heal: damage taken in last 5s (M30/M42)"),
    (0.2, "dsHealRecentDamageFraction", "DS heal: 20% of damage taken in last 5s (M30/M42)"),
    (0.07, "dsMinHealMaxHpFraction", "DS heal minimum 7% maxHP (M30/M42; written 7/100)"),
    (0.2, "dsBloodShieldCapPerSecond", "DS heal & Blood Shield counted max 1 per 5s = 0.2/s cap (X30/X42)"),
    # cooldowns / talents
    (0.33, "drwMirrorFraction", "DRW mirrors 33% of damage (K38)"),
    (8.0, "drwDurationSeconds", "DRW 8s duration (K38)"),
    (4.0, "drwEverlastingBondSeconds", "DRW +4s Everlasting Bond (K38)"),
    (12.0, "reapersMarkWindowSeconds", "Reaper's Mark 12s window (H134)"),
    (40.0, "reapersMarkStackCap", "Reaper's Mark 40 stack cap (H134)"),
    (7.0, "sanlaynStackCount", "San'layn 7 stacks (K134)"),
    (0.85, "sanlaynUptimeFactor", "San'layn 7 stacks x 0.85 uptime (K134)"),
    (195.5, "targetCountAttackSpeedBase", "Target-count attack-speed curve base (H15; unexplained by comments, fragile)"),
    (21.9, "targetCountAttackSpeedLinear", "Target-count attack-speed curve linear coefficient (H15; fragile)"),
    (0.673, "targetCountAttackSpeedQuadratic", "Target-count attack-speed curve quadratic coefficient (H15; fragile)"),
    (2.5, "boneShieldRechargeSeconds", "Bone Shield 2.5s recharge (L15)"),
    (2.0, "bossSwingSeconds", "Boss swing 2s (L15)"),
    (0.151, "domBoneShellCubicC0", "DoM Bone-Shell crit-multiplier cubic c0 (L15; fragile)"),
    (0.367, "domBoneShellCubicC1", "DoM Bone-Shell crit-multiplier cubic c1 (L15; fragile)"),
    (0.0791, "domBoneShellCubicC2", "DoM Bone-Shell crit-multiplier cubic c2 (L15; fragile)"),
    (0.0086, "domBoneShellCubicC3", "DoM Bone-Shell crit-multiplier cubic c3 (L15; fragile)"),
    (10.8, "runicAttenuationPpm", "Runic Attenuation 10.8 PPM (R67)"),
    (3.0, "unholyStrengthPpm", "Unholy Strength 3 PPM (R73)"),
    (25.0, "amsRpGen", "AMS 25 RP gen (O19)"),
    (0.3, "amsHpAbsorbFraction", "AMS 30% HP absorb (V8)"),
    (0.15, "amzHealFraction", "AMZ heals 15% of absorbed (U8)"),
    # racial / talent heal fractions of maxHP (row labels partially stale per §7)
    (0.48, "maxHpHealFractionM66", "Racial/talent heal fraction of maxHP (M66)"),
    (0.2, "maxHpHealFractionM41", "Racial/talent heal fraction of maxHP (M41)"),
    (0.2, "maxHpHealFractionM48", "Racial/talent heal fraction of maxHP (M48)"),
    (0.04, "maxHpHealFractionM73", "Racial/talent heal fraction of maxHP (M73)"),
    (0.075, "maxHpHealFractionM32", "Racial/talent heal fraction of maxHP (M32; written 0.5*0.15)"),
    (0.02, "maxHpHealFractionM74", "Racial/talent heal fraction of maxHP (M74)"),
    (0.0025, "maxHpHealFractionM51", "Racial/talent heal fraction of maxHP (M51)"),
    # WotN / IBF
    (0.7, "wotnEhpBaseFactor", "WotN EHP factor base 0.7 = 1-30% (Q15/R15/S15)"),
    (0.3, "wotnDamageReduction", "WotN EHP factor 30% at C79=2 ranks (Q15/R15/S15)"),
    (0.05, "wotnBonus", "WotN EHP factor +5% (Q15/R15/S15)"),
    (0.3, "ibfDamageReduction", "IBF 30% damage reduction (Q6)"),
    (0.1, "ibfBloodyFortitudeBonus", "IBF +10% Bloody Fortitude (Q6)"),
    (8.0, "ibfDurationSeconds", "IBF 8s duration (Q6)"),
    # magic damage reduction / heal fractions (O6/O8 row)
    (0.08, "nullMagicDamageReduction", "Null Magic 8% (O6/O8)"),
    (0.075, "rcpHealFraction", "RCP 7.5% (O6/O8)"),
    (0.08, "bsgDamageReduction", "BSG 8% (O6/O8)"),
    (0.06, "domDamageReduction", "DoM 6% (O6/O8)"),
    (0.025, "bloodshotDamageReduction", "Bloodshot 2.5% (O6/O8)"),
    (0.05, "consumptionFraction", "Consumption 5% (O6/O8)"),
    # J14/J15 row
    (0.06, "sanguineGroundDamageReduction", "Sanguine Ground 6% (J14/J15)"),
    (0.05, "coagulopathyBonus", "Coagulopathy 5% (J14/J15)"),
    (0.15, "brittleProcChance", "Brittle 6% (15% proc) (J14/J15)"),
    (0.12, "enfeebleSlowFraction", "Enfeeble 12% (J14/J15)"),
    (0.2, "insidiousChillSlowFraction", "Insidious Chill 20% (J14/J15)"),
    # Vampiric Blood
    (1.3, "vbHealingAmpBase", "VB healing amp 30% base (X10)"),
    (0.05, "vbHealingAmpPerRank", "VB healing amp +5% per IVB rank (X10)"),
    (10.0, "vbDurationBaseSeconds", "VB duration 10s base (X10)"),
    (2.0, "vbDurationPerRankSeconds", "VB duration +2s per IVB rank (X10)"),
    # AP sources
    (169.0, "orcRacialAp", "Orc racial AP, written 169*15/120 (J-col)"),
    (4925.0, "raiseDeadAp", "Raise Dead AP, written 4925*15/120 (M40)"),
    (6.0, "weaponApPerDps", "Weapon AP = DPS x 6 (J-col)"),
    (1.15, "bloodSpecDamageMultiplier", "Blood spec +15% damage (I-col)"),
    (24.0, "bloodPlagueDamageWindowSeconds", "Blood Plague damage window, K29/24 (V29)"),
    (6.0, "umbilicusApPerDps", "Umbilicus = BP DPS x VB duration x 6 (M72)"),
]


def collect_nums(node, out):
    """Append every num-literal value in the AST to `out` (document order)."""
    if isinstance(node, dict):
        if node.get("type") == "num":
            out.append(node["value"])
            return
        for key in ("left", "right", "operand"):
            if key in node:
                collect_nums(node[key], out)
        for arg in node.get("args", []):
            collect_nums(arg, out)
    elif isinstance(node, list):
        for item in node:
            collect_nums(item, out)


CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def cell_key(cell):
    """Sort key for A1-style refs: by row number, then column letters."""
    m = CELL_RE.match(cell.upper())
    return (int(m.group(2)), m.group(1)) if m else (0, cell.upper())


def main():
    by_value = {}       # float -> [{name, meaning}, ...] in table order
    value_order = []    # distinct values, first-appearance order
    for value, name, meaning in CONSTANTS:
        v = float(value)
        if v not in by_value:
            by_value[v] = []
            value_order.append(v)
        by_value[v].append({"name": name, "meaning": meaning})

    substitutions = []
    site_count = Counter()   # value -> matched unique (sheet, cell, literal) sites
    node_count = Counter()   # value -> total literal occurrences (incl. repeats)
    per_sheet = Counter()
    parse_failures = []
    scanned = 0

    for fname in sorted(os.listdir(FORMULA_DIR)):
        if not fname.endswith(".tsv"):
            continue
        stem = fname[:-len(".tsv")]
        sheet = STEM_TO_SHEET.get(stem, stem)
        formulas = formula_ast.load_formulas(os.path.join(FORMULA_DIR, fname))
        for cell, formula in formulas.items():
            scanned += 1
            try:
                ast = formula_ast.parse(formula, sheet=sheet)
            except SyntaxError as exc:
                parse_failures.append(f"{sheet}!{cell}: {exc}")
                continue
            nums = []
            collect_nums(ast, nums)
            for v in nums:
                node_count[v] += 1
            for v in sorted(set(nums)):        # one site per (sheet, cell, literal)
                if v in by_value:
                    entries = by_value[v]
                    rec = {"sheet": sheet, "cell": cell, "literal": v,
                           "name": entries[0]["name"]}
                    if len(entries) > 1:
                        rec["ambiguous"] = True
                        rec["candidates"] = [e["name"] for e in entries]
                    substitutions.append(rec)
                    site_count[v] += 1
                    per_sheet[sheet] += 1

    substitutions.sort(key=lambda r: (r["sheet"],) + cell_key(r["cell"]))

    game_json_draft = []
    for v in value_order:
        entries = by_value[v]
        entry = {"name": entries[0]["name"], "value": v,
                 "meaning": entries[0]["meaning"],
                 "occurrences": site_count.get(v, 0)}
        if len(entries) > 1:
            entry["ambiguous"] = True
            entry["candidates"] = list(entries)
        game_json_draft.append(entry)

    unmatched = [(v, c) for v, c in node_count.items() if v not in by_value]
    unmatched.sort(key=lambda item: (-item[1], item[0]))
    unmatched_frequent = [{"value": v, "count": c} for v, c in unmatched[:20]]

    proposal = {"gameJsonDraft": game_json_draft,
                "substitutions": substitutions,
                "unmatchedFrequent": unmatched_frequent}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2)
        f.write("\n")

    # ---------------- report ----------------
    n_ambiguous = sum(1 for v in value_order if len(by_value[v]) > 1)
    matched_values = sum(1 for v in value_order if site_count.get(v))
    print(f"constants table: {len(CONSTANTS)} entries, {len(value_order)} "
          f"distinct values ({n_ambiguous} ambiguous: value matches multiple "
          f"documented meanings)")
    print(f"formulas scanned: {scanned} ({len(parse_failures)} parse failures)")
    print(f"distinct values matched in formulas: {matched_values}/{len(value_order)}")
    print(f"total substitution sites: {len(substitutions)}")
    print("per-sheet substitution counts:")
    for sheet in sorted(per_sheet):
        print(f"  {sheet}: {per_sheet[sheet]}")
    print(f"top unmatched literals ({len(unmatched)} distinct unmatched values, "
          f"top 15 shown):")
    for v, c in unmatched[:15]:
        print(f"  {v} x {c}")
    if parse_failures:
        print("parse failures (excluded from the scan):")
        for p in parse_failures[:10]:
            print(f"  {p}")
    zero = [e["name"] for e in game_json_draft if e["occurrences"] == 0]
    if zero:
        print(f"documented constants with 0 literal matches: {', '.join(zero)}")
    print(f"wrote {os.path.relpath(OUT_PATH, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
