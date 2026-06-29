# Speaker Intelligence

Package: [`bonbon_speaker_intelligence`](../ros2_ws/src/bonbon_speaker_intelligence/README.md)

## Purpose

Persistent speaker identity, transcript-to-speaker mapping, and
audio-visual speaker association. Does not run VAD/STT/diarization — those
already exist in `bonbon_speech`. This package adds what that pipeline
computed internally and then discarded before publishing: per-segment
diarization detail (who spoke when, within one utterance).

## Architecture

```
bonbon_speech/speech_node
   │ /speech/transcription (SpeechTranscription: text, word timings,
   │  segment_speaker_ids/start/end/confidence — extended this round)
   ▼
speaker_intelligence_node
   │  SpeakerTurnBuilder
   │    ├─ transcript_segment_mapper (word-timestamp → segment attribution)
   │    ├─ SpeakerIdentityManager (DOA + recency continuity)
   │    ├─ audio_visual_associator (DOA → PersonTrack bearing)
   │    └─ VoiceEmotionCache (latest bonbon_affective_ai reading, if fresh)
   ▼
/bonbon/speaker/turns (SpeakerTurn)
```

### The bonbon_speech extension this required

`speech_node._process_segment` already computed the diarizer's full
`DiarizationResult.segments` every utterance, then discarded everything
except the collapsed `dominant_speaker`/`all_speaker_ids`. Re-running
diarization in this package to get the detail back would have duplicated
`bonbon_speech`. Instead, `SpeechTranscription.msg` gained four parallel
arrays (`segment_speaker_ids`, `segment_start_sec`, `segment_end_sec`,
`segment_confidences`), populated from data `speech_node` already had in
hand.

### Honest limitations

- **`SpeakerIdentityManager` is NOT a voiceprint.** No acoustic-embedding
  model exists anywhere in this repo. Identity continuity is DOA (direction
  of arrival) + recency matching — a real, working heuristic, but two
  different people speaking from the same direction in quick succession
  will be merged, and the same person moving will be treated as new.
- **A single DOA reading describes the WHOLE utterance**, not each
  diarization segment. Overlapping-speech turns get `is_overlapping=True`
  and a halved association confidence rather than a false-confident guess.
- **Voice emotion is "most recent if plausible," not verified per-speaker** —
  `bonbon_affective_ai`'s voice analyzer is itself unattributed
  (`person_id=""` by its own design).

## ROS2 interface

| Topic/Service | Type | Direction |
|---|---|---|
| `/speech/transcription` | `SpeechTranscription` | sub |
| `/bonbon/affective/voice_emotion` | `VoiceEmotion` | sub |
| `/bonbon/persons/tracks` | `PersonTrack` | sub |
| `/bonbon/safety/state` | `SafetyState` | sub |
| `/bonbon/speaker/turns` | `SpeakerTurn` | pub |
| `~/health_check` | `bonbon_srvs/HealthCheck` | service |

## Configuration

See [`config/speaker_intelligence_params.yaml`](../ros2_ws/src/bonbon_speaker_intelligence/bonbon_speaker_intelligence/config/speaker_intelligence_params.yaml).
Key knobs: `doa_tolerance_deg` (20.0), `recency_window_sec` (8.0),
`voice_emotion_max_age_sec` (3.0), `max_bearing_delta_deg` (25.0).

## Example

A 2-speaker overlapping utterance: "hello there" (0.0–1.5 s) then "hi back"
(1.5–3.0 s). Word timestamps let `transcript_segment_mapper` correctly split
the whole-utterance transcript across both segments rather than attributing
all the words to the first speaker.

## Failure modes

| Failure | Behavior |
|---|---|
| Diarizer disabled/timed out | Falls back to one synthetic segment spanning the whole utterance, attributed to the primary speaker. |
| No visible `PersonTrack` matches the DOA | `person_track_id=""`, `is_off_camera=true` — never guessed. |
| Overlapping speakers, no word timestamps | Transcript left empty for all segments (honest gap, not misattribution). |
| `VoiceEmotion` stale | `voice_emotion=""`, never a stale guess. |

## Tests

76 tests across 5 core modules. Plus 5 of the 25 cross-package scenarios
(two-speaker diarization, speaker linked to visible person, off-camera
speaker, overlapping speech, noisy audio).

## Performance tuning

Target: **speaker turn update ≤ 1000 ms** (the decision/fusion logic only;
STT/diarization latency belongs to `bonbon_speech`). Measured p99 ≈ 4.4 ms
for a 2-speaker turn — see [performance_tuning.md](performance_tuning.md).

## Troubleshooting

- **Speaker identity keeps resetting** — `doa_tolerance_deg`/
  `recency_window_sec` too tight for your room's actual mic array noise.
- **Turns never linked to a visible person** — confirm
  `bonbon_multi_person_tracker` is running and the DOA convention matches
  `bonbon_spatial`'s bearing sign convention (positive = robot's left).
- **All overlapping-speech transcripts come back empty** — this is by
  design when the STT backend doesn't return word timestamps; check
  `bonbon_speech`'s STT config for `word_timestamps`.
