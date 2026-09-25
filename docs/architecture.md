# Architecture

The application separates orchestration, evidence access, model transport, and operator interaction so each boundary can be tested independently.

## Runtime components

All paths are under `src/incident_agent/` unless noted.

| Component | Files | Responsibility |
|---|---|---|
| HTTP layer | `api.py` | Serves the console and exposes load, run, approval, incident, and health endpoints |
| Configuration | `config.py` | Reads `.env` and the environment once; reports what a live run is missing |
| State graph | `graph/builder.py`, `graph/state.py`, `graph/nodes.py` | Eleven nodes, reducers, interrupts, routing, and recursion limits |
| Agent runtime | `agents/loop.py`, `agents/prompts.py` | The provider-neutral tool loop every agent runs, and the five system prompts |
| Evidence boundary | `evidence/records.py`, `evidence/guard.py`, `evidence/metrics.py` | Normalizes an incident, quarantines injected text, and compares metrics with units |
| Tool boundary | `tools/` | Declares five read-only tools, grants them per role, and runs them on redacted evidence only |
| Model boundary | `llm/` | One `converse()` over mock fixtures, the Claude API, and Bedrock Converse |
| Scenario | `scenarios/<name>/` | The incident, its runbook risk overlay, and the mock replies for each agent |
| Operator console | `web/index.html` | Streams the investigation, shows citations, and submits approvals; replays `web/demo/` with no backend |

## Trust boundaries

1. Raw incident input is untrusted. Normalization carries through only the named fields and turns them into explicit, keyed evidence records.
2. The evidence guard scans instruction-shaped content before any model call. Quarantined records remain visible to the operator but are redacted from the model view.
3. Agents do not receive a generic tool registry. Role grants are enforced in code on every call.
4. The verifier can resolve citations but cannot search for new evidence, preventing it from manufacturing support for a preferred conclusion.
5. Execution is an approval receipt, not an infrastructure mutation. No write-capable production tool exists in the process.

## State and control flow

The planner operates as a loop, not a single fan-out. It sees the collected ledger after each investigation round and either asks new bounded questions or closes the investigation. Parallel investigator output uses reducers, and the deferred collector waits for every branch.

The verifier may route back to triage for missing evidence or to resolution for a weak plan. A retry counter and raised graph recursion limit make both the intended loop and its stop condition explicit.

LangGraph's interrupt ends the first response stream at the approval gate. The browser later submits the thread ID and approved action IDs to `/approve`, which resumes the checkpoint and produces a second stream.

## Persistence model

The current graph uses `InMemorySaver`. That is appropriate for a single-process demonstration and keeps setup credential-free, but pending approvals do not survive restarts and cannot move between replicas. Production hardening should replace it with a durable checkpointer before scaling beyond one process.

## Adding a scenario

A scenario is a folder under `scenarios/` with three things:

- `incident.json` -- the alert, `logs`, `metrics` and `runbooks` in the input format of the bundled example.
- `runbook_overlay.json` -- per-runbook risk, the individual actions (each a verbatim substring of the runbook body), `not_when` exclusions and human follow-ups. A test rejects any action the runbook does not contain.
- `fixtures/<agent>.json` -- the recorded replies mock mode plays for `planner`, `log`, `metric`, `resolver` and `verifier`. Only needed for mock mode; live runs ignore them.

Point `SCENARIO_DIR` at the folder to run it, and `make demo` to re-record the static replay.
