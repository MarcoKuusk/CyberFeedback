"""Tests for scripts/migrate_to_campaigns.py (Phase 1, step 7).

The migration MOVES legacy single-file assessments into the campaign layout and
deletes the originals, so its happy path is exercised here against real files
(per CLAUDE.md: real fixtures, no mocked I/O). No OpenAI involvement.
"""

import json
import os
import sys

import pytest

import campaign_store

# The migration script lives under scripts/, not src/; make it importable.
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import migrate_to_campaigns as migration  # noqa: E402


SAMPLE_PAYLOAD = {
    "responses": [
        {
            "question": "Do you use MFA?",
            "category": "Password & Access Management",
            "answers": [{"option": "No", "score": 0}, {"option": "Always", "score": 4}],
            "selectedAnswer": {"option": "Always", "score": 4},
        }
    ],
    "metadata": {"report_type": "employee", "generated_from": "legacy"},
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect campaign_store (and therefore the migration) to a temp tree."""
    data_dir = tmp_path / "data"
    report_dir = tmp_path / "reports"
    data_dir.mkdir()
    report_dir.mkdir()
    monkeypatch.setattr(campaign_store, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(campaign_store, "REPORT_DIR", str(report_dir))
    return campaign_store


def _seed_legacy(track, payload):
    path = os.path.join(campaign_store.DATA_DIR, f"{track}_assessment.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def test_migrate_no_legacy_is_noop(store):
    assert migration.migrate() == 0
    assert campaign_store.list_campaigns() == []


def test_migrate_moves_legacy_into_campaign(store):
    legacy_path = _seed_legacy("employee", SAMPLE_PAYLOAD)

    assert migration.migrate() == 1

    # Original legacy file is gone (moved, not copied).
    assert not os.path.exists(legacy_path)

    # Exactly one seeded campaign exists, with the employee track enabled.
    campaigns = campaign_store.list_campaigns()
    assert len(campaigns) == 1
    campaign = campaigns[0]
    assert campaign["org_name"] == migration.LEGACY_ORG_NAME
    assert campaign["tracks"] == ["employee"]

    # The record landed in the campaign layout and round-trips with no loss.
    ids = campaign_store.list_respondents(campaign["campaign_id"], "employee")
    assert len(ids) == 1
    responses, metadata = campaign_store.load_submission(campaign["campaign_id"], "employee", ids[0])
    assert responses == SAMPLE_PAYLOAD["responses"]
    assert metadata == SAMPLE_PAYLOAD["metadata"]


def test_migrate_both_tracks(store):
    emp_path = _seed_legacy("employee", SAMPLE_PAYLOAD)
    org_path = _seed_legacy("organization", SAMPLE_PAYLOAD)

    assert migration.migrate() == 2
    assert not os.path.exists(emp_path)
    assert not os.path.exists(org_path)

    campaign = campaign_store.list_campaigns()[0]
    assert sorted(campaign["tracks"]) == ["employee", "organization"]
    assert len(campaign_store.list_respondents(campaign["campaign_id"], "employee")) == 1
    assert len(campaign_store.list_respondents(campaign["campaign_id"], "organization")) == 1


def test_migrate_is_idempotent(store):
    _seed_legacy("employee", SAMPLE_PAYLOAD)
    assert migration.migrate() == 1
    # Re-running finds no legacy files: a no-op that creates no second campaign.
    assert migration.migrate() == 0
    assert len(campaign_store.list_campaigns()) == 1


def test_migrated_records_are_marked_as_lacking_consent(store):
    """Legacy respondents were never asked to consent.

    The record must say so rather than fabricating agreement, so the research
    export can exclude it by filtering on consent.agreed.
    """
    _seed_legacy("employee", SAMPLE_PAYLOAD)
    migration.migrate()

    campaign = campaign_store.list_campaigns()[0]
    respondent_id = campaign_store.list_respondents(campaign["campaign_id"], "employee")[0]
    record = campaign_store.load_record(campaign["campaign_id"], "employee", respondent_id)

    assert record["consent"]["agreed"] is False
    assert record["consent"]["legacy_import"] is True
    assert record["consent"]["recorded_at"] is None


def test_save_submission_still_refuses_missing_consent(store):
    """The legacy door must not have weakened the normal one."""
    campaign = campaign_store.create_campaign("Acme Ltd", ["employee"])
    with pytest.raises(campaign_store.InvalidInputError):
        campaign_store.save_submission(campaign["campaign_id"], "employee", SAMPLE_PAYLOAD)
