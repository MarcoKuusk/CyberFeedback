"""Generator tests for the Phase 2 org report AI classes (docs/PHASE2_PLAN.md step 3).

OpenAI is mocked at the module boundary — never called live. The key assertion is
by-construction anonymity: the assembled prompt is built from structured dicts, so
no verbatim employee answer or respondent id can reach it.
"""

import Feedback_Generators.combined_gap_feedback_generator as gap_gen
import Feedback_Generators.org_aggregate_feedback_generator as agg_gen
from utils.report_analysis import aggregate_assessment, analyze_assessment, compare_tracks

from org_fixtures import (
    CONTROL_SCORES,
    _employee_submissions,
    _org_submission,
)

CANNED = "# Report\n## Executive Summary\nAll clear.\n## Recommended Focus\n- Do the thing.\n"


def _capture(monkeypatch, module):
    """Patch a generator module's OpenAI boundary and capture the assembled prompt."""
    captured = {}

    def fake_generate(api_key, prompt):
        captured["api_key"] = api_key
        captured["prompt"] = prompt
        return CANNED

    monkeypatch.setattr(module, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(module, "generate_report_text", fake_generate)
    return captured


# --------------------------------------------------------------------------- #
# OrgAggregateFeedbackGenerator
# --------------------------------------------------------------------------- #
def test_org_aggregate_generator_calls_boundary(monkeypatch):
    captured = _capture(monkeypatch, agg_gen)
    aggregate = aggregate_assessment(_employee_submissions(5))
    text = agg_gen.OrgAggregateFeedbackGenerator(aggregate).generate_feedback()
    assert text == CANNED
    assert "prompt" in captured


def test_org_aggregate_prompt_has_no_verbatim_answers(monkeypatch):
    captured = _capture(monkeypatch, agg_gen)
    marker = "SECRET-PII-xyz789"
    aggregate = aggregate_assessment(_employee_submissions(5, marker=marker))
    agg_gen.OrgAggregateFeedbackGenerator(aggregate).generate_feedback()
    prompt = captured["prompt"]
    assert marker not in prompt
    assert "chosen" not in prompt
    # Team-level framing only: shares and means, no respondent identifiers.
    assert "respondents" in prompt.lower()


# --------------------------------------------------------------------------- #
# CombinedGapFeedbackGenerator
# --------------------------------------------------------------------------- #
def _comparison(n=5):
    aggregate = aggregate_assessment(_employee_submissions(n))
    org_summary = analyze_assessment(_org_submission(CONTROL_SCORES), report_type="organization")
    return compare_tracks(aggregate, org_summary)


def test_combined_gap_generator_calls_boundary(monkeypatch):
    captured = _capture(monkeypatch, gap_gen)
    text = gap_gen.CombinedGapFeedbackGenerator(_comparison()).generate_feedback()
    assert text == CANNED
    assert "prompt" in captured


def test_combined_gap_prompt_has_no_verbatim_answers(monkeypatch):
    captured = _capture(monkeypatch, gap_gen)
    gap_gen.CombinedGapFeedbackGenerator(_comparison()).generate_feedback()
    prompt = captured["prompt"]
    assert "chosen" not in prompt
    assert "Question for" not in prompt
    # The comparison surfaces mapped control categories, not individual answers.
    assert "Identity & Access Management" in prompt


def test_combined_gap_prompt_degraded_when_suppressed(monkeypatch):
    captured = _capture(monkeypatch, gap_gen)
    # Below the anonymity floor -> degraded comparison, still narratable.
    gap_gen.CombinedGapFeedbackGenerator(_comparison(n=3)).generate_feedback()
    prompt = captured["prompt"]
    assert "withheld" in prompt.lower()
    # Control-only areas are still described honestly.
    assert "Third-Party Risk" in prompt
