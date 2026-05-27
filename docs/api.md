# API

The primary HTTP API is implemented by `bonbon_operator_api`.

Base prefix:

```text
/api/v1
```

Authentication:

- JWT-based auth.
- RBAC permissions are required for command, status, memory, RAG, diagnostics, and config operations.
- `BONBON_JWT_SECRET` must be provided at runtime.

## Command API

Prefix:

```text
/api/v1/robot/commands
```

Endpoints:

- `POST /emergency_stop`
- `POST /speak`
- `POST /navigate`
- `POST /pause`
- `POST /resume`
- `POST /dock`
- `POST /cancel_task`

Safety behavior:

- Every command is validated before dispatch.
- Every command passes through `SafetyCommandGate`.
- Emergency stop is accepted regardless of current safety state.
- Motion commands are blocked during safety halt states.

## Robot Status API

Prefix:

```text
/api/v1/robot
```

Endpoints:

- `GET /status`
- `GET /status/safety`
- `GET /status/battery`
- `GET /status/navigation`
- `GET /status/health`

Typical use:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/robot/status
```

## Memory and RAG API

Prefix:

```text
/api/v1/memory
```

Endpoints:

- `POST /query`
- `POST /rag/query`

Example:

```bash
curl -X POST http://localhost:8080/api/v1/memory/rag/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"What room is patient 204 in?","collection":"general_knowledge","top_k":5}'
```

## Diagnostics and Config APIs

The diagnostics/config routers expose module health, restart operations, and configuration read/write flows. Safety-critical config changes require elevated permissions.

## WebSocket API

Dashboard WebSocket channels include robot status and safety event updates. Safety-event streams should be treated as high-priority UI signals and never hidden while the robot is not in a normal safety state.

## Metrics

The dashboard API should expose Prometheus-compatible metrics where enabled:

- command counts/outcomes
- command latency
- auth failures
- safety blocks
- dashboard health
- bridge call failures
