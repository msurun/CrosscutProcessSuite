"""Anonymise a process-data export before sharing it with a third party.

Column names become tags, value levels and scales are transformed, and absolute
time is shifted, so names, engineering units and calendar time are hidden. The
dynamics stay intact: sample spacing is untouched and grouped tags (for example
a setpoint and its measurement) keep their original relationship.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

TAG_DIGITS = 3  # zero-padding of the generated tag number, tag_001 ..
SCALE_LOG_MIN = 0.5  # dimensionless, smallest multiplicative factor per column
SCALE_LOG_MAX = 2.0  # dimensionless, largest multiplicative factor per column
OFFSET_STD_RANGE = 5.0  # offset drawn from +-5 standard deviations (same unit as the group)
OFFSET_FALLBACK = 1.0  # unit fallback when the group std is zero or NaN (constant columns)
SECONDS_PER_DAY = 86_400  # s, one day, used for the upper bound of the time shift
TIME_SHIFT_DAYS = 365  # days, shift drawn uniformly from a whole year of seconds


@dataclass(frozen=True)
class AnonymisedData:
    """An anonymised export: shifted time, renamed columns and the recipe to invert it.

    Attributes:
        t_s: time in seconds, original values plus `time_shift_s`.
        columns: new tag name -> values, in the same order as the input columns.
        tag_map: original name -> new tag name. Stays with the customer.
        transforms: new tag name -> (scale, offset), so new = scale * old + offset.
        time_shift_s: whole-second shift applied to the time vector.
    """

    t_s: np.ndarray
    columns: dict[str, np.ndarray]
    tag_map: dict[str, str]
    transforms: dict[str, tuple[float, float]]
    time_shift_s: float
    seed: int = 0  # the seed that drew every constant; keep it with the tag map


# codecheck: allow too-many-parameters (public signature used by tests and the import tools)
def anonymise(
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    linked_groups: Sequence[Sequence[str]] = (),
    keep_values: Sequence[str] = (),
    seed: int | None = None,
) -> AnonymisedData:
    """Rename columns to tags and hide their scales, offsets and absolute time.

    Every tag gets one affine transform new = scale * old + offset, except that
    tags in the same linked group share it (a setpoint minus its measurement keeps
    its meaning), and tags in `keep_values` are renamed only (flags, mode codes).
    A tag appears in at most one group and must exist as a column.

    Returns:
        AnonymisedData with shifted time, renamed columns and the transform recipe.

    Raises:
        ValueError: if a linked/keep tag is not a column, a tag is in two groups,
            or a column length differs from `t_s`.
    """
    _validate_tag_requests(len(t_s), columns, linked_groups, keep_values)
    seed = _resolve_seed(seed)
    rng = np.random.default_rng(seed)

    tag_map = {name: _tag_name(index) for index, name in enumerate(columns)}
    transforms, time_shift_s = _draw_recipe(columns, linked_groups, keep_values, rng)

    return AnonymisedData(
        t_s=np.asarray(t_s, dtype=float) + time_shift_s,
        columns=_transform_columns(columns, tag_map, transforms),
        tag_map=tag_map,
        transforms=transforms,
        time_shift_s=time_shift_s,
        seed=seed,
    )


def _draw_recipe(
    columns: Mapping[str, np.ndarray],
    linked_groups: Sequence[Sequence[str]],
    keep_values: Sequence[str],
    rng: np.random.Generator,
) -> tuple[dict[str, tuple[float, float]], float]:
    """Draw the per-tag transforms, then the time shift (whole seconds within one year).

    The draw order (transforms first) fixes which random numbers each part gets, so the same
    seed always gives the same recipe.
    """
    transforms = _draw_transforms(columns, linked_groups, keep_values, rng)
    return transforms, float(rng.integers(0, TIME_SHIFT_DAYS * SECONDS_PER_DAY))


def _transform_columns(
    columns: Mapping[str, np.ndarray],
    tag_map: dict[str, str],
    transforms: dict[str, tuple[float, float]],
) -> dict[str, np.ndarray]:
    """Apply each column's affine transform and store it under its new tag name."""
    return {
        tag_map[name]: _apply(transforms[tag_map[name]], values)
        for name, values in columns.items()
    }


def _resolve_seed(seed: int | None) -> int:
    """The given seed, or fresh OS entropy.

    A fixed default would give every customer the same scales and shift, which anyone with
    the code could undo.
    """
    if seed is None:
        return int(np.random.SeedSequence().entropy)  # type: ignore[arg-type]
    return seed


def invert_values(data: AnonymisedData, name: str, values: np.ndarray) -> np.ndarray:
    """Map a series given in new-tag units back to the original units.

    Inverse of new = scale * old + offset, i.e. old = (new - offset) / scale.

    Raises:
        ValueError: if `name` is not one of the anonymised tags.
    """
    if name not in data.transforms:
        raise ValueError(f"unknown tag {name!r}, expected one of {sorted(data.transforms)}")
    scale, offset = data.transforms[name]
    return (np.asarray(values, dtype=float) - offset) / scale


def _tag_name(index: int) -> str:
    """Return the tag name for a zero-based column position, tag_001, tag_002, .."""
    return f"tag_{index + 1:0{TAG_DIGITS}d}"


def _validate_tag_requests(
    length: int,
    columns: Mapping[str, np.ndarray],
    linked_groups: Sequence[Sequence[str]],
    keep_values: Sequence[str],
) -> None:
    """Check column lengths (``length`` = time samples), tag names and group membership first.

    Raises:
        ValueError: on an unknown tag, a tag in two groups, or a mismatched length.
    """
    known = set(columns)
    if any(len(group) == 0 for group in linked_groups):
        raise ValueError("a linked group must name at least one tag")
    overlap = set(keep_values) & {name for group in linked_groups for name in group}
    if overlap:
        raise ValueError(f"tags {sorted(overlap)} are both linked and kept unchanged")
    for name, values in columns.items():
        if len(values) != length:
            raise ValueError(f"column {name!r} has {len(values)} samples, time has {length}")
    for group in linked_groups:
        _require_known(group, known)
    _require_known(keep_values, known)
    _require_disjoint_groups(linked_groups)


def _require_disjoint_groups(linked_groups: Sequence[Sequence[str]]) -> None:
    """Raise if a tag appears in two linked groups."""
    seen: set[str] = set()
    for group in linked_groups:
        for name in group:
            if name in seen:
                raise ValueError(f"tag {name!r} appears in two linked groups")
            seen.add(name)


def _require_known(names: Sequence[str], known: set[str]) -> None:
    """Raise if any of `names` is not a column of the export."""
    for name in names:
        if name not in known:
            raise ValueError(f"tag {name!r} is not a column; available: {sorted(known)}")


def _draw_transforms(
    columns: Mapping[str, np.ndarray],
    linked_groups: Sequence[Sequence[str]],
    keep_values: Sequence[str],
    rng: np.random.Generator,
) -> dict[str, tuple[float, float]]:
    """Build new tag name -> (scale, offset) for every column, drawing one per group.

    Grouping exists so a row-wise relation (setpoint minus measurement) survives the
    anonymisation: all members share the same affine map.
    """
    transforms: dict[str, tuple[float, float]] = {}
    grouped = {name for group in linked_groups for name in group}

    for group in linked_groups:
        shared = _draw_transform(columns[group[0]], rng)
        for name in group:
            transforms[name] = shared

    for name, values in columns.items():
        if name in grouped:
            continue
        if name in keep_values:  # flags and codes must stay comparable across exports
            transforms[name] = (1.0, 0.0)
        else:
            transforms[name] = _draw_transform(values, rng)

    return {_tag_name(index): transforms[name] for index, name in enumerate(columns)}


def _draw_transform(values: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """Return one (scale, offset) pair for a column-like series.

    Scale is log-uniform in [0.5, 2.0], so it is always positive and never flips the
    sign of a trend. Offset is uniform in +-5 standard deviations of this series.
    """
    scale = float(np.exp(rng.uniform(np.log(SCALE_LOG_MIN), np.log(SCALE_LOG_MAX))))
    offset = float(rng.uniform(-OFFSET_STD_RANGE, OFFSET_STD_RANGE) * _safe_std(values))
    return scale, offset


def _safe_std(values: np.ndarray) -> float:
    """Return the NaN-aware standard deviation, or 1.0 when it is zero or undefined."""
    std = float(np.nanstd(np.asarray(values, dtype=float)))
    return std if np.isfinite(std) and std > 0.0 else OFFSET_FALLBACK


def _apply(transform: tuple[float, float], values: np.ndarray) -> np.ndarray:
    """new = scale * old + offset on a float copy; NaN stays NaN."""
    scale, offset = transform
    return scale * np.asarray(values, dtype=float) + offset
