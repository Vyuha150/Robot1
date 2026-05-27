# Security Concerns

## Secrets

Never commit:

- `.env`
- `BONBON_JWT_SECRET`
- `BONBON_ADMIN_PASSWORD`
- SSH private keys
- model credentials
- database credentials

Use `.env.example` only for variable shape.

## Operator API

- JWT secret must be strong and runtime-injected.
- Admin password must be runtime-injected.
- RBAC permissions must protect commands, diagnostics, config writes, memory, and RAG.
- Emergency stop should remain accessible only to authorized operators but must execute regardless of safety state once authorized.

## Data Privacy

- Face/person stores are sensitive.
- Speech transcripts may contain private information.
- Memory/RAG entries require retention and deletion policy.
- Backups must be protected like primary databases.

## Robot Safety

- Do not bypass safety supervisor or safety gate.
- Do not lower safety thresholds without risk review.
- Do not deploy if simulation/safety tests fail.

## Release and Deployment

- Use signed/checksummed releases.
- Verify checksums before deployment.
- Preserve robot-local runtime secrets during deployment.
- Keep config/model/map mounts read-only.
- Audit deployment and rollback actions.

## Network

- Avoid hardcoded robot IPs.
- Restrict dashboard exposure in production.
- Use least-privilege SSH deployment accounts.
- Rotate credentials after incident response.
