"""Preflight checks for the production entry point.

These guard the configuration mistakes that would otherwise be discovered
during an engagement: an unusable admin UI, links staff cannot open, or reports
that fail the moment someone asks for one.
"""

import pytest

import serve


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CYBERFEEDBACK_ADMIN_TOKEN",
        "CYBERFEEDBACK_VIEWER_TOKEN",
        "CYBERFEEDBACK_PUBLIC_URL",
        "CYBERFEEDBACK_HOST",
        "CYBERFEEDBACK_PORT",
        "CYBERFEEDBACK_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)


def _configured(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "op")
    monkeypatch.setenv("CYBERFEEDBACK_PUBLIC_URL", "https://assess.example.com")


class TestPreflight:
    def test_missing_api_key_blocks_startup(self, monkeypatch):
        assert any("OPENAI_API_KEY" in p for p in serve.preflight("127.0.0.1"))

    def test_loopback_needs_only_the_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert serve.preflight("127.0.0.1") == []

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
    def test_loopback_hosts_are_not_treated_as_exposed(self, monkeypatch, host):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert serve.preflight(host) == []

    def test_exposed_bind_requires_an_admin_token(self, monkeypatch):
        """Without it the admin gate falls back to loopback-only, locking the
        operator out of their own deployment."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("CYBERFEEDBACK_PUBLIC_URL", "https://assess.example.com")
        assert any("CYBERFEEDBACK_ADMIN_TOKEN" in p for p in serve.preflight("0.0.0.0"))

    def test_exposed_bind_requires_a_public_url(self, monkeypatch):
        """Behind a proxy, request-derived links are usually wrong, and a wrong
        link is indistinguishable from a broken product to the recipient."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("CYBERFEEDBACK_ADMIN_TOKEN", "op")
        assert any("CYBERFEEDBACK_PUBLIC_URL" in p for p in serve.preflight("0.0.0.0"))

    def test_fully_configured_exposed_bind_passes(self, monkeypatch):
        _configured(monkeypatch)
        assert serve.preflight("0.0.0.0") == []


class TestWarnings:
    def test_plaintext_public_url_warns(self, monkeypatch):
        _configured(monkeypatch)
        monkeypatch.setenv("CYBERFEEDBACK_PUBLIC_URL", "http://assess.example.com")
        assert any("clear text" in note for note in serve.warnings_for("0.0.0.0"))

    def test_https_public_url_does_not_warn_about_transport(self, monkeypatch):
        _configured(monkeypatch)
        assert not any("clear text" in note for note in serve.warnings_for("0.0.0.0"))

    def test_no_viewer_token_is_not_worth_mentioning(self, monkeypatch):
        """Leadership credentials are per-campaign now, so its absence from the
        environment is the normal, correct state."""
        _configured(monkeypatch)
        assert serve.preflight("0.0.0.0") == []
        assert not any("VIEWER_TOKEN" in note for note in serve.warnings_for("0.0.0.0"))

    def test_stale_viewer_token_is_flagged(self, monkeypatch):
        """It grants nothing now; left set, someone will assume it does."""
        _configured(monkeypatch)
        monkeypatch.setenv("CYBERFEEDBACK_VIEWER_TOKEN", "leftover")
        assert any("no longer used" in note for note in serve.warnings_for("0.0.0.0"))


class TestArgs:
    def test_defaults_are_safe(self):
        args = serve._parse_args([])
        assert args.host == "127.0.0.1"
        assert args.port == 8080

    def test_cli_overrides_environment(self, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_PORT", "9999")
        assert serve._parse_args(["--port", "7000"]).port == 7000

    def test_environment_supplies_defaults(self, monkeypatch):
        monkeypatch.setenv("CYBERFEEDBACK_HOST", "0.0.0.0")
        monkeypatch.setenv("CYBERFEEDBACK_THREADS", "32")
        args = serve._parse_args([])
        assert args.host == "0.0.0.0"
        assert args.threads == 32

    @pytest.mark.parametrize("bad", ["nonsense", "-4", "0", ""])
    def test_invalid_env_numbers_fall_back(self, monkeypatch, bad):
        monkeypatch.setenv("CYBERFEEDBACK_THREADS", bad)
        assert serve._parse_args([]).threads == serve.DEFAULT_THREADS

    def test_main_refuses_to_start_when_misconfigured(self, capsys):
        assert serve.main(["--host", "0.0.0.0"]) == 1
        assert "Refusing to start" in capsys.readouterr().err
