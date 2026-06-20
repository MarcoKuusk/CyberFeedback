from typing import Any, Dict

from Feedback_Generators.openai_response_client import generate_report_text, load_api_key
from utils.report_analysis import analyze_assessment


class EmployeeFeedbackGenerator:
    def __init__(self, assessment_data, metadata: Dict[str, Any] | None = None):
        self.assessment_data = assessment_data
        self.metadata = metadata or {}
        self.api_key = self._load_api_key()

    def _load_api_key(self):
        return load_api_key()

    def generate_feedback(self):
        summary = analyze_assessment(self.assessment_data, report_type="employee")
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
You are a cybersecurity coach writing a polished report for an employee with basic digital skills.

Write in plain English, with a warm and professional tone. Tailor all recommendations to the actual selected answers below. Do not make up policies, incidents, technology, or job responsibilities that were not provided. If evidence is limited, say so briefly and stay grounded in the assessment results.

Use exactly these sections and headings:
# Employee Cyber Hygiene Report
## Executive Summary
## Overall Score Snapshot
## What You Are Doing Well
## Priority Risks
## 30-60-90 Day Action Roadmap
## Category Breakdown
## Appendix: Response Highlights

Formatting requirements:
- Keep the executive summary to one short paragraph.
- In Overall Score Snapshot, include the score, maturity label, and 3 short bullets for the most important takeaways.
- In What You Are Doing Well, highlight 3-5 strengths tied to the user's selected answers.
- In Priority Risks, explain the main risks in concrete everyday terms.
- In 30-60-90 Day Action Roadmap, create three subsections titled ### Next 30 Days, ### Next 60 Days, ### Next 90 Days with 3-5 actions each.
- In Category Breakdown, discuss the strongest and weakest categories with short paragraphs or bullets.
- In Appendix: Response Highlights, include 6-8 concise bullets that quote or paraphrase the user's selected answers.
- Avoid generic filler and avoid repeating the same recommendation more than once.

Assessment summary:
- Overall score: {summary['overall_score']:.1f}%
- Maturity label: {summary['maturity_label']}
- Report type: employee

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
