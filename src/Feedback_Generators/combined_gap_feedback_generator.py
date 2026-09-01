from typing import Any, Dict

from Feedback_Generators.openai_response_client import generate_report_text, load_api_key


class CombinedGapFeedbackGenerator:
    """Narrate the stated-control vs. observed-behavior gap for leadership.

    Consumes the pre-computed `compare_tracks` dict only — mapped category scores,
    gaps, and control-only notes. There is no per-respondent or verbatim-answer
    path into the prompt, so the report cannot identify an employee. When the
    employee aggregate is suppressed, the comparison is degraded: the prompt still
    narrates the organization's stated controls and states why the staff-behavior
    comparison is unavailable.
    """

    def __init__(self, comparison: Dict[str, Any], metadata: Dict[str, Any] | None = None):
        self.comparison = comparison
        self.metadata = metadata or {}
        self.api_key = self._load_api_key()

    def _load_api_key(self):
        return load_api_key()

    def generate_feedback(self):
        prompt = self._build_feedback_prompt(self.comparison)
        return self._generate_ai_feedback(prompt)

    def _build_feedback_prompt(self, comparison: Dict[str, Any]) -> str:
        control_only_context = "\n".join(
            f"- {item['category']}: stated {item['score']:.1f}% (no behavioral signal collected)"
            for item in comparison.get("control_only", [])
        ) or "- None."

        if comparison.get("suppressed"):
            control_context = "\n".join(
                f"- {category}: stated {score:.1f}%"
                for category, score in sorted(comparison.get("control_scores", {}).items(), key=lambda item: item[1])
            ) or "- No organizational controls recorded."
            comparison_block = (
                f"The employee aggregate is withheld: only {comparison.get('respondent_count', 0)} staff have "
                f"responded and the anonymity floor is {comparison.get('min_n')}. There is no staff-behavior "
                "comparison to report yet. Describe the organization's stated control posture and explain that the "
                "behavior comparison will become available once enough employees participate.\n\n"
                f"Stated controls:\n{control_context}"
            )
        else:
            pairs_context = "\n".join(
                (
                    f"- {pair['control_category']}: stated {pair['control_score']:.1f}% vs. observed staff behavior "
                    f"({pair['behavior_category']}) {pair['behavior_score']:.1f}% — gap {pair['gap']:+.1f} "
                    f"[{pair['severity']}]"
                )
                for pair in comparison.get("pairs", [])
            ) or "- No mappable categories were available on both sides."
            comparison_block = (
                f"Employee aggregate covers {comparison.get('respondent_count')} respondents.\n\n"
                f"Stated control vs. observed behavior (largest gap first; positive gap = leadership rates the "
                f"control higher than staff behavior supports):\n{pairs_context}"
            )

        return f"""
You are a cybersecurity advisor writing a polished report for the leadership of an organization. It compares what leadership states is in place (the organizational self-assessment) against what employees actually do (the anonymized aggregate of many staff self-assessments).

Write in clear business language with an executive-ready tone. NEVER name or single out any individual employee — the employee side is an anonymized aggregate. Ground every statement in the figures below. Do not invent controls, incidents, or metrics that are not provided. Treat a positive gap (stated maturity above observed behavior) as the key risk signal.

Use exactly these sections and headings:
# Stated Controls vs. Observed Behavior
## Executive Summary
## Largest Gaps
## Where Controls and Behavior Align
## Areas Without Behavioral Signal
## Recommended Focus

Formatting requirements:
- Keep the executive summary to one short paragraph naming the single most important divergence (or, if suppressed, the current limitation).
- In Largest Gaps, walk the biggest positive gaps and explain the business risk of each in plain language.
- In Where Controls and Behavior Align, acknowledge categories where stated maturity and staff behavior agree.
- In Areas Without Behavioral Signal, briefly and honestly note the control-only categories the employee campaign cannot measure.
- In Recommended Focus, give 3-5 prioritized actions that close the widest gaps first.
- Avoid generic filler and do not repeat the same recommendation.

{comparison_block}

Control-only areas (stated by leadership, no employee behavioral counterpart):
{control_only_context}
""".strip()

    def _generate_ai_feedback(self, prompt):
        return generate_report_text(self.api_key, prompt)
