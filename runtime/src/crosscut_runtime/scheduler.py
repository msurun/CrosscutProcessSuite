"""
Periodic job scheduling on an injectable clock (Phase 1, #44).

The scheduler decides when a job is due; it never knows what a job computes.
Clock and sleep are injected so tests can run the real logic without waiting
for real time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobRun:
    """Outcome of one job execution: the result, or the error message when it failed.

    Attributes
    ----------
    job_id: Identifier of the job that was run.
    ok: True if the job completed without raising, otherwise False.
    result: Value returned by the job when ``ok`` is True; otherwise ``None``.
    error: String representation of the exception when ``ok`` is False; otherwise ``None``.
    """

    job_id: str
    ok: bool
    result: Any | None = None
    error: str | None = None


@dataclass
class JobSlot:
    """One scheduled job: how often it runs and what to call when it is due.

    ``next_run_at`` is in clock seconds of the Scheduler's injected clock; ``None``
    means “run at the first tick”.
    """

    job_id: str
    period_s: float
    run: Callable[[], Any]
    next_run_at: float | None = None


class Scheduler:
    """Runs due job slots on an injectable clock; a failing job never stops the others."""

    def __init__(self, now: Callable[[], float]) -> None:
        """Create a Scheduler with an injected clock accessor.

        Parameters
        ----------
        now: Callable that returns the current clock time in seconds.
        """
        self._now: Callable[[], float] = now
        self._slots: dict[str, JobSlot] = {}

    def put(self, slot: JobSlot) -> None:
        """Add a job slot or replace an existing one with the same ``job_id``."""
        self._slots[slot.job_id] = slot

    def remove(self, job_id: str) -> None:
        """Remove a job slot by identifier; unknown identifiers are ignored (idempotent)."""
        self._slots.pop(job_id, None)

    def get(self, job_id: str) -> JobSlot | None:
        """Return the job slot for *job_id* or ``None`` if it does not exist."""
        return self._slots.get(job_id)

    def ids(self) -> list[str]:
        """Return a sorted list of all known job identifiers."""
        return sorted(self._slots.keys())

    def due(self, at: float) -> list[JobSlot]:
        """Return the slots due at ``at`` in insertion order and reschedule them.

        A slot is due when its ``next_run_at`` is ``None`` (first tick) or
        ``next_run_at`` <= ``at``. After being reported as due, the slot's
        ``next_run_at`` is updated to ``at + period_s``.
        """
        due_slots: list[JobSlot] = []
        for slot in self._slots.values():
            if slot.next_run_at is None or slot.next_run_at <= at:
                due_slots.append(slot)
                # If the runtime was down or slowed for several periods,
                # this slot may have missed its scheduled times.
                # Reschedule from the current ``at`` rather than from the missed time.
                # This prevents a burst of immediate executions when the system restarts.
                slot.next_run_at = at + slot.period_s
        return due_slots

    def tick(self, at: float) -> list[JobRun]:
        """Run every due slot at ``at`` and return a list of ``JobRun`` results.

        A slot whose ``run()`` raises is recorded as failed, but the exception
        does not stop the remaining slots from being executed. The order of the
        returned ``JobRun`` items matches the insertion order of the due slots.
        """
        results: list[JobRun] = []
        for slot in self.due(at):
            try:
                outcome = slot.run()
                results.append(
                    JobRun(job_id=slot.job_id, ok=True, result=outcome, error=None)
                )
            except Exception as exc:  # noqa: BLE001
                # Capture any exception from a job so other jobs keep running.
                results.append(
                    JobRun(job_id=slot.job_id, ok=False, result=None, error=str(exc))
                )
        return results
