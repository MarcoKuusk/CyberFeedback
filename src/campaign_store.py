"""Campaign-scoped storage for assessment submissions.

Replaces the single-file-per-report-type model, where every save overwrote
`data/{type}_assessment.json` and a fixed output PDF filename could serve one
respondent's report to another. Records are keyed by
organization -> campaign -> track -> respondent, so submissions cannot collide.

All path construction lives here and flows through `_safe_join`, so server.py
stays thin and the containment guarantees are unit-testable in isolation.

Trust model: `campaign_id`, `respondent_id` and `org_slug` are never taken from
request input as free text. IDs are server-generated opaque hex and validated
against a strict pattern; `org_slug` is resolved from the trusted registry by
`campaign_id`, so the most user-influenced value never reaches a path directly.
`track` is allowlisted. Containment is then re-checked regardless.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from uuid import uuid4

# Single source of truth for tracks; server.py imports this rather than
# keeping its own copy.
ALLOWED_TRACKS = ("employee", "organization")
ALLOWED_LOCALES = ("en", "et")

CAMPAIGN_STATUSES = ("open", "closed")

# Campaign-level rollup reports (Phase 2). These are not tracks: they render one
# PDF per campaign rather than per respondent.
ALLOWED_ORG_REPORT_MODES = ("aggregate", "organization", "combined")

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

REGISTRY_FILENAME = "campaigns.json"

# Estonian and other Latin diacritics that NFKD alone will not reduce to ASCII.
_TRANSLITERATIONS = {
    "õ": "o", "ä": "a", "ö": "o", "ü": "u", "š": "s", "ž": "z",
    "å": "a", "æ": "ae", "ø": "o", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "ł": "l",
}

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))


class InvalidInputError(ValueError):
    """Rejected input. Callers map this to a generic 400 — never echo the path."""


class CampaignNotFoundError(LookupError):
    """Unknown campaign, track, or respondent. Callers map this to a 404."""


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_join(base: str, *parts: str) -> str:
    """Join under `base` and prove the result stayed inside it.

    The single containment guard every path in this module passes through.
    Uses realpath (not just abspath) so a symlink or directory junction cannot
    redirect a write outside the base directory.
    """
    for part in parts:
        if not isinstance(part, str) or not part:
            raise InvalidInputError("Path segment must be a non-empty string.")
        if os.path.isabs(part) or os.path.splitdrive(part)[0]:
            raise InvalidInputError("Path segment must be relative.")
        if "\x00" in part:
            raise InvalidInputError("Path segment contains a null byte.")

    base_real = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base_real, *parts))
    if candidate != base_real and not candidate.startswith(base_real + os.sep):
        raise InvalidInputError("Path escapes base directory.")
    return candidate


def _validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise InvalidInputError(f"Invalid {label}.")
    return value


def _validate_track(track: Any) -> str:
    if track not in ALLOWED_TRACKS:
        raise InvalidInputError("Invalid track.")
    return track


def _validate_locale(locale: Any) -> str:
    if locale not in ALLOWED_LOCALES:
        raise InvalidInputError("Invalid locale.")
    return locale


def _validate_slug(slug: Any) -> str:
    """Guards the registry as an input boundary too, in case it is edited by hand."""
    if not isinstance(slug, str) or not _SLUG_PATTERN.match(slug):
        raise InvalidInputError("Invalid organization slug.")
    return slug


def slugify(org_name: str) -> str:
    """Derive a filesystem-safe slug. Called once at campaign creation."""
    if not isinstance(org_name, str):
        raise InvalidInputError("Organization name must be a string.")

    lowered = org_name.strip().lower()
    transliterated = "".join(_TRANSLITERATIONS.get(ch, ch) for ch in lowered)
    decomposed = unicodedata.normalize("NFKD", transliterated)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-")
    # Names that transliterate to nothing (e.g. non-Latin scripts) still need a
    # valid directory name; campaign_id keeps the full path unique regardless.
    return slug or "org"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _registry_path() -> str:
    return os.path.join(os.path.realpath(DATA_DIR), REGISTRY_FILENAME)


def _read_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not os.path.exists(path):
        return {"campaigns": {}}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("campaigns"), dict):
        raise InvalidInputError("Campaign registry is malformed.")
    return data


def _write_registry(registry: Dict[str, Any]) -> None:
    """Atomic write: a concurrent reader never sees a half-written registry."""
    directory = os.path.realpath(DATA_DIR)
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".campaigns-", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(registry, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, _registry_path())
    except BaseException:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_campaign(org_name: str, tracks: List[str], locale: str = "en") -> Dict[str, Any]:
    if not isinstance(org_name, str) or not org_name.strip():
        raise InvalidInputError("Organization name must be a non-empty string.")
    if not isinstance(tracks, (list, tuple)) or not tracks:
        raise InvalidInputError("Tracks must be a non-empty list.")

    seen: List[str] = []
    for track in tracks:
        _validate_track(track)
        if track not in seen:
            seen.append(track)

    campaign = {
        "campaign_id": uuid4().hex,
        "org_name": org_name.strip(),
        "org_slug": slugify(org_name),
        "tracks": seen,
        "locale": _validate_locale(locale),
        "status": "open",
        "created_at": _now(),
    }

    registry = _read_registry()
    registry["campaigns"][campaign["campaign_id"]] = campaign
    _write_registry(registry)
    return dict(campaign)


def get_campaign(campaign_id: str) -> Dict[str, Any] | None:
    _validate_id(campaign_id, "campaign id")
    campaign = _read_registry()["campaigns"].get(campaign_id)
    return dict(campaign) if campaign else None


def list_campaigns() -> List[Dict[str, Any]]:
    campaigns = _read_registry()["campaigns"].values()
    return sorted((dict(c) for c in campaigns), key=lambda c: c.get("created_at", ""))


def set_campaign_status(campaign_id: str, status: str) -> Dict[str, Any]:
    if status not in CAMPAIGN_STATUSES:
        raise InvalidInputError("Invalid campaign status.")
    registry = _read_registry()
    campaign = registry["campaigns"].get(_validate_id(campaign_id, "campaign id"))
    if not campaign:
        raise CampaignNotFoundError("Unknown campaign.")
    campaign["status"] = status
    _write_registry(registry)
    return dict(campaign)


def _require_campaign(campaign_id: str) -> Dict[str, Any]:
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise CampaignNotFoundError("Unknown campaign.")
    return campaign


def _resolve_track(campaign: Dict[str, Any], track: str) -> str:
    _validate_track(track)
    if track not in campaign.get("tracks", ()):
        raise CampaignNotFoundError("Track is not enabled for this campaign.")
    return track


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

def _track_dir(campaign: Dict[str, Any], track: str, base: str) -> str:
    return _safe_join(
        base,
        _validate_slug(campaign["org_slug"]),
        _validate_id(campaign["campaign_id"], "campaign id"),
        track,
    )


def _validate_consent(consent: Any) -> Dict[str, Any]:
    """Consent is enforced at the storage boundary.

    This is a research instrument: a submission without recorded consent must
    never reach disk, so the guarantee lives here rather than only in the
    request layer.
    """
    if not isinstance(consent, dict):
        raise InvalidInputError("Consent record is required.")
    if consent.get("agreed") is not True:
        raise InvalidInputError("Consent must be given before a submission is stored.")
    version = consent.get("version")
    if not isinstance(version, str) or not version.strip():
        raise InvalidInputError("Consent version is required.")
    # Timestamp comes from the server clock, never the client's.
    return {"agreed": True, "version": version.strip(), "recorded_at": _now()}


def save_submission(campaign_id: str, track: str, payload: Dict[str, Any]) -> str:
    """Persist one respondent's submission. Returns the new respondent_id.

    Filenames are unique by construction, so concurrent submissions never
    contend on the same file — that is the whole point of the model.
    """
    campaign = _require_campaign(campaign_id)
    if campaign.get("status") != "open":
        raise InvalidInputError("Campaign is not open for submissions.")
    track = _resolve_track(campaign, track)

    if not isinstance(payload, dict):
        raise InvalidInputError("Payload must be an object.")
    responses = payload.get("responses")
    if not isinstance(responses, list) or not responses:
        raise InvalidInputError("Responses must be a non-empty list.")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidInputError("Metadata must be an object.")

    consent = _validate_consent(payload.get("consent"))
    respondent_id = uuid4().hex

    record = {
        "respondent_id": respondent_id,
        "campaign_id": campaign["campaign_id"],
        "track": track,
        "locale": campaign.get("locale", "en"),
        "submitted_at": _now(),
        "consent": consent,
        "metadata": metadata,
        "responses": responses,
    }

    directory = _track_dir(campaign, track, DATA_DIR)
    os.makedirs(directory, exist_ok=True)
    destination = _safe_join(directory, f"{respondent_id}.json")
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return respondent_id


def import_legacy_submission(campaign_id: str, track: str, payload: Dict[str, Any]) -> str:
    """Import one pre-campaign submission that has no consent record.

    `save_submission` refuses a submission without consent, and that gate must
    not be weakened — so legacy data comes in through this separate, explicitly
    named door instead. Consent is recorded as **not given**: these respondents
    were never asked, so the record must not look like they agreed. The research
    export filters on `consent.agreed`, which keeps this data out of the thesis
    dataset while preserving it for local operational use.
    """
    campaign = _require_campaign(campaign_id)
    track = _resolve_track(campaign, track)

    if not isinstance(payload, dict):
        raise InvalidInputError("Payload must be an object.")
    responses = payload.get("responses")
    if not isinstance(responses, list) or not responses:
        raise InvalidInputError("Responses must be a non-empty list.")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidInputError("Metadata must be an object.")

    respondent_id = uuid4().hex
    record = {
        "respondent_id": respondent_id,
        "campaign_id": campaign["campaign_id"],
        "track": track,
        "locale": campaign.get("locale", "en"),
        "submitted_at": _now(),
        "consent": {
            "agreed": False,
            "version": "not-collected",
            "recorded_at": None,
            "legacy_import": True,
        },
        "metadata": metadata,
        "responses": responses,
    }

    directory = _track_dir(campaign, track, DATA_DIR)
    os.makedirs(directory, exist_ok=True)
    destination = _safe_join(directory, f"{respondent_id}.json")
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    return respondent_id


def load_record(campaign_id: str, track: str, respondent_id: str) -> Dict[str, Any]:
    campaign = _require_campaign(campaign_id)
    track = _resolve_track(campaign, track)
    _validate_id(respondent_id, "respondent id")

    path = _safe_join(_track_dir(campaign, track, DATA_DIR), f"{respondent_id}.json")
    if not os.path.exists(path):
        raise CampaignNotFoundError("Unknown respondent.")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_submission(campaign_id: str, track: str, respondent_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The (responses, metadata) pair `main.generate_report` expects."""
    record = load_record(campaign_id, track, respondent_id)
    return record.get("responses", []), record.get("metadata", {})


def list_respondents(campaign_id: str, track: str) -> List[str]:
    campaign = _require_campaign(campaign_id)
    track = _resolve_track(campaign, track)
    directory = _track_dir(campaign, track, DATA_DIR)
    if not os.path.isdir(directory):
        return []
    return sorted(
        name[:-5]
        for name in os.listdir(directory)
        if name.endswith(".json") and _ID_PATTERN.match(name[:-5])
    )


def report_path(campaign_id: str, track: str, respondent_id: str) -> str:
    """Output path for a respondent's PDF, guaranteed inside REPORT_DIR."""
    campaign = _require_campaign(campaign_id)
    track = _resolve_track(campaign, track)
    _validate_id(respondent_id, "respondent id")

    directory = _track_dir(campaign, track, REPORT_DIR)
    os.makedirs(directory, exist_ok=True)
    return _safe_join(directory, f"{respondent_id}.pdf")


def org_report_path(campaign_id: str, mode: str) -> str:
    """Output path for a campaign-level rollup PDF, guaranteed inside REPORT_DIR.

    Org rollups live under a reserved "_org" segment rather than a real
    {track}/{respondent_id} location. "_org" is not in ALLOWED_TRACKS, so it can
    never be produced as a track path and cannot collide with a respondent PDF.
    """
    campaign = _require_campaign(campaign_id)
    if mode not in ALLOWED_ORG_REPORT_MODES:
        raise InvalidInputError("Invalid report mode.")

    directory = _safe_join(
        REPORT_DIR,
        _validate_slug(campaign["org_slug"]),
        _validate_id(campaign["campaign_id"], "campaign id"),
        "_org",
    )
    os.makedirs(directory, exist_ok=True)
    return _safe_join(directory, f"{mode}.pdf")
