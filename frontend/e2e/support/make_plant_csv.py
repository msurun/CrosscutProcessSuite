"""Make the synthetic whole-PI-file fixture the Import e2e spec uploads.

Usage: python make_plant_csv.py <out_dir>

Writes plant.csv (3 h of 10 s samples, naive local timestamps, decimal point) and
tag_dictionary.csv (the PI tag metadata with a UTF-8 BOM, as PI DataLink exports it).
Two level loops, one flow loop and one extra process tag; no real process is involved.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SAMPLE_INTERVAL_S = 10
DURATION_S = 3 * 60 * 60
START = datetime(2026, 10, 9, 11, 0, 0)  # local plant time, no timezone on purpose
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
RANDOM_SEED = 7

# The Scavenger line runs for the middle of the record only (second hour).
SCAVENGER_START_S = 60 * 60
SCAVENGER_END_S = 2 * 60 * 60
SCAVENGER_LABEL = "Scavenger"

# The loops start in manual and are put in automatic after this many seconds.
AUTO_START_S = 10 * 60

# Every level sits around this level (cm, the unit of the .mv tags).
LEVEL_CENTRE_CM = 50.0
LEVEL_NOISE_SD_CM = 0.5

LIC_20101 = "demo.1000-lic-20101"
LIC_20103 = "demo.1000-lic-20103"
FIC_20120 = "demo.1000-fic-20120"
AI_001 = "demo.1000-ai-001"

# Tag name -> (description, unit, signal, loop, cell).
# signal is one of: PV (measured), OUT (controller output), SP, mode flag, other.
TAG_METADATA: dict[str, tuple[str, str, str, str, str]] = {}


def register_loop(
    loop_tag: str, description: str, unit: str, cell: str
) -> tuple[str, ...]:
    """Register the four tags of a loop and return their names (.mv, .out, .sp, .auto#state)."""
    measured, output, setpoint, mode = (
        f"{loop_tag}.mv",
        f"{loop_tag}.out",
        f"{loop_tag}.sp",
        f"{loop_tag}.auto#state",
    )
    number = loop_tag.rsplit("-", 1)[1]  # the dictionary's loop column holds the loop number
    TAG_METADATA[measured] = (description, unit, "PV (measured)", number, cell)
    TAG_METADATA[output] = (f"{description} output", "%", "OUT (controller output)", number, cell)
    TAG_METADATA[setpoint] = (f"{description} setpoint", unit, "SP", number, cell)
    TAG_METADATA[mode] = (f"{description} mode", "", "mode flag", number, cell)
    return measured, output, setpoint, mode


def register_tags() -> None:
    """Fill TAG_METADATA with the loops and the extra process tag of the fixture."""
    register_loop(LIC_20101, "Level loop 20101", "cm", "Cell 3500")
    register_loop(LIC_20103, "Level loop 20103", "cm", "Cell 3500")
    register_loop(FIC_20120, "Flow loop 20120", "m3/h", "Cell 3500")
    TAG_METADATA[f"{AI_001}.pv"] = (
        "Process temperature probe",
        "degC",
        "other",
        "",
        "Cell 3500",
    )


def timestamps_seconds() -> np.ndarray:
    """Seconds since START for every sample of the record."""
    return np.arange(0, DURATION_S + SAMPLE_INTERVAL_S, SAMPLE_INTERVAL_S, dtype=float)


def format_timestamp(seconds: float) -> str:
    """Naive local timestamp of a sample, in TIMESTAMP_FORMAT."""
    moment = START + timedelta(seconds=float(seconds))
    return moment.strftime(TIMESTAMP_FORMAT)


def scavenger_column(seconds: np.ndarray) -> list[str]:
    """The text column 'test': Scavenger inside the middle hour, empty elsewhere."""
    is_in_scavenger = (seconds >= SCAVENGER_START_S) & (seconds < SCAVENGER_END_S)
    return [SCAVENGER_LABEL if active else "" for active in is_in_scavenger]


def mode_flag(seconds: float) -> int:
    """1 when the loop is in automatic, 0 during the first AUTO_START_S seconds."""
    return 1 if seconds >= AUTO_START_S else 0


def level_record(
    rng: np.random.Generator, seconds: np.ndarray, offset_cm: float
) -> dict[str, object]:
    """Column values of a level loop: mv and sp around LEVEL_CENTRE_CM, out in %, mode flag."""
    level = LEVEL_CENTRE_CM + offset_cm + rng.normal(0.0, LEVEL_NOISE_SD_CM, len(seconds))
    setpoint = np.full(len(seconds), LEVEL_CENTRE_CM + offset_cm)
    # OUT is a proportional controller: 50 % at the setpoint, 4 % per cm of deviation.
    output = np.clip(50.0 + 4.0 * (setpoint - level), 0.0, 100.0)
    return {
        "mv": level,
        "sp": setpoint,
        "out": output,
        "mode": np.array([mode_flag(s) for s in seconds]),
    }


def flow_record(rng: np.random.Generator, seconds: np.ndarray) -> dict[str, object]:
    """Column values of the flow loop: mv and sp in m3/h, out in %, mode flag."""
    setpoint_m3_h = 12.0
    measured = setpoint_m3_h + rng.normal(0.0, 0.1, len(seconds))
    output = np.clip(50.0 + 8.0 * (setpoint_m3_h - measured), 0.0, 100.0)
    return {
        "mv": measured,
        "sp": np.full(len(seconds), setpoint_m3_h),
        "out": output,
        "mode": np.array([mode_flag(s) for s in seconds]),
    }


def extra_tag_record(rng: np.random.Generator, seconds: np.ndarray) -> dict[str, object]:
    """Column values of the extra process tag: a slow sine temperature with noise, degC."""
    # One cycle per hour over 2 degC around 60 degC.
    phase = 2.0 * np.pi * seconds / 3600.0
    temperature = 60.0 + 2.0 * np.sin(phase) + rng.normal(0.0, 0.1, len(seconds))
    return {"pv": temperature}


def plant_columns(seconds: np.ndarray) -> dict[str, object]:
    """All plant.csv columns except 'timestamp' and 'test', keyed by the tag name part."""
    rng = np.random.default_rng(RANDOM_SEED)
    columns: dict[str, object] = {}
    for loop, loop_values in (
        (LIC_20101, level_record(rng, seconds, offset_cm=0.0)),
        (LIC_20103, level_record(rng, seconds, offset_cm=2.0)),
        (FIC_20120, flow_record(rng, seconds)),
    ):
        for suffix in ("mv", "out", "sp", "mode"):
            name = "auto#state" if suffix == "mode" else suffix
            columns[f"{loop}.{name}"] = loop_values[suffix]
    columns[f"{AI_001}.pv"] = extra_tag_record(rng, seconds)["pv"]
    return columns


def number_text(value: object) -> str:
    """Format one numeric cell with a decimal point and enough digits for its magnitude."""
    number = float(value)  # type: ignore[arg-type]
    return f"{number:.4f}" if abs(number) < 100.0 else f"{number:.3f}"


def write_plant_csv(path: Path) -> None:
    """Write plant.csv: header 'timestamp,test,<tag columns>' then one row per sample."""
    seconds = timestamps_seconds()
    columns = plant_columns(seconds)
    headers = ["timestamp", "test", *columns]
    rows = [",".join(headers)]
    scavenger = scavenger_column(seconds)
    tag_columns = list(columns.values())
    for index, stamp_seconds in enumerate(seconds):
        cells = [format_timestamp(stamp_seconds), scavenger[index]]
        cells.extend(number_text(column[index]) for column in tag_columns)  # type: ignore[index]
        rows.append(",".join(cells))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_tag_dictionary(path: Path) -> None:
    """Write tag_dictionary.csv as UTF-8 with BOM: header then one row per registered tag."""
    rows = ["tag,description,unit,signal,loop,cell"]
    for tag, (description, unit, signal, loop, cell) in TAG_METADATA.items():
        rows.append(f"{tag},{description},{unit},{signal},{loop},{cell}")
    # The BOM makes Excel treat the file as UTF-8, matching a PI DataLink export.
    path.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")


def main(out_dir: Path) -> None:
    """Write plant.csv and tag_dictionary.csv into out_dir, creating the folder if needed."""
    register_tags()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_plant_csv(out_dir / "plant.csv")
    write_tag_dictionary(out_dir / "tag_dictionary.csv")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
