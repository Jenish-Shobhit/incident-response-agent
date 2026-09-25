# Contributing

## Setup

```bash
make setup     # .venv, the package in editable mode with dev tools, and a .env
make check     # lint + tests -- the same checks CI runs
make run       # the app at http://127.0.0.1:8000
```

Mock mode must remain the default. Tests and pull requests must not require model credentials or spend tokens.

## Change expectations

- Add or update a focused test when behaviour changes. Tests describe claims ("a refusal is not an empty answer"), not implementation details.
- If you change the scenario, the fixtures or the graph, run `make demo` and commit `web/demo/frames.json`. CI fails when the recording no longer matches the code.
- Keep tools read-only unless the security model and approval flow are deliberately redesigned.
- Settings belong in `src/incident_agent/config.py` and `.env.example`, documented in `docs/configuration.md`.
- Never commit `.env`, API keys, AWS credentials, or raw production evidence.
- Keep commit subjects imperative, lowercase, and specific.

Use GitHub Issues for reproducible bugs and scoped feature proposals.
