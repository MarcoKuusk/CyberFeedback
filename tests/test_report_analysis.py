"""Unit tests for the Phase 2 analysis layer (docs/PHASE2_PLAN.md steps 1-2).

Pure functions — no I/O, no OpenAI. Covers aggregate math, the min-N anonymity
floor, gap-prevalence as a *share* (not a mean), the control->behavior mapping,
and adversarial/edge inputs. The category-mapping tables are also checked against
the real questionnaire files so a questionnaire edit can't silently break the map.
"""

import json
import os

from utils.report_analysis import (
    CONTROL_ONLY,
    CONTROL_TO_BEHAVIOR,
    MIN_AGGREGATE_N,
    aggregate_assessment,
    analyze_assessment,
    compare_tracks,
)

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# Employee behavior categories, in a fixed order so tie-breaking is deterministic.
EMP_CATEGORIES = [
    "Phishing Awareness & Email Security",
    "Password & Access Management",
    "Device & Data Security",
    "Remote Work & Public Network Security",
    "Incident Reporting & Cybersecurity Culture",
]

# Per-category selected scores (out of a max of 4) for 5 synthetic respondents.
# Chosen so every rolled-up figure below is exact.
EMP_SCORES = {
    "Phishing Awareness & Email Security": [0, 0, 2, 4, 4],
    "Password & Access Management": [4, 4, 4, 4, 0],
    "Device & Data Security": [2, 2, 2, 2, 2],
    "Remote Work & Public Network Security": [3, 3, 3, 3, 3],
    "Incident Reporting & Cybersecurity Culture": [4, 4, 4, 0, 0],
}


def _make_submission(scores_by_category, max_score=4, marker=""):
    """One respondent's raw `responses` list with a controllable score per category.

    `marker` is embedded only in user-answer-shaped fields (never in feedback.action)
    so anonymity tests can assert it does not leak into any aggregate.
    """
    responses = []
    for category in EMP_CATEGORIES:
        if category not in scores_by_category:
            continue
        selected = scores_by_category[category]
        responses.append(
            {
                "question": f"Question for {category} {marker}".strip(),
                "category": category,
                "answers": [{"option": "low", "score": 0}, {"option": "high", "score": max_score}],
                "selectedAnswer": {"option": f"chosen {marker}".strip(), "score": selected},
                "feedback": {"action": f"Do for {category}"},
            }
        )
    return responses


def _employee_submissions(n=5, marker=""):
    return [
        _make_submission({cat: EMP_SCORES[cat][i] for cat in EMP_CATEGORIES}, marker=marker)
        for i in range(n)
    ]


def _org_submission(control_scores, max_score=4):
    responses = []
    for category, selected in control_scores.items():
        responses.append(
            {
                "question": f"Org question for {category}",
                "category": category,
                "answers": [{"option": "low", "score": 0}, {"option": "high", "score": max_score}],
                "selectedAnswer": {"option": "chosen", "score": selected},
                "feedback": {"action": f"Improve {category}"},
            }
        )
    return responses


CONTROL_SCORES = {
    "Identity & Access Management": 4,               # 100% -> Password (80) -> gap +20
    "Security Awareness & Training": 4,              # 100% -> Phishing (50) -> gap +50
    "Remote Work Security": 2,                       # 50%  -> Remote (75)  -> gap -25
    "Incident Response & Business Continuity": 4,    # 100% -> Incident (60) -> gap +40
    "Network & Endpoint Security": 4,               # 100% -> Device (50)  -> gap +50
    "Data Classification & Protection": 3,          # 75%  -> Device (50)  -> gap +25
    "Backup & Recovery": 2,                          # control-only
    "Software & Patch Management": 4,                # control-only
    "Compliance & Regulatory Alignment": 3,          # control-only
    "Physical Security": 2,                          # control-only
    "Third-Party Risk": 0,                           # control-only
}


# --------------------------------------------------------------------------- #
# aggregate_assessment — math
# --------------------------------------------------------------------------- #
def test_aggregate_mean_overall_score():
    agg = aggregate_assessment(_employee_submissions(5), report_type="employee")
    assert agg["suppressed"] is False
    assert agg["respondent_count"] == 5
    assert agg["mean_overall_score"] == 63.0
    assert agg["maturity_label"] == "Moderate"


def test_aggregate_category_means():
    agg = aggregate_assessment(_employee_submissions(5))
    assert agg["category_means"] == {
        "Phishing Awareness & Email Security": 50.0,
        "Password & Access Management": 80.0,
        "Device & Data Security": 50.0,
        "Remote Work & Public Network Security": 75.0,
        "Incident Reporting & Cybersecurity Culture": 60.0,
    }


def test_aggregate_band_distribution():
    agg = aggregate_assessment(_employee_submissions(5))
    assert agg["band_distribution"] == {"Strong": 0, "Moderate": 4, "Needs Attention": 1}


def test_aggregate_gap_prevalence_is_a_share():
    agg = aggregate_assessment(_employee_submissions(5))
    # Share of respondents scoring "Needs Attention" per category — not a mean.
    assert agg["gap_prevalence"] == {
        "Phishing Awareness & Email Security": 0.6,
        "Password & Access Management": 0.2,
        "Device & Data Security": 1.0,
        "Remote Work & Public Network Security": 0.0,
        "Incident Reporting & Cybersecurity Culture": 0.4,
    }


def test_aggregate_top_team_gaps_are_lowest_means():
    agg = aggregate_assessment(_employee_submissions(5))
    gaps = {item["category"]: item["score"] for item in agg["top_team_gaps"]}
    assert set(gaps) == {
        "Phishing Awareness & Email Security",
        "Device & Data Security",
        "Incident Reporting & Cybersecurity Culture",
    }
    assert gaps["Phishing Awareness & Email Security"] == 50.0
    assert gaps["Incident Reporting & Cybersecurity Culture"] == 60.0


def test_aggregate_common_actions_count_across_team():
    agg = aggregate_assessment(_employee_submissions(5))
    actions = {item["action"]: item["count"] for item in agg["common_actions"]}
    # Every respondent scored Device at "watch", so its action recurs for all 5.
    assert actions["Do for Device & Data Security"] == 5


# --------------------------------------------------------------------------- #
# aggregate_assessment — min-N suppression
# --------------------------------------------------------------------------- #
def test_aggregate_suppressed_below_min_n():
    agg = aggregate_assessment(_employee_submissions(MIN_AGGREGATE_N - 1))
    assert agg["suppressed"] is True
    assert agg["respondent_count"] == MIN_AGGREGATE_N - 1
    assert agg["min_n"] == MIN_AGGREGATE_N
    # No breakdown is computed — it cannot leak downstream.
    for leaked_key in ("category_means", "gap_prevalence", "band_distribution", "top_team_gaps"):
        assert leaked_key not in agg


def test_aggregate_empty_is_suppressed():
    agg = aggregate_assessment([])
    assert agg["suppressed"] is True
    assert agg["respondent_count"] == 0


# --------------------------------------------------------------------------- #
# anonymity — no verbatim answer / PII in the aggregate
# --------------------------------------------------------------------------- #
def test_aggregate_contains_no_verbatim_answer_text():
    marker = "SECRET-PII-abc123"
    agg = aggregate_assessment(_employee_submissions(5, marker=marker))
    serialized = json.dumps(agg)
    assert marker not in serialized
    assert "chosen" not in serialized
    assert "Question for" not in serialized


# --------------------------------------------------------------------------- #
# compare_tracks — mapping, gap sign, control-only, edges
# --------------------------------------------------------------------------- #
def _org_summary():
    return analyze_assessment(_org_submission(CONTROL_SCORES), report_type="organization")


def test_compare_tracks_pairs_all_mapped_categories():
    agg = aggregate_assessment(_employee_submissions(5))
    comparison = compare_tracks(agg, _org_summary())
    assert comparison["suppressed"] is False
    assert len(comparison["pairs"]) == len(CONTROL_TO_BEHAVIOR)
    assert {p["control_category"] for p in comparison["pairs"]} == set(CONTROL_TO_BEHAVIOR)


def test_compare_tracks_gap_sign_and_severity():
    agg = aggregate_assessment(_employee_submissions(5))
    pairs = {p["control_category"]: p for p in compare_tracks(agg, _org_summary())["pairs"]}

    identity = pairs["Identity & Access Management"]
    assert identity["control_score"] == 100.0
    assert identity["behavior_score"] == 80.0
    assert identity["gap"] == 20.0            # leadership rates control above behavior
    assert identity["severity"] == "strength"  # behavior is 80% of stated -> aligned

    remote = pairs["Remote Work Security"]
    assert remote["gap"] == -25.0             # staff outperform the stated control
    assert remote["severity"] == "strength"


def test_compare_tracks_sorted_by_gap_descending():
    agg = aggregate_assessment(_employee_submissions(5))
    gaps = [p["gap"] for p in compare_tracks(agg, _org_summary())["pairs"]]
    assert gaps == sorted(gaps, reverse=True)
    assert gaps[-1] == -25.0  # Remote Work lands last


def test_compare_tracks_two_controls_map_to_one_behavior():
    agg = aggregate_assessment(_employee_submissions(5))
    pairs = compare_tracks(agg, _org_summary())["pairs"]
    device_pairs = [p for p in pairs if p["behavior_category"] == "Device & Data Security"]
    assert len(device_pairs) == 2
    assert all(p["behavior_score"] == 50.0 for p in device_pairs)


def test_compare_tracks_lists_control_only_separately():
    agg = aggregate_assessment(_employee_submissions(5))
    comparison = compare_tracks(agg, _org_summary())
    control_only_cats = {item["category"] for item in comparison["control_only"]}
    assert control_only_cats == set(CONTROL_ONLY)
    assert all("no behavioral signal" in item["note"].lower() for item in comparison["control_only"])


def test_compare_tracks_skips_category_missing_from_org():
    agg = aggregate_assessment(_employee_submissions(5))
    partial = dict(CONTROL_SCORES)
    del partial["Remote Work Security"]
    org_summary = analyze_assessment(_org_submission(partial), report_type="organization")
    control_cats = {p["control_category"] for p in compare_tracks(agg, org_summary)["pairs"]}
    assert "Remote Work Security" not in control_cats


def test_compare_tracks_skips_category_missing_from_behavior():
    # Behavior side only knows about phishing -> only its mapped control pairs.
    agg = {
        "suppressed": False,
        "respondent_count": 5,
        "min_n": MIN_AGGREGATE_N,
        "category_means": {"Phishing Awareness & Email Security": 50.0},
    }
    pairs = compare_tracks(agg, _org_summary())["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["control_category"] == "Security Awareness & Training"


def test_compare_tracks_degraded_when_aggregate_suppressed():
    agg = aggregate_assessment(_employee_submissions(MIN_AGGREGATE_N - 1))
    comparison = compare_tracks(agg, _org_summary())
    assert comparison["suppressed"] is True
    assert comparison["pairs"] == []
    # Org self-assessment side is still carried so the report can render it.
    assert {item["category"] for item in comparison["control_only"]} == set(CONTROL_ONLY)
    assert comparison["control_scores"]  # full stated-control picture present


# --------------------------------------------------------------------------- #
# mapping tables vs. the real questionnaires (drift guard)
# --------------------------------------------------------------------------- #
def _questionnaire_categories(name):
    path = os.path.join(SRC, "Question_And_Data", f"{name}_questionnaire.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {q["category"] for q in data["questions"]}


def test_mapping_matches_questionnaire_categories():
    employee_cats = _questionnaire_categories("employee")
    org_cats = _questionnaire_categories("organization")

    assert set(CONTROL_TO_BEHAVIOR.keys()) <= org_cats
    assert set(CONTROL_TO_BEHAVIOR.values()) <= employee_cats
    assert CONTROL_ONLY <= org_cats
    # Every org control is either mapped or explicitly control-only — none dropped.
    assert set(CONTROL_TO_BEHAVIOR.keys()) | CONTROL_ONLY == org_cats
