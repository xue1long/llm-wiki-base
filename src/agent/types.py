"""AgentLoopAction + AgentEvent + AgentRuntime types."""
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class AgentLoopAction:
    action: Literal["final", "tool", "user_input"]
    tool: Optional[str] = None
    query: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    top_k: int = 5
    allow_overwrite: bool = False
    fields: list[dict] = field(default_factory=list)  # for user_input
    answer: Optional[str] = None  # for final

    @classmethod
    def from_json(cls, raw: str) -> "AgentLoopAction":
        import json
        d = json.loads(raw)
        return cls(**d)


@dataclass
class AgentEvent:
    type: str
    iteration: int
    timestamp: int
    payload: dict = field(default_factory=dict)

    @classmethod
    def run_started(cls, session_id: str, mode: str) -> "AgentEvent":
        import time
        return cls(type="run_started", iteration=0, timestamp=int(time.time()*1000),
                  payload={"sessionId": session_id, "mode": mode})

    @classmethod
    def tool_started(cls, iteration: int, tool: str, params: dict) -> "AgentEvent":
        import time
        return cls(type="tool_started", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"tool": tool, "params": params})

    @classmethod
    def tool_completed(cls, iteration: int, tool: str, result: dict) -> "AgentEvent":
        import time
        return cls(type="tool_completed", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"tool": tool, "result": result})

    @classmethod
    def final_answer(cls, iteration: int, answer: str, references: list) -> "AgentEvent":
        import time
        return cls(type="final_answer", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"answer": answer, "references": references})


@dataclass
class AgentConfig:
    model: str = "gpt-4o-mini"
    max_iterations: int = 8  # standard mode MVP
    cost_cap_usd: float = 0.5  # MVP: not enforced; placeholder
