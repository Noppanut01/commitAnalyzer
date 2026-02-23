"""
File download endpoint.

Endpoint:
    GET /api/download/{filename}  — serve a generated .xlsx from the output/ folder
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/api/download/{filename}")
def download(filename: str):
    filepath = os.path.join("output", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
