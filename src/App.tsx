import { useEngine } from './ui/useEngine'
import type { CellValue } from './engine/cells'

/**
 * The six headline outputs. The workbook keeps them on the Baseline sheet —
 * the model run that reads the Inputs profile literals the engine's
 * overrides replace: values in row 15, labels in row 14. (The Outputs sheet
 * itself only carries the stat-weight/Pawn tables.) The grid's own label
 * strings are used when present; otherwise the fixed fallback labels ship.
 */
const SUMMARY_ROWS: { valueRef: string; labelRef: string; fallbackLabel: string }[] = [
  { valueRef: 'Baseline!N15', labelRef: 'Baseline!N14', fallbackLabel: 'Mitigation Factor' },
  { valueRef: 'Baseline!O15', labelRef: 'Baseline!O14', fallbackLabel: 'Overall DPS' },
  { valueRef: 'Baseline!P15', labelRef: 'Baseline!P14', fallbackLabel: 'Priority DPS' },
  { valueRef: 'Baseline!Q15', labelRef: 'Baseline!Q14', fallbackLabel: 'Reliable EHP' },
  { valueRef: 'Baseline!R15', labelRef: 'Baseline!R14', fallbackLabel: 'Reliable & Controllable EHP' },
  { valueRef: 'Baseline!S15', labelRef: 'Baseline!S14', fallbackLabel: 'Unreliable EHP' },
]

/** Render a cell value: strings (e.g. 'Self-Sufficient (+…%)') as-is, numbers lightly formatted, blank as a dash. */
function formatValue(v: CellValue | undefined): string {
  if (v == null) return '—'
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 3 })
  return v
}

/** Prefer the grid's own label string; fall back to the fixed label. */
function pickLabel(v: CellValue | undefined, fallback: string): string {
  return typeof v === 'string' && v.trim() !== '' ? v : fallback
}

export default function App() {
  const { grid } = useEngine()

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 920, margin: '2rem auto', padding: '0 1rem' }}>
      <h1 style={{ marginBottom: '0.25rem' }}>BDK Mitigation Model</h1>
      <p style={{ marginTop: 0, color: '#666' }}>
        Kyrasis 12.1 Blood Death Knight mitigation spreadsheet, rebuilt as a serverless web app.
      </p>
      <div style={{ display: 'flex', gap: '1.25rem', alignItems: 'stretch', flexWrap: 'wrap' }}>
        <section style={{ flex: '1 1 260px', border: '1px solid #ddd', borderRadius: 8, padding: '0.75rem 1rem' }}>
          <h2 style={{ marginTop: 0, fontSize: '1.05rem' }}>Inputs</h2>
          <div style={{ color: '#777' }}>Inputs editor — next</div>
        </section>
        <section style={{ flex: '1.2 1 320px', border: '1px solid #ddd', borderRadius: 8, padding: '0.75rem 1rem' }}>
          <h2 style={{ marginTop: 0, fontSize: '1.05rem' }}>Outputs</h2>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              {SUMMARY_ROWS.map(({ valueRef, labelRef, fallbackLabel }) => (
                <tr key={valueRef}>
                  <td style={{ padding: '0.3rem 0.25rem 0.3rem 0', borderBottom: '1px solid #eee', color: '#555' }}>
                    {pickLabel(grid[labelRef], fallbackLabel)}
                  </td>
                  <td
                    style={{
                      padding: '0.3rem 0',
                      borderBottom: '1px solid #eee',
                      textAlign: 'right',
                      fontWeight: 600,
                      fontVariantNumeric: 'tabular-nums',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {formatValue(grid[valueRef])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </main>
  )
}
