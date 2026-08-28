"""HTTP adapter for the minimal Knowledge Compiler path."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/kc", tags=["knowledge-compiler"])


@router.post("/compile")
async def compile_knowledge(body: dict):
    from src.kc.api import compile_source

    try:
        return await compile_source(
            str(body["source"]),
            content=str(body["content"]).encode("utf-8"),
            candidate_json=str(body["candidate_json"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
