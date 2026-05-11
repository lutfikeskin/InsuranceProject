"""
Tests for core/variant_tracker.py.

Locks the behavior introduced by commit 8d9c695 (audit Phase 2.2b):
the five swallow-and-log try/excepts were collapsed into a single
_load_state helper, and the inner false-"known" fallback in
check_and_record was removed so real bugs surface.
"""

import json
import pytest

from core.variant_tracker import VariantTracker, _load_state


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "variants.json")


@pytest.fixture
def tracker(db_path):
    return VariantTracker(path=db_path)


# ---------- _load_state ------------------------------------------------------


def test_load_state_handles_missing_file(tmp_path):
    state = _load_state(str(tmp_path / "does_not_exist.json"))
    assert state == {"known_variants": {}, "candidates": []}


def test_load_state_handles_corrupt_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json", encoding="utf-8")

    state = _load_state(str(p))
    assert state == {"known_variants": {}, "candidates": []}


def test_load_state_handles_non_dict_root(tmp_path):
    p = tmp_path / "list_root.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")

    state = _load_state(str(p))
    assert state == {"known_variants": {}, "candidates": []}


def test_load_state_fills_in_missing_keys(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"known_variants": {"v1": {}}}), encoding="utf-8")

    state = _load_state(str(p))
    assert state["known_variants"] == {"v1": {}}
    assert state["candidates"] == []


# ---------- check_and_record -------------------------------------------------


def _record(tracker, **overrides):
    defaults = dict(
        fingerprint="fp-1",
        carrier_name="Progressive",
        document_type="declarations_page",
        policy_type="personal_auto",
        page_count=3,
        file_hash="h-1",
    )
    defaults.update(overrides)
    return tracker.check_and_record(**defaults)


def test_first_sighting_is_new_carrier(tracker):
    result = _record(tracker)
    assert result["status"] == "new_carrier"
    assert tracker.get_candidates(min_seen=1), "expected a candidate row to be recorded"


def test_second_sighting_of_same_variant_increments_seen_count(tracker):
    _record(tracker)
    _record(tracker)

    candidates = tracker.get_candidates()
    assert len(candidates) == 1
    assert candidates[0]["seen_count"] == 2


def test_new_layout_variant_same_carrier_same_policy_type(tracker):
    """A different fingerprint for the same (carrier, policy_type) is new_layout_variant."""
    _record(tracker, fingerprint="fp-1")
    # Manually promote so the next record sees it under known_variants.
    candidate = tracker.get_candidates()[0]
    tracker.promote_to_known(candidate["variant_key"], golden_path="golden/a.json")

    result = _record(tracker, fingerprint="fp-2")
    assert result["status"] == "new_layout_variant"


def test_new_policy_type_variant_same_carrier_different_policy_type(tracker):
    _record(tracker, fingerprint="fp-1", policy_type="personal_auto")
    candidate = tracker.get_candidates()[0]
    tracker.promote_to_known(candidate["variant_key"], golden_path="golden/a.json")

    result = _record(tracker, fingerprint="fp-3", policy_type="commercial_auto")
    assert result["status"] == "new_policy_type_variant"


def test_known_variant_returns_known(tracker):
    _record(tracker)
    candidate = tracker.get_candidates()[0]
    tracker.promote_to_known(candidate["variant_key"], golden_path="golden/a.json")

    result = _record(tracker)
    assert result["status"] == "known"


# ---------- promote_to_known -------------------------------------------------


def test_promote_to_known_moves_candidate(tracker):
    _record(tracker)
    candidate = tracker.get_candidates()[0]
    variant_key = candidate["variant_key"]

    tracker.promote_to_known(variant_key, golden_path="golden/a.json")

    assert tracker.get_known_variants().get(variant_key) is not None
    assert tracker.get_known_variants()[variant_key]["golden_path"] == "golden/a.json"
    assert all(c["variant_key"] != variant_key for c in tracker.get_candidates())


def test_promote_to_known_with_unknown_key_is_noop(tracker):
    # Should not raise, should not corrupt state.
    tracker.promote_to_known("does-not-exist", golden_path="golden/x.json")
    assert tracker.get_known_variants() == {}
    assert tracker.get_candidates() == []


# ---------- persistence ------------------------------------------------------


def test_state_persists_across_tracker_instances(db_path):
    t1 = VariantTracker(path=db_path)
    _record(t1)

    t2 = VariantTracker(path=db_path)
    assert len(t2.get_candidates()) == 1


def test_filter_get_candidates_by_min_seen(tracker):
    _record(tracker, fingerprint="fp-1")
    _record(tracker, fingerprint="fp-1")
    _record(tracker, fingerprint="fp-2")

    assert len(tracker.get_candidates(min_seen=1)) == 2
    assert len(tracker.get_candidates(min_seen=2)) == 1
