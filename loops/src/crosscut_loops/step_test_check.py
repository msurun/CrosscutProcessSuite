"""Pre-flight check of a recorded level step test, before it is loaded into the tuning wizard.

`check_step_test` measures the record (sampling, OUT moves, quiet lead, time after the last
move, mode, quantisation), applies the same thresholds as `identify_ipdt`, and runs the real
identification as a dry run, so the engineer sees what the wizard will say. Advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np

from crosscut_loops.identification_ipdt import (
    DEFAULT_SETTINGS,
    IpdtIdentificationError,
    IpdtSettings,
    _move_span,
    identify_ipdt,
)

UNEVEN_GAP_FACTOR = 3.0  # a gap above this many median periods marks the sampling as uneven
MIN_MANUAL_SHARE = 0.9  # below this share of samples in manual the record is closed-loop data
MOVE_EPS = 1e-9  # OUT change (%) treated as "the output did not change"
COARSE_PV_FRACTION = 0.02  # PV quantisation above this share of the PV range is coarse
THETA_UNKNOWN_POST_S = 300.0  # post-move requirement used while the dead time is unknown


@dataclass(frozen=True)
class Finding:
    """One problem found in the record: a code, what is wrong and what to do about it.

    ``params`` holds the figures behind the English texts (shares as 0..1, times in s) so a
    client can write the same message in its own language.
    """

    code: str
    text: str
    what_to_do: str
    blocking: bool = False
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DryRun:
    """Result of running identify_ipdt on the record (what the wizard will say)."""

    verdict: str
    reasons: tuple[str, ...]
    slope_per_s: float | None = None
    delay_s: float | None = None
    delay_lower_s: float | None = None
    delay_upper_s: float | None = None
    r_squared: float | None = None
    error: str = ""


@dataclass(frozen=True)
class StepTestCheck:
    """Measured properties of the record, a verdict and the findings behind it."""

    n: int
    duration_s: float
    dt_median_s: float
    dt_max_s: float
    uneven_sampling: bool
    out_range: float
    n_out_moves: int
    first_move_s: float | None
    lead_share: float | None
    post_last_move_s: float | None
    pv_range: float
    manual_share: float | None
    pv_quantisation: float
    out_quantisation: float
    verdict: str
    findings: tuple[Finding, ...]
    dry_run: DryRun | None


def minutes_text(seconds: float) -> str:
    """Seconds as a short minutes text such as '5.0 min'."""
    return f"{seconds / 60.0:.1f} min"


def sampling_figures(t: np.ndarray) -> tuple[float, float, bool]:
    """Median period, largest gap (both s) and whether the sampling is uneven."""
    dt = np.diff(t)
    median, longest = float(np.median(dt)), float(np.max(dt))
    return median, longest, longest > UNEVEN_GAP_FACTOR * median


def quantisation(x: np.ndarray) -> float:
    """Smallest step between distinct values (0.0 if the signal is constant).

    A noisy continuous signal gives a tiny number; a signal from a coarse converter gives its
    resolution. Values are rounded to 9 digits first to remove float noise.
    """
    levels = np.unique(np.round(x, 9))
    return float(np.min(np.diff(levels))) if len(levels) > 1 else 0.0


def count_out_moves(u: np.ndarray, min_step: float) -> int:
    """Number of OUT moves: runs of consecutive changes whose net size is at least min_step."""
    changed = np.abs(np.diff(u)) > MOVE_EPS
    edges = np.flatnonzero(np.diff(np.concatenate(([0], changed.astype(int), [0]))))
    starts, ends = edges[0::2], edges[1::2]
    return int(sum(abs(u[e] - u[s]) >= min_step for s, e in zip(starts, ends, strict=True)))


def resample_uniform(
    t: np.ndarray, columns: dict[str, np.ndarray], step_s: float
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Put signals on a uniform grid of period step_s starting at t[0].

    Columns named 'pv' are linearly interpolated; every other column (OUT, SP, MODE) holds its
    last value (zero-order hold), which is how a historian stores a controller output.
    """
    grid = t[0] + step_s * np.arange(int((t[-1] - t[0]) // step_s) + 1)
    idx = np.clip(np.searchsorted(t, grid, side="right") - 1, 0, len(t) - 1)
    out = {k: (np.interp(grid, t, v) if k == "pv" else v[idx]) for k, v in columns.items()}
    return grid, out


def _dry_run(t: np.ndarray, out: np.ndarray, pv: np.ndarray, s: IpdtSettings) -> DryRun:
    """Run identify_ipdt; a malformed record becomes a blocked result with the error text."""
    try:
        fit = identify_ipdt(t, out, pv, s)
    except IpdtIdentificationError as exc:
        return DryRun("blocked", ("malformed_input",), error=str(exc))
    m = fit.model
    return DryRun(
        fit.verdict, fit.reasons, m.slope_per_s, m.delay_s,
        fit.delay_lower_s, fit.delay_upper_s, fit.r_squared,
    )  # fmt: skip


class _Rows(NamedTuple):
    """Rows with finite t, OUT and PV (and the matching MODE and SP), and the dropped count."""

    t: np.ndarray
    u: np.ndarray
    y: np.ndarray
    mode: np.ndarray | None
    dropped: int


def _prepare(t_s: object, out: object, pv: object, mode: object | None) -> _Rows:
    """Float arrays of the rows where t, OUT and PV are finite."""
    t, u, y = (np.asarray(a, dtype=float) for a in (t_s, out, pv))
    keep = np.isfinite(t) & np.isfinite(u) & np.isfinite(y)
    m = None if mode is None else np.asarray(mode, dtype=float)[keep]
    return _Rows(t[keep], u[keep], y[keep], m, int((~keep).sum()))


def _lead_finding(lead_share: float, first_s: float, t_end: float, s: IpdtSettings) -> Finding:
    """Finding for too little quiet time before the first OUT move, with the time to record."""
    f = s.min_pre_move_fraction
    need = f / (1.0 - f) * (t_end - first_s)
    return Finding(
        "lead_too_short",
        f"Only {lead_share:.0%} of the record ({minutes_text(first_s)}) is quiet before the "
        f"first OUT move; the wizard needs at least {f:.0%}.",
        f"Record at least {minutes_text(need)} of quiet time (OUT and PV steady) before the "
        "first move, then repeat the move and the hold.",
        blocking=True,
        params={"share": lead_share, "lead_s": first_s, "min_share": f, "need_s": need},
    )


def _post_finding(post_s: float, need_s: float, known: bool) -> Finding:
    """Finding for too little time after the last OUT move."""
    basis = "5 x the fitted dead time" if need_s > THETA_UNKNOWN_POST_S else "300 s"
    note = "" if known else " (dead time is unknown, so 300 s is used)"
    return Finding(
        "post_move_too_short",
        f"Only {minutes_text(post_s)} are recorded after the last OUT move; the wizard needs "
        f"{minutes_text(need_s)} ({basis}){note}.",
        f"Keep recording and hold OUT for at least {minutes_text(need_s)} after the last move.",
        blocking=True,
        params={
            "post_s": post_s, "need_s": need_s, "known": known,
            "basis": "fit" if need_s > THETA_UNKNOWN_POST_S else "floor",
        },
    )


def _timing_findings(
    t: np.ndarray, u: np.ndarray, theta: float | None, s: IpdtSettings
) -> tuple[list[Finding], float, float, float]:
    """Lead and post-move findings plus (first move s, lead share, post s) from record start."""
    t_first, t_last = _move_span(t, u, s)
    window = float(t[-1] - t[0])
    first_s, post_s = t_first - float(t[0]), float(t[-1]) - t_last
    share = first_s / window
    need = max(s.post_move_delay_factor * (theta or 0.0), s.min_post_move_s)
    found = []
    if share < s.min_pre_move_fraction:
        found.append(_lead_finding(share, first_s, float(t[-1] - t[0]), s))
    if post_s < need:
        found.append(_post_finding(post_s, need, theta is not None))
    return found, first_s, share, post_s


def _mode_findings(manual_share: float | None) -> list[Finding]:
    """Findings when part of the record was not in manual."""
    if manual_share is None or manual_share >= 1.0:
        return []
    blocking = manual_share < MIN_MANUAL_SHARE
    return [Finding(
        "not_in_manual",
        f"Only {manual_share:.0%} of the record is in manual."
        + (" This looks like closed-loop data, which is not supported yet." if blocking else ""),
        "Record the test with the loop in MANUAL for the whole record "
        "(or cut the record to the manual part).",
        blocking=blocking,
        params={"share": manual_share, "closed_loop": blocking},
    )]  # fmt: skip


def _signal_findings(n_dropped: int, uneven: bool) -> list[Finding]:
    """Findings about dropped rows and uneven sampling."""
    found = []
    if n_dropped:
        found.append(Finding(
            "bad_values", f"{n_dropped} rows with missing or non-numeric values were dropped.",
            "Check the export (quality column, gaps in the historian).",
            params={"count": n_dropped},
        ))  # fmt: skip
    if uneven:
        found.append(Finding(
            "uneven_sampling", "The sampling is uneven (long gaps in the record).",
            "Export at a fixed period (1-10 s); the check resamples to a uniform grid by holding "
            "OUT and interpolating PV, which hides the gaps.",
        ))  # fmt: skip
    return found


def _dry_run_findings(dry: DryRun, pv_quant: float, pv_range: float) -> list[Finding]:
    """Findings from the dry run (low confidence) and from coarse PV resolution."""
    found = []
    if dry.verdict == "low_confidence":
        found.append(Finding(
            "low_confidence",
            "The identification is only low-confidence: " + ", ".join(dry.reasons),
            "Use a larger OUT step or a doublet, a longer hold, and keep other disturbances away.",
            params={"reasons": list(dry.reasons)},
        ))  # fmt: skip
    if pv_range > 0 and pv_quant > COARSE_PV_FRACTION * pv_range:
        found.append(Finding(
            "pv_coarse",
            f"PV resolution ({pv_quant:g}) is coarse against its range ({pv_range:g}).",
            "Use a larger OUT move so PV travels further, or export PV with more digits.",
            params={"resolution": pv_quant, "range": pv_range},
        ))  # fmt: skip
    return found


def _verdict(findings: list[Finding], dry: DryRun | None) -> str:
    """'not_usable' on any blocker or a blocked dry run, 'ready' when nothing is left."""
    if any(f.blocking for f in findings) or (dry is not None and dry.verdict == "blocked"):
        return "not_usable"
    return "usable_with_warnings" if findings else "ready"


def _manual_share(mode: np.ndarray | None) -> float | None:
    """Share of samples with MODE equal to 0 (manual), or None when no mode was given."""
    return None if mode is None else float(np.mean(mode == 0.0))


def _measures(rows: _Rows) -> dict[str, Any]:
    """The plain figures of the record, keyed like the StepTestCheck fields."""
    t, u, y = rows.t, rows.u, rows.y
    dt_med, dt_max, uneven = sampling_figures(t)
    return {
        "n": len(t), "duration_s": float(t[-1] - t[0]), "dt_median_s": dt_med,
        "dt_max_s": dt_max, "uneven_sampling": uneven, "out_range": float(np.ptp(u)),
        "pv_range": float(np.ptp(y)), "manual_share": _manual_share(rows.mode),
        "pv_quantisation": quantisation(y), "out_quantisation": quantisation(u),
    }  # fmt: skip


def _no_move_finding(s: IpdtSettings) -> Finding:
    """Finding for a record whose OUT never moves."""
    return Finding(
        "no_out_move", f"OUT does not move by the minimum of {s.min_out_range:g} % in this record.",
        "Move OUT by a step (5-10 % of OUT) while the loop is in manual and record the result.",
        blocking=True,
        params={"min_range": s.min_out_range},
    )


def _analyse_move(
    rows: _Rows, figures: dict[str, Any], s: IpdtSettings
) -> tuple[dict[str, Any], list[Finding], DryRun]:
    """Dry run on the uniform grid and the timing figures and findings of a record with a move."""
    step = max(1.0, float(round(figures["dt_median_s"])))
    grid, cols = resample_uniform(rows.t, {"out": rows.u, "pv": rows.y}, step)
    dry = _dry_run(grid, cols["out"], cols["pv"], s)
    theta = dry.delay_upper_s if not dry.error else None
    timing, first_s, share, post_s = _timing_findings(grid, cols["out"], theta, s)
    found = timing + _dry_run_findings(dry, figures["pv_quantisation"], figures["pv_range"])
    extra = {
        "n_out_moves": count_out_moves(rows.u, s.min_out_range), "first_move_s": first_s,
        "lead_share": share, "post_last_move_s": post_s,
    }  # fmt: skip
    return extra, found, dry


def check_step_test(
    t_s: object,
    out: object,
    pv: object,
    sp: object | None = None,
    mode: object | None = None,
    settings: IpdtSettings = DEFAULT_SETTINGS,
) -> StepTestCheck:
    """Check a recorded step test (times in s, OUT and PV in %/unit, MODE 0 = manual).

    Uses the thresholds of `identify_ipdt`; the post-move requirement is 300 s while the dead
    time is unknown. The dry run executes `identify_ipdt` on the record resampled to the uniform
    grid that `make-dataset` writes (period = median period, at least 1 s; OUT held, PV
    interpolated), so it reports what the wizard will say. ``sp`` is accepted for symmetry and
    is not needed for the checks. Raises IpdtIdentificationError if time is not increasing.
    """
    rows = _prepare(t_s, out, pv, mode)
    if len(rows.t) < 2 or np.any(np.diff(rows.t) <= 0):
        raise IpdtIdentificationError("time must be strictly increasing with at least 2 rows")
    figures = _measures(rows)
    findings = _signal_findings(rows.dropped, figures["uneven_sampling"])
    findings += _mode_findings(figures["manual_share"])
    if figures["out_range"] < settings.min_out_range:
        findings.append(_no_move_finding(settings))
        return StepTestCheck(
            **figures, n_out_moves=0, first_move_s=None, lead_share=None,
            post_last_move_s=None, verdict="not_usable", findings=tuple(findings), dry_run=None,
        )  # fmt: skip
    extra, more, dry = _analyse_move(rows, figures, settings)
    findings += more
    return StepTestCheck(
        **figures, **extra, verdict=_verdict(findings, dry), findings=tuple(findings), dry_run=dry
    )  # fmt: skip
