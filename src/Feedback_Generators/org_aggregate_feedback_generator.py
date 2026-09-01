from typing import Any, Dict

from Feedback_Generators.openai_response_client import generate_report_text, load_api_key


class OrgAggregateFeedbackGenerator:
    """Narrate the anonymized team-wide human-risk picture.

    Consumes the pre-computed `aggregate_assessment` dict only — there is no
    raw-response path into the prompt, so no individual can be named and no
    verbatim answer can leak (CLAUDE.md: prompts are built from structured
    summaries, never raw user text). Speaks in shares and team means, never about
    a single respondent.
    """

    def __init__(self, aggregate: Dict[str, Any], metadata: Dict[str, Any] | None = None):
        self.aggregate = aggregate
        self.metadata = metadata or {}
        self.api_key = self._load_api_key()

    def _load_api_key(self):
        return load_api_key()

    def generate_feedback(self):
        prompt = self._build_feedback_prompt(self.aggregate)
        return self._generate_ai_feedback(prompt)

    def _build_feedback_prompt(self, aggregate: Dict[str, Any]) -> str:
        category_context = "\n".join(
            f"- {category}: team mean {score:.1f}%"
            for category, score in sorted(aggregate["category_means"].items(), key=lambda item: item[1])
        )
        gap_context = "\n".join(
            f"- {category}: {share * 100:.0f}% of respondents scored Needs Attention"
            for category, share in sorted(aggregate["gap_prevalence"].items(), key=lambda item: item[1], reverse=True)
        )
        band_context = "\n".join(
            f"- {label}: {count} of {aggregate['respondent_count']} respondents"
            for label, count in aggregate["band_distribution"].items()
        )
        actions_context = "\n".join(
            f"- {item['action']} (raised for {item['count']} respondents)" for item in aggregate["common_actions"]
        ) or "- No common priority actions across the team."

        return f"""
You are a cybersecurity advisor writing a polished, anonymized human-risk report for the leadership of an organization, based on an aggregate of many employee self-assessments.

Write in clear business language with an executive-ready tone. This report is about the team as a whole. NEVER refer to, name, or single out any individual employee — speak only in team means, counts, and percentages. Ground every statement in the aggregate figures below. Do not invent policies, incidents, tooling, or headcount that are not provided. If the signal is limited, say so briefly.

Use exactly these sections and headings:
# Team Human-Risk Report
## Executive Summary
## Where the Team Is Strong
## Prevalent Risks
## Recommended Team Actions
## Category Breakdown

Formatting requirements:
- Keep the executive summary to one short paragraph.
- In Where the Team Is Strong, highlight the strongest categories using the team means.
- In Prevalent Risks, lead with the highest gap-prevalence categories, framed as shares of the team (for example, "just under half the team is weak on phishing").
- In Recommended Team Actions, give 4-6 concrete, prioritized actions for the whole team.
- In Category Breakdown, contrast the strongest and weakest categories in short bullets.
- Avoid generic filler and do not repeat the same recommendation.

Aggregate summary (anonymized, {aggregate['respondent_count']} respondents):
- Mean overall score: {aggregate['mean_overall_score']:.1f}%
- Overall maturity band: {aggregate['maturity_label']}

Maturity distribution:
{band_context}

Category team means (weakest first):
{category_context}

Gap prevalence (share of team scoring Needs Attention, highest first):
{gap_context}

Most widely shared priority actions:
{actions_context}
""".strip()

    def _generate_ai_feedback(self, prompt):
        return generate_report_text(self.api_key, prompt)
