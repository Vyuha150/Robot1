"""
tests/test_filler_player.py
============================
Unit tests for FillerPlayer.
"""

import io
import wave

from bonbon_tts.core.filler_player import FillerClip, FillerPlayer


def _make_wav(duration_sec: float = 0.1) -> bytes:
    n = int(22050 * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class TestFillerClip:
    def test_attrs(self):
        clip = FillerClip("hello", b"data")
        assert clip.name == "hello"
        assert clip.wav_bytes == b"data"


class TestFillerPlayerBuiltin:
    def test_generate_builtin_returns_three_clips(self):
        clips = FillerPlayer.generate_builtin()
        assert len(clips) == 3

    def test_builtin_clips_have_wav_data(self):
        clips = FillerPlayer.generate_builtin()
        for clip in clips:
            assert len(clip.wav_bytes) > 44  # at least a valid WAV header
            assert clip.name != ""

    def test_load_without_dir_uses_builtin(self):
        fp = FillerPlayer(filler_dir="")
        count = fp.load()
        assert count == 3
        assert fp.clip_count == 3


class TestFillerPlayerLoad:
    def test_load_from_dir(self, tmp_path):
        # Write two WAV files
        for name in ["a.wav", "b.wav"]:
            (tmp_path / name).write_bytes(_make_wav())
        fp = FillerPlayer(filler_dir=str(tmp_path))
        count = fp.load()
        assert count == 2
        assert fp.clip_count == 2

    def test_load_ignores_non_wav(self, tmp_path):
        (tmp_path / "clip.wav").write_bytes(_make_wav())
        (tmp_path / "readme.txt").write_text("ignore me")
        fp = FillerPlayer(filler_dir=str(tmp_path))
        fp.load()
        assert fp.clip_count == 1

    def test_load_missing_dir_falls_back_to_builtin(self):
        fp = FillerPlayer(filler_dir="/nonexistent/path/xyz")
        count = fp.load()
        assert count == 3


class TestFillerPlayerMaybePlay:
    def _player(
        self, cooldown_sec=0.0, trigger_queue=1, trigger_latency=0.0, enabled=True
    ) -> FillerPlayer:
        fp = FillerPlayer(
            cooldown_sec=cooldown_sec,
            trigger_queue_depth=trigger_queue,
            trigger_latency_ms=trigger_latency,
            enabled=enabled,
        )
        fp.load()
        return fp

    def test_plays_when_conditions_met(self):
        fp = self._player()
        played = []
        fp.maybe_play(
            speaker_play_fn=lambda wav: played.append(wav),
            queue_depth=2,
            elapsed_ms=500.0,
        )
        assert len(played) == 1

    def test_disabled_no_play(self):
        fp = self._player(enabled=False)
        played = []
        fp.maybe_play(
            speaker_play_fn=lambda wav: played.append(wav),
            queue_depth=5,
            elapsed_ms=1000.0,
        )
        assert len(played) == 0

    def test_queue_too_shallow(self):
        fp = self._player(trigger_queue=3)
        played = []
        fp.maybe_play(
            speaker_play_fn=lambda wav: played.append(wav),
            queue_depth=2,  # below threshold
            elapsed_ms=1000.0,
        )
        assert len(played) == 0

    def test_elapsed_too_short(self):
        fp = self._player(trigger_latency=500.0)
        played = []
        fp.maybe_play(
            speaker_play_fn=lambda wav: played.append(wav),
            queue_depth=5,
            elapsed_ms=100.0,  # below threshold
        )
        assert len(played) == 0

    def test_cooldown_prevents_repeat(self):
        fp = self._player(cooldown_sec=60.0)
        played = []

        def fn(wav):
            return played.append(wav)

        fp.maybe_play(fn, queue_depth=2, elapsed_ms=500.0)
        fp.maybe_play(fn, queue_depth=2, elapsed_ms=500.0)
        # Second call blocked by cooldown
        assert len(played) == 1

    def test_returns_true_when_played(self):
        fp = self._player()
        result = fp.maybe_play(lambda wav: None, queue_depth=2, elapsed_ms=500.0)
        assert result is True

    def test_returns_false_when_not_played(self):
        fp = self._player(enabled=False)
        result = fp.maybe_play(lambda wav: None, queue_depth=2, elapsed_ms=500.0)
        assert result is False

    def test_play_random_ignores_cooldown(self):
        fp = self._player(cooldown_sec=60.0)
        played = []

        def fn(wav):
            return played.append(wav)

        fp.maybe_play(fn, queue_depth=2, elapsed_ms=500.0)
        fp.play_random(fn)  # should bypass cooldown
        assert len(played) == 2

    def test_no_clips_returns_false(self):
        fp = FillerPlayer(enabled=True)
        # Don't call load() → no clips
        result = fp.maybe_play(lambda wav: None, queue_depth=5, elapsed_ms=1000.0)
        assert result is False


class TestFillerPlayerEnabled:
    def test_enabled_toggle(self):
        fp = FillerPlayer()
        fp.load()
        assert fp.enabled is True
        fp.enabled = False
        assert fp.enabled is False
