import os
from typing import Any, Dict, List

import openai

from utils.report_analysis import analyze_assessment


class OrganizationFeedbackGenerator:
    def __init__(self, assessment_data, metadata: Dict[str, Any] | None = None):
        self.assessment_data = assessment_data
        self.metadata = metadata or {}
        self.api_key = self._load_api_key()

    def _load_api_key(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY environment variable. Set it before generating reports.")
        return api_key

    def generate_feedback(self):
        summary = analyze_assessment(self.assessment_data, report_type="organization")
        sections = {
            "Executive Summary": self._generate_executive_summary(summary),
            "Overall Score Snapshot": self._build_score_snapshot(summary),
            "What This Means for Leadership": self._generate_leadership_implications(summary),
            "Key Strengths": self._generate_strengths(summary),
            "Biggest Risks to Address": self._generate_risks(summary),
            "Immediate / Next Quarter / Next Two Quarters": self._generate_action_plan(summary),
            "Category Breakdown": self._generate_category_commentary(summary),
            "Appendix: Response Highlights": self._build_appendix(summary),
        }

        lines = ["# Organization Cyber Hygiene Report"]
        for heading, content in sections.items():
            lines.append(f"## {heading}")
            lines.append(content.strip())
            lines.append("")
        return "\n".join(lines).strip()

    def _generate_executive_summary(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write one short paragraph for an organization cyber hygiene report aimed at SME leadership.

Tone:
- executive-ready
- practical and clear
- moderate detail
- not alarmist

Rules:
- Use only the supplied evidence.
- Mention the overall score and maturity in natural language.
- Explain the most important organizational pattern.
- Avoid long action lists and technical detail.

Evidence:
- Overall score: {summary['overall_score']:.1f}%
- Maturity: {summary['maturity_label']}
- Top leadership priorities: {self._format_priority_themes(summary['top_priorities'])}
- Strongest control areas: {self._format_habit_themes(summary['strongest_habits'])}
- Mixed signals: {self._format_mixed_signals(summary['mixed_signals'])}
""".strip()
        return self._generate_text(prompt, max_tokens=180)

    def _build_score_snapshot(self, summary: Dict[str, Any]) -> str:
        strongest = summary["top_strength_categories"][0]["category"] if summary["top_strength_categories"] else "No clear standout category"
        weakest = summary["top_gap_categories"][0]["category"] if summary["top_gap_categories"] else "No major gap category"
        lines = [
            f"- Overall score: {summary['overall_score']:.1f}% ({summary['maturity_label']})",
            f"- Strongest area: {strongest}",
            f"- Top focus area: {weakest}",
        ]
        for priority in summary["top_priorities"][:2]:
            lines.append(f"- Leadership priority: {priority['theme']} because {priority['reason']}")
        return "\n".join(lines[:5])

    def _generate_leadership_implications(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write 2 short paragraphs for a section called 'What This Means for Leadership'.

Rules:
- Explain what the current pattern means for leaders making decisions.
- Ground every point in the evidence.
- Use business language, not deep technical detail.
- Do not repeat exact wording from other sections.
- Do not invent regulations, staffing, or tooling.

Evidence:
- Context signals: {self._format_context_signals(summary['context_signals'])}
- Leadership priorities: {self._format_priority_details(summary['top_priorities'])}
- Most important risks: {self._format_risk_evidence(summary['most_important_risks'])}
- Mixed signals: {self._format_mixed_signals(summary['mixed_signals'])}
""".strip()
        return self._generate_text(prompt, max_tokens=280)

    def _generate_strengths(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write 4-5 bullets for 'Key Strengths'.

Rules:
- Each bullet must cite selected-answer context explicitly.
- Explain briefly why that control foundation matters.
- Keep the tone measured and credible.
- Do not overclaim maturity.

Evidence:
{self._format_strength_evidence(summary)}
""".strip()
        return self._generate_text(prompt, max_tokens=260)

    def _generate_risks(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write 4-5 bullets for 'Biggest Risks to Address'.

Rules:
- Each bullet must include:
  - the weak pattern
  - why it matters to the organization
  - one leadership-level improvement direction
- Use answer evidence explicitly.
- Avoid repeating the same recommendation.
- Keep the language concrete and business-relevant.

Evidence:
{self._format_risk_evidence(summary['most_important_risks'])}
""".strip()
        return self._generate_text(prompt, max_tokens=340)

    def _generate_action_plan(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write a prioritized leadership action roadmap for an organization cyber hygiene report.

Format exactly as:
### Immediate
- bullets
### Next Quarter
- bullets
### Next Two Quarters
- bullets

Rules:
- 3-4 bullets per timeframe.
- Actions should feel realistic for SME leadership.
- Use ownership hints when reasonable, such as leadership, IT, operations, or HR.
- Sequence actions so the most important governance and control gaps come first.
- Avoid product-specific recommendations unless very generic.
- Avoid repeating the same action across timeframes.

Evidence:
- Leadership priorities: {self._format_priority_details(summary['top_priorities'])}
- Repeated weak patterns: {self._format_repeated_patterns(summary['repeated_patterns'])}
- Mixed signals: {self._format_mixed_signals(summary['mixed_signals'])}
""".strip()
        return self._generate_text(prompt, max_tokens=460)

    def _generate_category_commentary(self, summary: Dict[str, Any]) -> str:
        prompt = f"""
Write short commentary for the organization's category breakdown.

Rules:
- Start with the weakest category first, then the strongest, then one additional noteworthy category if useful.
- Use short paragraphs or bullets.
- Explain what each score pattern means operationally.
- Cite answer evidence explicitly.
- Avoid generic commentary.

Evidence:
{self._format_category_evidence(summary['answer_evidence_by_category'])}
""".strip()
        return self._generate_text(prompt, max_tokens=340)

    def _build_appendix(self, summary: Dict[str, Any]) -> str:
        evidence_lines: List[str] = []
        for category in summary["answer_evidence_by_category"][:5]:
            for highlight in category["highlights"][:2]:
                evidence_lines.append(f"- {category['category']}: {highlight}")
        return "\n".join(evidence_lines[:10])

    def _format_strength_evidence(self, summary: Dict[str, Any]) -> str:
        lines: List[str] = []
        for habit in summary["strongest_habits"][:4]:
            evidence = "; ".join(habit["evidence"])
            lines.append(f"- {habit['theme']}: {evidence}")
        return "\n".join(lines) or "- No clear strengths identified."

    def _format_risk_evidence(self, items: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for item in items[:4]:
            evidence = "; ".join(item["evidence"])
            lines.append(f"- {item['theme']}: {item['risk']} Evidence: {evidence}")
        return "\n".join(lines) or "- No major risks identified."

    def _format_category_evidence(self, categories: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for category in categories[:6]:
            strengths = "; ".join(category["strengths"]) or "No standout strengths"
            risks = "; ".join(category["risks"]) or "No clear risks"
            lines.append(f"- {category['category']} ({category['score']:.1f}%): strengths={strengths}; risks={risks}")
        return "\n".join(lines)

    def _format_priority_themes(self, items: List[Dict[str, Any]]) -> str:
        return ", ".join(item["theme"] for item in items) or "none"

    def _format_habit_themes(self, items: List[Dict[str, Any]]) -> str:
        return ", ".join(item["theme"] for item in items) or "none"

    def _format_priority_details(self, items: List[Dict[str, Any]]) -> str:
        return " | ".join(f"{item['theme']}: {item['reason']} Evidence: {'; '.join(item['evidence'])}" for item in items) or "none"

    def _format_context_signals(self, items: List[str]) -> str:
        return " | ".join(items) or "none"

    def _format_mixed_signals(self, items: List[Dict[str, Any]]) -> str:
        return " | ".join(f"{item['theme']}: {'; '.join(item['evidence'])}" for item in items) or "none"

    def _format_repeated_patterns(self, items: List[Dict[str, Any]]) -> str:
        return " | ".join(f"{item['theme']} ({item['count']})" for item in items) or "none"

    def _generate_text(self, prompt: str, max_tokens: int) -> str:
        client = openai.OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write concise, executive-ready organization cybersecurity report sections. "
                        "Stay grounded in the supplied answers, avoid generic filler, and do not invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
