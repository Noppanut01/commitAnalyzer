"""
Azure DevOps browse endpoints.

All credentials are passed as query parameters so the user can browse
org / project / repo / branch without saving the config first.

Endpoints:
    GET /api/azure/orgs           — list organisations accessible with PAT
    GET /api/azure/projects       — list projects in an org
    GET /api/azure/repos          — list repositories in a project
    GET /api/azure/branches       — list branches in a repo
    GET /api/azure/commit-dates   — oldest + newest commit dates in a repo
"""

from fastapi import APIRouter, HTTPException

from azure_client import AzureAPIError, AzureDevOpsClient
from models import SprintConfig

router = APIRouter(prefix="/api/azure")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client(org: str, project: str = "_", repo: str = "_",
                 pat: str = "") -> AzureDevOpsClient:
    """Build an AzureDevOpsClient from explicit credentials."""
    config = SprintConfig(
        org=org, project=project, repo=repo, pat=pat,
        anthropic_api_key="",
        sprint_start="", sprint_end="",
    )
    return AzureDevOpsClient(config)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/orgs")
def azure_orgs(pat: str = ""):
    if not pat:
        raise HTTPException(status_code=400, detail="pat is required.")
    client = _make_client(org="_", pat=pat)
    try:
        return {"orgs": client.get_organizations()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/projects")
def azure_projects(org: str = "", pat: str = ""):
    if not org or not pat:
        raise HTTPException(status_code=400, detail="org and pat are required.")
    client = _make_client(org=org, pat=pat)
    try:
        return {"projects": client.get_projects()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/repos")
def azure_repos(org: str = "", project: str = "", pat: str = ""):
    if not all([org, project, pat]):
        raise HTTPException(status_code=400,
                            detail="org, project and pat are required.")
    client = _make_client(org=org, project=project, pat=pat)
    try:
        return {"repos": client.get_repositories()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/branches")
def azure_branches(org: str = "", project: str = "", repo: str = "",
                   pat: str = ""):
    if not all([org, project, repo, pat]):
        raise HTTPException(status_code=400,
                            detail="org, project, repo and pat are required.")
    client = _make_client(org=org, project=project, repo=repo, pat=pat)
    try:
        return {"branches": client.get_branches()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/commit-dates")
def azure_commit_dates(org: str = "", project: str = "", repo: str = "",
                       pat: str = "", branch: str = ""):
    if not all([org, project, repo, pat]):
        raise HTTPException(status_code=400,
                            detail="org, project, repo and pat are required.")
    client = _make_client(org=org, project=project, repo=repo, pat=pat)
    try:
        return client.get_commit_date_range(branch=branch)
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
