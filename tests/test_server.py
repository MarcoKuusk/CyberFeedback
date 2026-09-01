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
    body = response.get_json()
    campaign = body["campaign"]
    # The per-track link token is what a respondent actually holds; it, not the
    # campaign id, is the credential every respondent-facing route accepts.
    campaign["links"] = body["links"]
    return campaign


def _token(campaign, track="employee"):
    return campaign["links"][track]["token"]


def _org_token(campaign):
    return _token(campaign, "organization")


_DEFAULT = object()


def _submit(client, campaign, track="employee", payload=_DEFAULT):
    # A distinct sentinel, so `payload=None` still exercises the null-body path.
    return client.post(
        f"/api/link/{_token(campaign, track)}/submit",
        json=_submission() if payload is _DEFAULT else payload,
    )


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
        _submit(client, campaign)
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

    def test_campaign_detail_is_no_longer_public(self, client, monkeypatch):
        """Respondents reach an assessment by token now, so the id-addressed
        detail route is administrative and must be gated like the rest."""
        campaign = _new_campaign(client)
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "s3cret")
        assert client.get(f"/api/campaigns/{campaign['campaign_id']}").status_code == 403

    def test_campaign_detail_hides_internal_fields(self, client):
        campaign = _new_campaign(client)
        body = client.get(f"/api/campaigns/{campaign['campaign_id']}").get_json()
        assert set(body["campaign"]) == {"campaign_id", "org_name", "tracks", "locale", "status"}
        assert "tokens" not in body["campaign"]

    def test_campaign_detail_unknown_is_404(self, client):
        assert client.get(f"/api/campaigns/{'0' * 32}").status_code == 404

    @pytest.mark.parametrize("bad", ["..", "../../etc", "abc", "A" * 32, "0" * 31])
    def test_campaign_detail_rejects_adversarial_ids(self, client, bad):
        assert client.get(f"/api/campaigns/{bad}").status_code in (400, 404)


# ---------------------------------------------------------------------------
# Campaign links — one unguessable token per track
# ---------------------------------------------------------------------------

class TestCampaignLinks:
    def test_creation_mints_one_token_per_enabled_track(self, client):
        campaign = _new_campaign(client)
        assert set(campaign["links"]) == {"employee", "organization"}
        for track in ("employee", "organization"):
            assert cs._ID_PATTERN.match(_token(campaign, track))

    def test_tokens_differ_between_tracks(self, client):
        """The whole point: a staff link must not open the leadership survey."""
        campaign = _new_campaign(client)
        assert _token(campaign) != _org_token(campaign)

    def test_disabled_track_gets_no_token(self, client):
        campaign = _new_campaign(client, tracks=("employee",))
        assert set(campaign["links"]) == {"employee"}

    def test_tokens_differ_between_campaigns(self, client):
        assert _token(_new_campaign(client)) != _token(_new_campaign(client))

    def test_links_endpoint_is_operator_only(self, client, monkeypatch):
        """Leadership holds a viewer token; recovering the staff link from it
        would let them enumerate nothing useful, but the leadership link is a
        credential and must not be re-derivable by a lesser role."""
        campaign = _new_campaign(client)
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "op")
        monkeypatch.setenv("CYBERFEEDBACK_VIEWER_TOKEN", "view")
        path = f"/api/campaigns/{campaign['campaign_id']}/links"
        assert client.get(path).status_code == 403
        assert client.get(path, headers={"X-Admin-Token": "view"}).status_code == 403
        assert client.get(path, headers={"X-Admin-Token": "op"}).status_code == 200

    def test_links_endpoint_is_stable_across_calls(self, client):
        """Backfill must be idempotent: a link already emailed to staff cannot
        be invalidated by an operator opening the admin page again."""
        campaign = _new_campaign(client)
        path = f"/api/campaigns/{campaign['campaign_id']}/links"
        first = client.get(path).get_json()["links"]
        second = client.get(path).get_json()["links"]
        assert first == second
        assert first["employee"]["token"] == _token(campaign)

    def test_links_use_the_configured_public_url(self, client, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_PUBLIC_URL", "https://assess.example.com/")
        campaign = _new_campaign(client)
        assert campaign["links"]["employee"]["url"] == f"https://assess.example.com/c/{_token(campaign)}"

    def test_legacy_campaign_without_tokens_is_backfilled(self, client):
        campaign = _new_campaign(client)
        registry = cs._read_registry()
        del registry["campaigns"][campaign["campaign_id"]]["tokens"]
        cs._write_registry(registry)

        links = client.get(f"/api/campaigns/{campaign['campaign_id']}/links").get_json()["links"]
        assert set(links) == {"employee", "organization"}
        assert cs._ID_PATTERN.match(links["employee"]["token"])


# ---------------------------------------------------------------------------
# Link resolution — what a respondent's browser sees
# ---------------------------------------------------------------------------

class TestLinkResolution:
    def test_resolve_returns_org_and_track(self, client):
        campaign = _new_campaign(client)
        body = client.get(f"/api/link/{_token(campaign)}").get_json()
        assert body["track"] == "employee"
        assert body["campaign"]["org_name"] == "Acme Ltd"

    def test_resolve_does_not_disclose_the_other_track(self, client):
        campaign = _new_campaign(client)
        body = client.get(f"/api/link/{_token(campaign)}").get_json()
        assert set(body["campaign"]) == {"org_name", "locale", "status"}
        assert "campaign_id" not in body["campaign"]
        assert "tracks" not in body["campaign"]

    def test_leadership_token_resolves_to_the_org_track(self, client):
        campaign = _new_campaign(client)
        assert client.get(f"/api/link/{_org_token(campaign)}").get_json()["track"] == "organization"

    def test_resolve_requires_no_authentication(self, client, monkeypatch):
        campaign = _new_campaign(client)
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "s3cret")
        assert client.get(f"/api/link/{_token(campaign)}").status_code == 200

    @pytest.mark.parametrize("bad", ["..", "abc", "A" * 32, "0" * 31, "%2e%2e", "0" * 32])
    def test_resolve_rejects_bad_tokens(self, client, bad):
        assert client.get(f"/api/link/{bad}").status_code in (400, 404)

    def test_campaign_link_page_is_served(self, client):
        campaign = _new_campaign(client)
        response = client.get(f"/c/{_token(campaign)}")
        assert response.status_code == 200
        assert b"<html" in response.data.lower()


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class TestSaveAssessment:
    def test_save_returns_respondent_id(self, client):
        campaign = _new_campaign(client)
        response = _submit(client, campaign)
        assert response.status_code == 200
        assert cs._ID_PATTERN.match(response.get_json()["respondent_id"])

    def test_submission_lands_in_the_track_the_token_grants(self, client, isolated):
        """The confidentiality guarantee, at the storage layer: a leadership
        token cannot deposit a record into the employee track or vice versa."""
        data, _ = isolated
        campaign = _new_campaign(client)
        _submit(client, campaign, track="organization")
        base = data / "acme-ltd" / campaign["campaign_id"]
        assert len(list((base / "organization").glob("*.json"))) == 1
        assert not (base / "employee").exists() or not list((base / "employee").glob("*.json"))

    def test_concurrent_respondents_do_not_overwrite(self, client, isolated):
        """The data-loss bug, verified through the HTTP layer."""
        data, _ = isolated
        campaign = _new_campaign(client)
        ids = [_submit(client, campaign).get_json()["respondent_id"] for _ in range(5)]

        assert len(set(ids)) == 5
        stored = list((data / "acme-ltd" / campaign["campaign_id"] / "employee").glob("*.json"))
        assert len(stored) == 5

    def test_save_without_consent_is_rejected_and_stores_nothing(self, client, isolated):
        data, _ = isolated
        campaign = _new_campaign(client)
        response = _submit(client, campaign, payload=_submission(consent=False))
        assert response.status_code == 400
        assert "consent" in response.get_json()["message"].lower()
        track_dir = data / "acme-ltd" / campaign["campaign_id"] / "employee"
        assert not track_dir.exists() or not list(track_dir.glob("*.json"))

    @pytest.mark.parametrize("consent", [{"agreed": False, "version": "1.0"}, {"agreed": True}, {}, "yes"])
    def test_save_rejects_malformed_consent(self, client, consent):
        campaign = _new_campaign(client)
        payload = _submission()
        payload["consent"] = consent
        assert _submit(client, campaign, payload=payload).status_code == 400

    def test_save_rejects_a_closed_campaign(self, client):
        campaign = _new_campaign(client)
        cs.set_campaign_status(campaign["campaign_id"], "closed")
        assert _submit(client, campaign).status_code == 409

    @pytest.mark.parametrize("bad", ["..", "abc", "A" * 32, "0" * 31, "%2e%2e", "0" * 32])
    def test_save_rejects_adversarial_tokens(self, client, bad):
        assert client.post(f"/api/link/{bad}/submit", json=_submission()).status_code in (400, 404)

    @pytest.mark.parametrize("payload", [None, {}, {"responses": []}, {"responses": "x"}])
    def test_save_rejects_malformed_payloads(self, client, payload):
        campaign = _new_campaign(client)
        assert _submit(client, campaign, payload=payload).status_code == 400


# ---------------------------------------------------------------------------
# Report generation and download
# ---------------------------------------------------------------------------

class TestReports:
    def _saved(self, client, track="employee"):
        campaign = _new_campaign(client)
        respondent_id = _submit(client, campaign, track=track).get_json()["respondent_id"]
        return campaign, respondent_id

    def test_generate_writes_a_campaign_scoped_pdf(self, client, isolated):
        _, reports = isolated
        campaign, respondent_id = self._saved(client)
        response = client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}")
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
            ids.append(_submit(client, campaign, payload=payload).get_json()["respondent_id"])

        for respondent_id in ids:
            assert client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}").status_code == 200

        pdfs = list((reports / "acme-ltd" / campaign["campaign_id"] / "employee").glob("*.pdf"))
        assert len(pdfs) == 2
        assert {p.stem for p in pdfs} == set(ids)

    def test_generate_rejects_unknown_respondent(self, client):
        campaign = _new_campaign(client)
        assert client.post(f"/api/link/{_token(campaign)}/report/{'0' * 32}").status_code == 404

    def test_generate_cannot_cross_tracks(self, client):
        """A leadership token cannot render the report of an employee
        respondent, even knowing that respondent's id."""
        campaign, respondent_id = self._saved(client, track="employee")
        assert client.post(f"/api/link/{_org_token(campaign)}/report/{respondent_id}").status_code == 404

    def test_generate_cannot_cross_campaigns(self, client):
        campaign_a, respondent_id = self._saved(client)
        campaign_b = _new_campaign(client)
        assert client.post(f"/api/link/{_token(campaign_b)}/report/{respondent_id}").status_code == 404

    @pytest.mark.parametrize("bad", ["..", "abc", "A" * 32, "0" * 31])
    def test_generate_rejects_adversarial_respondent_ids(self, client, bad):
        campaign = _new_campaign(client)
        assert client.post(f"/api/link/{_token(campaign)}/report/{bad}").status_code in (400, 404)

    def test_download_before_generation_is_404(self, client):
        campaign, respondent_id = self._saved(client)
        assert client.get(f"/api/link/{_token(campaign)}/report/{respondent_id}").status_code == 404

    def test_download_returns_the_pdf(self, client):
        campaign, respondent_id = self._saved(client)
        client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}")
        response = client.get(f"/api/link/{_token(campaign)}/report/{respondent_id}")
        assert response.status_code == 200
        assert response.data[:4] == b"%PDF"
        assert "attachment" in response.headers["Content-Disposition"]

    def test_download_cannot_cross_tracks(self, client):
        campaign, respondent_id = self._saved(client, track="employee")
        client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}")
        assert client.get(f"/api/link/{_org_token(campaign)}/report/{respondent_id}").status_code == 404

    @pytest.mark.parametrize("bad", ["..", "abc", "0" * 31, "A" * 32])
    def test_download_rejects_adversarial_ids(self, client, bad):
        campaign = _new_campaign(client)
        assert client.get(f"/api/link/{_token(campaign)}/report/{bad}").status_code in (400, 404)

    def test_missing_api_key_surfaces_a_clean_error(self, client, monkeypatch):
        campaign, respondent_id = self._saved(client)

        def _raise():
            raise RuntimeError("Missing OPENAI_API_KEY environment variable. Set it before generating reports.")

        monkeypatch.setattr(employee_feedback_generator, "load_api_key", _raise)
        response = client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}")
        assert response.status_code == 500
        assert "OPENAI_API_KEY" in response.get_json()["message"]

    def test_ai_failure_returns_a_generic_error(self, client, monkeypatch):
        campaign, respondent_id = self._saved(client)

        def _boom(api_key, prompt):
            raise Exception("upstream exploded with /secret/path/detail")

        monkeypatch.setattr(employee_feedback_generator, "generate_report_text", _boom)
        response = client.post(f"/api/link/{_token(campaign)}/report/{respondent_id}")
        assert response.status_code == 500
        message = response.get_json()["message"]
        assert "secret" not in message and "Traceback" not in message


# ---------------------------------------------------------------------------
# Role separation — operator vs. the client's leadership
# ---------------------------------------------------------------------------

class TestRoleSeparation:
    """Operator vs. the leadership of one client organization.

    The viewer credential is minted per campaign, so it answers two questions at
    once: what leadership may see, and whose data they may see it for.
    """

    OP = {"X-Admin-Token": "op-token"}

    @pytest.fixture(autouse=True)
    def operator_token(self, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "op-token")

    def _campaign(self, client, org_name="Acme Ltd", submissions=1):
        response = client.post(
            "/api/campaigns", json={"org_name": org_name, "tracks": ["employee"]}, headers=self.OP
        )
        body = response.get_json()
        campaign = body["campaign"]
        campaign["links"] = body["links"]
        campaign["viewer"] = body["viewer"]
        for _ in range(submissions):
            _submit(client, campaign)
        return campaign

    @staticmethod
    def _view(campaign):
        return {"X-Admin-Token": campaign["viewer"]["token"]}

    def test_creation_issues_a_viewer_credential(self, client):
        campaign = self._campaign(client)
        assert cs._ID_PATTERN.match(campaign["viewer"]["token"])
        assert campaign["viewer"]["url"].endswith("/admin")

    def test_viewer_credential_differs_from_the_staff_link(self, client):
        campaign = self._campaign(client)
        assert campaign["viewer"]["token"] != _token(campaign)

    def test_viewer_cannot_create_campaigns(self, client):
        campaign = self._campaign(client)
        response = client.post(
            "/api/campaigns", json={"org_name": "Other", "tracks": ["employee"]}, headers=self._view(campaign)
        )
        assert response.status_code == 403

    def test_viewer_cannot_read_the_link_tokens(self, client):
        """The staff link is a distributable credential; leadership distributes
        it, but re-deriving it is the operator's job, not a read they get."""
        campaign = self._campaign(client)
        path = f"/api/campaigns/{campaign['campaign_id']}/links"
        assert client.get(path, headers=self._view(campaign)).status_code == 403

    def test_viewer_never_receives_respondent_ids(self, client):
        """A respondent id is the bearer credential for that person's private
        report. Leadership getting one would undo the whole promise."""
        campaign = self._campaign(client)
        body = client.get(
            f"/api/campaigns/{campaign['campaign_id']}/submissions", headers=self._view(campaign)
        ).get_json()

        assert body["role"] == "viewer"
        assert body["participation"] == {"employee": 1}
        assert "submissions" not in body

        real_ids = cs.list_respondents(campaign["campaign_id"], "employee")
        assert real_ids and all(rid not in str(body) for rid in real_ids)

    def test_operator_does_receive_respondent_ids(self, client):
        campaign = self._campaign(client)
        body = client.get(
            f"/api/campaigns/{campaign['campaign_id']}/submissions", headers=self.OP
        ).get_json()

        assert body["role"] == "operator"
        assert len(body["submissions"]["employee"]) == 1
        assert cs._ID_PATTERN.match(body["submissions"]["employee"][0]["respondent_id"])

    def test_viewer_may_reach_their_own_org_rollups(self, client):
        """Leadership is entitled to the aggregate; that is what they bought."""
        campaign = self._campaign(client)
        path = f"/downloadOrgReport/{campaign['campaign_id']}/aggregate"
        # Not generated yet, so 404 — the point is that the role gate is not
        # what rejects it, while an unauthenticated caller is refused outright.
        assert client.get(path, headers=self._view(campaign)).status_code == 404
        assert client.get(path).status_code == 403

    def test_viewer_listing_shows_only_their_own_campaign(self, client):
        acme = self._campaign(client, org_name="Acme Ltd")
        self._campaign(client, org_name="Globex OU")

        body = client.get("/api/campaigns", headers=self._view(acme)).get_json()
        assert [c["campaign_id"] for c in body["campaigns"]] == [acme["campaign_id"]]
        assert body["role"] == "viewer"

    def test_operator_listing_shows_every_campaign(self, client):
        self._campaign(client, org_name="Acme Ltd")
        self._campaign(client, org_name="Globex OU")
        body = client.get("/api/campaigns", headers=self.OP).get_json()
        assert len(body["campaigns"]) == 2

    # -- cross-tenant isolation ------------------------------------------- #

    def test_viewer_cannot_read_another_clients_participation(self, client):
        """Several client organizations share one deployment. One client's
        leadership must not reach another's data even knowing its campaign id."""
        acme = self._campaign(client, org_name="Acme Ltd")
        globex = self._campaign(client, org_name="Globex OU")

        response = client.get(
            f"/api/campaigns/{globex['campaign_id']}/submissions", headers=self._view(acme)
        )
        assert response.status_code == 403

    def test_viewer_cannot_read_another_clients_campaign_detail(self, client):
        acme = self._campaign(client, org_name="Acme Ltd")
        globex = self._campaign(client, org_name="Globex OU")
        assert client.get(
            f"/api/campaigns/{globex['campaign_id']}", headers=self._view(acme)
        ).status_code == 403

    def test_viewer_cannot_generate_another_clients_rollup(self, client):
        acme = self._campaign(client, org_name="Acme Ltd")
        globex = self._campaign(client, org_name="Globex OU")
        assert client.post(
            f"/generateOrgReport/{globex['campaign_id']}/aggregate", headers=self._view(acme)
        ).status_code == 403

    def test_viewer_cannot_download_another_clients_rollup(self, client):
        acme = self._campaign(client, org_name="Acme Ltd")
        globex = self._campaign(client, org_name="Globex OU")
        assert client.get(
            f"/downloadOrgReport/{globex['campaign_id']}/aggregate", headers=self._view(acme)
        ).status_code == 403

    def test_deleting_a_campaign_kills_its_viewer_credential(self, client):
        campaign = self._campaign(client)
        registry = cs._read_registry()
        del registry["campaigns"][campaign["campaign_id"]]
        cs._write_registry(registry)
        assert client.get("/api/campaigns", headers=self._view(campaign)).status_code == 403

    # -- credential hygiene ------------------------------------------------ #

    def test_unknown_token_gets_nothing(self, client):
        campaign = self._campaign(client)
        bad = {"X-Admin-Token": "nope"}
        assert client.get("/api/campaigns", headers=bad).status_code == 403
        assert client.get(
            f"/api/campaigns/{campaign['campaign_id']}/submissions", headers=bad
        ).status_code == 403

    def test_viewer_token_is_ignored_without_an_operator_token(self, client, monkeypatch):
        """A half-configured deployment must not grant remote access: with no
        operator token the app is in its loopback-only development posture."""
        campaign = self._campaign(client)
        monkeypatch.delenv("CYBERFEEDBACK_ADMIN_TOKEN")
        response = client.get(
            "/api/campaigns", headers=self._view(campaign), environ_overrides={"REMOTE_ADDR": "10.0.0.9"}
        )
        assert response.status_code == 403

    def test_legacy_campaign_without_a_viewer_token_is_backfilled(self, client):
        campaign = self._campaign(client)
        registry = cs._read_registry()
        del registry["campaigns"][campaign["campaign_id"]]["viewer_token"]
        cs._write_registry(registry)

        body = client.get(
            f"/api/campaigns/{campaign['campaign_id']}/links", headers=self.OP
        ).get_json()
        assert cs._ID_PATTERN.match(body["viewer"]["token"])

    def test_backfilled_viewer_token_is_stable(self, client):
        campaign = self._campaign(client)
        path = f"/api/campaigns/{campaign['campaign_id']}/links"
        first = client.get(path, headers=self.OP).get_json()["viewer"]["token"]
        second = client.get(path, headers=self.OP).get_json()["viewer"]["token"]
        assert first == second == campaign["viewer"]["token"]


# ---------------------------------------------------------------------------
# Error hygiene
# ---------------------------------------------------------------------------

class TestErrorHygiene:
    def test_errors_never_leak_filesystem_paths(self, client, isolated):
        data, reports = isolated
        campaign = _new_campaign(client)
        responses = [
            client.post("/api/link/../submit", json=_submission()),
            client.post(f"/api/link/{'0' * 32}/submit", json=_submission()),
            client.post(f"/api/link/{_token(campaign)}/report/{'0' * 32}"),
            client.get(f"/api/link/{_token(campaign)}/report/{'0' * 32}"),
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


# ---------------------------------------------------------------------------
# The admin console shell
# ---------------------------------------------------------------------------

class TestAdminConsoleReachability:
    """A browser cannot attach X-Admin-Token to a navigation.

    So the console shell must load without a credential, or the operator can
    never reach the prompt that asks for one. The data behind it stays gated.
    """

    @pytest.fixture(autouse=True)
    def token_configured(self, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "op-token")

    def test_admin_page_loads_without_a_header(self, client):
        response = client.get("/admin")
        assert response.status_code == 200
        assert b"<html" in response.data.lower()

    def test_admin_script_loads_without_a_header(self, client):
        assert client.get("/admin.js").status_code == 200

    def test_but_the_data_behind_it_is_still_gated(self, client):
        """The shell being public must not make anything in it readable."""
        assert client.get("/api/campaigns").status_code == 403

    def test_operator_reaches_the_data_with_the_header(self, client):
        assert client.get("/api/campaigns", headers={"X-Admin-Token": "op-token"}).status_code == 200
