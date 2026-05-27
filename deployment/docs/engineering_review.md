# Top 1% Robotics Engineering Review

## Weak Architecture Found

- The first deployment draft allowed hidden dependency failures through `rosdep ... || true`.
- Robot Compose expected `/etc/bonbon/bonbon.env`, but deployment only copied `runtime.env`.
- Remote health checks referenced scripts that were not copied to the release directory.
- Module-specific services existed in systemd, but some originally pointed at shared `core` containers.

Improvements made:

- Removed masked rosdep failures in CI and the ROS2 Dockerfile.
- Deployment now copies health/post-deploy scripts and creates `/etc/bonbon/bonbon.env`.
- Robot Compose exposes explicit `safety`, `speech`, `tts`, and `perception` services.
- systemd units now map to the expected service names.

## Missing Edge Cases Found

- No post-deployment verifier for ROS2 graph, topics, dashboard, logs, metrics, and rollback state.
- No checksum verification helper.
- Dry-run safety checks initially depended on host disk state.

Improvements made:

- Added `post_deploy_check.py`.
- Added `verify_release.py`.
- Made dry-run deterministic while keeping real deployments strict.

## Weak Safety Handling Found

- Deployment depended on operator env flags but lacked structured preflight output.
- Rollback did not verify health after restart.

Improvements made:

- `pre_deploy_check.py` explicitly checks battery, estop, safety supervisor, paused task, no active navigation, disk space, rollback version, config state, health, and authorization.
- Rollback now runs `health_check.sh` and `post_deploy_check.py`.

## Missing Tests Found

- No tests for post-deploy checks, checksum validation, audit logging, or rosdep failure masking.

Improvements made:

- Added tests for all of the above in `devops/tests/test_deployment_system.py`.

## Performance Risks Found

- Full ROS2 Docker builds copy the whole workspace and can be slow.
- CI runs broad package tests in one ROS job.

Mitigations:

- The architecture keeps deterministic simulation tests lightweight.
- Future work should add Docker layer caching and package-level CI matrix splitting.

## Deployment Risks Found

- A robot could end up with a missing `bonbon.env`.
- Health check scripts might be absent on the target.
- Release artifact integrity was not checked locally before deploy.

Improvements made:

- Deployment now materializes `bonbon.env`, ships health scripts, and supports checksum verification.

## Security and Privacy Risks Found

- Initial workflow had a secret scan but no deployment audit trail.
- Signed release existed, but checksum verification was not scriptable.

Improvements made:

- Added deployment and rollback audit logging.
- Added `verify_release.py` and release workflow checksum verification.

## Maintainability Issues Found

- Documentation was split but lacked a complete operator reference.
- Some scripts had behavior only visible by reading shell code.

Improvements made:

- Added architecture, configuration, ROS2 interface, examples, tests, and future-improvement docs.
