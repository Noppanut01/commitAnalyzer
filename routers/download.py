"""
File download endpoint.

Endpoint:
    GET /api/download/{filename}  — serve a generated .xlsx from the output/ folder
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_DOWNLOAD_DIR = Path("output").resolve()


@router.get("/api/download/{filename}")
def download(filename: str):
    filepath = (_DOWNLOAD_DIR / filename).resolve()
    if not filepath.is_relative_to(_DOWNLOAD_DIR):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        str(filepath),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filepath.name,
    )
