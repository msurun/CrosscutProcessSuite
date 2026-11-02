"""Runtime state store: jobs, state and log under <data root>/_runtime/ (Phase 1, #44).

The runtime service and the API process exchange state through these three small files,
so both can crash independently and restart without losing the deployment.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RUNTIME_FOLDER = "_runtime"
JOBS_FILE = "jobs.json"
STATE_FILE = "state.json"
LOG_FILE = "log.jsonl"
JOBS_SCHEMA_FILE = "job.schema.json"
SCHEMAS_ENV_VAR = "CROSSCUT_SCHEMAS_DIR"


def schemas_dir() -> Path:
    """Directory holding schemas/*.schema.json; CROSSCUT_SCHEMAS_DIR wins."""
    if schemas_path := os.getenv(SCHEMAS_ENV_VAR):
        return Path(schemas_path)
    return Path(__file__).resolve().parents[3] / "schemas"


class JobStoreError(ValueError):
    """The jobs document does not pass validation."""


def empty_jobs_document() -> dict[str, Any]:
    """Return an empty jobs document."""
    return {"schema_version": 1, "jobs": []}


def job_problems(document: dict[str, Any]) -> list[str]:
    """Problems of one jobs document against schemas/job.schema.json."""
    schema_path = schemas_dir() / JOBS_SCHEMA_FILE
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [f"{_where(error.absolute_path)}: {error.message}" for error in errors]


def _where(path: Any) -> str:
    """A dotted location such as ``jobs.3.id`` ("jobs" for the document itself)."""
    return ".".join(str(part) for part in path) or "jobs"


class RuntimeStore:
    """File layout under <root>/_runtime/: jobs.json, state.json, log.jsonl."""

    def __init__(self, root: Path) -> None:
        """Initialize the store with the data root."""
        self.root = root

    @property
    def dir(self) -> Path:
        """Directory holding the runtime files."""
        return self.root / RUNTIME_FOLDER

    def jobs_path(self) -> Path:
        """Path to the jobs file."""
        return self.dir / JOBS_FILE

    def state_path(self) -> Path:
        """Path to the state file."""
        return self.dir / STATE_FILE

    def log_path(self) -> Path:
        """Path to the log file."""
        return self.dir / LOG_FILE

    def load_jobs(self) -> dict[str, Any]:
        """Load the jobs document, or an empty one when the file is missing."""
        path = self.jobs_path()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_jobs_document()
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            return empty_jobs_document()
        if not isinstance(document, dict):
            return empty_jobs_document()
        return document

    def save_jobs(self, document: dict[str, Any]) -> None:
        """Validate and write the jobs file atomically."""
        problems = job_problems(document)
        if problems:
            raise JobStoreError("; ".join(problems))
        path = self.jobs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temp_name, path)
        except Exception:
            os.unlink(temp_name)
            raise

    def load_state(self) -> dict[str, Any]:
        """Load the state document, or an empty one when the file is missing or corrupt."""
        path = self.state_path()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            state = json.loads(text)
        except json.JSONDecodeError:
            logging.getLogger(__name__).warning("Corrupt state file: %s", path)
            return {}
        if not isinstance(state, dict):
            logging.getLogger(__name__).warning("State file is not a JSON object: %s", path)
            return {}
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        """Write the state file atomically."""
        path = self.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(state, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temp_name, path)
        except Exception:
            os.unlink(temp_name)
            raise

    def append_log(self, level: str, message: str, job_id: str | None = None) -> None:
        """Append a JSON line to the log; failures are logged but not raised."""
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
        }
        if job_id is not None:
            entry["job"] = job_id
        path = self.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(entry) + "\n")
        except OSError as error:
            logging.getLogger(__name__).warning("Failed to write log: %s", error)

    def read_log(self, limit: int = 200) -> list[dict[str, Any]]:
        """Read the last `limit` lines of the log file."""
        path = self.log_path()
        try:
            with path.open("r", encoding="utf-8") as stream:
                lines = stream.readlines()[-limit:]
        except FileNotFoundError:
            return []
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logging.getLogger(__name__).warning("Corrupt log line: %s", line)
        return entries
