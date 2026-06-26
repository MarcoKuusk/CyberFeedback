"""One-time migration: legacy single-file assessments -> campaign data model.

Phase 1 (see docs/PHASE1_PLAN.md §7). Before Phase 1, each track stored exactly
one submission at `src/data/{track}_assessment.json`, which the next respondent
overwrote. This script moves any such legacy files into the per-respondent layout
under a single seeded campaign ("Legacy import").

Properties:
  - Idempotent / safe to re-run: legacy files are MOVED (removed only after the
    new record is written), so a second run finds nothing and is a no-op. No new
    campaign is created unless there is legacy data to migrate.
  - Local-only: it touches the gitignored src/data and src/Generated_PDF_Report
    trees, never the repo.

Run from the repo root:
    python scripts/migrate_to_campaigns.py
"""

from __future__ import annotations

import json
import os
import sys

# Make the app modules importable the same way the server/tests do (src/ as root).
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import campaign_store  # noqa: E402

# Fixed order so the seeded campaign's track list is deterministic.
TRACK_ORDER = ["employee", "organization"]
LEGACY_ORG_NAME = "Legacy import"


def _legacy_file(track: str) -> str:
    return os.path.join(campaign_store.DATA_DIR, f"{track}_assessment.json")


def _discover_legacy() -> "list[str]":
    return [track for track in TRACK_ORDER if os.path.exists(_legacy_file(track))]


def migrate() -> int:
    """Run the migration. Returns the number of submissions migrated."""
    legacy_tracks = _discover_legacy()
    if not legacy_tracks:
        print("No legacy assessment files found; nothing to migrate.")
        return 0

    campaign = campaign_store.create_campaign(LEGACY_ORG_NAME, legacy_tracks)
    campaign_id = campaign["campaign_id"]
    print(f"Created seeded campaign {campaign_id} (tracks: {', '.join(legacy_tracks)}).")

    migrated = 0
    for track in legacy_tracks:
        legacy_path = _legacy_file(track)
        with open(legacy_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        respondent_id = campaign_store.save_submission(campaign_id, track, payload)
        os.remove(legacy_path)  # remove only after the new record is safely written
        migrated += 1
        # Intentionally do not print payload contents (no PII to logs).
        print(f"  migrated {track}: {os.path.basename(legacy_path)} -> {track}/{respondent_id}.json")

    print(f"Done. Migrated {migrated} submission(s) into campaign {campaign_id}.")
    return migrated


if __name__ == "__main__":
    migrate()
