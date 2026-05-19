"""
Tests for modules/extraction/extraction_local_cache.py.

The extraction cache had four near-identical try/except blocks that all
swallowed exceptions and returned None or {}. Commit df43a66 (audit Phase
2.2a) narrowed each catch to (OSError, json.JSONDecodeError). These tests
lock in the new contract:

  - Round-trip get/save with normal data.
  - Cache miss when the file is absent.
  - Corrupt JSON on disk → log + return None (recoverable).
  - Non-serializable payload → raises TypeError (real bug, must surface).
  - get_gemini_cache_meta / save_gemini_cache_meta round-trip.
  - mark_non_cacheable / is_marked_non_cacheable lifecycle.
  - extraction_result_cache_scope helper.
"""

import json
import pytest

from modules.extraction.extraction_local_cache import (
    ExtractionCache,
    extraction_result_cache_scope,
)


@pytest.fixture
def cache(tmp_path):
    """Fresh ExtractionCache rooted in a per-test temp directory."""
    return ExtractionCache(cache_dir=str(tmp_path))


def test_scope_helper():
    assert extraction_result_cache_scope(None) == "auto"
    assert extraction_result_cache_scope("") == "auto"
    assert extraction_result_cache_scope("personal_auto") == "manual_personal_auto"
    assert extraction_result_cache_scope("commercial_auto") == "manual_commercial_auto"


def test_save_and_get_roundtrip(cache):
    payload = {"classification": {"document_type": "coi"}, "policies": [{"n": 1}]}
    cache.save("hash-abc", payload)

    got = cache.get("hash-abc")
    assert got == payload


def test_save_and_get_respect_cache_scope(cache):
    """auto-scope and manual-scope entries must not collide for the same hash."""
    auto_payload = {"scope": "auto"}
    manual_payload = {"scope": "manual"}

    cache.save("hash-xyz", auto_payload, cache_scope="auto")
    cache.save("hash-xyz", manual_payload, cache_scope="manual_personal_auto")

    assert cache.get("hash-xyz", cache_scope="auto") == auto_payload
    assert cache.get("hash-xyz", cache_scope="manual_personal_auto") == manual_payload


def test_get_returns_none_when_missing(cache):
    assert cache.get("never-seen-hash") is None


def test_get_returns_none_on_corrupt_file(cache, tmp_path):
    """A corrupt cache file must log and miss-through, not crash."""
    # Save a real entry to get its on-disk path, then corrupt it.
    payload = {"ok": True}
    cache.save("corrupt-hash", payload)

    # Reach into the cache dir and break the file.
    files = list(tmp_path.glob("*corrupt-hash*.json"))
    assert files, "expected the save() call to produce a file"
    files[0].write_text("{ this is not valid json", encoding="utf-8")

    assert cache.get("corrupt-hash") is None


def test_save_raises_on_non_serializable_payload(cache):
    """Programming bugs must surface — non-serializable values are not OSError."""
    class NotSerializable:
        pass

    with pytest.raises(TypeError):
        cache.save("bad-hash", {"thing": NotSerializable()})


def test_gemini_cache_meta_roundtrip(cache):
    cache.save_gemini_cache_meta(
        file_hash="abc123",
        cache_name="caches/test",
        expire_time="2026-12-31T00:00:00Z",
        model="gemini-3.1-flash-lite",
    )

    meta = cache.get_gemini_cache_meta("abc123")
    assert meta is not None
    assert meta["cache_name"] == "caches/test"
    assert meta["expire_time"] == "2026-12-31T00:00:00Z"
    assert meta["model"] == "gemini-3.1-flash-lite"


def test_gemini_cache_meta_missing_returns_none(cache):
    assert cache.get_gemini_cache_meta("never-recorded") is None


def test_gemini_cache_meta_survives_corrupt_index(cache, tmp_path):
    """A corrupt index.json must not block a fresh save."""
    cache.save_gemini_cache_meta("h1", "cn1", "2026-01-01T00:00:00Z", "m1")

    # Corrupt the index file.
    (tmp_path / "index.json").write_text("{ broken", encoding="utf-8")

    # Read returns None — no crash.
    assert cache.get_gemini_cache_meta("h1") is None

    # Subsequent save reseeds the index from empty state and persists cleanly.
    cache.save_gemini_cache_meta("h2", "cn2", "2027-01-01T00:00:00Z", "m2")
    assert cache.get_gemini_cache_meta("h2") is not None
    # h1 is gone because the corrupt index was discarded — that is the
    # documented "treat as empty state" recovery contract.
    assert cache.get_gemini_cache_meta("h1") is None


def test_non_cacheable_marker_lifecycle(cache):
    assert cache.is_marked_non_cacheable("h-not-yet") is False

    cache.mark_non_cacheable("h-not-yet", reason="document_too_small_for_cache")

    assert cache.is_marked_non_cacheable("h-not-yet") is True
    # An unrelated hash is unaffected.
    assert cache.is_marked_non_cacheable("h-other") is False


def test_is_marked_non_cacheable_returns_false_on_corrupt_index(cache, tmp_path):
    cache.mark_non_cacheable("h1", reason="probe")
    (tmp_path / "index.json").write_text("not json", encoding="utf-8")

    # Corrupt index is recoverable — treated as "not marked".
    assert cache.is_marked_non_cacheable("h1") is False


def test_cache_dir_is_created_lazily(tmp_path):
    """ExtractionCache should make the cache directory if absent."""
    target = tmp_path / "deeper" / "nested"
    cache = ExtractionCache(cache_dir=str(target))
    assert target.exists()
    # And the index file is initialized.
    assert (target / "index.json").exists()
    # The fresh index is a valid empty JSON object.
    assert json.loads((target / "index.json").read_text()) == {}
