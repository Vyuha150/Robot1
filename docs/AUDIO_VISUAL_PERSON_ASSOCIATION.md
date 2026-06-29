# Audio-Visual Person Association

How BonBon links a sound (a gesture's frame position, or a speaker's
direction-of-arrival) to a specific tracked person. The same design pattern
is implemented twice, independently, for two different input modalities —
this doc explains the shared pattern and why it isn't shared code.

## The shared pattern

Both `bonbon_gesture` and `bonbon_speaker_intelligence` need to answer "which
tracked person does this signal belong to," using `bonbon_multi_person_tracker`'s
`PersonTrack.position_3d` as the ground truth for where people actually are.
Both convert that position to a **bearing** (`atan2(y, x)`, the same
convention `bonbon_spatial`'s `SpatialRelation.bearing_deg` already uses —
positive = robot's left) and match the incoming signal's own
direction/position against it, **within a tolerance, never forcing a match**.

| | `bonbon_gesture` (`GesturePersonAssigner`) | `bonbon_speaker_intelligence` (`audio_visual_associator`) |
|---|---|---|
| Input signal | Camera-pixel horizontal position of a landmark set | Microphone-array direction-of-arrival (DOA) |
| Conversion needed | Pixel position → bearing prediction (needs `camera_hfov_deg`) | None — DOA already IS a bearing |
| Matching | Greedy nearest-bearing, one-to-one | Single nearest-bearing match |
| Granularity | Per camera frame | Per WHOLE utterance (can't disambiguate within one) |

## Why this isn't one shared module

The two are solving genuinely different geometry problems (projecting a
pixel position through a camera model vs. using an already-physical
bearing measurement), and unifying them behind one abstraction would add an
indirection layer for what is, in each case, a handful of lines of
well-understood trigonometry — not the kind of duplication the project's
"don't duplicate pipelines" rule is about (that rule targets redundant
detection/diarization/tracking PIPELINES, not a shared textbook formula
implemented twice for two different inputs).

## Honest limitations (apply to both)

- **Never a forced match.** Both implementations reject a candidate outside
  tolerance rather than assigning it to the nearest-but-still-wrong person.
  A rejected match means "unknown person" downstream — `person_track_id=""`
  — never a guess.
- **Camera HFOV / DOA calibration matters.** A wrong `camera_hfov_deg` (must
  match the active camera driver) skews every bearing prediction in
  `bonbon_gesture`; a poorly calibrated mic array does the same for
  `bonbon_speaker_intelligence`.
- **Crowded scenes degrade gracefully, not silently.** Two people close
  together in bearing may both fail to match confidently — that shows up as
  more unassigned events, not misattributed ones.
- **`bonbon_speaker_intelligence`'s case is strictly harder**: a single DOA
  reading describes a whole utterance, not a diarization segment within it.
  Overlapping-speech turns are explicitly flagged `is_overlapping=True` with
  halved association confidence — the system tells you it's less sure,
  rather than pretending otherwise.

## Where this is implemented

- [`bonbon_gesture/logic/person_assigner.py`](../ros2_ws/src/bonbon_gesture/bonbon_gesture/logic/person_assigner.py) — see [GESTURE_INTELLIGENCE.md](GESTURE_INTELLIGENCE.md).
- [`bonbon_speaker_intelligence/core/audio_visual_associator.py`](../ros2_ws/src/bonbon_speaker_intelligence/bonbon_speaker_intelligence/core/audio_visual_associator.py) — see [SPEAKER_INTELLIGENCE.md](SPEAKER_INTELLIGENCE.md).

## Tests

Covered by each package's own test suite (`test_person_assigner.py`,
`test_audio_visual_associator.py`) plus 3 of the 25 cross-package scenarios
specifically exercising cross-modal correctness (pointing gesture assigned
correctly, simultaneous multi-person gestures, speaker linked to visible
person).
