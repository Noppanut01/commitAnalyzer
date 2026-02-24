import React, { useState, useRef, useLayoutEffect } from 'react'

const CATEGORIES = ['All', 'Bug Fix', 'Feature', 'Refactor', 'Chore', 'Unclear']

// Detects real DOM overflow — no character-count guessing.
// "More" shows only when text is actually clipped by CSS.
function ExpandableCell({ text, prefix }) {
  const [isExp, setIsExp]       = useState(false)
  const [overflows, setOverflows] = useState(false)
  const textRef = useRef(null)

  useLayoutEffect(() => {
    const el = textRef.current
    if (!el || isExp) return
    setOverflows(el.scrollWidth > el.offsetWidth)
  }, [text, isExp])

  return (
    <div className="expandable-cell">
      <div ref={textRef} className={isExp ? 'cell-text cell-text--exp' : 'cell-text'}>
        {prefix}{text}
      </div>
      <button
        className="msg-toggle-btn"
        style={{ visibility: (overflows || isExp) ? 'visible' : 'hidden' }}
        onClick={() => setIsExp(e => !e)}
      >
        {isExp ? 'Less' : 'More'}
      </button>
    </div>
  )
}

export default function CommitTable({ rows }) {
  const [filter, setFilter]     = useState('All')
  const [expanded, setExpanded] = useState(new Set())

  const toggleMerge = (id) =>
    setExpanded(prev => {
      const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
    })

  const getChildren = (mergeId) => {
    const all = rows.filter(r => r.from_merge_commit === mergeId)
    return filter === 'All' ? all : all.filter(c => c.category === filter)
  }

  const topLevel = filter === 'All'
    ? rows.filter(r => !r.from_merge_commit)
    : rows.filter(r => {
        if (r.from_merge_commit) return false
        if (r.is_merge_commit)   return getChildren(r.commit_id).length > 0
        return r.category === filter
      })

  const workCount = rows.filter(r => !r.is_merge_commit).length

  const bugBadge = ok => ok
    ? <span className="badge badge-yes">Yes</span>
    : <span className="badge badge-no">No</span>

  const catBadge = cat =>
    <span className={`badge cat-${cat.toLowerCase().replace(' ', '-')}`}>{cat}</span>

  const sevBadge = sev =>
    <span className={`badge sev-${sev.toLowerCase().replace('/', '\\/').replace(' ', '-')}`}>{sev}</span>

  return (
    <div className="card">
      <div className="table-header">
        <h3>Commit Details ({workCount})</h3>
        <div className="filter-tabs">
          {CATEGORIES.map(c => (
            <button key={c}
              className={`filter-tab ${filter === c ? 'active' : ''}`}
              onClick={() => setFilter(c)}
            >{c}</button>
          ))}
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 4, padding: 0 }}></th>
              <th className="nowrap">Date</th>
              <th className="nowrap">Commit</th>
              <th>Message</th>
              <th>Author</th>
              <th>Bug Fix</th>
              <th>Category</th>
              <th>Severity</th>
              <th>Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {topLevel.length === 0 && (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '32px' }}>
                  No commits
                </td>
              </tr>
            )}

            {topLevel.map((r, i) => {
              const children = r.is_merge_commit ? getChildren(r.commit_id) : []
              const isExp    = expanded.has(r.commit_id)

              const prBtn = r.is_merge_commit && children.length > 0 ? (
                <button
                  className={`pr-inline-btn${isExp ? ' pr-inline-btn--open' : ''}`}
                  onClick={(e) => { e.stopPropagation(); toggleMerge(r.commit_id) }}
                  title={isExp ? 'Collapse PR commits' : `Expand ${children.length} commits in PR`}
                >
                  PR {isExp ? '▼' : '▶'} {children.length}
                </button>
              ) : null

              return (
                <React.Fragment key={r.commit_id + '-' + i}>

                  <tr className={r.is_merge_commit ? 'merge-row' : ''}>
                    <td className={r.is_merge_commit ? 'merge-accent-cell' : ''}
                        style={{ padding: 0, width: 4 }}></td>
                    <td className="nowrap">{r.date}</td>
                    <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {r.commit_id?.slice(0, 7)}
                    </td>
                    <td className="msg-cell">
                      <ExpandableCell text={r.message} prefix={prBtn} />
                    </td>
                    <td className="nowrap" style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{r.author}</td>
                    <td className="center">{bugBadge(r.is_bug_fix)}</td>
                    <td>{catBadge(r.category)}</td>
                    <td>{sevBadge(r.severity)}</td>
                    <td className="reasoning-cell">
                      <ExpandableCell text={r.reasoning} />
                    </td>
                  </tr>

                  {r.is_merge_commit && isExp && children.length > 0 && (
                    <tr className="pr-children-row">
                      <td colSpan={9} style={{ padding: 0 }}>
                        <div className="pr-children-section">
                          <table className="pr-children-table">
                            <thead>
                              <tr className="pr-children-hdr">
                                <th style={{ width: 60 }}>Commit</th>
                                <th>Message</th>
                                <th>Author</th>
                                <th>Bug Fix</th>
                                <th>Category</th>
                                <th>Severity</th>
                                <th>Reasoning</th>
                              </tr>
                            </thead>
                            <tbody>
                              {children.map((child, j) => (
                                <tr key={j} className="pr-child-inner">
                                  <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                    {child.commit_id?.slice(0, 7)}
                                  </td>
                                  <td className="msg-cell">
                                    <ExpandableCell text={child.message} />
                                  </td>
                                  <td className="nowrap" style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                                    {child.author}
                                  </td>
                                  <td className="center">{bugBadge(child.is_bug_fix)}</td>
                                  <td>{catBadge(child.category)}</td>
                                  <td>{sevBadge(child.severity)}</td>
                                  <td className="reasoning-cell">
                                    <ExpandableCell text={child.reasoning} />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}

                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
