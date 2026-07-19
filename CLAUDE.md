# ContractSentinel - Claude Code Integration

This project uses Claude Code for implementation development. Planning and specification work is done with Claude Opus, while implementation is handled by Claude Sonnet through Claude Code.

## Project Structure

The project follows a strict specification-driven development approach with a predefined architecture based on LangGraph.

## Development Workflow

All development follows the spec-driven workflow defined in `specs/000-constitution.md`:
1. Create specification (spec.md)
2. Create technical plan (plan.md)
3. Create implementation tasks (tasks.md)
4. Implementation

## Artifact Review Gate (mandatory)

Every spec-driven artifact must pass the **`spec-reviewer` subagent** before the workflow advances to
the next stage. This gate sits between every stage: spec → plan → tasks → implementation.

Rules — apply to `spec.md`, `plan.md`, and `tasks.md` alike:
1. **After creating (or editing) an artifact, immediately invoke the `spec-reviewer` subagent** on
   that artifact (pass its path and stage) via the Agent tool. Do not skip this even if the artifact
   "looks simple."
2. **Do not proceed to the next stage until the reviewer returns `VERDICT: APPROVED`.** Approval of
   one stage authorizes only starting the next artifact — not skipping the next stage's own review.
3. **If the reviewer returns `VERDICT: CHANGES REQUESTED`, apply every required change first, then
   re-invoke the reviewer on the revised artifact.** Repeat until APPROVED. Non-blocking suggestions
   may be applied at discretion but do not block progression.
4. The reviewer is **read-only** — it reports; the main model applies the changes. Never weaken the
   artifact just to obtain approval (mirrors constitution §7 for tests).
5. This gate is additional to, not a replacement for, the constitution §1 rule that no `app/` or
   `frontend/src/` file may be written until that feature's spec.md AND plan.md exist and are
   approved — "approved" now means **spec-reviewer-APPROVED**.

Note: a `PostToolUse` hook (`.claude/hooks/spec_review_gate.py`) automatically reminds the model to
run this gate whenever a `spec.md`/`plan.md`/`tasks.md` is written or edited. The hook only reminds;
the review itself and honoring its verdict are the model's responsibility.

## Model Separation

- Planning/Architecture: Claude Opus (via Claude Code)
- Implementation: Claude Sonnet (via Claude Code)
- Runtime generative (pipeline): Qwen3 14B via Ollama — OLLAMA_MODEL_NAME
- Embeddings: BGE-M3 via Ollama (separate from generative models)

This separation means all context should remain explicitly documented in specs, plans, and tasks — the specs are written to be self-contained even though context may carry across phases.