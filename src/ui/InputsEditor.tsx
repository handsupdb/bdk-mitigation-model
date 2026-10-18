/**
 * Inputs editor: editable fields over the Inputs sheet's saved profile.
 *
 * One SECTIONS entry renders per group, in sheet order:
 *   - Character Attributes  (rows 7-17:    label `Inputs!B<row>`, value `Inputs!C<row>`)
 *   - Runeforging           (rows 19-23:   one checkbox per 0/1 flag cell, named
 *                                         by the row-20/row-22 label cells)
 *   - Race                  (rows 25-37:   one dropdown over the 24 race flag
 *                                         cells in columns C and E)
 *   - DK Class Talents      (rows 40-85:   label B, rank C, plus a variable D
 *                                         input only where the sheet has one)
 *   - Blood Talents         (rows 88-129:  same label/rank/variable pattern)
 *   - Hero Class            (rows 132-133: label B, value C, uptime D)
 *   - Deathbringer Talents  (rows 136-141: label B, value C)
 *   - San'layn Talents      (rows 138-143: label D, value E)
 *   - Conditional Variables (rows 146-156: label B, value C; the Armor
 *     Constant row carries a per-difficulty hint note under its field)
 *   - Tier Set              (rows 159-160: label B, value C)
 *
 * Runeforging and Race are 0/1 flag blocks rather than label/value rows, so
 * they render from their own specs — checkboxes and a single-select dropdown
 * — between Character Attributes and DK Class Talents, in sheet order.
 *
 * After the baseline groups come the Comparison profile sections — the
 * Inputs sheet's G/H/I columns: G mirrors the B labels, H holds absolute
 * 'Set' overrides, I holds '+/-' differentials, and a blank cell inherits
 * the baseline value. Each row renders a 'Set' input (`H<n>`) beside its
 * G-column label and, where the Comparison module also reads it, a '+/-'
 * input (`I<n>`) indented below. The Conditional Variables and Tier Set
 * groups list only the rows whose H/I cells the generated Comparison
 * module actually reads (H147 is never read; no I differential in those
 * rows is read at all).
 *
 * Each NumberField/CellInput edits one Inputs cell; the override is keyed
 * by the bare Inputs ref (`'C7'`, `'H123'`), exactly as
 * `useEngine`/`evaluateWithInputs` expect.
 * The committed value is always `override ?? savedValue` (empty string when
 * null). While typing, the field shows a local draft so intermediate states
 * like `'0.'` or `'-'` are not clobbered by the committed value re-render;
 * the draft is dropped on blur. An empty input clears the override, so the
 * field inherits the saved profile value again.
 *
 * NOTE: the cell-ref prop is named `cellRef`, not `ref` — React 19 hoists a
 * string `ref` prop into the fiber and throws ("Expected ref to be a
 * function, an object returned by React.createRef(), or undefined/null."),
 * so a prop literally named `ref` cannot carry a cell ref like 'C7'.
 */
import { Fragment, useState } from 'react'
import type { ChangeEvent, CSSProperties, ReactNode } from 'react'
import type { CellValue, Grid } from '../engine/cells'

/** Where one editor section lives on the Inputs sheet. */
interface SectionSpec {
  /** Header label cell for the section title. */
  titleRef: string
  /** Title when the header cell is missing or blank. */
  fallbackTitle: string
  /** First data row. */
  firstRow: number
  /** Last data row (inclusive). */
  lastRow: number
  /** Column holding each row's label; defaults to `'B'`. */
  labelCol?: string
  /** Column holding each row's primary editable value; defaults to `'C'`. */
  valueCol?: string
  /** Optional second editable column per row (talent variable / uptime). */
  variableCol?: string
  /** Header cell naming the variable column (e.g. `Inputs!D39` -> 'Variable'). */
  variableTitleRef?: string
  /** Variable field label when its header cell is missing or blank. */
  fallbackVariableLabel?: string
  /** Render the variable input even when its saved cell is null. */
  variableAlways?: boolean
  /**
   * Per-row label fallbacks, indexed by `row - firstRow`. Optional for the
   * data-driven sections: the grid itself carries every label there, so a
   * missing label falls back to `Row <n>`.
   */
  fallbackLabels?: string[]
  /**
   * Per-row hint text, keyed by row number: a small muted note rendered
   * under that row's value field (e.g. the Armor Constant difficulty note).
   */
  rowHints?: Record<number, string>
}

const SECTIONS: SectionSpec[] = [
  {
    titleRef: 'Inputs!B6',
    fallbackTitle: 'Character Attributes',
    firstRow: 7,
    lastRow: 17,
    fallbackLabels: [
      'Armor',
      'Strength',
      'Stamina',
      'Critical Strike Rating',
      'Haste Rating',
      'Versatility Rating',
      'Mastery Rating',
      'Leech Rating',
      'Avoidance Rating',
      'Base Weapon DPS',
      'Base Weapon Speed',
    ],
  },
  {
    titleRef: 'Inputs!B39',
    fallbackTitle: 'DK Class Talents',
    firstRow: 40,
    lastRow: 85,
    variableCol: 'D',
    variableTitleRef: 'Inputs!D39',
    fallbackVariableLabel: 'Variable',
  },
  {
    titleRef: 'Inputs!B87',
    fallbackTitle: 'Blood Talents',
    firstRow: 88,
    lastRow: 129,
    variableCol: 'D',
    variableTitleRef: 'Inputs!D87',
    fallbackVariableLabel: 'Variable',
  },
  {
    titleRef: 'Inputs!B131',
    fallbackTitle: 'Hero Class',
    firstRow: 132,
    lastRow: 133,
    variableCol: 'D',
    fallbackVariableLabel: 'Uptime',
    variableAlways: true,
  },
  {
    titleRef: 'Inputs!B135',
    fallbackTitle: 'Deathbringer Talents',
    firstRow: 136,
    lastRow: 141,
  },
  {
    titleRef: 'Inputs!D135',
    fallbackTitle: "San'layn Talents",
    firstRow: 138,
    lastRow: 143,
    labelCol: 'D',
    valueCol: 'E',
  },
  {
    titleRef: 'Inputs!B145',
    fallbackTitle: 'Conditional Variables',
    firstRow: 146,
    lastRow: 156,
    fallbackLabels: [
      'Overhealing',
      'Damage Taken Per Sec.',
      '% Magic Damage Taken',
      '% Phys AoE Damage Taken',
      '% Magic AoE Damage Taken',
      'Defensive Cooldown Utilization',
      'Relative AMS Utilization',
      'Cooldown Ability Delay',
      'Number of Targets',
      'Target Level',
      'Armor Constant',
    ],
    rowHints: {
      156: 'Set per content difficulty — 12.1.5: 4531.03 (Mythic+) / 5656.07 (Mythic Raid). The saved profile\'s 3966.55 is stale.',
    },
  },
  {
    titleRef: 'Inputs!B158',
    fallbackTitle: 'Tier Set',
    firstRow: 159,
    lastRow: 160,
  },
]

/** One 0/1 flag cell plus the label cell that names it. */
interface FlagSpec {
  /** Bare Inputs ref of the 0/1 flag cell (e.g. `'B21'`). */
  ref: string
  /** Grid key of the label cell naming the flag (e.g. `'Inputs!B20'`). */
  labelRef: string
  /** Label when the label cell is missing or blank. */
  fallbackLabel: string
}

/**
 * Runeforging flags: row 21 cells B/C/D/E (labels in row 20) and row 23
 * cells B/C/D (labels in row 22). The saved profile has Sanguination (C21)
 * on; the other six cells are blank.
 */
const RUNEFORGE_FLAGS: FlagSpec[] = [
  { ref: 'B21', labelRef: 'Inputs!B20', fallbackLabel: 'Razorice' },
  { ref: 'C21', labelRef: 'Inputs!C20', fallbackLabel: 'Sanguination' },
  { ref: 'D21', labelRef: 'Inputs!D20', fallbackLabel: 'Spellwarding' },
  { ref: 'E21', labelRef: 'Inputs!E20', fallbackLabel: 'Apocalypse' },
  { ref: 'B23', labelRef: 'Inputs!B22', fallbackLabel: 'Fallen Crusader' },
  { ref: 'C23', labelRef: 'Inputs!C22', fallbackLabel: 'Stoneskin Gargoyle' },
  { ref: 'D23', labelRef: 'Inputs!D22', fallbackLabel: 'Unending Thirst' },
]

/** Race flag rows: two 12-row columns of 0/1 cells, rows 26-37. */
const RACE_FIRST_ROW = 26
const RACE_LAST_ROW = 37
/** Each race column: flag cells in `valueCol`, labels in `labelCol`. */
const RACE_COLUMNS: { valueCol: string; labelCol: string }[] = [
  { valueCol: 'C', labelCol: 'B' },
  { valueCol: 'E', labelCol: 'D' },
]
/**
 * Fixed labels for race label cells the sheet leaves blank: the 24th slot
 * (D37 names E37) carries no label in the saved profile, so it takes the
 * next playable race's name; any other missing label falls back to
 * `Row <n>`.
 */
const RACE_FALLBACK_LABELS: Record<string, string> = { D37: 'Dracthyr' }

/** Prefer the grid's own label string; fall back to the fixed label. */
function pickLabel(v: CellValue | undefined, fallback: string): string {
  return typeof v === 'string' && v.trim() !== '' ? v : fallback
}

/** Render a cell as input text; blank (null/undefined) -> empty string. */
function toText(v: CellValue | undefined): string {
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v
  return ''
}

/** Props for one editable numeric Inputs cell. */
interface NumberFieldProps {
  /** Field label text (from `Inputs!B<row>`). */
  label: string
  /** Saved profile value (from `Inputs!C<row>`). */
  savedValue: CellValue | undefined
  /** Current override for this cell, if one is set. */
  override: CellValue | undefined
  /** Bare Inputs cell ref, e.g. `'C7'` (see the file note on naming). */
  cellRef: string
  /** Set (or replace) the override. */
  onSet: (ref: string, v: number) => void
  /** Remove the override, restoring the saved value. */
  onClear: (ref: string) => void
}

const inputStyle: CSSProperties = {
  width: '7rem',
  flexShrink: 0,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  fontSize: '0.85rem',
  padding: '0.25rem 0.4rem',
  border: '1px solid #ddd',
  borderRadius: 6,
  background: '#fff',
  color: '#333',
}

/** Amber tint while an override is active. */
const editedInputStyle: CSSProperties = {
  borderColor: '#d9a441',
  background: '#fffaf0',
}

/** Dropdown over the race flags; wide enough for 'Lightforged Draenei'. */
const selectStyle: CSSProperties = {
  ...inputStyle,
  width: '12rem',
  textAlign: 'left',
}

/** One runeforging checkbox row: checkbox, label, edited marker. */
const checkboxRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.5rem',
  fontSize: '0.85rem',
  color: '#555',
}

/** Amber text while a checkbox's override is active. */
const editedLabelStyle: CSSProperties = { color: '#9a6b00' }

const badgeStyle: CSSProperties = {
  flexShrink: 0,
  fontSize: '0.7rem',
  color: '#9a6b00',
  background: '#fff3d6',
  border: '1px solid #f0d9a8',
  borderRadius: 999,
  padding: '0.05rem 0.45rem',
  whiteSpace: 'nowrap',
}

const resetStyle: CSSProperties = {
  flexShrink: 0,
  fontSize: '0.8rem',
  lineHeight: 1,
  padding: '0.3rem 0.55rem',
  border: '1px solid #ccc',
  borderRadius: 6,
  background: '#fff',
  cursor: 'pointer',
}

/** Slight indent tying a row's variable field to the talent row above it. */
const variableRowStyle: CSSProperties = { paddingLeft: '1.1rem' }

/** Small muted note under a row's field (per-row hint). */
const hintStyle: CSSProperties = {
  margin: 0,
  fontSize: '0.75rem',
  color: '#999',
}

/** Small muted label naming a comparison input column ('Set' / '+/-'). */
const miniLabelStyle: CSSProperties = {
  flexShrink: 0,
  fontSize: '0.7rem',
  color: '#999',
  whiteSpace: 'nowrap',
}

/**
 * One editable Inputs cell's control: the number input (with its local
 * typing draft) plus the edited marker and reset button while an override
 * is active. It renders bare — no wrapper element — so the caller's flex
 * row lays the label, input, marker, and button out as direct siblings.
 */
function CellInput({
  savedValue,
  override,
  cellRef,
  onSet,
  onClear,
  title,
}: {
  savedValue: CellValue | undefined
  override: CellValue | undefined
  /** Bare Inputs cell ref, e.g. `'C7'` or `'H123'` (see the file note). */
  cellRef: string
  onSet: (ref: string, v: number) => void
  onClear: (ref: string) => void
  /** Accessible name for the input and its reset button. */
  title: string
}) {
  // Local draft while typing keeps intermediate text stable until blur; the
  // committed value remains `override ?? savedValue` the whole time.
  const [draft, setDraft] = useState<string | null>(null)

  const edited = override !== undefined
  const text = draft ?? toText(override ?? savedValue)

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    setDraft(raw)
    if (raw.trim() === '') {
      onClear(cellRef) // empty -> inherit the saved value
    } else {
      const num = Number(raw)
      if (!Number.isNaN(num)) onSet(cellRef, num)
    }
  }

  const reset = () => {
    onClear(cellRef)
    setDraft(null)
  }

  return (
    <>
      <input
        id={`inputs-${cellRef}`}
        type="number"
        step="any"
        value={text}
        onChange={onChange}
        onBlur={() => setDraft(null)}
        title={title}
        aria-label={title}
        style={{ ...inputStyle, ...(edited ? editedInputStyle : null) }}
      />
      {edited && (
        <>
          <span style={badgeStyle}>edited</span>
          <button
            type="button"
            onClick={reset}
            title="Reset to saved value"
            aria-label={`Reset ${title} to saved value`}
            style={resetStyle}
          >
            ↺
          </button>
        </>
      )}
    </>
  )
}

/** One editable Inputs cell: label, number input, edited marker + reset. */
function NumberField({ label, savedValue, override, cellRef, onSet, onClear }: NumberFieldProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <label
        htmlFor={`inputs-${cellRef}`}
        style={{ flex: 1, minWidth: 0, fontSize: '0.85rem', color: '#555' }}
      >
        {label}
      </label>
      <CellInput
        savedValue={savedValue}
        override={override}
        cellRef={cellRef}
        onSet={onSet}
        onClear={onClear}
        title={label}
      />
    </div>
  )
}

const sectionStyle: CSSProperties = {
  border: '1px solid #e4e4e4',
  borderRadius: 8,
  padding: '0.6rem 0.9rem 0.75rem',
  background: '#fcfcfc',
}

/** One titled group of input fields. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={sectionStyle}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem' }}>{title}</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>{children}</div>
    </section>
  )
}

/** One SECTIONS group rendered as label/value/variable number fields. */
function GenericSection({
  section,
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  section: SectionSpec
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  const rows: number[] = []
  for (let row = section.firstRow; row <= section.lastRow; row++) rows.push(row)
  const labelCol = section.labelCol ?? 'B'
  const valueCol = section.valueCol ?? 'C'
  // The variable field's label: the sheet's own column header
  // ('Variable' for talents; 'Uptime' fallback for hero class).
  const variableLabel =
    section.variableCol !== undefined
      ? pickLabel(
          section.variableTitleRef !== undefined ? grid[section.variableTitleRef] : undefined,
          section.fallbackVariableLabel ?? 'Variable',
        )
      : ''

  return (
    <Section title={pickLabel(grid[section.titleRef], section.fallbackTitle)}>
      {rows.map((row) => {
        const valueRef = `${valueCol}${row}`
        const variableRef =
          section.variableCol !== undefined ? `${section.variableCol}${row}` : null
        // A variable input renders only where the sheet carries a value
        // for it — unless the section always wants it (hero uptime).
        const hasVariable =
          variableRef !== null &&
          (section.variableAlways || (grid[`Inputs!${variableRef}`] ?? null) !== null)
        const hint = section.rowHints?.[row]
        return (
          <Fragment key={row}>
            <NumberField
              label={pickLabel(
                grid[`Inputs!${labelCol}${row}`],
                section.fallbackLabels?.[row - section.firstRow] ?? `Row ${row}`,
              )}
              savedValue={grid[`Inputs!${valueRef}`]}
              override={overrides[valueRef]}
              cellRef={valueRef}
              onSet={setOverride}
              onClear={clearOverride}
            />
            {hint !== undefined && <p style={hintStyle}>{hint}</p>}
            {hasVariable && variableRef !== null && (
              <div style={variableRowStyle}>
                <NumberField
                  label={variableLabel}
                  savedValue={grid[`Inputs!${variableRef}`]}
                  override={overrides[variableRef]}
                  cellRef={variableRef}
                  onSet={setOverride}
                  onClear={clearOverride}
                />
              </div>
            )}
          </Fragment>
        )
      })}
    </Section>
  )
}

/** Runeforging: one checkbox per 0/1 flag cell (rows 21 and 23). */
function RuneforgingSection({
  grid,
  overrides,
  setOverride,
}: {
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
}) {
  return (
    <Section title={pickLabel(grid['Inputs!B19'], 'Runeforging')}>
      {RUNEFORGE_FLAGS.map(({ ref, labelRef, fallbackLabel }) => {
        const checked = (overrides[ref] ?? grid[`Inputs!${ref}`]) === 1
        const edited = overrides[ref] !== undefined
        return (
          <label
            key={ref}
            style={{ ...checkboxRowStyle, ...(edited ? editedLabelStyle : null) }}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setOverride(ref, e.target.checked ? 1 : 0)}
            />
            {pickLabel(grid[labelRef], fallbackLabel)}
            {edited && <span style={badgeStyle}>edited</span>}
          </label>
        )
      })}
    </Section>
  )
}

/** Race: one dropdown over the 24 race flag cells (columns C and E). */
function RaceSection({
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  // The 24 (label, ref) pairs: column C rows 26-37 (labels in B), then
  // column E rows 26-37 (labels in D).
  const options: { ref: string; label: string }[] = []
  for (const { valueCol, labelCol } of RACE_COLUMNS) {
    for (let row = RACE_FIRST_ROW; row <= RACE_LAST_ROW; row++) {
      options.push({
        ref: `${valueCol}${row}`,
        label: pickLabel(
          grid[`Inputs!${labelCol}${row}`],
          RACE_FALLBACK_LABELS[`${labelCol}${row}`] ?? `Row ${row}`,
        ),
      })
    }
  }
  // Current selection: the race whose effective value is 1; the saved
  // profile has none selected, so this is 'None' until the user picks one.
  const selected =
    options.find(({ ref }) => (overrides[ref] ?? grid[`Inputs!${ref}`]) === 1)?.ref ?? ''
  const edited = options.some(({ ref }) => overrides[ref] !== undefined)

  const onChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const chosen = e.target.value
    for (const { ref } of options) {
      if (chosen === '') clearOverride(ref) // 'None' clears every race override
      else setOverride(ref, ref === chosen ? 1 : 0)
    }
  }

  return (
    <Section title={pickLabel(grid['Inputs!B25'], 'Race')}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <select
          aria-label="Race"
          value={selected}
          onChange={onChange}
          style={{ ...selectStyle, ...(edited ? editedInputStyle : null) }}
        >
          <option value="">None</option>
          {options.map(({ ref, label }) => (
            <option key={ref} value={ref}>
              {label}
            </option>
          ))}
        </select>
        {edited && <span style={badgeStyle}>edited</span>}
      </div>
    </Section>
  )
}

/**
 * One comparison-profile row: the Inputs row plus whether the generated
 * Comparison module also reads its '+/-' differential cell (`I<row>`).
 * Every listed row's `H<row>` 'Set' cell is read.
 */
interface ComparisonRowSpec {
  row: number
  /** The module reads `Inputs!I<row>` ('+/-' differential). */
  diff: boolean
}

/** Rows `lo`..`hi` (inclusive) with the given differential flag. */
function comparisonRows(lo: number, hi: number, diff: boolean): ComparisonRowSpec[] {
  const rows: ComparisonRowSpec[] = []
  for (let row = lo; row <= hi; row++) rows.push({ row, diff })
  return rows
}

/**
 * Character Attributes comparison rows (7-17): the Comparison module reads
 * every row's H cell and every I cell except I17 (Base Weapon Speed's
 * differential is never read; the input still renders so the block mirrors
 * the sheet's G/H/I layout).
 */
const COMPARISON_ATTRIBUTE_ROWS: ComparisonRowSpec[] = comparisonRows(7, 17, true)

/**
 * Conditional Variables (146-156) and Tier Set (159-160) comparison rows:
 * only the H cells the Comparison module actually reads — H146 and
 * H148-H156 (H147, 'Damage Taken Per Sec.', is never read) plus H159/H160.
 * No I differential in any of these rows is read, so only 'Set' inputs
 * render. (Verified by grepping `G('Inputs','H1..'` / `G('Inputs','I1..'`
 * over src/engine/generated/Comparison.ts.)
 */
const COMPARISON_CONDITIONAL_ROWS: ComparisonRowSpec[] = [
  146, 148, 149, 150, 151, 152, 153, 154, 155, 156,
].map((row) => ({ row, diff: false }))
const COMPARISON_TIER_ROWS: ComparisonRowSpec[] = [159, 160].map((row) => ({ row, diff: false }))

/** One comparison-profile section: its G-column header cell plus rows. */
interface ComparisonSectionSpec {
  /** G-column header cell naming the group (mirror of the B header). */
  titleRef: string
  /** Header text when the G cell is missing or blank. */
  fallbackTitle: string
  /** Optional note line under the title. */
  note?: string
  /** Row specs: the H/I cells the Comparison module reads. */
  rows: ComparisonRowSpec[]
}

const COMPARISON_SECTIONS: ComparisonSectionSpec[] = [
  {
    titleRef: 'Inputs!G6',
    fallbackTitle: 'Character Attributes',
    note: 'Set = absolute override, +/- = differential; blank inherits the baseline value.',
    rows: COMPARISON_ATTRIBUTE_ROWS,
  },
  {
    titleRef: 'Inputs!G145',
    fallbackTitle: 'Conditional Variables',
    rows: COMPARISON_CONDITIONAL_ROWS,
  },
  {
    titleRef: 'Inputs!G158',
    fallbackTitle: 'Tier Set',
    rows: COMPARISON_TIER_ROWS,
  },
]

/**
 * One comparison-profile row: the row label (the G-column mirror of the B
 * label), its absolute 'Set' input (`H<row>`) on the label line, and its
 * '+/-' differential input (`I<row>`) indented below when the module reads
 * it. Blank inputs clear the override, inheriting the baseline value.
 */
function ComparisonRow({
  label,
  row,
  diff,
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  label: string
  row: number
  diff: boolean
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  const setRef = `H${row}`
  const diffRef = `I${row}`
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <label
          htmlFor={`inputs-${setRef}`}
          style={{ flex: 1, minWidth: 0, fontSize: '0.85rem', color: '#555' }}
        >
          {label}
        </label>
        <label htmlFor={`inputs-${setRef}`} style={miniLabelStyle}>
          Set
        </label>
        <CellInput
          savedValue={grid[`Inputs!${setRef}`]}
          override={overrides[setRef]}
          cellRef={setRef}
          onSet={setOverride}
          onClear={clearOverride}
          title={`${label} — Set (absolute override)`}
        />
      </div>
      {diff && (
        <div style={{ ...variableRowStyle, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor={`inputs-${diffRef}`} style={miniLabelStyle}>
            +/-
          </label>
          <CellInput
            savedValue={grid[`Inputs!${diffRef}`]}
            override={overrides[diffRef]}
            cellRef={diffRef}
            onSet={setOverride}
            onClear={clearOverride}
            title={`${label} — +/- (differential)`}
          />
        </div>
      )}
    </>
  )
}

/** One comparison-profile group: G-column header title, note, and rows. */
function ComparisonSection({
  spec,
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  spec: ComparisonSectionSpec
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  return (
    <Section title={`Comparison: ${pickLabel(grid[spec.titleRef], spec.fallbackTitle)}`}>
      {spec.note !== undefined && (
        <p style={{ margin: 0, fontSize: '0.75rem', color: '#999' }}>{spec.note}</p>
      )}
      {spec.rows.map(({ row, diff }) => (
        <ComparisonRow
          key={row}
          row={row}
          diff={diff}
          label={pickLabel(grid[`Inputs!G${row}`], pickLabel(grid[`Inputs!B${row}`], `Row ${row}`))}
          grid={grid}
          overrides={overrides}
          setOverride={setOverride}
          clearOverride={clearOverride}
        />
      ))}
    </Section>
  )
}

/**
 * The Inputs pane: every SECTIONS group plus the Runeforging and Race flag
 * blocks in sheet order, then the Comparison profile sections (the sheet's
 * G/H/I columns).
 */
export default function InputsEditor({
  overrides,
  setOverride,
  clearOverride,
  grid,
}: {
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
  grid: Grid
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
      {SECTIONS.map((section) => (
        <Fragment key={section.titleRef}>
          <GenericSection
            section={section}
            grid={grid}
            overrides={overrides}
            setOverride={setOverride}
            clearOverride={clearOverride}
          />
          {/* In sheet order, the Runeforging (rows 19-23) and Race (rows
              25-37) flag blocks follow Character Attributes (Inputs!B6)
              and precede DK Class Talents. */}
          {section.titleRef === 'Inputs!B6' && (
            <>
              <RuneforgingSection grid={grid} overrides={overrides} setOverride={setOverride} />
              <RaceSection
                grid={grid}
                overrides={overrides}
                setOverride={setOverride}
                clearOverride={clearOverride}
              />
            </>
          )}
        </Fragment>
      ))}
      {/* The Comparison profile (G/H/I columns) follows the baseline
          groups: absolute 'Set' overrides and '+/-' differentials that
          re-run the Comparison model against the baseline above. */}
      {COMPARISON_SECTIONS.map((spec) => (
        <ComparisonSection
          key={spec.titleRef}
          spec={spec}
          grid={grid}
          overrides={overrides}
          setOverride={setOverride}
          clearOverride={clearOverride}
        />
      ))}
    </div>
  )
}
