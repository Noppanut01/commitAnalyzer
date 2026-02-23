export default function CategoryTable({ rows }) {
  return (
    <div className="card">
      <h3>Commits by Category</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>Category</th>
            <th>Count</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>
                <span className={`badge cat-${r.category.toLowerCase().replace(' ', '-')}`}>
                  {r.category}
                </span>
              </td>
              <td>{r.count}</td>
              <td>{r.pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
