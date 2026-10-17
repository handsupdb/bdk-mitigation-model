# Baseline Sheet Analysis — Complete Notes (work product for implementation threads)

Source: extracted/Baseline__formulas.tsv (1191 lines), Baseline__values.tsv, metadata.json (323 comments, dumped to baseline_comments_dump.txt). All refs Baseline-local unless `Inputs!` prefixed.

## 1. SECTION MAP
- B2 title. **B4-B15 Input Attributes** (C=char-sheet values, D="Averate Ratings", E="Diminished Ratings"; D/E mostly empty here — used by Comparison sheets)
- **B17-B21 Runeforging**: B19=Inputs!B21 (Razorice flag), B21=Inputs!B23 (Fallen Crusader flag) — both reference EMPTY Inputs cells → 0; show <NO_CACHED_VALUE>
- **B23-B35 Race**: C col = 13 race flags (=Inputs!C+2row); D col = 2nd race set (Pandaren…Vulpera), E col = their flags (=Inputs!E+2row)
- **B37-B83 DK class talents** (Rows 1-10): C=rank (=Inputs!C+2), D=variable (=Inputs!D+2; only D44/D59/D61 non-zero)
- **B85-B126 Blood spec talents** (Rows 1-10): C=rank, D=variable (D97=7 Foul Bulwark stacks, D105=5 Insatiable Blade, D117=0.8 Coagulopathy, D120=0.4 Bloodshot, D121=1 Consumption)
- **B127 Apex**: Dance of Midnight C127=4; E127/F127 derived (DoM uptime / DoM rune proc rate)
- **B129-B131 Hero Class**: Deathbringer C130=0 (D130=0.6), San'layn C131=1 (D131=0.85)
- **B133-B141** Deathbringer Talents (C) + San'layn Talents (D/E); G133/H134/H135 Deathbringer calcs; J133/K134 San'layn calcs
- **B143-B154 Conditional Variables** (all =Inputs!C+2): Overhealing C144=0.2, DTPS C145=400000, %Magic C146=0.2, %PhysAoE C147=0, %MagicAoE C148=0, CD Utilization C149=1, Relative AMS Util C150=0.4, CD Ability Delay C151=0.8s, #Targets C152=5, Target Level C153=90, Armor Constant C154=3966.55
- **B156-B158 Tier Set**: (2)Set C157=1 → D157/E157 derived; (4)Set C158=1
- **B160-B168 Color Legend** (info only)
- **G4-L15 Attribute Calculations** (§3)
- **G17-AB77 Abilities table** (~59 abilities rows 18-76; row 77 totals). Cols: G=name, H=AP coeff, I=Spec mult, J=Tooltip dmg, K=Overall dmg/cast, L=Priority dmg/cast, M=Healing/cast, N=Runes/cast, O=RP/cast, P=BoneShield/cast, Q=Cast time, R=Base CD, S=Effective CD, T=Casts/sec, U=Time util, V=Overall DPS, W=Priority DPS, X=HPS, Y=EHPS, Z=Runes/s, AA=RP/s, AB=BoneShield/s
- **N4-X15 Damage Taken Breakdown + Performance Measures** (§4)

KEY: entire left config block mirrors Inputs! with +2 row offset (C38=Inputs!C40 … C158=Inputs!C160). Baseline = calculation engine; Inputs = single source of truth.

## 2. ABILITIES TABLE — FORMULA CATALOG (distinct patterns)

**J (tooltip dmg)**: `=(J6*(1+E116)*(1+D157)+169*15/120*C24+C14*6)*H<row>*J10*L11*I<row>*(mods)`
= (ModifiedStr×(1+BloodiedBlade)×(1+2set) + Orc AP 169×15/120 + WeaponDPS×6) × APcoeff × versa × masteryAPmult × specMult × mods. (Row 23 auto-attack omits I; row 61 Raise Dead uses 4925×15/120×Orc.)

**H (AP coeff)**: literals or small products, "Source: Wowhead" per comments (H23=`5*C15/12*1.25*1.2`; H42=`1.5312*1.2*1.12`; H29=`0.3348*24/3*(1/(1-0.15*C107))` full-duration BP). **I (Spec mult)**: 1.15 (Blood +15%) or 1.0; I40=`1.48*1.15` (D&D).

**K (overall dmg/cast)**: `=J*J8*0.7*J14*(mods)` — crit × **0.7 enemy armor** × misc-dmg-mult. AoE rows multiply by `C152/SQRT(MAX(1,C152/8))` (full dmg to 8 targets, sqrt split beyond); L (priority) divides same back out. San'layn amp `(1+C131*0.05*MIN(1,5/C152))` ("Incite Terror" per comments). Razorice amp `(1+0.15*B19*(1+0.2*C63))` (B19=Razorice flag, C63=Unholy Bond). Bloodshot `(1+0.08*C120*D120)`. WoS amp `H135`. DRW rows K38/K39: composite = SUM of mirrored ability DPS (BB, DS, DC, HS, MR, VS) × (8+4×C110 Everlasting Bond hits) × 0.33 (DRW mirrors at 33%) + auto-attack swings + BP; ×(1+0.01×Orc)×(1+C110)×I38×(1+San'layn 5%)×DoM(1+2×3%×E127). K59 Pact of San'layn = SUM(ability DPS)×10s×0.15×0.15×targetsplit. K61 Raise Dead: ghoul swings `INT(J9*60/2+1)` + claw `(60*J9*10+25)/40*1.35`. K69 Soul Rupture = K64×10%×(targets−1)×1.05×SanguineGround. K75 WoS souls = `(J8+2)/2*(1+C152)`.

**M (healing/cast)**: default `=K*L12` (leech). Distinct: M26 BloodDraw `K*(1+L12)*1.25`; M27 BloodFeast `=V10/T19` (AMS absorb/cast); M29 BP `K*(1+0.85*C107+L12)*1.25`; M30 BloodShield `=MIN(J11*(MAX(5*0.2*T10*(1+0.05*C111),7/100*L7)*(1+0.15*C42))*J10*(1+0.15*C46)*(1+0.2*C115),(0.5+0.15*C114)*L7*MAX(1,T42/0.2)/(1+(T76*(10+2*C92))*(0.3+0.05*C92)))` — mastery × DS-heal-basis (MAX(20%×5s DTPS×(1+5% Voracious), 7% maxHP)) ×(1+15% ImpDS)×versa×(1+15%×GloomWard rank)×(1+20% IronHeart), capped (50%+15% BloodyRefl)×HP×MAX(1,DSrate/0.2)/VBamp; M32 Bloodworms `L7*0.5*0.15`; M35 Consumption = leech + `24/(1+C130)*V29*D121*0.25*(1+0.5*C107+L12)*1.25` + Carnage BS; M40 D&D = leech + Relish in Blood `AP*0.375*(D97+2*C104)*J10*J8*L11*C94*uptime`; M41 DeathPact `L7*(0.2+0.1*C62)*J10` (minus absorb per comment); M42 DS heal = leech + `MAX(5*0.2*T10*(1+0.05*C111),7/100*L7)*(1+C99*0.08*MIN((BB+HS)/DS,5))*J10*J15*(1+0.15*C42)` (Hemostasis 8%/stack max 5); M44 Bwonsamdi `K*(1+L12)`; M48 GotN `L7*0.2`; M50 HealingVial `J*J8*J15`; M51 HS = leech + LeechingStrike `(D&D-targets helper)*L7*0.0025*C95`; M55 Lifeblood `M42*0.2/(1+Hemostasis)`; M60 Permafrost `K23*0.5*(1+0.15*C46)*(1+C130)`; M66 RoS `L7*0.48*(1+0.2*C63)`; M68 SangBurst `K*(0.18+L12)`; M71 TotG `K*(1+L12)`; M72 Umbilicus `MIN(L7,V29*(10+2*C92)*6)*J10*(1+0.15*C46)`; M73 UnholyStr `L7*0.04*(1+0.2*C63)`; M74 VS = leech + LeechingStrike + `L7*0.02*J10`.

**N/O/P (resources/cast)**: O19 AMS RP `=AA19/T19` (=25×versa×(1+40% AMB)×(1+15%×GloomWard)); O22 ArcaneTorrent 20; O28 BloodMist `MIN(C152,5)*2*9`; P38 DRW BS `=D105*C105` (Insatiable Blade 5); N40 D&D runes `−1×PotEB-uptime`; O40 D&D RP `10×Relish-uptime`; **O42 DS RP cost `=(-45)+5*C91+IF(C42>0,5,0)+10*8*T26`** (−45 base, +5 Ossuary, +5 ImpDS, +80×BloodDraw casts); N43 DC −1 rune/O43 +10 RP/P43 +2 BS; P49 Gorefiend `MIN(C90*C152,6)`; N51 HS −1 rune, O51 `=15+2*C96×(D&D-targets helper)` (Heartbreaker); N57 MR −2 runes/O57 +20 RP/P57 +3 BS; O58 MindFreeze `10*C52` (IBF refund); N63 Reaper's Mark −2/O63 +20/P63 +3; O67 RunicAttenuation 3.

**Q (cast time)**: `=1.5/J9` (GCD 1.5s ÷ haste) for GCD abilities; Q35 Consumption `(1+0.5*D121)/J9`.

**R (base CD)**: literals (120/90/60/45/15/7.5/6/0.5/360) or PPM: R32=60/5, R44=60/3, R67=60/10.8, R73=60/3.

**S (effective CD)**: `=R+C151` (player delay 0.8s) typical; S19 AMS `R−20×C68+20×C81`; S20 AMZ `240−60×C67`; S23 autoattack `=H15`; S25 BB charges `1/((1/(R/J9))+(C113/((R/J9)/tickrate)))`; S32/S44/S73 `=R/1.13(/J9)` (BLP); S35 Consumption `R/(1+C125×22.5×1.1/60×1.13×J9)+C151`; S38 DRW `120−30×C105+C151`; S40 D&D `15−5×C131×E137−C82` (Desecrate −5s, Death's Echo −1s); S43 DC cast-time-stacking; S54 Lichborne `120−30×C130×C138−30×C72`; S63 Reaper's Mark `2×R/(2+C137)+C151`; S67 RunicAtt `1/(10.8×J9×1.13/60)`; S76 VB `R76/(1−AA42/5×C122×((O42−5×ImpDS)/O42))` (Red Thirst: RP spend shortens VB CD).

**T (casts/sec)**: default `=1/S×talent×C149` (CD util). Distinct: T19 AMS `1/S19×C149×C150` (×relative AMS util 0.4); T23 `=1/S23`; T24 BloodBeasts `1/S24×C131`; **T25 BB** `=MIN(1/S25,MAX((1−SUM(other time utils)−(runegen)×Q51/(−N51)+(RPgen)×Q42/O42×(−O42/(O25−O42)))/Q25×(−O42/(O25−O42)),(1+C130)/24−T47×C130×0.5))` — resource+GCD constrained; T27 BloodFeast `=T19×C112`; T28 BloodMist `=T38×C118`; T30 BloodShield `=T42`; T31 BloodyDemise `=T42/10×C158` (4-set: every 10th DS); T37 DoM runes `=F127`; T38 DRW `1/S38×C98×C149`; T39 DRW-DoM `IF(C127>3,1,0)×0.1×(T40+T43+T51+T57+T63)`; T40 D&D `=1/S40`; **T42 DS `=−(SUM(AA19:AA41,AA43:AA76))/O42`** — ALL RP generated ÷ DS net cost; T43 DC `MIN(1/S43,(L15−BSconsumption)/2)×D87`; T46/47 Exterminate `=T64×(3−C137)+T38`; **T51 HS `=MIN((L9+SUM(Z19:Z50)+SUM(Z52:Z76))/(−N51),MAX((1−SUM(time utils)+RPgen×Q42/O42)/Q51×(−O42/(O51−O42)),0))`** — rune-constrained; T52 IBF `1/S52×C38×C149`; T53 Infliction `=C131×T74`; T55 Lifeblood `=T42×C109`; T57 MR `=MAX((L15−SUM(AB…))/3,T47)` — Bone-Shield-charge-constrained; T59 PactSan'layn `=T24×C131×E141`; T60 Permafrost `=T23×C54`; T62 Razorice `=B19×(T23+T35×C152+T42×…+T51×…+T57)` (procs per swing+abilities); T63 Reaper's Mark `1/S63×C130`; T68 SangBurst `=T28×C123`; T69 SoulRupture `=T64`; T72 Umbilicus `=T76×C126`; T73 UnholyStr `1/S73×B21`; **T74 VampiricStrike** `=C131×((T38×(8+C110×4))×T51+(1−T38×(8+C110×4))×((0.35+0.05×14/S40×E136)×T42+(E140×0.35×0.15)×T42))` — replaces HS during DRW, else 35% of DS casts (+SanguineScent); T75 WoS `=T63`; T76 VB `1/S76×C89×C149`.

**U** `=T×Q` (time util; U77=SUM=1 — GCD budget full). **V/W** `=T×K` / `=T×L` (V25/W25 add Boiling Point HS→BB resets `(T25+C108×T51×(1−(1−0.15)×(1−0.15×MAX(4,C152−1)))×1.5)`; V29 BP `=K29/24×(1+C130)`; V51/W51/V74/W74 embed Bloodied Blade extra swings + DoM procs — huge). **X** `=T×M` (X30 BloodShield `=MIN(T30,0.2)×M30` — capped 1 DS/5s; X42 DS `=MIN(T42,0.2)×M42` same cap; X34 BrushItOff `=T10×0.02×E33` KulTiran; X60 Permafrost adds Exterminate shielding `+C130×T47×(K46+K47)×0.1×(1+0.15×C46)×C54`). **Y** `=X×(1−C144)` (overheal 20%); Y30/Y31/Y32/Y41/Y60/Y72 = X (assumed no overheal). **Z/AA/AB** `=T×N/O/P` (Z57 MR `=(T57−T47/2)×N57`).

**Row 77 totals**: U77=1, V77=324430.93 (Overall DPS), W77=112067.47 (Priority DPS), X77=442136.66 (HPS), Y77=384443.55 (EHPS), Z77=−0.457 (net runes/s), AA77=0 (net RP/s — by construction of T42), AB77=0.32692 (Bone Shield consumption/s = L15).

## 3. ATTRIBUTE CALCULATIONS (G5-L15)
- H5 BaseArmor `=C5/(1+C21*0.05*(1+0.2*C63))` (strip Stoneskin Gargoyle 5% × Unholy Bond 20%)
- J5 ModifiedArmor `=(C5*1.45+(J6*(1+E116)*(1+D157)*1.8)+IF(E28=3,1,0)*1.13*(1-exp(-J9*12/60))*(J6*(1+E116)*(1+D157)*0.02*J10))*(1+0.06*C75)` — 1.45×sheet armor + 1.8×str ("Reinforced Bones"/Bone Shield armor per comment) + racial, ×(1+6% Runic Protection)
- L5 PhysDR `=J5/(J5+C154)` — armor/(armor+3966.55)
- H6 BaseStr `=C6/(1+C21*0.05*(1+0.2*C63))-C34*33`; J6 ModStr `=(C6+E32*252*8/120+E34*50)*(1+B21*1.13*(1-exp(-3*J9*15/60))*0.15*(1+0.2*C63))*(1+0.03*C77*(1-0.85^(8*L9)))*(1+0.1*12*(1/S40)*C131*(swing-uptime-IF-chain))*(1+0.1*T69*8*IF(C152=1,1,0))` — Fallen Crusader 15% (uptime 1.13×(1−exp(−3×haste×15/60))), Rune Mastery 3%/rune (cap 0.85^(8×runeregen)), San'layn str-from-D&D 12×0.1×D&D-uptime, Soul Rupture
- L6 ParryFromStr `=(J6-622)/19130`; L8 ParryFromCrit `=E8/5200/(1+0.02*C30)`
- H7 BaseStam `=(C7/(1+C21*0.05*(1+0.2*C63))/1.05/(1+0.2*C55)/(1.4))-C26*99` (strip SSG, 5%, Veteran 20%, **Blood Presence 1.4× stam**, Tauren); J7 TotalHealth `=C7*20` (20 HP/stam); L7 ModHealth `=(J7+racial)*(1+0.01*C97*(D97+2*C104))` (Foul Bulwark 1%×(7+2) stacks)
- H8 Crit `=E8/4600+0.05+(C28+C32+C35)*0.01+racial`; J8 CritMult `=1+H8*(1+2*0.02*(C26+C31))`
- H9 Haste `=(1+(C29+C33)*0.01)*E9/4400+(C29+C33)*0.01`; J9 HasteMult `=(1+H9)*(1+C27*0.15/18)*(1+0.1*C104)*(1+0.02*C49)*(1+0.01*K134)` (Troll Berserking 15%×10/180, ImpBS 10%, Unholy Momentum 2%/rank, San'layn 1%×effective stacks); L9 RuneRegen `=3/10*J9`
- H10 Vers `=E10/5400+(E26+E33)*0.01`; J10 `=1+H10`; L10 DmgTakenMult `=1-H10/2`
- H11 Mastery `=0.16+E11/2300+0.002*(C131*K134)`; J11 BloodShieldMult `=H11`; L11 APMult `=1+H11/2`
- H12 Leech `=E12/6900+C71*0.03+C131*E138*0.02`; L12 ModLeech `=J12+C111*0.15*MIN(8*T42,1)+0.06*(10+2*C72)*T54*(1+C131*E138)` (Voracious 15% capped, Lichborne 6%×10s×casts)
- H13 Avoidance `=E13/3680+C70*0.03`; J13 AoEDmgTakenMult `=1-H13`
- L13 TotalParry `=622/19130+0.03+(L6+L8)/((L6+L8)+1/0.94)+0.05*8*T28` — **parry DR curve p/(p+1/0.94)**; H14 Dodge `=0.03+0.02*C32`
- J14 MiscDmgMult: VoidElf 5%×uptime, Brittle 6%×(1−0.85^(5/tick)) (15%/tick, 5s), Coagulopathy 5%, Sanguine Ground 6%×D&D-uptime, DoM 2×3%×E127
- L14 AttackAvoidance `=MAX(L13-0.015*(C153-90),0)+MAX(H14-0.015*(C153-90),0)+MAX(0.03-0.015*(C153-90),0)` — **1.5%/level above 90** (but F116/E157 use −80! inconsistency)
- H15 AveWeaponSpeed `=C15/(J9*(1+0.06*(3+1.5*C130*C136)*C59*D59))/((195.5+21.9*C152-0.673*C152^2)/195.5)` — Icy Talons 18%×0.9 (+Dark Talons 9% if Deathbringer) ÷ **unexplained target-count curve** (1.109 at T=1, 1.474 at T=5, 1.675 at T=8)
- J15 MiscHealMult: VoidElf, Unholy Momentum 2%×rank, Insidious Chill 15%×(5+2×AMB)×AMS-uptime, Lightforged 1%
- L15 BoneShieldConsumption `=IF(C127=4, 1/(2.5+(2/(1-(L14+0.3*(0.151+0.367*J8-0.0791*J8^2+0.0086*J8^3)))-1+IF(C152=1,0.5,0))/C152), 1/(2.5+(2/(1-(L14+0.3*T38*(8+C110*4)))-1+IF(C152=1,0.5,0))/C152))` — Bone Shield charge drain: 2.5s recharge + boss 2s swings ÷ (1−avoidance-ish) ÷ targets; DoM branch uses crit-multiplier cubic

## 4. DAMAGE-TAKEN CASCADE (N4-X15) — THE CORE
Direction: **T (fully mitigated = actual taken, anchored to C145 input) → S (misc CDs) → R (IBF) → Q (DRW parry) → P (passives) → O (unmitigated)**. Each step DIVIDES OUT a layer ("reverse calculated" per comments).
- T10 `=C145` (400k); T6 physST `=(1-C146-C147)*T10`; T7 physAoE `=C147*T10`; T8 magST `=(C146-C148)*T10`; T9 magAoE `=C148*T10`
- S=T (misc col pass-through); R6 `=S6/(1-(T70*8)*0.1)/(1-(T26*8)*0.1)/(1-(T35*(Q35+8/2^(D121-1)))*(0.05*D121))` (Stoneform/BloodDraw 10%×8s, Consumption 5%)
- Q6 `=R6/(1-(T52*8)*(0.3+0.1*E139))` — IBF (30%+10% Bloody Fortitude)×8s×casts/s
- P6 `=Q6/(1-((1-(1-(T38*(8+C110*4)))*(1-IF(C127>3,1,0)*(1-0.875^(8*(T40+T43+T51+T57+T63)))))*MIN(0.3/(1-L14),1)))` — DRW parry: 30% parry during DRW (8+4s EB) + DoM 12.5%/ability-cast uptime, capped 30%/(1−avoidance)
- O6 physST unmitigated `=P6/(1-L14)/(1-L5)/L10/(1-0.01*E32)/(1-0.2/C152*C74)/(1-C51*0.12/C152*uptime)/(1-C135*C130*D130*0.075)/(1-C131*E136*10/S40*0.08)/(1-F116)/(1-E157)/(1-IF(C127>1,1)*0.06*E127)/(1-(0.04*10*(1/S40)*C100*uptime))/(1-C120*0.025)+E26*C152/2*C7*0.0003*30` — divides out avoidance, armor, vers, DID 1%, Insidious Chill 20%/targets, Enfeeble 12%/targets, Rune Carved Plates 7.5%, Blood-Soaked Ground 8%×D&D-uptime, Bloodied Blade parry-DR (F116), 2-set parry-DR (E157), DoM 6%×uptime, PotEB 4%×D&D-uptime, Bloodshot 2.5%; + Highmountain additive
- O8 magST `=P8/L10/(Enfeeble)/(RCP)/(1-0.08*C80 NullMagic)/(DoM)/(PotEB)/(Bloodshot)` — no armor/avoidance vs magic
- U8 AMZ heal `=T8*(T20*(6+2*C67))*0.15` (15% of magic dmg during AMZ 6+2s); V8 AMS heal `=IF(T8-U8-T19*(L7*0.3*J10*(1+0.4*C68)*(1+0.15*C46))>0, T19*(…), T8-U8)` — AMS absorbs 30%HP×versa×(1+40% AMB)×(1+15%×GloomWard rank), capped by magic damage
- W10 OtherHealing `=(Y77+C27*0.0011*L7*(1-C144))` — total EHPS + Troll regen
- **X10 EHRPS** `=(MAX(T10-U10-V10-W10,0)*(1-T76*(10+2*C92))+MAX(T10-U10-V10-W10*(1.3+0.05*C92),0)*(T76*(10+2*C92))/(1.3+0.05*C92))/(1+0.02*C49)` — residual damage after AMZ+AMS+self-healing, split into non-VB and VB windows (VB: 10+2×IVB s duration, healing amp 1.3+0.05×IVB; excess VB healing discounted)
- **N15 MitigationFactor** `=IF(X10=0,"Self-Sufficient (+…"&Round(−(residual)/O10%,2)&"%)",(O10-X10)/O10)` — **(UDTPS−EHRPS)/UDTPS** per docx; self-sufficiency branch shows surplus %
- **Q15 ReliableEHP** `=L7/(1-(1-(1-L5)*(1-C131*E136*10/S40*0.08))*(physShare)/(physShare+T8+T9))/L10*(0.7+0.3/(1-0.15*C79-0.05*IF(C79>0,1,0)))/(1-RCP)/(1-(0.08*C80)*(1-physShareAdj))/(1-(0.05*C131*E136)*(physShareAdj))` where physShare = (T6/(1-L14)/(1-DRWparry)+T7)/(1-L5) — health ÷ effective taken-damage multiplier using ONLY always-on mitigation (armor, avoidance, vers, WotN `0.7+0.3/(1-30%)`, BSG, RCP, Null Magic)
- **R15 R&C EHP** = Q15 structure + `/(T10/(Q10+P7+P8+P9))*(1+T76*(10+2*C92)*0.3)` — adds IBF/misc-CD mitigation and VB +30% healing as "controllable"
- **S15 UnreliableEHP** `=L7*O10/T10*(WotN)*(1+T76*(10+2*C92)*0.3)` — health × (unmitigated/fully-mitigated) — treats ALL mitigation incl. random avoidance as guaranteed

## 5. HELPER CELLS (left block, locally computed)
- E116 BloodiedBlade eff str buff (Bone-Shell-swing-rate model, 0.02/0.01 coeffs, target decay 0.8/3^(T−1)); F116 BloodiedBlade eff parry DR (marginal avoidance ÷ (1−avoidance))
- E127 DoM "Average Weapon Count" `=T38*(8+C110*4)*(1+C110)+IF(C127>3,1,0)*8*0.125*(T40+T43+T51+T57+T63)`; F127 DoM rune proc rate (rank-4 branch, 1−(1−uptime)/(3+2/(L13+0.3)−1+0.5ifST)/targets)
- H134 Reaper's Mark stacks `=MIN(40,1+12*(all ability hit rates))`; H135 WoS amp `=1+C130*(0.05*15+0.05*17*H8)*T75`
- K134 San'layn effective stacks `=C131*7*(1+2*T38*(8+C110*4))*D131` (7 stacks ×2 during DRW ×0.85)
- D157 2-set eff str `=C157*(0.025+0.1*T42)`; E157 2-set eff parry DR (marginal)
- F35 `=H35/H25` (Consumption/BB AP coeff ratio) — orphan, unreferenced in Baseline

## 6. CONSTANTS TABLE (value, cell, meaning, patch-sensitive?)
| Const | Cell(s) | Meaning | Patch? |
|---|---|---|---|
| 3966.55 | C154 (Inputs!C156) | Armor DR constant K (armor/(armor+K)) for level-90 target | YES |
| 1.45 | J5 | Sheet-armor multiplier (Blood Presence/plate) | YES |
| 1.8 | J5 | Armor per point strength ("Reinforced Bones"/Bone Shield armor) | YES |
| 20 | J7 | HP per stamina | YES |
| 1.4 / 1.05 | H7 | Blood Presence 40% stam / 5% stam (divided out) | YES |
| 622, 19130 | L6, L13 | Parry-from-strength base & divisor | YES |
| 1/0.94 | L13 | Parry DR curve coefficient | YES |
| 4600/4400/5400/2300/6900/3680/5200 | H8/H9/H10/H11/H12/H13/L8 | Rating→% conversions (crit/haste/vers/mastery/leech/avoidance/parry-from-crit) | YES |
| 0.16 | H11 | Base Blood Shield mastery 16% | YES |
| 0.05 / 0.03 | H8 / H14,L13 | Base crit 5% / base dodge & parry 3% | YES |
| 0.015 | L14, F116, E157 | Avoidance suppression per boss level above player | YES — **inconsistent: L14 uses (C153−90), F116/E157 use (C153−80)** |
| 1.13 | many | RPPM bad-luck-protection multiplier (S32/S44/S73 comments) | YES |
| 0.75 / 0.85 / 0.875 | uptime models | 25%/15%/12.5% proc chances (uptime=1−(1−p)^(events)) | mechanic |
| 0.7 | K-col | Enemy armor: 30% reduction on physical damage dealt | YES |
| 1.5 | Q-col | GCD seconds | YES |
| 3/10 | L9 | Rune regen: 3 runes per 10s ×haste | YES |
| 45/5/5 | O42 | DS RP cost 45, Ossuary refund 5, ImpDS refund 5 | YES |
| 0.2, 0.07, 5s | M30/M42 | DS heal: 20% of dmg taken in last 5s, min 7% maxHP | YES |
| 0.2/s cap | X30, X42 | DS heal & Blood Shield counted max 1 per 5s | modeling choice |
| 0.33, 8+4 | K38 | DRW mirrors 33% dmg, 8s+4s Everlasting Bond | YES |
| 12, 40 | H134 | Reaper's Mark 12s window, 40 stack cap | YES |
| 7, 0.85 | K134 | San'layn 7 stacks ×0.85 uptime | YES |
| 195.5, 21.9, 0.673 | H15 | Target-count attack-speed curve — UNEXPLAINED by comments | YES — fragile |
| 2.5, 2 | L15 | Bone Shield 2.5s recharge, 2s boss swing | YES |
| 0.151+0.367x−0.0791x²+0.0086x³ | L15 | DoM Bone-Shell crit-multiplier cubic | YES — fragile |
| 10.8, 3 | R67, R73 | Runic Attenuation 10.8 PPM, Unholy Strength 3 PPM | YES |
| 25, 0.3 | O19, V8 | AMS 25 RP gen, 30% HP absorb | YES |
| 0.15 | U8 | AMZ heals 15% of absorbed | YES |
| 0.48/0.2/0.2/0.04/0.075/0.02/0.0025 | M66/M41/M48/M73/M32/M74/M51 | Racial/talent heal fractions of maxHP | YES |
| 0.7+0.3/(1−0.3−0.05) | Q15/R15/S15 | WotN EHP factor (C79=2 ranks → 30%+5%) | YES |
| 0.3+0.1, 8 | Q6 | IBF 30%+10% Bloody Fortitude, 8s | YES |
| 0.08/0.075/0.08/0.06/0.025/0.05 | O6/O8 | Null Magic 8%, RCP 7.5%, BSG 8%, DoM 6%, Bloodshot 2.5%, Consumption 5% | YES |
| 0.06/0.05/0.15/0.12/0.2 | J14/J15 | Sanguine Ground 6%, Coagulopathy 5%, Brittle 6% (15% proc), Enfeeble 12%, Insidious Chill 20% | YES |
| 1.3+0.05×rank, 10+2×rank | X10 | VB healing amp 30%+5%/IVB rank, duration 10+2s/IVB | YES |
| 169×15/120, 4925×15/120 | J-col | Orc racial AP, Raise Dead AP | YES |
| 6 | J-col | Weapon AP = DPS×6 | YES |
| 1.15 | I-col | Blood spec +15% damage | YES |
| 24 | V29 | Blood Plague damage window (K29/24) | YES |
| 6 | M72 | Umbilicus = BP DPS × VB duration × 6 | YES |

## 7. METHODOLOGY NOTES (from 323 comments — key ones)
- G4: "Many of these values include average proc and buff modifiers, so they may not match character sheet values."
- O/P/Q/R/S cols: "Reverse calculated" — model anchors on taken DTPS (C145) and divides out each layer to get UDTPS
- H-col sources: "Source: Wowhead" (tooltips), "in-game observations/testing" (H61 Raise Dead, H71 Touch of Grave)
- 0.7 = "Enemy Armor" (K23 comment); 1.13 = "bad luck protection" (S32/S44/S73)
- T25: "Blood Boil casts are normally first ability to be throttled if not enough cast time… at a minimum, Blood Plague is maintained"
- T42: "total Runic Power Per Second (excluding Death Strike) ÷ RP cost; if 3+ targets and damage prioritized, DS throttled when cast time limited"
- T51: "rune regeneration minus other usage; Heart Strikes throttled after Blood Boils"
- T57: "Cast frequency based on net Bone Shield consumption"; P38: "assumed no Marrowrend during DRW"
- S33: "Blood Shield assumed to only survive a single damage instance per Death Strike" (the 0.2/s cap)
- M32: "worms assumed to proc at 50% player health"
- L15: "Dance of Midnight requires an approximation function for overall DRW uptime to avoid a circular feedback loop" (E127)
- E127 "Average Weapon Count"; F127 "DRW Parry Proc Rate"; E116/F116 & D157/E157 "Effective Strength Buff"/"Effective Parry DR"
- M41: "Healing after subtracting the healing absorb" (Death Pact)
- K59: "10% of shadow DPS over 10 seconds; Bloodshot, versatility, and incite terror double dip"
- T74: "These casts are taken out of Heart Strike casts" (VS replaces HS)
- N14: "Mitigation Factor - The Ratio of Raw Damage Taken to External Healing Required" (comment stale vs formula (O10−X10)/O10)
- Comments use talent names NOT in current row labels: Incite Terror, Swift and Painful, Visceral Regeneration, Essence of the Blood Queen, Thrill of Blood, Heartrend, Grim Reaper, Echoing Fury, Corrupted Blood, Inevitable, Frigid Resolve, Reinforced Bones, Blood Fortification, Armor Skills, Painful Death, Spec Aura, Blooddrinker — sheet evolved; comments partially stale

## 8. FRAGILE / OBSCURE PATTERNS
1. **Level-suppression inconsistency**: L14 uses 0.015×(C153−90); F116/E157 use 0.015×(C153−80). With C153=90: L14 penalty=0, F116/E157 penalty=15%. One hardcoded player level is stale.
2. **H15 target-count attack-speed curve** (195.5+21.9T−0.673T²)/195.5 — unexplained by comments; even 1 target gets ×1.109. Patch-sensitive, likely a Midnight mechanic (possibly Cleaving Strikes rework or tier).
3. **DS heal & Blood Shield 0.2/s cap** (X30/X42 MIN(T,0.2)) — deliberate modeling choice ("Blood Shield survives single damage instance"), but caps DS HEAL too — questionable.
4. **Circularity avoided via approximations**: E127 (DoM uptime) is an explicit approximation to avoid circular feedback (L15 comment); T42 depends on AA19:AA76 which depends on T19/T22 etc. — evaluation order matters for reimplementation.
5. **K52 (IBF row) holds a D&D-target-count helper** (used by Brittle/Sanguine Ground/Leeching Strike scaling) — data stored in semantically unrelated cell.
6. **O6 Highmountain tail** `+E26*C152/2*C7*0.0003*30` — additive unmitigated-damage term, unexplained.
7. **B19/B21 runeforge flags reference EMPTY Inputs cells** (Inputs!B21/B23) → evaluate 0; <NO_CACHED_VALUE> in TSVs. Razorice/Fallen Crusader effectively OFF in baseline despite J6/K62 formulas supporting them.
8. **Comment/formula drift**: N14 comment describes UDTPS/EHRPS ratio; formula is (UDTPS−EHRPS)/UDTPS. Several comment talent names don't exist in row labels.
9. **V25/W25/X25 Boiling Point** adds HS-reset BB casts into V/W but X25 only adds 0.15×1.5 portion — asymmetric.
10. **S43 Death's Caress** cast-time-stacking formula (4×Q43≥R43 nested IFs) — obscure charge model.
11. **T62 Razorice** proc model multiplies by B19 (empty→0) — entire row zeroed in baseline.
12. **F35 orphan** (=H35/H25, unreferenced).

## 9. DOWNSTREAM CONSUMERS (verified via grep)
- Outputs pulls: Baseline!C92 (×66, IVB rank), T10 (×55), W10/V10/U10 (×44 each), O10 (×22), N15/O15/P15/Q15/R15/S15 (×1 each)
- Comparison pulls: Baseline!H5/H6/H7 (base armor/str/stam) and O6/O7/O8/O9 (unmitigated damage rows) — recomputes cascade with stat delta
- +Stat sheets pull same H5/H6/H7 + O6-O9 pattern (11 refs each per crossrefs.txt)

## 10. KEY OUTPUT VALUES (Baseline, cached)
UDTPS O10=3,720,571.088 | Fully-mitigated DTPS T10=400,000 (=C145) | EHRPS X10=1,257.4746 | Mitigation Factor N15=0.9996620211 | Reliable EHP Q15=9,369,364.5 | R&C EHP R15=11,517,616.6 | Unreliable EHP S15=21,754,755.5 | HPS X77=442,136.66 | EHPS Y77=384,443.55 | Overall DPS V77=324,430.93 | Priority DPS W77=112,067.47