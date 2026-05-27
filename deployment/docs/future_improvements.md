# Future Improvements

Recommended next steps:

1. Add Docker BuildKit cache and GitHub Actions cache for ROS dependency layers.
2. Split CI into a package matrix so unrelated packages do not block each other.
3. Add a real ROS2 metrics exporter node for `bonbon_ros2_node_health` and topic freshness.
4. Integrate Loki or OpenTelemetry for structured logs and traces.
5. Add canary rollout support for multiple robots.
6. Add hardware-in-the-loop deployment rehearsal in `lab_robot`.
7. Add SBOM generation with Syft and enforce vulnerability policy with Grype or Trivy.
8. Replace SSH deployment with an OTA agent when fleet size grows.
9. Add cosign verification on the robot before activating a release.
10. Add signed model manifests and checksum verification for model files.
