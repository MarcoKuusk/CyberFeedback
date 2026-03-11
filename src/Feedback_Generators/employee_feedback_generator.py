import openai
from collections import defaultdict
import json

class EmployeeFeedbackGenerator:
    def __init__(self, assessment_data, config_path="src\config.json"):
        self.assessment_data = assessment_data
        self.api_key = self._load_api_key(config_path)

    def _load_api_key(self, config_path):
        with open(config_path, "r") as config_file:
            config = json.load(config_file)
        return config.get("openai_api_key")

    def generate_feedback(self):
        findings, strengths = self._summarize_findings()
        total_score = self._calculate_total_score()
        prompt = self._build_feedback_prompt(findings, strengths, total_score)
        return self._generate_ai_feedback(prompt)

    def _summarize_findings(self):
        findings = defaultdict(list)
        strengths = []

        for question_data in self.assessment_data:
            category = question_data.get("category", "General")
            question = question_data["question"]
            selected_answer = question_data.get("selectedAnswer")

            if selected_answer:
                score = selected_answer["score"]
                if score >= 3:
                    strengths.append(f"{question}")
                else:
                    findings[category].append(f"{question}")

        return findings, strengths

    def _calculate_total_score(self):
        total_score = 0
        max_score = 0

        for question_data in self.assessment_data:
            selected_answer = question_data.get("selectedAnswer")
            if selected_answer:
                total_score += selected_answer["score"]
            max_score += len(question_data["answers"]) - 1

        return (total_score / max_score) * 100 if max_score > 0 else 0

    def _determine_urgency_tone(self, score):
        if score < 30:
            return "**Critical:** Your cyber hygiene practices need urgent improvement."
        elif score < 60:
            return "**Needs Improvement:** You're making progress, but there are significant gaps."
        else:
            return "**Good Start:** You're doing well, but there's room for improvement."

    def _build_feedback_prompt(self, findings, strengths, total_score):
        findings_text = "\n\n".join(
            f"**{category}**\n" + "\n".join(f"- {item}" for item in items)
            for category, items in findings.items()
        )

        strengths_text = "\n".join(f"- {s}" for s in strengths) if strengths else "- No specific strengths identified yet."

        tone = self._determine_urgency_tone(total_score)

        prompt = f"""
        You are a cybersecurity coach helping employees at small and medium-sized businesses improve their personal cyber hygiene and security habits.

        Generate a clear, structured, and friendly feedback report based on the following self-assessment results. Your audience is an individual employee with basic digital skills but no technical background. Use plain, accessible language and make your advice easy to understand and act on.

        Use the following structure:

        ## Cyber Hygiene Score
        {total_score:.2f}%  
        {tone}

        ## Introduction
        Write a short paragraph summarizing the employee’s current cybersecurity hygiene based on the score. Mention whether it’s strong, moderate, or weak, and highlight the importance of good habits in protecting both the individual and the organization.

        ## What You're Doing Well
        Highlight areas where the employee is following good cybersecurity practices. Use bullet points and explain briefly why each one is important.

        {strengths_text}

        ## Areas to Improve
        Break down the weak areas by topic. For each, explain what needs improvement and why it matters. Use clear, simple language.

        {findings_text}

        ## Potential Risks and Risk Scenarios
        Based on the weak areas, describe the main risks. Use short, concrete examples (e.g., “If you reuse the same password everywhere, a data breach on one site could expose all your accounts.”)

        ## Personal Cyber Hygiene Action Plan

        Provide a step-by-step action plan the employee can follow to improve their habits. Break it down by timeframe, and ensure each section includes 4–6 clear, actionable items. Where helpful, add a brief tip on how to begin or what to look for (e.g., tools to use, settings to check, or support to ask for).

        ### Immediate (0–30 Days)
        Quick wins and critical fixes:

        ### Short-Term (60–90 Days)
        Mid-term improvements that may need a bit more time or learning:

        ### Medium-Term (3–6 Months)
        Longer-term changes to build sustainable habits:

        ## Conclusion
        Encourage the employee to keep improving their cybersecurity practices. Remind them that small actions — like updating passwords or learning to spot phishing — can have a big impact. Suggest reviewing their cyber hygiene again in 6–12 months.

        Write the feedback as if you’re coaching and supporting a real person in your team.
        """

        return prompt.strip()

    def _generate_ai_feedback(self, prompt):
        client = openai.OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
