import { useState } from 'react'

const CATEGORIES = ['All', 'Bug Fix', 'Feature', 'Refactor', 'Chore', 'Unclear']

export default function CommitTable({ rows }) {
  const [filter, setFilter] = useState('All')

  const filtered = filter === 'All' ? rows : rows.filter(r => r.category === filter)

  return (
    <div className="card">
      <div className="table-header">
        <h3>Commit Details ({filtered.length})</h3>
        <div className="filter-tabs">
          {CATEGORIES.map(c => (
            <button
              key={c}
              className={`filter-tab ${filter === c ? 'active' : ''}`}
              onClick={() => setFilter(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Commit</th>
              <th>Author</th>
              <th>Message</th>
              <th>Bug Fix</th>
              <th>Category</th>
              <th>Severity</th>
              <th>Confidence</th>
              <th>Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                  No commits
                </td>
              </tr>
            )}
            {filtered.map((r, i) => (
              <tr key={i}>
                <td className="nowrap">{r.date}</td>
                <td className="mono">{r.commit_id}</td>
                <td>{r.author}</td>
                <td className="msg-cell">{r.message}</td>
                <td className="center">
                  {r.is_bug_fix
                    ? <span className="badge badge-yes">Yes</span>
                    : <span className="badge badge-no">No</span>
                  }
                </td>
                <td>
                  <span className={`badge cat-${r.category.toLowerCase().replace(' ', '-')}`}>
                    {r.category}
                  </span>
                </td>
                <td>
                  <span className={`badge sev-${r.severity.toLowerCase().replace('/', '\\/').replace(' ', '-')}`}>
                    {r.severity}
                  </span>
                </td>
                <td>
                  <span className={`badge conf-${r.confidence.toLowerCase()}`}>
                    {r.confidence}
                  </span>
                </td>
                <td className="reasoning-cell">{r.reasoning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
