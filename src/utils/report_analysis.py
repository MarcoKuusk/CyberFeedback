from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List


MATURITY_BANDS = (
    (80, "Strong"),
    (60, "Moderate"),
    (0, "Needs Attention"),
)

# Below this respondent count, no per-respondent-derived breakdown leaves
# aggregate_assessment(). This is the anonymity floor for every org-level report
# (see docs/PHASE2_PLAN.md §1) — enforced here at the source, not just in the UI,
# so a suppressed aggregate can never leak through a downstream serialization
# mistake.
MIN_AGGREGATE_N = 5

# The two questionnaires use different category taxonomies, so the gap report is
# not a row-by-row score diff — it requires an explicit control -> behavior
# mapping. Keeping the map as data (not scattered if-branches) makes a
# questionnaire edit a one-line change and the map directly unit-testable.
# control category (organization track) -> employee behavior category
CONTROL_TO_BEHAVIOR = {
    "Identity & Access Management": "Password & Access Management",
    "Security Awareness & Training": "Phishing Awareness & Email Security",
    "Remote Work Security": "Remote Work & Public Network Security",
    "Incident Response & Business Continuity": "Incident Reporting & Cybersecurity Culture",
    "Network & Endpoint Security": "Device & Data Security",
    "Data Classification & Protection": "Device & Data Security",
}

# Organization controls with no behavioral mirror in the employee questionnaire.
# These are reported in the organizational report and flagged honestly in the gap
# report as "control stated — no behavioral signal collected" rather than silently
# dropped.
CONTROL_ONLY = {
    "Software & Patch Management",
    "Backup & Recovery",
    "Compliance & Regulatory Alignment",
    "Physical Security",
    "Third-Party Risk",
}


def get_maturity_label(score: float) -> str:
    for threshold, label in MATURITY_BANDS:
        if score >= threshold:
            return label
    return "Needs Attention"


def get_priority_label(score_ratio: float) -> str:
    if score_ratio <= 0.25:
        return "gap"
    if score_ratio < 0.75:
        return "watch"
    return "strength"


def infer_context_signals(report_type: str, category_scores: Dict[str, float]) -> List[str]:
    signals: List[str] = []

    if report_type == "employee":
        if category_scores.get("Remote Work & Public Network Security", 100) < 60:
            signals.append("Remote work habits need reinforcement.")
        if category_scores.get("Phishing Awareness & Email Security", 100) < 60:
            signals.append("Email and phishing awareness is a priority learning area.")
        if category_scores.get("Incident Reporting & Cybersecurity Culture", 100) < 60:
            signals.append("Reporting confidence and security culture need support.")
    else:
        if category_scores.get("Security Awareness & Training", 100) < 60:
            signals.append("Training maturity is low and likely increasing human-risk exposure.")
        if category_scores.get("Incident Response & Business Continuity", 100) < 60:
            signals.append("Incident readiness appears immature for operational resilience.")
        if category_scores.get("Identity & Access Management", 100) < 60:
            signals.append("Identity and access controls need leadership attention.")

    return signals[:3]


def _extract_answer_text(selected_answer: Dict[str, Any]) -> str:
    return (
        selected_answer.get("option")
        or selected_answer.get("text")
        or selected_answer.get("label")
        or "No response"
    )


def _extract_answer_score(selected_answer: Dict[str, Any]) -> int:
    if "score" in selected_answer:
        return int(selected_answer["score"])
    return int(selected_answer.get("value", 0))


def _extract_max_score(question_data: Dict[str, Any]) -> int:
    answers = question_data.get("answers", [])
    max_score = 0
    for answer in answers:
        if "score" in answer:
            max_score = max(max_score, int(answer["score"]))
        else:
            max_score = max(max_score, int(answer.get("value", 0)))
    return max_score


def analyze_assessment(assessment_data: List[Dict[str, Any]], report_type: str) -> Dict[str, Any]:
    question_summaries: List[Dict[str, Any]] = []
    category_totals: Dict[str, Dict[str, float]] = defaultdict(lambda: {"earned": 0, "possible": 0, "count": 0})
    strengths: List[Dict[str, Any]] = []
    watch_items: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    action_counter: Counter[str] = Counter()

    total_score = 0
    max_score = 0

    for question_data in assessment_data:
        selected_answer = question_data.get("selectedAnswer")
        if not selected_answer:
            continue

        category = question_data.get("category", "General")
        question = question_data.get("question", "Unknown question")
        answer_text = _extract_answer_text(selected_answer)
        score = _extract_answer_score(selected_answer)
        possible = _extract_max_score(question_data)
        score_ratio = (score / possible) if possible else 0
        interpretation = get_priority_label(score_ratio)

        summary = {
            "category": category,
            "question": question,
            "selected_answer": answer_text,
            "score": score,
            "max_score": possible,
            "interpretation": interpretation,
            "feedback": question_data.get("feedback", {}),
        }
        question_summaries.append(summary)

        category_totals[category]["earned"] += score
        category_totals[category]["possible"] += possible
        category_totals[category]["count"] += 1
        total_score += score
        max_score += possible

        if interpretation == "strength":
            strengths.append(summary)
        elif interpretation == "watch":
            watch_items.append(summary)
        else:
            gaps.append(summary)

        action_text = question_data.get("feedback", {}).get("action")
        if action_text and interpretation != "strength":
            action_counter[action_text] += 1

    overall_score = round((total_score / max_score) * 100, 1) if max_score else 0.0

    category_scores = {
        category: round((values["earned"] / values["possible"]) * 100, 1) if values["possible"] else 0.0
        for category, values in category_totals.items()
    }
    sorted_categories = sorted(category_scores.items(), key=lambda item: item[1])
    top_gaps = sorted_categories[:3]
    top_strength_categories = sorted(category_scores.items(), key=lambda item: item[1], reverse=True)[:3]

    repeated_patterns = []
    for action, count in action_counter.most_common():
        if count > 1:
            repeated_patterns.append({"theme": action, "count": count})

    priority_actions = [action for action, _count in action_counter.most_common(6)]

    return {
        "report_type": report_type,
        "overall_score": overall_score,
        "maturity_label": get_maturity_label(overall_score),
        "category_scores": category_scores,
        "top_gap_categories": [{"category": name, "score": score} for name, score in top_gaps],
        "top_strength_categories": [{"category": name, "score": score} for name, score in top_strength_categories],
        "strengths": strengths[:6],
        "watch_items": watch_items[:6],
        "gaps": gaps[:8],
        "priority_actions": priority_actions,
        "repeated_patterns": repeated_patterns[:4],
        "question_summaries": question_summaries,
        "context_signals": infer_context_signals(report_type, category_scores),
    }


def aggregate_assessment(submissions: List[List[Dict[str, Any]]], report_type: str = "employee") -> Dict[str, Any]:
    """Roll many per-respondent submissions up into one anonymized team view.

    `submissions` is a list of per-respondent `assessment_data` lists (the raw
    `responses` arrays). Each is scored with the existing `analyze_assessment`
    engine, then aggregated. Only scored output is consumed here — no respondent
    id, name, or free-text answer ever enters the result.

    Anonymization is enforced at the source: below `MIN_AGGREGATE_N` respondents
    the breakdown is *never computed*, so it cannot leak downstream. A suppressed
    result carries only the count and the threshold.
    """
    n = len(submissions)
    if n < MIN_AGGREGATE_N:
        return {
            "report_type": report_type,
            "suppressed": True,
            "respondent_count": n,
            "min_n": MIN_AGGREGATE_N,
        }

    summaries = [analyze_assessment(data, report_type=report_type) for data in submissions]

    overall_scores = [summary["overall_score"] for summary in summaries]
    mean_overall_score = round(sum(overall_scores) / n, 1)

    # Collect each category's per-respondent scores so means and gap-prevalence
    # share a single pass over the scored summaries.
    category_series: Dict[str, List[float]] = defaultdict(list)
    for summary in summaries:
        for category, score in summary["category_scores"].items():
            category_series[category].append(score)

    category_means = {
        category: round(sum(scores) / len(scores), 1)
        for category, scores in category_series.items()
    }

    # Overall maturity band spread across respondents (stable shape: every band
    # present, even with a zero count).
    band_distribution = {label: 0 for _threshold, label in MATURITY_BANDS}
    for score in overall_scores:
        band_distribution[get_maturity_label(score)] += 1

    # The human-risk headline is a *share*, not a mean: what fraction of the team
    # scored "Needs Attention" in each category ("48% weak on phishing").
    gap_prevalence = {
        category: round(
            sum(1 for score in scores if get_maturity_label(score) == "Needs Attention") / len(scores),
            3,
        )
        for category, scores in category_series.items()
    }

    top_team_gaps = [
        {"category": category, "score": score}
        for category, score in sorted(category_means.items(), key=lambda item: item[1])[:3]
    ]

    # Most widely shared priority actions. Each respondent already de-dupes its
    # own actions into a list, so counting across respondents answers "how many
    # people share this action" — aggregated Counter logic, never raw text.
    action_counter: Counter[str] = Counter()
    for summary in summaries:
        for action in summary["priority_actions"]:
            action_counter[action] += 1
    common_actions = [
        {"action": action, "count": count} for action, count in action_counter.most_common(6)
    ]

    return {
        "report_type": report_type,
        "suppressed": False,
        "respondent_count": n,
        "min_n": MIN_AGGREGATE_N,
        "mean_overall_score": mean_overall_score,
        "maturity_label": get_maturity_label(mean_overall_score),
        "category_means": category_means,
        "band_distribution": band_distribution,
        "gap_prevalence": gap_prevalence,
        "top_team_gaps": top_team_gaps,
        "common_actions": common_actions,
        "participation": {"respondent_count": n, "expected_count": None},
    }


def compare_tracks(employee_aggregate: Dict[str, Any], org_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Pair stated control maturity against observed staff behavior per category.

    Walks `CONTROL_TO_BEHAVIOR`, emitting one row per mappable category with the
    org's stated `control_score`, the employee aggregate's `behavior_score`, and
    the `gap` between them (positive = leadership rates the control higher than
    staff behavior backs up — the risk signal). Control-only categories are listed
    separately, never faked.

    If the employee aggregate is suppressed (below the anonymity floor) this
    returns a degraded result: no behavior pairs, but the org's stated controls
    are still carried so the report can render the self-assessment side and say
    why the comparison is unavailable.
    """
    control_scores = dict(org_summary.get("category_scores", {}))
    control_only = [
        {
            "category": category,
            "score": control_scores[category],
            "note": "Control stated — no behavioral signal collected.",
        }
        for category in sorted(CONTROL_ONLY)
        if category in control_scores
    ]

    if employee_aggregate.get("suppressed"):
        return {
            "suppressed": True,
            "respondent_count": employee_aggregate.get("respondent_count", 0),
            "min_n": employee_aggregate.get("min_n", MIN_AGGREGATE_N),
            "pairs": [],
            "control_only": control_only,
            "control_scores": control_scores,
        }

    behavior_means = employee_aggregate.get("category_means", {})
    pairs: List[Dict[str, Any]] = []
    for control_category, behavior_category in CONTROL_TO_BEHAVIOR.items():
        if control_category not in control_scores or behavior_category not in behavior_means:
            continue  # a category missing from one side is skipped, not faked
        control_score = control_scores[control_category]
        behavior_score = behavior_means[behavior_category]
        # Reuse get_priority_label so severity language stays consistent with the
        # per-respondent reports: how far observed behavior falls short of the
        # stated control. Full alignment (or staff outperforming) -> "strength".
        alignment_ratio = min(behavior_score / control_score, 1.0) if control_score else 1.0
        pairs.append(
            {
                "control_category": control_category,
                "behavior_category": behavior_category,
                "control_score": control_score,
                "behavior_score": behavior_score,
                "gap": round(control_score - behavior_score, 1),
                "severity": get_priority_label(alignment_ratio),
            }
        )
    pairs.sort(key=lambda pair: pair["gap"], reverse=True)  # largest divergence first

    return {
        "suppressed": False,
        "respondent_count": employee_aggregate.get("respondent_count"),
        "min_n": employee_aggregate.get("min_n", MIN_AGGREGATE_N),
        "pairs": pairs,
        "control_only": control_only,
        "control_scores": control_scores,
    }
