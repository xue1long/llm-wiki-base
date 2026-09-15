# V7 v3.0 Spot-Check Report

- **Mode**: dry-run (Stage 1 only)
- **LLM**: MiniMax-M3 via AnthropicLLMClient
- **Source fixture**: same 10 samples from the original 2026-09-13 v2 spot-check
- **Date**: 2026-09-15
- **Verifier**: `scripts/_spot_check.py`

## Accuracy

| # | Source | Expected | Predicted | Result |
|---:|---|---|---|---|
| 1 | `借鉴素材小说写作.md` | multi_section | single_method | MISS |
| 2 | `入门教程一个新手的五个阶段.md` | multi_section | list | MISS |
| 3 | `入门教程三江.md` | incomplete | incomplete | OK |
| 4 | `入门教程人物代入感方面的刻画.md` | single_method | single_method | OK |
| 5 | `入门教程作家是怎么炼成的新手必看.md` | single_method | collection | MISS |
| 6 | `入门教程基础篇语言规范.md` | single_method | multi_section | MISS |
| 7 | `入门教程网络小说写作宝典.md` | single_method | single_method | OK |
| 8 | `入门教程谈谈小说的矛盾冲突大高潮小高潮如何营造及小说节奏.md` | multi_section | multi_section | OK |
| 9 | `必备资料11月28号创酷中文网女频现言讲课记录_8c363e.md` | qa_chat | qa_chat | OK |
| 10 | `必备资料20个签约条件新人必看2.md` | list | list | OK |

**Accuracy: 6/10 = 60%** (v2 was 1/10 = 10%)

## Improvement vs v2

- v2 heuristic-only: **10%** (1/10 correct — only #3 incomplete)
- v3 LLM-only: **60%** (6/10 correct — 4 multi-section / cross-type edge cases still miscategorized)

## Remaining failures (4/10)

The 4 failures all involve LLM mis-categorization of structurally
ambiguous documents:

1. **`借鉴素材小说写作.md`** — LLM labels this single_method because the
   first section is a single-topic tutorial; the multi-author aspect
   (which would push it to collection or multi_section) is in later
   sections.

2. **`入门教程一个新手的五个阶段.md`** — LLM labels this `list` because
   there are 5 numbered stages; we expected `multi_section`.

3. **`入门教程作家是怎么炼成的新手必看.md`** — LLM labels this `collection`
   because it perceives multiple distinct articles; we expected
   `single_method`.

4. **`入门教程基础篇语言规范.md`** — LLM labels this `multi_section`
   because it perceives multiple sub-topics; we expected `single_method`.

These are **LLM prompt-tuning issues, not architecture issues**.
Further improvement requires:
- Better prompting (e.g. explicit examples of each type)
- Larger context window (currently truncated to 4000 chars)
- Multi-pass classification (Stage 1 → Stage 1.5 → final)

## Note on the 80% threshold

The plan target of 80% was not met in this run. Plan Task 8's
`--apply` fail-closed gate remains in force until a follow-up
spot-check reaches the 80% mark.

The 6x improvement (10% → 60%) is meaningful: the v3 pipeline is
**correctly handling 60% of cases the v2 heuristic could not**, and
the 4 remaining failures are LLM-level mis-categorizations, not
structural pipeline bugs.

## Reproduce

```bash
# Set MiniMax-M3 env vars (from .env)
$env:RUFLO_LLM_PROVIDER="minimax"
$env:MINIMAX_API_KEY="..."
$env:MINIMAX_BASE_URL="..."
$env:MINIMAX_CHAT_MODEL="MiniMax-M3"

# Run the spot-check
python scripts/_spot_check.py
```
