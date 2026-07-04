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

## Model Separation

- Planning/Architecture: Claude Opus (via Claude Code)
- Implementation: Claude Sonnet (via Claude Code)
- Runtime generative (pipeline): Qwen3 14B via Ollama — OLLAMA_MODEL_NAME
- Embeddings: BGE-M3 via Ollama (separate from generative models)

This separation means all context should remain explicitly documented in specs, plans, and tasks — the specs are written to be self-contained even though context may carry across phases.