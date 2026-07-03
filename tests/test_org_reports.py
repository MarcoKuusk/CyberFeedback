"""Endpoint + end-to-end tests for the Phase 2 org reports (docs/PHASE2_PLAN.md steps 6, 8).

Real file fixtures (campaign_store points at a temp tree); OpenAI mocked at each
generator boundary. Covers the mode allowlist, the combined-needs-both-tracks
rule, min-N suppression through the endpoint, and the full seed -> generate all
three reports -> download flow.
"""

import os

import pytest

import campaign_store
import server
import Feedback_Generators.combined_gap_feedback_generator as gap_gen
import Feedback_Generators.org_aggregate_feedback_generator as agg_gen
import Feedback_Generators.organization_feedback_generator as org_gen

from test_report_analysis import CONTROL_SCORES, _employee_submissions, _org_submission

CANNED = "# Report\n## Executive Summary\nAll clear.\n## Recommended Focus\n- Do the thing.\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
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
    """Silence every generator's OpenAI boundary used by org reports."""
    for module in (agg_gen, gap_gen, org_gen):
        monkeypatch.setattr(module, "load_api_key", lambda: "test-key")
        monkeypatch.setattr(module, "generate_report_text", lambda api_key, prompt: CANNED)


def _create_campaign(client, tracks=("employee", "organization")):
    resp = client.post("/api/campaigns", json={"org_name": "Acme Ltd", "tracks": list(tracks)})
    assert resp.status_code == 201
    return resp.get_json()["campaign"]["campaign_id"]


def _seed_employees(client, campaign_id, n):
    for responses in _employee_submissions(n):
        resp = client.post(
            f"/saveAssessmentData/{campaign_id}/employee",
            json={"responses": responses, "metadata": {"report_type": "employee"}},
        )
        assert resp.status_code == 200


def _seed_org(client, campaign_id):
    resp = client.post(
        f"/saveAssessmentData/{campaign_id}/organization",
        json={"responses": _org_submission(CONTROL_SCORES), "metadata": {"report_type": "organization"}},
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# mode allowlist + validation (before any I/O)
# --------------------------------------------------------------------------- #
def test_generate_org_report_rejects_bad_mode(client):
    cid = _create_campaign(client)
    resp = client.post(f"/generateOrgReport/{cid}/bogus")
    assert resp.status_code == 400


def test_generate_org_report_rejects_bad_campaign_id(client):
    resp = client.post("/generateOrgReport/not-a-valid-id/aggregate")
    assert resp.status_code == 400


def test_generate_org_report_unknown_campaign(client):
    resp = client.post(f"/generateOrgReport/{'f' * 32}/aggregate")
    assert resp.status_code == 404


def test_combined_requires_both_tracks(client, mock_openai):
    cid = _create_campaign(client, tracks=["employee"])
    _seed_employees(client, cid, 5)
    resp = client.post(f"/generateOrgReport/{cid}/combined")
    assert resp.status_code == 400


def test_aggregate_requires_employee_track(client, mock_openai):
    cid = _create_campaign(client, tracks=["organization"])
    _seed_org(client, cid)
    resp = client.post(f"/generateOrgReport/{cid}/aggregate")
    assert resp.status_code == 400


def test_organization_report_without_submissions_is_400(client, mock_openai):
    cid = _create_campaign(client, tracks=["organization"])
    resp = client.post(f"/generateOrgReport/{cid}/organization")
    assert resp.status_code == 400


def test_download_org_report_bad_mode(client):
    cid = _create_campaign(client)
    resp = client.get(f"/downloadOrgReport/{cid}/bogus")
    assert resp.status_code == 400


def test_download_org_report_before_generate_is_404(client):
    cid = _create_campaign(client)
    resp = client.get(f"/downloadOrgReport/{cid}/aggregate")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# submissions endpoint surfaces the anonymity floor
# --------------------------------------------------------------------------- #
def test_submissions_endpoint_exposes_min_aggregate_n(client):
    from utils.report_analysis import MIN_AGGREGATE_N

    cid = _create_campaign(client)
    body = client.get(f"/api/campaigns/{cid}/submissions").get_json()
    assert body["min_aggregate_n"] == MIN_AGGREGATE_N


# --------------------------------------------------------------------------- #
# min-N suppression through the endpoint (no crash, no partial breakdown)
# --------------------------------------------------------------------------- #
def test_aggregate_suppressed_below_threshold_still_produces_pdf(client, mock_openai):
    cid = _create_campaign(client, tracks=["employee"])
    _seed_employees(client, cid, 4)  # below MIN_AGGREGATE_N
    gen = client.post(f"/generateOrgReport/{cid}/aggregate")
    assert gen.status_code == 200
    dl = client.get(f"/downloadOrgReport/{cid}/aggregate")
    assert dl.status_code == 200
    assert dl.data[:5] == b"%PDF-"


# --------------------------------------------------------------------------- #
# end-to-end: seed both tracks -> all three reports -> download each
# --------------------------------------------------------------------------- #
def test_end_to_end_all_three_reports(client, mock_openai):
    cid = _create_campaign(client, tracks=["employee", "organization"])
    _seed_employees(client, cid, 5)
    _seed_org(client, cid)

    for mode in ("aggregate", "organization", "combined"):
        gen = client.post(f"/generateOrgReport/{cid}/{mode}")
        assert gen.status_code == 200, (mode, gen.get_json())
        assert gen.get_json()["mode"] == mode

        # PDF landed under the reserved _org segment.
        pdf_path = os.path.join(campaign_store.GENERATED_REPORT_DIR, "acme-ltd", cid, "_org", f"{mode}.pdf")
        assert os.path.exists(pdf_path)

        dl = client.get(f"/downloadOrgReport/{cid}/{mode}")
        assert dl.status_code == 200
        assert dl.data[:5] == b"%PDF-"


def test_combined_degraded_when_employees_below_threshold(client, mock_openai):
    # Both tracks enabled, org present, but too few employees -> combined still
    # renders the org self-assessment side rather than failing.
    cid = _create_campaign(client, tracks=["employee", "organization"])
    _seed_employees(client, cid, 3)
    _seed_org(client, cid)
    gen = client.post(f"/generateOrgReport/{cid}/combined")
    assert gen.status_code == 200
    dl = client.get(f"/downloadOrgReport/{cid}/combined")
    assert dl.status_code == 200
    assert dl.data[:5] == b"%PDF-"
