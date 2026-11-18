"""Read PI Web API points without granting write access.

Transport injection keeps recorded synthetic responses independent of a PI server.
"""

from __future__ import annotations

import base64
import json
import math
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_HISTORY,
    CAP_METADATA,
    CAP_READ_LIVE,
    LiveValue,
    NodeInfo,
    Snapshot,
    SourceConnectionError,
    TagMetadata,
)
from crosscut_connectors.site import Limits, SiteImportSettings, TagSettings

TIMEOUT_S = 30  # Seconds per HTTP request.
PAGE_SIZE = 1000  # Events per recorded request, including the continuation boundary.
GOOD, UNCERTAIN, BAD = 0, 1, 2
Transport = Callable[[Request, float], Mapping[str, Any]]


class _NoRedirect(HTTPRedirectHandler):
    """Prevent credentials from following a redirect to another server."""

    def http_response(self, request: Request, response: Any) -> Any:
        """Reject redirects before urllib can forward an Authorization header."""
        if 300 <= response.status < 400:
            response.close()
            raise SourceConnectionError("PI Web API redirected; configure its final base_url")
        return response

    https_response = http_response


def _http_get(request: Request, timeout: float) -> Mapping[str, Any]:
    """Decode one GET response; urllib enforces TLS certificate validation."""
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        return json.load(response)


def _headers(auth: Mapping[str, Any]) -> dict[str, str]:
    """Resolve credentials at runtime without including their values in errors."""
    headers = {"Accept": "application/json"}
    if set(auth) - {"kind", "credential_env"}:
        raise ValueError("PI auth accepts only kind and credential_env; remove inline credentials")
    kind = auth.get("kind")
    if kind is None or kind == "kerberos":
        return headers
    if kind not in {"basic", "bearer"}:
        raise ValueError("PI auth kind must be basic, kerberos or bearer")
    variable = auth.get("credential_env", "")
    credential = os.environ.get(variable)
    if not credential:
        raise SourceConnectionError("Set the PI auth credential_env environment variable")
    if kind == "basic":
        credential = base64.b64encode(credential.encode()).decode("ascii")
    headers["Authorization"] = f"{'Basic' if kind == 'basic' else 'Bearer'} {credential}"
    return headers


def _reason(sample: Mapping[str, Any]) -> str | None:
    """Preserve PI system digital state names rather than treating them as numbers."""
    value = sample.get("Value")
    if isinstance(value, dict) and value.get("IsSystem", False):
        return str(value.get("Name", "PI system digital state"))
    if sample.get("Good") is False:
        return "PI Good=false"
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "PI value is not a finite number"
    return None


def _live_value(sample: Mapping[str, Any], settings: TagSettings | None = None) -> LiveValue:
    """Map PI flags to 0 good, 1 uncertain, 2 bad; bad overrides uncertain.

    A numeric value equal to a missing code the site declares is read as no value with BAD.
    """
    reason = _reason(sample)
    quality = UNCERTAIN if sample.get("Questionable") or sample.get("Substituted") else GOOD
    value = None if reason else float(sample["Value"])
    if value is not None and settings is not None and settings.is_missing_number(value):
        value, quality = None, BAD
    return LiveValue(value, BAD if reason else quality, str(sample.get("Timestamp", "")))


def _metadata(
    tag: str, point: Mapping[str, Any], settings: TagSettings | None = None
) -> TagMetadata:
    """Convert PI Zero and Span to engineering limits in the point's units.

    The site unit and engineering limits win over the point's own values when declared.
    """
    zero, span = point.get("Zero"), point.get("Span")
    # PI span is a width: upper engineering limit = zero + span, in engineering units.
    upper = zero + span if zero is not None and span is not None else None
    site_unit = settings.unit if settings is not None else ""
    unit = site_unit or point.get("EngineeringUnits")
    low, high = _site_limits(settings, zero, upper)
    return TagMetadata(tag, unit, point.get("Descriptor"), low, high)


def _site_limits(
    settings: TagSettings | None, low: float | None, high: float | None
) -> tuple[float | None, float | None]:
    """Engineering limits from the site when declared, else the point's Zero and Zero+Span."""
    limits: Limits | None = settings.eng_limits if settings is not None else None
    if limits is None:
        return low, high
    return limits.low if limits.low is not None else low, (
        limits.high if limits.high is not None else high
    )


class PiWebApiConnector:
    """Read-only PI adapter using point WebIds as tag identifiers."""

    def __init__(self, endpoint: str, options: Mapping[str, Any] | None = None,
                 transport: Transport | None = None,
                 settings: SiteImportSettings | None = None) -> None:
        """Configure read requests; reject unsupported authentication and invalid page sizes.

        ``settings`` is the site settings read through ``site.read_import_settings``; it
        supplies missing codes, units, engineering limits and sampling periods.
        """
        self.options = dict(options or {})
        self.settings = settings
        self.endpoint = str(self.options.get("base_url", endpoint)).rstrip("/")
        address = urlsplit(self.endpoint)
        if (address.scheme not in {"http", "https"} or not address.hostname
                or address.username is not None or address.query or address.fragment):
            raise ValueError("PI base_url must be an HTTP(S) URL without credentials")
        self.transport = transport or _http_get
        if self.options.get("auth", {}).get("kind") == "kerberos" and transport is None:
            raise SourceConnectionError("PI Kerberos requires an injected Negotiate GET transport")
        self.page_size = int(self.options.get("max_count", PAGE_SIZE))
        if self.page_size < 2:
            raise ValueError("PI max_count must be at least 2 for boundary continuation")

    def capabilities(self) -> set[str]:
        """Return the four supported read capabilities."""
        return {CAP_BROWSE, CAP_METADATA, CAP_HISTORY, CAP_READ_LIVE}

    def _get(self, path: str, parameters: Sequence[tuple[str, Any]] = ()) -> Mapping[str, Any]:
        url = f"{self.endpoint}/{path}?{urlencode(parameters)}"
        request = Request(url, headers=_headers(self.options.get("auth", {})), method="GET")
        try:
            return self.transport(request, TIMEOUT_S)
        except HTTPError as error:
            raise SourceConnectionError(
                f"PI Web API HTTP {error.code}; check authentication and read permissions"
            ) from None
        except (TimeoutError, URLError, OSError) as error:
            raise SourceConnectionError(
                "PI Web API timeout or connection failure; check server"
            ) from error
        except (ValueError, TypeError) as error:
            raise SourceConnectionError("PI Web API returned invalid JSON; check server") from error

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """List data servers, or points on a configured or selected server."""
        server = node_id or self.options.get("web_id")
        if not server and self.options.get("data_server"):
            servers = self._get("dataservers")["Items"]
            server = next((item["WebId"] for item in servers
                           if item["Name"] == self.options["data_server"]), None)
            if server is None:
                raise SourceConnectionError("PI data_server was not found; check its name")
        path = f"dataservers/{quote(str(server), safe='')}/points" if server else "dataservers"
        parameters = [("nameFilter", self.options.get("name_filter", "*"))] if server else []
        items = self._get(path, parameters)["Items"]
        return [NodeInfo(item["WebId"], item["Name"], "variable" if server else "folder",
                         not bool(server), item.get("PointType"), item.get("EngineeringUnits"))
                for item in items]

    def _tag_settings(self, tag: str) -> TagSettings | None:
        """The site settings of one tag, or None when no site file was read."""
        return self.settings.for_tag(tag) if self.settings is not None else None

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Fetch point descriptions, units and engineering limits."""
        return [
            _metadata(tag, self._get(f"points/{quote(tag, safe='')}"), self._tag_settings(tag))
            for tag in tag_ids
        ]

    def history(self, tag_ids: Sequence[str], start_utc: str, end_utc: str,
                period_s: float | None = None) -> Mapping[str, Any]:
        """Return tag-keyed sample dictionaries, retaining quality and bad-state reasons.

        A ``period_s`` of None uses the sampling period the site declares for each tag.
        """
        if period_s is not None and (not math.isfinite(period_s) or period_s <= 0):
            raise ValueError("PI period_s must be finite and positive seconds")
        parameters = [("startTime", start_utc), ("endTime", end_utc)]
        result = {}
        for tag in tag_ids:
            result[tag] = self._tag_history(tag, parameters, period_s)
        return result

    def _tag_history(self, tag: str, parameters: list[tuple[str, Any]],
                     period_s: float | None) -> list[dict[str, Any]]:
        """Read one tag's history, interpolated when a period applies."""
        settings = self._tag_settings(tag)
        period = period_s if period_s is not None else (
            settings.sample_period_s if settings is not None else None)
        path = f"streams/{quote(tag, safe='')}"
        if period is None:
            samples = self._recorded(path, parameters)
        else:
            samples = self._get(f"{path}/interpolated",
                                [*parameters, ("interval", f"{period}s")])["Items"]
        return [_history_sample(sample, settings) for sample in samples]

    def _recorded(self, path: str, parameters: list[tuple[str, Any]]) -> list[Mapping[str, Any]]:
        samples: list[Mapping[str, Any]] = []
        cursor = parameters[0][1]
        while True:
            page = self._get(f"{path}/recorded", [("startTime", cursor), parameters[1],
                             ("maxCount", self.page_size), ("boundaryType", "Inside")])["Items"]
            # PI includes the start boundary again; remove only that repeated event.
            samples.extend(page[1:] if samples and page and page[0] == samples[-1] else page)
            if len(page) < self.page_size:
                return samples
            following = page[-1]["Timestamp"]
            if following == cursor:
                raise SourceConnectionError("PI history paging stalled at one timestamp")
            cursor = following

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Read all requested WebIds in a single GET; failures raise clear errors."""
        return self._batch(tag_ids)[0]

    def _batch(self, tag_ids: Sequence[str]) -> tuple[dict[str, LiveValue], str | None]:
        if not tag_ids:
            return {}, None
        items = self._get("streamsets/value", [("webId", tag) for tag in tag_ids])["Items"]
        samples = {item["WebId"]: item["Value"] for item in items}
        values, reasons = {}, []
        for tag in tag_ids:
            sample = samples.get(tag, {"Good": False})
            values[tag] = _live_value(sample, self._tag_settings(tag))
            reason = _reason(sample)
            if reason:
                reasons.append(f"{tag}: {reason}")
        return values, "; ".join(reasons) or None

    def read_snapshot(self, tag_ids: Sequence[str]) -> Snapshot:
        """Return a batch snapshot; communication loss marks every requested tag bad."""
        cycle = datetime.now(UTC).isoformat()
        try:
            values, reason = self._batch(tag_ids)
            return Snapshot(cycle, values, True, reason)
        except SourceConnectionError as error:
            values = {tag: LiveValue(None, BAD, cycle) for tag in tag_ids}
            return Snapshot(cycle, values, False, str(error))


def _history_sample(
    sample: Mapping[str, Any], settings: TagSettings | None = None
) -> dict[str, Any]:
    """Keep history and live quality semantics identical."""
    value = _live_value(sample, settings)
    return {"timestamp_utc": value.timestamp_utc, "value": value.value,
            "quality": value.quality, "reason": _reason(sample)}
