"""Endpoint + validation tests for the Phase 1 campaign API (steps 5, 8).

Per CLAUDE.md: real file fixtures (campaign_store points at a temp tree), and the
OpenAI client is mocked at the boundary — never called live. Covers the happy
path, the no-overwrite guarantee at the HTTP layer, and adversarial inputs.
"""

import os

import pytest

import campaign_store
import server
import Feedback_Generators.employee_feedback_generator as emp_gen


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

CANNED_REPORT = """# Employee Cyber Hygiene Report
## Executive Summary
You are doing well overall.
## Priority Risks
Keep MFA enabled everywhere.
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with campaign_store redirected to a temp data/report tree."""
    data_dir = tmp_path / "data"
    report_dir = tmp_path / "reports"
    data_dir.mkdir()
    report_dir.mkdir()
    monkeypatch.setattr(campaign_store, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(campaign_store, "GENERATED_REPORT_DIR", str(report_dir))
    server.app.testing = True
    return server.app.test_client()


@pytest.fixture
def mock_openai(monkeypatch):
    """Replace the OpenAI boundary so generate_feedback never calls the API."""
    monkeypatch.setattr(emp_gen, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(emp_gen, "generate_report_text", lambda api_key, prompt: CANNED_REPORT)


def _create_campaign(client, tracks=("employee", "organization")):
    resp = client.post("/api/campaigns", json={"org_name": "Acme Ltd", "tracks": list(tracks)})
    assert resp.status_code == 201
    return resp.get_json()["campaign"]["campaign_id"]


# --------------------------------------------------------------------------- #
# _validate_campaign
# --------------------------------------------------------------------------- #
def test_validate_campaign_accepts_valid():
    ok, _ = server._validate_campaign({"org_name": "Acme", "tracks": ["employee"]})
    assert ok


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-dict",
        {"org_name": "", "tracks": ["employee"]},
        {"org_name": "   ", "tracks": ["employee"]},
        {"org_name": "Acme"},                              # missing tracks
        {"org_name": "Acme", "tracks": []},                # empty tracks
        {"org_name": "Acme", "tracks": "employee"},        # tracks not a list
        {"org_name": "Acme", "tracks": [123]},             # non-string track
        {"org_name": "Acme", "tracks": ["admin"]},         # non-allowlist track
    ],
)
def test_validate_campaign_rejects(payload):
    ok, message = server._validate_campaign(payload)
    assert not ok and message


# --------------------------------------------------------------------------- #
# campaign endpoints
# --------------------------------------------------------------------------- #
def test_create_campaign_endpoint(client):
    resp = client.post("/api/campaigns", json={"org_name": "Acme Ltd", "tracks": ["employee"]})
    assert resp.status_code == 201
    campaign = resp.get_json()["campaign"]
    assert campaign_store.is_valid_id(campaign["campaign_id"])
    assert campaign["org_slug"] == "acme-ltd"


def test_create_campaign_endpoint_rejects_bad_payload(client):
    resp = client.post("/api/campaigns", json={"org_name": "", "tracks": ["employee"]})
    assert resp.status_code == 400


def test_create_campaign_endpoint_rejects_bad_track(client):
    resp = client.post("/api/campaigns", json={"org_name": "Acme", "tracks": ["admin"]})
    assert resp.status_code == 400


def test_list_campaigns_endpoint(client):
    cid = _create_campaign(client)
    resp = client.get("/api/campaigns")
    assert resp.status_code == 200
    ids = {c["campaign_id"] for c in resp.get_json()["campaigns"]}
    assert cid in ids


# --------------------------------------------------------------------------- #
# save submission endpoint
# --------------------------------------------------------------------------- #
def test_save_submission_returns_respondent_id(client):
    cid = _create_campaign(client)
    resp = client.post(f"/saveAssessmentData/{cid}/employee", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    rid = resp.get_json()["respondent_id"]
    assert campaign_store.is_valid_id(rid)


def test_two_submissions_do_not_overwrite_via_http(client):
    cid = _create_campaign(client)
    first = client.post(f"/saveAssessmentData/{cid}/employee", json=SAMPLE_PAYLOAD).get_json()["respondent_id"]
    second = client.post(f"/saveAssessmentData/{cid}/employee", json=SAMPLE_PAYLOAD).get_json()["respondent_id"]
    assert first != second
    track_dir = os.path.join(campaign_store.DATA_DIR, "acme-ltd", cid, "employee")
    assert sorted(os.listdir(track_dir)) == sorted([f"{first}.json", f"{second}.json"])


def test_save_submission_invalid_campaign_id_format(client):
    resp = client.post("/saveAssessmentData/not-a-valid-id/employee", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 400


def test_save_submission_unknown_campaign(client):
    resp = client.post(f"/saveAssessmentData/{'f' * 32}/employee", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 404


def test_save_submission_invalid_track(client):
    cid = _create_campaign(client)
    resp = client.post(f"/saveAssessmentData/{cid}/admin", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 400


def test_save_submission_track_not_enabled(client):
    cid = _create_campaign(client, tracks=["employee"])
    resp = client.post(f"/saveAssessmentData/{cid}/organization", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 400


def test_save_submission_rejects_bad_body(client):
    cid = _create_campaign(client)
    resp = client.post(f"/saveAssessmentData/{cid}/employee", json={"responses": []})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# generate + download flow (OpenAI mocked)
# --------------------------------------------------------------------------- #
def test_generate_then_download(client, mock_openai):
    cid = _create_campaign(client)
    rid = client.post(f"/saveAssessmentData/{cid}/employee", json=SAMPLE_PAYLOAD).get_json()["respondent_id"]

    gen = client.post(f"/generateFeedback/{cid}/employee/{rid}")
    assert gen.status_code == 200
    assert "summary" in gen.get_json()

    pdf_path = os.path.join(campaign_store.GENERATED_REPORT_DIR, "acme-ltd", cid, "employee", f"{rid}.pdf")
    assert os.path.exists(pdf_path)

    dl = client.get(f"/downloadReport/{cid}/employee/{rid}")
    assert dl.status_code == 200
    assert dl.data[:5] == b"%PDF-"


def test_download_before_generate_is_404(client):
    cid = _create_campaign(client)
    rid = client.post(f"/saveAssessmentData/{cid}/employee", json=SAMPLE_PAYLOAD).get_json()["respondent_id"]
    resp = client.get(f"/downloadReport/{cid}/employee/{rid}")
    assert resp.status_code == 404


def test_generate_unknown_respondent_is_404(client, mock_openai):
    cid = _create_campaign(client)
    resp = client.post(f"/generateFeedback/{cid}/employee/{'a' * 32}")
    assert resp.status_code == 404


def test_generate_invalid_identifier_format(client):
    cid = _create_campaign(client)
    resp = client.post(f"/generateFeedback/{cid}/employee/not-a-valid-id")
    assert resp.status_code == 400
