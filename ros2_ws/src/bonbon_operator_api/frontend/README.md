# BonBon Operator Dashboard Frontend

React-based local test cockpit for the BonBon service robot. It runs on `http://localhost:3000` and connects to the FastAPI backend on `http://127.0.0.1:8080` by default.

## What You Can Test Visually

- Backend/API health and authentication.
- Live browser camera stream.
- Frame-processing metrics: FPS, brightness, contrast, edge score, and motion.
- Browser microphone level, including an obvious "audio heard" indicator.
- LLM prompting through local Ollama or an OpenAI-compatible provider.
- One-shot runtime API-key testing without saving the key.
- TTS command dispatch through the existing safety-gated robot command API.
- Emergency stop command dispatch through the existing safety gate.
- Robot status and diagnostics snapshots.

## Structure

```text
frontend/
|-- index.html
|-- package.json
|-- vite.config.ts
|-- tsconfig.json
`-- src/
    |-- App.tsx
    |-- main.tsx
    |-- styles.css
    `-- services/
        `-- api.ts
```

## Quick Start

```powershell
cd "C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_operator_api\frontend"
npm install
npm start
```

Open:

```text
http://localhost:3000
```

## Backend

Start the FastAPI backend separately:

```powershell
cd "C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_operator_api"
$env:BONBON_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
$env:BONBON_ADMIN_PASSWORD="local-only-password"
..\..\..\.venv\Scripts\python.exe -m uvicorn bonbon_operator_api.main:create_app --factory --host 0.0.0.0 --port 8080
```

Then login in the dashboard with:

```text
username: admin
password: value of BONBON_ADMIN_PASSWORD
```

## LLM Testing

Recommended free local path:

```powershell
ollama pull llama3.2:3b
ollama serve
```

Use provider `Local Ollama`, base URL `http://localhost:11434`, and model `llama3.2:3b`.

For remote OpenAI-compatible APIs, paste the key into the dashboard. The backend uses the key only for that single request and does not persist or audit-log it.

## Camera And Audio

The dashboard uses browser APIs for visual local testing:

- `navigator.mediaDevices.getUserMedia({ video: true })` for live camera.
- Canvas frame analysis for brightness, contrast, edges, FPS, and motion.
- `AudioContext` analyser for microphone level and "audio heard" confirmation.

These checks confirm browser media access. ROS2 camera, perception, and STT are still validated through the robot modules and ROS2 topics.

## Safety UI Contract

- Emergency stop is exposed as an explicit red action.
- TTS and emergency commands go through the backend `SafetyCommandGate`.
- The dashboard never directly publishes `/cmd_vel`, direct motor, servo, or GPIO commands.
- API keys are request-scoped runtime input only; do not put them in `.env` unless they are deployment-managed secrets outside Git.

