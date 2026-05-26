# bonbon_perception_ai

Perception + AI module for the Bonbon service robot.

Fuses raw sensor inputs (detected objects, tracked persons, speech commands, robot
pose and navigation state) into high-level semantic outputs: scene understanding,
user intent, context events, risk events, episodic memory and behaviour
recommendations — all without requiring a GPU, an external API, or network access
by default.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       INPUTS (ROS2 subscriptions)                       │
│  /bonbon/vision/objects   /bonbon/vision/persons   /speech/command      │
│  /bonbon/nav/status       /bonbon/spatial/pose                          │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         MultimodalFusion                                │
│  ModalityBuffer × 5  ──►  StaleDetector  ──►  FusionContext             │
│  (thread-safe slots)       (uncertainty)       (immutable snapshot)     │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
            ┌───────────────────────┼──────────────────────┐
            ▼                       ▼                      ▼
┌──────────────────┐   ┌─────────────────────┐  ┌───────────────────────┐
│  SceneAnalyzer   │   │   IntentEngine       │  │    RiskAssessor       │
│  SceneSnapshot   │   │   (rule-based /      │  │  person proximity     │
│  ContextEvent[]  │   │    LangChain)        │  │  nav uncertainty      │
│  activity / prox │   │   UserIntent         │  │  stale sensors        │
│  event diffing   │   │   slot extraction    │  │  conflicting commands │
└────────┬─────────┘   └──────────┬──────────┘  └──────────┬────────────┘
         │                        │                         │
         └───────────────────────►┼◄────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   BehaviorRecommender   │
                    │   risk > intent > scene │
                    │   BehaviorRecommendation│
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
         ┌──────────────────┐      ┌──────────────────────┐
         │   MemoryManager  │      │  ROS2 Publications   │
         │  FAISS (vector)  │      │  (see topic table)   │
         │  SQLite (struct) │      └──────────────────────┘
         │  privacy-aware   │
         └──────────────────┘
```

---

## ROS2 Topics

### Subscriptions

| Topic                       | Message Type          | QoS           | Rate      | Notes                              |
|-----------------------------|-----------------------|---------------|-----------|------------------------------------|
| `/bonbon/vision/objects`    | `DetectedObjectArray` | BEST_EFFORT   | ~10 Hz    | Filtered by `min_object_confidence` |
| `/bonbon/vision/persons`    | `PersonStateArray`    | BEST_EFFORT   | ~10 Hz    | Filtered by `min_person_confidence` |
| `/speech/command`           | `SpeechCommand`       | RELIABLE      | event     | Triggers immediate intent classify  |
| `/bonbon/nav/status`        | `std_msgs/String`     | BEST_EFFORT   | ~2 Hz     | Optional — nav uncertainty risk     |
| `/bonbon/spatial/pose`      | `geometry_msgs/Pose2D`| BEST_EFFORT   | ~5 Hz     | Optional — spatial context          |

### Publications

| Topic                        | Message Type              | QoS      | Rate          | Contents                                        |
|------------------------------|---------------------------|----------|---------------|-------------------------------------------------|
| `/perception/scene`          | `SemanticScene`           | RELIABLE | ≤10 Hz        | Activity, persons, objects, proximity, confidence |
| `/perception/intent`         | `UserIntent`              | RELIABLE | on speech     | Intent class, slots, confidence, ambiguity flag |
| `/perception/events`         | `ContextEvent`            | RELIABLE | on change     | person_arrived/left, activity_changed, etc.     |
| `/perception/risks`          | `RiskEvent`               | RELIABLE | on detection  | Severity CRITICAL/HIGH/MEDIUM/LOW, risk type    |
| `/perception/behavior`       | `BehaviorRecommendation`  | RELIABLE | on intent/tick| Recommended action, priority, trigger           |
| `/perception/memory_updates` | `MemoryEntry`             | RELIABLE | on record     | New/updated memory items                        |
| `/health/perception_ai`      | `ModuleHealth`            | RELIABLE | 1 Hz          | Uptime, scene count, pipeline status            |

---

## Quick Start

### Run the test suite

```bash
cd ros2_ws/src/bonbon_perception_ai

# All unit + integration tests (no ROS2, no GPU, no API keys needed)
pytest tests/ -v

# Run only integration scenarios
pytest tests/integration/ -v -s

# Run only benchmarks (p99 budget assertions)
pytest tests/benchmarks/bench_perception.py -v -s
```

### Run benchmarks standalone

```bash
# 200 repetitions, table output
python tests/benchmarks/bench_perception.py

# Quick 50-rep pass
python tests/benchmarks/bench_perception.py --quick

# Machine-readable JSON
python tests/benchmarks/bench_perception.py --json
```

### Launch with ROS2

```bash
# Defaults: rule-based intent, NumPy (no FAISS needed), in-memory SQLite
ros2 launch bonbon_perception_ai perception.launch.py

# Persistent SQLite database
ros2 launch bonbon_perception_ai perception.launch.py \
    memory.db_path:=/var/lib/bonbon/perception.db

# Enable LangChain intent backend (requires OPENAI_API_KEY or param)
ros2 launch bonbon_perception_ai perception.launch.py \
    intent.backend:=langchain \
    intent.langchain_model:=gpt-3.5-turbo

# Privacy-hardened: anonymise persons, suppress face storage
ros2 launch bonbon_perception_ai perception.launch.py \
    memory.privacy_anonymize_persons:=true \
    memory.privacy_store_faces:=false \
    privacy.suppress_speaker_id:=true

# Drone/slow-sensor scenario: relax staleness timeouts
ros2 launch bonbon_perception_ai perception.launch.py \
    fusion.objects_stale_sec:=5.0 \
    fusion.persons_stale_sec:=5.0
```

### Lifecycle management

```bash
# Configure → activate the node manually
ros2 lifecycle set /perception_ai_node configure
ros2 lifecycle set /perception_ai_node activate

# Deactivate (stops timers, clears buffers)
ros2 lifecycle set /perception_ai_node deactivate

# Watch health
ros2 topic echo /health/perception_ai

# Echo live scene state
ros2 topic echo /perception/scene

# Spy on behavior recommendations
ros2 topic echo /perception/behavior
```

---

## Parameter Reference

All parameters are declared with safe defaults. No secrets or paths are hardcoded.

### Node parameters

| Parameter               | Type   | Default | Description                                                |
|-------------------------|--------|---------|------------------------------------------------------------|
| `scene_publish_rate_hz` | float  | `10.0`  | Max frequency at which `/perception/scene` is published    |
| `health_rate_hz`        | float  | `1.0`   | Frequency of `/health/perception_ai` heartbeat             |
| `allow_degraded_startup`| bool   | `false` | Allow the node to start even if pipeline init fails        |

### Fusion parameters (`fusion.*`)

| Parameter                        | Type  | Default | Description                                                    |
|----------------------------------|-------|---------|----------------------------------------------------------------|
| `fusion.objects_stale_sec`       | float | `2.0`   | Object modality is STALE after this many seconds without update |
| `fusion.persons_stale_sec`       | float | `2.0`   | Person modality staleness timeout                              |
| `fusion.speech_stale_sec`        | float | `8.0`   | Speech is infrequent by design; longer timeout                 |
| `fusion.pose_stale_sec`          | float | `5.0`   | Robot pose staleness timeout                                   |
| `fusion.nav_stale_sec`           | float | `5.0`   | Navigation status staleness timeout                            |
| `fusion.min_object_confidence`   | float | `0.40`  | Objects below this confidence are dropped before fusion        |
| `fusion.min_person_confidence`   | float | `0.50`  | Persons below this confidence are dropped before fusion        |

### Scene parameters (`scene.*`)

| Parameter                        | Type  | Default | Description                                                      |
|----------------------------------|-------|---------|------------------------------------------------------------------|
| `scene.near_person_threshold_m`  | float | `2.0`   | Distance below which spatial_context = `"near_person"`           |
| `scene.interaction_proximity_m`  | float | `1.5`   | Distance below which activity = `"interacting"` or `"serving"`   |
| `scene.crowded_threshold`        | int   | `3`     | Minimum number of simultaneous persons to trigger `is_crowded`   |
| `scene.event_debounce_sec`       | float | `0.5`   | Minimum time between identical context events (avoids chattering)|

### Intent parameters (`intent.*`)

| Parameter                            | Type   | Default          | Description                                                     |
|--------------------------------------|--------|------------------|-----------------------------------------------------------------|
| `intent.backend`                     | string | `"rule_based"`   | `"rule_based"` or `"langchain"`. See backend comparison below.  |
| `intent.langchain_model`             | string | `"gpt-3.5-turbo"`| LLM model name — only used when `backend=langchain`             |
| `intent.langchain_api_key`           | string | `""`             | **NEVER hardcode.** Set here or via `OPENAI_API_KEY` env var.   |
| `intent.langchain_timeout_sec`       | float  | `5.0`            | LangChain inference timeout before fallback to rule-based       |
| `intent.intent_confidence_threshold` | float  | `0.55`           | Below this → `is_ambiguous=true`                                |
| `intent.ambiguity_policy`            | string | `"clarify"`      | `"clarify"` / `"best_guess"` / `"ignore"` (see below)          |

### Risk parameters (`risk.*`)

| Parameter                    | Type   | Default | Description                                                      |
|------------------------------|--------|---------|------------------------------------------------------------------|
| `risk.critical_proximity_m`  | float  | `0.40`  | Person closer than this → CRITICAL risk, immediate action flag   |
| `risk.high_proximity_m`      | float  | `0.70`  | Person in range (critical, high) → HIGH risk                     |
| `risk.caution_proximity_m`   | float  | `1.20`  | Person in range (high, caution) → MEDIUM risk                    |
| `risk.nav_uncertainty_risk`  | bool   | `true`  | Emit HIGH risk when navigating with HIGH sensor uncertainty       |
| `risk.crowded_severity`      | string | `"LOW"` | Severity level emitted for crowded-area risk events              |

### Memory parameters (`memory.*`)

| Parameter                          | Type   | Default | Description                                                      |
|------------------------------------|--------|---------|------------------------------------------------------------------|
| `memory.db_path`                   | string | `""`    | SQLite file path. Empty string = in-memory DB (cleared on exit). |
| `memory.max_episodes`              | int    | `10000` | Oldest 10% evicted when vector store exceeds this count          |
| `memory.episode_ttl_days`          | float  | `7.0`   | SQLite scene episodes older than this are purged                 |
| `memory.privacy_anonymize_persons` | bool   | `false` | Anonymise person IDs before storage (SHA-256 → `anon_<hex>`)    |
| `memory.privacy_store_faces`       | bool   | `false` | Whether to persist `face_id` strings in the database            |

### Privacy parameters (`privacy.*`)

| Parameter                            | Type  | Default | Description                                                      |
|--------------------------------------|-------|---------|------------------------------------------------------------------|
| `privacy.anonymize_persons`          | bool  | `false` | Synonym for `memory.privacy_anonymize_persons`                   |
| `privacy.store_faces`                | bool  | `false` | Synonym for `memory.privacy_store_faces`                         |
| `privacy.suppress_speaker_id`        | bool  | `false` | Replace speaker IDs with empty string before publishing          |
| `privacy.max_memory_retention_days`  | float | `7.0`   | Maximum days any personal data is retained                       |

---

## Intent Classification Backends

| Feature                  | `rule_based` (default)        | `langchain`                                   |
|--------------------------|-------------------------------|-----------------------------------------------|
| Latency                  | < 1 ms (regex, no I/O)        | 200 ms – 2 s (network round-trip)             |
| Requires network         | No                            | Yes                                           |
| Requires API key         | No                            | Yes (`OPENAI_API_KEY` or param)               |
| Offline capable          | Yes                           | No (unless self-hosted LLM)                   |
| Slot extraction          | Regex patterns                | LLM-extracted, higher recall                  |
| Novel phrasings          | Limited (pattern gaps)        | Strong                                        |
| Deterministic            | Yes                           | No                                            |
| Fallback                 | N/A (always available)        | Falls back to `rule_based` on timeout/error   |
| Config key               | `intent.backend=rule_based`   | `intent.backend=langchain`                    |

**Supported intent classes** (rule-based, zero configuration):

| Intent class   | Example utterances                                   | Behavior produced           |
|----------------|------------------------------------------------------|-----------------------------|
| `greeting`     | "Hello", "Hi there", "Good morning"                  | `speak_greeting`            |
| `order_item`   | "I'd like a coffee", "Bring me tea", "One water"     | `serve_item`                |
| `navigate_to`  | "Go to table 3", "Move to the entrance"              | `navigate_to_goal`          |
| `cancel`       | "Cancel", "Stop that", "Never mind"                  | `stop_navigation`           |
| `confirm`      | "Yes", "That's right", "Correct"                     | context-dependent           |
| `deny`         | "No", "Not that", "Wrong"                            | context-dependent           |
| `help_request` | "Help!", "I need assistance"                         | `alert_safety`              |
| `ask_question` | "What can you do?", "Where is the exit?"             | `speak_information`         |
| `silence`      | (is_silence flag from speech module)                 | idle / approach_person      |
| `unknown`      | Anything below confidence threshold                  | `speak_clarification`       |

**Ambiguity policies:**

| Policy        | Behaviour when `confidence < threshold`                              |
|---------------|----------------------------------------------------------------------|
| `clarify`     | Publish `is_ambiguous=true` + `fallback_response` text (default)     |
| `best_guess`  | Publish best-matching intent with `is_ambiguous=true`                |
| `ignore`      | Return `None` — nothing published to `/perception/intent`            |

### Setting the LangChain API key (safely)

```bash
# Option 1: environment variable (recommended for development)
export OPENAI_API_KEY="sk-..."
ros2 launch bonbon_perception_ai perception.launch.py intent.backend:=langchain

# Option 2: ROS2 parameter file
# config/params.yaml:
#   perception_ai_node:
#     ros__parameters:
#       intent.backend: langchain
#       intent.langchain_api_key: "sk-..."   # store encrypted; rotate regularly
ros2 launch bonbon_perception_ai perception.launch.py \
    --params-file config/params.yaml

# Option 3: launch argument (visible in process table — use only in dev)
ros2 launch bonbon_perception_ai perception.launch.py \
    intent.backend:=langchain \
    intent.langchain_api_key:=sk-...
```

**Never** embed the key in source code, `setup.py`, `package.xml`, or any file
committed to version control.

---

## Memory Backends

| Feature              | FAISS (`faiss-cpu`)             | NumPy fallback (built-in)          |
|----------------------|---------------------------------|------------------------------------|
| Install required     | `pip install faiss-cpu`         | None                               |
| Search algorithm     | `IndexFlatIP` (cosine, exact)   | Brute-force dot product            |
| Speed (10 k eps)     | ~0.5 ms                         | ~1–5 ms                            |
| Memory (10 k eps)    | ~1.3 MB (32-dim float32)        | Same                               |
| Deletions            | Full index rebuild (on eviction)| `np.delete` slice                  |
| Auto-selected        | Yes (tried first at import)     | Used automatically if FAISS absent |

**SQLite structured store** (always active):

```
persons           — person_id, first_seen, interaction_count, face_id
interactions      — person_id → intent_class, raw_text, timestamp
scene_episodes    — id, timestamp, activity, person_count, objects, description
known_objects     — class_name, first_seen, last_seen, observation_count
```

- `PRAGMA journal_mode=WAL` — concurrent reads while writes in progress
- Foreign key cascade ensures `forget_person()` removes all linked rows atomically
- `db_path=""` → in-memory (`:memory:`) — safe for tests, cleared on process exit

---

## Uncertainty and Staleness

The pipeline continuously monitors sensor freshness. Each modality has an
independent staleness timeout. When no update has arrived within the configured
window, that modality is flagged **stale**.

| Stale modality count | `uncertainty_level` | Confidence penalty | Typical cause                  |
|----------------------|---------------------|--------------------|--------------------------------|
| 0                    | `LOW`               | 0 %                | All sensors live               |
| 1–2                  | `MEDIUM`            | −20 %              | One camera lag, speech pause   |
| ≥ 3                  | `HIGH`              | −45 %              | Sensor failure, boot-up, test  |

Downstream effects:
- **Scene confidence** is penalised and `uncertainty_level` is propagated to `SemanticScene.msg`.
- **Navigation risk**: when `is_moving=True` and `uncertainty_level=HIGH`, a `navigation_with_uncertainty` `RiskEvent` (severity HIGH) is emitted.
- **Stale-sensor risk**: when ≥ 2 modalities are stale and uncertainty is MEDIUM or higher, a `stale_sensors` `RiskEvent` is emitted. When ≥ 3 stale, `requires_immediate_action=true`.

You can inspect the current stale state at any time:

```bash
ros2 topic echo /perception/scene --field stale_modalities
```

---

## Privacy and GDPR

### Design principles

- **Privacy by default** — anonymization, face storage, and speaker tracking are all `false` by default.
- **Data minimisation** — only the data needed for real-time behaviour is stored. Raw sensor data (audio, images) is never persisted by this module.
- **Right to erasure** — `MemoryManager.forget_person(person_id)` hard-deletes all rows for that person including all interactions, cascading via SQLite foreign keys. Episodic scene vectors are not linked to persons and are retained.

### Person ID anonymization

When `memory.privacy_anonymize_persons=true`, all person IDs are replaced with a
stable anonymous token before any database write:

```
real_id  →  SHA-256(real_id)[:12]  →  stored as "anon_<12-char hex>"
```

The real ID never appears in any database table, log, or published `MemoryEntry`.
The mapping is **one-way** — given only the anonymous ID, the original cannot be
recovered without also knowing the real ID to hash.

### GDPR forget-person

```python
# Python (e.g. from a privacy-compliance service)
memory_manager.forget_person("customer_42")

# Result:
#   DELETE FROM interactions WHERE person_id = "customer_42"   (cascade)
#   DELETE FROM persons      WHERE person_id = "customer_42"
#   After: is_known_person("customer_42") == False
```

```bash
# From a ROS2 service call (if a service wrapper is added)
ros2 service call /perception/forget_person \
    bonbon_msgs/srv/ForgetPerson '{person_id: "customer_42"}'
```

### Face ID storage

Face embeddings or recognition IDs are **not stored** unless `memory.privacy_store_faces=true`.
When disabled, `face_id=""` is written for every person regardless of what the
vision system provides.

### TTL purge

Scene episodes are automatically purged when:
1. `episode_ttl_days` has elapsed (time-based); or
2. `max_episodes` is exceeded (capacity-based — oldest 10 % removed).

Call `memory_manager.purge_old_data()` explicitly, or rely on the automatic
purge triggered by each `record_scene()` call.

---

## Behaviour Recommendation Priority

The `BehaviorRecommender` applies a strict four-tier priority rule:

```
1. RISK EVENTS  — highest severity risk drives the behavior
   CRITICAL → alert_safety      (PRIORITY_URGENT)
   HIGH     → stop_navigation   (PRIORITY_HIGH)
   MEDIUM   → speak_clarification
   LOW/nav  → stop_navigation

2. USER INTENT  — classified from speech
   greeting      → speak_greeting
   order_item    → serve_item        (item slot → params["item"])
   navigate_to   → navigate_to_goal  (destination slot → params["destination"])
   cancel        → stop_navigation   (PRIORITY_HIGH)
   help_request  → alert_safety
   ask_question  → speak_information
   ambiguous     → speak_clarification

3. SCENE CONTEXT — no speech, no risks
   idle + person present at 1.5–4.0 m → approach_person

4. DEFAULT
   → idle  (PRIORITY_LOW)
```

---

## Context Events

`SceneAnalyzer` emits discrete events whenever the scene state changes:

| `event_type`          | Trigger                                             |
|-----------------------|-----------------------------------------------------|
| `person_arrived`      | New person ID appears in current tick               |
| `person_left`         | Person ID present last tick is absent now           |
| `activity_changed`    | `dominant_activity` differs from previous snapshot  |
| `crowd_formed`        | `is_crowded` transitions `False → True`             |
| `crowd_dispersed`     | `is_crowded` transitions `True → False`             |
| `object_appeared`     | New object class detected that was absent           |
| `object_disappeared`  | Object class present last tick is absent now        |

Events are debounced: a change must persist for at least `scene.event_debounce_sec`
before a new event of the same type is re-emitted. This suppresses sensor flicker
without masking genuine scene transitions.

---

## Risk Events

| `risk_type`                    | Severity  | Requires action | Condition                                       |
|--------------------------------|-----------|-----------------|--------------------------------------------------|
| `person_too_close`             | CRITICAL  | Yes             | Person within `critical_proximity_m`            |
| `person_too_close`             | HIGH      | No              | Person within `high_proximity_m`                |
| `person_too_close`             | MEDIUM    | No              | Person within `caution_proximity_m`             |
| `navigation_with_uncertainty`  | HIGH      | No              | Moving + `uncertainty_level=HIGH`               |
| `crowded_area`                 | configurable | No           | `scene.is_crowded=True`                         |
| `stale_sensors`                | MEDIUM    | No              | ≥ 2 stale modalities                            |
| `stale_sensors`                | HIGH      | Yes             | ≥ 3 stale modalities                            |
| `conflicting_commands`         | LOW       | No              | confirm/deny or cancel/navigate within 3 s     |

All risk lists are sorted **descending by severity** before being published, so
the most critical item is always first.

---

## Extending the Module

### Add a new intent class

1. Add a key + regex list to `INTENT_PATTERNS` in `intent_engine.py`.
2. Add a slot pattern to `SLOT_PATTERNS` if needed.
3. Add an `elif intent.intent_class == "my_intent":` branch in `behavior_recommender.py`.
4. Add a test case in `tests/test_intent_engine.py`.

### Add a new risk type

1. Add a `_check_my_risk(ctx, scene)` method to `RiskAssessor`.
2. Call it inside `assess()` and `extend(risks, ...)`.
3. Add a test class in `tests/test_risk_assessor.py`.

### Add a new behavior class

1. Add a branch to `BehaviorRecommender.recommend()`.
2. Update the integration tests to assert the new mapping.

### Swap the scene embedding

Replace `SceneEmbedding.encode()` in `memory/vector_store.py`. Keep the output
shape `(DIM,)` float32 and update `MemoryConfig.vector_dim` if the dimension
changes. The FAISS index will be rebuilt automatically on the next open.

---

## Package Layout

```
bonbon_perception_ai/
├── bonbon_perception_ai/
│   ├── config/
│   │   └── perception_config.py   # typed dataclass config hierarchy
│   ├── fusion/
│   │   ├── types.py               # ObjectObservation, PersonObservation, FusionContext, …
│   │   ├── modality_buffer.py     # thread-safe single-slot timestamped buffer
│   │   ├── stale_detector.py      # maps stale count → uncertainty level
│   │   └── multimodal_fusion.py   # five buffers → FusionContext
│   ├── understanding/
│   │   ├── scene_analyzer.py      # SceneSnapshot + ContextEvent diffing
│   │   ├── intent_engine.py       # rule-based + LangChain intent + slots
│   │   ├── risk_assessor.py       # per-type risk checks → sorted RiskEvent[]
│   │   └── behavior_recommender.py# priority table → BehaviorRecommendation
│   ├── memory/
│   │   ├── vector_store.py        # SceneEmbedding + FAISS/NumPy store
│   │   ├── structured_store.py    # SQLite persons/interactions/episodes
│   │   └── memory_manager.py     # unified API + privacy + TTL
│   ├── langchain_tools/
│   │   ├── intent_chain.py        # LangChain intent classification chain
│   │   └── scene_describer.py     # LangChain natural-language scene summary
│   └── nodes/
│       └── perception_node.py     # ROS2 LifecycleNode entry point
├── launch/
│   └── perception.launch.py       # full parameterised launch file
├── tests/
│   ├── test_modality_buffer.py
│   ├── test_stale_detector.py
│   ├── test_multimodal_fusion.py
│   ├── test_scene_analyzer.py
│   ├── test_intent_engine.py
│   ├── test_risk_assessor.py
│   ├── test_behavior_recommender.py
│   ├── test_memory_manager.py
│   ├── integration/
│   │   └── test_perception_integration.py   # 8 end-to-end scenarios
│   └── benchmarks/
│       └── bench_perception.py              # 13 latency benchmarks, p99 budgets
├── package.xml
├── setup.py
└── setup.cfg
```

---

## Dependencies

### Required

| Package          | Source   | Notes                                    |
|------------------|----------|------------------------------------------|
| `rclpy`          | ROS2     | Humble or later                          |
| `bonbon_msgs`    | workspace| Custom message definitions               |
| `numpy`          | pip/apt  | Vector operations, fallback search       |
| `std_msgs`       | ROS2     |                                          |
| `geometry_msgs`  | ROS2     |                                          |

### Optional (graceful fallback if absent)

| Package                 | Install                      | Enables                                   |
|-------------------------|------------------------------|-------------------------------------------|
| `faiss-cpu`             | `pip install faiss-cpu`      | 10× faster vector search for episodic memory |
| `langchain`             | `pip install langchain`      | LLM-powered intent classification         |
| `openai`                | `pip install openai`         | OpenAI backend for LangChain              |
| `sentence-transformers` | `pip install sentence-transformers` | Richer scene embeddings (optional)  |

Install all optional extras at once:

```bash
pip install faiss-cpu langchain openai sentence-transformers
```

---

## Benchmark P99 Budgets

| Benchmark                    | p99 budget | What it measures                              |
|------------------------------|------------|-----------------------------------------------|
| `fusion_fuse`                | 1.0 ms     | `MultimodalFusion.fuse()` with 3 live modalities |
| `fusion_update_objects`      | 0.5 ms     | `update_objects()` with 5 objects             |
| `scene_analyze_idle`         | 2.0 ms     | `SceneAnalyzer.analyze()` — empty scene       |
| `scene_analyze_3persons`     | 5.0 ms     | `analyze()` — 3 persons, event diffing        |
| `intent_classify_match`      | 2.0 ms     | Rule-based intent, clear match                |
| `intent_classify_ambiguous`  | 2.0 ms     | Rule-based intent, no match                   |
| `risk_assess_no_risk`        | 1.0 ms     | `RiskAssessor.assess()` — safe scene          |
| `risk_assess_critical`       | 1.0 ms     | `assess()` — critical proximity               |
| `behavior_recommend`         | 1.0 ms     | `BehaviorRecommender.recommend()`             |
| `scene_embedding`            | 0.5 ms     | `SceneEmbedding.encode()` + `normalise()`     |
| `memory_record_scene`        | 10.0 ms    | SQLite insert + FAISS/NumPy add               |
| `memory_recall_200ep`        | 15.0 ms    | Similarity search over 200 stored episodes    |
| `e2e_pipeline`               | 10.0 ms    | Full fuse → analyze → classify → assess → recommend |

All benchmarks run entirely in-process with mocked data. No ROS2 middleware,
no GPU, no network I/O.

---

## License

Proprietary — Bonbon Robotics. All rights reserved.
