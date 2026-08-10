"""Regression net over the scoring engine.

Everything org-facing in Blocks 2-3 (aggregate, gap report, research export) is
built on top of `analyze_assessment`, so its arithmetic and band boundaries are
pinned here before that work starts. Pure functions, no I/O, no OpenAI.
"""

from utils.report_analysis import (
    analyze_assessment,
    get_maturity_label,
    get_priority_label,
)


def _question(category, question, selected_score, max_score=4, style="score"):
    """Build one response record in the shape the frontend POSTs."""
    if style == "score":
        answers = [{"option": f"opt{i}", "score": i} for i in range(max_score + 1)]
        selected = None if selected_score is None else {"option": f"opt{selected_score}", "score": selected_score}
    else:
        # The organization questionnaire's native value/text shape.
        answers = [{"text": f"opt{i}", "value": i} for i in range(max_score + 1)]
        selected = None if selected_score is None else {"text": f"opt{selected_score}", "value": selected_score}
    return {"question": question, "category": category, "answers": answers, "selectedAnswer": selected}


def _fixture():
    return [
        _question("Password & Access Management", "q1", 4),  # ratio 1.00 -> strength
        _question("Password & Access Management", "q2", 0),  # ratio 0.00 -> gap
        _question("Phishing Awareness & Email Security", "q3", 3),  # ratio 0.75 -> strength
    ]


class TestBands:
    def test_maturity_boundaries(self):
        assert get_maturity_label(80) == "Strong"
        assert get_maturity_label(79.9) == "Moderate"
        assert get_maturity_label(60) == "Moderate"
        assert get_maturity_label(59.9) == "Needs Attention"
        assert get_maturity_label(0) == "Needs Attention"

    def test_priority_boundaries(self):
        assert get_priority_label(0.0) == "gap"
        assert get_priority_label(0.25) == "gap"
        assert get_priority_label(0.26) == "watch"
        assert get_priority_label(0.74) == "watch"
        assert get_priority_label(0.75) == "strength"
        assert get_priority_label(1.0) == "strength"


class TestAnalyzeAssessment:
    def test_overall_score_is_earned_over_possible(self):
        summary = analyze_assessment(_fixture(), report_type="employee")
        # earned 4+0+3 = 7, possible 4+4+4 = 12 -> 58.3%
        assert summary["overall_score"] == 58.3
        assert summary["maturity_label"] == "Needs Attention"

    def test_category_scores_are_per_category_ratios(self):
        summary = analyze_assessment(_fixture(), report_type="employee")
        assert summary["category_scores"] == {
            "Password & Access Management": 50.0,          # 4/8
            "Phishing Awareness & Email Security": 75.0,   # 3/4
        }

    def test_gap_categories_sorted_weakest_first(self):
        summary = analyze_assessment(_fixture(), report_type="employee")
        assert [c["category"] for c in summary["top_gap_categories"]][0] == "Password & Access Management"
        assert [c["category"] for c in summary["top_strength_categories"]][0] == "Phishing Awareness & Email Security"

    def test_responses_bucketed_by_interpretation(self):
        summary = analyze_assessment(_fixture(), report_type="employee")
        assert [s["question"] for s in summary["strengths"]] == ["q1", "q3"]
        assert [g["question"] for g in summary["gaps"]] == ["q2"]

    def test_value_style_answers_score_identically(self):
        """Org-questionnaire value/text records must score the same as option/score ones."""
        as_score = analyze_assessment(_fixture(), report_type="organization")
        as_value = analyze_assessment(
            [
                _question("Password & Access Management", "q1", 4, style="value"),
                _question("Password & Access Management", "q2", 0, style="value"),
                _question("Phishing Awareness & Email Security", "q3", 3, style="value"),
            ],
            report_type="organization",
        )
        assert as_value["overall_score"] == as_score["overall_score"]
        assert as_value["category_scores"] == as_score["category_scores"]

    def test_unanswered_questions_are_excluded_from_scoring(self):
        data = _fixture() + [_question("Device & Data Security", "q4", None)]
        summary = analyze_assessment(data, report_type="employee")
        assert summary["overall_score"] == 58.3
        assert "Device & Data Security" not in summary["category_scores"]
        assert len(summary["question_summaries"]) == 3

    def test_empty_assessment_does_not_divide_by_zero(self):
        summary = analyze_assessment([], report_type="employee")
        assert summary["overall_score"] == 0.0
        assert summary["maturity_label"] == "Needs Attention"
        assert summary["category_scores"] == {}
        assert summary["top_gap_categories"] == []
