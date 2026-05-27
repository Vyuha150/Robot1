# Metrics Guide

Scenario reports include:

- navigation success rate
- collision count
- near-miss count
- average path deviation
- emergency stop reaction time
- obstacle detection latency
- replanning latency
- recovery success rate
- CPU usage
- memory usage
- average task completion time
- battery usage estimate
- false positive safety stops
- false negative safety events
- docking success rate

Reports are written as JSON under `simulation_reports/`. Failed scenarios should save artifacts under `simulation_artifacts/`.
