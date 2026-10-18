# Flagged Issues Register — BDK Model Rebuild

Known defects, oddities, and preserved anomalies in the Kyrasis 12.1 BDK mitigation
spreadbook (`excel_mitigation_model.xlsx`) that are carried into the rebuild
**bug-for-bug**. Nothing here is "fixed"; corrected values are recorded only as
reference variants computed by `verify_chains.py` ("OUTPUTS BUG EVIDENCE" section).

- **Provenance**: FI-01–FI-15 expand `extracted/porting_spec.md` §6 (hazard register
  #1–#15, 1:1). FI-16–FI-21 are additions found during extraction/rebuild, not in the spec.
- **Golden baseline**: 9,598 of 9,647 formula cells across all 13 data sheets (Baseline,
  Comparison, 10 +Stat, Outputs) match the Excel cache at ≤1e-9 relative; Outputs' 7 string
  cells match by exact string comparison (144/144, including both FI-14 anomalous blocks).
  49 cells are blank/no-cached (FI-08).
- **Categories**: likely-bug / unexplained-constant / stale-or-dead / design-note.
- **Standing rule** (FI-09): formulas win over comments and documentation.

## Register

### FI-01 — Level-suppression inconsistency (−90 vs −80 baseline)
- **Cells**: Baseline!L14 vs Baseline!F116 / E157 (mirrored on Comparison and +Stat); C153 = Target Level (saved 90).
- **Category**: likely-bug
- **Evidence**: L14 = `MAX(L13-0.015*(C153-90),0)+MAX(H14-0.015*(C153-90),0)+MAX(0.03-0.015*(C153-90),0)` (penalty 0 at level 90); F116/E157 use `0.015*(C153-80)` (penalty 15% at level 90). Both verified exact vs cache (L14 = 0.3239229608) — the inconsistency is real in the model, not an extraction artifact.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-02 — Unexplained target-count swing-speed curve
- **Cells**: Baseline!H15 (mirrored); C152 = #Targets (saved 5).
- **Category**: unexplained-constant
- **Evidence**: H15 divides by `(195.5+21.9*T-0.673*T^2)/195.5` → ×1.109 @T=1, ×1.474 @T=5; H15 = 1.378599312 exact. No comment anywhere explains the quadratic. Patch-sensitive.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-03 — 0.2/s cap applied to the DS heal as well as Blood Shield
- **Cells**: Baseline!X42 `=MIN(T42,0.2)*M42` (and X30).
- **Category**: likely-bug
- **Evidence**: the S33 comment justifies the cap only for Blood Shield ("assumed to only survive a single damage instance per Death Strike"), but the same 0.2/s cap is applied to the Death Strike **heal** too. X42 exact.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-04 — Highmountain additive tail on O6
- **Cells**: Baseline!O6 tail `+E26*C152/2*C7*0.0003*30`; E26 = Highmountain flag (Inputs!E28).
- **Category**: design-note (dormant racial term)
- **Evidence**: E26 = 0 at the saved config → term inert; O6 exact. Activates only if Highmountain is selected (see FI-21: no race selected).
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-05 — +Stat forward chain omits Consumption / Stoneform
- **Cells**: +Stat!S6 (omits the Consumption factor, C121); +Stat!S8/S9 (omit Stoneform, C31).
- **Category**: likely-bug (latent)
- **Evidence**: +Stat sheets are exact at the current config, but would diverge from Baseline's reverse chain if C121 (Consumption) or C31 (Stoneform) were enabled.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); divergence risk documented.

### FI-06 — +Stat D8:D11 normalization identically 1
- **Cells**: +Stat!D8:D11 factor `*(1+0.02*C30)/(1+0.02*Baseline!C30)`.
- **Category**: stale-or-dead (vestigial)
- **Evidence**: C30 holds the same value on both sheets → the factor is identically 1. Exact.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-07 — Y77 sums an empty W78
- **Cells**: +Stat!Y77 `=sum(Y19:Y76)+W78`, W78 empty.
- **Category**: stale-or-dead (vestigial)
- **Evidence**: exact (+0); the `+W78` term contributes nothing.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified), including the +0.

### FI-08 — Volatile cells with no cached values
- **Cells**: ~4–5 per sheet, e.g. Baseline!B19/B21/C21.
- **Category**: design-note (verification caveat)
- **Evidence**: these cells carry no cached values in the workbook (volatile/uncalculated); the verifier skips them and they evaluate fine as blanks. Rebuild computes them.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified; missing cached treated as blank).

### FI-09 — Comment/formula drift
- **Cells**: Baseline!N14 (comment) vs N15; ~17 comment talent names absent from row labels.
- **Category**: design-note
- **Evidence**: N14's comment says "ratio of raw damage taken to external healing" but N15 = (O10−X10)/O10. Standing rule: follow formulas, not comments.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-10 — K52 (IBF row) holds the D&D target-count helper
- **Cells**: Baseline!K52, consumed by O51/M51/etc.
- **Category**: design-note (mapping quirk)
- **Evidence**: K52 = `=IF($C$152<=5,IF($C$152<3,$C$152,2+IF($C$43>0,$C$152-2,0)*((14-5*C131*E137)/S40)),2+IF($C$43>0,3,0)*((14-5*C131*E137)/S40))` — a target-count helper parked on the Icebound Fortitude row. Exact.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); keep mapping (rename only with a cross-reference note).

### FI-11 — D10's second stat-comparison hardcoded to 0
- **Cells**: Baseline!D10 (mirrored +Stat!D10); C10 = Versatility, C9 = Haste Rating.
- **Category**: likely-bug
- **Evidence**: D10 = `=C10+65*E24+225*15/2/120*IF(1<(IF(C10>C8,1,0)+IF(C10>C9,0)+IF(C10>C11,1,0)),E27,0)` — the middle term `IF(C10>C9,0)` is constant 0, so vers-vs-haste never counts toward the "highest stat" bonus. Exact.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-12 — Per-formula SUM-range exclusion sets differ
- **Cells**: throughout the data sheets (spec §1.3).
- **Category**: design-note (transcription hazard)
- **Evidence**: each formula's SUM range excludes a different ad-hoc set of rows; all exact. Normalizing them is a known porting trap — transcribe each range exactly.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-13 — Orphan F35; dead +Stat scratch rows
- **Cells**: Baseline!F35 `=H35/H25` (unreferenced, Baseline only); +Stat scratch rows 79–199.
- **Category**: stale-or-dead
- **Evidence**: unreferenced; no numeric effect either way (omit or keep).
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-14 — Outputs anomalies (verified bug-for-bug and quantified)
- **Cells**: Outputs!D72:D81 + C82 (Unreliable-EHP block); Outputs!C16, D16, C17 (Mitigation block).
- **Category**: likely-bug
- **Evidence**: Outputs 144/144 verified exact bug-for-bug, including both anomalous blocks; corrected variants computed by `verify_chains.py` "OUTPUTS BUG EVIDENCE".
- **Current → corrected**:
  - **(a) Unreliable-EHP normalization**: D72:D81 normalize with the R&C block's `MAX($C$59:$C$68)` = 1468.012210591137 instead of the block's own `MAX($C$72:$C$81)` = 3864.519343724102 → all 10 normalized weights inflated ×2.6325.
    - D72 Armor 1.13547916258499 → 0.43133366074453
    - D73 Strength 2.52793609627272 → 0.96028528436508
    - D74 Stamina 0.338627867387225 → 0.128634326796211
    - D75 Crit 2.63248446834645 → **1** (becomes block max)
    - D76 Haste 0.942334268729793 → 0.357963847483478
    - D77 Vers 1.59869094890837 → 0.607293592091944
    - D78–D80 5.07528516668376E-13 → 1.92794496138916E-13
    - D81 Dps 5.07528516668376E-12 → 1.92794496138916E-12
    - Corrected C82 Pawn: `( Pawn: v1: "BDK EHP(u)": Leech=1.92794496138916E-13, CritRating=1, Dps=1.92794496138916E-12, Strength=0.96028528436508, HasteRating=0.357963847483478, MasteryRating=1.92794496138916E-13, Stamina=0.128634326796211, Armor=0.43133366074453, Versatility=0.607293592091944 )`
  - **(b) Mitigation /10 on a +1 probe**: C16 divides the Weapon-DPS delta by 10 though the probe is +1 (spec §3). Raw weight 1.6307412964988721e-06 → corrected 1.630741296498872e-05 (×10; IF else-branch live: N15 0.9996620210884503 current → 0.9996783285014152). D16 0.171111075250752 → **1.0** (corrected C16 overtakes the old block max 9.530308275540466e-06 = Mastery). C17 Pawn `Dps=` 0.171111075250752 → 1.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); both anomalies flagged.

### FI-15 — Empty O25 pins T25's ratio to 1
- **Cells**: Baseline!O25 (empty); T25's `(-O42/(O25-O42))` term.
- **Category**: design-note (fragile empty-cell dependency)
- **Evidence**: with O25 empty the ratio evaluates to 1; exact. If O25 were ever authored, the Blood-Boil cast math changes.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); O25 kept empty.

### FI-16 — Typo "Calcultion Output"
- **Cells**: Baseline!B168 (mirrored at B168 on Comparison and the 10 +Stat sheets).
- **Category**: likely-bug (cosmetic label typo)
- **Evidence**: section label reads "Calcultion Output" (missing 'a'); carried verbatim into the generated sheets.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-17 — Typo "Averate Ratings"
- **Cells**: D4 on Baseline, Comparison, and all 10 +Stat sheets (12 sheets total).
- **Category**: likely-bug (cosmetic label typo)
- **Evidence**: header label reads "Averate Ratings" (should be "Average Ratings"). Note: the tasked ref "Outputs!D4" is incorrect — Outputs!D4 is empty (Outputs!B4 = "Baseline Stat Weights"); the typo lives at D4 on the data sheets.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-18 — Typo "Controllalbe"
- **Cells**: Outputs!B58.
- **Category**: likely-bug (cosmetic label typo)
- **Evidence**: block header reads "Reliable and Controllalbe EHP Stat Weights" — while Outputs!B11 spells the same word correctly ("Reliable and Controllable Effective Health").
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

### FI-19 — Instructions sheet refers to nonexistent sheet names
- **Cells**: Instructions!B13 ('Open the "Data Input" Sheet'), Instructions!B22 ('Open the "Data Output" Sheet').
- **Category**: stale-or-dead (stale doc reference)
- **Evidence**: no sheets named "Data Input"/"Data Output" exist; the actual sheet names are `Inputs` and `Outputs` (the Outputs sheet's B2 title reads "Data Outputs", but the tab is `Outputs`).
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); Instructions text kept verbatim.

### FI-20 — Saved Armor Constant matches neither documented value
- **Cells**: Inputs!C156 = 3966.55 (mirrored to C154 on Baseline/Comparison/+Stat via `=Inputs!C+2`); consumed by Baseline!L5 PhysDR `=J5/(J5+C154)` → L5 = 0.7527781176.
- **Category**: stale-or-dead (stale constant)
- **Evidence**: the workbook's own Instructions sheet documents "Mythic+ = 4531.03, Mythic Raid = 5656.07" for this input, and the 12.1.5 guide states the current M+ K value is 4531.03. The saved 3966.55 matches neither — stale, or from another difficulty/season.
- **Current → corrected**: not carried — the saved value is what the golden cache encodes; correcting it would change every armor-dependent result.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified); discrepancy flagged, not fixed.

### FI-21 — No race selected in the saved profile
- **Cells**: Inputs!C26:C37 (first race set: Orc, Undead, Tauren, Troll, Blood Elf, Goblin, Human, Dwarf, Night Elf, Gnome, …) and Inputs!E26:E37 (second set: Pandaren, Nightborne, Highmountain, Mag'har, Zandalari, Vulpera, Void Elf, Lightforged Draenei, Dark Iron Dwarf, Kul Tiran, …).
- **Category**: design-note (saved-profile state)
- **Evidence**: all 24 race flags = 0.0 — no racial passives active. Race-dependent terms (FI-04's Highmountain tail, Troll Berserking in J9's haste mult, etc.) are dormant; the golden verification therefore covers only the no-race configuration.
- **Status**: preserved bug-for-bug in the rebuild (golden-verified).

## Pending cross-checks (not yet run)

Model-vs-guide checks against the `[12.1.5] Advanced Blood Death Knight Guide for M+`
(`extracted/bdk_advanced_guide_full.txt`). **No verdict yet** — these have not been
executed; outcomes will be recorded here when run.

1. **DS once-per-damage-event rule vs the model's haste scaling** — the model caps DS
   heal and Blood Shield at 0.2/s (X30/X42, FI-03), i.e. once per 5s regardless of haste,
   while DS cast frequency elsewhere scales with haste (J9). Check against the guide's
   rule that Blood Shield survives a single damage instance per Death Strike.
2. **Blood Shield 50% cap vs Vampiric Blood's max-HP boost** — guide: Blood Shield caps
   at 50% of max health at baseline, and Vampiric Blood's max-HP increase (flat 30%) does
   NOT raise that cap ("for no good reason"). Check whether the model implements the 50%
   cap at all, and whether it uses baseline or VB-boosted max HP.
3. **Armor K + rating conversions vs the 12.1.5 guide** — saved K 3966.55 (FI-20) vs the
   guide's 4531.03 (M+); rating→% conversions H8–H13/L8 (4600 crit / 4400 haste / 5400 vers
   / 2300 mastery / 6900 leech / 3680 avoidance / 5200 parry-from-crit) vs guide values.
