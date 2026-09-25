# Security Policy

## Supported version

Security fixes target the latest commit on `main`.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities that expose credentials, incident evidence, or an approval bypass. Report them privately through GitHub's security advisory flow for this repository.

Include the affected endpoint or component, reproduction conditions, impact, and any suggested mitigation. Do not include real production logs or credentials.

## Deployment boundary

The public deployment is a static replay with no backend. The application itself defaults to deterministic mock mode. Live model mode is not intended for unauthenticated internet exposure. Add identity, authorization, rate limits, durable state, and a least-privilege cloud role before using it with real incidents.
