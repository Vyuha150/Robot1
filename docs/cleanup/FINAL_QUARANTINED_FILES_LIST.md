# Final Quarantined Files List

**Phase 13.** Every git-tracked file moved to `_archive/quarantine_cleanup_20260814/` in this cleanup. List generated directly from `git status --short`'s rename records, not reconstructed from memory — **36 files total**, all tracked by git as renames, none permanently deleted. Full restore commands per group are in `RESTORE_PLAN.md`.

## Group 1: `bonbon_perception` package (25 files)

Confirmed dead duplicate of `bonbon_vision` — see `DUPLICATE_PIPELINE_REPORT.md`.

```
ros2_ws/src/bonbon_perception/README.md
ros2_ws/src/bonbon_perception/bonbon_perception/__init__.py
ros2_ws/src/bonbon_perception/bonbon_perception/config/perception_params.yaml
ros2_ws/src/bonbon_perception/bonbon_perception/detectors/__init__.py
ros2_ws/src/bonbon_perception/bonbon_perception/detectors/hog_person_detector.py
ros2_ws/src/bonbon_perception/bonbon_perception/detectors/mock_person_detector.py
ros2_ws/src/bonbon_perception/bonbon_perception/detectors/person_detector.py
ros2_ws/src/bonbon_perception/bonbon_perception/detectors/yolo_person_detector.py
ros2_ws/src/bonbon_perception/bonbon_perception/nodes/__init__.py
ros2_ws/src/bonbon_perception/bonbon_perception/nodes/detection_node.py
ros2_ws/src/bonbon_perception/bonbon_perception/nodes/face_node.py
ros2_ws/src/bonbon_perception/bonbon_perception/trackers/__init__.py
ros2_ws/src/bonbon_perception/bonbon_perception/trackers/person_tracker.py
ros2_ws/src/bonbon_perception/bonbon_perception/trackers/simple_tracker.py
ros2_ws/src/bonbon_perception/launch/perception.launch.py.disabled
ros2_ws/src/bonbon_perception/package.xml
ros2_ws/src/bonbon_perception/resource/bonbon_perception
ros2_ws/src/bonbon_perception/setup.cfg
ros2_ws/src/bonbon_perception/setup.py
ros2_ws/src/bonbon_perception/tests/__init__.py
ros2_ws/src/bonbon_perception/tests/integration/__init__.py
ros2_ws/src/bonbon_perception/tests/integration/test_perception_integration.py
ros2_ws/src/bonbon_perception/tests/test_detection_node_logic.py
ros2_ws/src/bonbon_perception/tests/test_person_detector.py
ros2_ws/src/bonbon_perception/tests/test_tracker.py
```

## Group 2: Dead hand-tracking assets (9 files, 3 Git-LFS-tracked)

Zero references anywhere in `frontend/src` — see `STALE_MOCK_AND_PLACEHOLDER_REPORT.md`.

```
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hand_landmark_full.tflite       [LFS]
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hand_landmark_lite.tflite
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands.binarypb
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands.js
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_packed_assets.data
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_packed_assets_loader.js
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_simd_wasm_bin.data
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_simd_wasm_bin.js
ros2_ws/src/bonbon_operator_api/frontend/public/models/hands/hands_solution_simd_wasm_bin.wasm [LFS]
```

## Group 3: Orphaned package launch files (2 files)

Zero `IncludeLaunchDescription` references anywhere; the real deployment launches these two nodes via inline `ros2 run` instead — see `BROKEN_CODE_REPORT.md` and `DEPLOYMENT_MODE_CONFLICT_REPORT.md`.

```
ros2_ws/src/bonbon_authority_manager/launch/authority_manager.launch.py
ros2_ws/src/bonbon_distributed_safety/launch/distributed_safety.launch.py
```

## Total: 36 files quarantined (25 + 9 + 2)

Every one is individually restorable per `RESTORE_PLAN.md`; none is scheduled for permanent deletion by this cleanup — permanent deletion of Tier 2 items only happens after the sanity-check window described in `QUARANTINE_REPORT.md`, which is a decision for you, not something this phase executes automatically.
