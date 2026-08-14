"""Tests for the campaign-scoped storage layer.

Real files in a tmp directory throughout — no mocked I/O, per CLAUDE.md. The
adversarial path battery is the reason this module exists as a separate unit.
"""

import json
import os

import pytest

import campaign_store as cs


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect storage at real tmp directories for every test."""
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    data.mkdir()
    reports.mkdir()
    monkeypatch.setattr(cs, "DATA_DIR", str(data))
    monkeypatch.setattr(cs, "REPORT_DIR", str(reports))
    return data, reports


def _payload(answer_score=3):
    return {
        "responses": [
            {
                "question": "Do you use MFA?",
                "category": "Password & Access Management",
                "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
                "selectedAnswer": {"option": "Yes", "score": answer_score},
            }
        ],
        "metadata": {"report_type": "employee", "generated_from": "web-interface"},
        "consent": {"agreed": True, "version": "1.0"},
    }


def _campaign(tracks=("employee", "organization"), locale="en", name="Acme Ltd"):
    return cs.create_campaign(name, list(tracks), locale=locale)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Acme Ltd", "acme-ltd"),
            ("  Spaced  Out  ", "spaced-out"),
            ("Foo & Bar, Inc.", "foo-bar-inc"),
            ("UPPER CASE", "upper-case"),
            ("---leading-trailing---", "leading-trailing"),
            ("a/b\\c", "a-b-c"),
            ("../../etc/passwd", "etc-passwd"),
        ],
    )
    def test_produces_safe_slugs(self, name, expected):
        assert cs.slugify(name) == expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Küberturve OÜ", "kuberturve-ou"),
            ("Tõõtajate Ühing", "tootajate-uhing"),
            ("Šokolaad Žurnaal", "sokolaad-zurnaal"),
            ("Käru Möbel", "karu-mobel"),
        ],
    )
    def test_transliterates_estonian_names(self, name, expected):
        """Estonian org names must not produce empty or non-ASCII directory names."""
        assert cs.slugify(name) == expected

    def test_unrepresentable_names_still_yield_a_valid_slug(self):
        assert cs.slugify("日本語") == "org"
        assert cs.slugify("!!!") == "org"

    def test_slug_is_length_capped_and_pattern_valid(self):
        slug = cs.slugify("x" * 200)
        assert len(slug) <= 63
        assert cs._SLUG_PATTERN.match(slug)

    def test_every_slug_satisfies_the_validator(self):
        for name in ["Acme Ltd", "Küberturve OÜ", "!!!", "a", "-a-", "x" * 200, "日本語"]:
            cs._validate_slug(cs.slugify(name))

    def test_rejects_non_string(self):
        with pytest.raises(cs.InvalidInputError):
            cs.slugify(None)


# ---------------------------------------------------------------------------
# _safe_join — the containment guard
# ---------------------------------------------------------------------------

class TestSafeJoin:
    TRAVERSALS = [
        "..",
        "../",
        "../..",
        "../../etc",
        "../../etc/passwd",
        "..\\..\\Windows",
        "foo/../../bar",
        "./../..",
    ]

    @pytest.mark.parametrize("part", TRAVERSALS)
    def test_rejects_traversal(self, part, tmp_path):
        with pytest.raises(cs.InvalidInputError):
            cs._safe_join(str(tmp_path), part)

    @pytest.mark.parametrize("part", ["C:\\Windows\\System32", "/etc/passwd", "\\\\server\\share", "C:relative"])
    def test_rejects_absolute_and_drive_qualified(self, part, tmp_path):
        with pytest.raises(cs.InvalidInputError):
            cs._safe_join(str(tmp_path), part)

    @pytest.mark.parametrize("part", ["", None, 5, b"bytes", "with\x00null"])
    def test_rejects_empty_wrong_type_and_null_bytes(self, part, tmp_path):
        with pytest.raises(cs.InvalidInputError):
            cs._safe_join(str(tmp_path), part)

    def test_rejects_traversal_hidden_in_a_later_segment(self, tmp_path):
        with pytest.raises(cs.InvalidInputError):
            cs._safe_join(str(tmp_path), "ok", "..", "..", "escaped")

    def test_allows_legitimate_nesting(self, tmp_path):
        result = cs._safe_join(str(tmp_path), "acme", "a" * 32, "employee", "b.json")
        assert result.startswith(os.path.realpath(str(tmp_path)) + os.sep)
        assert result.endswith(os.path.join("acme", "a" * 32, "employee", "b.json"))

    def test_url_encoded_traversal_is_not_decoded_into_an_escape(self, tmp_path):
        """%2e%2e is a literal directory name here, not a traversal — must stay contained."""
        result = cs._safe_join(str(tmp_path), "%2e%2e", "%2f")
        assert result.startswith(os.path.realpath(str(tmp_path)) + os.sep)


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------

class TestIdValidation:
    BAD_IDS = [
        "",
        None,
        123,
        "../../etc/passwd",
        "..",
        "/etc/passwd",
        "C:\\Windows",
        "%2e%2e%2f",
        "0" * 31,               # too short
        "0" * 33,               # too long
        "0" * 32 + "/x",        # right length prefix, trailing path
        "A" * 32,               # uppercase hex rejected — canonical form only
        "g" * 32,               # non-hex
        "0123456789abcdef0123456789abcde ",  # trailing space
        "0123456789abcdef0123456789abcd\n",
    ]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_rejects_malformed_ids(self, bad):
        with pytest.raises(cs.InvalidInputError):
            cs._validate_id(bad, "campaign id")

    def test_accepts_canonical_uuid4_hex(self):
        from uuid import uuid4

        value = uuid4().hex
        assert cs._validate_id(value, "campaign id") == value

    @pytest.mark.parametrize("bad", ["admin", "../employee", "employee/..", "", None, "EMPLOYEE", "employee "])
    def test_rejects_non_allowlisted_tracks(self, bad):
        with pytest.raises(cs.InvalidInputError):
            cs._validate_track(bad)

    def test_accepts_allowlisted_tracks(self):
        for track in cs.ALLOWED_TRACKS:
            assert cs._validate_track(track) == track

    @pytest.mark.parametrize("bad", ["fr", "EN", "", None, "en-US"])
    def test_rejects_unknown_locales(self, bad):
        with pytest.raises(cs.InvalidInputError):
            cs._validate_locale(bad)


# ---------------------------------------------------------------------------
# Campaign registry
# ---------------------------------------------------------------------------

class TestCampaignRegistry:
    def test_create_returns_valid_campaign(self):
        campaign = _campaign(name="Acme Ltd", tracks=("employee",), locale="et")
        assert cs._ID_PATTERN.match(campaign["campaign_id"])
        assert campaign["org_slug"] == "acme-ltd"
        assert campaign["org_name"] == "Acme Ltd"
        assert campaign["tracks"] == ["employee"]
        assert campaign["locale"] == "et"
        assert campaign["status"] == "open"
        assert campaign["created_at"].endswith("Z")

    def test_get_round_trips(self):
        created = _campaign()
        assert cs.get_campaign(created["campaign_id"]) == created

    def test_get_unknown_returns_none(self):
        assert cs.get_campaign("0" * 32) is None

    def test_get_validates_id_before_lookup(self):
        with pytest.raises(cs.InvalidInputError):
            cs.get_campaign("../../etc")

    def test_list_returns_all_campaigns(self):
        a = _campaign(name="Acme")
        b = _campaign(name="Beta")
        ids = {c["campaign_id"] for c in cs.list_campaigns()}
        assert ids == {a["campaign_id"], b["campaign_id"]}

    def test_registry_is_valid_json_on_disk(self, isolated_dirs):
        data, _ = isolated_dirs
        campaign = _campaign()
        registry = json.loads((data / cs.REGISTRY_FILENAME).read_text(encoding="utf-8"))
        assert campaign["campaign_id"] in registry["campaigns"]

    def test_second_create_preserves_the_first(self):
        """Guards the registry write against the overwrite bug this module replaces."""
        first = _campaign(name="Acme")
        second = _campaign(name="Beta")
        assert cs.get_campaign(first["campaign_id"]) is not None
        assert cs.get_campaign(second["campaign_id"]) is not None

    def test_no_temp_files_left_behind(self, isolated_dirs):
        data, _ = isolated_dirs
        _campaign()
        assert [p.name for p in data.iterdir()] == [cs.REGISTRY_FILENAME]

    def test_duplicate_tracks_are_collapsed(self):
        campaign = cs.create_campaign("Acme", ["employee", "employee", "organization"])
        assert campaign["tracks"] == ["employee", "organization"]

    @pytest.mark.parametrize("tracks", [[], ["admin"], ["employee", "admin"], "employee", None])
    def test_rejects_bad_track_lists(self, tracks):
        with pytest.raises(cs.InvalidInputError):
            cs.create_campaign("Acme", tracks)

    @pytest.mark.parametrize("name", ["", "   ", None, 5])
    def test_rejects_bad_org_names(self, name):
        with pytest.raises(cs.InvalidInputError):
            cs.create_campaign(name, ["employee"])

    def test_malformed_registry_is_reported_not_ignored(self, isolated_dirs):
        data, _ = isolated_dirs
        (data / cs.REGISTRY_FILENAME).write_text('["not", "a", "dict"]', encoding="utf-8")
        with pytest.raises(cs.InvalidInputError):
            cs.list_campaigns()

    def test_status_can_be_closed_and_reopened(self):
        campaign = _campaign()
        assert cs.set_campaign_status(campaign["campaign_id"], "closed")["status"] == "closed"
        assert cs.set_campaign_status(campaign["campaign_id"], "open")["status"] == "open"

    def test_status_rejects_unknown_value(self):
        campaign = _campaign()
        with pytest.raises(cs.InvalidInputError):
            cs.set_campaign_status(campaign["campaign_id"], "deleted")

    def test_status_on_unknown_campaign_raises_not_found(self):
        with pytest.raises(cs.CampaignNotFoundError):
            cs.set_campaign_status("0" * 32, "closed")


# ---------------------------------------------------------------------------
# Submissions — the no-overwrite guarantee
# ---------------------------------------------------------------------------

class TestSubmissions:
    def test_save_returns_a_valid_respondent_id(self):
        campaign = _campaign()
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        assert cs._ID_PATTERN.match(respondent_id)

    def test_thirty_submissions_produce_thirty_distinct_records(self, isolated_dirs):
        """M1's core exit criterion: the data-loss bug cannot recur."""
        data, _ = isolated_dirs
        campaign = _campaign()
        ids = [
            cs.save_submission(campaign["campaign_id"], "employee", _payload(answer_score=i % 5))
            for i in range(30)
        ]
        assert len(set(ids)) == 30

        directory = data / campaign["org_slug"] / campaign["campaign_id"] / "employee"
        assert len(list(directory.glob("*.json"))) == 30

        # Every record loads back with its own distinct answer.
        for index, respondent_id in enumerate(ids):
            responses, _ = cs.load_submission(campaign["campaign_id"], "employee", respondent_id)
            assert responses[0]["selectedAnswer"]["score"] == index % 5

    def test_round_trip_preserves_responses_and_metadata(self):
        campaign = _campaign()
        payload = _payload()
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", payload)
        responses, metadata = cs.load_submission(campaign["campaign_id"], "employee", respondent_id)
        assert responses == payload["responses"]
        assert metadata == payload["metadata"]

    def test_record_carries_the_amendment_fields(self):
        """locale, consent and submitted_at — retrofitting these later would touch every record."""
        campaign = _campaign(locale="et")
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        record = cs.load_record(campaign["campaign_id"], "employee", respondent_id)
        assert record["locale"] == "et"
        assert record["submitted_at"].endswith("Z")
        assert record["consent"]["agreed"] is True
        assert record["consent"]["version"] == "1.0"
        assert record["consent"]["recorded_at"].endswith("Z")
        assert record["respondent_id"] == respondent_id
        assert record["campaign_id"] == campaign["campaign_id"]
        assert record["track"] == "employee"

    def test_consent_timestamp_comes_from_the_server_not_the_client(self):
        campaign = _campaign()
        payload = _payload()
        payload["consent"]["recorded_at"] = "1999-01-01T00:00:00Z"
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", payload)
        record = cs.load_record(campaign["campaign_id"], "employee", respondent_id)
        assert record["consent"]["recorded_at"] != "1999-01-01T00:00:00Z"

    def test_estonian_responses_survive_the_round_trip(self):
        """The ET questionnaire's text must not be mangled by the storage layer."""
        campaign = _campaign(locale="et")
        payload = _payload()
        payload["responses"][0]["question"] = "Kas nõuate mitmeastmelist autentimist kõigis süsteemides?"
        payload["responses"][0]["selectedAnswer"] = {"option": "Mõnedele töötajatele", "score": 2}
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", payload)
        responses, _ = cs.load_submission(campaign["campaign_id"], "employee", respondent_id)
        assert responses[0]["question"] == "Kas nõuate mitmeastmelist autentimist kõigis süsteemides?"
        assert responses[0]["selectedAnswer"]["option"] == "Mõnedele töötajatele"

    def test_tracks_are_stored_separately(self, isolated_dirs):
        data, _ = isolated_dirs
        campaign = _campaign()
        emp = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        org = cs.save_submission(campaign["campaign_id"], "organization", _payload())
        base = data / campaign["org_slug"] / campaign["campaign_id"]
        assert (base / "employee" / f"{emp}.json").exists()
        assert (base / "organization" / f"{org}.json").exists()

    def test_submission_to_a_disabled_track_is_rejected(self):
        campaign = _campaign(tracks=("employee",))
        with pytest.raises(cs.CampaignNotFoundError):
            cs.save_submission(campaign["campaign_id"], "organization", _payload())

    def test_submission_to_a_closed_campaign_is_rejected(self):
        campaign = _campaign()
        cs.set_campaign_status(campaign["campaign_id"], "closed")
        with pytest.raises(cs.InvalidInputError):
            cs.save_submission(campaign["campaign_id"], "employee", _payload())

    def test_submission_to_unknown_campaign_is_rejected(self):
        with pytest.raises(cs.CampaignNotFoundError):
            cs.save_submission("0" * 32, "employee", _payload())

    @pytest.mark.parametrize(
        "consent",
        [
            None,
            {},
            {"agreed": False, "version": "1.0"},
            {"agreed": "true", "version": "1.0"},   # string, not boolean
            {"agreed": 1, "version": "1.0"},        # truthy but not True
            {"agreed": True},                       # missing version
            {"agreed": True, "version": ""},
            {"agreed": True, "version": "   "},
            {"agreed": True, "version": 1.0},
            "yes",
        ],
    )
    def test_submission_without_valid_consent_never_reaches_disk(self, consent, isolated_dirs):
        data, _ = isolated_dirs
        campaign = _campaign()
        payload = _payload()
        payload["consent"] = consent
        with pytest.raises(cs.InvalidInputError):
            cs.save_submission(campaign["campaign_id"], "employee", payload)
        track_dir = data / campaign["org_slug"] / campaign["campaign_id"] / "employee"
        assert not list(track_dir.glob("*.json")) if track_dir.exists() else True

    @pytest.mark.parametrize(
        "payload",
        [None, "string", {}, {"responses": []}, {"responses": "not-a-list"}],
    )
    def test_rejects_malformed_payloads(self, payload):
        campaign = _campaign()
        with pytest.raises(cs.InvalidInputError):
            cs.save_submission(campaign["campaign_id"], "employee", payload)

    def test_rejects_non_object_metadata(self):
        campaign = _campaign()
        payload = _payload()
        payload["metadata"] = "not-an-object"
        with pytest.raises(cs.InvalidInputError):
            cs.save_submission(campaign["campaign_id"], "employee", payload)


# ---------------------------------------------------------------------------
# Retrieval — adversarial inputs
# ---------------------------------------------------------------------------

class TestRetrieval:
    @pytest.mark.parametrize("bad", TestIdValidation.BAD_IDS)
    def test_load_rejects_adversarial_respondent_ids(self, bad):
        campaign = _campaign()
        cs.save_submission(campaign["campaign_id"], "employee", _payload())
        with pytest.raises((cs.InvalidInputError, cs.CampaignNotFoundError)):
            cs.load_submission(campaign["campaign_id"], "employee", bad)

    @pytest.mark.parametrize("bad", TestIdValidation.BAD_IDS)
    def test_load_rejects_adversarial_campaign_ids(self, bad):
        with pytest.raises((cs.InvalidInputError, cs.CampaignNotFoundError)):
            cs.load_submission(bad, "employee", "0" * 32)

    @pytest.mark.parametrize("bad", ["admin", "../employee", "employee/..", "", None])
    def test_load_rejects_adversarial_tracks(self, bad):
        campaign = _campaign()
        with pytest.raises((cs.InvalidInputError, cs.CampaignNotFoundError)):
            cs.load_submission(campaign["campaign_id"], bad, "0" * 32)

    def test_load_cannot_read_a_file_outside_its_track(self, isolated_dirs):
        """A respondent id valid for one track must not resolve in another."""
        campaign = _campaign()
        emp = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        with pytest.raises(cs.CampaignNotFoundError):
            cs.load_submission(campaign["campaign_id"], "organization", emp)

    def test_load_cannot_read_across_campaigns(self):
        a = _campaign(name="Acme")
        b = _campaign(name="Beta")
        respondent_id = cs.save_submission(a["campaign_id"], "employee", _payload())
        with pytest.raises(cs.CampaignNotFoundError):
            cs.load_submission(b["campaign_id"], "employee", respondent_id)

    def test_load_unknown_respondent_raises_not_found(self):
        campaign = _campaign()
        with pytest.raises(cs.CampaignNotFoundError):
            cs.load_submission(campaign["campaign_id"], "employee", "0" * 32)

    def test_list_respondents_returns_saved_ids(self):
        campaign = _campaign()
        ids = {cs.save_submission(campaign["campaign_id"], "employee", _payload()) for _ in range(3)}
        assert set(cs.list_respondents(campaign["campaign_id"], "employee")) == ids

    def test_list_respondents_empty_before_any_submission(self):
        campaign = _campaign()
        assert cs.list_respondents(campaign["campaign_id"], "employee") == []

    def test_list_respondents_ignores_foreign_files(self, isolated_dirs):
        data, _ = isolated_dirs
        campaign = _campaign()
        good = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        directory = data / campaign["org_slug"] / campaign["campaign_id"] / "employee"
        (directory / "notes.txt").write_text("x", encoding="utf-8")
        (directory / "not-a-uuid.json").write_text("{}", encoding="utf-8")
        assert cs.list_respondents(campaign["campaign_id"], "employee") == [good]


# ---------------------------------------------------------------------------
# Report paths
# ---------------------------------------------------------------------------

class TestReportPath:
    def test_lands_inside_the_report_directory(self, isolated_dirs):
        _, reports = isolated_dirs
        campaign = _campaign()
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        path = cs.report_path(campaign["campaign_id"], "employee", respondent_id)
        assert path.startswith(os.path.realpath(str(reports)) + os.sep)
        assert path.endswith(f"{respondent_id}.pdf")

    def test_never_lands_in_the_data_directory(self, isolated_dirs):
        data, _ = isolated_dirs
        campaign = _campaign()
        respondent_id = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        path = cs.report_path(campaign["campaign_id"], "employee", respondent_id)
        assert not path.startswith(os.path.realpath(str(data)) + os.sep)

    def test_distinct_respondents_get_distinct_paths(self):
        """The fixed-filename bug that could serve A's PDF to B cannot recur."""
        campaign = _campaign()
        a = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        b = cs.save_submission(campaign["campaign_id"], "employee", _payload())
        assert cs.report_path(campaign["campaign_id"], "employee", a) != cs.report_path(
            campaign["campaign_id"], "employee", b
        )

    def test_tracks_get_distinct_paths(self):
        campaign = _campaign()
        respondent_id = "0" * 32
        assert cs.report_path(campaign["campaign_id"], "employee", respondent_id) != cs.report_path(
            campaign["campaign_id"], "organization", respondent_id
        )

    @pytest.mark.parametrize("bad", TestIdValidation.BAD_IDS)
    def test_rejects_adversarial_respondent_ids(self, bad):
        campaign = _campaign()
        with pytest.raises((cs.InvalidInputError, cs.CampaignNotFoundError)):
            cs.report_path(campaign["campaign_id"], "employee", bad)
