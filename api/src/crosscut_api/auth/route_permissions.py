"""Route permission mapping for the Crosscut API.

Defines permission requirements for each API route, separating public routes from
those that require authentication or specific permissions.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sentinel indicating a valid session is sufficient; no specific permission needed.
AUTHENTICATED = "authenticated"


@dataclass(frozen=True)
class AnyOf:
    """A wrapper for alternative permission strings where any one suffices.

    Attributes:
        permissions: A tuple of permission identifiers; at least one must be
            present for the request to be authorized.
    """

    permissions: tuple[str, ...]


# A type representing either a single permission string or an AnyOf wrapper.
Requirement = str | AnyOf

# Public routes that bypass permission checks entirely.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/auth/login"), ("GET", "/auth/config"), ("GET", "/health")}
)

# Mapping from (HTTP method, path) to the required permission.
ROUTE_PERMISSIONS: dict[tuple[str, str], Requirement] = {
    # data.view (GET unless stated)
    ("GET", "/datasets"): "data.view",
    ("GET", "/datasets/{dataset_id}/tags"): "data.view",
    ("GET", "/datasets/{dataset_id}/series"): "data.view",
    ("GET", "/datasets/{dataset_id}/loops"): "data.view",
    ("GET", "/datasets/{dataset_id}/loops/{loop_name}/tuning"): "data.view",
    ("GET", "/datasets/{dataset_id}/loops/{loop_name}/benefit"): "data.view",
    ("GET", "/datasets/{dataset_id}/loops/{loop_name}/knowledge"): "data.view",
    ("GET", "/datasets/{dataset_id}/readiness"): "data.view",
    ("GET", "/fuzzy"): "data.view",
    ("GET", "/fuzzy/{system_id}"): "data.view",
    ("GET", "/fuzzy/{system_id}/versions"): "data.view",
    ("GET", "/fuzzy/{system_id}/versions/{version_id}"): "data.view",
    ("GET", "/supervisors"): "data.view",
    ("GET", "/supervisors/{sid}"): "data.view",
    ("GET", "/supervisors/{sid}/log"): "data.view",
    ("GET", "/anomaly"): "data.view",
    ("GET", "/anomaly/{aid}"): "data.view",
    ("GET", "/anomaly/{aid}/model"): "data.view",
    ("GET", "/softsensor"): "data.view",
    ("GET", "/softsensor/{sid}"): "data.view",
    ("GET", "/softsensor/{sid}/lab"): "data.view",
    ("GET", "/softsensor/{sid}/model"): "data.view",
    ("GET", "/site"): "data.view",
    ("GET", "/site/import-settings"): "data.view",
    ("GET", "/catalogue/mapping"): "data.view",
    ("GET", "/sources"): "data.view",
    ("GET", "/schemas"): "data.view",
    ("GET", "/schemas/{name}"): "data.view",
    ("GET", "/config/{kind}/{config_id}"): "data.view",
    ("GET", "/runtime/status"): "data.view",
    ("GET", "/runtime/log"): "data.view",
    ("GET", "/runtime/jobs"): "data.view",

    # analysis.run (POST)
    ("POST", "/fuzzy/diff"): "analysis.run",
    ("POST", "/fuzzy/infer"): "analysis.run",
    ("POST", "/fuzzy/matrix"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/fuzzy/replay"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/fuzzy/backtest"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/supervisor/{sid}/advise"): "analysis.run",
    ("POST", "/supervisors/{sid}/log/{advice_id}/ack"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/anomaly/{aid}/scan"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/softsensor/{sid}/run"): "analysis.run",
    ("POST", "/intake/preview"): "analysis.run",
    ("POST", "/intake/check"): "analysis.run",
    ("POST", "/catalogue/suggest"): "analysis.run",
    ("POST", "/valve-test/plan"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/loops/{loop_name}/valve-test/analyse"): "analysis.run",
    ("POST", "/valve-test/analyse-csv"): "analysis.run",
    ("POST", "/datasets/{dataset_id}/steps"): "analysis.run",

    # config.edit (PUT/POST)
    ("PUT", "/fuzzy/{system_id}"): "config.edit",
    ("PUT", "/supervisors/{sid}"): "config.edit",
    ("POST", "/datasets/{dataset_id}/supervisor/{sid}/replay"): "config.edit",
    ("PUT", "/anomaly/{aid}"): "config.edit",
    ("POST", "/datasets/{dataset_id}/anomaly/{aid}/fit"): "config.edit",
    ("PUT", "/softsensor/{sid}"): "config.edit",
    ("POST", "/softsensor/{sid}/lab"): "config.edit",
    ("POST", "/datasets/{dataset_id}/softsensor/{sid}/fit"): "config.edit",
    ("PUT", "/site"): "config.edit",
    ("PUT", "/catalogue/mapping"): "config.edit",
    ("PUT", "/config/{kind}/{config_id}"): "config.edit",
    ("PUT", "/datasets/{dataset_id}/loops/{loop_name}/knowledge"): "config.edit",

    # data.import (POST/DELETE)
    ("POST", "/intake/dataset"): "data.import",
    ("POST", "/intake/plant/upload"): "data.import",
    ("DELETE", "/intake/plant/upload/{upload_id}"): "data.import",
    ("POST", "/intake/plant/preview"): "data.import",
    ("POST", "/intake/plant/import"): "data.import",

    # connector.use (POST/GET)
    ("POST", "/sources/{source_id}/test"): "connector.use",
    ("GET", "/sources/{source_id}/browse"): "connector.use",
    ("POST", "/sources/{source_id}/read-live"): "connector.use",

    # job.manage (POST/PATCH/DELETE)
    ("POST", "/runtime/jobs"): "job.manage",
    ("PATCH", "/runtime/jobs/{job_id}"): "job.manage",
    ("DELETE", "/runtime/jobs/{job_id}"): "job.manage",
    ("POST", "/runtime/jobs/{job_id}/start"): "job.manage",

    # job.stop (POST)
    ("POST", "/runtime/jobs/{job_id}/stop"): "job.stop",

    # gateway (various)
    ("GET", "/gateway/status"): "gw.view",
    ("GET", "/gateway/pending"): "gw.view",
    ("GET", "/gateway/audit"): "audit.view",
    ("POST", "/gateway/pending/{key}/approve"): "gw.approve",
    ("POST", "/gateway/pending/{key}/reject"): "gw.reject",
    ("POST", "/gateway/kill"): "gw.kill",
    ("POST", "/gateway/kill/reset"): "gw.kill.reset",
    ("PUT", "/gateway/mode"): AnyOf(
        (
            "gw.mode.down",
            "gw.mode.up.advisory",
            "gw.mode.up.dry_run",
            "gw.mode.up.confirm",
            "gw.mode.up.supervised",
        )
    ),
    ("POST", "/gateway/targets/{tag}/re-enable"): AnyOf(
        ("gw.re_enable.hold_off", "gw.re_enable.stopped")
    ),
    ("GET", "/gateway/policy/draft"): "policy.edit",
    ("PUT", "/gateway/policy/draft"): "policy.edit",
    ("POST", "/gateway/policy/pin"): "policy.pin",
    ("POST", "/gateway/policy/reload"): "policy.reload",

    # auth (authenticated)
    ("POST", "/auth/logout"): AUTHENTICATED,
    ("GET", "/auth/me"): AUTHENTICATED,
    ("POST", "/auth/password"): AUTHENTICATED,
    ("POST", "/auth/stepup"): AUTHENTICATED,

    # auth (users.manage)
    ("GET", "/auth/users"): "users.manage",
    ("GET", "/auth/users/{username}"): "users.manage",
    ("POST", "/auth/users"): "users.manage",
    ("PATCH", "/auth/users/{username}"): "users.manage",
    ("DELETE", "/auth/users/{username}"): "users.manage",
}


def requirement_for(method: str, path: str) -> Requirement | None:
    """Return the permission requirement for the given HTTP method and path.

    The ``method`` argument is case‑insensitive; it is normalised to upper case
    before lookup. If the (method, path) pair is not present in
    :data:`ROUTE_PERMISSIONS`, ``None`` is returned.

    Args:
        method: The HTTP method (e.g. ``"GET"`` or ``"POST"``).
        path: The exact route path as defined in FastAPI.

    Returns:
        The permission requirement associated with the route, or ``None`` if the
        route is public or otherwise not listed.
    """
    return ROUTE_PERMISSIONS.get((method.upper(), path))
