/**
 * Comparison-profile editor for the talent and racial blocks of the Inputs
 * sheet's comparison mirror columns.
 *
 * The Comparison model re-runs the whole workbook against a second profile
 * laid out beside the baseline on the Inputs sheet: the G column mirrors the
 * baseline labels, H holds absolute 'Set' overrides, and a blank cell makes
 * the generated module inherit the baseline value (`ifL(isBlank(H<n>),
 * () => C<n>, () => H<n>)`). This component covers the talent and racial
 * blocks that InputsEditor's comparison sections leave out; every rendered
 * ref was verified as actually read by grepping `G('Inputs','...')` over
 * src/engine/generated/Comparison.ts:
 *
 *   - Death Knight Talents (rows 40-85): a 'Set' rank input `H<row>` per
 *     row, plus a 'Variable' input `I<row>` for the rows whose variable the
 *     module reads (46, 61, 63). The talent blocks' I column mirrors the
 *     baseline D 'Variable' column — an absolute override, not a
 *     differential (the sheet's own I39/I87 headers say 'Variable'; only
 *     the Character Attributes block's I column, I6 = 'Differentials', is
 *     additive, which is why InputsEditor labels those '+/-').
 *   - Blood Talents (rows 88-129): same pattern; variables read for rows
 *     89, 99, 102, 103, 105, 107, 119, 122, 123.
 *   - Hero Class (rows 132-133): 'Set' `H<row>` plus an 'Uptime' input
 *     `I<row>` (the module reads both cells).
 *   - Deathbringer Talents (rows 137-140): 'Set' `H<row>` only — H136 and
 *     H141 are never read.
 *   - San'layn Talents (rows 138-143): 'Set' `J<row>` — the San'layn mirror
 *     sits one column right (labels I, values J); J136 and J137 are never
 *     read.
 *   - Tier Set Bonus (rows 159-160): 'Set' `H<row>`.
 *   - Race (rows 26-37): a single-select dropdown over the 24 race flag
 *     cells the module reads — `H26..H37` (labels G, first race column) and
 *     `J26..J37` (labels I, second race column). 'None' clears every race
 *     override so the comparison inherits the baseline race.
 *   - Runeforging (rows 21 and 23): checkboxes for the four flag cells the
 *     module reads — `G21`/`H21` and `G23`/`H23`. The other three
 *     runeforges (Spellwarding, Apocalypse, Unending Thirst) are not
 *     modeled by the Comparison module at all, so they are not editable
 *     here.
 *
 * Blank text inputs clear the override, inheriting the baseline value. As
 * in InputsEditor, the committed value is always `override ?? savedValue`
 * (empty string when null) while a local typing draft keeps intermediate
 * text like `'0.'` or `'-'` stable until blur. Input ids are prefixed
 * `comparison-` rather than `inputs-` because the Tier rows H159/H160 also
 * render in InputsEditor's comparison section and the two must not emit
 * duplicate DOM ids. The cell-ref prop is named `cellRef`, not `ref` —
 * React 19 hoists a string `ref` prop into the fiber and throws.
 */
import { useState } from 'react'
import type { ChangeEvent, CSSProperties, ReactNode } from 'react'
import type { CellValue, Grid } from '../engine/cells'

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

/** Dropdown over the comparison race flags; wide enough for race names. */
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

/** Slight indent tying a row's second input to the row above it. */
const variableRowStyle: CSSProperties = { paddingLeft: '1.1rem' }

/** Small muted label naming a comparison input column ('Set' / 'Variable'). */
const miniLabelStyle: CSSProperties = {
  flexShrink: 0,
  fontSize: '0.7rem',
  color: '#999',
  whiteSpace: 'nowrap',
}

const sectionStyle: CSSProperties = {
  border: '1px solid #e4e4e4',
  borderRadius: 8,
  padding: '0.6rem 0.9rem 0.75rem',
  background: '#fcfcfc',
}

/**
 * One editable comparison cell's control: the number input (with its local
 * typing draft) plus the edited marker and reset button while an override
 * is active. Renders bare so the caller's flex row lays everything out as
 * direct siblings.
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
  /** Bare Inputs cell ref, e.g. `'H123'` or `'J140'` (see the file note). */
  cellRef: string
  onSet: (ref: string, v: number) => void
  onClear: (ref: string) => void
  /** Accessible name for the input and its reset button. */
  title: string
}) {
  const [draft, setDraft] = useState<string | null>(null)

  const edited = override !== undefined
  const text = draft ?? toText(override ?? savedValue)

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    setDraft(raw)
    if (raw.trim() === '') {
      onClear(cellRef) // empty -> inherit the baseline value
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
        id={`comparison-${cellRef}`}
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

/** One titled group of input fields. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={sectionStyle}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem' }}>{title}</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>{children}</div>
    </section>
  )
}

/**
 * One comparison-profile row: the Inputs row number plus, where the module
 * also reads it, the row's second absolute-override cell (`I<row>` — the
 * talent 'Variable' or hero 'Uptime' mirror).
 */
interface RowSpec {
  row: number
  /** Second absolute-override cell rendered indented below (e.g. `'I46'`). */
  secondRef?: string
}

/**
 * Rows `lo`..`hi` (inclusive), attaching the second `I<row>` input to
 * exactly the rows whose variable cell the Comparison module reads.
 */
function talentRows(lo: number, hi: number, variableRows: ReadonlySet<number>): RowSpec[] {
  const rows: RowSpec[] = []
  for (let row = lo; row <= hi; row++) {
    rows.push(variableRows.has(row) ? { row, secondRef: `I${row}` } : { row })
  }
  return rows
}

/** DK talent rows (40-85) whose `I<row>` variable cell the module reads. */
const DK_VARIABLE_ROWS: ReadonlySet<number> = new Set([46, 61, 63])

/** Blood talent rows (88-129) whose `I<row>` variable cell the module reads. */
const BLOOD_VARIABLE_ROWS: ReadonlySet<number> = new Set([
  89, 99, 102, 103, 105, 107, 119, 122, 123,
])

/** One comparison-profile section: its header cell plus row specs. */
interface SectionSpec {
  /** Header cell naming the group (G-column mirror of the B header). */
  titleRef: string
  /** Title when the header cell is missing or blank. */
  fallbackTitle: string
  /** Comparison label column; defaults to `'G'` (I for San'layn). */
  labelCol?: string
  /** Baseline label column used as fallback; defaults to `'B'` (D for San'layn). */
  fallbackLabelCol?: string
  /** Column holding each row's 'Set' cell; defaults to `'H'` (J for San'layn). */
  setCol?: string
  /** Header cell naming the second input column, when the sheet has one. */
  secondTitleRef?: string
  /** Second-input label when no header cell exists (hero 'Uptime'). */
  fallbackSecondLabel?: string
  /** Row specs: the cells the Comparison module actually reads. */
  rows: RowSpec[]
}

const SECTIONS: SectionSpec[] = [
  {
    titleRef: 'Inputs!G39',
    fallbackTitle: 'Death Knight Talents',
    secondTitleRef: 'Inputs!I39',
    fallbackSecondLabel: 'Variable',
    rows: talentRows(40, 85, DK_VARIABLE_ROWS),
  },
  {
    titleRef: 'Inputs!G87',
    fallbackTitle: 'Blood Talents',
    secondTitleRef: 'Inputs!I87',
    fallbackSecondLabel: 'Variable',
    rows: talentRows(88, 129, BLOOD_VARIABLE_ROWS),
  },
  {
    // Both rows' H (value) and I (uptime) cells are read.
    titleRef: 'Inputs!G131',
    fallbackTitle: 'Hero Class',
    fallbackSecondLabel: 'Uptime',
    rows: [132, 133].map((row) => ({ row, secondRef: `I${row}` })),
  },
  {
    // H136 ('Death's Bargain') and H141 ('Expelling Shield') are never read.
    titleRef: 'Inputs!G135',
    fallbackTitle: 'Deathbringer Talents',
    rows: [137, 138, 139, 140].map((row) => ({ row })),
  },
  {
    // The San'layn mirror sits one column right: labels I, 'Set' values J.
    // J136 ('Newly Turned') and J137 ('Vampiric Speed') are never read.
    titleRef: 'Inputs!I135',
    fallbackTitle: "San'layn Talents",
    labelCol: 'I',
    fallbackLabelCol: 'D',
    setCol: 'J',
    rows: [138, 139, 140, 141, 142, 143].map((row) => ({ row })),
  },
  {
    titleRef: 'Inputs!G158',
    fallbackTitle: 'Tier Set Bonus',
    rows: [159, 160].map((row) => ({ row })),
  },
]

/**
 * One comparison-profile row: the row label, its absolute 'Set' input on
 * the label line, and its second absolute-override input ('Variable' /
 * 'Uptime') indented below when the module reads that cell. Blank inputs
 * clear the override, inheriting the baseline value.
 */
function ComparisonRow({
  label,
  setRef,
  secondRef,
  secondLabel,
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  label: string
  /** Bare Inputs ref of the 'Set' cell, e.g. `'H123'` or `'J140'`. */
  setRef: string
  /** Bare Inputs ref of the second cell, when the row has one. */
  secondRef: string | undefined
  /** Label for the second input ('Variable' / 'Uptime'). */
  secondLabel: string
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <label
          htmlFor={`comparison-${setRef}`}
          style={{ flex: 1, minWidth: 0, fontSize: '0.85rem', color: '#555' }}
        >
          {label}
        </label>
        <label htmlFor={`comparison-${setRef}`} style={miniLabelStyle}>
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
      {secondRef !== undefined && (
        <div style={{ ...variableRowStyle, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor={`comparison-${secondRef}`} style={miniLabelStyle}>
            {secondLabel}
          </label>
          <CellInput
            savedValue={grid[`Inputs!${secondRef}`]}
            override={overrides[secondRef]}
            cellRef={secondRef}
            onSet={setOverride}
            onClear={clearOverride}
            title={`${label} — ${secondLabel} (absolute override)`}
          />
        </div>
      )}
    </>
  )
}

/** One comparison-profile group: header title and its rows. */
function ComparisonSection({
  spec,
  grid,
  overrides,
  setOverride,
  clearOverride,
}: {
  spec: SectionSpec
  grid: Grid
  overrides: Record<string, CellValue>
  setOverride: (ref: string, v: CellValue) => void
  clearOverride: (ref: string) => void
}) {
  const labelCol = spec.labelCol ?? 'G'
  const fallbackLabelCol = spec.fallbackLabelCol ?? 'B'
  const setCol = spec.setCol ?? 'H'
  // The second input's label: the sheet's own column header ('Variable')
  // when it has one, else the fixed fallback (hero 'Uptime').
  const secondLabel =
    spec.secondTitleRef !== undefined
      ? pickLabel(grid[spec.secondTitleRef], spec.fallbackSecondLabel ?? 'Variable')
      : spec.fallbackSecondLabel ?? ''

  return (
    <Section title={pickLabel(grid[spec.titleRef], spec.fallbackTitle)}>
      {spec.rows.map(({ row, secondRef }) => (
        <ComparisonRow
          key={row}
          label={pickLabel(
            grid[`Inputs!${labelCol}${row}`],
            pickLabel(grid[`Inputs!${fallbackLabelCol}${row}`], `Row ${row}`),
          )}
          setRef={`${setCol}${row}`}
          secondRef={secondRef}
          secondLabel={secondLabel}
          grid={grid}
          overrides={overrides}
          setOverride={setOverride}
          clearOverride={clearOverride}
        />
      ))}
    </Section>
  )
}

/** Race flag rows: two 12-row columns of comparison flag cells, rows 26-37. */
const RACE_FIRST_ROW = 26
const RACE_LAST_ROW = 37
/**
 * Each comparison race column: 'Set' flag cells in `valueCol` (overriding
 * the baseline C/E flags), labels in `labelCol` with the baseline label
 * column as fallback.
 */
const RACE_COLUMNS: { valueCol: string; labelCol: string; fallbackLabelCol: string }[] = [
  { valueCol: 'H', labelCol: 'G', fallbackLabelCol: 'B' },
  { valueCol: 'J', labelCol: 'I', fallbackLabelCol: 'D' },
]
/**
 * Fixed label for the one race label cell the sheet leaves blank: I37 (the
 * mirror of the blank D37) carries no label in the saved profile, so it
 * takes the next playable race's name.
 */
const RACE_LABEL_FALLBACKS: Record<string, string> = { I37: 'Dracthyr' }

/**
 * Comparison Race: one dropdown over the 24 race flag cells the module
 * reads (`H26..H37`, `J26..J37`). Picking a race sets that cell to 1 and
 * every other race cell to 0 (single-select, mirroring the baseline Race
 * dropdown); 'None' clears all 24 overrides so the comparison inherits the
 * baseline race selection.
 */
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
  const options: { ref: string; label: string }[] = []
  for (const { valueCol, labelCol, fallbackLabelCol } of RACE_COLUMNS) {
    for (let row = RACE_FIRST_ROW; row <= RACE_LAST_ROW; row++) {
      options.push({
        ref: `${valueCol}${row}`,
        label: pickLabel(
          grid[`Inputs!${labelCol}${row}`],
          pickLabel(
            grid[`Inputs!${fallbackLabelCol}${row}`],
            RACE_LABEL_FALLBACKS[`${labelCol}${row}`] ?? `Row ${row}`,
          ),
        ),
      })
    }
  }
  // Current selection: the race whose effective value is 1; the saved
  // comparison profile has none selected, so this is 'None' until picked.
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
    <Section title={pickLabel(grid['Inputs!G25'], 'Race')}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <select
          aria-label="Comparison race"
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
 * Comparison Runeforging flags: the four 0/1 flag cells the module reads —
 * `G21`/`H21` (row 21, labels in row 20) and `G23`/`H23` (row 23, labels
 * in row 22). Checking/unchecking sets the override to 1/0 (an explicit
 * off, mirroring the baseline Runeforging checkboxes); the other three
 * runeforges are not modeled in Comparison at all.
 */
const RUNEFORGE_FLAGS: { ref: string; labelRef: string; fallbackLabel: string }[] = [
  { ref: 'G21', labelRef: 'Inputs!G20', fallbackLabel: 'Razorice' },
  { ref: 'H21', labelRef: 'Inputs!H20', fallbackLabel: 'Sanguination' },
  { ref: 'G23', labelRef: 'Inputs!G22', fallbackLabel: 'Fallen Crusader' },
  { ref: 'H23', labelRef: 'Inputs!H22', fallbackLabel: 'Stoneskin Gargoyle' },
]

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
    <Section title={pickLabel(grid['Inputs!G19'], 'Runeforging')}>
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

/**
 * The Comparison — Talents & Racials block: the talent sections in sheet
 * order, then the Race dropdown and Runeforging checkboxes over the racial
 * flag cells the Comparison module reads.
 */
export default function ComparisonTalents({
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
      <p style={{ margin: 0, fontSize: '0.75rem', color: '#999' }}>
        Comparison profile (the Inputs sheet&apos;s mirror columns): every input holds an
        absolute override — including the &apos;Variable&apos;/&apos;Uptime&apos; cells,
        which replace the talent&apos;s variable rather than adding to it — and a blank
        cell inherits the baseline value.
      </p>
      {SECTIONS.map((spec) => (
        <ComparisonSection
          key={spec.titleRef}
          spec={spec}
          grid={grid}
          overrides={overrides}
          setOverride={setOverride}
          clearOverride={clearOverride}
        />
      ))}
      <RaceSection
        grid={grid}
        overrides={overrides}
        setOverride={setOverride}
        clearOverride={clearOverride}
      />
      <RuneforgingSection grid={grid} overrides={overrides} setOverride={setOverride} />
    </div>
  )
}
