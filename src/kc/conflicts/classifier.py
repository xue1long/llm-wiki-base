"""Conflict 6-type Classifier (A-3 / G6, spec §8.2 + §5.11 Conflict).

Classifies a pair of statements into one of the 6 conflict types defined in
spec §8.2:

| Type          | Rule (spec §8.2)                                                 |
|---------------|------------------------------------------------------------------|
| actual        | Context 与时间均重叠 + 命题不能同时成立                            |
| conditional   | Context 部分重叠 + 条件可解释差异                                  |
| temporal      | 时间不重叠 → supersede                                             |
| perspective   | 事实范围相同但来源立场不同                                          |
| none          | Context 不重叠（建立 related_to，不冲突）                          |
| unresolved    | 决定性维度 unknown + 潜在互斥                                      |

Used by the resolution layer to choose among the actions defined in
spec §11.4 (conflict / link / supersede / quarantine).

The classification order below matters — earlier rules short-circuit later
ones:

  1. Context disjoint     → ``none``
  2. Time disjoint        → ``temporal`` (priority supersede)
  3. Decisive unknown     → ``unresolved``
  4. Partial overlap      → ``conditional``
  5. Contradiction        → ``actual``
  6. default              → ``perspective``
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# spec §8.2 — closed enum of 6 conflict types. No drift allowed.
ConflictType = Literal[
    "actual", "conditional", "temporal", "perspective", "none", "unresolved"
]


@dataclass(frozen=True)
class Conflict:
    """One classified conflict (spec §5.11 Conflict dataclass, A-3 slice).

    Carries the two statements, the determined type, the inputs that produced
    the classification (context + validity windows), and a confidence score.
    Downstream resolution (spec §11.4) reads these to pick the right action.
    """

    statement_a: str
    statement_b: str
    conflict_type: ConflictType
    context_a: dict | None = None
    context_b: dict | None = None
    valid_from_a: int | None = None
    valid_to_a: int | None = None
    valid_from_b: int | None = None
    valid_to_b: int | None = None
    resolution: str | None = None
    confidence: float = 0.0


# Heuristic lexicon used by ``_statements_contradict`` to spot a clear
# contradiction. Pairs are bidirectional: each pair checks both directions.
# Kept minimal — the full semantic judge (LLM-based) is wired in B-3 when this
# classifier is consumed from src.kc.agents.conflict_resolver.
_CONTRADICTION_PAIRS: tuple[tuple[str, str], ...] = (
    ("快", "慢"), ("慢", "快"),
    ("公平", "不公平"), ("不公平", "公平"),
    ("是", "不是"), ("不是", "是"),
    ("会", "不会"), ("不会", "会"),
    ("增加", "减少"), ("减少", "增加"),
    ("有效", "无效"), ("无效", "有效"),
    ("相同", "不同"), ("不同", "相同"),
    ("prevents", "does not prevent"), ("does not prevent", "prevents"),
    ("reduces", "hurts"), ("hurts", "reduces"),
)


class ConflictClassifier:
    """Classify a potential conflict into 1 of 6 spec §8.2 types."""

    def classify(
        self,
        statement_a: str,
        statement_b: str,
        context_a: dict | None = None,
        context_b: dict | None = None,
        valid_from_a: int | None = None,
        valid_to_a: int | None = None,
        valid_from_b: int | None = None,
        valid_to_b: int | None = None,
    ) -> Conflict:
        """Apply the 6-rule decision table from spec §8.2 and return a Conflict.

        Order matters: earlier rules short-circuit later ones. See module
        docstring for the rule table.
        """
        common_kwargs = dict(
            statement_a=statement_a,
            statement_b=statement_b,
            context_a=context_a,
            context_b=context_b,
            valid_from_a=valid_from_a,
            valid_to_a=valid_to_a,
            valid_from_b=valid_from_b,
            valid_to_b=valid_to_b,
        )

        # Rule 1 (spec §8.2 X-1): Context disjoint → none (build related_to, no conflict).
        if self._context_disjoint(context_a, context_b):
            return Conflict(conflict_type="none", confidence=0.9, **common_kwargs)

        # Rule 2 (spec §8.2 X-6): Time disjoint → temporal (priority supersede).
        if self._temporal_disjoint(valid_from_a, valid_to_a, valid_from_b, valid_to_b):
            return Conflict(conflict_type="temporal", confidence=0.95, **common_kwargs)

        # Rule 3 (spec §8.2 X-9 + §11.4 #7): Unknown decisive dimension → unresolved.
        if self._has_unknown_dimension(context_a, context_b):
            return Conflict(conflict_type="unresolved", confidence=0.7, **common_kwargs)

        # Rule 4 (spec §8.2 X-3): Partial Context overlap → conditional.
        # Exception: when the *only* differing shared key is the ``perspective``
        # dimension, the partial overlap reflects a stance difference, not a
        # condition difference — defer to the perspective rule (CF-007 / CF-008).
        if self._context_partial_overlap(context_a, context_b) and not self._differs_only_in_perspective(
            context_a, context_b
        ):
            return Conflict(conflict_type="conditional", confidence=0.8, **common_kwargs)

        # Rule 5 (spec §8.2 X-2): Same scope + contradictory → actual.
        if self._statements_contradict(statement_a, statement_b):
            return Conflict(conflict_type="actual", confidence=0.85, **common_kwargs)

        # Rule 6 (spec §8.2 X-4): Same scope, different stance → perspective.
        return Conflict(conflict_type="perspective", confidence=0.7, **common_kwargs)

    # ------------------------------------------------------------------
    # Rule predicates — one per decision-table row.
    # ------------------------------------------------------------------

    def _context_disjoint(self, c_a: dict | None, c_b: dict | None) -> bool:
        """spec §8.3 disjoint: no shared decisive dimension with the same value.

        Conservative: any shared key with the same value defeats disjointness.
        If either side is missing, we cannot claim disjointness either.
        """
        if c_a is None or c_b is None:
            return False
        shared_keys = set(c_a.keys()) & set(c_b.keys())
        if not shared_keys:
            # No shared dimensions → conservative: not disjoint (let later rules decide).
            return False
        # Disjoint iff every shared key has different values.
        return all(c_a[k] != c_b[k] for k in shared_keys)

    def _temporal_disjoint(self, vf_a, vt_a, vf_b, vt_b) -> bool:
        """spec §8.2 X-6: validity windows do not overlap.

        A ``None`` bound is open-ended (±∞). Disjointness holds when the
        known bounds place one window entirely before the other (e.g.
        ``vt_a ≤ vf_b`` with both ``vf_a`` and ``vf_b`` known). If only one
        bound is known on each side, we still accept disjointness when those
        two bounds do not overlap (mirrors CF-005 where ``valid_to_b`` is
        null because B is the current open-ended window).
        """
        # Treat None as ±∞: collapse to whatever bound we do know.
        # If neither side has any bound, we cannot establish disjointness.
        if vf_a is None and vt_a is None and vf_b is None and vt_b is None:
            return False
        a_lo = -float("inf") if vf_a is None else vf_a
        a_hi = float("inf") if vt_a is None else vt_a
        b_lo = -float("inf") if vf_b is None else vf_b
        b_hi = float("inf") if vt_b is None else vt_b
        # Disjoint when one window ends before the other starts.
        return a_hi <= b_lo or b_hi <= a_lo

    def _has_unknown_dimension(self, c_a: dict | None, c_b: dict | None) -> bool:
        """spec §8.2 X-9: decisive dimension is unknown on a shared key.

        Mirrors CF-009 (domain: unknown on both sides). Triggered when a key
        that exists on both sides has an explicit "unknown" sentinel
        (None / "" / "unknown"). Conservative: only fires when both sides share
        the same key and that key's value is unknown on either side.
        """
        if c_a is None or c_b is None:
            return False
        for key in set(c_a.keys()) & set(c_b.keys()):
            va = c_a[key]
            vb = c_b[key]
            if va in (None, "", "unknown") or vb in (None, "", "unknown"):
                return True
        return False

    def _differs_only_in_perspective(self, c_a: dict | None, c_b: dict | None) -> bool:
        """True iff the two contexts agree on every shared key except ``perspective``.

        Used to keep perspective (CF-007 / CF-008) from being mis-routed to
        conditional via the partial-overlap rule. Requires at least one
        shared key and a shared ``perspective`` key with different values;
        every other shared key must agree.
        """
        if c_a is None or c_b is None:
            return False
        shared = set(c_a.keys()) & set(c_b.keys())
        if not shared or "perspective" not in shared:
            return False
        for key in shared:
            if key == "perspective":
                if c_a[key] == c_b[key]:
                    return False  # no stance difference → not perspective
                continue
            if c_a[key] != c_b[key]:
                return False  # another dimension also differs → not perspective-only
        return True

    def _context_partial_overlap(self, c_a: dict | None, c_b: dict | None) -> bool:
        """spec §8.2 X-3: shared dimensions, some same + some different.

        Distinguishes conditional (partial overlap, conditions explain the
        difference) from actual (full overlap, contradiction) and none
        (no overlap). Requires at least one shared key and a mix of equal +
        unequal values.
        """
        if c_a is None or c_b is None:
            return False
        shared = set(c_a.keys()) & set(c_b.keys())
        if not shared:
            return False
        same = sum(1 for k in shared if c_a[k] == c_b[k])
        return 0 < same < len(shared)

    def _statements_contradict(self, s_a: str, s_b: str) -> bool:
        """Heuristic negation detector for the actual-vs-perspective split.

        A full semantic judge belongs to B-3 (LLM-backed resolution agent).
        The pair lexicon is intentionally minimal: it covers the obvious
        Chinese + English antonym pairs observed in the 10 gold cases.
        Returns False on identical strings (same statement, no conflict).
        """
        if s_a == s_b:
            return False
        for pos, neg in _CONTRADICTION_PAIRS:
            if pos in s_a and neg in s_b:
                return True
        return False
