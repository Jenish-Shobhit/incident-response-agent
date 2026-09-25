# Architecture

The application separates orchestration, evidence access, model transport, and operator interaction so each boundary can be tested independently.

## Runtime components

| Component | Files | Responsibility |
|---|---|---|
| HTTP layer | `app/main.py` | Serves the console and exposes load, run, approval, incident, and health endpoints |
| State graph | `app/graph.py`, `app/state.py` | Connects eleven nodes, reducers, interrupts, routing, and recursion limits |
| Agent runtime | `app/agent.py`, `app/nodes.py` | Runs provider-neutral tool loops and emits observable progress events |
| Evidence boundary | `app/evidence.py`, `app/metrics.py` | Normalizes evidence, quarantines injected text, and compares typed metrics |
| Tool boundary | `app/tools/` | Defines schemas, grants per role, validates calls, and exposes read-only operations |
| Model boundary | `app/llm.py` | Adapts mock fixtures, Bedrock Converse, and Anthropic Messages to one shape |
| Operator console | `web/index.html` | Streams the investigation, displays citations, and submits approvals |

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

For a stage-by-stage walkthrough of how state flows through the graph and which LangGraph concepts each stage uses, open [`docs/learn.html`](learn.html) in a browser.
