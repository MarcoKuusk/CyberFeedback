"""Unit tests for campaign_store (Phase 1, steps 1-3).

Per CLAUDE.md: real file fixtures (no mocked JSON I/O), and adversarial inputs
are tested alongside the happy path. No OpenAI involvement here.
"""

import json
import os

import pytest

import campaign_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point campaign_store at temp data/report dirs for the duration of a test."""
    data_dir = tmp_path / "data"
    report_dir = tmp_path / "reports"
    data_dir.mkdir()
    report_dir.mkdir()
    monkeypatch.setattr(campaign_store, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(campaign_store, "GENERATED_REPORT_DIR", str(report_dir))
    return campaign_store


SAMPLE_PAYLOAD = {
    "responses": [
        {
            "question": "Do you use MFA?",
            "category": "Password & Access Management",
            "answers": [{"option": "No", "score": 0}, {"option": "Always", "score": 4}],
            "selectedAnswer": {"option": "Always", "score": 4},
        }
    ],
    "metadata": {"report_type": "employee", "generated_from": "web-interface"},
}


# --------------------------------------------------------------------------- #
# slugify
# --------------------------------------------------------------------------- #
def test_slugify_basic():
    assert campaign_store.slugify("Acme Ltd") == "acme-ltd"


def test_slugify_strips_punctuation_and_edges():
    assert campaign_store.slugify("  Hello, World!! ") == "hello-world"


def test_slugify_truncates_long_names():
    slug = campaign_store.slugify("a" * 200)
    assert len(slug) <= 64
    assert campaign_store._SLUG_RE.match(slug)


def test_slugify_rejects_symbol_only_name():
    with pytest.raises(ValueError):
        campaign_store.slugify("!!!")


def test_slugify_rejects_non_string():
    with pytest.raises(ValueError):
        campaign_store.slugify(None)


# --------------------------------------------------------------------------- #
# id validation
# --------------------------------------------------------------------------- #
def test_is_valid_id():
    assert campaign_store.is_valid_id("a" * 32)
    assert campaign_store.is_valid_id("0123456789abcdef0123456789abcdef")
    assert not campaign_store.is_valid_id("A" * 32)        # uppercase
    assert not campaign_store.is_valid_id("a" * 31)        # too short
    assert not campaign_store.is_valid_id("a" * 33)        # too long
    assert not campaign_store.is_valid_id("../../etc/pass")
    assert not campaign_store.is_valid_id(None)


def test_is_valid_track():
    assert campaign_store.is_valid_track("employee")
    assert campaign_store.is_valid_track("organization")
    assert not campaign_store.is_valid_track("admin")
    assert not campaign_store.is_valid_track(None)


# --------------------------------------------------------------------------- #
# _safe_join
# --------------------------------------------------------------------------- #
def test_safe_join_allows_contained_path(tmp_path):
    base = str(tmp_path)
    result = campaign_store._safe_join(base, "org", "campaign", "employee", "x.json")
    assert result.startswith(os.path.abspath(base) + os.sep)


def test_safe_join_rejects_parent_traversal(tmp_path):
    with pytest.raises(ValueError):
        campaign_store._safe_join(str(tmp_path), "..", "..", "etc", "passwd")


def test_safe_join_rejects_absolute_escape(tmp_path):
    with pytest.raises(ValueError):
        campaign_store._safe_join(str(tmp_path), "C:\\Windows\\system32")


# --------------------------------------------------------------------------- #
# campaign CRUD
# --------------------------------------------------------------------------- #
def test_create_campaign_shape(store):
    campaign = store.create_campaign("Acme Ltd", ["employee", "organization"])
    assert store.is_valid_id(campaign["campaign_id"])
    assert campaign["org_slug"] == "acme-ltd"
    assert campaign["org_name"] == "Acme Ltd"
    assert campaign["tracks"] == ["employee", "organization"]
    assert campaign["status"] == "open"
    assert campaign["created_at"].endswith("Z")
    assert os.path.exists(store._registry_path())


def test_create_campaign_dedupes_tracks(store):
    campaign = store.create_campaign("Acme", ["employee", "employee"])
    assert campaign["tracks"] == ["employee"]


def test_create_campaign_rejects_empty_tracks(store):
    with pytest.raises(ValueError):
        store.create_campaign("Acme", [])


def test_create_campaign_rejects_unknown_track(store):
    with pytest.raises(ValueError):
        store.create_campaign("Acme", ["employee", "admin"])


def test_create_campaign_rejects_blank_org_name(store):
    with pytest.raises(ValueError):
        store.create_campaign("   ", ["employee"])


def test_get_campaign_roundtrip(store):
    created = store.create_campaign("Acme", ["employee"])
    fetched = store.get_campaign(created["campaign_id"])
    assert fetched == created


def test_get_campaign_unknown_returns_none(store):
    assert store.get_campaign("f" * 32) is None


def test_get_campaign_malformed_id_returns_none(store):
    assert store.get_campaign("../../etc") is None


def test_list_campaigns(store):
    a = store.create_campaign("Acme", ["employee"])
    b = store.create_campaign("Globex", ["organization"])
    ids = {c["campaign_id"] for c in store.list_campaigns()}
    assert ids == {a["campaign_id"], b["campaign_id"]}


def test_registry_persists_across_reload(store):
    a = store.create_campaign("Acme", ["employee"])
    b = store.create_campaign("Globex", ["organization"])
    # Read the registry file straight from disk to confirm atomic write landed.
    with open(store._registry_path(), "r", encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert set(on_disk["campaigns"]) == {a["campaign_id"], b["campaign_id"]}


# --------------------------------------------------------------------------- #
# submissions — the no-overwrite guarantee
# --------------------------------------------------------------------------- #
def test_two_submissions_do_not_overwrite(store):
    campaign = store.create_campaign("Acme", ["employee"])
    cid = campaign["campaign_id"]

    first = store.save_submission(cid, "employee", SAMPLE_PAYLOAD)
    second = store.save_submission(cid, "employee", SAMPLE_PAYLOAD)

    assert first != second
    track_dir = os.path.join(store.DATA_DIR, campaign["org_slug"], cid, "employee")
    files = sorted(os.listdir(track_dir))
    assert files == sorted([f"{first}.json", f"{second}.json"])


def test_save_then_load_roundtrip(store):
    campaign = store.create_campaign("Acme", ["employee"])
    cid = campaign["campaign_id"]
    rid = store.save_submission(cid, "employee", SAMPLE_PAYLOAD)

    responses, metadata = store.load_submission(cid, "employee", rid)
    assert responses == SAMPLE_PAYLOAD["responses"]
    assert metadata == SAMPLE_PAYLOAD["metadata"]


def test_save_submission_unknown_campaign(store):
    with pytest.raises(LookupError):
        store.save_submission("f" * 32, "employee", SAMPLE_PAYLOAD)


def test_save_submission_track_not_enabled(store):
    campaign = store.create_campaign("Acme", ["employee"])
    with pytest.raises(ValueError):
        store.save_submission(campaign["campaign_id"], "organization", SAMPLE_PAYLOAD)


def test_save_submission_invalid_track(store):
    campaign = store.create_campaign("Acme", ["employee"])
    with pytest.raises(ValueError):
        store.save_submission(campaign["campaign_id"], "admin", SAMPLE_PAYLOAD)


def test_load_submission_missing(store):
    campaign = store.create_campaign("Acme", ["employee"])
    with pytest.raises(FileNotFoundError):
        store.load_submission(campaign["campaign_id"], "employee", "a" * 32)


def test_load_submission_rejects_adversarial_respondent_id(store):
    campaign = store.create_campaign("Acme", ["employee"])
    with pytest.raises(ValueError):
        store.load_submission(campaign["campaign_id"], "employee", "../../etc/passwd")


# --------------------------------------------------------------------------- #
# report path
# --------------------------------------------------------------------------- #
def test_report_path_is_contained(store):
    campaign = store.create_campaign("Acme", ["employee"])
    rid = "a" * 32
    path = store.report_path(campaign["campaign_id"], "employee", rid)
    assert path.startswith(os.path.abspath(store.GENERATED_REPORT_DIR) + os.sep)
    assert path.endswith(f"{rid}.pdf")


def test_report_path_rejects_adversarial_respondent_id(store):
    campaign = store.create_campaign("Acme", ["employee"])
    with pytest.raises(ValueError):
        store.report_path(campaign["campaign_id"], "employee", "../../evil")
