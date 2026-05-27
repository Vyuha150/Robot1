# Security Concerns

## Secrets

Do not commit `.env`, `BONBON_JWT_SECRET`, `BONBON_ADMIN_PASSWORD`, SSH keys, model credentials, or database credentials.

Use `.env.example` for shape only. Robot hosts should provision runtime secrets directly into `/etc/bonbon/bonbon.env` or a future secret manager.

## Release Integrity

- Generate release metadata with `release_version.py`.
- Verify checksums with `verify_release.py`.
- Sign release archives in CI.
- Production deployments should use signed/checksummed artifacts only.

## Volumes

- Mount `/etc/bonbon` read-only inside containers.
- Mount `/opt/bonbon/models` read-only.
- Mount `/opt/bonbon/maps` read-only.
- Keep `/var/lib/bonbon` private to the robot host.

## Dashboard

- Require a strong `BONBON_JWT_SECRET`.
- Rotate `BONBON_ADMIN_PASSWORD` after provisioning.
- Restrict dashboard network exposure in production.
- Monitor authentication failures.

## Remote Update Path

Current deployment uses SSH and Docker Compose. Keep robot SSH access least-privileged and audited.

Future production fleet deployment should move toward an OTA agent with artifact verification on the robot before activation.
