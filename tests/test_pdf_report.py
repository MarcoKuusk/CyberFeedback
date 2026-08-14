"""PDF rendering tests.

These exist because `_build_styles()` raised KeyError on every call — ReportLab's
getSampleStyleSheet() already defines a style named "Bullet" — so no report could
ever be produced, and a broad `except Exception` in the request handler turned
that into a generic "Report generation failed" message. Nothing caught it.
"""

import main
import pytest
from utils.report_analysis import analyze_assessment

AI_TEXT = """# Employee Cyber Hygiene Report
## Executive Summary
Password practice is the weakest area, but device habits are strong.
## What You Are Doing Well
- You lock your device consistently.
## Priority Risks
- Reused passwords put several accounts at once at risk.
## 30-60-90 Day Action Roadmap
### Next 30 Days
- Install a password manager.
## Category Breakdown
Access management trails the other categories.
## Appendix: Response Highlights
- Reported reusing passwords across accounts.
"""

# Every style name `save_feedback_to_pdf` looks up. A rename that misses one
# would raise at build time, exactly like the "Bullet" collision did.
REQUIRED_STYLES = ("ReportTitle", "SectionHeading", "SubHeading", "Body", "Muted", "ReportBullet", "MetricValue")


def _assessment(question="Do you use unique passwords?", option="No", score=0):
    return [
        {
            "question": question,
            "category": "Password & Access Management",
            "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
            "selectedAnswer": {"option": option, "score": score},
        },
        {
            "question": "Do you lock your device?",
            "category": "Device & Data Security",
            "answers": [{"option": "No", "score": 0}, {"option": "Yes", "score": 4}],
            "selectedAnswer": {"option": "Yes", "score": 4},
        },
    ]


class TestStyles:
    def test_build_styles_does_not_raise(self):
        """The regression guard for the duplicate-style-name bug."""
        assert main._build_styles() is not None

    def test_build_styles_is_callable_twice(self):
        main._build_styles()
        main._build_styles()

    @pytest.mark.parametrize("name", REQUIRED_STYLES)
    def test_every_referenced_style_is_defined(self, name):
        assert name in main._build_styles().byName

    def test_does_not_collide_with_reportlab_builtins(self):
        from reportlab.lib.styles import getSampleStyleSheet

        builtins = set(getSampleStyleSheet().byName)
        assert not (set(REQUIRED_STYLES) & builtins)


class TestPdfOutput:
    def test_writes_a_valid_pdf(self, tmp_path):
        summary = analyze_assessment(_assessment(), report_type="employee")
        out = tmp_path / "report.pdf"
        main.save_feedback_to_pdf(AI_TEXT, summary, "Employee Cyber Hygiene Report", str(out))
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_contains_the_expected_sections(self, tmp_path):
        fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
        summary = analyze_assessment(_assessment(), report_type="employee")
        out = tmp_path / "report.pdf"
        main.save_feedback_to_pdf(AI_TEXT, summary, "Employee Cyber Hygiene Report", str(out))

        document = fitz.open(str(out))
        text = "\n".join(page.get_text() for page in document)
        for heading in ("Executive Summary", "Top Priorities", "Priority Risks", "Category Breakdown"):
            assert heading in text
        assert "50.0%" in text  # 4 of 8 points earned

    def test_estonian_text_renders(self, tmp_path):
        """Base-14 fonts cover Estonian diacritics; this pins that they survive."""
        fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
        estonian = "Kas nõuate mitmeastmelist autentimist kõigis süsteemides?"
        summary = analyze_assessment(
            _assessment(question=estonian, option="Mõnedele töötajatele", score=2), report_type="organization"
        )
        out = tmp_path / "et.pdf"
        # The diacritics must travel through the AI-text path, which is what the
        # PDF body actually renders — question text stays in the summary tables.
        main.save_feedback_to_pdf(
            "# Aruanne\n## Executive Summary\nKüberhügieen vajab tähelepanu: kõik töötajad, šokk ja žanr.\n",
            summary,
            "Organisatsiooni aruanne",
            str(out),
        )
        document = fitz.open(str(out))
        text = "\n".join(page.get_text() for page in document)
        assert "Küberhügieen" in text
        for character in "õäöüšž":
            assert character in text, f"{character!r} did not survive PDF rendering"


class TestUntrustedAiOutput:
    """AI output is untrusted text and must be escaped before rendering."""

    def test_markup_in_ai_output_is_escaped(self):
        cleaned = main._clean_inline_markup("<script>alert('x')</script>")
        assert "<script>" not in cleaned
        assert "&lt;script&gt;" in cleaned

    def test_ampersands_are_escaped(self):
        assert main._clean_inline_markup("Tom & Jerry") == "Tom &amp; Jerry"

    def test_bold_markdown_is_converted_not_escaped(self):
        assert main._clean_inline_markup("**important**") == "<b>important</b>"

    def test_injected_tags_inside_bold_are_still_escaped(self):
        cleaned = main._clean_inline_markup("**<img src=x onerror=1>**")
        assert cleaned.startswith("<b>") and cleaned.endswith("</b>")
        assert "&lt;img" in cleaned

    def test_pdf_builds_even_when_ai_returns_no_headings(self, tmp_path):
        """A model that ignores the heading contract must not break generation."""
        summary = analyze_assessment(_assessment(), report_type="employee")
        out = tmp_path / "plain.pdf"
        main.save_feedback_to_pdf("Just a paragraph with no headings at all.", summary, "Report", str(out))
        assert out.read_bytes()[:4] == b"%PDF"
