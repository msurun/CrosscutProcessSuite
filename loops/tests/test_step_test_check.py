"""Step-test intake: check_step_test, the CSV readers and the step_test_cli commands."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
from crosscut_loops.project_loops import loops_from_project
from crosscut_loops.step_test_check import check_step_test
from crosscut_loops.step_test_cli import main

DT = 10.0
START = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)


def make_signals(n=720, move_at=2400.0, back_at=4200.0, dt=DT, step=5.0):
    """t, OUT (doublet) and PV of an integrator with 30 s dead time and a little noise."""
    t = np.arange(n) * dt
    out = 50.0 + step * ((t >= move_at) & (t < back_at))
    delayed = np.concatenate([np.full(3, out[0]), out[:-3]])
    pv = 40.0 + 0.002 * dt * np.cumsum(delayed - out[0])
    return t, out, pv + np.random.default_rng(1).normal(0.0, 0.02, n)


def write_wide(path, t, out, pv, delimiter=",", decimal=".", iso=True):
    """Write a wide historian CSV with PV, OUT and MODE columns."""
    lines = [delimiter.join(["timestamp", "LIC1.PV", "LIC1.OUT", "LIC1.MODE"])]
    for ti, o, p in zip(t, out, pv, strict=True):
        stamp = (START + timedelta(seconds=float(ti))).isoformat() if iso else f"{ti:.0f}"
        fmt = lambda x: f"{x:.4f}".replace(".", decimal)  # noqa: E731
        lines.append(delimiter.join([stamp, fmt(p), fmt(o), "MAN"]))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_long(path, t, out, pv):
    """Write a long CSV (timestamp, tag, value, quality) with change-only rows for OUT."""
    rows = ["timestamp,tag,value,quality"]
    for i, ti in enumerate(t):
        stamp = (START + timedelta(seconds=float(ti))).isoformat()
        rows.append(f"{stamp},LIC1.PV,{pv[i]:.4f},Good")
        if i == 0 or out[i] != out[i - 1]:
            rows.append(f"{stamp},LIC1.OUT,{out[i]:.3f},Good")
        rows.append(f"{stamp},OTHER.TAG,1.0,Good")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


COLS = ["--time-col", "timestamp", "--pv-col", "LIC1.PV", "--out-col", "LIC1.OUT"]


def codes(result):
    """Finding codes of a check."""
    return {f.code for f in result.findings}


def test_good_record_is_ready_and_dry_run_ok():
    t, out, pv = make_signals()
    result = check_step_test(t, out, pv, mode=np.zeros(len(t)))
    assert result.verdict == "ready"
    assert result.dry_run.verdict == "ok"
    assert result.n_out_moves == 2
    assert result.dry_run.delay_upper_s >= result.dry_run.delay_s


def test_short_lead_gives_finding_and_cli_says_how_long(tmp_path, capsys):
    t, out, pv = make_signals(move_at=300.0, back_at=3000.0)
    result = check_step_test(t, out, pv)
    assert "lead_too_short" in codes(result)
    assert result.verdict == "not_usable"
    path = write_wide(tmp_path / "a.csv", t, out, pv)
    assert main(["check", str(path), *COLS]) == 1
    assert "of quiet time" in capsys.readouterr().out


def test_no_out_move_is_not_usable():
    t, out, pv = make_signals(step=0.0)
    result = check_step_test(t, out, pv)
    assert "no_out_move" in codes(result)
    assert result.verdict == "not_usable"
    assert result.dry_run is None


def test_too_short_after_last_move():
    t, out, pv = make_signals(n=400, back_at=3900.0)
    result = check_step_test(t, out, pv)
    assert "post_move_too_short" in codes(result)
    assert result.verdict == "not_usable"


def test_closed_loop_mode_is_not_usable():
    t, out, pv = make_signals()
    result = check_step_test(t, out, pv, mode=np.ones(len(t)))
    assert "not_in_manual" in codes(result)
    assert result.verdict == "not_usable"


def test_long_layout_gives_same_verdict_as_wide(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_long(tmp_path / "long.csv", t, out, pv)
    args = ["check", str(path), "--tag-pv", "LIC1.PV", "--tag-out", "LIC1.OUT", "--json"]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["check"]["verdict"] == "ready"
    assert "layout long" in data["read_as"][0]


def test_long_layout_without_tags_lists_them(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_long(tmp_path / "long.csv", t, out, pv)
    assert main(["check", str(path)]) == 2
    assert "LIC1.OUT" in capsys.readouterr().err


def test_decimal_comma_and_semicolon(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_wide(tmp_path / "eu.csv", t, out, pv, delimiter=";", decimal=",")
    assert main(["check", str(path), *COLS, "--mode-col", "LIC1.MODE", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["check"]["verdict"] == "ready"
    assert "decimal ','" in data["read_as"][0]


def test_seconds_time_column(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_wide(tmp_path / "s.csv", t, out, pv, iso=False)
    assert main(["check", str(path), *COLS, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["check"]["verdict"] == "ready"


def test_missing_column_is_a_readable_error(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_wide(tmp_path / "a.csv", t, out, pv)
    assert main(["check", str(path), "--pv-col", "NOPE", "--out-col", "LIC1.OUT"]) == 2
    assert "not found" in capsys.readouterr().err


def make_dataset(tmp_path, name="ds"):
    """Run make-dataset on a good record; return (exit code, dataset dir)."""
    t, out, pv = make_signals()
    csv_path = write_wide(tmp_path / "in.csv", t, out, pv)
    target = tmp_path / "root" / name
    code = main(["make-dataset", str(csv_path), *COLS, "--out", str(target)])
    return code, target


def test_make_dataset_loads_and_marks_integrating(tmp_path, capsys):
    code, target = make_dataset(tmp_path)
    assert code == 0
    assert "UTC" in capsys.readouterr().out
    project = json.loads((target / "project.json").read_text(encoding="utf-8"))
    tags = json.loads((target / "tags.json").read_text(encoding="utf-8"))["tags"]
    loops = loops_from_project(project, tags)
    assert [lp.name for lp in loops] == ["LIC1"]
    assert loops[0].process_kind == "integrating"
    assert (target / "dataset.json").exists()


def test_make_dataset_refuses_to_overwrite(tmp_path, capsys):
    _, target = make_dataset(tmp_path)
    capsys.readouterr()
    code, _ = make_dataset(tmp_path)
    assert code == 2
    assert "already exists" in capsys.readouterr().err


def test_json_output_parses(tmp_path, capsys):
    t, out, pv = make_signals()
    path = write_wide(tmp_path / "a.csv", t, out, pv)
    main(["check", str(path), *COLS, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["check"]["dry_run"]["verdict"] == "ok"
    assert isinstance(data["check"]["findings"], list)


def test_uneven_sampling_is_flagged():
    t, out, pv = make_signals()
    keep = np.ones(len(t), bool)
    keep[100:140] = False
    result = check_step_test(t[keep], out[keep], pv[keep])
    assert result.uneven_sampling
    assert "uneven_sampling" in codes(result)


def test_findings_carry_the_figures_behind_their_texts():
    t, out, pv = make_signals(move_at=300.0, back_at=3000.0)
    by_code = {f.code: f for f in check_step_test(t, out, pv).findings}
    lead = by_code["lead_too_short"].params
    assert set(lead) == {"share", "lead_s", "min_share", "need_s"} and lead["share"] < 0.2
    t, out, pv = make_signals(n=400, back_at=3900.0)
    post = {f.code: f for f in check_step_test(t, out, pv).findings}["post_move_too_short"]
    assert post.params["basis"] in {"fit", "floor"}
    assert post.params["need_s"] > post.params["post_s"]
    flat = {f.code: f for f in check_step_test(*make_signals(step=0.0)).findings}
    assert flat["no_out_move"].params["min_range"] > 0
    closed = check_step_test(t, out, pv, mode=np.ones(len(t)))
    manual = {f.code: f for f in closed.findings}["not_in_manual"]
    assert manual.params == {"share": 0.0, "closed_loop": True}


def test_read_notes_have_stable_codes_and_params(tmp_path):
    from crosscut_loops.step_test_io import ReadOptions, read_record

    t, out, pv = make_signals()
    path = write_wide(tmp_path / "eu.csv", t, out, pv, delimiter=";", decimal=",", iso=False)
    opts = ReadOptions(time_col="timestamp", pv_col="LIC1.PV", out_col="LIC1.OUT")
    note = read_record(path, opts).notes[0]
    assert note.code == "read_wide" and note.text.startswith("layout wide")
    assert note.params == {"time": "relative", "decimal": ",", "delimiter": ";"}
