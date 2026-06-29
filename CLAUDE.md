# ContractSentinel - Claude Code Integration

This project uses Claude Code for implementation development. The planning and specification work is done with a different model (Qwen3 480B via Ollama), while implementation is handled by a locally hosted Qwen3 30B model through Claude Code.

## Project Structure

The project follows a strict specification-driven development approach with a predefined architecture based on LangGraph.

## Development Workflow

All development follows the spec-driven workflow defined in `specs/000-constitution.md`:
1. Create specification (spec.md)
2. Create technical plan (plan.md)
3. Create implementation tasks (tasks.md)
4. Implementation

## Model Separation

- Planning/Architecture: Qwen3 480B via Ollama (cloud)
- Implementation: Qwen3 30B via Claude Code (local)
- Embeddings: BGE-M3 or Qwen3-Embedding via Ollama (separate from generative models)

This separation means all context must be explicitly documented in specs, plans, and tasks - nothing carries over conversationally between planning and implementation phases.