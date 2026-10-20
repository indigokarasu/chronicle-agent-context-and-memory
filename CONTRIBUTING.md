# Contributing to Chronicle

Contributions welcome: reproducible bug reports, real-world memory use cases, and
small, tested improvements.

## Before opening an issue

Run `/chronicle` in Hermes and paste its output with secrets and private memory
content removed. For retrieval problems, include the question you asked, the
result you expected, and whether a local embedding server was running.

Don't attach a Chronicle database to a public issue. It may hold conversation
history and personal facts.

## Development setup

```bash
git clone https://github.com/indigokarasu/chronicle-agent-context-and-memory.git
cd chronicle-agent-context-and-memory
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
ruff check .
```

Chronicle supports Python 3.9 and newer. Tests use temporary databases and don't
need a running embedding service.

## Pull requests

- Keep each pull request focused on one behavior or documentation change.
- Preserve durable capture, lossless context eviction, abstention gating, and
  graceful degradation. `AGENTS.md` documents these invariants in detail.
- Add or update tests when behavior changes.
- Run the full test and lint commands above before requesting review.
- Explain the user-visible result and any remaining limitations in the pull
  request description.

If you're unsure where a change belongs, open an issue with the use case first.
