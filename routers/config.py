"""
In-memory config store and CRUD endpoints.

Config is held entirely in RAM — nothing is written to disk.
PAT and API keys disappear when the server stops.

Endpoints:
    GET    /api/config  — return current in-memory config
    POST   /api/config  — store config (replaces previous values)
    DELETE /api/config  — wipe config
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory store  (mutated in-place so other modules can hold a reference)
# ---------------------------------------------------------------------------

_config: dict = {}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ConfigPayload(BaseModel):
    azure_org: str = ""
    azure_project: str = ""
    azure_repo: str = ""
    azure_pat: str = ""
    azure_branch: str = ""
    sprint_name: str = ""
    sprint_start: str = ""
    sprint_end: str = ""
    analysis_mode: str = "claude"
    anthropic_api_key: str = ""
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_use_vertex: str = "false"
    google_cloud_project: str = ""
    google_cloud_region: str = "us-central1"
    ollama_model: str = "qwen2.5:3b"
    ollama_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/config")
def get_config():
    """Return current in-memory config (empty dict on first load)."""
    return dict(_config)


@router.post("/api/config")
def save_config(payload: ConfigPayload):
    """Store config in memory — nothing is written to disk."""
    _config.clear()
    _config.update(payload.model_dump())
    return {"status": "saved"}


@router.delete("/api/config")
def clear_config():
    """Wipe the in-memory config (called when user clicks Clear)."""
    _config.clear()
    return {"status": "cleared"}
