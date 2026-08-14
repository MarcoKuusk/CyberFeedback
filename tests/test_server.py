"""Endpoint tests for the campaign-scoped API.

Real files in tmp directories; OpenAI is mocked at the client boundary so no
test ever reaches the live API (per CLAUDE.md).
"""

import os

import pytest

import campaign_store as cs
import server
from Feedback_Generators import employee_feedback_generator, organization_feedback_generator

CANNED_AI_REPORT = """# Employee Cyber Hygiene Report
## Executive Summary
Overall hygiene is developing, with clear gaps in password practice.
## What You Are Doing Well
- Device locking is consistent.
## Priority Risks
- Password reuse across accounts.
## 30-60-90 Day Action Roadmap
### Next 30 Days
- Adopt a password manager.
### Next 60 Days
- Enable MFA everywhere.
### Next 90 Days
- Review recovery codes.
## Category Breakdown
Password practice is the weakest area.
## Appendix: Response Highlights
- Reported reusing passwords across accounts.
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    data.mkdir()
    reports.mkdir()
    monkeypatch.setattr(cs, "DATA_DIR", str(data))
    monkeypatch.setattr(cs, "REPORT_DIR", str(reports))
    monkeypatch.delenv("CYBERFEEDBACK_ADMIN_TOKEN", raising=False)

    # Mock the OpenAI boundary in both generator modules.
    for module in (employee_feedback_generator, organization_feedback_generator):
        monkeypatch.setattr(module, "load_api_key", lambda: "test-key")
        monkeypatch.setattr(module, "generate_report_text", lambda api_key, prompt: CANNED_AI_REPORT)

    return data, reports


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    return server.app.test_client()


def _submission(consent=True):
    payload = {
        "responses": [
            {
                "question": "Do you use unique passwords?",
                "category": "Password & Access Management",
                "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
                "selectedAnswer": {"option": "No", "score": 0},
            },
            {
                "question": "Do you use MFA?",
                "category": "Password & Access Management",
                "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
                "selectedAnswer": {"option": "Yes", "score": 4},
            },
        ],
        "metadata": {"report_type": "employee", "generated_from": "web-interface"},
    }
    if consent:
        payload["consent"] = {"agreed": True, "version": "1.0-draft"}
    return payload


def _new_campaign(client, tracks=("employee", "organization")):
    response = client.post("/api/campaigns", json={"org_name": "Acme Ltd", "tracks": list(tracks)})
    assert response.status_code == 201
    return response.get_json()["campaign"]


# ---------------------------------------------------------------------------
# Campaign management + admin gate
# ---------------------------------------------------------------------------

class TestCampaignEndpoints:
    def test_create_from_loopback_is_allowed(self, client):
        campaign = _new_campaign(client)
        assert cs._ID_PATTERN.match(campaign["campaign_id"])
        assert campaign["org_name"] == "Acme Ltd"
        assert campaign["status"] == "open"
        assert "org_slug" not in campaign  # internal detail stays server-side

    def test_create_requires_token_when_one_is_configured(self, client, monkeypatch):
        """Once bound to the org LAN, loopback is no longer a sufficient gate."""
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "s3cret")
        denied = client.post("/api/campaigns", json={"org_name": "Acme", "tracks": ["employee"]})
        assert denied.status_code == 403

        allowed = client.post(
            "/api/campaigns",
            json={"org_name": "Acme", "tracks": ["employee"]},
            headers={"X-Admin-Token": "s3cret"},
        )
        assert allowed.status_code == 201

    def test_create_rejects_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "s3cret")
        response = client.post(
            "/api/campaigns",
            json={"org_name": "Acme", "tracks": ["employee"]},
            headers={"X-Admin-Token": "wrong"},
        )
        assert response.status_code == 403

    def test_listing_is_admin_gated(self, client, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "s3cret")
        assert client.get("/api/campaigns").status_code == 403

    def test_listing_reports_participation(self, client):
        campaign = _new_campaign(client)
        client.post(f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=_submission())
        body = client.get("/api/campaigns").get_json()
        entry = next(c for c in body["campaigns"] if c["campaign_id"] == campaign["campaign_id"])
        assert entry["participation"] == {"employee": 1, "organization": 0}

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"org_name": "", "tracks": ["employee"]},
            {"org_name": "   ", "tracks": ["employee"]},
            {"org_name": "Acme"},
            {"org_name": "Acme", "tracks": []},
            {"org_name": "Acme", "tracks": ["admin"]},
            {"org_name": "Acme", "tracks": "employee"},
            {"org_name": "Acme", "tracks": ["employee"], "locale": "fr"},
        ],
    )
    def test_create_rejects_invalid_payloads(self, client, payload):
        assert client.post("/api/campaigns", json=payload).status_code == 400

    def test_public_lookup_returns_campaign(self, client):
        campaign = _new_campaign(client)
        body = client.get(f"/api/campaigns/{campaign['campaign_id']}").get_json()
        assert body["campaign"]["tracks"] == ["employee", "organization"]

    def test_public_lookup_hides_internal_fields(self, client):
        campaign = _new_campaign(client)
        body = client.get(f"/api/campaigns/{campaign['campaign_id']}").get_json()
        assert set(body["campaign"]) == {"campaign_id", "org_name", "tracks", "locale", "status"}

    def test_public_lookup_unknown_is_404(self, client):
        assert client.get(f"/api/campaigns/{'0' * 32}").status_code == 404

    @pytest.mark.parametrize("bad", ["..", "../../etc", "abc", "A" * 32, "0" * 31])
    def test_public_lookup_rejects_adversarial_ids(self, client, bad):
        assert client.get(f"/api/campaigns/{bad}").status_code in (400, 404)


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class TestSaveAssessment:
    def test_save_returns_respondent_id(self, client):
        campaign = _new_campaign(client)
        response = client.post(f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=_submission())
        assert response.status_code == 200
        assert cs._ID_PATTERN.match(response.get_json()["respondent_id"])

    def test_concurrent_respondents_do_not_overwrite(self, client, isolated):
        """The data-loss bug, verified through the HTTP layer."""
        data, _ = isolated
        campaign = _new_campaign(client)
        ids = []
        for _ in range(5):
            response = client.post(f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=_submission())
            ids.append(response.get_json()["respondent_id"])

        assert len(set(ids)) == 5
        stored = list((data / "acme-ltd" / campaign["campaign_id"] / "employee").glob("*.json"))
        assert len(stored) == 5

    def test_save_without_consent_is_rejected_and_stores_nothing(self, client, isolated):
        data, _ = isolated
        campaign = _new_campaign(client)
        response = client.post(
            f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=_submission(consent=False)
        )
        assert response.status_code == 400
        assert "consent" in response.get_json()["message"].lower()
        track_dir = data / "acme-ltd" / campaign["campaign_id"] / "employee"
        assert not track_dir.exists() or not list(track_dir.glob("*.json"))

    @pytest.mark.parametrize("consent", [{"agreed": False, "version": "1.0"}, {"agreed": True}, {}, "yes"])
    def test_save_rejects_malformed_consent(self, client, consent):
        campaign = _new_campaign(client)
        payload = _submission()
        payload["consent"] = consent
        assert client.post(f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=payload).status_code == 400

    def test_save_rejects_disabled_track(self, client):
        campaign = _new_campaign(client, tracks=("employee",))
        response = client.post(f"/saveAssessmentData/{campaign['campaign_id']}/organization", json=_submission())
        assert response.status_code == 404

    def test_save_rejects_unknown_campaign(self, client):
        assert client.post(f"/saveAssessmentData/{'0' * 32}/employee", json=_submission()).status_code == 404

    @pytest.mark.parametrize("track", ["admin", "Employee", "employee2"])
    def test_save_rejects_non_allowlisted_track(self, client, track):
        campaign = _new_campaign(client)
        assert client.post(f"/saveAssessmentData/{campaign['campaign_id']}/{track}", json=_submission()).status_code in (
            400,
            404,
        )

    @pytest.mark.parametrize("bad", ["..", "abc", "A" * 32, "0" * 31, "%2e%2e"])
    def test_save_rejects_adversarial_campaign_ids(self, client, bad):
        response = client.post(f"/saveAssessmentData/{bad}/employee", json=_submission())
        assert response.status_code in (400, 404)

    @pytest.mark.parametrize("payload", [None, {}, {"responses": []}, {"responses": "x"}])
    def test_save_rejects_malformed_payloads(self, client, payload):
        campaign = _new_campaign(client)
        assert client.post(f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=payload).status_code == 400


# ---------------------------------------------------------------------------
# Report generation and download
# ---------------------------------------------------------------------------

class TestReports:
    def _saved(self, client, track="employee"):
        campaign = _new_campaign(client)
        respondent_id = client.post(
            f"/saveAssessmentData/{campaign['campaign_id']}/{track}", json=_submission()
        ).get_json()["respondent_id"]
        return campaign, respondent_id

    def test_generate_writes_a_campaign_scoped_pdf(self, client, isolated):
        _, reports = isolated
        campaign, respondent_id = self._saved(client)
        response = client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{respondent_id}")
        assert response.status_code == 200
        assert response.get_json()["summary"]["overall_score"] == 50.0

        expected = reports / "acme-ltd" / campaign["campaign_id"] / "employee" / f"{respondent_id}.pdf"
        assert expected.exists() and expected.stat().st_size > 0

    def test_two_respondents_get_two_distinct_pdfs(self, client, isolated):
        """The bug that could serve one person's report to another, end to end."""
        _, reports = isolated
        campaign = _new_campaign(client)
        ids = []
        for score in (0, 4):
            payload = _submission()
            payload["responses"][0]["selectedAnswer"] = {"option": "x", "score": score}
            ids.append(
                client.post(
                    f"/saveAssessmentData/{campaign['campaign_id']}/employee", json=payload
                ).get_json()["respondent_id"]
            )

        for respondent_id in ids:
            assert client.post(
                f"/generateFeedback/{campaign['campaign_id']}/employee/{respondent_id}"
            ).status_code == 200

        pdfs = list((reports / "acme-ltd" / campaign["campaign_id"] / "employee").glob("*.pdf"))
        assert len(pdfs) == 2
        assert {p.stem for p in pdfs} == set(ids)

    def test_generate_rejects_unknown_respondent(self, client):
        campaign = _new_campaign(client)
        assert client.post(
            f"/generateFeedback/{campaign['campaign_id']}/employee/{'0' * 32}"
        ).status_code == 404

    def test_generate_cannot_cross_tracks(self, client):
        campaign, respondent_id = self._saved(client, track="employee")
        assert client.post(
            f"/generateFeedback/{campaign['campaign_id']}/organization/{respondent_id}"
        ).status_code == 404

    def test_generate_cannot_cross_campaigns(self, client):
        campaign_a, respondent_id = self._saved(client)
        campaign_b = _new_campaign(client)
        assert client.post(
            f"/generateFeedback/{campaign_b['campaign_id']}/employee/{respondent_id}"
        ).status_code == 404

    @pytest.mark.parametrize("bad", ["..", "abc", "A" * 32, "0" * 31])
    def test_generate_rejects_adversarial_respondent_ids(self, client, bad):
        campaign = _new_campaign(client)
        assert client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{bad}").status_code in (400, 404)

    def test_download_before_generation_is_404(self, client):
        campaign, respondent_id = self._saved(client)
        assert client.get(f"/downloadReport/{campaign['campaign_id']}/employee/{respondent_id}").status_code == 404

    def test_download_returns_the_pdf(self, client):
        campaign, respondent_id = self._saved(client)
        client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{respondent_id}")
        response = client.get(f"/downloadReport/{campaign['campaign_id']}/employee/{respondent_id}")
        assert response.status_code == 200
        assert response.data[:4] == b"%PDF"
        assert "attachment" in response.headers["Content-Disposition"]

    @pytest.mark.parametrize("bad", ["..", "abc", "0" * 31, "A" * 32])
    def test_download_rejects_adversarial_ids(self, client, bad):
        campaign = _new_campaign(client)
        assert client.get(f"/downloadReport/{campaign['campaign_id']}/employee/{bad}").status_code in (400, 404)

    def test_missing_api_key_surfaces_a_clean_error(self, client, monkeypatch):
        campaign, respondent_id = self._saved(client)

        def _raise():
            raise RuntimeError("Missing OPENAI_API_KEY environment variable. Set it before generating reports.")

        monkeypatch.setattr(employee_feedback_generator, "load_api_key", _raise)
        response = client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{respondent_id}")
        assert response.status_code == 500
        assert "OPENAI_API_KEY" in response.get_json()["message"]

    def test_ai_failure_returns_a_generic_error(self, client, monkeypatch):
        campaign, respondent_id = self._saved(client)

        def _boom(api_key, prompt):
            raise Exception("upstream exploded with /secret/path/detail")

        monkeypatch.setattr(employee_feedback_generator, "generate_report_text", _boom)
        response = client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{respondent_id}")
        assert response.status_code == 500
        message = response.get_json()["message"]
        assert "secret" not in message and "Traceback" not in message


# ---------------------------------------------------------------------------
# Error hygiene
# ---------------------------------------------------------------------------

class TestErrorHygiene:
    def test_errors_never_leak_filesystem_paths(self, client, isolated):
        data, reports = isolated
        campaign = _new_campaign(client)
        responses = [
            client.post(f"/saveAssessmentData/{'..'}/employee", json=_submission()),
            client.post(f"/saveAssessmentData/{'0' * 32}/employee", json=_submission()),
            client.post(f"/generateFeedback/{campaign['campaign_id']}/employee/{'0' * 32}"),
            client.get(f"/downloadReport/{campaign['campaign_id']}/employee/{'0' * 32}"),
            client.get(f"/api/campaigns/{'..'}"),
        ]
        for response in responses:
            body = response.get_data(as_text=True)
            assert str(data) not in body
            assert str(reports) not in body
            assert "Traceback" not in body
            assert os.sep + "src" + os.sep not in body

    def test_questionnaire_endpoint_still_serves_both_tracks(self, client):
        for track in ("employee", "organization"):
            body = client.get(f"/api/questionnaire/{track}").get_json()
            assert body["status"] == "ok"
            assert body["questionnaire"]["questions"]

    def test_questionnaire_rejects_bad_track(self, client):
        assert client.get("/api/questionnaire/../../etc/passwd").status_code in (400, 404)
        assert client.get("/api/questionnaire/admin").status_code == 400
