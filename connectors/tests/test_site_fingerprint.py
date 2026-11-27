"""Fingerprint diff per change kind, the tags a job uses and the dependency index (#166)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from crosscut_connectors.dependency_index import (
    DependencyView,
    confirm,
    load_index,
    on_publish,
    register,
    stale_items,
)
from crosscut_connectors.site_fingerprint import (
    diff_fingerprints,
    job_tag_ids,
    reason_text,
    tag_fingerprints,
)

SITE: dict[str, Any] = {
    "schema_version": 1, "site": {"name": "t"},
    "sources": [{"id": "s1", "type": "opcua"}],
    "tags": [
        {"id": "a", "source": "s1", "address": "ns=2;s=A", "unit": "t/h",
         "range": {"low": 0, "high": 9}},
        {"id": "b", "source": "s1", "address": "ns=2;s=B", "unit": "%"},
        {"id": "c", "source": "s1", "address": "ns=2;s=C", "unit": "%"},
    ],
    "loops": [{"id": "L1", "pv": "a", "sp": "b", "out": "c"}],
}


def _changed(change: Any) -> dict[str, Any]:
    """A copy of SITE after ``change``."""
    site = copy.deepcopy(SITE)
    change(site)
    return site


def _kinds(site: dict[str, Any], tags: list[str] | None = None) -> list[tuple[str, str]]:
    """``(tag, kind)`` of the diff of SITE's tags a, b against ``site``."""
    base = tag_fingerprints(SITE)
    wanted = {t: base[t] for t in (tags or ["a", "b"])}
    return [(r["tag"], r["kind"]) for r in diff_fingerprints(wanted, tag_fingerprints(site))]


def test_unchanged_catalogue_has_no_reasons() -> None:
    assert _kinds(copy.deepcopy(SITE)) == []


def test_removed_tag() -> None:
    site = _changed(lambda s: s["tags"].pop(0))
    assert ("a", "removed") in _kinds(site)


def test_remapped_address() -> None:
    site = _changed(lambda s: s["tags"][0].update(address="ns=2;s=NEW"))
    assert _kinds(site) == [("a", "remapped")]


def test_remapped_source() -> None:
    site = _changed(lambda s: s["tags"][1].update(source="s2"))
    assert _kinds(site) == [("b", "remapped")]


def test_unit_changed() -> None:
    site = _changed(lambda s: s["tags"][1].update(unit="kPa"))
    assert _kinds(site) == [("b", "unit_changed")]


def test_role_moved() -> None:
    site = _changed(lambda s: s["loops"][0].update(pv="b", sp="a"))
    assert sorted(_kinds(site)) == [("a", "role_moved"), ("b", "role_moved")]


def test_range_changed() -> None:
    site = _changed(lambda s: s["tags"][0].update(range={"low": 0, "high": 12}))
    assert _kinds(site) == [("a", "range_changed")]


def test_unrelated_tag_change_is_not_a_reason() -> None:
    site = _changed(lambda s: s["tags"][2].update(unit="mA"))
    assert _kinds(site) == []


def test_rebound_when_the_job_uses_a_tag_it_was_not_built_on() -> None:
    base = tag_fingerprints(SITE)
    found = diff_fingerprints({"a": base["a"]}, base, used_now=["a", "b"])
    assert [(r["tag"], r["kind"]) for r in found] == [("b", "rebound")]
    assert reason_text(found).startswith("stale_dependency: b rebound")


def test_job_tag_ids_by_kind() -> None:
    kpi = {"id": "j", "kind": "loop_kpi", "loops": ["L1"]}
    assert job_tag_ids(kpi, SITE) == {"a", "b", "c"}
    assert job_tag_ids({"kind": "anomaly_scan", "tags": ["a"]}, SITE) == {"a"}
    assert job_tag_ids({"kind": "loop_kpi", "loops": ["nope"]}, SITE) == set()


def _root(tmp_path: Path) -> Path:
    """A data root with the published SITE and one loop job deployed."""
    (tmp_path / "_site").mkdir()
    (tmp_path / "_site" / "site.json").write_text(json.dumps(SITE), encoding="utf-8")
    (tmp_path / "_runtime").mkdir()
    jobs = {"schema_version": 1, "jobs": [{"id": "j", "kind": "loop_kpi", "loops": ["L1"]}]}
    (tmp_path / "_runtime" / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    (tmp_path / "_anomaly").mkdir()
    config = json.dumps({"tags": ["a", "b"]})
    (tmp_path / "_anomaly" / "m.json").write_text(config, encoding="utf-8")
    return tmp_path


def test_publish_baselines_on_the_previous_catalogue_and_marks_stale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    new = _changed(lambda s: s["tags"][0].update(unit="kg/h"))
    stale = on_publish(root, SITE, new, 2)
    assert set(stale) == {"job:j", "anomaly:m"}
    assert stale["anomaly:m"]["since_version"] == 2
    items = {i["key"]: i for i in stale_items(root, new)}
    assert items["anomaly:m"]["needs_relearn"] and "relearn" in items["anomaly:m"]["actions"]
    assert items["job:j"]["actions"] == ["edit_config", "reconfirm"]
    assert items["job:j"]["reasons"][0]["kind"] == "unit_changed"


def test_register_after_relearn_clears_and_confirm_is_recorded(tmp_path: Path) -> None:
    root = _root(tmp_path)
    new = _changed(lambda s: s["tags"][0].update(unit="kg/h"))
    on_publish(root, SITE, new, 2)
    register(root, new, {"kind": "anomaly", "id": "m", "tags": ["a", "b"]}, 2)
    assert [i["key"] for i in stale_items(root, new)] == ["job:j"]
    entry = confirm(root, new, "job:j", 2, "eng1", "unit change is cosmetic")
    assert entry["confirmed"]["by"] == "eng1"
    assert stale_items(root, new) == []
    assert load_index(root)["items"]["job:j"]["confirmed"]["note"].startswith("unit")


def test_view_uses_memory_baseline_without_writing_the_index(tmp_path: Path) -> None:
    root = _root(tmp_path)
    memory: dict[str, Any] = {}
    dependent = {"kind": "job", "id": "j", "tags": ["a", "b", "c"]}
    assert DependencyView(root, SITE, memory).reasons("job:j", dependent) == []
    new = _changed(lambda s: s["tags"][0].update(address="x"))
    assert DependencyView(root, new, memory).reasons("job:j", dependent)[0]["kind"] == "remapped"
    assert not (root / "_site" / "dependencies.json").exists()
