# Deployment Guide

The public demo runs as a static replay on AWS S3 and CloudFront (section 4). The same code also runs as a container locally or on Render in mock mode, and can move to live Bedrock on AWS with workload identity.

## 1. Verify locally

```bash
make install
make check
./run.sh
```

Confirm these endpoints:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/incident
```

The health response should report `ok: true` and `mock: "1"`.

## 2. Verify the production image

```bash
docker build -t incident-response-agent .
docker run --rm -p 8000:8000 incident-response-agent
```

Open `http://127.0.0.1:8000`, complete an investigation, approve or reject the proposed actions, and verify a receipt is shown.

The image runs as an unprivileged user, includes only runtime files, binds to `0.0.0.0`, and reads the platform-provided `PORT` variable.

## 3. Deploy mock mode to Render

The root `render.yaml` is a Render Blueprint. It declares one free Docker web service in Singapore, waits for GitHub CI before automatic deployment, checks `/health`, and fixes `MOCK=1`.

1. Sign in to Render and choose **New > Blueprint**.
2. Connect `Jenish-Shobhit/incident-response-agent`.
3. Keep the Blueprint path as `render.yaml` and apply it.
4. Wait for the image build and health check to pass.
5. Open the generated `onrender.com` URL and run the bundled incident.

Every push to `main` starts CI. Render deploys only after those checks pass. If a new release fails its health check, Render keeps the previous healthy release serving traffic.

The free service can sleep when idle and its filesystem is ephemeral. Neither affects deterministic mock mode.

## Rollback exercise

To learn the operational loop rather than only the happy path:

1. Record the deployed commit SHA.
2. Make and push a visible README-only change; watch CI and the automatic deployment.
3. In Render's deploy history, select the previous successful deploy and redeploy it.
4. Confirm `/health` and the UI, then redeploy the latest passing commit.

## 4. Static demo on AWS (S3 + CloudFront)

This is the public demo. Only `web/index.html` and `web/demo/frames.json` are published; there is no server and no model credential in the cloud.

### One-time setup

1. **Account safety:** MFA on the root user, an IAM admin user for daily work, and a $1 budget alert.
2. **S3 bucket:** general purpose, *Block all public access* on, ACLs disabled, SSE-S3 encryption, no versioning. Upload `web/index.html` to the root and `web/demo/frames.json` under `demo/`.
3. **CloudFront distribution:** origin type Amazon S3, choose the bucket, keep *Grant CloudFront access to origin* (creates the Origin Access Control and bucket policy). Leave security protections off on pay-as-you-go, because AWS WAF is billed monthly. Set **Default root object** to `index.html`.
4. **Deploy role:** in CloudFormation, create a stack from [`deploy/aws/github-deploy-role.yaml`](../deploy/aws/github-deploy-role.yaml) in any region. Copy the `RoleArn` output.
5. **GitHub repository variables** (Settings > Secrets and variables > Actions > Variables):

   | Variable | Example |
   |---|---|
   | `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::<account>:role/incident-agent-demo-deploy` |
   | `AWS_REGION` | `ap-south-2` |
   | `DEMO_S3_BUCKET` | `incident-agent-demo-jenish` |
   | `DEMO_CLOUDFRONT_ID` | `E23VNZY3PVRM7N` |

   None of these are secrets. Without the role, AWS rejects the OIDC token from any other repository or branch.

### Every push to `main`

CI runs the tests and container build, then the `deploy-demo` job assumes the role over OIDC, runs `aws s3 sync web/ --delete`, and invalidates `/*` on CloudFront. The job is skipped when `AWS_DEPLOY_ROLE_ARN` is unset.

### Verify

```bash
curl -I https://<distribution>.cloudfront.net/                       # 200 text/html
curl -I https://<distribution>.cloudfront.net/demo/frames.json       # 200 application/json
curl -I https://<bucket>.s3.<region>.amazonaws.com/index.html        # 403: bucket is private
```

### Tear down

Disable the distribution, wait for it to deploy, then delete it. Empty and delete the bucket. Delete the CloudFormation stack. Delete the GitHub variables.

## Live Bedrock deployment

Do not put long-lived AWS access keys in Render for a public demo. Deploy live mode to AWS App Runner, ECS/Fargate, or another AWS runtime that can attach a least-privilege IAM role.

The runtime configuration is:

```text
MOCK=0
LLM_PROVIDER=bedrock
AWS_REGION=<region>
BEDROCK_MODEL=<permitted model or inference profile>
```

Grant only `bedrock:InvokeModel` for the selected model or inference-profile ARN. Keep the service private until authentication and rate limits are in place.

## Production hardening path

1. Replace `InMemorySaver` with a durable LangGraph checkpointer backed by a managed datastore.
2. Add operator authentication and authorization to `/run`, `/load`, and `/approve`.
3. Add request-size limits, rate limits, structured logs, request IDs, and error reporting.
4. Store incident evidence in encrypted durable storage with a retention policy.
5. Add OpenTelemetry traces and metrics for model latency, tool calls, retries, approvals, and token use.
6. Run multiple replicas only after checkpoint persistence and resume routing are shared across instances.

Render Blueprint reference: <https://render.com/docs/blueprint-spec>

Render FastAPI guide: <https://render.com/docs/deploy-fastapi>

Render health checks: <https://render.com/docs/health-checks>
