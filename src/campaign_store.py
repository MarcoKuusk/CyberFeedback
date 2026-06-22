"""Multi-respondent storage for CyberFeedback campaigns.

Centralizes all path construction, identifier validation, and on-disk I/O for
the campaign data model introduced in Phase 1 (see docs/PHASE1_PLAN.md). Keeping
this logic in one module lets server.py stay thin and makes the security-critical
path handling unit-testable in isolation.

Layout written by this module:
    {DATA_DIR}/{org_slug}/{campaign_id}/{track}/{respondent_id}.json
    {GENERATED_REPORT_DIR}/{org_slug}/{campaign_id}/{track}/{respondent_id}.pdf

Security backbone:
  - Request URLs carry the opaque campaign_id, never org_slug. The slug is
    resolved from the trusted registry, so the most user-influenced value never
    reaches path construction directly.
  - campaign_id and respondent_id are server-generated uuid4 hex and validated
    against a strict pattern; track is checked against an allowlist.
  - Every constructed path is finally confirmed to stay inside its base dir via
    _safe_join (defense in depth).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Base directories mirror server.py. They are module globals (not captured at
# import inside functions) so tests can monkeypatch them to a temp location.
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
GENERATED_REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))

# Canonical source of truth for tracks. server.py should import this in Phase 1
# step 5 rather than keeping its own ALLOWED_REPORT_TYPES copy.
ALLOWED_TRACKS = {"employee", "organization"}

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #
def _new_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def is_valid_track(track: Any) -> bool:
    return isinstance(track, str) and track in ALLOWED_TRACKS


def slugify(org_name: str) -> str:
    """Derive a filesystem-safe, validated slug from an organization name."""
    if not isinstance(org_name, str):
        raise ValueError("Organization name must be a string.")
    slug = re.sub(r"[^a-z0-9]+", "-", org_name.strip().lower()).strip("-")
    slug = slug[:63].strip("-")
    if not _SLUG_RE.match(slug):
        raise ValueError("Organization name does not yield a valid slug.")
    return slug


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Path containment guard
# --------------------------------------------------------------------------- #
def _safe_join(base: str, *parts: str) -> str:
    """Join parts onto base and confirm the result stays inside base.

    Raises ValueError if the resolved path escapes the base directory (path
    traversal) per the CLAUDE.md guard pattern.
    """
    base_abs = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base_abs, *parts))
    if candidate != base_abs and not candidate.startswith(base_abs + os.sep):
        raise ValueError("Path escapes base directory.")
    return candidate


# --------------------------------------------------------------------------- #
# Registry I/O (atomic)
# --------------------------------------------------------------------------- #
def _registry_path() -> str:
    return os.path.join(DATA_DIR, "campaigns.json")


def _load_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not os.path.exists(path):
        return {"campaigns": {}}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("campaigns"), dict):
        raise ValueError("Campaign registry is malformed.")
    return data


def _save_registry(registry: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _registry_path()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2)
    os.replace(tmp_path, path)  # atomic on POSIX and Windows


# --------------------------------------------------------------------------- #
# Campaign CRUD
# --------------------------------------------------------------------------- #
def create_campaign(org_name: str, tracks: List[str]) -> Dict[str, Any]:
    if not isinstance(org_name, str) or not org_name.strip():
        raise ValueError("Organization name is required.")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("At least one track is required.")
    invalid = sorted({t for t in tracks if not is_valid_track(t)})
    if invalid:
        raise ValueError(f"Unknown track(s): {', '.join(invalid)}.")

    deduped: List[str] = []
    for track in tracks:
        if track not in deduped:
            deduped.append(track)

    campaign = {
        "campaign_id": _new_id(),
        "org_name": org_name.strip(),
        "org_slug": slugify(org_name),
        "tracks": deduped,
        "status": "open",
        "created_at": _utc_now_iso(),
    }

    registry = _load_registry()
    registry["campaigns"][campaign["campaign_id"]] = campaign
    _save_registry(registry)
    return campaign


def get_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    if not is_valid_id(campaign_id):
        return None
    return _load_registry()["campaigns"].get(campaign_id)


def list_campaigns() -> List[Dict[str, Any]]:
    campaigns = _load_registry()["campaigns"].values()
    return sorted(campaigns, key=lambda c: c.get("created_at", ""))


def _resolve(campaign_id: str, track: str) -> Dict[str, Any]:
    """Validate track + campaign and return the trusted campaign record.

    Raises ValueError for a bad track / disabled track, LookupError for an
    unknown campaign. Callers map these to 400 / 404 respectively.
    """
    if not is_valid_track(track):
        raise ValueError("Invalid track.")
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise LookupError("Campaign not found.")
    if track not in campaign.get("tracks", []):
        raise ValueError("Track not enabled for this campaign.")
    return campaign


# --------------------------------------------------------------------------- #
# Submissions
# --------------------------------------------------------------------------- #
def save_submission(campaign_id: str, track: str, payload: Any) -> str:
    """Persist one submission and return its server-generated respondent_id."""
    campaign = _resolve(campaign_id, track)
    respondent_id = _new_id()
    path = _safe_join(DATA_DIR, campaign["org_slug"], campaign_id, track, f"{respondent_id}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return respondent_id


def load_submission(campaign_id: str, track: str, respondent_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (responses, metadata) for one submission."""
    campaign = _resolve(campaign_id, track)
    if not is_valid_id(respondent_id):
        raise ValueError("Invalid respondent id.")
    path = _safe_join(DATA_DIR, campaign["org_slug"], campaign_id, track, f"{respondent_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError("Submission not found.")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        return data.get("responses", []), data.get("metadata", {})
    if isinstance(data, list):
        return data, {}
    return [], {}


def report_path(campaign_id: str, track: str, respondent_id: str) -> str:
    """Resolve the per-respondent PDF output path (validated + contained)."""
    campaign = _resolve(campaign_id, track)
    if not is_valid_id(respondent_id):
        raise ValueError("Invalid respondent id.")
    return _safe_join(GENERATED_REPORT_DIR, campaign["org_slug"], campaign_id, track, f"{respondent_id}.pdf")
