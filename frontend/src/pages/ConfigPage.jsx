import { useState, useEffect } from 'react'
import ModeFields from '../components/ModeFields'

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
}

export default function ConfigPage({ onRun }) {
  const [config, setConfig]       = useState(DEFAULT_CONFIG)
  const [status, setStatus]       = useState(null)
  const [loading, setLoading]     = useState(true)
  const [loadError, setLoadError] = useState(null)

  // ── Browse cascade state ─────────────────────────────────────────────────
  const [projects,    setProjects]    = useState(null)  // null|'loading'|string[]
  const [repos,       setRepos]       = useState(null)
  const [branches,    setBranches]    = useState(null)
  const [dateLoading, setDateLoading] = useState(false)
  const [browseErr,   setBrowseErr]   = useState({})

  // ── Load saved config on mount — merges server values into form ──────────────
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const timer = setTimeout(() => { if (!cancelled) controller.abort() }, 6000)

    fetch('/api/config', { signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => { if (cancelled) return; clearTimeout(timer); setConfig(prev => ({ ...prev, ...data })); setLoading(false) })
      .catch(err => {
        if (cancelled) return
        clearTimeout(timer)
        setLoadError(err.name === 'AbortError' ? 'timeout' : 'refused')
        setLoading(false)
      })

    return () => { cancelled = true; clearTimeout(timer); controller.abort() }
  }, [])

  const set = (key, value) => setConfig(prev => ({ ...prev, [key]: value }))

  // ── Helpers ──────────────────────────────────────────────────────────────
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

  // ── Derived: when are browse buttons enabled ──────────────────────────────
  const canBrowseProjects = !!(config.azure_pat && config.azure_org)
  const canBrowseRepos    = !!(config.azure_pat && config.azure_org && config.azure_project)

  // ── Step 1 — load projects ───────────────────────────────────────────────
  const loadProjects = () => {
    setProjects('loading')
    const q = qs({ org: config.azure_org, pat: config.azure_pat })
    apiGet(`/api/azure/projects?${q}`, 'projects')
      .then(data => setProjects(data.projects || []))
      .catch(e => { setProjects(null); setBrowseErr(prev => ({ ...prev, projects: e.message })) })
  }

  // ── Step 2 — project selected → load repos ───────────────────────────────
  const onSelectProject = (project) => {
    set('azure_project', project)
    setProjects(null)
    loadReposFor(project)
  }

  const loadReposFor = (project) => {
    const { azure_org: org, azure_pat: pat } = config
    setRepos('loading')
    const q = qs({ org, project, pat })
    apiGet(`/api/azure/repos?${q}`, 'repos')
      .then(data => setRepos(data.repos || []))
      .catch(e => { setRepos(null); setBrowseErr(prev => ({ ...prev, repos: e.message })) })
  }

  // ── Step 3 — repo selected → load branches + commit dates ────────────────
  const onSelectRepo = (repo) => {
    set('azure_repo', repo)
    setRepos(null)

    const { azure_org: org, azure_project: project, azure_pat: pat } = config

    setBranches('loading')
    const q = qs({ org, project, repo, pat })
    apiGet(`/api/azure/branches?${q}`, 'branches')
      .then(data => setBranches(data.branches || []))
      .catch(e => { setBranches(null); setBrowseErr(prev => ({ ...prev, branches: e.message })) })

    fetchCommitDates(org, project, repo, pat, '')
  }

  // ── Step 4 — branch selected → refresh dates ────────────────────────────
  const onSelectBranch = (branch) => {
    set('azure_branch', branch)
    setBranches(null)
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

  // ── Save / run ────────────────────────────────────────────────────────────
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

  // ── Loading / error screens ───────────────────────────────────────────────
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

  // ── Main form ─────────────────────────────────────────────────────────────
  return (
    <div className="page-config">

      {/* ── Azure DevOps ── */}
      <div className="card">
        <h2>Azure DevOps</h2>

        {/* PAT (plain) + Org (⤵ disabled until both filled) */}
        <div className="form-grid">
          <Field label="Personal Access Token" value={config.azure_pat}
            onChange={v => set('azure_pat', v)} type="password" required
            placeholder="Enter your Personal Access Token" autoComplete="off" />

          {/* Org + ⤵ → projects (disabled until PAT + Org filled) */}
          <div className="field">
            <label className="field-label">Organisation <span className="required">*</span></label>
            <div className="field-row">
              <input className="field-input" value={config.azure_org}
                placeholder="Enter your organization name"
                onChange={e => set('azure_org', e.target.value)} />
              <button className="btn-browse"
                onClick={loadProjects}
                disabled={!canBrowseProjects || projects === 'loading'}
                title="Browse projects">
                {projects === 'loading' ? '…' : '⤵'}
              </button>
            </div>
            {browseErr.projects && <div className="browse-err">{browseErr.projects}</div>}
            {Array.isArray(projects) && projects.length > 0 && (
              <select className="field-select" defaultValue=""
                onChange={e => { if (e.target.value) onSelectProject(e.target.value) }}>
                <option value="" disabled>Select project…</option>
                {projects.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            )}
          </div>
        </div>

        <div className="form-grid" style={{ marginTop: 12 }}>

          {/* Project (auto-filled from org browse, plain input) */}
          <Field label="Project" value={config.azure_project} required
            onChange={v => set('azure_project', v)}
            placeholder="Enter your project name" />

          {/* Repository + ⤵ → repos dropdown (disabled until PAT + Org + Project filled) */}
          <div className="field">
            <label className="field-label">Repository <span className="required">*</span></label>
            <div className="field-row">
              <input className="field-input" value={config.azure_repo}
                placeholder="Enter your repository name"
                onChange={e => set('azure_repo', e.target.value)} />
              <button className="btn-browse"
                onClick={() => loadReposFor(config.azure_project)}
                disabled={!canBrowseRepos || repos === 'loading'}
                title="Browse repositories">
                {repos === 'loading' ? '…' : '⤵'}
              </button>
            </div>
            {browseErr.repos && <div className="browse-err">{browseErr.repos}</div>}
            {Array.isArray(repos) && repos.length > 0 && (
              <select className="field-select" defaultValue=""
                onChange={e => { if (e.target.value) onSelectRepo(e.target.value) }}>
                <option value="" disabled>Select repository…</option>
                {repos.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            )}
          </div>

          {/* Branch (optional) */}
          <div className="field">
            <label className="field-label">
              Branch <span className="field-hint">(optional — blank = all branches)</span>
            </label>
            <input className="field-input" value={config.azure_branch}
              placeholder="Enter branch name (leave blank for all)"
              onChange={e => set('azure_branch', e.target.value)} />
            {browseErr.branches && <div className="browse-err">{browseErr.branches}</div>}
            {Array.isArray(branches) && branches.length > 0 && (
              <select className="field-select" defaultValue=""
                onChange={e => { if (e.target.value) onSelectBranch(e.target.value) }}>
                <option value="" disabled>Select branch…</option>
                {branches.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            )}
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
            {['claude', 'gemini', 'keyword', 'ollama'].map(m => (
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
          setConfig(DEFAULT_CONFIG)
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

function Field({ label, value, onChange, type = 'text', required, placeholder, autoComplete }) {
  return (
    <div className="field">
      <label className="field-label">
        {label}{required && <span className="required"> *</span>}
      </label>
      <input className="field-input" type={type} value={value}
        placeholder={placeholder} autoComplete={autoComplete}
        onChange={e => onChange(e.target.value)} />
    </div>
  )
}
