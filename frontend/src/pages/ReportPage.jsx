import { useState, useRef } from 'react'
import KpiCards from '../components/KpiCards'
import DevTable from '../components/DevTable'
import CategoryTable from '../components/CategoryTable'
import CommitTable from '../components/CommitTable'

const PHASE_LABELS = {
  fetch:   'Fetching commits',
  enrich:  'Loading diffs',
  analyze: 'Analyzing commits',
  report:  'Generating Excel report',
}

export default function ReportPage() {
  const [running, setRunning]   = useState(false)
  const [logs, setLogs]         = useState([])
  const [progress, setProgress] = useState(null) // { phase, current, total }
  const [result, setResult]     = useState(null)
  const [error, setError]       = useState(null)
  const esRef = useRef(null)

  const stop = () => {
    if (esRef.current) esRef.current.close()
    setRunning(false)
    setProgress(null)
    setLogs(prev => [...prev, '⏹ Stopped.'])
  }

  const run = () => {
    if (running) return
    setRunning(true)
    setLogs([])
    setProgress(null)
    setResult(null)
    setError(null)

    const es = new EventSource('/api/analyze')
    esRef.current = es

    es.onmessage = e => {
      const event = JSON.parse(e.data)
      if (event.type === 'heartbeat') return

      if (event.type === 'status') {
        setLogs(prev => [...prev, event.message])
        setProgress({ phase: event.phase, current: 0, total: 0 })

      } else if (event.type === 'progress') {
        setProgress({ phase: event.phase, current: event.current, total: event.total })
        if (event.message) {
          setLogs(prev => {
            const next = [...prev]
            next[next.length - 1] = event.message
            return next
          })
        }

      } else if (event.type === 'complete') {
        setProgress(null)
        setLogs(prev => [...prev, '✓ Analysis complete!'])
        setResult(event.data)
        setRunning(false)
        es.close()

      } else if (event.type === 'error') {
        setError(event.message)
        setRunning(false)
        es.close()
      }
    }

    es.onerror = () => {
      if (running) {
        setError('Connection lost. Please try again.')
        setRunning(false)
        es.close()
      }
    }
  }

  const pct = progress && progress.total > 0
    ? Math.round(progress.current / progress.total * 100)
    : null

  return (
    <div className="page-report">
      {/* Run card */}
      <div className="card run-card">
        <h2>Run Analysis</h2>
        <p className="hint">Make sure your config is saved before running.</p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn-primary" onClick={run} disabled={running}>
            {running ? '⏳  Running...' : '▶  Run Analysis'}
          </button>
          {running && (
            <button className="btn-stop" onClick={stop}>
              ⏹  Stop
            </button>
          )}
        </div>

        {(logs.length > 0 || running) && (
          <div className="progress-section">
            {progress && (
              <div style={{ marginBottom: 8 }}>
                <div className="progress-phase">
                  {PHASE_LABELS[progress.phase] || progress.phase}
                </div>
                <div className="progress-track">
                  <div
                    className="progress-fill"
                    style={{
                      width: pct != null ? `${pct}%` : '30%',
                      animation: pct == null ? 'pulse 1.2s ease-in-out infinite' : 'none',
                    }}
                  />
                </div>
                {pct != null && (
                  <div className="progress-pct">{pct}% ({progress.current}/{progress.total})</div>
                )}
              </div>
            )}

            <div className="log-box">
              {logs.map((l, i) => (
                <div key={i} className="log-line">{l}</div>
              ))}
              {running && <div className="log-line blink">▋</div>}
            </div>
          </div>
        )}

        {error && <div className="alert-error">{error}</div>}
      </div>

      {/* Results */}
      {result && (
        <>
          <KpiCards kpis={result.kpis} />
          <div className="two-col">
            <DevTable rows={result.dev_table} />
            <CategoryTable rows={result.cat_table} />
          </div>
          <CommitTable rows={result.commit_rows} />
          <div className="download-bar">
            <a
              className="btn-download"
              href={`/api/download/${result.filename}`}
              download
            >
              Download Excel Report
            </a>
          </div>
        </>
      )}
    </div>
  )
}
