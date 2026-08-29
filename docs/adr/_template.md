# ADR: <title>

- **状态**: proposed | accepted | superseded by <other ADR>
- **日期**: YYYY-MM-DD
- **触发**: <what decision needed to be made>
- **关联**: <plan / spec / related ADR>

## Context（背景）

What is the issue? What are the forces at play (technical, business, social)?
What constraints exist? Include relevant data, links, current state.

## Decision（决策）

What did you decide? State the choice clearly. If the decision is "do X by
default with Y timeout", say so explicitly. Include any conditional branches.

## Rationale（理由）

Why this decision over alternatives? Bullet the key reasons:

- Reason A: maps to constraint X
- Reason B: minimizes cost Y
- Reason C: preserves spec §Z compliance

## Consequences（后果）

What becomes easier? What becomes harder? What risks remain?

### Trigger to Revisit（重审触发条件）

When should this decision be reconsidered? List concrete conditions:

- Condition 1 (e.g. "cost drops 50%")
- Condition 2 (e.g. "business need emerges for X")

## Alternatives Considered（备选方案）

What else was considered? Why rejected?

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| A | ... | ... | ❌ rejected |
| B | ... | ... | ✅ chosen |

## References（参考）

- spec §X.Y
- plan file
- related ADR
- external docs

## Implementation Notes（实施笔记）

Anything operational: tests, scripts, integration steps, rollback procedure.