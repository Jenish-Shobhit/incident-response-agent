# Configuration

Every setting is read once, in `src/incident_agent/config.py`. Values come from the environment; a `.env` file at the project root is loaded first if it exists. Real environment variables always win over `.env`, so Docker, CI and hosting platforms can override anything without editing files.

```bash
cp .env.example .env    # make setup does this for you
```

## Modes

| Mode | Settings | Needs | Cost |
|---|---|---|---|
| Mock (default) | `MOCK=1` | nothing | free, deterministic |
| Claude API | `MOCK=0`, `LLM_PROVIDER=anthropic` | `ANTHROPIC_API_KEY` | per token |
| Amazon Bedrock | `MOCK=0`, `LLM_PROVIDER=bedrock` | AWS credentials with `bedrock:InvokeModel` | per token |

If a live mode is missing something, `GET /health` returns `"ok": false` with a `problems` list naming the variable to set, and `POST /run` refuses with the same message instead of failing inside the SDK.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `MOCK` | `1` | `1` replays the scenario's recorded replies; `0` calls a model |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `bedrock` |
| `ANTHROPIC_API_KEY` | | Your Claude API key. Read by the Anthropic SDK |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Any Claude model id |
| `ANTHROPIC_REFUSAL_FALLBACK` | `1` | On a policy decline, let the API retry the request on another model in the same call |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `AWS_PROFILE` | | Standard AWS SDK profile selection. Prefer `aws login` or SSO to access keys |
| `BEDROCK_MODEL` | | Empty probes a preference list once and caches the first model that answers in `.cache/` |
| `LLM_MAX_TOKENS` | `8000` | Output ceiling per model call |
| `PROMPT_CACHE` | `1` | Mark system prompts and tool schemas cacheable |
| `MAX_ROUNDS` | `3` | Planner investigation rounds before it must conclude |
| `MAX_QUESTIONS` | `2` | Parallel investigators per round |
| `RECURSION_LIMIT` | `40` | LangGraph superstep limit |
| `SCENARIO_DIR` | `scenarios/inventory-migration-lock` | Which scenario to serve. Relative paths resolve from the project root |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Used by `make run` and the container |
| `APP_ROOT` | the repository | Where `web/` and `scenarios/` live; set by the Dockerfile |

## Keys and safety

- `.env` is git-ignored. Never commit it, and never paste AWS access keys into it; use `aws login`, an SSO profile, or an attached role.
- Tests always force `MOCK=1`, whatever `.env` says, so `make test` never spends tokens.
- Live mode is for local use. Before exposing it on a network, add authentication and rate limits (see [deployment](deployment.md#production-hardening-path)).
