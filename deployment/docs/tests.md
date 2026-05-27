# Test Matrix

The module includes unit, integration, failure injection, stress, simulation, regression, and latency benchmark style tests.

The deployment tests live in `devops/tests/test_deployment_system.py`.

Covered checks:

- unit tests for Python script helpers
- Dockerfile presence and basic buildability signals
- ROS2 colcon build script
- ruff configuration
- black configuration
- mypy configuration
- unit test script
- integration test CI stage
- simulation smoke script
- config validation success
- deployment dry-run gates
- rollback dry-run support
- service health script
- pre-deployment dry run
- post-deployment dry run
- missing environment variable failure
- missing model file failure
- missing config file failure
- failed service startup guardrails
- failed rollback documentation
- monitoring stack config
- log collection
- version generation
- release checksum verification
- unmasked rosdep failure behavior
- deployment audit logging
- Grafana dashboard JSON validity
- stress validation across all environments
- latency checks for pre-deploy and checksum tooling
- simulation smoke execution through `bonbon_simulation`
- regression checks against hardcoded robot IPs
- documentation coverage and link checks

Run:

```bash
python -m pytest devops/tests -q
```

The tests intentionally avoid requiring Docker, ROS2, or SSH on a developer machine. CI is responsible for executing real Docker and ROS2 jobs.
