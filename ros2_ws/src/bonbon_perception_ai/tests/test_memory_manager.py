"""
Tests for MemoryManager (FAISS vector store + SQLite structured store).

Covers: scene recording, similarity search, person memory,
GDPR forget, privacy anonymization, TTL purge.
"""

import math
import time

import pytest
from bonbon_perception_ai.config.perception_config import MemoryConfig
from bonbon_perception_ai.memory.memory_manager import MemoryManager
from bonbon_perception_ai.memory.vector_store import SceneEmbedding
from bonbon_perception_ai.understanding.intent_engine import IntentSlot, UserIntent
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot


def _cfg(**kw) -> MemoryConfig:
    defaults = dict(
        db_path="",  # in-memory SQLite
        vector_dim=32,
        max_episodes=1000,
        episode_ttl_days=7.0,
        privacy_anonymize_persons=False,
        privacy_store_faces=False,
    )
    defaults.update(kw)
    return MemoryConfig(**defaults)


def _snap(
    scene_id=None,
    activity="idle",
    persons=None,
    objects=None,
    confidence=0.9,
    uncertainty="LOW",
) -> SceneSnapshot:
    import uuid

    return SceneSnapshot(
        scene_id=scene_id or str(uuid.uuid4()),
        timestamp=time.monotonic(),
        confidence=confidence,
        uncertainty_level=uncertainty,
        present_object_classes=objects or [],
        present_person_ids=persons or [],
        dominant_activity=activity,
        activity_label=activity,
        spatial_context="open_space",
        human_proximity_m=math.inf,
        is_crowded=False,
        stale_modalities=[],
        description=f"activity={activity}",
    )


def _intent(cls="order_item", text="coffee please", speaker="spk1", slots=None) -> UserIntent:
    return UserIntent(
        intent_class=cls,
        confidence=0.9,
        speaker_id=speaker,
        raw_text=text,
        slots=slots or [IntentSlot("item", "coffee", 0.9)],
        speech_confidence=0.85,
    )


@pytest.fixture
def mem():
    m = MemoryManager(_cfg())
    m.open()
    yield m
    m.close()


# ── Scene recording ───────────────────────────────────────────────────────────


class TestSceneRecording:
    def test_record_scene_increments_count(self, mem):
        mem.record_scene(_snap())
        mem.record_scene(_snap())
        assert mem.episode_count == 2

    def test_scene_stored_in_vector_store(self, mem):
        snap = _snap(activity="navigating")
        mem.record_scene(snap)
        results = mem.recall_similar_scenes(snap, k=1)
        assert len(results) == 1

    def test_similar_scenes_returned(self, mem):
        for activity in ["idle", "idle", "navigating"]:
            mem.record_scene(_snap(activity=activity))
        query = _snap(activity="idle")
        results = mem.recall_similar_scenes(query, k=2)
        assert len(results) == 2
        # idle scenes should rank higher than navigating
        activities = [r.snapshot.dominant_activity for r in results]
        assert activities[0] == "idle"

    def test_empty_recall_returns_empty_list(self, mem):
        assert mem.recall_similar_scenes(_snap()) == []

    def test_known_objects_updated(self, mem):
        snap = _snap(objects=["cup", "bottle"])
        mem.record_scene(snap)
        objs = mem.list_known_objects()
        class_names = {o["class_name"] for o in objs}
        assert "cup" in class_names
        assert "bottle" in class_names


# ── Person memory ─────────────────────────────────────────────────────────────


class TestPersonMemory:
    def test_record_person_makes_known(self, mem):
        mem.record_person("person_01")
        assert mem.is_known_person("person_01")

    def test_unknown_person_not_known(self, mem):
        assert not mem.is_known_person("ghost_99")

    def test_interaction_logged(self, mem):
        mem.record_interaction("person_01", _intent())
        history = mem.get_person_history("person_01")
        assert history is not None
        assert len(history["interactions"]) == 1

    def test_multiple_interactions(self, mem):
        for _ in range(3):
            mem.record_interaction("person_01", _intent())
        history = mem.get_person_history("person_01")
        assert len(history["interactions"]) == 3

    def test_interaction_count_tracked(self, mem):
        for _ in range(4):
            mem.record_interaction("person_01", _intent())
        info = mem.get_person_history("person_01")["person"]
        assert info["interaction_count"] >= 4


# ── GDPR forget ───────────────────────────────────────────────────────────────


class TestGDPRForget:
    def test_forget_removes_person(self, mem):
        mem.record_interaction("person_01", _intent())
        assert mem.is_known_person("person_01")
        mem.forget_person("person_01")
        assert not mem.is_known_person("person_01")

    def test_forget_removes_interactions(self, mem):
        mem.record_interaction("person_01", _intent())
        mem.forget_person("person_01")
        # After forget, no history
        history = mem.get_person_history("person_01")
        assert history is None

    def test_forget_unknown_person_no_error(self, mem):
        mem.forget_person("nonexistent_999")  # must not raise

    def test_forget_does_not_affect_other_persons(self, mem):
        mem.record_interaction("person_A", _intent(speaker="person_A"))
        mem.record_interaction("person_B", _intent(speaker="person_B"))
        mem.forget_person("person_A")
        assert mem.is_known_person("person_B")


# ── Privacy anonymization ─────────────────────────────────────────────────────


class TestPrivacyAnonymization:
    def test_anonymized_ids_stored_differently(self):
        m1 = MemoryManager(_cfg(privacy_anonymize_persons=True))
        m1.open()
        m1.record_person("real_person_id")
        persons = m1.list_known_persons()
        m1.close()
        # The stored ID should be an anon hash, not the original
        stored_ids = {p["id"] for p in persons}
        assert "real_person_id" not in stored_ids
        assert any(p_id.startswith("anon_") for p_id in stored_ids)

    def test_non_anonymized_stores_real_id(self):
        m2 = MemoryManager(_cfg(privacy_anonymize_persons=False))
        m2.open()
        m2.record_person("real_person_id")
        persons = m2.list_known_persons()
        m2.close()
        stored_ids = {p["id"] for p in persons}
        assert "real_person_id" in stored_ids

    def test_face_id_not_stored_by_default(self):
        m = MemoryManager(_cfg(privacy_store_faces=False))
        m.open()
        m.record_person("p1", face_id="face_abc")
        history = m.get_person_history("p1")
        m.close()
        assert history is not None
        assert history["person"]["face_id"] == ""

    def test_face_id_stored_when_enabled(self):
        m = MemoryManager(_cfg(privacy_store_faces=True))
        m.open()
        m.record_person("p1", face_id="face_abc")
        history = m.get_person_history("p1")
        m.close()
        assert history["person"]["face_id"] == "face_abc"


# ── TTL purge ─────────────────────────────────────────────────────────────────


class TestTTLPurge:
    def test_purge_removes_old_episodes(self):
        m = MemoryManager(_cfg(episode_ttl_days=0.0001))  # ~8 seconds
        m.open()
        _snap()
        # Manually insert a very old episode via structured store
        import time as _t

        m._structured._conn.execute(
            "INSERT INTO scene_episodes(id, timestamp, dominant_activity, "
            "person_count, object_classes_json, description, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("old_ep", _t.time() - 1000, "idle", 0, "[]", "old", 0.5),
        )
        deleted = m.purge_old_data()
        m.close()
        assert deleted >= 1

    def test_fresh_episodes_not_purged(self):
        m = MemoryManager(_cfg(episode_ttl_days=7.0))
        m.open()
        m.record_scene(_snap())
        deleted = m.purge_old_data()
        m.close()
        assert deleted == 0


# ── Capacity / eviction ───────────────────────────────────────────────────────


class TestCapacityEviction:
    def test_max_episodes_respected(self):
        m = MemoryManager(_cfg(max_episodes=10))
        m.open()
        for _ in range(15):
            m.record_scene(_snap())
        assert m.episode_count <= 10 + 1  # eviction rounds down
        m.close()


# ── Vector embedding ──────────────────────────────────────────────────────────


class TestSceneEmbedding:
    def test_embedding_shape(self):
        snap = _snap()
        v = SceneEmbedding.encode(snap)
        assert v.shape == (32,)
        assert v.dtype.kind == "f"

    def test_crowded_bit_set(self):
        import uuid

        snap = SceneSnapshot(
            scene_id=str(uuid.uuid4()),
            timestamp=time.monotonic(),
            confidence=0.9,
            uncertainty_level="LOW",
            present_object_classes=[],
            present_person_ids=["p1", "p2", "p3"],
            dominant_activity="crowded",
            activity_label="crowded",
            spatial_context="crowded",
            human_proximity_m=0.8,
            is_crowded=True,
            stale_modalities=[],
            description="",
        )
        v = SceneEmbedding.encode(snap)
        assert v[3] == 1.0  # is_crowded bit

    def test_normalise_unit_length(self):
        import numpy as np

        snap = _snap()
        v = SceneEmbedding.encode(snap)
        n = SceneEmbedding.normalise(v)
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-5

    def test_zero_vector_normalise_no_divide_by_zero(self):
        import numpy as np

        v = SceneEmbedding.normalise(np.zeros(32, dtype=np.float32))
        assert not any(np.isnan(v))
