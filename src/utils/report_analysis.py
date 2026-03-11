from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List


MATURITY_BANDS = (
    (80, "Strong"),
    (60, "Moderate"),
    (0, "Needs Attention"),
)


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
