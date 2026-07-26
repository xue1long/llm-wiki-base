"""Local Claude Code CLI bridge for the web frontend.

Spec: FRONTEND_DESIGN.md §4.4 / §5.7 / §7F / §12.

Two endpoints:
  GET  /api/v1/agent-cli/status   - probe `claude --version`
  POST /api/v1/agent-cli/chat     - SSE stream of claude's stream-json events

Security (per §12):
  - Subprocess invoked via asyncio.create_subprocess_exec with arg array,
    NEVER shell=True, NEVER string interpolation of user message.
  - Service is expected to bind 127.0.0.1 only.
  - Working directory is pinned to project root.
  - Per-run timeout + max-turns + optional max-budget-usd bound resources.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_logger = logging.getLogger(__name__)

# ---------- Config ----------
# Windows quirk: Python's subprocess won't resolve .cmd via PATHEXT when
# passing an arg list without shell=True. Resolve to the full path once at
# import time so subprocess_exec gets a real executable.
CLAUDE_CMD = shutil.which("claude") or "claude"
PERMISSION_MODE = "acceptEdits"   # user opted in to file edits (§12.3)
MAX_TURNS = 8
TIMEOUT_S = 180
MAX_BUDGET_USD: str | None = None  # user opted out of spending cap (§4.4)
EXTRA_ARGS: list[str] = []         # e.g. ["--bare"] or ["--allowedTools","Read,Grep,Glob"]
VERSION_PROBE_TIMEOUT_S = 10

# routes/ -> server/ -> src/ -> project_root
WORKDIR = Path(__file__).resolve().parents[3]

router = APIRouter(prefix="/api/v1", tags=["agent-cli"])


# ---------- Endpoints ----------

@router.get("/agent-cli/status")
async def status():
    """Probe `claude --version`. Always 200; body conveys availability."""
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CMD, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=VERSION_PROBE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"available": False, "error": "claude --version 超时"}
        if proc.returncode == 0:
            version_line = (out.decode(errors="ignore").strip().splitlines() or [""])[0]
            return {"available": True, "version": version_line}
        return {
            "available": False,
            "error": (err or out).decode(errors="ignore").strip()[:500] or f"exit {proc.returncode}",
        }
    except FileNotFoundError:
        return {
            "available": False,
            "error": "claude CLI 未安装或不在 PATH。请先安装 claude code 并登录。",
        }
    except OSError as e:
        # shutil.which returned a path but exec failed (e.g. ENOENT for .cmd
        # when shell=True isn't set on Windows).
        return {"available": False, "error": f"claude 启动失败: {e}"}
    except Exception as e:
        return {"available": False, "error": str(e)[:500]}


class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None


@router.post("/agent-cli/chat")
async def chat(body: ChatRequest):
    """Stream claude's response as SSE.

    Event types emitted:
      start        - {"version": "<claude version>"}
      text_delta   - {"delta": "..."}              (visible text incremental)
      thinking_delta - {"delta": "..."}            (optional, if --include-thinking)
      tool_use     - {"name": "...", "id": "..."}  (claude invoked a tool)
      usage        - {"input_tokens": int, "output_tokens": int}
      done         - {"sessionId": "...", "fullText": "..."}
      error        - {"message": "..."}
    """
    if not body.message.strip():
        raise HTTPException(400, "message 不能为空")

    # Build arg array — NEVER shell=True, NEVER string concat (FRONTEND_DESIGN.md §12.1).
    cmd: list[str] = [
        CLAUDE_CMD,
        "--print",
        "-p", body.message,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", PERMISSION_MODE,
        "--max-turns", str(MAX_TURNS),
    ]
    if body.sessionId:
        cmd += ["--resume", body.sessionId]
    if MAX_BUDGET_USD:
        cmd += ["--max-budget-usd", MAX_BUDGET_USD]
    cmd += EXTRA_ARGS

    _logger.info("[agent-cli] spawn: cwd=%s args=%s", WORKDIR, cmd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(WORKDIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise HTTPException(503, "claude CLI 未安装")
    except Exception as e:
        raise HTTPException(500, f"spawn 失败: {e}")

    return StreamingResponse(
        _stream_claude(proc),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_claude(proc: asyncio.subprocess.Process) -> AsyncIterator[bytes]:
    """Consume claude's stream-json NDJSON stdout and yield SSE frames."""
    # Background task: drain stderr so the pipe never fills.
    stderr_chunks: list[str] = []
    async def _drain_stderr():
        while True:
            chunk = await proc.stderr.readline()
            if not chunk:
                return
            stderr_chunks.append(chunk.decode(errors="ignore"))

    drain_task = asyncio.create_task(_drain_stderr())
    full_text_parts: list[str] = []
    usage_out: dict | None = None
    session_id: str | None = None

    try:
        # Emit start with claude version (best-effort; if version probe failed earlier,
        # we just emit an empty version string).
        yield _sse("start", {"version": ""})

        async def _timeout_killer():
            try:
                await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_S)
            except asyncio.TimeoutError:
                _logger.warning("[agent-cli] timeout after %ds, killing", TIMEOUT_S)
                proc.kill()
                await proc.wait()

        killer = asyncio.create_task(_timeout_killer())

        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="ignore").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                yield _sse("stdout", {"chunk": line})
                continue

            etype = ev.get("type")

            # Pull session_id from any event that carries it.
            sid = ev.get("session_id")
            if sid:
                session_id = sid

            # ── claude stream-json event types we observed in the wild ──
            # 1) system/hook_*  → hooks firing (SessionStart etc.). No UI value.
            # 2) system/thinking_tokens  → token counter updates, no UI value.
            # 3) system/init  → session init info.
            # 4) assistant  → carries the assistant message; content[] contains
            #    one or more blocks of type "thinking" | "text" | "tool_use"
            #    | "tool_result". We extract these and emit our own events.
            # 5) result  → final event with session_id / usage / full result text.

            if etype == "system":
                sub = ev.get("subtype")
                if sub in ("init", "hook_started", "hook_response", "thinking_tokens"):
                    # No-op for the UI; skip silently.
                    continue
                # unknown system subtype → forward as raw agent event
                yield _sse("agent", ev)
                continue

            if etype == "assistant":
                msg = ev.get("message") or {}
                for block in msg.get("content", []) or []:
                    btype = block.get("type")
                    if btype == "text":
                        text = block.get("text", "")
                        if text:
                            full_text_parts.append(text)
                            yield _sse("text_delta", {"delta": text})
                    elif btype == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            yield _sse("thinking_delta", {"delta": thinking})
                    elif btype == "tool_use":
                        yield _sse("tool_use", {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })
                    elif btype == "tool_result":
                        yield _sse("tool_result", {
                            "toolUseId": block.get("tool_use_id", ""),
                            "content": block.get("content", ""),
                            "isError": bool(block.get("is_error", False)),
                        })
                # also forward the assistant event meta (model etc.) for UI use
                yield _sse("agent", ev)
                continue

            if etype == "result":
                # Final event from claude: carries total usage + session_id.
                if isinstance(ev.get("result"), str):
                    full_text_parts = [ev["result"]]
                usage_out = ev.get("usage") or usage_out
                yield _sse("usage", {
                    "input_tokens": (usage_out or {}).get("input_tokens", 0),
                    "output_tokens": (usage_out or {}).get("output_tokens", 0),
                })
                # done is emitted below after the stream ends; don't double-fire.
                continue

            # Unknown event types: forward as-is under a generic "agent" channel.
            yield _sse("agent", ev)

        # Wait for process to fully exit.
        await killer
        await proc.wait()
        drain_task.cancel()

        # Always emit a terminal event so the client knows the run is over.
        if proc.returncode != 0:
            err_tail = "".join(stderr_chunks).strip()[-500:]
            yield _sse("error", {
                "message": err_tail or f"claude 退出码 {proc.returncode}",
            })
        else:
            yield _sse("done", {
                "sessionId": session_id or "",
                "fullText": "".join(full_text_parts),
                "usage": usage_out or {},
            })
    except asyncio.CancelledError:
        # Client disconnected. Kill the subprocess so we don't leak.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    except Exception as e:
        _logger.exception("[agent-cli] stream failed: %s", e)
        yield _sse("error", {"message": str(e)[:500]})


def _sse(event: str, data: dict) -> bytes:
    """Encode an SSE frame: event: <name>\ndata: <json>\n\n"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")