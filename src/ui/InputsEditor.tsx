/**
 * Inputs editor: editable fields over the Inputs sheet's saved profile.
 *
 * Two sections render (add more to SECTIONS as the editor grows):
 *   - Character Attributes  (rows 7-17:  label `Inputs!B<row>`, value `Inputs!C<row>`)
 *   - Conditional Variables (rows 146-156: same columns)
 *
 * Each NumberField edits one Inputs cell; the override is keyed by the bare
 * Inputs ref (`'C7'`), exactly as `useEngine`/`evaluateWithInputs` expect.
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
import { useState } from 'react'
import type { ChangeEvent, CSSProperties, ReactNode } from 'react'
import type { CellValue, Grid } from '../engine/cells'

/** Where one editor section lives on the Inputs sheet. */
interface SectionSpec {
  /** Header label cell for the section title. */
  titleRef: string
  /** Title when the header cell is missing or blank. */
  fallbackTitle: string
  /** First data row (label B<row>, value C<row>). */
  firstRow: number
  /** Last data row (inclusive). */
  lastRow: number
  /** Per-row label fallbacks, indexed by `row - firstRow`. */
  fallbackLabels: string[]
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
  },
]

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

/** One editable Inputs cell: label, number input, edited marker + reset. */
function NumberField({ label, savedValue, override, cellRef, onSet, onClear }: NumberFieldProps) {
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
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <label
        htmlFor={`inputs-${cellRef}`}
        style={{ flex: 1, minWidth: 0, fontSize: '0.85rem', color: '#555' }}
      >
        {label}
      </label>
      <input
        id={`inputs-${cellRef}`}
        type="number"
        step="any"
        value={text}
        onChange={onChange}
        onBlur={() => setDraft(null)}
        style={{ ...inputStyle, ...(edited ? editedInputStyle : null) }}
      />
      {edited && (
        <>
          <span style={badgeStyle}>edited</span>
          <button
            type="button"
            onClick={reset}
            title="Reset to saved value"
            aria-label={`Reset ${label} to saved value`}
            style={resetStyle}
          >
            ↺
          </button>
        </>
      )}
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

/** The Inputs pane: every SECTIONS group rendered as editable fields. */
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
      {SECTIONS.map((section) => {
        const rows: number[] = []
        for (let row = section.firstRow; row <= section.lastRow; row++) rows.push(row)
        return (
          <Section
            key={section.titleRef}
            title={pickLabel(grid[section.titleRef], section.fallbackTitle)}
          >
            {rows.map((row) => (
              <NumberField
                key={row}
                label={pickLabel(
                  grid[`Inputs!B${row}`],
                  section.fallbackLabels[row - section.firstRow],
                )}
                savedValue={grid[`Inputs!C${row}`]}
                override={overrides[`C${row}`]}
                cellRef={`C${row}`}
                onSet={setOverride}
                onClear={clearOverride}
              />
            ))}
          </Section>
        )
      })}
    </div>
  )
}
