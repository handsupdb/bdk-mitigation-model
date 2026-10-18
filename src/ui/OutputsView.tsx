/**
 * Outputs sheet view: everything renders straight from the evaluated grid
 * (keys `'Outputs!<Ref>'`), so the UI always matches the workbook.
 *
 *   - Performance Indicators table (rows 7-12): label F<row>, Baseline
 *     G<row>, Comparison H<row>, differential I<row>; title from F4 and
 *     column headers from row 6, each with a fixed fallback.
 *   - Six stat-weight blocks. Each block's title comes from the sheet's own
 *     header label cell (B6/B19/B32/B45/B58/B71) when present, else the fixed
 *     fallback. The 10 stat rows read label B<row>, raw weight C<row>,
 *     normalized weight D<row> (column headers from the title row's C/D
 *     cells). The block's Pawn string (C17/C30/C43/C56/C69/C82) sits in a
 *     readonly box with a Copy button.
 *
 * Numbers render through `excelNumToStr` for Excel-identical formatting —
 * the same coercion the workbook's `&` concatenation uses.
 */
import { useCallback, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { CellValue, Grid } from '../engine/cells'
import { excelNumToStr } from '../engine/numstr'

/** Where one stat-weight block lives on the Outputs sheet. */
interface WeightBlock {
  /** Header label cell for the block title. */
  titleRef: string
  /** Title when the header cell is missing or blank. */
  fallbackTitle: string
  /** First of the block's 10 stat rows (label B, raw C, normalized D). */
  firstRow: number
  /** The block's Pawn string cell. */
  pawnRef: string
}

const WEIGHT_BLOCKS: WeightBlock[] = [
  { titleRef: 'Outputs!B6', fallbackTitle: 'Mitigation Stat Weights', firstRow: 7, pawnRef: 'Outputs!C17' },
  { titleRef: 'Outputs!B19', fallbackTitle: 'Overall DPS Stat Weights', firstRow: 20, pawnRef: 'Outputs!C30' },
  { titleRef: 'Outputs!B32', fallbackTitle: 'Priority DPS Stat Weights', firstRow: 33, pawnRef: 'Outputs!C43' },
  { titleRef: 'Outputs!B45', fallbackTitle: 'Reliable EHP Stat Weights', firstRow: 46, pawnRef: 'Outputs!C56' },
  { titleRef: 'Outputs!B58', fallbackTitle: 'Reliable & Controllable EHP Stat Weights', firstRow: 59, pawnRef: 'Outputs!C69' },
  { titleRef: 'Outputs!B71', fallbackTitle: 'Unreliable EHP Stat Weights', firstRow: 72, pawnRef: 'Outputs!C82' },
]

/** Performance Indicators data rows (labels F7-F12). */
const INDICATOR_ROWS = [7, 8, 9, 10, 11, 12] as const

/** Excel-identical rendering: numbers via excelNumToStr, strings as-is, blank → dash. */
function fmt(v: CellValue | undefined): string {
  if (v == null) return '—'
  if (typeof v === 'number') return excelNumToStr(v)
  return v
}

/** Prefer the grid's own label string; fall back to the fixed label. */
function pickLabel(v: CellValue | undefined, fallback: string): string {
  return typeof v === 'string' && v.trim() !== '' ? v : fallback
}

/** Readonly box for one Pawn string with a Copy button. */
function PawnBox({ text }: { text: string }) {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  const [copied, setCopied] = useState(false)

  /** Copy via the async clipboard API; fall back to select + execCommand. */
  const copy = useCallback(async () => {
    let ok = false
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text)
        ok = true
      }
    } catch {
      // Clipboard API unavailable or rejected — try the legacy path below.
    }
    if (!ok) {
      const el = ref.current
      if (el) {
        el.focus()
        el.select()
        try {
          ok = document.execCommand('copy')
        } catch {
          ok = false
        }
      }
    }
    setCopied(ok)
    if (ok) window.setTimeout(() => setCopied(false), 1500)
  }, [text])

  return (
    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', alignItems: 'flex-start' }}>
      <textarea
        ref={ref}
        readOnly
        rows={2}
        value={text}
        spellCheck={false}
        style={{
          flex: 1,
          minWidth: 0,
          resize: 'none',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: '0.75rem',
          lineHeight: 1.4,
          color: '#444',
          background: '#fafafa',
          border: '1px solid #e2e2e2',
          borderRadius: 6,
          padding: '0.35rem 0.5rem',
        }}
      />
      <button
        type="button"
        onClick={copy}
        style={{
          flexShrink: 0,
          fontSize: '0.8rem',
          padding: '0.35rem 0.8rem',
          border: '1px solid #ccc',
          borderRadius: 6,
          background: copied ? '#e6f4ea' : '#fff',
          cursor: 'pointer',
        }}
      >
        {copied ? 'Copied ✓' : 'Copy'}
      </button>
    </div>
  )
}

const thStyle: CSSProperties = {
  fontWeight: 600,
  color: '#888',
  padding: '0.2rem 0.25rem 0.2rem 0',
  borderBottom: '2px solid #ddd',
}

const tdStyle: CSSProperties = {
  padding: '0.25rem 0.25rem 0.25rem 0',
  borderBottom: '1px solid #eee',
  color: '#555',
}

const numTdStyle: CSSProperties = {
  ...tdStyle,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
}

/** One stat-weight block: title, the 10-stat raw/normalized table, Pawn box. */
function WeightBlockView({ grid, block }: { grid: Grid; block: WeightBlock }) {
  const titleRow = block.firstRow - 1
  const title = pickLabel(grid[block.titleRef], block.fallbackTitle)
  const rawLabel = pickLabel(grid[`Outputs!C${titleRow}`], 'Raw')
  const normalizedLabel = pickLabel(grid[`Outputs!D${titleRow}`], 'Normalized')
  const pawn = grid[block.pawnRef]

  return (
    <section
      style={{
        border: '1px solid #e4e4e4',
        borderRadius: 8,
        padding: '0.6rem 0.9rem 0.75rem',
        background: '#fcfcfc',
      }}
    >
      <h3 style={{ margin: '0 0 0.35rem', fontSize: '0.95rem' }}>{title}</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.85rem' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: 'left' }}>Stat</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{rawLabel}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{normalizedLabel}</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 10 }, (_, i) => block.firstRow + i).map((row) => (
            <tr key={row}>
              <td style={tdStyle}>{fmt(grid[`Outputs!B${row}`])}</td>
              <td style={numTdStyle}>{fmt(grid[`Outputs!C${row}`])}</td>
              <td style={numTdStyle}>{fmt(grid[`Outputs!D${row}`])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <PawnBox text={typeof pawn === 'string' ? pawn : ''} />
    </section>
  )
}

/** Performance Indicators: Baseline vs Comparison with differentials. */
function PerformanceIndicatorsView({ grid }: { grid: Grid }) {
  return (
    <section
      style={{
        border: '1px solid #e4e4e4',
        borderRadius: 8,
        padding: '0.6rem 0.9rem 0.75rem',
        background: '#fcfcfc',
      }}
    >
      <h3 style={{ margin: '0 0 0.35rem', fontSize: '0.95rem' }}>
        {pickLabel(grid['Outputs!F4'], 'Performance Indicators')}
      </h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.85rem' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: 'left' }}>{pickLabel(grid['Outputs!F6'], 'Performance Measures')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{pickLabel(grid['Outputs!G6'], 'Baseline')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{pickLabel(grid['Outputs!H6'], 'Comparison')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{pickLabel(grid['Outputs!I6'], 'Differential')}</th>
          </tr>
        </thead>
        <tbody>
          {INDICATOR_ROWS.map((row) => (
            <tr key={row}>
              <td style={tdStyle}>{fmt(grid[`Outputs!F${row}`])}</td>
              <td style={numTdStyle}>{fmt(grid[`Outputs!G${row}`])}</td>
              <td style={numTdStyle}>{fmt(grid[`Outputs!H${row}`])}</td>
              <td style={numTdStyle}>{fmt(grid[`Outputs!I${row}`])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** The Outputs pane: Performance Indicators, then the six stat-weight blocks. */
export default function OutputsView({ grid }: { grid: Grid }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
      <PerformanceIndicatorsView grid={grid} />
      {WEIGHT_BLOCKS.map((block) => (
        <WeightBlockView key={block.pawnRef} grid={grid} block={block} />
      ))}
    </div>
  )
}
