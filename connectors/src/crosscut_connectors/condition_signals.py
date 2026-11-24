"""Propose equipment condition roles from synthetic catalogue metadata.

Suggestions remain unconfirmed so an engineer can review their meaning and thresholds.
"""

import re

UNIT_KINDS = {
    "temperature": {"degc", "°c", "k", "degf"},
    "current": {"a", "ma", "ka"},
    "power": {"kw", "w", "mw", "hp"},
    "torque": {"nm", "knm"},
    "vibration": {"mm/s", "in/s", "g", "um"},
    "speed": {"rpm", "1/min"},
}
KEYWORD_KINDS = {
    "temperature": ("TEMP", "TT", "BRG"),
    "current": ("CURR", "AMP", "IT"),
    "power": ("POWER", "JT"),
    "torque": ("TORQ",),
    "vibration": ("VIB", "VT"),
    "speed": ("SPEED", "ST", "RPM"),
    "ambient": ("AMB",),
}
RUNNING_DEFAULTS = (("speed", 10.0), ("current", 1.0))  # Thresholds: rpm, then A.


def propose_kind(tag_id: str, unit: str | None, description: str | None) -> str | None:
    """Return a proposed condition kind, preferring units over naming hints."""
    normalized_unit = (unit or "").strip().casefold()
    for kind, units in UNIT_KINDS.items():
        if normalized_unit in units:
            return kind
    name = tag_id.upper()
    if normalized_unit == "hz" and ("SPEED" in name or "FREQ" in name):
        return "speed"
    return _keyword_kind(f"{tag_id} {description or ''}".upper())


def _keyword_kind(text: str) -> str | None:
    """Match word prefixes, including instrument codes followed by digits."""
    # Boundaries avoid interpreting IT inside an unrelated word such as QUALITY.
    words = re.findall(r"[A-Z]+", text)
    for kind, keywords in KEYWORD_KINDS.items():
        if any(word.startswith(keyword) for word in words for keyword in keywords):
            return kind
    return None


def propose_running(signals: list[dict]) -> dict | None:
    """Return an unconfirmed running threshold, preferring speed over current."""
    # No rated speed is supplied, so a percentage cannot be calculated. These fixed
    # defaults assume rpm or A respectively; an engineer must review other units.
    for kind, threshold in RUNNING_DEFAULTS:
        for signal in signals:
            if signal.get("kind") == kind:
                return {"tag": signal["tag"], "above": threshold, "confirmed": False}
    return None


def one_loop_equipment(loop_id: str) -> dict:
    """Return a minimal equipment entry primarily owning one otherwise unowned loop."""
    return {"id": loop_id, "level": "equipment", "loops": [loop_id]}
