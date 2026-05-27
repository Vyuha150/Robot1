# BonBon Robot Software Documentation

This documentation covers the full BonBon service robot software platform: ROS2 modules, simulation, dashboard API, data stores, safety, navigation, deployment, testing, troubleshooting, and future improvements.

BonBon is organized as a ROS2 Humble workspace with package-level modules under `ros2_ws/src`, plus operational tooling under `deployment/`, `devops/`, and `.github/workflows/`.

## Documentation Index

- [Overview](overview.md)
- [Architecture](architecture.md)
- [Setup](setup.md)
- [Configuration](configuration.md)
- [Module Guide](modules.md)
- [API](api.md)
- [ROS2 Interfaces](ros2_interfaces.md)
- [Examples](examples.md)
- [Testing](tests.md)
- [Troubleshooting](troubleshooting.md)
- [Deployment Notes](deployment.md)
- [Performance Tuning](performance_tuning.md)
- [Security Concerns](security.md)
- [Future Improvements](future_improvements.md)

## Deployment Gate

No real-world deployment should happen unless linting, type checks, unit tests, integration tests, safety tests, and simulation smoke tests pass. Safety gate, command validation, ROS2 bridge, navigation, and simulation failures must be treated as deployment blockers.
