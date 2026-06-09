# Payment Exception Resolution Agent

A production-grade multi-agent system for diagnosing, routing, and resolving failed payment transactions end-to-end.

## Architecture

Multi-agent system with 7 specialized agents:
- **Ingress Gateway** — Validates, normalizes, deduplicates exception events
- **Orchestrator** — Sequences workflow, manages timeouts, coordinates agents
- **Investigation Agents** (7 specialists) — Gathers evidence from specific domains
- **Decision Engine** — Evaluates evidence, applies rules, determines action
- **Egress Executor** — Executes decided actions idempotently
- **Async Post-Decision** — Handles notifications, retries, audit
- **Feedback & Replay** — Re-evaluates when new evidence arrives

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the demo flow
python -m src.main

# Run tests
pytest
```

## Project Structure

```
src/
  models/       — Pydantic data models and enums
  agents/       — Agent implementations
  rules/        — Decision rules engine
  guardrails/   — LLM safety guardrails
  infrastructure/ — State store, message bus, config
  api/          — FastAPI endpoints
config/         — Rail-specific configs and thresholds
docs/           — Architecture and planning docs
tests/          — Unit, integration, and E2E tests
```

## Documentation

- [Architecture](docs/architecture.md)
- [Development Plan](docs/development-plan.md)
