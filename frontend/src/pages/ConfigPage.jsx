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
  openai_api_key: '',
  openai_model: '',
  azure_openai_endpoint: '',
  azure_openai_api_key: '',
  azure_openai_deployment: '',
  azure_openai_api_version: '',
}

export default function ConfigPage({ onRun }) {
  const [config, setConfig]       = useState(DEFAULT_CONFIG)
  const [status, setStatus]       = useState(null)
  const [missing, setMissing]     = useState([])

  const [projects,    setProjects]    = useState(null)
  const [repos,       setRepos]       = useState(null)
  const [branches,    setBranches]    = useState(null)
  const [dateLoading, setDateLoading] = useState(false)
  const [browseErr,   setBrowseErr]   = useState({})

  // Clear all persisted state on every load
  useEffect(() => {
    localStorage.removeItem('bugAnalyzer_config')
    sessionStorage.removeItem('bugAnalyzer_secrets')
    fetch('/api/config', { method: 'DELETE' }).catch(() => {})
  }, [])

  const REQUIRED = [
    ['azure_pat',     'Personal Access Token'],
    ['azure_org',     'Organisation'],
    ['azure_project', 'Project'],
    ['azure_repo',    'Repository'],
    ['sprint_start',  'Start Date'],
    ['sprint_end',    'End Date'],
  ]

  const getModeRequired = () => {
    const mode = config.analysis_mode
    if (mode === 'claude')       return [['anthropic_api_key',    'Anthropic API Key']]
    if (mode === 'openai')       return [['openai_api_key',       'OpenAI API Key']]
    if (mode === 'azure_openai') return [
      ['azure_openai_endpoint',   'Azure OpenAI Endpoint'],
      ['azure_openai_api_key',    'Azure OpenAI API Key'],
      ['azure_openai_deployment', 'Deployment Name'],
    ]
    if (mode === 'gemini') {
      if (config.gemini_use_vertex === 'true') return [['google_cloud_project', 'GCP Project']]
      return [['google_api_key', 'Google API Key']]
    }
    return [] // ollama, keyword — no required key
  }

  const set = (key, value) => {
    setConfig(prev => ({ ...prev, [key]: value }))
    setMissing(prev => prev.filter(k => k !== key))
  }

  const apiPost = async (path, body, errKey) => {
    setBrowseErr(prev => ({ ...prev, [errKey]: '' }))
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) {
      const data = await r.json().catch(() => ({}))
      throw new Error(data.detail || `HTTP ${r.status}`)
    }
    return r.json()
  }

  // Step 1 — load projects (auto on Org blur)
  const loadProjects = (org = config.azure_org, pat = config.azure_pat) => {
    if (!org || !pat || projects === 'loading') return
    setProjects('loading')
    setRepos(null); setBranches(null)
    apiPost('/api/azure/projects', { org, pat }, 'projects')
      .then(data => setProjects(data.projects || []))
      .catch(e => { setProjects(null); setBrowseErr(prev => ({ ...prev, projects: e.message })) })
  }

  // Step 2 — project chosen → load repos
  const onSelectProject = (project) => {
    set('azure_project', project)
    setRepos('loading'); setBranches(null)
    const { azure_org: org, azure_pat: pat } = config
    apiPost('/api/azure/repos', { org, project, pat }, 'repos')
      .then(data => setRepos(data.repos || []))
      .catch(e => { setRepos(null); setBrowseErr(prev => ({ ...prev, repos: e.message })) })
  }

  // Step 3 — repo chosen → load branches + dates
  const onSelectRepo = (repo) => {
    set('azure_repo', repo)
    setBranches('loading')
    const { azure_org: org, azure_project: project, azure_pat: pat } = config
    apiPost('/api/azure/branches', { org, project, repo, pat }, 'branches')
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
    apiPost('/api/azure/commit-dates', { org, project, repo, pat, branch }, 'dates')
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

  const saveAndRun = async () => {
    const allRequired = [...REQUIRED, ...getModeRequired()]
    const empty = allRequired.filter(([k]) => !config[k]).map(([k]) => k)
    if (empty.length > 0) { setMissing(empty); return }
    const ok = await save()
    if (ok) onRun()
  }

  return (
    <div className="page-config">

      {/* ── Azure DevOps ── */}
      <div className="card">
        <h2>Azure DevOps</h2>

        <div className="form-grid">
          {/* PAT */}
          <Field label="Personal Access Token" value={config.azure_pat} required
            type="password" placeholder="Enter your Personal Access Token"
            autoComplete="off" error={missing.includes('azure_pat')}
            onChange={v => {
              set('azure_pat', v)
              setProjects(null); setRepos(null); setBranches(null)
            }}
            onKeyDown={e => e.key === 'Enter' && loadProjects(config.azure_org, e.target.value)} />

          {/* Organisation — auto-loads projects on blur or Enter */}
          <div className="field">
            <label className="field-label">Organisation <span className="required">*</span></label>
            <input className={`field-input${missing.includes('azure_org') ? ' field-error' : ''}`}
              value={config.azure_org}
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
            <select className={`field-input field-input-select${missing.includes('azure_project') ? ' field-error' : ''}`}
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
            <select className={`field-input field-input-select${missing.includes('azure_repo') ? ' field-error' : ''}`}
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
            onChange={v => set('sprint_start', v)} type="date" required
            error={missing.includes('sprint_start')} />
          <Field label="End Date" value={config.sprint_end}
            onChange={v => set('sprint_end', v)} type="date" required
            error={missing.includes('sprint_end')} />
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
            {[
              ['claude',       'Claude'],
              ['gemini',       'Gemini'],
              ['openai',       'OpenAI'],
              ['azure_openai', 'Azure OpenAI'],
              ['keyword',      'Keyword'],
              ['ollama',       'Ollama'],
            ].map(([val, label]) => (
              <label key={val} className="radio-label">
                <input type="radio" name="analysis_mode" value={val}
                  checked={config.analysis_mode === val}
                  onChange={() => set('analysis_mode', val)} />
                {label}
              </label>
            ))}
          </div>
        </div>
        <ModeFields config={config} set={set} missing={missing} />
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
          setProjects(null); setRepos(null); setBranches(null)
          fetch('/api/config', { method: 'DELETE' })
        }}>
          Clear
        </button>
        {status === 'saved' && <span className="status-ok">Saved successfully</span>}
        {status === 'error'  && <span className="status-err">Failed to save</span>}
        {missing.length > 0 && (
          <span className="status-err">
            Required: {[...REQUIRED, ...getModeRequired()].filter(([k]) => missing.includes(k)).map(([, label]) => label).join(', ')}
          </span>
        )}
      </div>

    </div>
  )
}

function Field({ label, value, onChange, onKeyDown, type = 'text', required, error, placeholder, autoComplete }) {
  return (
    <div className="field">
      <label className="field-label">
        {label}{required && <span className="required"> *</span>}
      </label>
      <input className={`field-input${error ? ' field-error' : ''}`} type={type} value={value}
        placeholder={placeholder} autoComplete={autoComplete}
        onChange={e => onChange(e.target.value)}
        onKeyDown={onKeyDown} />
    </div>
  )
}
