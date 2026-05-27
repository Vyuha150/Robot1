# BonBon CI/CD and Deployment System

This deployment system makes BonBon production-ready across `local_dev`, `simulation`, `lab_robot`, `staging_robot`, and `production_robot`.

Deployment is blocked unless linting, formatting, type checks, unit tests, integration tests, safety tests, and simulation smoke tests pass.

## Overview

The module provides the operational wrapper around the BonBon ROS2 software platform: build validation, Docker packaging, environment-specific deployment, rollback, observability, release integrity, and deployment documentation.

Testing is part of the module contract. The DevOps test suite covers unit, integration, failure injection, stress, regression, simulation, and latency benchmark style checks.

## Architecture

The system is split into:

- `.github/workflows/`: CI and signed release automation
- `deployment/docker/`: runtime images for ROS2, AI, navigation, and dashboard API
- `deployment/compose/`: local, simulation, and robot Compose stacks
- `deployment/systemd/`: host-level service managers
- `deployment/monitoring/`: Prometheus and Grafana configuration
- `devops/scripts/`: build, test, deploy, rollback, health, logs, config, and version tooling
- `devops/config/`: environment-specific config without secrets

## Required Gates

Before robot deployment:

- `ruff check .`
- `black --check .`
- `mypy`
- `rosdep install --from-paths ros2_ws/src --ignore-src`
- `colcon build`
- package unit tests
- integration tests
- safety tests
- simulation smoke tests
- security scan
- config validation
- signed/checksummed release artifact

## Documentation Index

- [Architecture](architecture.md)
- [Top 1% Engineering Review](engineering_review.md)
- [Local Setup](local_setup.md)
- [Configuration Reference](configuration.md)
- [ROS2 Interfaces](ros2_interfaces.md)
- [Usage Examples](examples.md)
- [Test Matrix](tests.md)
- [Simulation Setup](simulation_setup.md)
- [Robot Deployment](robot_deployment.md)
- [Deployment Notes](deployment_notes.md)
- [CI Pipeline](ci_pipeline.md)
- [Docker Usage](docker_usage.md)
- [Systemd Setup](systemd_setup.md)
- [Monitoring Setup](monitoring_setup.md)
- [Release Process](release_process.md)
- [Rollback Process](rollback_process.md)
- [Troubleshooting](troubleshooting.md)
- [Security Checklist](security_checklist.md)
- [Security Concerns](security_concerns.md)
- [Failure Modes](failure_modes.md)
- [Performance Tuning](performance_tuning.md)
- [Production Deployment Checklist](production_deployment_checklist.md)
- [Future Improvements](future_improvements.md)
