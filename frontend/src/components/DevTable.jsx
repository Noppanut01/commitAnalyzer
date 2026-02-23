export default function DevTable({ rows }) {
  return (
    <div className="card">
      <h3>Bug Fixes by Developer</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>Developer</th>
            <th>Total</th>
            <th>Bug Fixes</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No data</td></tr>
          )}
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.developer}</td>
              <td>{r.total}</td>
              <td>{r.bug_fixes}</td>
              <td>{r.pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
