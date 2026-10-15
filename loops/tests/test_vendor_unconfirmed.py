"""The report must mark ABB time tags as unconfirmed until assumption A7 is closed."""

from crosscut_loops.tuning_report import _render_vendor_section
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.vendor_forms import vendor_summaries


def _section() -> str:
    forms = vendor_summaries(PiSettings(kc=2.0, ti_s=30.0), pv_span=100.0)
    return _render_vendor_section(forms, "## Vendor tags")


def test_abb_time_tag_is_marked_unconfirmed() -> None:
    assert "s (UNCONFIRMED)" in _section()


def test_unconfirmed_banner_is_printed() -> None:
    assert "**UNCONFIRMED:**" in _section()


def test_siemens_ti_is_not_marked() -> None:
    siemens_lines = [ln for ln in _section().splitlines() if "CtrlParams.Ti" in ln]
    assert siemens_lines and all("UNCONFIRMED" not in ln for ln in siemens_lines)
