"""HTTP adapter for the minimal Knowledge Compiler path."""

from fastapi import APIRouter, HTTPException

from src.kc.compiler.normalize import normalize_text

router = APIRouter(prefix="/api/v1/kc", tags=["knowledge-compiler"])


@router.post("/compile")
async def compile_knowledge(body: dict):
    from src.kc.api import compile_source

    try:
        return await compile_source(
            str(body["source"]),
            document=normalize_text(str(body["content"]), source=str(body["source"])),
            candidate_json=str(body["candidate_json"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
