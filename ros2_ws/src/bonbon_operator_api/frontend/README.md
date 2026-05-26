# BonBon Operator Dashboard — Frontend

React-based operator dashboard for the BonBon service robot.

## Structure

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── App.tsx                  # Root component, router
│   ├── index.tsx                # Entry point
│   ├── api/
│   │   ├── client.ts            # Axios instance with JWT interceptor
│   │   ├── auth.ts              # Login, /me endpoints
│   │   ├── robot.ts             # Robot status REST calls
│   │   ├── commands.ts          # Command dispatch (speak, navigate, e-stop, …)
│   │   ├── diagnostics.ts       # Module status, audit log
│   │   └── config.ts            # Config read/write
│   ├── hooks/
│   │   ├── useWebSocket.ts      # Generic WS hook with auto-reconnect
│   │   ├── useRobotStatus.ts    # Subscribes to robot-status channel
│   │   └── useSafetyEvents.ts   # Subscribes to safety-events channel
│   ├── store/
│   │   ├── authSlice.ts         # Redux slice: token, role, expiry
│   │   └── robotSlice.ts        # Redux slice: live robot status snapshot
│   ├── pages/
│   │   ├── Login/               # Login form
│   │   ├── Dashboard/           # Main operator dashboard
│   │   ├── Diagnostics/         # Module health, audit log
│   │   ├── Config/              # Config editor (role-gated)
│   │   └── Memory/              # Memory / RAG query UI
│   └── components/
│       ├── SafetyBanner.tsx     # Red banner when safety_state != normal
│       ├── BatteryIndicator.tsx
│       ├── NavigationMap.tsx    # Simple 2D nav goal picker
│       ├── CommandPanel.tsx     # Speak, navigate, pause, resume, dock
│       └── AuditTable.tsx       # Paginated audit log viewer
├── package.json
└── tsconfig.json
```

## Quick Start

```bash
cd frontend
npm install
npm start          # Dev server on http://localhost:3000
npm run build      # Production build → build/
```

## Environment variables

Create `frontend/.env`:
```
REACT_APP_API_BASE_URL=http://localhost:8080
```

## Authentication

All API calls include `Authorization: Bearer <token>` from `localStorage`.
WebSocket channels authenticate via `?token=<jwt>` query param.

## Role-gating

| Page / Action         | Viewer | Operator | Engineer | Admin |
|-----------------------|--------|----------|----------|-------|
| Dashboard (read)      | ✓      | ✓        | ✓        | ✓     |
| Issue commands        |        | ✓        | ✓        | ✓     |
| Diagnostics (read)    | ✓      | ✓        | ✓        | ✓     |
| Restart module        |        |          | ✓        | ✓     |
| Config (limited)      |        | ✓        | ✓        | ✓     |
| Config (critical)     |        |          |          | ✓     |
| User management       |        |          |          | ✓     |
| Audit log             |        |          |          | ✓     |

## Safety UI contract

* The **Safety Banner** is always visible and cannot be dismissed while `safety_state != "normal"`.
* The **Emergency Stop** button is always rendered and enabled regardless of other UI state.
* Navigation commands are disabled in the UI when `safety_state` is `emergency_stop` or `safety_stop`.
  The server enforces the same rules; the UI disabling is a UX improvement only.
