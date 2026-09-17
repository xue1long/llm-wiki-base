"""V7 摄取管线的 Agent Lightning 训练集成。

Ponytail: plan 2026-09-18-v7-agl-training.md — Stage5-only training via
AGL Gateway proxy. The training topology is 1 rollout = 1 topic; raw-level
orchestration (Stage1/3/4) is offline and precomputed before the rollout.
"""
from __future__ import annotations

from .agent import Agent
from .hooks import V7AglHook

__all__ = ["Agent", "V7AglHook", "precompute_topics"]