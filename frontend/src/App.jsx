import { useState } from 'react'
import './styles.css'
import ConfigPage from './pages/ConfigPage'
import ReportPage from './pages/ReportPage'

export default function App() {
  const [page, setPage] = useState('config')

  return (
    <div className="app">
      <nav className="navbar">
        <span className="navbar-brand">Sprint Bug Fix Analyzer</span>
        <div className="nav-tabs">
          <button
            className={`nav-tab ${page === 'config' ? 'active' : ''}`}
            onClick={() => setPage('config')}
          >
            Config
          </button>
          <button
            className={`nav-tab ${page === 'report' ? 'active' : ''}`}
            onClick={() => setPage('report')}
          >
            Run Report
          </button>
        </div>
      </nav>
      <main className="main-content">
        {page === 'config'
          ? <ConfigPage onRun={() => setPage('report')} />
          : <ReportPage />}
      </main>
    </div>
  )
}
