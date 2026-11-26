"""Guard declarative vendor loading and its schema contract.

The literal snapshot preserves the registry from before the data migration.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_loops.vendor_forms import VENDOR_FORMS, VendorForm
from crosscut_loops.vendor_profiles import VendorProfileError, load_vendor_profiles
from jsonschema import Draft202012Validator

ORIGINAL_VENDOR_FORMS = {
    "siemens_pid_compact": VendorForm(
        key="siemens_pid_compact",
        block="PID_Compact V2.x (S7-1200 FW>=4.0, S7-1500)",
        form="gain_seconds",
        evidence="verified",
        source=(
            "Siemens FAQ 109481448 V1.0 (01/2016) p.3-5: all times in seconds, no negative Gain; "
            "app. example 79047707 V3.0.0 (03/2017) p.14-15: y = Kp[(b w - x) + 1/(TI s)(w - x) "
            "+ TD s/(a TD s + 1)(c w - x)]; S7-1500 PID Control manual A5E35300227-AA 12/2014 "
            "p.90-91"
        ),
        caveats=(
            "Set PWeighting = 1.0 (b = 1), otherwise the setpoint is weighted and a step reacts "
            "slower than the textbook PI that SIMC and AMIGO assume",
            "TI = 0 switches the integral action OFF",
            "Gain must be positive; reverse action is Config.InvertControl",
            "Gain is entered in output units per PV engineering unit (raw, not normalised): the "
            "identified kc goes in as it is, but the same Gain on another range is another loop",
        ),
    ),
    "abb_pidcc": VendorForm(
        key="abb_pidcc",
        block="PidCC (AC 800M), documented through the Pid01A unit",
        form="gain_seconds",
        evidence="partly_verified",
        source=(
            "ABB 3AST001596D013 rev D (Pid01A, 2009) p.9-10, p.23: ideal PID, deviation in percent "
            "of range; ABB 3BSE041488-600 A (Binary and Analog Handling, 05/2016) p.120-124: "
            "G = Gain x OutRange / PvRange with Gain normalised and dimensionless, setpoint weight "
            "beta editable in PidCC; neither document states the unit of TI"
        ),
        caveats=(
            "Unit of TI and TD NOT confirmed by a document: check the PidCC page of the Control "
            "Builder library manual (3BSE035982) or the block's parameter help before use",
            "Pid01A is the ControlIT unit around PidCC, not the AC 800M library manual itself",
            "Gain is entered normalised (G = Gain x OutRange / PvRange is applied inside), "
            "so kc is used as it is, with no range scaling",
            "Reverse action is a selectable setting, not a negative Gain",
            "Setpoint weight beta is 0 for a discontinuous setpoint by default: set it to 1 "
            "(editable in PidCC) when an externally calculated tuning is applied",
        ),
    ),
}


def test_declarative_profiles_equal_the_original_registry() -> None:
    """Preserve every field, including caveat order and tuple representation."""
    assert VENDOR_FORMS == ORIGINAL_VENDOR_FORMS
    assert list(VENDOR_FORMS) == list(ORIGINAL_VENDOR_FORMS)


def test_loader_reads_packaged_profiles() -> None:
    """Load both vendors through the resource API used by installed wheels."""
    assert set(load_vendor_profiles()) == {"abb_pidcc", "siemens_pid_compact"}


def test_packaged_schema_matches_the_canonical_schema() -> None:
    """Prevent wheel validation from drifting from the repository contract."""
    canonical = Path(__file__).resolve().parents[2] / "schemas/vendor_profile.schema.json"
    packaged = Path(__file__).resolve().parents[1] / (
        "src/crosscut_loops/vendor_profiles/vendor_profile.schema.json"
    )
    schema = json.loads(canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == json.loads(packaged.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("field", "value"), [
    ("form", "unknown"), ("evidence", "certain"), ("caveats", "text"),
    ("caveats", []), ("block", ""), ("key", "Invalid key"), ("source", 42),
    ("extra", True),
])
def test_loader_identifies_the_invalid_file_and_field(
    tmp_path: Path, field: str, value: Any
) -> None:
    """Report schema failures as the profile-specific exception."""
    record = load_vendor_profiles()["abb_pidcc"]
    record[field] = value
    profile = tmp_path / "invalid.json"
    profile.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(VendorProfileError, match="invalid.json") as caught:
        load_vendor_profiles(tmp_path)
    assert field in str(caught.value)


@pytest.mark.parametrize("content", ['{', '[]', '{"key": "abb_pidcc"}', '\ufffd'])
def test_loader_rejects_malformed_or_incomplete_records(tmp_path: Path, content: str) -> None:
    """Reject JSON syntax, root type and required-field errors."""
    (tmp_path / "broken.json").write_text(content, encoding="utf-8")
    with pytest.raises(VendorProfileError, match="broken.json"):
        load_vendor_profiles(tmp_path)


def test_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    """Avoid silently replacing one vendor with another file."""
    content = json.dumps(load_vendor_profiles()["abb_pidcc"])
    (tmp_path / "first.json").write_text(content, encoding="utf-8")
    (tmp_path / "second.json").write_text(content, encoding="utf-8")
    with pytest.raises(VendorProfileError, match="Duplicate"):
        load_vendor_profiles(tmp_path)


def test_loader_rejects_an_empty_directory(tmp_path: Path) -> None:
    """Missing profiles must not silently empty reports."""
    with pytest.raises(VendorProfileError, match="No vendor profile"):
        load_vendor_profiles(tmp_path)


def test_loader_rejects_a_missing_directory(tmp_path: Path) -> None:
    """Give a useful exception for an unreadable profile directory."""
    with pytest.raises(VendorProfileError, match="Cannot read vendor profiles"):
        load_vendor_profiles(tmp_path / "missing")


def test_loader_rejects_invalid_utf8(tmp_path: Path) -> None:
    """Keep decoding failures in the same file-specific error contract."""
    (tmp_path / "encoding.json").write_bytes(b"\xff")
    with pytest.raises(VendorProfileError, match="encoding.json"):
        load_vendor_profiles(tmp_path)
