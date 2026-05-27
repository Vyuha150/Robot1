# Simulation Setup

Run deterministic simulation validation:

```bash
devops/scripts/run_simulation_smoke.sh
```

Run the simulation Compose stack:

```bash
docker compose -f docker-compose.simulation.yml up --build
```

Simulation reports are written by `bonbon_simulation` under `simulation_reports/`; failed scenario artifacts are written under `simulation_artifacts/`.
