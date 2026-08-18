# src/server/routes/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health():
    # R13: single version source — never hard-code the API version here.
    from src import __version__
    return {
        "ok": True,
        "status": "running",
        "version": __version__,
        "agent": {"chat": True, "streaming": False},
    }
