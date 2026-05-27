# Future Improvements

## Platform

- Add a top-level bringup package that launches all production modules with environment profiles.
- Add generated interface documentation from `.msg` and `.srv` definitions.
- Add architecture diagrams rendered in CI.
- Add a unified module health dashboard.

## Safety

- Add hardware-in-the-loop safety regression tests.
- Add formal safety case documentation.
- Add automated verification that no package publishes directly to `/cmd_vel`.
- Add safety threshold diff review tooling.

## Simulation

- Add full Gazebo launch testing in scheduled CI.
- Add Isaac Sim adapters for selected scenarios.
- Add sensor noise model calibration from lab logs.
- Add scenario coverage tracking.

## Deployment

- Add OTA agent with on-robot artifact verification.
- Add canary rollout support for robot fleets.
- Add SBOM generation and enforcement.
- Add cosign verification on the robot before activation.
- Add package-level CI matrix and Docker layer cache.

## Observability

- Add Loki or OpenTelemetry.
- Add alert rules for stale topics, safety events, battery, disk, CPU, and memory.
- Add ROS2 graph exporter.
- Add dashboard panels for scenario pass rates.

## Security and Privacy

- Add secret manager integration.
- Add encrypted database backups.
- Add signed model manifests.
- Add automatic privacy retention reports.
