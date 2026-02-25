"""
Azure DevOps browse endpoints.

Credentials are passed in the POST request body to avoid exposing the PAT
in URL query strings and server access logs.

Endpoints:
    POST /api/azure/orgs           — list organisations accessible with PAT
    POST /api/azure/projects       — list projects in an org
    POST /api/azure/repos          — list repositories in a project
    POST /api/azure/branches       — list branches in a repo
    POST /api/azure/commit-dates   — oldest + newest commit dates in a repo
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from azure_client import AzureAPIError, AzureDevOpsClient
from models import SprintConfig

router = APIRouter(prefix="/api/azure")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class AzureBrowseBody(BaseModel):
    org: str = ""
    project: str = ""
    repo: str = ""
    pat: str = ""
    branch: str = ""


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


@router.post("/orgs")
def azure_orgs(body: AzureBrowseBody):
    if not body.pat:
        raise HTTPException(status_code=400, detail="pat is required.")
    client = _make_client(org="_", pat=body.pat)
    try:
        return {"orgs": client.get_organizations()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/projects")
def azure_projects(body: AzureBrowseBody):
    if not body.org or not body.pat:
        raise HTTPException(status_code=400, detail="org and pat are required.")
    client = _make_client(org=body.org, pat=body.pat)
    try:
        return {"projects": client.get_projects()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/repos")
def azure_repos(body: AzureBrowseBody):
    if not all([body.org, body.project, body.pat]):
        raise HTTPException(status_code=400,
                            detail="org, project and pat are required.")
    client = _make_client(org=body.org, project=body.project, pat=body.pat)
    try:
        return {"repos": client.get_repositories()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/branches")
def azure_branches(body: AzureBrowseBody):
    if not all([body.org, body.project, body.repo, body.pat]):
        raise HTTPException(status_code=400,
                            detail="org, project, repo and pat are required.")
    client = _make_client(org=body.org, project=body.project,
                          repo=body.repo, pat=body.pat)
    try:
        return {"branches": client.get_branches()}
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/commit-dates")
def azure_commit_dates(body: AzureBrowseBody):
    if not all([body.org, body.project, body.repo, body.pat]):
        raise HTTPException(status_code=400,
                            detail="org, project, repo and pat are required.")
    client = _make_client(org=body.org, project=body.project,
                          repo=body.repo, pat=body.pat)
    try:
        return client.get_commit_date_range(branch=body.branch)
    except AzureAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
