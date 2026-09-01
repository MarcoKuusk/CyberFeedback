"""Tests for the operator scripts: research export and organization deletion.

Both handle data that must not leak and actions that cannot be undone, so they
are covered like product code rather than treated as throwaway tooling.
"""

import csv
import os
import sys

import pytest

import campaign_store as cs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import delete_org_data  # noqa: E402
import export_research_data  # noqa: E402

CONSENT = {"agreed": True, "version": "1.0-draft"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    data.mkdir()
    reports.mkdir()
    monkeypatch.setattr(cs, "DATA_DIR", str(data))
    monkeypatch.setattr(cs, "REPORT_DIR", str(reports))
    return data, reports


def _responses(score=4):
    return [
        {
            "question": "Do you use unique passwords?",
            "category": "Password & Access Management",
            "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
            "selectedAnswer": {"option": "Yes" if score else "No", "score": score},
        },
        {
            "question": "Do you report suspicious email?",
            "category": "Phishing Awareness & Email Security",
            "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
            "selectedAnswer": {"option": "Yes" if score else "No", "score": score},
        },
    ]


def _seed(org_name="Acme Ltd", tracks=("employee",), respondents=3, close=True):
    campaign = cs.create_campaign(org_name, list(tracks))
    for track in tracks:
        for index in range(respondents):
            cs.save_submission(
                campaign["campaign_id"],
                track,
                {"responses": _responses(4 if index % 2 else 0), "metadata": {"secret": "do-not-export"}, "consent": CONSENT},
            )
    if close:
        cs.set_campaign_status(campaign["campaign_id"], "closed")
    return campaign


def _read(out_dir, name):
    with open(os.path.join(out_dir, f"{name}.csv"), encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Research export
# ---------------------------------------------------------------------------

class TestResearchExport:
    def test_exports_all_four_tables(self, tmp_path):
        _seed()
        out = str(tmp_path / "out")
        assert export_research_data.main(["--out", out]) == 0
        for name in ("campaigns", "respondents", "respondent_categories", "responses_long"):
            assert os.path.exists(os.path.join(out, f"{name}.csv"))

    def test_row_counts_match_the_data(self, tmp_path):
        _seed(respondents=3)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        assert len(_read(out, "campaigns")) == 1
        assert len(_read(out, "respondents")) == 3
        # 3 respondents x 2 questions
        assert len(_read(out, "responses_long")) == 6
        # 3 respondents x 2 categories
        assert len(_read(out, "respondent_categories")) == 6

    def test_organization_name_never_appears(self, tmp_path):
        """The dataset must be publishable without naming the client."""
        _seed(org_name="Very Distinctive Client Name OU")
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        for name in ("campaigns", "respondents", "respondent_categories", "responses_long"):
            with open(os.path.join(out, f"{name}.csv"), encoding="utf-8") as handle:
                assert "Very Distinctive" not in handle.read()

    def test_respondent_ids_never_appear(self, tmp_path):
        """A respondent id downloads that person's private report. Exporting one
        would put that capability into a shareable spreadsheet."""
        campaign = _seed(respondents=2)
        real_ids = cs.list_respondents(campaign["campaign_id"], "employee")
        assert real_ids

        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        for name in ("respondents", "respondent_categories", "responses_long"):
            with open(os.path.join(out, f"{name}.csv"), encoding="utf-8") as handle:
                content = handle.read()
            for real_id in real_ids:
                assert real_id not in content

    def test_link_tokens_never_appear(self, tmp_path):
        campaign = _seed()
        token = cs.ensure_tokens(campaign["campaign_id"])["employee"]
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        with open(os.path.join(out, "campaigns.csv"), encoding="utf-8") as handle:
            assert token not in handle.read()

    def test_submission_metadata_is_dropped(self, tmp_path):
        """Metadata is excluded wholesale, so a field added there later cannot
        start leaking into published data on its own."""
        _seed()
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        for name in ("respondents", "responses_long"):
            with open(os.path.join(out, f"{name}.csv"), encoding="utf-8") as handle:
                assert "do-not-export" not in handle.read()

    def test_open_campaigns_are_skipped_by_default(self, tmp_path):
        _seed(close=False)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])
        assert _read(out, "respondents") == []

    def test_open_campaigns_included_on_request(self, tmp_path):
        _seed(close=False, respondents=2)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out, "--include-open"])
        assert len(_read(out, "respondents")) == 2

    def test_same_org_keeps_one_pseudonym_across_campaigns(self, tmp_path):
        """Longitudinal comparison depends on this and re-identification must
        not."""
        _seed(org_name="Acme Ltd", respondents=1)
        _seed(org_name="Acme Ltd", respondents=1)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        rows = _read(out, "campaigns")
        assert len(rows) == 2
        assert {r["org_ref"] for r in rows} == {"org_1"}
        assert {r["campaign_ref"] for r in rows} == {"campaign_1", "campaign_2"}

    def test_distinct_orgs_get_distinct_pseudonyms(self, tmp_path):
        _seed(org_name="Acme Ltd", respondents=1)
        _seed(org_name="Globex OU", respondents=1)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])
        assert {r["org_ref"] for r in _read(out, "campaigns")} == {"org_1", "org_2"}

    def test_scores_and_consent_are_carried_through(self, tmp_path):
        _seed(respondents=2)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        row = _read(out, "respondents")[0]
        assert row["consent_version"] == "1.0-draft"
        assert row["consent_recorded_at"]
        assert row["submitted_at"]
        assert float(row["overall_score"]) in (0.0, 100.0)
        assert row["maturity_band"]

    def test_response_rows_carry_the_score_ratio(self, tmp_path):
        _seed(respondents=2)
        out = str(tmp_path / "out")
        export_research_data.main(["--out", out])

        for row in _read(out, "responses_long"):
            assert row["ratio"] in ("0.0", "1.0")
            assert int(row["max_score"]) == 4

    def test_empty_dataset_still_writes_headers(self, tmp_path):
        out = str(tmp_path / "out")
        assert export_research_data.main(["--out", out]) == 0
        with open(os.path.join(out, "respondents.csv"), encoding="utf-8") as handle:
            assert "respondent_ref" in handle.readline()


# ---------------------------------------------------------------------------
# Organization deletion
# ---------------------------------------------------------------------------

class TestDeleteOrgData:
    def test_summary_counts_what_is_there(self):
        _seed(org_name="Acme Ltd", respondents=4)
        report = delete_org_data.summarize("acme-ltd")
        assert report["submissions"] == 4
        assert len(report["campaigns"]) == 1
        assert report["org_names"] == ["Acme Ltd"]

    def test_delete_removes_files_and_registry_entries(self, isolated):
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=3)
        assert (data / "acme-ltd").exists()

        result = delete_org_data.delete("acme-ltd")
        assert result["campaigns"] == 1
        assert not (data / "acme-ltd").exists()
        assert cs.list_campaigns() == []

    def test_delete_leaves_other_organizations_untouched(self, isolated):
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=2)
        _seed(org_name="Globex OU", respondents=2)

        delete_org_data.delete("acme-ltd")
        assert not (data / "acme-ltd").exists()
        assert (data / "globex-ou").exists()
        assert [c["org_slug"] for c in cs.list_campaigns()] == ["globex-ou"]

    def test_delete_kills_the_link_tokens(self):
        """A dead campaign must not leave a working assessment link behind."""
        campaign = _seed(org_name="Acme Ltd", respondents=1)
        token = cs.ensure_tokens(campaign["campaign_id"])["employee"]
        assert cs.resolve_token(token)

        delete_org_data.delete("acme-ltd")
        with pytest.raises(cs.CampaignNotFoundError):
            cs.resolve_token(token)

    @pytest.mark.parametrize("bad", ["..", "../../etc", "acme/../..", "", "C:\\Windows"])
    def test_adversarial_slugs_touch_nothing(self, bad, isolated):
        """The slug is typed by hand into a destructive command."""
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=2)
        delete_org_data.delete(bad)
        assert (data / "acme-ltd").exists()
        assert len(cs.list_campaigns()) == 1

    def test_unknown_org_reports_and_exits_nonzero(self, capsys):
        _seed(org_name="Acme Ltd")
        assert delete_org_data.main(["--org", "does-not-exist", "--yes"]) == 1
        assert "Nothing found" in capsys.readouterr().out

    def test_confirmation_mismatch_deletes_nothing(self, monkeypatch, isolated, capsys):
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=2)
        monkeypatch.setattr("builtins.input", lambda _prompt: "wrong-slug")

        assert delete_org_data.main(["--org", "acme-ltd"]) == 1
        assert "Nothing was deleted" in capsys.readouterr().out
        assert (data / "acme-ltd").exists()

    def test_matching_confirmation_deletes(self, monkeypatch, isolated):
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=2)
        monkeypatch.setattr("builtins.input", lambda _prompt: "acme-ltd")

        assert delete_org_data.main(["--org", "acme-ltd"]) == 0
        assert not (data / "acme-ltd").exists()

    def test_yes_flag_skips_the_prompt(self, isolated):
        data, _ = isolated
        _seed(org_name="Acme Ltd", respondents=1)
        assert delete_org_data.main(["--org", "acme-ltd", "--yes"]) == 0
        assert not (data / "acme-ltd").exists()

    def test_list_mode_names_organizations(self, capsys):
        _seed(org_name="Acme Ltd")
        assert delete_org_data.main(["--list"]) == 0
        assert "acme-ltd" in capsys.readouterr().out
