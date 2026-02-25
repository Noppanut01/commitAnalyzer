"""
FastAPI application factory for Sprint Bug Fix Analyzer.

Run:
    uvicorn app:app --reload          (development)
    uvicorn app:app --host 0.0.0.0 --port 8000   (production)

Endpoints are split across routers:
    routers/config.py    — GET/POST/DELETE /api/config
    routers/azure.py     — GET /api/azure/*  (browse orgs/projects/repos/branches)
    routers/analyze.py   — GET /api/analyze  (SSE analysis stream)
    routers/download.py  — GET /api/download/{filename}
    /                    — React SPA (served from dist/ when built)
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import analyze, azure, config, download

app = FastAPI(title="Sprint Bug Fix Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(azure.router)
app.include_router(analyze.router)
app.include_router(download.router)

# Serve the React SPA from the built dist/ directory (must be registered last)
if os.path.isdir("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
