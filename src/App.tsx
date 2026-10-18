import { useEngine } from './ui/useEngine'
import OutputsView from './ui/OutputsView'

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
          <OutputsView grid={grid} />
        </section>
      </div>
    </main>
  )
}
