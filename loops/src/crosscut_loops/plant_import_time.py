"""Wall-clock to UTC conversion for whole PI wide files, with DST and fixed-offset options.

Plant files carry naive LOCAL times; the dataset stores UTC. Resolving IANA zones row by row in
Python would be too slow for ~100k rows, so local times are grouped by calendar date and each
date is resolved once, reusing the result for all rows of that date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from crosscut_loops.step_test_io import Note

MAX_OFFSET_HOURS = 14.0  # the widest civil offset in use (UTC+14, Line Islands)
NS_PER_SECOND = 1_000_000_000
SECONDS_PER_HOUR = 3600
NS_PER_HOUR = SECONDS_PER_HOUR * NS_PER_SECOND
NS_PER_MICROSECOND = 1000


@dataclass(frozen=True)
class TimeZoneSpec:
    """How to read the naive local times of a file.

    kind 'utc' means the times are already UTC; 'iana' uses a named zone with DST rules;
    'offset' uses a fixed number of hours east of UTC (e.g. -3 for Chile in winter).
    """

    kind: str = "utc"
    value: str | float | None = None


@dataclass(frozen=True)
class _Instant:
    """Seconds east of UTC of one local wall-clock time plus whether it falls in a DST edge."""

    seconds: int
    is_ambiguous: bool
    is_nonexistent: bool


def _resolve_instant(local_wall: datetime, zone: ZoneInfo) -> _Instant:
    """Offset of one wall-clock time and whether it is ambiguous or nonexistent.

    Ambiguous: the wall time occurs twice when clocks go back; fold=0 and fold=1 then give
    different offsets, and we keep fold=0 (the FIRST occurrence). Nonexistent: the wall time
    is skipped when clocks go forward; zoneinfo still returns an offset, so we detect the gap
    by converting to UTC and back to local and comparing with the input.
    """
    first = local_wall.replace(tzinfo=zone, fold=0)
    second = local_wall.replace(tzinfo=zone, fold=1)
    is_ambiguous = first.utcoffset() != second.utcoffset()
    round_trip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    is_nonexistent = round_trip != local_wall
    seconds = int(first.utcoffset().total_seconds())
    return _Instant(seconds, is_ambiguous, is_nonexistent)


def _midnight_of_day(day_offset: int) -> datetime:
    """Naive datetime at 00:00 of the day ``day_offset`` days after 1970-01-01."""
    return datetime(1970, 1, 1) + timedelta(days=day_offset)


def _date_flags(unique_days: np.ndarray, zone: ZoneInfo) -> tuple[np.ndarray, np.ndarray]:
    """Per unique date: offset seconds at 00:00, and whether 00:00 is near a DST change."""
    epoch_day = np.datetime64(0, "D")
    offsets_s = np.empty(unique_days.shape, dtype=np.int64)
    is_unstable = np.empty(unique_days.shape, dtype=bool)
    for position, day in enumerate(unique_days):
        day_offset = int((day - epoch_day).astype(int))
        resolved = _resolve_instant(_midnight_of_day(day_offset), zone)
        offsets_s[position] = resolved.seconds
        # A date whose midnight is ambiguous or nonexistent straddles a DST change: every
        # timestamp on it must be resolved exactly, because a whole-date offset is wrong.
        # A change at 24:00 (Chile) hides in the day BEFORE the midnight it happens at, so also
        # compare with the offset at the next midnight.
        following = _resolve_instant(_midnight_of_day(day_offset + 1), zone)
        is_unstable[position] = (
            resolved.is_ambiguous
            or resolved.is_nonexistent
            or resolved.seconds != following.seconds
        )
    return offsets_s, is_unstable


def _wall_by_ns(local_ns: np.ndarray) -> dict[int, datetime]:
    """Map each unique local nanosecond value to the naive Python datetime it means."""
    unique_ns = np.unique(local_ns)
    base = datetime(1970, 1, 1)
    return {
        int(ns): base + timedelta(microseconds=int(ns) // NS_PER_MICROSECOND)
        for ns in unique_ns
    }


def _offsets_on_unstable_days(
    local_ns: np.ndarray, zone: ZoneInfo
) -> tuple[np.ndarray, int, int]:
    """Exact per-row offsets on DST-change days, plus ambiguous and nonexistent row counts."""
    wall_by_ns = _wall_by_ns(local_ns)
    per_row_offset = np.empty(local_ns.shape, dtype=np.int64)
    ambiguous_rows = 0
    nonexistent_rows = 0
    for position, ns in enumerate(local_ns):
        resolved = _resolve_instant(wall_by_ns[int(ns)], zone)
        per_row_offset[position] = resolved.seconds
        ambiguous_rows += int(resolved.is_ambiguous)
        nonexistent_rows += int(resolved.is_nonexistent)
    return per_row_offset, ambiguous_rows, nonexistent_rows


def _per_row_offsets(local_ns: np.ndarray, zone: ZoneInfo) -> tuple[np.ndarray, int, int]:
    """Offset seconds for every row, plus ambiguous and nonexistent row counts.

    Rows on stable dates share the offset of their date; rows on DST-change dates are resolved
    individually, so Python runs once per date plus once per row only near a clock change.
    """
    days = local_ns.astype("datetime64[ns]").astype("datetime64[D]")
    unique_days, inverse = np.unique(days, return_inverse=True)
    offsets_s, is_unstable = _date_flags(unique_days, zone)
    stable = ~is_unstable[inverse]
    per_row_offset = np.where(stable, offsets_s[inverse], 0).astype(np.int64)
    if stable.all():
        return per_row_offset, 0, 0
    unstable_offset, ambiguous_rows, nonexistent_rows = _offsets_on_unstable_days(
        local_ns[~stable], zone
    )
    per_row_offset[~stable] = unstable_offset
    return per_row_offset, ambiguous_rows, nonexistent_rows


def _first_last_offset_hours(offset_s: np.ndarray) -> tuple[float, float]:
    """Offsets of the first and the last row in hours east of UTC."""
    return float(offset_s[0]) / SECONDS_PER_HOUR, float(offset_s[-1]) / SECONDS_PER_HOUR


def _to_utc(naive: np.ndarray) -> tuple[np.ndarray, list[Note]]:
    """Times already in UTC: nothing to shift."""
    utc_ns = naive.astype("datetime64[ns]").astype(np.int64)
    return utc_ns, [Note("tz_utc", "times read as UTC (no conversion)", {})]


def _to_fixed_offset(naive: np.ndarray, hours: float) -> tuple[np.ndarray, list[Note]]:
    """Subtract a fixed offset: a local wall time at UTC+h is UTC = local - h."""
    if abs(hours) > MAX_OFFSET_HOURS:
        raise ValueError(
            f"time zone offset {hours} h is outside ±{MAX_OFFSET_HOURS:g} h; "
            "give hours east of UTC, e.g. -3 for America/Santiago in winter"
        )
    local_ns = naive.astype("datetime64[ns]").astype(np.int64)
    utc_ns = local_ns - int(round(hours * NS_PER_HOUR))
    text = f"fixed offset applied: local times shifted by {-hours:+g} h to UTC"
    return utc_ns, [Note("tz_offset", text, {"hours": hours})]


def _zone_or_raise(name: str) -> ZoneInfo:
    """ZoneInfo for an IANA name, or ValueError naming the mistake."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(
            f"unknown time zone '{name}'; give an IANA name such as 'America/Santiago'"
        ) from error


def _iana_note(zone_name: str, per_row_offset: np.ndarray) -> Note:
    """Note recording the zone and the offset at the first and the last row."""
    first_offset, last_offset = _first_last_offset_hours(per_row_offset)
    text = (
        f"times read in {zone_name}, stored in UTC (offset {first_offset:+g} h at the first "
        f"row, {last_offset:+g} h at the last)"
    )
    params = {
        "zone": zone_name,
        "offset_first_hours": first_offset,
        "offset_last_hours": last_offset,
    }
    return Note("tz_iana", text, params)


def _ambiguous_note(rows: int) -> Note:
    """Note recording that some local times occurred twice and the first occurrence was used."""
    text = (
        f"{rows} local time(s) occurred twice at the DST change; "
        "the first occurrence was used"
    )
    return Note("tz_ambiguous", text, {"rows": rows})


def _nonexistent_note(rows: int) -> Note:
    """Note recording that some local times were skipped by the DST change."""
    text = (
        f"{rows} local time(s) do not exist at the DST change; "
        "the times after the gap were used"
    )
    return Note("tz_nonexistent", text, {"rows": rows})


def _dst_notes(
    zone_name: str, per_row_offset: np.ndarray, ambiguous_rows: int, nonexistent_rows: int
) -> list[Note]:
    """Notes for an IANA conversion: the zone always, the DST edges only when they happened."""
    notes = [_iana_note(zone_name, per_row_offset)]
    if ambiguous_rows:
        notes.append(_ambiguous_note(ambiguous_rows))
    if nonexistent_rows:
        notes.append(_nonexistent_note(nonexistent_rows))
    return notes


def _to_iana(naive: np.ndarray, name: str) -> tuple[np.ndarray, list[Note]]:
    """Resolve wall-clock times in a named zone using its DST rules."""
    zone = _zone_or_raise(name)
    if naive.size == 0:
        raise ValueError("no rows to convert: the time column is empty")
    local_ns = naive.astype("datetime64[ns]").astype(np.int64)
    per_row_offset, ambiguous_rows, nonexistent_rows = _per_row_offsets(local_ns, zone)
    utc_ns = local_ns - per_row_offset * NS_PER_SECOND
    return utc_ns, _dst_notes(name, per_row_offset, ambiguous_rows, nonexistent_rows)


def to_utc_ns(naive: np.ndarray, spec: TimeZoneSpec) -> tuple[np.ndarray, list[Note]]:
    """Convert naive local wall-clock times to int64 nanoseconds since Unix epoch in UTC.

    ``naive`` is a sorted datetime64 array (any unit); the result has the same length. Raises
    ValueError for an unknown zone name, an offset outside ±14 h, or an unknown spec kind.
    """
    times = np.asarray(naive)
    if spec.kind == "utc":
        return _to_utc(times)
    if spec.kind == "offset":
        if spec.value is None:
            raise ValueError("offset time zone needs a value: hours east of UTC, e.g. -3")
        return _to_fixed_offset(times, float(spec.value))
    if spec.kind == "iana":
        if not spec.value:
            raise ValueError("iana time zone needs a name, e.g. 'America/Santiago'")
        return _to_iana(times, str(spec.value))
    raise ValueError(f"unknown time zone kind '{spec.kind}'; use 'utc', 'iana' or 'offset'")
