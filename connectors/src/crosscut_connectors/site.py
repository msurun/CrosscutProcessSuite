"""The site catalogue: load, validate and save ``<data root>/_site/site.json``.

The layout is fixed by ``schemas/site.schema.json``. Validation is the JSON Schema plus the
cross-reference checks a schema cannot express (unique ids, known sources, consistent limits;
tag ids, hierarchy and units of the 36b sections live in ``site_refs``).
Nothing here touches a plant: it reads and writes one configuration file.

Importers and modules read their settings through :func:`read_import_settings`, the single
place where the site file turns into time zone, missing codes, quality mapping, units,
engineering ranges and sampling periods. Precedence is tag, then source, then site.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crosscut_sim.core import BAD, GOOD, UNCERTAIN
from jsonschema import Draft202012Validator

from crosscut_connectors.site_refs import reference_problems

SITE_FOLDER = "_site"
SITE_FILE = "site.json"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "site.schema.json"
IMPORT_KEYS = ("missing_codes", "decimal_comma", "delimiter", "time_names")
DEFAULT_TIMEZONE = "UTC"  # Neutral default: no plant clock is assumed when the file is silent.
QUALITY_WORDS = {"good": GOOD, "uncertain": UNCERTAIN, "bad": BAD}


class SiteError(ValueError):
    """The site file is missing, unreadable or not acceptable."""


@dataclass(frozen=True)
class Limits:
    """An engineering range in the tag's unit; an open side is ``None``."""

    low: float | None = None
    high: float | None = None

    def contains(self, value: float) -> bool:
        """True when ``value`` lies inside the stated bounds (inclusive)."""
        above = self.low is None or value >= self.low
        below = self.high is None or value <= self.high
        return above and below


@dataclass(frozen=True)
class UnitConversion:
    """A linear unit conversion as declared in the site file: to = from * factor + offset."""

    from_unit: str
    to_unit: str
    factor: float
    offset: float = 0.0

    def convert(self, value: float) -> float:
        """The value expressed in ``to_unit``."""
        return value * self.factor + self.offset


@dataclass(frozen=True)
class QualityMapping:
    """Source status codes (kept as text) mapped to local quality 0 good / 1 uncertain / 2 bad."""

    good_codes: frozenset[str] = frozenset()
    uncertain_codes: frozenset[str] = frozenset()
    bad_codes: frozenset[str] = frozenset()

    def classify(self, code: Any) -> int | None:
        """The local quality of one source code, or None when the site does not declare it."""
        text = _code_text(code)
        if text in self.bad_codes:
            return BAD
        if text in self.uncertain_codes:
            return UNCERTAIN
        if text in self.good_codes:
            return GOOD
        return None

    def with_overrides(self, overrides: Mapping[str, str]) -> QualityMapping:
        """The same mapping with per-tag ``code -> word`` entries winning over the site codes."""
        groups = {
            GOOD: set(self.good_codes),
            UNCERTAIN: set(self.uncertain_codes),
            BAD: set(self.bad_codes),
        }
        for code, word in overrides.items():
            target = QUALITY_WORDS[word]
            for codes in groups.values():
                codes.discard(_code_text(code))
            groups[target].add(_code_text(code))
        return QualityMapping(
            frozenset(groups[GOOD]), frozenset(groups[UNCERTAIN]), frozenset(groups[BAD])
        )


@dataclass(frozen=True)
class TagSettings:
    """The settings one importer tag uses after tag, source and site values are merged."""

    tag_id: str | None = None
    source_id: str | None = None
    missing_codes: tuple[float, ...] = ()
    missing_text_codes: frozenset[str] = frozenset()
    quality: QualityMapping = QualityMapping()
    quality_map: Mapping[str, str] | None = None
    unit: str = ""
    eng_limits: Limits | None = None
    valid_range: Limits | None = None
    sample_period_s: float | None = None

    def is_missing_number(self, value: float) -> bool:
        """True when ``value`` is one of the tag's declared missing numbers."""
        return any(value == code for code in self.missing_codes)

    def is_missing_text(self, text: str) -> bool:
        """True when ``text`` is one of the tag's declared missing text codes."""
        return text.strip().casefold() in self.missing_text_codes


@dataclass(frozen=True)
class SourceSettings:
    """Overrides one source declares for every tag read from it; None means "not stated"."""

    source_id: str | None = None
    missing_codes: tuple[float, ...] | None = None
    missing_text_codes: frozenset[str] | None = None


@dataclass(frozen=True)
class SiteImportSettings:
    """Everything an importer or module reads from the site file.

    Attributes
    ----------
    timezone: IANA zone of naive file timestamps; UTC when the file states none.
    missing_codes / missing_text_codes: site-wide "no result" values.
    quality: status-code mapping of ``quality`` in the site file.
    sample_period_s: site sampling period in seconds, or None when unstated.
    conversions: declared linear unit conversions.
    tags / sources: per-tag and per-source overrides, keyed by id.
    """

    timezone: str = DEFAULT_TIMEZONE
    missing_codes: tuple[float, ...] = ()
    missing_text_codes: frozenset[str] = frozenset()
    quality: QualityMapping = QualityMapping()
    sample_period_s: float | None = None
    conversions: tuple[UnitConversion, ...] = ()
    tags: Mapping[str, TagSettings] = field(default_factory=dict)
    sources: Mapping[str, SourceSettings] = field(default_factory=dict)

    def for_tag(self, tag_id: str | None) -> TagSettings:
        """Effective settings of a tag: its own values beat its source, which beats the site."""
        tag = self.tags.get(tag_id or "")
        source = self.sources.get(tag.source_id or "") if tag is not None else None
        return _merge_settings(self._site_defaults(), source, tag)

    def for_source(self, source_id: str | None) -> TagSettings:
        """Settings for a tag the catalogue does not name, read from one known source."""
        return _merge_settings(self._site_defaults(), self.sources.get(source_id or ""), None)

    def conversion(self, from_unit: str, to_unit: str) -> UnitConversion | None:
        """The declared conversion between two units, or None when no conversion is needed."""
        if not from_unit or not to_unit or from_unit == to_unit:
            return None
        return next(
            (
                item
                for item in self.conversions
                if item.from_unit == from_unit and item.to_unit == to_unit
            ),
            None,
        )

    def _site_defaults(self) -> TagSettings:
        """The site-wide values every tag starts from."""
        return TagSettings(
            missing_codes=self.missing_codes,
            missing_text_codes=self.missing_text_codes,
            quality=self.quality,
            sample_period_s=self.sample_period_s,
        )


def _merge_settings(
    defaults: TagSettings,
    source: SourceSettings | None,
    tag: TagSettings | None,
) -> TagSettings:
    """Apply source overrides, then tag overrides, on top of the site defaults."""
    return TagSettings(
        tag_id=tag.tag_id if tag is not None else None,
        source_id=_source_of(tag, source),
        missing_codes=_merged_codes(tag, source, defaults),
        missing_text_codes=_merged_text_codes(tag, source, defaults),
        quality=_merged_quality(defaults, tag),
        unit=tag.unit if tag is not None else "",
        eng_limits=tag.eng_limits if tag is not None else None,
        valid_range=tag.valid_range if tag is not None else None,
        sample_period_s=_merged_period(tag, defaults),
    )


def _source_of(tag: TagSettings | None, source: SourceSettings | None) -> str | None:
    """The source a tag belongs to, falling back to the source being merged."""
    if tag is not None and tag.source_id:
        return tag.source_id
    return source.source_id if source is not None else None


def _merged_codes(
    tag: TagSettings | None, source: SourceSettings | None, defaults: TagSettings
) -> tuple[float, ...]:
    """Numeric missing codes: tag beats source beats site."""
    return _first_stated(
        tag.missing_codes if tag else None,
        source.missing_codes if source else None,
        defaults.missing_codes,
    ) or ()


def _merged_text_codes(
    tag: TagSettings | None, source: SourceSettings | None, defaults: TagSettings
) -> frozenset[str]:
    """Text missing codes: tag beats source beats site."""
    return _first_stated(
        tag.missing_text_codes if tag else None,
        source.missing_text_codes if source else None,
        defaults.missing_text_codes,
    ) or frozenset()


def _merged_quality(defaults: TagSettings, tag: TagSettings | None) -> QualityMapping:
    """Site quality codes with the tag's own ``quality_map`` entries applied last."""
    if tag is None or not tag.quality_map:
        return defaults.quality
    return defaults.quality.with_overrides(tag.quality_map)


def _merged_period(tag: TagSettings | None, defaults: TagSettings) -> float | None:
    """Sampling period: the tag's own period beats the site default."""
    return _first_stated(tag.sample_period_s if tag else None, defaults.sample_period_s)


def _first_stated(*values: Any) -> Any:
    """The first value that is not None, so an explicit empty list still wins."""
    return next((value for value in values if value is not None), None)


def _code_text(code: Any) -> str:
    """A status code as comparable text; whole numbers lose a pointless ``.0``."""
    if isinstance(code, bool):
        return str(code).casefold()
    if isinstance(code, int | float):
        number = float(code)
        return str(int(number)) if number.is_integer() else str(number)
    return str(code).strip().casefold()


def site_path(root: Path) -> Path:
    """Where the site file of a data root lives."""
    return root / SITE_FOLDER / SITE_FILE


def load_site(root: Path) -> dict[str, Any]:
    """Read the site file of a data root as stored (no validation)."""
    path = site_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SiteError(f"no site file: {path}") from None
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SiteError(f"site file is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise SiteError("site file must hold a JSON object")
    return document


def validate_site(document: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Problems of a site document, as readable lines; empty when it is acceptable."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    problems = [f"{_where(error.absolute_path)}: {error.message}" for error in errors]
    return problems or _cross_reference_problems(document)


def _where(path: Any) -> str:
    """A dotted location such as ``tags.3.id`` ("site" for the document itself)."""
    return ".".join(str(part) for part in path) or "site"


def _cross_reference_problems(document: dict[str, Any]) -> list[str]:
    """Checks beyond the schema; the document already matches the schema."""
    source_ids = [source["id"] for source in document.get("sources", [])]
    problems = _duplicates("sources", source_ids)
    problems += _duplicates("tags", [tag["id"] for tag in document["tags"]])
    for index, tag in enumerate(document["tags"]):
        problems += _tag_problems(index, tag, set(source_ids))
    problems += _import_problems(document.get("import", {}))
    problems += _quality_problems(document.get("quality", {}))
    problems += reference_problems(document)
    return problems


def _duplicates(name: str, ids: list[str]) -> list[str]:
    """One line per id that occurs more than once."""
    counts = Counter(ids)
    return [f"{name}: duplicate id {item!r}" for item in sorted(counts) if counts[item] > 1]


def _tag_problems(index: int, tag: dict[str, Any], source_ids: set[str]) -> list[str]:
    """Unknown source and inverted limits of one tag."""
    where = f"tags.{index}"
    problems = []
    if "source" in tag and tag["source"] not in source_ids:
        problems.append(f"{where}.source: unknown source {tag['source']!r}")
    for key in ("range", "eng_limits"):
        limits = tag.get(key, {})
        if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
            problems.append(f"{where}.{key}: min is above max")
    return problems


def _import_problems(settings: dict[str, Any]) -> list[str]:
    """A decimal comma cannot share the file with a comma delimiter."""
    if settings.get("decimal_comma") and settings.get("delimiter", ",") == ",":
        return ["import.decimal_comma: needs a delimiter other than a comma"]
    return []


def _quality_problems(settings: dict[str, Any]) -> list[str]:
    """One status code may not mean two different things."""
    groups = {
        name: set(_numbers(settings.get(f"{name}_codes")))
        for name in ("good", "uncertain", "bad")
    }
    problems = [
        f"quality.{other}_codes: {code:g} is also a good code"
        for other in ("uncertain", "bad")
        for code in sorted(groups["good"] & groups[other])
    ]
    problems += [
        f"quality.bad_codes: {code:g} is also an uncertain code"
        for code in sorted(groups["uncertain"] & groups["bad"])
    ]
    return problems


def read_import_settings(document: dict[str, Any]) -> SiteImportSettings:
    """The one place importers and modules read the site settings from.

    Returns the time zone, missing codes, quality mapping, units, engineering ranges and
    sampling periods of the document. Settings the file does not state keep documented
    neutral defaults: UTC, no missing codes, no conversions, no sampling period.
    """
    stated = document.get("import", {})
    sources = {entry["id"]: _source_settings(entry) for entry in document.get("sources", [])}
    return SiteImportSettings(
        timezone=document.get("site", {}).get("timezone", DEFAULT_TIMEZONE),
        missing_codes=_numbers(stated.get("missing_codes")),
        missing_text_codes=_text_codes(stated.get("missing_text_codes")),
        quality=_quality_mapping(document.get("quality", {})),
        sample_period_s=document.get("defaults", {}).get("sample_period_s"),
        conversions=_conversions(document.get("units", {})),
        tags={tag["id"]: _tag_settings(tag) for tag in document.get("tags", [])},
        sources=sources,
    )


def _numbers(values: Any) -> tuple[float, ...]:
    """Declared numbers as floats; a missing list means no code."""
    return tuple(float(value) for value in values or ())


def _optional_numbers(values: Any) -> tuple[float, ...] | None:
    """Declared numbers, or None when the key is absent so a lower level still applies."""
    return None if values is None else _numbers(values)


def _text_codes(values: Any) -> frozenset[str]:
    """Declared text codes, trimmed and case-folded for comparison."""
    return frozenset(str(value).strip().casefold() for value in values or ())


def _optional_text_codes(values: Any) -> frozenset[str] | None:
    """Declared text codes, or None when the key is absent."""
    return None if values is None else _text_codes(values)


def _quality_mapping(settings: dict[str, Any]) -> QualityMapping:
    """The site quality section as a mapping from source code text to local quality."""
    return QualityMapping(
        good_codes=_text_codes(settings.get("good_codes")),
        uncertain_codes=_text_codes(settings.get("uncertain_codes")),
        bad_codes=_text_codes(settings.get("bad_codes")),
    )


def _source_settings(entry: dict[str, Any]) -> SourceSettings:
    """The missing-code overrides one source declares."""
    return SourceSettings(
        source_id=entry["id"],
        missing_codes=_optional_numbers(entry.get("missing_codes")),
        missing_text_codes=_optional_text_codes(entry.get("missing_text_codes")),
    )


def _tag_settings(entry: dict[str, Any]) -> TagSettings:
    """The overrides one tag declares, plus its unit, ranges and sampling period."""
    return TagSettings(
        tag_id=entry["id"],
        source_id=entry.get("source"),
        missing_codes=_optional_numbers(entry.get("missing_codes")),
        missing_text_codes=_optional_text_codes(entry.get("missing_text_codes")),
        quality_map=dict(entry.get("quality_map", {})),
        unit=entry.get("unit", ""),
        eng_limits=_limits(entry.get("eng_limits")),
        valid_range=_limits(entry.get("range")),
        sample_period_s=entry.get("sampling", {}).get("period_s"),
    )


def _limits(section: dict[str, Any] | None) -> Limits | None:
    """An optional low/high range; None when the tag states neither side."""
    if not section:
        return None
    return Limits(section.get("min"), section.get("max"))


def _conversions(settings: dict[str, Any]) -> tuple[UnitConversion, ...]:
    """The declared linear unit conversions."""
    return tuple(
        UnitConversion(
            from_unit=item["from"],
            to_unit=item["to"],
            factor=float(item["factor"]),
            offset=float(item.get("offset", 0.0)),
        )
        for item in settings.get("conversions", [])
    )


def read_settings_from_site(document: dict[str, Any]) -> dict[str, Any]:
    """The import settings stated in the site file, as keyword arguments for ReadSettings.

    Only keys the file states are returned, so the reader's own defaults apply to the rest.
    """
    stated = document.get("import", {})
    settings = {key: stated[key] for key in IMPORT_KEYS if key in stated}
    if "missing_codes" in settings:
        settings["missing_codes"] = tuple(float(code) for code in settings["missing_codes"])
    if "time_names" in settings:
        settings["time_names"] = frozenset(name.lower() for name in settings["time_names"])
    return settings


def save_site(root: Path, document: dict[str, Any]) -> None:
    """Validate and write the site file atomically; SiteError lists the problems."""
    problems = validate_site(document)
    if problems:
        raise SiteError("; ".join(problems))
    path = site_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temp_name, path)
