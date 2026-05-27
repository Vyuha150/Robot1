# Security Checklist

- no secrets in repo
- `.env.example` only
- `.env` ignored by git
- release artifacts are checksummed and signed
- config volumes are read-only
- model volumes are read-only
- database volumes are not exposed publicly
- dashboard API requires strong `BONBON_JWT_SECRET`
- dashboard admin password is injected at runtime only
- deployment actions are logged
- runtime secret values are preserved on the robot and not copied from repo config
- remote update path uses SSH and least privilege
- containers use `no-new-privileges`
- robot IPs are not hardcoded
- production deployment requires operator authorization
