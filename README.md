# Incident Response Agent

**Investigate production incidents with an auditable multi-agent workflow, evidence-bound recommendations, and a human approval gate.**

[![CI](https://github.com/Jenish-Shobhit/incident-response-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Jenish-Shobhit/incident-response-agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

![Incident Response Agent dashboard](assets/screenshots/dashboard.jpg)

This is a working FastAPI and LangGraph application, not a chat mockup. It ingests an incident bundle, quarantines prompt-injection-shaped evidence, delegates bounded investigations, checks every recommendation against source evidence, and pauses before any action can be approved.

Mock mode is the default: it is deterministic, costs no tokens, and runs without cloud credentials.

**Live demo:** <https://dpdduyx82d5bu.cloudfront.net> — a recorded run replayed in the real UI. Press **Investigate**, then approve or reject the plan. It is served as static files from a private S3 bucket through CloudFront, so no model or API key is exposed.

## The bundled incident

`INC-3172`, P1 on `inventory-service`: write latency p99 at 12.4s and a 27% 5xx rate, minutes after a deploy. The deploy's schema migration is building an index on `stock_levels` without `CONCURRENTLY`, and its lock queues every write.

The evidence is built to make shortcuts fail:

- **A tempting wrong fix.** A deploy just happened, so rolling it back looks obvious, but rolling back application code does not release a running migration's lock.
- **A metric that rules things out.** Database CPU is *below* baseline, so adding compute or replicas cannot help.
- **Units that invert naive arithmetic.** `12.4s` against `85ms` is 146x worse; parsing the numbers without units reports an improvement.
- **A planted prompt injection.** One log line claims to be from the on-call lead and asks the system to mark the incident resolved and drop the index in production.

The correct outcome is to **escalate**: mitigation steps are available, but the runbook says rebuilding the index is a human decision. The incident is synthetic and written for this project.

## What it demonstrates

- **Real orchestration:** a planner can dispatch multiple investigators, collect their results, and decide whether another round is needed.
- **Evidence discipline:** claims carry citations and the verifier can inspect evidence but cannot hunt for support.
- **Least privilege:** each agent receives only its declared read-only tools; the planner receives none.
- **Prompt-injection containment:** suspicious log content is preserved for audit, redacted from every model-visible path, and covered by adversarial tests.
- **Human control:** remediation stops at an approval interrupt and resumes in a second streamed request.
- **Provider flexibility:** deterministic fixtures, Amazon Bedrock, and Anthropic share one internal calling convention.

## Run it

```bash
git clone https://github.com/Jenish-Shobhit/incident-response-agent.git
cd incident-response-agent
./run.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and select **Investigate incident**. To try your own incident, write a file in the shape of [`examples/incident-input.json`](examples/incident-input.json) and upload it.

For a frontend-only recorded replay, open [http://127.0.0.1:8000/?demo](http://127.0.0.1:8000/?demo).

## Workflow

```mermaid
flowchart LR
    A[Ingest] --> B[Guard]
    B --> C[Triage planner]
    C -->|questions| D[Parallel investigators]
    D --> E[Collect evidence]
    E --> C
    C -->|closed| F[Match runbooks]
    F --> G[Resolve]
    G --> H[Verify]
    H -->|needs evidence| C
    H -->|needs redraft| G
    H -->|passes or capped| I[Render brief]
    I --> J{Human approval}
    J --> K[Record receipts]
```

The graph has eleven explicit nodes, capped retry loops, reducer-backed fan-in, and checkpointed interrupts. See [Architecture](docs/ARCHITECTURE.md) for the state model and trust boundaries.

## Development

```bash
make install    # create .venv and install runtime + test dependencies
make check      # compile application modules and run the test suite
make run        # start the local server in mock mode
```

The test suite defends behavioral claims rather than implementation details: unit conversion, injection quarantine, tool grants, evidence preservation, graph routing, approval validation, and the HTTP surface.

## Live model mode

Mock mode is the safe public-demo configuration. To use Amazon Bedrock locally with your existing AWS profile:

```bash
export MOCK=0
export LLM_PROVIDER=bedrock
export AWS_REGION=us-east-1
./run.sh
```

You can also set `BEDROCK_MODEL` explicitly. Do not commit credentials. For a live cloud deployment, use an AWS compute service with an attached IAM role instead of long-lived access keys.

## Deploy

The public demo is a static replay on AWS:

```text
Browser --HTTPS--> CloudFront --Origin Access Control--> private S3 bucket (web/)
GitHub push to main --> CI tests --> OIDC role (no stored keys) --> s3 sync + cache invalidation
```

- The bucket blocks all public access; only this CloudFront distribution can read it.
- The deploy role is defined in [`deploy/aws/github-deploy-role.yaml`](deploy/aws/github-deploy-role.yaml). Only pushes to `main` of this repository can assume it, and it can only write this bucket and invalidate this distribution.
- With no backend reachable, `web/index.html` switches itself to replay mode, hides upload, and never calls `/run`.

To run the full application with a live backend instead, use the non-root [`Dockerfile`](Dockerfile) or the Render Blueprint in mock mode. Setup steps, validation, rollback, and the live Bedrock path are in [Deployment](docs/DEPLOYMENT.md).

## Repository map

| Path | Responsibility |
|---|---|
| `app/` | Graph, agents, prompts, evidence guard, model adapters, and HTTP API |
| `web/` | Responsive single-page operator console and recorded demo frames |
| `tests/` | Graph, guardrail, metric, tool-grant, and API contract tests |
| `examples/` | The bundled incident in its input format; the template for your own |
| `data/` | The normalized incident the app reads, and the runbook risk overlay |
| `fixtures/` | Deterministic model responses used by mock mode |
| `tools/` | Normalization, live-run recording, and demo-frame recording utilities |
| `deploy/` | AWS CloudFormation for the GitHub OIDC deploy role |
| `docs/` | Architecture, deployment guide, and a LangGraph data-flow walkthrough |

## Honest limitations

- Approval checkpoints use an in-memory saver. Run one application process; restarts invalidate pending approvals.
- The public deployment is intentionally a static replay. Live model mode needs authentication, rate limiting, durable checkpoints, and workload identity before internet exposure.
- Recommendations are read-only plans and receipts. The project deliberately exposes no infrastructure mutation tool.
- The bundled incident is synthetic and does not establish performance on arbitrary production telemetry.

These are the next engineering boundaries, not hidden footnotes. See [Deployment](docs/DEPLOYMENT.md#production-hardening-path) for the staged path forward.

## License

[MIT](LICENSE) © 2026 Jenish Shobhit
