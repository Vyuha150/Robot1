# Examples

## Run DevOps Tests

```bash
python -m pytest devops/tests -q
```

## Validate Config

```bash
python devops/scripts/validate_config.py --env simulation
```

## Generate Release Version

```bash
python devops/scripts/release_version.py --channel staging
```

## Verify Release Checksum

```bash
python devops/scripts/verify_release.py \
  --artifact bonbon-release.tar.gz \
  --sha256 bonbon-release.tar.gz.sha256
```

## Pre-Deployment Dry Run

```bash
python devops/scripts/pre_deploy_check.py --dry-run
```

## Post-Deployment Dry Run

```bash
python devops/scripts/post_deploy_check.py --dry-run
```

## Robot Deployment Dry Run

```bash
BONBON_DRY_RUN=1 \
BONBON_ROBOT_HOST=robot.local \
BONBON_ROBOT_USER=bonbon \
devops/scripts/deploy_to_robot.sh --env lab_robot --version lab-test --dry-run
```

## Rollback Dry Run

```bash
BONBON_DRY_RUN=1 \
BONBON_ROBOT_HOST=robot.local \
devops/scripts/rollback_robot.sh previous-version
```
