# BDK Mitigation Model — Porting Specification (bug-for-bug reimplementation)

Source of truth for implementation threads. Companion artifacts:
- `extracted/verify_chains.py` — Excel-formula evaluator + verifier (run: `.venv/bin/python extracted/verify_chains.py`). Parses every formula from the TSVs, resolves refs on demand (memoized, cycle-detecting) from Inputs literals, compares every formula cell to its cached value.
- `extracted/eval_order.txt` — empirical 38-layer topological order of all 765 Baseline formula cells (depth = 1 + max depth of referenced cells).
- `extracted/analysis_baseline_notes.md` — section map, formula catalog, constants table, methodology comments.

---

## 1. EVALUATION ORDER & DEPENDENCIES

### 1.1 Iterative calculation ruled out
`xl/workbook.xml` ends `<definedNames/><calcPr/>` — calcPr has NO `iterate`/`iterateCount` attributes → Excel iterative mode is OFF. Empirically confirmed: memoized on-demand evaluation of all ~9,600 formula cells across the 13 data sheets (incl. Outputs, which references all 12 others) completes with **zero cycle detections** and reproduces every cached value exactly (§2). The workbook is a pure DAG; a single topological pass suffices. No fixed-point iteration is needed anywhere.

### 1.2 The T42 ↔ AA-column dependency (resolved)
`T42 = -(SUM(AA19:AA41,AA43:AA76))/O42` (DS casts/sec = total RP generation ÷ net DS RP cost). The sum skips only row 42 (DS itself). **AA cells that exist**: AA19(AMS), AA22(ArcaneTorrent), AA28(BloodMist), AA40(D&D), AA42(DS), AA43(DC), AA51(HS), AA57(MR), AA58(MindFreeze), AA63(Reaper'sMark), AA67(RunicAtt), AA77(total). The rows whose T depends on T42 — 30 BloodShield (`T30=T42`), 31 BloodyDemise (`T42/10*C158`), 55 Lifeblood (`T42*C109`), 62 Razorice (`B19*(...)`, B19 empty→0), 74 VampiricStrike, 76 VB — have **NO AA cells at all** (O30/O31/O55/O62/O74/O76 are empty → AA would be 0 anyway, and the cells were never authored). Hence no cycle: **T42 depends on {T19,T22,T28,T40,T43,T51,T57,T58,T63,T67}; T30/T31/T55/T62/T74 and S76 (via AA42) consume T42 downstream.** A naive engine that materializes `AA = T*O` for every table row still works because the T42-dependent rows generate 0 RP — but the safe port evaluates T42 after the independent cast rates and before its consumers.

### 1.3 Deliberate self-exclusions in SUM ranges (the real "order" traps)
Each solver cell excludes its own resource row and its throttle partners — port each range EXACTLY:
- `T51` (HS): `SUM(Z19:Z50)+SUM(Z52:Z76)` excludes **Z51** (own rune spend); `SUM(U18:U41,U43:U50,U52:U76)` excludes U42, U51; `SUM(AA19:AA41,AA43:AA50,AA52:AA76)` excludes AA42, AA51.
- `T25` (BB): U-sum `U19:U23,U29:U41,U43:U50,U52:U76` excludes **U24–U28** (Blood Beasts/BB/BloodDraw/BloodFeast/BloodMist — shared charge pool) and U51; AA-sum excludes **AA25, AA51**; Z-sum same as T51 (includes Z37).
- `T57` (MR): `SUM(AB19:AB56)-SUM(AB58:AB76)` excludes **AB57** only (includes AB38 DRW, AB43 DC, AB63 RM).
- `T43` (DC): excludes **AB43** and **AB57:AB60**.
- `T42`: excludes **AA42** (see 1.2).

### 1.4 E127 / F127 — the DoM approximation (forward reference, not a cycle)
- `E127` (DoM "average weapon count"/uptime) = `T38*(8+C110*4)*(1+C110) + IF(C127>3,1,0)*8*0.125*(T40+T43+T51+T57+T63)` — depends on T51/T57 (depth 23). Consumed by J14, O6:O9, P6, Q15/R15.
- `F127` (DoM rune proc rate; `T37=F127`, `Z37=T37*N37`) — C127=4 branch embeds a **replica of T51's formula** whose sums exclude **Z37** (DoM's own runes), **U25** (BB), **AA25/AA51** — the explicit approximation that breaks the would-be cycle `T51 → Z37 → T37 → F127 → (T51-replica)`. The replica otherwise uses the same Z/U/AA cells. Comment on L15: "Dance of Midnight requires an approximation function … to avoid a circular feedback loop."
- Evaluation order (empirical depths): T38(3) → L15(12) → T43(13) → T57(15) → F127(17) → T37(18) → Z37(19) → T25(20) → T51(22) → E127/E116/P6(23) → T42(24).

### 1.5 Other resource loops (all one-directional)
- **RP → DS casts**: `O42 = -45+5*C91+IF(C42>0,5,0)+10*8*T26` (−45 base, +5 Ossuary, +5 Improved DS, +80 RP per Blood Draw cast — T26=0 currently → O42=−35). T42 = −ΣAA/O42; AA77=0 by construction.
- **Bone Shield**: `L15` (drain rate; C127=4 branch uses a crit-multiplier cubic of J8, non-DoM branch uses T38) → `T43` (DC, gated by D87=0) → `T57 = MAX((L15-ΣAB_except57)/3, T47)` (MR tops up BS generation; AB77 = L15 exactly). Z57 = (T57−T47/2)×(−2).
- **VS taken out of HS**: `T74 = C131*((T38*(8+C110*4))*T51 + (1-T38*(8+C110*4))*((0.35+0.05*14/S40*E136)*T42+(E140*0.35*0.15)*T42))` — VS replaces HS during DRW, else 35% of DS casts; `T53 = C131*T74`.
- **VB CD**: `S76 = R76/(1-AA42/5*C122*((O42-5*IF(C42>0,1,0))/O42))` (Red Thirst: DS RP spend shortens Vampiric Blood CD) → T76 → X10.

### 1.6 STAGED COMPUTATION PLAN (empirical; full 38-layer detail in `eval_order.txt`)
| Phase | Depths | Computes (key cells) | Consumes |
|---|---|---|---|
| 0. Config | 1 | All C5:C158 mirrors of Inputs (row = Inputs row − 2), B19/B21 (empty→0), D/E talent vars, literals: R-col CDs (R19=60, R25=7.5, R52=120, R63=45, R76=90…), O22=20, O57=20, O63=20, P38=D105*C105=5, P43=2, P57=3, P63=3, H-col AP coeffs, I-col spec mults | Inputs literals only |
| 1. Base attributes & CD cast rates | 2–5 | D8:D13→E8:E13 rating-DR curves; H5/H6/H7 base stats; H9→T38(=1/S38*C98*C149)→K134→J9; H10/J10/L10; H11/J11/L11; H12/J12; H13/J13; H14; H15 (J9, C59=1, D59=0.9); J7=C7*20; T10=C145 anchor, T6:T9 splits; all CD-only cast rates T18–T76 (T19, T22, T23, T26, T32, T35, T36, T38, T40, T41, T46/T47, T48–T50, T52, T54, T56, T58, T61, T63–T65, T67, T70, T71, T73); O42; L9 | Phase 0 |
| 2. Derived attributes & simple aggregates | 6–12 | H8/J8 (needs J9); L6, L8; L13 (T28=0); L14; L15 (L14, J8 — DoM branch); Q-col cast times (1.5/J9); U-col time utils for CD abilities; AA19/AA40/AA67/AA22/AA28/AA58/AA63; J6 (S40, H15, T69=0); L7 (J6); V8/V9/V10 AMS heals (T19, L7, J10); Z40; AB38/AB49/AB63; O51 (K52 helper); M-col heals w/o solver (M32, M41, M48, M66, M73); X32/X36/X41/X48/X66/X73 | Phase 1 |
| 3. Bone-Shield solver | 13–16 | T43 (L15, AB sums; ×D87=0); T57 (L15, AB38/49/63, T47); U43/Z43/AA43/AB43; U57/Z57/AA57/AB57; AB77 | Phase 2 |
| 4. DoM approximation | 17–19 | F127 (T38, T40, T43, T46, T57, T63, L13 + embedded T51-replica over Z/U/AA excluding Z37/U25/AA25/AA51); T37=F127; Z37 | Phase 3 |
| 5. GCD/resource solvers | 20–22 | T25 (BB: S25, U/Z/AA sums, O42, Q42, O51, N51, Q51, Q25, O25-empty, C130, T47); U25; T51 (HS: L9, Z37, Z/Z sums, U/AA sums, O51, Q51, O42, Q42, N51); U51/Z51/AA51 | Phase 4 |
| 6. DoM uptime, DRW parry, DS casts | 23–25 | E127 (T38, T40, T43, T51, T57, T63); E116 (same + L14, C116); P6 (DRW parry); T39; J14 (E127, S40, T40, H15); O8/O9/P10; **T42** (AA19/22/28/40/43/51/57/58/63/67, O42); Z77; D157 (T42); L12 (T42, T54); T30/T31/T55/T62; T74 (T51, T42); S33; U42/AA42 | Phase 5 |
| 7. Armor/parry-DR helpers, ability damage | 26–27 | F116/E157 (E116/D157, J6, L8, H14); H134; **J5** (J6, E116, D157, J9, J10) → **L5**; S76 (AA42, O42) → T76; J-col ability damages (J21–J75); K21–K75 base; U77/AA77 | Phase 6 |
| 8. Ability damage/healing, cascade unmitigated | 28–30 | K-col composites (K38/K39 DRW mirror = Σ of other abilities' V/W ×0.33×(8+4*C110)…); L-col priority dmg; M-col heals (M30 needs T42; M42 needs T10; M51 needs K52); **O6/O7** (P6, L14, L5, L10, F116, E157, E127, S40, config DR divisors) → **O10 = UDTPS**; Q15/R15 (EHP tiers); V/W cols; S15 | Phase 7 |
| 9. Ability DPS/HPS/EHPS totals | 31–35 | X-col HPS (X30/X42 = MIN(T,0.2)×M caps); Y-col EHPS (×(1−C144), some rows uncapped); V77/W77 DPS totals; O15=V77, P15=W77; **Y77 = ΣY19:Y76** | Phase 8 |
| 10. Final metrics | 36–38 | **W10** = Y77 + C27*0.0011*L7*(1−C144); **X10** = EHRPS (T10, U10, V10, W10, T76, C92, C49); **N15** = Mitigation Factor = (O10−X10)/O10 (self-sufficient text branch if X10=0) | Phase 9 |

A lazy on-demand evaluator (as in `verify_chains.py`) or an explicit topo-sort over these layers both work; the layers are a convenience, not a requirement — any topological order is correct.

---

## 2. NUMERIC VERIFICATION (all EXACT)

Method: `verify_chains.py` evaluates every formula cell from Inputs literals and compares to the cached value (tolerance ≤1e-9 relative; Excel stores IEEE-754 doubles, same as JS `Number`). Text-valued cells (Outputs' 6 Pawn strings + I7 `(0.01%)`) are compared as exact strings, using Excel's `&` number→text coercion reverse-engineered from the cache (§5).

| Sheet | Formula cells | Exact | Mismatch | No cached value | Errors/Cycles |
|---|---|---|---|---|---|
| Baseline | 765 | **761** | 0 | 4 (B19, B21, C21, E35) | 0 |
| Comparison | 768 | **763** | 0 | 5 | 0 |
| each +Stat (×10) | 797 | **793** | 0 | 4 | 0 |
| Outputs | 144 | **144** (137 numeric + 7 string) | 0 | 0 | 0 |

**~9,600 formula cells across all 13 data sheets: 9,598 verified exact (9,591 numeric at ≤1e-9 relative + 7 exact strings), 49 blank/no-cached, zero mismatches, zero cycles.** Outputs' 7 string-valued formulas = the 6 Pawn strings (C17/C30/C43/C56/C69/C82) + I7; its other 123 cells are labels/literals (not formulas, not verified). The four required chains (checkpoints, computed = cached):

- **(i) Armor DR** Inputs!C7=3852 → C5=3852 → H5=3852 (SSG off) → J6=2890.654188 (mod Str: Rune Mastery 3%/rune cap, San'layn D&D term) → E116=0.048140815 (Bloodied Blade eff Str) → D157=0.065134944 (2-set: C157×(0.025+0.1×T42)) → J5=12077.94396 → **L5=0.7527781176** = J5/(J5+3966.55). Note: armor DR depends on the DS-cast solver through D157/E116.
- **(ii) Total parry** C8=778.5 → D8=778.5 (no bonus: only 1 of 3 "highest-stat" IFs true) → E8=778.5 (below 1380 knee) → H8=0.2192391304 → J8=1.2192391304; L8=E8/5200/(1+0.02×C30)=0.1497115385; L6=(J6−622)/19130=0.1185914369 → **L13=0.2639229608** = 622/19130+0.03+(L6+L8)/((L6+L8)+1/0.94)+0.05×8×T28(=0) → L14=0.3239229608 (level-90 penalty 0).
- **(iii) DS casts/sec** J9=1.524574934 (haste: E9=1053.5→H9=0.2394318182; ×1.1 ImpBS ×1.04 UnholyMomentum ×1.0752 San'layn K134=7.5227) → L9=0.4573724803; T38=0.01101321586 (DRW 120.8s CD); L15=0.3269240909 (Bone Shield drain, DoM cubic branch); T57=0.0906193372 (MR = (L15−AB38)/3); F127=0.1402974432 (DoM rune rate, embedded T51-replica=0.2602881); T51=0.4003060619 (HS — GCD/RP-constrained arg wins); O42=−35 → **T42=0.4013494365** = −(AA19 0.582611+AA40 0.714286+AA51 10.007652+AA57 1.812387+AA67 0.930296)/(−35). Also verified: T25=1/24 (BB at charge cap), T74=0.1922269492, E127=0.8266711512, S76=21.37363360, T76=0.0467866166.
- **(iv) Mitigation Factor** T10=400000 (=C145) → T6=320000/T8=80000 → Q6=328767.1233 (IBF) → P6=428388.0441 (DRW parry) → O6=3608042.253, O8=112528.8350 → **O10=UDTPS=3720571.088**; L7=1682894.6; V8=V10=11765.66776 (AMS); W10=384443.5455 (=Y77, fully computed through the abilities table); **X10=EHRPS=1257.474567** → **N15=0.9996620211** = (O10−X10)/O10.

**Failure encountered & resolved**: first run produced 484 SyntaxErrors ("bad char 'I'") — the tokenizer's cell-ref pattern requires digits, so function names (IF, SUM, MAX, MIN, exp, AND…) were unlexable. Fix: added an identifier token ordered AFTER ref (so `C8` stays a ref), marking identifier+`(` as function calls. After the fix: 761/761 exact, no evaluation-order failures — the DAG resolves naturally; the only order-sensitivity is the deliberate SUM-range self-exclusions (§1.3) and F127's replica (§1.4), both of which a correct topological evaluation handles for free.

**Outputs string verification & the `&` coercion finding**: with correctly-rounded 15-significant-digit rendering of the binary value, 6 of Outputs' 7 string cells matched and C17 mismatched in exactly one digit (`Stamina=0.00439246562690172` computed vs `…0173` cached) while D9 itself verified exact numerically. Diagnosis: neither transcription error nor stale cache — Excel's `&` coercion rounds the SHORTEST ROUND-TRIP decimal to 15 significant digits half-away-from-zero (D9 = 0.004392465626901725 → `…0173`), not the correctly-rounded 15 digits of the exact binary value (…01724887… → `…0172`). The xlsx's numeric `<v>` caches store only 10 significant digits, but C9's 10-digit cache pins Excel's N15 inputs bit-exact to the evaluator's (the N15 difference is Sterbenz-exact; a 1-ULP N15 difference would shift C9 by more than its full 10-digit rounding interval), so the D9 double is identical and the divergence is purely coercion semantics. Implemented in `excel_num_str()`; after the fix 7/7 string cells exact. Evaluator additions for Outputs: quoted sheet-name refs (`'+Weapon DPS'!$N$15`), the `N()` function, and exact string comparison.

---

## 3. +STAT DELTA SPEC

Each +Stat sheet = Baseline + a fixed change set. Model-area changes (rows ≤77), common to ALL 10 sheets (38 cells):

| Cell(s) | Baseline | +Stat |
|---|---|---|
| B2 | "Baseline Profile" | "+<Stat> Profile" |
| H5/H6/H7 | `=C5/(1+C21*0.05*(1+0.2*C63))` etc. (strip multipliers) | `=Baseline!H5` / `=Baseline!H6` / `=Baseline!H7` — **target stat's cell gets `+10`** |
| C5 | `=Inputs!C7` | `=H5*(1+C21*0.05*(1+0.2*C63))` (re-apply multiplier) |
| C6 | `=Inputs!C8` | `=(H6+C34*33)*(1+C21*0.05*(1+0.2*C63))` |
| C7 | `=Inputs!C9` | `=(H7+C26*99)*(1+C21*0.05*(1+0.2*C63))*1.05*(1+0.2*C55)*(1.4)` |
| D8:D11 | `=C8+225*15/2/120*IF(...)` | same expression wrapped: `=(...)*(1+0.02*C30)/(1+0.02*Baseline!C30)` — **identically 1 at C30=0 (vestigial no-op; preserve literally)** |
| O6:O9 | reverse cascade (divide out layers) | `=Baseline!O6` … `=Baseline!O9` (anchor unmitigated) |
| P6 | `=Q6/(1-DRWparry)` | `=(O6-E26*C152/2*C7*0.0003*30)*(1-L14)*(1-L5)*L10*(1-0.01*E32)*(1-0.2/C152*C74)*(1-C51*0.12/C152*1.13*(1-exp(-3*6/60*55/120)))*(1-C135*C130*D130*0.075)*(1-C131*E136*10/S40*0.08)*(1-F116)*(1-E157)*(1-IF(C127>1,1)*0.06*E127)*(1-(0.04*10*(1/S40)*C100*(uptime-IF-chain)))*(1-C120*0.025)` — full forward inverse; Highmountain tail subtracted first |
| P7/P8/P9 | reverse | `=O7*$J$13*(1-L5)*L10*…` / `=O8*L10*…(1-0.08*C80)…` / `=O9*$J$13*L10*…` (AoE rows use J13 AoE-DR; magic rows add Null Magic; no avoidance/armor-vs-magic) |
| Q6 | `=R6/(1-(T52*8)*(0.3+0.1*E139))` | `=P6*(1-((1-(1-(T38*(8+C110*4)))*(1-IF(C127>3,1,0)*(1-0.875^(8*(T40+T43+T51+T57+T63)))))*MIN(0.3/(1-L14),1)))` (forward DRW parry) |
| Q7/Q8/Q9 | reverse IBF | **EMPTY** (DRW step exists only for physical ST row 6; R7/R8/R9 reference P directly) |
| R6:R9 | reverse misc | `=Q6*(1-(T52*8)*(0.3+0.1*E139))` / `=P7|P8|P9*(1-(T52*8)*(0.3+0.1*E139))` (forward IBF) |
| S6:S9 | reverse (incl. Consumption + Stoneform + BloodDraw) | `=R6*(1-(T70*8)*0.1)*(1-(T26*8)*0.1)` — **Consumption factor ABSENT**; S8/S9 omit the Stoneform factor (both inert at T35=0/T70=0 but would diverge if those talents were taken) |
| T6:T9 | `=(1-C146-C147)*T10` etc. | `=S6` … `=S9` (pass-through) |
| T10 | `=C145` (anchor 400k) | `=SUM(T6:T9)` (forward total) |
| Y77 | `=sum(Y19:Y76)` | `=sum(Y19:Y76)+W78` (**W78 is an empty cell → +0**) |
| Q5/S5 | "…Mitigation" labels | "…Mitigated" |
| D102 | `=Inputs!D104` | removed (empty → T18=0, same value since C102=0) |
| F35 | `=H35/H25` (orphan) | removed |

Per-stat increment (exactly one cell beyond the common set for rating/weapon sheets; base-stat increments live inside H5/H6/H7):
- **+Armor**: `H5 = Baseline!H5+10` (others anchored plain)
- **+Strength**: `H6 = Baseline!H6+10`; **+Stamina**: `H7 = Baseline!H7+10`
- **Ratings** (+Critical Strike/+Haste/+Versatility/+Mastery/+Leech/+Avoidance): target `C8..C13 = Inputs!C10..C15+10`; non-target ratings stay `=Inputs!C10..` plain
- **+Weapon DPS**: `C14 = Inputs!C16+1` (increment is **+1**, not +10)

Additionally each +Stat sheet carries ~40 **dead scratch cells** in rows 79–199 (V79–V94, W79/W81/W88, X88–X94, Y79/Y88, U86/U89/U90/U96, N196–P199 "Conduit Runes", Q103, D114) — present only in the +Stat copies, unreferenced by any model cell (verified: each appears exactly once, its own definition; W78 appears only as Y77's operand). Safe to omit in the port; harmless to keep.

All 10 +Stat sheets verified 793/793 formula cells exact against cache.

---

## 4. COMPARISON SPEC

Comparison = full model recompute with an A/B override layer over Inputs. Row mapping: Baseline/Comparison row n ↔ Inputs row n+2.

- **C-column (ranks/values)**: `=IF(ISBLANK(Inputs!H<n>), Inputs!C<n>, Inputs!H<n>)` — H = full replacement; blank H inherits the Inputs C value. (Example: C121 = IF(ISBLANK(Inputs!H123), Inputs!C123, Inputs!H123); the only H override currently set is **Inputs!H123 = 1.0 → Consumption rank 1 ON** vs Baseline C121=0.)
- **H5/H6/H7 (base stats)**: `=IF(ISBLANK(Inputs!H7|H8|H9), Baseline!H5|H6|H7 + Inputs!I7|I8|I9, C5|C6|C7/(multipliers))` — I-column = differential added to Baseline's base; if H overrides, back the base out of the overridden C.
- **C5/C6/C7**: `=IF(ISBLANK(Inputs!H7|H8|H9), H5|H6|H7*(multipliers), Inputs!H7|H8|H9)`.
- **C8:C16 (ratings)**: `=IF(ISBLANK(Inputs!H10..H18), (Inputs!C10..C16 + Inputs!I10..I16)*(1+0.02*$C$30)/(1+0.02*Baseline!$C$30), Inputs!H10..H18)` — differential + normalization (normalization lives in C here, in D for +Stat sheets; inert at C30=0).
- **D8:D11**: NOT wrapped in Comparison (plain `=C8+…`).
- **E-column (second race-flag set)**: `=IF(ISBLANK(Inputs!J26..J37), Inputs!E26..E37, Inputs!J26..J37)` — **J-column = race-flag overrides** (12 rows, 2 refs each; J20 "Apocalypse" is just a label).
- **O6:O9** anchored `=Baseline!O6..O9`; forward cascade P/Q/R/S/T identical to the +Stat pattern (§3), `T10=SUM(T6:T9)`.
- **Inputs H/I/J semantics** (Inputs-sheet rows): H = "Character Sheet" overrides across the whole mirrored config (rows 7–17 stats, 20–23 runeforge, 26–37 races, 39–85 DK talents, 87–129 Blood talents, 132–143 hero talents, 146–160 conditional variables); I = differentials, authored only for stats/ratings (I7–I16) and a few talent variables (I46, I61, I63, I89, I99, I102, I103, I105, I107, I119, I122, I123, I132, I133); J = race-flag overrides (J26–J37). All other H/I/J cells are labels/blank.
- Comparison verified 763/763 exact (with Inputs!H123=1.0 → Consumption on: N15 0.99966→0.99981, O15 324431→326198, P15 112067→111420, Q15 9.369M→9.363M, R15 11.518M→11.593M, S15 21.755M→21.818M).

---

## 5. EXCEL → TYPESCRIPT SEMANTICS

- **Empty cell in arithmetic = 0.** Load-bearing empties: B19/B21 (runeforge flags → Razorice/FC rows zeroed), C21, O25 (makes `(-O42/(O25-O42))=1`), O30/O31/O55/O62/O74/O76 (kills the would-be T42 cycle), W78 (+Stat Y77 operand), D102 (+Stat), Q7:Q9 (+Stat). **ISBLANK** is true only for a truly absent/never-written cell; a cell holding `""` or `0` is NOT blank. `<NO_CACHED_VALUE>` in the TSVs = blank.
- **SUM/MIN/MAX over ranges** skip text cells and treat blanks as 0/ignored; over direct ref args, blanks coerce to 0. All SUMs in this workbook are over ranges or computed expressions.
- **`^` is LEFT-associative** in Excel (`2^3^2 = 64`); **unary minus binds tighter than `^`** (`-2^2 = 4`); `%` postfix = `/100` and binds to the **preceding primary (paren group), not the whole quotient** — load-bearing in Outputs!I7: `ROUND((A−B)/(1−B)%, 2)` divides by the percent-scaled damage fraction (net ×100 effect), producing `(0.01%)`; also appears in N15's dead text branch. JS port: `Math.pow` calls with explicit parens, or `**` (also left-assoc in JS — but parenthesize anyway).
- **Comparisons return booleans; TRUE/FALSE coerce to 1/0** in arithmetic; `IF(cond,a)` with no else returns FALSE (→0). `AND/OR/NOT` variadic.
- **INT floors toward −∞** (JS `Math.floor`, NOT `Math.trunc`). **ROUND is half-away-from-zero** (differs from `Math.round` only for negatives; used only in N15's dead branch).
- **`&` concatenation / number→text coercion** (N15's dead branch, Outputs Pawn strings + I7): a number renders as its SHORTEST ROUND-TRIP decimal rounded to 15 significant digits HALF-AWAY-FROM-ZERO — NOT the correctly-rounded 15 digits of the exact binary value (proof: Outputs!D9, §2). Integers render plain (`MasteryRating=1`); nonzero |x| < 1e-4 render in scientific notation, uppercase `E`, signed exponent, 15 sig digits (`5.07528516668376E-13`); 0 → `0`. JS port: `String(x)` already yields the shortest round-trip decimal; then round that STRING to 15 significant digits half-up (decimal helper) — do NOT use `toPrecision`/`toFixed` (ties-to-even → wrong at `…25` boundaries like D9).
- **Doubles**: Excel cached values are IEEE-754 doubles, identical to JS `Number`. All ~9,600 verified cells match at ≤1e-9 relative — no epsilon tricks needed; use plain `===`-adjacent tolerances only where you re-derive.
- Function names are case-insensitive (`exp`, `sum` appear lowercase); `$` signs are no-ops; whitespace is insignificant (L5 contains spaces). Sheet names that need quoting appear quoted in formulas (`'+Armor'!T10`, `'+Weapon DPS'!$N$15` — the 10 +Stat sheets, referenced only from Outputs); `N()` (20 uses, Outputs C7:C16) passes numbers through, text/blank → 0.
- Text in arithmetic = `#VALUE!` error — never triggered in this workbook (all referenced cells are numeric or blank).
- No named ranges, no data validations, no charts anywhere; conditional formatting only on Outputs (vestigial, targets empty cells W15:W37/AA15:AA37).

---

## 6. HAZARD REGISTER (unresolved ambiguities + defaults)

| # | Hazard | Evidence | Recommended default |
|---|---|---|---|
| 1 | **Level-suppression inconsistency**: L14 uses `0.015*(C153-90)` (penalty 0 at level 90); F116/E157 use `0.015*(C153-80)` (penalty 15%). Both verified exact vs cache — the inconsistency is real in the model. | L14=0.3239229608 exact; F116/E157 exact | Preserve both literally; do NOT "fix" |
| 2 | H15 target-count swing-speed curve `(195.5+21.9*T-0.673*T^2)/195.5` (×1.109 @1 target, ×1.474 @5) — unexplained by any comment | H15=1.378599312 exact | Preserve; flag as patch-sensitive |
| 3 | 0.2/s cap applied to DS **heal** as well as Blood Shield (`X42=MIN(T42,0.2)*M42`) — questionable modeling | X42 exact | Preserve |
| 4 | O6 Highmountain additive tail `+E26*C152/2*C7*0.0003*30` | exact (E26=0 → inert) | Preserve |
| 5 | +Stat forward S6 omits the Consumption factor; S8/S9 omit Stoneform — would diverge from Baseline's reverse chain if C121 (Consumption) or C31 (Stoneform) were enabled | +Stat sheets exact at current config | Replicate +Stat sheets literally; document divergence risk |
| 6 | +Stat D8:D11 normalization `(1+0.02*C30)/(1+0.02*Baseline!C30)` is identically 1 (C30 same both sheets) | exact | Preserve literally (vestigial) |
| 7 | `Y77(+Stat) = sum(Y19:Y76)+W78` with W78 empty | exact (+0) | Preserve the +0 |
| 8 | 4–5 cells/sheet have no cached values (volatile/uncalculated: B19/B21/C21 etc.) — they evaluate to 0/blank | verifier skips them; all evaluate fine as blanks | Treat missing cached as blank; compute them |
| 9 | Comment/formula drift: N14 comment says "ratio of raw damage taken to external healing" but N15 = (O10−X10)/O10; ~17 comment talent names absent from row labels | — | Follow formulas, not comments |
| 10 | K52 (IBF row) holds the D&D-target-count helper consumed by O51/M51/etc. | exact | Keep mapping (or rename with a cross-reference note) |
| 11 | D10's second stat-comparison is `IF(C10>C9,0,…)` — constant 0 (vers-vs-haste never counts toward the "highest stat" bonus) — looks like a bug | exact | Preserve |
| 12 | Per-formula SUM-range exclusion sets differ (§1.3) — easy to "normalize" wrongly | all exact | Transcribe each range exactly |
| 13 | F35 orphan (Baseline only); +Stat scratch rows 79–199 dead | unreferenced | Omit or keep; no numeric effect |
| 14 | **Outputs anomalies — now VERIFIED bug-for-bug and quantified** (corrected variants computed by `verify_chains.py` "OUTPUTS BUG EVIDENCE" section): (a) Unreliable-EHP block D72:D81 normalizes with the R&C block's `MAX($C$59:$C$68)`=1468.012210591137 instead of its own `MAX($C$72:$C$81)`=3864.519343724102 → all 10 normalized weights inflated ×2.6325. Current → corrected: D72 Armor 1.13547916258499→0.43133366074453; D73 Strength 2.52793609627272→0.96028528436508; D74 Stamina 0.338627867387225→0.128634326796211; D75 Crit 2.63248446834645→**1** (becomes block max); D76 Haste 0.942334268729793→0.357963847483478; D77 Vers 1.59869094890837→0.607293592091944; D78–D80 5.07528516668376E-13→1.92794496138916E-13; D81 Dps 5.07528516668376E-12→1.92794496138916E-12. Corrected C82 Pawn: `( Pawn: v1: "BDK EHP(u)": Leech=1.92794496138916E-13, CritRating=1, Dps=1.92794496138916E-12, Strength=0.96028528436508, HasteRating=0.357963847483478, MasteryRating=1.92794496138916E-13, Stamina=0.128634326796211, Armor=0.43133366074453, Versatility=0.607293592091944 )`. (b) Mitigation C16 divides the Weapon-DPS delta by 10 though the probe is +1 (§3): raw weight 1.6307412964988721e-06 → corrected 1.630741296498872e-05 (×10; IF else-branch live, N15 = 0.9996783285014152 vs 0.9996620210884503); D16 0.171111075250752 → **1.0** (corrected C16 overtakes the old block max 9.530308275540466e-06 = Mastery); C17 Pawn `Dps=` 0.171111075250752 → 1 | Outputs 144/144 verified exact (bug-for-bug), incl. both anomalous blocks | Preserve bug-for-bug; flag both |
| 15 | Empty O25 makes T25's `(−O42/(O25−O42))=1` — if O25 were ever authored, BB cast math changes | exact | Preserve empty |

**Verification status**: ALL 13 data sheets (Baseline, Comparison, 10 +Stat, Outputs) fully verified exact — 9,598 of 9,647 formula cells (49 blank/no-cached), numeric at ≤1e-9 relative and Outputs' 7 string cells by exact string comparison (§2). Outputs' two known anomalies (#14) are verified bug-for-bug and quantified with corrected variants by `verify_chains.py`'s "OUTPUTS BUG EVIDENCE" section.
