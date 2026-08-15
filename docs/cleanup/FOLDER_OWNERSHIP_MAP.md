# Folder Ownership Map

**Phase 2 companion to `FILE_CLASSIFICATION_MATRIX.md`.** Answers "who owns this, and what depends on it" as a narrative rather than a table — useful for Phase 3 (duplicate detection) and Phase 8 (config/launch cleanup), which need to reason about dependency direction, not just classification.

## The two production launch mechanisms (confirmed distinct, relationship not yet fully resolved — Phase 3/8)

1. **`*_bringup` packages** (`bonbon_bringup`, `bonbon_human_ai_bringup`, `bonbon_ui_api_bringup`, `bonbon_patient_kiosk_bringup`, `bonbon_navigation_bringup`) — each composes the **full application stack** for its deployment target (single-host, Pi-2, Pi-1, kiosk, Pi-3 respectively) by including existing per-package launch files.
2. **`launch/edge_ai/{ai,nav,ui}_pi_edge.launch.py`** — each launches the **edge-AI infrastructure layer** for its Pi: task router (`bonbon_edge_ai_runtime`, AI Pi only), hardware telemetry, network monitor, plus (on the nav Pi) the safety supervisor/gate/gateway/e-stop chain. Invoked by `scripts/edge_ai/start_{ai,nav,ui}_pi.sh`.

Both sets are real and both are referenced by real scripts/systemd services. Whether a given Pi's boot sequence runs both (as separate systemd units, standard practice for a multi-service host) or whether one has silently superseded the other is a genuine open question — Phase 8's systemd-service audit will resolve it by checking which systemd units on `deployment/systemd/pi{1,2,3}/` actually invoke which launch file. Not guessed here.

## Ownership by subsystem

**Camera/vision:** `bonbon_vision` owns the camera and all model inference (YOLO, face). Everything else in the perception cluster (`bonbon_perception_ai`, `bonbon_perception_efficiency`, `bonbon_object_intelligence`, `bonbon_multi_person_tracker`, `bonbon_spatial`) is a pure consumer of `bonbon_vision`'s topic output (`/bonbon/vision/objects`, `/bonbon/vision/persons`) — none of them re-run detection. `bonbon_gesture` is the exception: it reads the camera stream directly for its own MediaPipe/deterministic gesture classification (a distinct modality, not object/person detection), separately from `bonbon_vision`.

**Microphone/speech:** `bonbon_speech` owns the microphone (VAD, wake-word, Whisper STT). `bonbon_tts` owns the speaker output. `bonbon_affective_ai` and `bonbon_speaker_intelligence` are consumers of speech/audio-derived signals, not audio-device owners. `bonbon_speech_ai` (router/normalizer library) currently owns nothing at runtime — it exists but isn't wired to either owner.

**Motion/actuation authority:** `bonbon_safety`'s `safety_gate_node` is the **sole** publisher of `/cmd_vel` and gated servo/stepper commands — confirmed via repo-wide grep, no other publisher exists. `bonbon_hal` is the only package that writes to physical motor/servo/stepper hardware, and only ever in response to the gated topics. `bonbon_base_controller` and `bonbon_navigation` explicitly disclaim originating motion in their own docstrings. `bonbon_actuation` publishes only to `*_raw` topics that still route through the gate. This chain has no exceptions anywhere in the 44-package tree (see the safety-cluster research pass and `DANGEROUS_CODE_AUDIT.md`).

**Dashboard/data:** `bonbon_operator_api` (staff dashboard) and `bonbon_patient_kiosk` (patient-facing kiosk) are independent backends for different audiences, each with its own SQLite store and its own (structurally duplicated — see Delete Risk Register) auth implementation. `bonbon_data_stores` is the one shared persistence layer both could in principle use but currently don't (each maintains a separate DB). `bonbon_fault_manager` is the single aggregation point for hardware fault state, consumed only by `operator_api`.

**Interfaces:** `bonbon_msgs` (51 `.msg` files) and `bonbon_srvs` (16 `.srv` files) are pure interface packages with no runtime code — nearly every other package depends on one or both.

## Top-level non-package ownership

- **`config/`** is the single source of runtime YAML truth, loaded by launch files and Dockerfiles — no package hardcodes what belongs here.
- **`deployment/`** owns all Docker/systemd/compose definitions for actual Pi deployment; the 3 root-level `docker-compose.*.yml` files are thin includes into it, not a competing source.
- **`deploy/`** (singular) is unrelated to `deployment/` (plural) — it's a one-off historical artifact directory from a completed Pi-2 deployment session, not an ongoing engineering location.
- **`bonbon_behavior_validation/`** and **`bonbon_field_learning/`** (top-level, outside `ros2_ws/`) are simulation/offline-validation tooling consumed by `bonbon_operator_api`'s `validation_api.py` and the top-level `tests/production/` suite — never part of the live ROS2 graph.
- **`founder_command_center/`** has no ownership relationship to anything else in this repo — zero inbound or outbound references found. It reads as a separate product that happens to live in the same git repository.
