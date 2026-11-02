"""Tests for crosscut_runtime.scheduler periodic job scheduling behavior.

Part of Phase 1, #44: Verifies slot registration, execution semantics, error isolation,
and non-burst rescheduling policies against a controllable synthetic clock.
"""

from __future__ import annotations

from typing import Any

from crosscut_runtime.scheduler import JobRun, JobSlot, Scheduler

DEFAULT_JOB_PERIOD_S = 10.0
INITIAL_TICK_TIME_S = 0.0
FIRST_ADVANCE_TIME_S = 5.0
SUB_PERIOD_ADVANCE_TIME_S = 9.999
EXACT_PERIOD_ADVANCE_TIME_S = 10.0
BETWEEN_PERIODS_TIME_S = 15.0
SIGNIFICANT_DELAY_TIME_S = 35.0
EXPECTED_NEXT_RUN_AFTER_DELAY_S = 45.0


class FakeClock:
    """A controllable monotonic clock returning a settable timestamp in seconds."""

    def __init__(self, current_time_s: float = INITIAL_TICK_TIME_S) -> None:
        """Initialize the fake clock with a starting timestamp."""
        self._current_time_s = current_time_s

    def __call__(self) -> float:
        """Return the current configured timestamp in seconds."""
        return self._current_time_s

    def set_time(self, new_time_s: float) -> None:
        """Set the simulated current time to a new value in seconds."""
        self._current_time_s = new_time_s


def _create_slot(
    job_id: str,
    run: Any,
    period_s: float = DEFAULT_JOB_PERIOD_S,
    next_run_at: float | None = None,
) -> JobSlot:
    """Create a JobSlot helper with standard defaults."""
    return JobSlot(
        job_id=job_id,
        period_s=period_s,
        run=run,
        next_run_at=next_run_at,
    )


def test_runs_at_first_tick_when_next_run_at_is_none() -> None:
    """A slot configured with next_run_at=None executes on the very first tick."""
    # In plain words: When a job does not specify a future start time, it is immediately
    # ready to run on the first tick and then schedules its next occurrence one period out.
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    executed_events: list[str] = []

    def record_run() -> str:
        """Record the run in the tracking list and return status."""
        executed_events.append("executed")
        return "first_run_ok"

    slot = _create_slot(job_id="initial_job", run=record_run)
    scheduler.put(slot)

    runs = scheduler.tick(INITIAL_TICK_TIME_S)

    assert runs == [
        JobRun(job_id="initial_job", ok=True, result="first_run_ok", error=None)
    ]
    assert executed_events == ["executed"]
    updated_slot = scheduler.get("initial_job")
    assert updated_slot is not None
    assert updated_slot.next_run_at == DEFAULT_JOB_PERIOD_S


def test_not_due_before_period_elapsed() -> None:
    """A slot does not execute when ticks occur before its period has elapsed."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    slot = _create_slot(job_id="periodic_job", run=lambda: "done")
    scheduler.put(slot)
    scheduler.tick(INITIAL_TICK_TIME_S)

    runs_at_five = scheduler.tick(FIRST_ADVANCE_TIME_S)
    runs_near_boundary = scheduler.tick(SUB_PERIOD_ADVANCE_TIME_S)

    assert runs_at_five == []
    assert runs_near_boundary == []


def test_due_again_after_period() -> None:
    """A slot executes once its period has elapsed, but not between subsequent periods."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    slot = _create_slot(job_id="recurrent_job", run=lambda: "cycle_result")
    scheduler.put(slot)
    scheduler.tick(INITIAL_TICK_TIME_S)

    runs_at_ten = scheduler.tick(EXACT_PERIOD_ADVANCE_TIME_S)
    runs_at_fifteen = scheduler.tick(BETWEEN_PERIODS_TIME_S)

    assert len(runs_at_ten) == 1
    assert runs_at_ten[0].ok is True
    assert runs_at_ten[0].result == "cycle_result"
    assert runs_at_fifteen == []


def test_behind_slot_reschedules_from_now_without_burst() -> None:
    """A delayed slot executes only once and schedules its next run from the current tick."""
    # In plain words: If ticks were missed or delayed, we do not perform multiple catch-up runs.
    # We execute exactly once and anchor the subsequent deadline to the current tick time.
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    slot = _create_slot(job_id="delayed_job", run=lambda: "catchup_run")
    scheduler.put(slot)
    scheduler.tick(INITIAL_TICK_TIME_S)

    delayed_runs = scheduler.tick(SIGNIFICANT_DELAY_TIME_S)

    assert len(delayed_runs) == 1
    assert delayed_runs[0].job_id == "delayed_job"
    updated_slot = scheduler.get("delayed_job")
    assert updated_slot is not None
    assert updated_slot.next_run_at == EXPECTED_NEXT_RUN_AFTER_DELAY_S


def _raise_boom() -> Any:
    """Raise a RuntimeError to simulate a crashing job run."""
    raise RuntimeError("boom")


def test_failing_job_does_not_stop_others() -> None:
    """A failing job records an error result while permitting subsequent jobs to execute."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    failing_slot = _create_slot(job_id="failing_slot", run=_raise_boom)
    healthy_slot = _create_slot(job_id="healthy_slot", run=lambda: "healthy_output")
    scheduler.put(failing_slot)
    scheduler.put(healthy_slot)

    runs = scheduler.tick(INITIAL_TICK_TIME_S)

    expected_runs = [
        JobRun(job_id="failing_slot", ok=False, result=None, error="boom"),
        JobRun(job_id="healthy_slot", ok=True, result="healthy_output", error=None),
    ]
    assert runs == expected_runs


def test_put_replaces_same_job_id() -> None:
    """Adding a slot with an existing job_id replaces the previous registration."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    original_slot = _create_slot(job_id="replaceable_job", run=lambda: "original")
    replacement_slot = _create_slot(job_id="replaceable_job", run=lambda: "replaced")

    scheduler.put(original_slot)
    scheduler.put(replacement_slot)

    assert scheduler.ids() == ["replaceable_job"]
    runs = scheduler.tick(INITIAL_TICK_TIME_S)
    assert len(runs) == 1
    assert runs[0].result == "replaced"


def test_remove_is_idempotent() -> None:
    """Removing a registered slot prevents execution, and removing an unknown ID succeeds."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    slot = _create_slot(job_id="disposable_job", run=lambda: "unreachable")
    scheduler.put(slot)

    scheduler.remove("disposable_job")
    runs = scheduler.tick(INITIAL_TICK_TIME_S)
    scheduler.remove("unknown_job_id")

    assert runs == []
    assert scheduler.get("disposable_job") is None


def test_get_and_ids_sorted() -> None:
    """The ids() method returns sorted identifiers, and get() retrieves existing slots."""
    clock = FakeClock(current_time_s=INITIAL_TICK_TIME_S)
    scheduler = Scheduler(now=clock)
    slot_b = _create_slot(job_id="b", run=lambda: "b")
    slot_a = _create_slot(job_id="a", run=lambda: "a")

    scheduler.put(slot_b)
    scheduler.put(slot_a)

    assert scheduler.ids() == ["a", "b"]
    assert scheduler.get("a") is slot_a
    assert scheduler.get("zz") is None
