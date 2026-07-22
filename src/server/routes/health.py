# src/server/routes/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health():
    return {
        "ok": True,
        "status": "running",
        "version": "0.2.0",
        "agent": {"chat": True, "streaming": False},
    }
