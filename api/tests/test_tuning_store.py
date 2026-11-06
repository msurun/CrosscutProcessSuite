"""Tests of the tuning proposal store: atomic writes, locking, forward-only statuses (ADR 014)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from crosscut_api import tuning_store
from crosscut_api.tuning_store import (
    ProposalNotFound,
    ProposalStore,
    Record,
    StoreBusy,
    TransitionRefused,
    check_change,
    merged_view,
    transition_allowed,
)
from crosscut_loops.tuning_proposal import (
    ProposalRequest,
    Stamp,
    WindowSpec,
    build_proposal,
)
from crosscut_loops.tuning_report import report_from_model
from crosscut_loops.tuning_rules import FopdtModel

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
TARGETS = {"gain": "FIC101.KP", "ti": "FIC101.TI"}
APPLIED = {
    "from_read": {"FIC101.KP": 0.5, "FIC101.TI": 200.0},
    "to_read": {"FIC101.KP": 1.25, "FIC101.TI": 100.0},
    "t": "2026-11-06T12:05:00Z",
    "approver": "eng2",
}


def make_record(offset_min: int = 0) -> Record:
    """A valid draft record built the way the route builds it."""
    report = report_from_model("FIC-101", FopdtModel(2.0, 100.0, 10.0))
    window = WindowSpec(NOW - timedelta(hours=2), NOW - timedelta(hours=1), "ds1")
    request = ProposalRequest("FIC-101", "siemens_pid_compact", "simc", TARGETS, window)
    stamp = Stamp(str(uuid.uuid4()), "eng1", NOW + timedelta(minutes=offset_min))
    return build_proposal(report, request, {"gain": 0.5, "ti": 200.0}, stamp)


@pytest.fixture
def store(tmp_path: Path) -> ProposalStore:
    """A store over an empty data root."""
    return ProposalStore(tmp_path)


def queued(store: ProposalStore) -> Record:
    """Store a draft and move it to queued."""
    record = store.create(make_record())
    with store.exclusive(record["id"]) as locked:
        return locked.save({**record, "status": "queued", "gateway_key": "a" * 64})


def test_create_and_get_round_trip(store: ProposalStore) -> None:
    record = store.create(make_record())
    assert store.get(record["id"]) == record
    assert list(store.dir.glob("*.tmp")) == [] and list(store.dir.glob("*.lock")) == []


@pytest.mark.parametrize("bad", ["x", "../etc", "ABCDEF12-0000-4000-8000-000000000000", ""])
def test_ids_that_are_not_lowercase_uuids_are_not_found(store: ProposalStore, bad: str) -> None:
    with pytest.raises(ProposalNotFound):
        store.get(bad)
    with pytest.raises(ProposalNotFound):
        store.path(bad)


def test_unknown_id_is_not_found(store: ProposalStore) -> None:
    with pytest.raises(ProposalNotFound):
        store.get(str(uuid.uuid4()))
    with pytest.raises(ProposalNotFound), store.exclusive(str(uuid.uuid4())):
        pass


def test_create_refuses_a_duplicate_a_non_draft_and_an_invalid_record(store: ProposalStore) -> None:
    record = store.create(make_record())
    with pytest.raises(TransitionRefused):
        store.create(record)
    with pytest.raises(TransitionRefused):
        store.create({**make_record(), "status": "queued"})
    with pytest.raises(TransitionRefused):
        store.create({**make_record(), "items": []})
    assert len(store.list_records()) == 1


@pytest.mark.parametrize(
    ("old", "new", "allowed"),
    [
        ("draft", "queued", True),
        ("draft", "draft", True),
        ("draft", "refused:loop_busy", True),
        ("draft", "applied", False),
        ("queued", "applied", True),
        ("queued", "rejected", True),
        ("queued", "expired", True),
        ("queued", "refused:from_mismatch", True),
        ("queued", "draft", False),
        ("applied", "applied", True),
        ("applied", "queued", False),
        ("applied", "rejected", False),
        ("rejected", "applied", False),
        ("rejected", "rejected", False),
        ("expired", "queued", False),
        ("refused:x", "queued", False),
        ("refused:x", "refused:y", False),
    ],
)
def test_transition_table(old: str, new: str, allowed: bool) -> None:
    assert transition_allowed(old, new) is allowed


def test_content_is_frozen_after_creation(store: ProposalStore) -> None:
    record = queued(store)
    changed = {**record, "items": [{**record["items"][0], "to": 9.0}, *record["items"][1:]]}
    with pytest.raises(TransitionRefused), store.exclusive(record["id"]) as locked:
        locked.save(changed)
    with pytest.raises(TransitionRefused), store.exclusive(record["id"]) as locked:
        locked.save({**record, "created_by": "mallory"})
    assert store.get(record["id"]) == record


def test_terminal_states_are_never_overwritten(store: ProposalStore) -> None:
    record = queued(store)
    with store.exclusive(record["id"]) as locked:
        locked.save({**record, "status": "rejected"})
    for status in ("queued", "applied", "expired", "refused:late", "rejected"):
        with pytest.raises(TransitionRefused), store.exclusive(record["id"]) as locked:
            locked.save({**record, "status": status})
    assert store.get(record["id"])["status"] == "rejected"


def test_applied_block_is_frozen_but_the_invalid_flag_can_be_set_once(store: ProposalStore) -> None:
    record = queued(store)
    with store.exclusive(record["id"]) as locked:
        applied = locked.save({**record, "status": "applied", "applied": APPLIED})
    flagged = {**APPLIED, "invalid": "param_changed_externally"}
    with store.exclusive(record["id"]) as locked:
        locked.save({**applied, "applied": flagged})
    for bad in (None, {**flagged, "approver": "x"}, {**APPLIED}):
        with pytest.raises(TransitionRefused), store.exclusive(record["id"]) as locked:
            locked.save({**applied, "applied": bad})
    assert store.get(record["id"])["applied"] == flagged


def test_schema_invalid_record_is_refused_and_the_file_is_kept(store: ProposalStore) -> None:
    record = queued(store)
    with pytest.raises(TransitionRefused), store.exclusive(record["id"]) as locked:
        locked.save({**record, "status": "applied", "applied": {"from_read": {}}})
    assert store.get(record["id"]) == record


def test_a_failing_replace_leaves_the_old_file_and_no_temp_file(
    store: ProposalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = queued(store)

    def broken(_src: Any, _dst: Any) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError), store.exclusive(record["id"]) as locked:
        locked.save({**record, "status": "rejected"})
    monkeypatch.undo()
    assert store.get(record["id"]) == record
    assert list(store.dir.glob("*.tmp")) == []


def test_concurrent_apply_has_exactly_one_winner(store: ProposalStore) -> None:
    record = queued(store)
    outcomes: list[str] = []

    def apply(approver: str) -> None:
        try:
            with store.exclusive(record["id"]) as locked:
                time.sleep(0.01)
                applied = {**APPLIED, "approver": approver}
                locked.save({**locked.record, "status": "applied", "applied": applied})
            outcomes.append(approver)
        except TransitionRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=apply, args=(f"eng{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert outcomes.count("refused") == 5 and len(outcomes) == 6
    assert store.get(record["id"])["applied"]["approver"] in outcomes


def test_lock_is_released_after_an_error_and_a_busy_lock_times_out(
    store: ProposalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = queued(store)
    with pytest.raises(RuntimeError), store.exclusive(record["id"]):
        raise RuntimeError("boom")
    assert list(store.dir.glob("*.lock")) == []
    monkeypatch.setattr(tuning_store, "LOCK_TIMEOUT_S", 0.05)
    with store.exclusive(record["id"]):
        lock_file = store.path(record["id"]).with_suffix(".lock")
        assert lock_file.exists()
        with pytest.raises(StoreBusy), tuning_store._file_lock(lock_file):
            pass


def test_a_stale_lock_file_is_dropped(
    store: ProposalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = queued(store)
    lock_file = store.path(record["id"]).with_suffix(".lock")
    lock_file.write_text("", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock_file, (old, old))
    with store.exclusive(record["id"]) as locked:
        locked.save({**record, "status": "rejected"})
    assert store.get(record["id"])["status"] == "rejected"


def test_list_skips_review_files_and_corrupt_files_and_sorts_newest_first(
    store: ProposalStore,
) -> None:
    older = store.create(make_record(0))
    newer = store.create(make_record(5))
    (store.dir / f"{older['id']}.review.json").write_text("{}", encoding="utf-8")
    (store.dir / "broken.json").write_text("{not json", encoding="utf-8")
    assert [r["id"] for r in store.list_records()] == [newer["id"], older["id"]]
    assert ProposalStore(store.dir.parent / "nothing").list_records() == []


def test_review_file_is_read_and_merged_into_the_applied_record(store: ProposalStore) -> None:
    record = queued(store)
    assert store.read_review(record["id"]) is None
    with store.exclusive(record["id"]) as locked:
        applied = locked.save({**record, "status": "applied", "applied": APPLIED})
    review = {"verdict": "worse", "t": "2026-11-06T14:00:00Z", "reasons": ["error_std_up"]}
    document = {"proposal_id": record["id"], "version": 1, "final": True,
                "status": "reviewed:worse", "review": review}  # fmt: skip
    store.review_path(record["id"]).write_text(json.dumps(document), encoding="utf-8")
    view = merged_view(applied, store.read_review(record["id"]))
    assert view["status"] == "reviewed:worse" and view["review"] == review
    assert view["rollback_recommended"] is True
    assert store.get(record["id"])["status"] == "applied"


def test_a_review_never_changes_a_record_that_is_not_applied(store: ProposalStore) -> None:
    record = queued(store)
    stray = {"status": "reviewed:improved", "review": {"verdict": "improved"}}
    view = merged_view(record, stray)
    assert view["status"] == "queued" and view["review"] is None
    assert view["rollback_recommended"] is False


def test_unreadable_review_file_counts_as_no_review(store: ProposalStore) -> None:
    record = queued(store)
    store.review_path(record["id"]).write_text("{oops", encoding="utf-8")
    assert store.read_review(record["id"]) is None


def test_check_change_allows_a_late_gateway_key_on_a_draft() -> None:
    old = make_record()
    check_change(old, {**old, "gateway_key": "b" * 64})
    check_change(old, {**old, "status": "queued", "gateway_key": "b" * 64})
