"""Log export for the Health page (issue #170): a zip of the application logs of a time range.

Sources: the rotating files ``<root>/_logs/*.log*`` (api, runtime, gateway; see
``crosscut_runtime.logsetup``) and the runtime job log ``<root>/_runtime/log.jsonl``. Lines are
cut to ``[start, end]`` by their time stamp (a line without one, such as a traceback, follows the
line above it) and scrubbed of secrets before they are written to the archive.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOG_FOLDER = "_logs"
RUNTIME_LOG = Path("_runtime") / "log.jsonl"
MASK = "[redacted]"
_SECRET_WORDS = (
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|hmac[_-]?key|private[_-]?key"
    r"|credential)"
)
_NAME = rf"[\w.-]*{_SECRET_WORDS}[\w.-]*\\*[\"']?\s*[:=]\s*"
# "name": "va\"lue" (also inside a JSON-escaped message: \"name\": \"value\"): the value runs to
# the first unescaped quote and may hold spaces and escapes, so a secret is never cut in the middle.
_QUOTED = re.compile(rf"(?i)(?P<name>{_NAME}\\*[\"'])(?P<value>(?:\\.|[^\"'\\])*)")
# ODBC / SQL style PWD={a;b}; the braces may hold semicolons.
_BRACED = re.compile(rf"(?i)(?P<name>{_NAME}\{{)(?P<value>[^}}]*)")
# name = value / name: value; the value stops at whitespace, quote, comma, semicolon or }.
_ASSIGNMENT = re.compile(rf"(?i)(?P<name>{_NAME})(?P<value>[^\s\"',;}}&]+)")
# .netrc: machine host login user password secret
_NETRC = re.compile(r"(?i)(?P<name>\bmachine\s+\S+\s+login\s+\S+\s+password\s+)(?P<value>\S+)")
_AUTH_HEADER = re.compile(
    r"(?i)(?P<name>\bauthorization\s*[:=]\s*(?:bearer|basic)?\s*)(?P<value>[^\s\"',;]+)"
)
_COOKIE = re.compile(
    r"(?i)(?P<name>\b(?:cc_session|session|set-cookie|cookie)\s*[:=]\s*)(?P<value>[^\s\"',;]+)"
)
# scheme://user:pass@host for any scheme (opc.tcp, https, postgresql); the password may hold "@".
_URL_CREDENTIALS = re.compile(
    r"(?P<name>[a-z][a-z0-9+.-]*://[^\s/:@]+:)(?P<value>[^\s/]+)(?=@)", re.I
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S
)
_PATTERNS = (
    _PRIVATE_KEY, _URL_CREDENTIALS, _NETRC, _AUTH_HEADER, _COOKIE, _QUOTED, _BRACED, _ASSIGNMENT,
)
MAX_SPAN = timedelta(days=31)
MAX_BYTES = 100 * 2**20  # scrubbed text of all files together, before compression
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


class LogRangeError(ValueError):
    """The requested time range is empty or not a date."""


def scrub(text: str) -> str:
    """Replace the secret values in ``text`` (passwords, tokens, keys, cookies, URL credentials)."""
    for pattern in _PATTERNS:
        if pattern is _PRIVATE_KEY:
            text = pattern.sub(MASK, text)
        else:
            text = pattern.sub(lambda m: m.group("name") + MASK, text)
    return text


def parse_instant(value: str) -> datetime:
    """An ISO 8601 time as an aware UTC datetime; naive values are taken as UTC."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LogRangeError(f"not an ISO time: {value!r}") from error
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _line_time(line: str) -> datetime | None:
    """The UTC time stamp of a text log line or a JSON log line; ``None`` when it has none."""
    if line.startswith("{"):
        try:
            stamp = json.loads(line).get("ts")
        except (ValueError, AttributeError):
            return None
        try:
            return parse_instant(stamp) if isinstance(stamp, str) else None
        except LogRangeError:
            return None
    found = _STAMP.match(line)
    return datetime.fromisoformat(found.group(1)).replace(tzinfo=UTC) if found else None


def select_lines(text: str, start: datetime, end: datetime) -> str:
    """The lines of ``text`` stamped within ``[start, end]``; unstamped lines follow their line."""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        moment = _line_time(line)
        if moment is not None:
            inside = start <= moment <= end
        if inside:
            kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")


def log_files(root: Path) -> list[Path]:
    """The application log files that exist: rotated ``_logs`` files and the runtime job log."""
    found = sorted((root / LOG_FOLDER).glob("*.log*")) if (root / LOG_FOLDER).is_dir() else []
    runtime = root / RUNTIME_LOG
    return found + ([runtime] if runtime.is_file() else [])


def _archive_name(root: Path, path: Path) -> str:
    """Name of a file inside the archive: its path relative to the data root."""
    return path.relative_to(root).as_posix()


def build_export(root: Path, start: datetime, end: datetime) -> tuple[bytes, list[str]]:
    """A zip with the scrubbed lines of every log file in the range; also the member names."""
    if end < start:
        raise LogRangeError("the end of the range is before its start")
    if end - start > MAX_SPAN:
        raise LogRangeError(f"the range is longer than {MAX_SPAN.days} days; narrow it")
    buffer = io.BytesIO()
    names: list[str] = []
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in log_files(root):
            text = path.read_text(encoding="utf-8", errors="replace")
            cleaned = scrub(select_lines(text, start, end))
            total += len(cleaned.encode("utf-8"))
            if total > MAX_BYTES:
                raise LogRangeError(
                    f"the logs of this range exceed {MAX_BYTES // 2**20} MB; narrow the range"
                )
            archive.writestr(_archive_name(root, path), cleaned)
            names.append(_archive_name(root, path))
        archive.writestr("README.txt", _readme(start, end, names))
    return buffer.getvalue(), names


def _readme(start: datetime, end: datetime, names: list[str]) -> str:
    """Short description of what the archive holds."""
    listing = "\n".join(f"- {name}" for name in names) or "- (no log files exist yet)"
    return (
        "Crosscut log export\n"
        f"Range (UTC): {start.isoformat()} .. {end.isoformat()}\n"
        "Secrets (passwords, tokens, keys, cookies) are replaced by [redacted].\n"
        f"Files:\n{listing}\n"
    )
