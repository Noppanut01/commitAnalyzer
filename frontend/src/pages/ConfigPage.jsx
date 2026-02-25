import { useState, useEffect } from 'react'
import ModeFields from '../components/ModeFields'

const STORAGE_KEY = 'bugAnalyzer_config'
const SESSION_KEY = 'bugAnalyzer_secrets'
const SENSITIVE   = new Set(['azure_pat', 'anthropic_api_key', 'google_api_key', 'openai_api_key'])

const loadStored = () => {
  try {
    const local   = localStorage.getItem(STORAGE_KEY)
    const session = sessionStorage.getItem(SESSION_KEY)
    const merged  = { ...(local ? JSON.parse(local) : {}), ...(session ? JSON.parse(session) : {}) }
    return Object.keys(merged).length > 0 ? { ...DEFAULT_CONFIG, ...merged } : null
  } catch { return null }
}

const DEFAULT_CONFIG = {
  azure_org: '',
  azure_project: '',
  azure_repo: '',
  azure_pat: '',
  azure_branch: '',
  sprint_name: '',
  sprint_start: '',
  sprint_end: '',
  analysis_mode: 'claude',
  anthropic_api_key: '',
  google_api_key: '',
  gemini_model: '',
  gemini_use_vertex: 'false',
  google_cloud_project: '',
  google_cloud_region: '',
  ollama_model: '',
  ollama_url: '',
  openai_api_key: '',
  openai_model: '',
}

export default function ConfigPage({ onRun }) {
  const stored = loadStored()
  const [config, setConfig]       = useState(stored ?? DEFAULT_CONFIG)
  const [status, setStatus]       = useState(null)
  const [loading, setLoading]     = useState(!stored)   // skip spinner if localStorage has data
  const [loadError, setLoadError] = useState(null)

  const [projects,    setProjects]    = useState(null)  // null | 'loading' | string[]
  const [repos,       setRepos]       = useState(null)
  const [branches,    setBranches]    = useState(null)
  const [dateLoading, setDateLoading] = useState(false)
  const [browseErr,   setBrowseErr]   = useState({})

  // Auto-save — sensitive keys → sessionStorage, rest → localStorage
  useEffect(() => {
    const secrets = {}
    const normal  = {}
    Object.entries(config).forEach(([k, v]) => {
      if (SENSITIVE.has(k)) secrets[k] = v
      else normal[k] = v
    })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normal))
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(secrets))
  }, [config])

  // Backend check — show error if server unreachable; merge data if backend has it
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const timer = setTimeout(() => { if (!cancelled) controller.abort() }, 6000)

    fetch('/api/config', { signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => {
        if (cancelled) return
        clearTimeout(timer)
        // Only merge if backend has actual saved data (non-empty values beyond defaults)
        const hasData = data && Object.entries(data).some(([k, v]) =>
          !['analysis_mode', 'gemini_use_vertex'].includes(k) && v && v !== ''
        )
        if (hasData) setConfig(prev => ({ ...prev, ...data }))
        setLoading(false)
      })
      .catch(err => {
        if (cancelled) return
        clearTimeout(timer)
        if (!stored) setLoadError(err.name === 'AbortError' ? 'timeout' : 'refused')
        setLoading(false)
      })

    return () => { cancelled = true; clearTimeout(timer); controller.abort() }
  }, [])

  const set = (key, value) => setConfig(prev => ({ ...prev, [key]: value }))

  const apiGet = async (path, errKey) => {
    setBrowseErr(prev => ({ ...prev, [errKey]: '' }))
    const r = await fetch(path)
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail || `HTTP ${r.status}`)
    }
    return r.json()
  }

  const qs = (params) =>
    new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== ''))
    ).toString()

  // Step 1 — load projects (auto on Org blur)
  const loadProjects = (org = config.azure_org, pat = config.azure_pat) => {
    if (!org || !pat || projects === 'loading') return
    setProjects('loading')
    setRepos(null); setBranches(null)
    const q = qs({ org, pat })
    apiGet(`/api/azure/projects?${q}`, 'projects')
      .then(data => setProjects(data.projects || []))
      .catch(e => { setProjects(null); setBrowseErr(prev => ({ ...prev, projects: e.message })) })
  }

  // Step 2 — project chosen → load repos
  const onSelectProject = (project) => {
    set('azure_project', project)
    setRepos('loading'); setBranches(null)
    const { azure_org: org, azure_pat: pat } = config
    const q = qs({ org, project, pat })
    apiGet(`/api/azure/repos?${q}`, 'repos')
      .then(data => setRepos(data.repos || []))
      .catch(e => { setRepos(null); setBrowseErr(prev => ({ ...prev, repos: e.message })) })
  }

  // Step 3 — repo chosen → load branches + dates
  const onSelectRepo = (repo) => {
    set('azure_repo', repo)
    setBranches('loading')
    const { azure_org: org, azure_project: project, azure_pat: pat } = config
    const q = qs({ org, project, repo, pat })
    apiGet(`/api/azure/branches?${q}`, 'branches')
      .then(data => setBranches(data.branches || []))
      .catch(e => { setBranches(null); setBrowseErr(prev => ({ ...prev, branches: e.message })) })
    fetchCommitDates(org, project, repo, pat, '')
  }

  // Step 4 — branch chosen → refresh dates
  const onSelectBranch = (branch) => {
    set('azure_branch', branch)
    const { azure_org: org, azure_project: project, azure_repo: repo, azure_pat: pat } = config
    fetchCommitDates(org, project, repo, pat, branch)
  }

  const fetchCommitDates = (org, project, repo, pat, branch) => {
    setDateLoading(true)
    setBrowseErr(prev => ({ ...prev, dates: '' }))
    const q = qs({ org, project, repo, pat, branch })
    apiGet(`/api/azure/commit-dates?${q}`, 'dates')
      .then(data => {
        if (data.start_date) set('sprint_start', data.start_date)
        if (data.end_date)   set('sprint_end',   data.end_date)
        setDateLoading(false)
      })
      .catch(e => { setBrowseErr(prev => ({ ...prev, dates: e.message })); setDateLoading(false) })
  }

  const save = async () => {
    setStatus('saving')
    try {
      const r = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (!r.ok) throw new Error('save failed')
      setStatus('saved')
      setTimeout(() => setStatus(null), 2500)
      return true
    } catch {
      setStatus('error')
      return false
    }
  }

  const saveAndRun = async () => { const ok = await save(); if (ok) onRun() }

  if (loading) return <div className="loading">Loading config…</div>

  if (loadError) return (
    <div className="page-config">
      <div className="card server-error-card">
        <h2>⚠️ Cannot Connect to Backend</h2>
        <p>
          {loadError === 'timeout' ? 'Connection timed out (6 s).' : 'Connection refused.'}
          {' '}Make sure the FastAPI server is running:
        </p>
        <pre className="code-hint">uvicorn app:app --reload</pre>
        <p className="hint">
          Then open <strong>http://localhost:8000</strong>
          {' '}(or keep Vite on :5173 while uvicorn also runs on :8000).
        </p>
        <button className="btn-primary" style={{ marginTop: 12 }}
          onClick={() => {
            setLoadError(null); setLoading(true)
            fetch('/api/config').then(r => r.json())
              .then(() => setLoading(false))
              .catch(() => { setLoadError('refused'); setLoading(false) })
          }}>
          Retry
        </button>
      </div>
    </div>
  )

  return (
    <div className="page-config">

      {/* ── Azure DevOps ── */}
      <div className="card">
        <h2>Azure DevOps</h2>

        <div className="form-grid">
          {/* PAT */}
          <Field label="Personal Access Token" value={config.azure_pat} required
            type="password" placeholder="Enter your Personal Access Token"
            autoComplete="off"
            onChange={v => {
              set('azure_pat', v)
              setProjects(null); setRepos(null); setBranches(null)
            }}
            onKeyDown={e => e.key === 'Enter' && loadProjects(config.azure_org, e.target.value)} />

          {/* Organisation — auto-loads projects on blur or Enter */}
          <div className="field">
            <label className="field-label">Organisation <span className="required">*</span></label>
            <input className="field-input" value={config.azure_org}
              placeholder="Enter your organization name"
              onChange={e => {
                set('azure_org', e.target.value)
                setProjects(null); setRepos(null); setBranches(null)
              }}
              onBlur={() => loadProjects(config.azure_org, config.azure_pat)}
              onKeyDown={e => e.key === 'Enter' && loadProjects(e.target.value, config.azure_pat)} />
            {projects === 'loading' && (
              <span className="date-loading-badge" style={{ display: 'inline-block', marginTop: 4 }}>
                Loading projects…
              </span>
            )}
            {browseErr.projects && <div className="browse-err">{browseErr.projects}</div>}
          </div>
        </div>

        <div className="form-grid" style={{ marginTop: 12 }}>

          {/* Project */}
          <div className="field">
            <label className="field-label">Project <span className="required">*</span></label>
            <select className="field-input field-input-select"
              value={config.azure_project}
              disabled={projects === 'loading'}
              onChange={e => e.target.value && onSelectProject(e.target.value)}>
              <option value="">
                {projects === 'loading' ? 'Loading…' : 'Select project…'}
              </option>
              {Array.isArray(projects) && projects.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            {browseErr.projects && <div className="browse-err">{browseErr.projects}</div>}
          </div>

          {/* Repository */}
          <div className="field">
            <label className="field-label">Repository <span className="required">*</span></label>
            <select className="field-input field-input-select"
              value={config.azure_repo}
              disabled={repos === 'loading'}
              onChange={e => e.target.value && onSelectRepo(e.target.value)}>
              <option value="">
                {repos === 'loading' ? 'Loading…' : 'Select repository…'}
              </option>
              {Array.isArray(repos) && repos.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            {browseErr.repos && <div className="browse-err">{browseErr.repos}</div>}
          </div>

          {/* Branch */}
          <div className="field">
            <label className="field-label">
              Branch <span className="field-hint">(optional)</span>
            </label>
            <select className="field-input field-input-select"
              value={config.azure_branch}
              disabled={branches === 'loading'}
              onChange={e => onSelectBranch(e.target.value)}>
              <option value="">
                {branches === 'loading' ? 'Loading…' : 'All branches'}
              </option>
              {Array.isArray(branches) && branches.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
            {browseErr.branches && <div className="browse-err">{browseErr.branches}</div>}
          </div>

        </div>
      </div>

      {/* ── Date Range ── */}
      <div className="card">
        <div className="section-header">
          <h2 style={{ marginBottom: 0 }}>Date Range</h2>
          {dateLoading && <span className="date-loading-badge">⏳ Loading…</span>}
        </div>
        {browseErr.dates && <div className="browse-err" style={{ marginBottom: 6 }}>{browseErr.dates}</div>}
        <p className="hint" style={{ marginTop: 4, marginBottom: 12 }}>
          Auto-filled from the first and last commits when you select a repository. You can edit freely.
        </p>
        <div className="form-grid">
          <Field label="Start Date" value={config.sprint_start}
            onChange={v => set('sprint_start', v)} type="date" required />
          <Field label="End Date" value={config.sprint_end}
            onChange={v => set('sprint_end', v)} type="date" required />
          <Field label="Report Label" value={config.sprint_name}
            onChange={v => set('sprint_name', v)}
            placeholder="e.g. Q1-2025 or Sprint 12  (optional)" />
        </div>
      </div>

      {/* ── Analysis Mode ── */}
      <div className="card">
        <h2>Analysis Mode</h2>
        <div className="form-row" style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 8 }}>
          <label className="field-label">Mode</label>
          <div className="radio-group">
            {['claude', 'gemini', 'openai', 'keyword', 'ollama'].map(m => (
              <label key={m} className="radio-label">
                <input type="radio" name="analysis_mode" value={m}
                  checked={config.analysis_mode === m}
                  onChange={() => set('analysis_mode', m)} />
                {m}
              </label>
            ))}
          </div>
        </div>
        <ModeFields config={config} set={set} />
      </div>

      {/* ── Actions ── */}
      <div className="actions">
        <button className="btn-primary" onClick={save} disabled={status === 'saving'}>
          {status === 'saving' ? 'Saving...' : 'Save Config'}
        </button>
        <button className="btn-primary" onClick={saveAndRun} disabled={status === 'saving'}>
          Save & Run
        </button>
        <button className="btn-secondary" onClick={() => {
          localStorage.removeItem(STORAGE_KEY)
          sessionStorage.removeItem(SESSION_KEY)
          setConfig(DEFAULT_CONFIG)
          setProjects(null); setRepos(null); setBranches(null)
          fetch('/api/config', { method: 'DELETE' })
        }}>
          Clear
        </button>
        {status === 'saved' && <span className="status-ok">Saved successfully</span>}
        {status === 'error'  && <span className="status-err">Failed to save</span>}
      </div>

    </div>
  )
}

function Field({ label, value, onChange, onKeyDown, type = 'text', required, placeholder, autoComplete }) {
  return (
    <div className="field">
      <label className="field-label">
        {label}{required && <span className="required"> *</span>}
      </label>
      <input className="field-input" type={type} value={value}
        placeholder={placeholder} autoComplete={autoComplete}
        onChange={e => onChange(e.target.value)}
        onKeyDown={onKeyDown} />
    </div>
  )
}
