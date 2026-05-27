# Overview

BonBon is a ROS2 Humble service robot platform for safe navigation, perception, speech, TTS, LLM orchestration, data storage, operator dashboard control, simulation validation, and production deployment.

Primary software goals:

- Safe robot command execution through safety gates and supervisor state.
- Human-aware navigation with Nav2, RTAB-Map, recovery, docking, and low-battery routing.
- Modular perception, speech, TTS, and LLM pipelines.
- Persistent SQLite/vector/RAG data stores.
- Operator API and dashboard workflows with JWT auth and RBAC.
- Deterministic simulation validation before hardware deployment.
- CI/CD, Docker, systemd, monitoring, release, rollback, and security controls.

## Package Families

- Hardware and sensor abstraction: `bonbon_hal`
- Safety: `bonbon_safety`
- Navigation: `bonbon_navigation`
- Perception and vision: `bonbon_perception`, `bonbon_vision`, `bonbon_perception_ai`
- Speech and audio: `bonbon_speech`, `bonbon_tts`
- LLM and behavior orchestration: `bonbon_llm`
- Data stores: `bonbon_data_stores`
- Operator API/dashboard: `bonbon_operator_api`
- Simulation validation: `bonbon_simulation`
- Messages/services: `bonbon_msgs`, `bonbon_srvs`
- Deployment/DevOps: `deployment`, `devops`, `.github/workflows`

## Safety Principle

All command paths must respect the safety contract. Navigation must publish through `/bonbon/safety_gate/cmd_vel` rather than bypassing the safety pipeline. Operator API commands must pass validation and safety gating before reaching the ROS2 bridge.
