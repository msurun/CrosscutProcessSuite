"""Propose operating modes and equipment groups from history (PRODUCT 3.1, #145).

Pure functions over aligned arrays; nothing is read from or written to a plant. Every proposal
carries evidence (share of time, thresholds, example windows) and a confidence, and the engineer
accepts, edits or rejects it in the GUI. Time ``t_s`` is seconds since the first sample.

Model. A machine activity tag (speed, current, power) is bimodal: a stopped cluster and a running
cluster. Otsu's method picks the split that maximises the between-class variance; the share of
total variance it explains (``separation``, 0..1) says how clear the two clusters are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_connectors.condition_signals import propose_kind

Doc = dict[str, Any]

MIN_SAMPLES = 50  # fewer finite samples give no stable histogram
MIN_CLUSTER_SHARE = 0.03  # each cluster must hold this share of the samples
MIN_SEPARATION = 0.75  # unimodal data explains about 0.64 of variance at best
HIGH_SEPARATION = 0.9
HISTOGRAM_BINS = 100
HIGH_QUANTILE = 0.9  # upper band of the running throughput
RAMP_FRACTION = 0.9  # a start-up ends at this fraction of the way to the running median
MIN_RAMP_SAMPLES = 2  # a one-sample jump is a step, not a ramp
MIN_RAMPS = 2  # fewer start-ups do not make a start-up mode
MIN_BAND_SAMPLES = 500
CORRELATION_LINK = 0.85
STRONG_CORRELATION = 0.95
STRONG_OVERLAP = 0.8
SWITCH_TOLERANCE = 2  # samples within which two switches count as simultaneous
SWITCH_LINK = 0.6
MAX_WINDOWS = 3
ACTIVITY_KINDS = ("speed", "current", "power")
THROUGHPUT_WORDS = ("FLOW", "FEED", "TPH", "THROUGHPUT")


@dataclass(frozen=True)
class Split:
    """A two-cluster split of one tag: threshold in the empty gap, clarity and cluster shares."""

    threshold: float
    separation: float
    gap: tuple[float, float]  # highest stopped value, lowest running value
    low_share: float


def split_threshold(x: np.ndarray) -> Split | None:
    """Otsu split of the finite values, or None when the tag is not clearly bimodal."""
    finite = x[np.isfinite(x)]
    if finite.size < MIN_SAMPLES or np.ptp(finite) == 0:
        return None
    counts, edges = np.histogram(finite, bins=HISTOGRAM_BINS)
    centers = (edges[:-1] + edges[1:]) / 2
    below = np.cumsum(counts)
    moment = np.cumsum(counts * centers)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap_of_means = moment / below - (moment[-1] - moment) / (finite.size - below)
        between = below * (finite.size - below) * gap_of_means**2 / finite.size**2
    between = np.nan_to_num(between)
    k = int(np.argmax(between))
    low, high = finite[finite <= edges[k + 1]], finite[finite > edges[k + 1]]
    if low.size == 0 or high.size == 0:
        return None
    split = Split(
        threshold=float((low.max() + high.min()) / 2),
        separation=float(between[k] / finite.var()),
        gap=(float(low.max()), float(high.min())),
        low_share=low.size / finite.size,
    )
    clear = min(split.low_share, 1 - split.low_share) >= MIN_CLUSTER_SHARE
    return split if clear and split.separation >= MIN_SEPARATION else None


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """First and last index of every run of True values."""
    edges = np.diff(np.concatenate(([0], mask.astype(int), [0])))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1, strict=True))


def _windows(t_s: np.ndarray, runs: list[tuple[int, int]]) -> list[list[float]]:
    """The longest runs as [start, end] seconds, in time order, at most MAX_WINDOWS."""
    longest = sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:MAX_WINDOWS]
    return [[float(t_s[a]), float(t_s[b])] for a, b in sorted(longest)]


def _evidence(kind: str, mask: np.ndarray, t_s: np.ndarray, thresholds: Doc, detail: str) -> Doc:
    """Evidence of a mode that holds where ``mask`` is True: share of time and example windows."""
    runs = _runs(mask)
    return {
        "kind": kind,
        "share": round(float(np.mean(mask)), 4),
        "thresholds": thresholds,
        "windows": _windows(t_s, runs),
        "events": len(runs),
        "detail": detail,
    }


def _clause(tag: str, op: str, value: float) -> Doc:
    """One condition clause; the value is rounded to 4 significant digits for readability."""
    return {"tag": tag, "op": op, "value": float(f"{value:.4g}")}


def _mode(scope: str, suffix: str, clauses: list[Doc], confidence: str, evidence: Doc) -> Doc:
    """A mode proposal: the catalogue entry plus its confidence and evidence."""
    label = suffix.replace("_", " ")
    entry = {
        "id": f"{scope}_{suffix}",
        "name": f"{scope} {label}",
        "scope": scope,
        "condition": {"match": "all", "clauses": clauses},
    }
    return {"id": entry["id"], "entry": entry, "confidence": confidence, "evidence": evidence}


def _startups(x: np.ndarray, split: Split) -> tuple[float, list[tuple[int, int]]]:
    """Top of the ramp and the (last stopped sample, ramp top reached) indices of each start-up."""
    running = x > split.threshold
    top = split.threshold + RAMP_FRACTION * (float(np.median(x[running])) - split.threshold)
    found = []
    for i in np.flatnonzero(running[1:] & ~running[:-1]) + 1:
        reached = np.flatnonzero(x[i:] >= top)
        if reached.size and reached[0] >= MIN_RAMP_SAMPLES:
            found.append((int(i - 1), int(i + reached[0])))
    return top, found


def _stopped(scope: str, tag: str, t_s: np.ndarray, x: np.ndarray, split: Split) -> Doc:
    """Stopped: the low cluster, below the threshold that sits in the gap between the clusters."""
    confidence = "high" if split.separation >= HIGH_SEPARATION else "medium"
    thresholds = {"threshold": round(split.threshold, 4), "gap": [round(v, 4) for v in split.gap]}
    detail = f"{tag} splits into two clusters (separation {split.separation:.2f})"
    evidence = _evidence("bimodal_gap", x <= split.threshold, t_s, thresholds, detail)
    return _mode(scope, "stopped", [_clause(tag, "<=", split.threshold)], confidence, evidence)


def _startup(
    scope: str, tag: str, t_s: np.ndarray, split: Split, top: float, ramps: list[tuple[int, int]]
) -> Doc:
    """Start-up: activity above the stopped threshold but not yet at running level."""
    clauses = [_clause(tag, ">", split.threshold), _clause(tag, "<", top)]
    seconds = [float(t_s[b] - t_s[a]) for a, b in ramps]
    detail = f"{len(ramps)} ramps from stopped, median duration {float(np.median(seconds)):.0f} s"
    evidence = {
        "kind": "transition_windows",
        "share": round(sum(seconds) / float(t_s[-1] - t_s[0]), 4),
        "thresholds": {"from": round(split.threshold, 4), "to": round(top, 4)},
        "windows": [[float(t_s[a]), float(t_s[b])] for a, b in ramps[:MAX_WINDOWS]],
        "events": len(ramps),
        "detail": detail,
    }
    confidence = "high" if len(ramps) > MIN_RAMPS else "medium"
    return _mode(scope, "startup", clauses, confidence, evidence)


def _running_modes(
    scope: str, tag: str, flow: str, t_s: np.ndarray, x: np.ndarray, level: np.ndarray, split: Split
) -> list[Doc]:
    """Normal and (when the flow has a distinct upper band) high-throughput proposals."""
    top, ramps = _startups(x, split)
    started = len(ramps) >= MIN_RAMPS
    floor = top if started else split.threshold
    base = _clause(tag, ">=" if started else ">", floor)
    band = (x > split.threshold) & np.isfinite(level)
    if band.sum() < MIN_SAMPLES:
        return []
    q = float(np.quantile(level[band], HIGH_QUANTILE))
    if q <= float(np.median(level[band])):
        thresholds = {"from": round(floor, 4)}
        return [
            _mode(
                scope,
                "normal",
                [base],
                "medium",
                _evidence("running_band", x >= floor, t_s, thresholds, f"{tag} at running level"),
            )
        ]
    high = band & (level >= q)
    confidence = "medium" if band.sum() >= MIN_BAND_SAMPLES else "low"
    normal = (x >= floor) & ~high
    return [
        _mode(
            scope,
            "normal",
            [base, _clause(flow, "<", q)],
            confidence,
            _evidence(
                "running_band",
                normal,
                t_s,
                {"from": round(floor, 4), "to": round(q, 4)},
                f"running with {flow} below {q:.4g}",
            ),
        ),
        _mode(
            scope,
            "high_throughput",
            [_clause(tag, ">", split.threshold), _clause(flow, ">=", q)],
            confidence,
            _evidence(
                "upper_quantile",
                high,
                t_s,
                {"quantile": HIGH_QUANTILE, "value": round(q, 4)},
                f"upper {round((1 - HIGH_QUANTILE) * 100)}% of {flow} while running",
            ),
        ),
    ]


def activity_tag(
    entry_tags: list[str], signals: list[Doc], running: Doc | None, values: dict[str, np.ndarray]
) -> str | None:
    """The tag that tells whether the equipment runs: running tag, then signals, then names."""
    if running and running["tag"] in values:
        return str(running["tag"])
    found = {
        kind: tag
        for tag in reversed(entry_tags)
        if tag in values
        if (kind := propose_kind(tag, None, None))
    }
    found.update({s["kind"]: s["tag"] for s in signals if s["tag"] in values})
    return next((found[kind] for kind in ACTIVITY_KINDS if kind in found), None)


def throughput_tag(entry_tags: list[str], fallback: str, values: dict[str, np.ndarray]) -> str:
    """A flow or feed-rate tag of the equipment, else the activity tag itself."""
    for tag in entry_tags:
        if tag in values and any(word in tag.upper() for word in THROUGHPUT_WORDS):
            return tag
    return fallback


def propose_modes(
    scope: str,
    tags: list[str],
    t_s: np.ndarray,
    values: dict[str, np.ndarray],
    signals: list[Doc] | None = None,
    running: Doc | None = None,
) -> list[Doc]:
    """Mode proposals of one equipment: stopped, start-up, normal and high throughput."""
    tag = activity_tag(tags, signals or [], running, values)
    split = split_threshold(values[tag]) if tag else None
    if tag is None or split is None:
        return []
    x = values[tag]
    flow = throughput_tag(tags, tag, values)
    found = [_stopped(scope, tag, t_s, x, split)]
    top, ramps = _startups(x, split)
    if len(ramps) >= MIN_RAMPS:
        found.append(_startup(scope, tag, t_s, split, top, ramps))
    return found + _running_modes(scope, tag, flow, t_s, x, values[flow], split)


def _prefix(tag: str) -> str:
    """Leading name token (before . _ : / -), made a valid catalogue identifier."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", re.split(r"[._:/-]", tag)[0])


def _switches(x: np.ndarray) -> np.ndarray:
    """Sample indices at which a bimodal tag changes state; empty when it is not bimodal."""
    split = split_threshold(x)
    if split is None:
        return np.empty(0, int)
    return np.flatnonzero(np.diff((x > split.threshold).astype(int))) + 1


def _shared_switches(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Switch events of A that B repeats within the tolerance, and the Jaccard overlap."""
    if a.size < 2 or b.size < 2:
        return 0, 0.0
    matched = int(sum(np.any(np.abs(b - i) <= SWITCH_TOLERANCE) for i in a))
    return matched, matched / (a.size + b.size - matched)


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation on the samples where both are finite; 0 when undefined."""
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < MIN_SAMPLES or np.ptp(a[ok]) == 0 or np.ptp(b[ok]) == 0:
        return 0.0
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def _link(a: np.ndarray, b: np.ndarray) -> Doc | None:
    """How strongly two tags move together, or None when they are not linked."""
    shared, overlap = _shared_switches(_switches(a), _switches(b))
    corr = abs(_correlation(a, b))
    if corr < CORRELATION_LINK and overlap < SWITCH_LINK:
        return None
    return {"correlation": corr, "overlap": overlap, "shared": shared}


def _components(tags: list[str], links: dict[tuple[str, str], Doc]) -> list[list[str]]:
    """Connected components of the link graph with at least two tags (union-find)."""
    parent = {t: t for t in tags}

    def root(t: str) -> str:
        while parent[t] != t:
            t = parent[t]
        return t

    for a, b in links:
        parent[root(a)] = root(b)
    groups: dict[str, list[str]] = {}
    for t in tags:
        groups.setdefault(root(t), []).append(t)
    return [g for g in groups.values() if len(g) >= 2]


def _group(ident: str, prefix: str, members: list[str], links: dict[tuple[str, str], Doc]) -> Doc:
    """An equipment proposal; the weakest link of the group is its evidence."""
    own = [v for (a, b), v in links.items() if a in members and b in members]
    corr = min(v["correlation"] for v in own)
    overlap = max(v["overlap"] for v in own)
    switching = overlap >= SWITCH_LINK
    strong = overlap >= STRONG_OVERLAP or corr >= STRONG_CORRELATION
    thresholds = {
        "prefix": prefix,
        "min_correlation": round(corr, 3),
        "switch_overlap": round(overlap, 3),
    }
    entry = {"id": ident, "name": ident, "level": "equipment", "tags": sorted(members)}
    evidence = {
        "kind": "co_switching" if switching else "co_variation",
        "share": 1.0,
        "thresholds": thresholds,
        "windows": [],
        "events": sum(v["shared"] for v in own),
        "detail": f"{len(members)} tags with prefix {prefix} move together (r >= {corr:.2f})",
    }
    return {
        "id": ident,
        "entry": entry,
        "confidence": "high" if strong else "medium",
        "evidence": evidence,
    }


def propose_equipment(
    values: dict[str, np.ndarray], attached: set[str], taken: set[str]
) -> list[Doc]:
    """Equipment groups: tags with a shared name prefix that switch or vary together.

    ``attached`` are tags already on an equipment entry; ``taken`` are ids that already exist.
    """
    by_prefix: dict[str, list[str]] = {}
    for tag in sorted(values):
        if tag not in attached and _prefix(tag):
            by_prefix.setdefault(_prefix(tag), []).append(tag)
    found: list[Doc] = []
    for prefix, tags in by_prefix.items():
        links = {
            (a, b): link
            for i, a in enumerate(tags)
            for b in tags[i + 1 :]
            if (link := _link(values[a], values[b]))
        }
        parts = _components(tags, links)
        for n, members in enumerate(parts, start=1):
            ident = prefix if len(parts) == 1 else f"{prefix}_{n}"
            if ident not in taken:
                found.append(_group(ident, prefix, members, links))
    return found


def _children(entries: list[Doc]) -> set[str]:
    """Ids of entries that have at least one child."""
    return {e["parent"] for e in entries if e.get("parent")}


def propose_from_history(t_s: np.ndarray, values: dict[str, np.ndarray], site: Doc) -> Doc:
    """Mode and equipment-group proposals for a site document and one history window.

    Modes are proposed for every leaf equipment entry, and for each proposed group (flagged
    ``scope_new`` because accepting the mode must also add the group).
    """
    entries = site.get("equipment", [])
    parents = _children(entries)
    known_modes = {m["id"] for m in site.get("modes", [])}
    attached = {t for e in entries for t in e.get("tags", [])}
    groups = propose_equipment(values, attached, {e["id"] for e in entries})
    modes: list[Doc] = []
    for e in entries:
        if e["id"] not in parents and e.get("tags"):
            modes += propose_modes(
                e["id"], e["tags"], t_s, values, e.get("signals"), e.get("running")
            )
    for g in groups:
        modes += [
            {**m, "scope_new": True}
            for m in propose_modes(g["id"], g["entry"]["tags"], t_s, values)
        ]
    return {"modes": [m for m in modes if m["id"] not in known_modes], "equipment": groups}
