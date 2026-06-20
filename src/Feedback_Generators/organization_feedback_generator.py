from typing import Any, Dict

from Feedback_Generators.openai_response_client import generate_report_text, load_api_key
from utils.report_analysis import analyze_assessment


class OrganizationFeedbackGenerator:
    def __init__(self, assessment_data, metadata: Dict[str, Any] | None = None):
        self.assessment_data = assessment_data
        self.metadata = metadata or {}
        self.api_key = self._load_api_key()

    def _load_api_key(self):
        return load_api_key()

    def generate_feedback(self):
        summary = analyze_assessment(self.assessment_data, report_type="organization")
        prompt = self._build_feedback_prompt(summary)
        return self._generate_ai_feedback(prompt)

    def _build_feedback_prompt(self, summary: Dict[str, Any]) -> str:
        question_context = "\n".join(
            [
                (
                    f"- Category: {item['category']} | Score: {item['score']}/{item['max_score']} | "
                    f"Interpretation: {item['interpretation']} | Question: {item['question']} | "
                    f"Selected answer: {item['selected_answer']}"
                )
                for item in summary["question_summaries"]
            ]
        )
        category_context = "\n".join(
            f"- {category}: {score:.1f}%" for category, score in summary["category_scores"].items()
        )
        top_actions = "\n".join(f"- {action}" for action in summary["priority_actions"]) or "- No urgent actions identified."
        context_signals = "\n".join(f"- {signal}" for signal in summary["context_signals"]) or "- No special context signals inferred."
        repeated_patterns = "\n".join(
            f"- {pattern['theme']} (appears {pattern['count']} times)" for pattern in summary["repeated_patterns"]
        ) or "- No repeated patterns identified."

        return f"""
You are a cybersecurity advisor writing a polished report for SME leaders.

Write in clear business language with an executive-ready tone. Ground every recommendation in the selected answers below. Do not invent regulations, incidents, security tooling, headcount, or maturity claims that are not supported by the assessment. If information is limited, state the limitation briefly and keep the guidance practical.

Use exactly these sections and headings:
# Organization Cyber Hygiene Report
## Executive Summary
## Overall Score Snapshot
## Key Strengths
## Priority Risks
## Prioritized Action Roadmap
## Category Breakdown
## Appendix: Response Highlights

Formatting requirements:
- Keep the executive summary to one short paragraph.
- In Overall Score Snapshot, include the score, maturity label, and 3 short bullets for leadership.
- In Key Strengths, list 3-5 strengths tied to specific selected answers.
- In Priority Risks, explain the business impact in plain language.
- In Prioritized Action Roadmap, create three subsections titled ### Immediate, ### Next Quarter, ### Next Two Quarters with 3-5 actions each and mention likely owners when reasonable.
- In Category Breakdown, discuss the strongest and weakest categories with short paragraphs or bullets.
- In Appendix: Response Highlights, include 8-10 concise bullets grounded in the selected answers.
- Avoid generic filler and avoid repeating the same recommendation more than once.

Assessment summary:
- Overall score: {summary['overall_score']:.1f}%
- Maturity label: {summary['maturity_label']}
- Report type: organization

Category scores:
{category_context}

Context signals:
{context_signals}

Repeated patterns:
{repeated_patterns}

Priority actions:
{top_actions}

Question and answer evidence:
{question_context}
""".strip()

    def _generate_ai_feedback(self, prompt):
        return generate_report_text(self.api_key, prompt)
