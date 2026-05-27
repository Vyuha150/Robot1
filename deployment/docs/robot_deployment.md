# Robot Deployment

Robot deployment requires:

- robot host supplied via `BONBON_ROBOT_HOST`
- operator authorization via `BONBON_OPERATOR_AUTH_CONFIRMED=1`
- rollback version available
- config validation pass
- service health pass
- signed/checksummed release artifacts for staging and production

Dry run:

```bash
BONBON_DRY_RUN=1 BONBON_ROBOT_HOST=robot.local \
  devops/scripts/deploy_to_robot.sh --env lab_robot --version lab-test --dry-run
```

Real deployment:

```bash
BONBON_OPERATOR_AUTH_CONFIRMED=1 \
  devops/scripts/deploy_to_robot.sh --env production_robot --version production-20260527
```

Do not hardcode robot IPs in scripts or config. Use environment variables or deployment host inventory.

Runtime secrets already present in `/etc/bonbon/bonbon.env` are preserved during deployment. New robot provisioning should create that file with runtime-only secrets before the first production deployment.
