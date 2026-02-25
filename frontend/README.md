# Sprint Bug Fix Analyzer — Frontend

React + Vite web UI for the Sprint Bug Fix Analyzer.

## Development

```bash
npm install
npm run dev     # http://localhost:5173
```

The dev server proxies `/api/*` to the FastAPI backend at `http://localhost:8000` (configured in `vite.config.js`).

## Production Build

```bash
npm run build
```

Output goes to `dist/` — the FastAPI backend serves this as static files.

## Structure

```
src/
├── App.jsx               # Root component, tab navigation (Config / Run Report)
├── main.jsx              # Entry point
├── styles.css            # All app styles
├── pages/
│   ├── ConfigPage.jsx    # Azure DevOps config, date range, analysis mode
│   └── ReportPage.jsx    # SSE progress stream + results display
└── components/
    ├── CommitTable.jsx   # Commit details table with expand/collapse
    ├── KpiCards.jsx      # Summary KPI cards
    ├── DevTable.jsx      # Bug fixes by developer
    ├── CategoryTable.jsx # Commits by category
    └── ModeFields.jsx    # API key fields per analysis mode
```
