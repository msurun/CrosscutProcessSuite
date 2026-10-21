"""Tests for the hash-chained advisory audit log."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_supervisor.audit import AckRequest, AuditError, AuditLog, ack

SHA = "a" * 64


def advice(n: int = 0) -> dict[str, Any]:
    """A schema-valid advice record (prev filled by the log)."""
    return {
        "kind": "advice", "advice_id": f"{n:064x}", "t_ns": 5, "target_loop": "FIC1",
        "direction": "hold", "magnitude": None, "activation": 0.5,
        "explanation": [{"rule_id": "r1", "sentence": "s", "strength": 0.5}],
        "inputs": {"x": 1.0}, "gate": {"state": "open", "reasons": []},
        "rulebase_sha256": SHA, "prev_sha256": "",
    }


def req(advice_id: str, decision: str = "accepted", who: str = "op") -> AckRequest:
    """Build an ack request."""
    return AckRequest(advice_id, decision, "ok", who, 7, note="n")


def three(tmp_path: Path) -> AuditLog:
    """A log with three advices."""
    log = AuditLog(tmp_path / "sub" / "log.jsonl")
    for i in range(3):
        log.append(advice(i))
    return log


def test_first_record_empty_prev(tmp_path: Path) -> None:
    assert three(tmp_path).records()[0]["prev_sha256"] == ""


def test_chain_of_three_verifies(tmp_path: Path) -> None:
    rep = three(tmp_path).verify()
    assert rep.ok and rep.records == 3 and rep.first_broken_index is None


def test_edit_byte_breaks_line_2(tmp_path: Path) -> None:
    log = three(tmp_path)
    lines = log.path.read_text(encoding="utf-8").split("\n")
    lines[1] = lines[1].replace("FIC1", "FIC2")
    log.path.write_text("\n".join(lines), encoding="utf-8")
    assert log.verify().first_broken_index == 1


def test_deleted_middle_line_breaks(tmp_path: Path) -> None:
    log = three(tmp_path)
    lines = log.path.read_text(encoding="utf-8").split("\n")
    del lines[1]
    log.path.write_text("\n".join(lines), encoding="utf-8")
    rep = log.verify()
    assert not rep.ok and rep.first_broken_index == 1


def test_garbled_last_line(tmp_path: Path) -> None:
    log = three(tmp_path)
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write('{"record": {"kind"\n')
    rep = log.verify()
    assert not rep.ok and rep.first_broken_index == 3


def test_quick_appends_chain(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "l.jsonl")
    first = log.append(advice(1))
    log.append(advice(1))
    recs = log.records()
    assert len(recs) == 2 and recs[1]["prev_sha256"] == first
    assert log.verify().ok


def test_ack_unknown_advice(tmp_path: Path) -> None:
    with pytest.raises(AuditError):
        ack(three(tmp_path), req("f" * 64))


@pytest.mark.parametrize("kw", [{"decision": "maybe"}, {"who": ""}])
def test_ack_invalid(tmp_path: Path, kw: dict[str, str]) -> None:
    log = three(tmp_path)
    with pytest.raises(AuditError):
        ack(log, req(advice(0)["advice_id"], **kw))


def test_ack_found_and_valid(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[2] / "schemas" / "advisory-record.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    log = three(tmp_path)
    ack(log, req(advice(1)["advice_id"], "deferred"))
    recs = log.records()
    assert recs[-1]["kind"] == "ack"
    for rec in recs:
        jsonschema.validate(rec, schema)
    assert log.verify().ok


def test_reopen_continues_chain(tmp_path: Path) -> None:
    log = three(tmp_path)
    again = AuditLog(log.path)
    again.append(advice(9))
    assert again.verify().ok and len(again.records()) == 4
