export default function KpiCards({ kpis }) {
  return (
    <div className="kpi-row">
      <KpiCard label="Total Commits"    value={kpis.total_commits} />
      <KpiCard label="Bug Fixes"        value={kpis.bug_fixes}     accent="danger" />
      <KpiCard label="Bug Fix Rate"     value={`${kpis.bug_fix_rate}%`} accent="warning" />
      <KpiCard label="Non-Bug Commits"  value={kpis.non_bug_fix}   accent="success" />
    </div>
  )
}

function KpiCard({ label, value, accent }) {
  return (
    <div className={`kpi-card${accent ? ` kpi-${accent}` : ''}`}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  )
}
