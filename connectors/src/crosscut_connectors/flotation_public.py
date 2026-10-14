"""Loader for the public "Quality Prediction in a Mining Process" flotation data (Kaggle, CC0).

The file has decimal commas and one timestamp per HOUR on rows sampled every 20 s, so the real
time of a row is rebuilt here from its position inside the hour. This is the first non-simulated
data the suite meets; see docs/PROVENANCE.md for the source and the limits (no setpoint, no
controller output).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

SAMPLE_PERIOD_S = 20.0  # the fast columns were sampled every 20 s (dataset description)
HOUR_S = 3600.0
TIME_COLUMN = "date"
# Columns the description says come from the laboratory once per hour; the file repeats each value
# on every 20 s row of that hour, so they are step signals, not 20 s measurements.
LAB_COLUMNS = ("% Iron Feed", "% Silica Feed", "% Iron Concentrate", "% Silica Concentrate")


@dataclass(frozen=True)
class FlotationData:
    """The data as numpy arrays: ``t_s`` seconds since the first hour, one array per column."""

    t_s: np.ndarray
    columns: dict[str, np.ndarray]
    hours_missing: int


def _to_float_columns(table: pa.Table) -> dict[str, np.ndarray]:
    """Convert every column except the timestamp from decimal-comma text to float64."""
    columns: dict[str, np.ndarray] = {}
    for name in table.column_names:
        if name == TIME_COLUMN:
            continue
        dotted = pc.replace_substring(table[name], ",", ".")
        columns[name] = dotted.cast(pa.float64()).to_numpy()
    return columns


def _time_inside_hours(hour_labels: np.ndarray) -> np.ndarray:
    """Seconds since the first label: hour start plus 20 s times the row's index within its hour.

    Rows of one hour are consecutive in the file; the label is taken as the start of its block (the
    file does not say whether it is the start or the end, a constant shift that changes no result).
    """
    labels = hour_labels.astype("datetime64[s]")
    hour_start_s = (labels - labels[0]).astype(np.int64).astype(float)
    new_hour = np.r_[True, hour_start_s[1:] != hour_start_s[:-1]]
    block_first_row = np.maximum.accumulate(np.where(new_hour, np.arange(len(labels)), 0))
    row_in_hour = np.arange(len(labels)) - block_first_row
    return np.asarray(hour_start_s + row_in_hour * SAMPLE_PERIOD_S)


def load_flotation_csv(path: str | Path) -> FlotationData:
    """Read the Kaggle CSV; rows keep file order, gaps (missing hours) stay visible in ``t_s``."""
    text_types = pacsv.ConvertOptions(strings_can_be_null=False)
    table = pacsv.read_csv(Path(path), convert_options=text_types)
    table = table.cast(pa.schema([(name, pa.string()) for name in table.column_names]))
    labels = np.array(table[TIME_COLUMN].to_pylist(), dtype="datetime64[s]")
    t_s = _time_inside_hours(labels)
    hours = np.unique(np.floor(t_s / HOUR_S))
    missing = int(hours[-1] - hours[0] + 1 - len(hours))
    return FlotationData(t_s, _to_float_columns(table), missing)
