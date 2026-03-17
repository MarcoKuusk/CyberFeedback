from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List


MATURITY_BANDS = (
    (80, "Strong"),
    (60, "Moderate"),
    (0, "Needs Attention"),
)

EMPLOYEE_THEME_RULES = (
    {
        "key": "password_hygiene",
        "label": "Password hygiene",
        "keywords": ("password", "password manager"),
        "risk": "Password reuse or weak storage can turn one exposed account into many compromised accounts.",
        "action": "Use unique passwords everywhere and keep them in a trusted password manager.",
    },
    {
        "key": "mfa_access",
        "label": "Multi-factor authentication",
        "keywords": ("multi-factor", "mfa"),
        "risk": "Without strong MFA habits, stolen passwords are much easier to use.",
        "action": "Enable MFA on every work-critical account and review the few accounts still missing it.",
    },
    {
        "key": "phishing_awareness",
        "label": "Phishing awareness",
        "keywords": ("phishing", "sender", "attachments", "links", "email"),
        "risk": "Weak email verification habits make it easier to click into account theft or malware.",
        "action": "Slow down around messages that ask for urgent action and verify links and senders before clicking.",
    },
    {
        "key": "reporting_culture",
        "label": "Incident reporting",
        "keywords": ("report", "incident", "mistake", "security issue"),
        "risk": "If suspicious activity is not reported quickly, small problems can grow into larger incidents.",
        "action": "Learn the reporting route and use it early, even when you are unsure whether something is serious.",
    },
    {
        "key": "device_update",
        "label": "Device protection",
        "keywords": ("update", "patch", "lock", "device", "usb", "software"),
        "risk": "Outdated or loosely controlled devices are easier to misuse or compromise.",
        "action": "Keep devices updated, locked, and limited to approved software and accessories.",
    },
    {
        "key": "secure_communication",
        "label": "Secure communication",
        "keywords": ("encrypted", "communication"),
        "risk": "Sensitive work conversations are more exposed when secure channels are used inconsistently.",
        "action": "Use approved secure channels by default whenever work information is sensitive.",
    },
    {
        "key": "remote_work",
        "label": "Remote work safety",
        "keywords": ("vpn", "public wi-fi", "public wi", "remote", "family", "friends"),
        "risk": "Unsafe remote access and shared devices can expose work information outside trusted environments.",
        "action": "Treat remote work as high-risk by using VPN, avoiding public Wi-Fi, and keeping work devices private.",
    },
    {
        "key": "security_training",
        "label": "Security training",
        "keywords": ("training", "exercise", "simulated"),
        "risk": "Without regular practice, recognition and response habits fade over time.",
        "action": "Take part in regular security training and use each exercise to improve one habit.",
    },
)

ORGANIZATION_THEME_RULES = (
    {
        "key": "identity_access",
        "label": "Identity and access management",
        "keywords": ("mfa", "multi-factor", "password", "access", "least privilege", "account"),
        "risk": "Weak identity controls increase the chance of unauthorized access, credential misuse, and privilege sprawl.",
        "action": "Prioritize stronger identity controls, especially MFA coverage, privilege review, and account lifecycle discipline.",
    },
    {
        "key": "patch_vulnerability",
        "label": "Patch and vulnerability management",
        "keywords": ("update", "patch", "vulnerability", "endpoint", "antivirus"),
        "risk": "Gaps in patching and vulnerability management leave known weaknesses open longer than necessary.",
        "action": "Tighten update governance and scanning coverage so known weaknesses are identified and closed faster.",
    },
    {
        "key": "data_protection",
        "label": "Data protection",
        "keywords": ("data classification", "encryption", "sensitive", "files", "communications"),
        "risk": "Inconsistent data protection makes sensitive information harder to control and easier to expose.",
        "action": "Strengthen data classification, encryption consistency, and protection of sensitive business information.",
    },
    {
        "key": "backup_resilience",
        "label": "Backup and recovery",
        "keywords": ("backup", "recovery", "restoration", "offsite"),
        "risk": "Recovery capability weakens when backups, storage practices, or restoration routines are uneven.",
        "action": "Improve backup resilience by tightening frequency, secure storage, and restoration confidence.",
    },
    {
        "key": "training_culture",
        "label": "Security awareness and culture",
        "keywords": ("training", "phishing", "awareness", "employees", "role-specific"),
        "risk": "Low training maturity increases exposure to routine human-error and social engineering risks.",
        "action": "Raise training maturity with regular awareness, role-based reinforcement, and measurable follow-through.",
    },
    {
        "key": "network_remote",
        "label": "Network and remote access security",
        "keywords": ("wi-fi", "endpoint", "remote access", "vpn", "zero trust", "remote"),
        "risk": "Weak network and remote-access controls can widen the attack surface and reduce visibility over access paths.",
        "action": "Strengthen network hygiene, endpoint coverage, and remote-access controls around how staff connect to systems.",
    },
    {
        "key": "incident_readiness",
        "label": "Incident readiness",
        "keywords": ("incident", "emergencies", "logging", "insurance", "reported"),
        "risk": "Incident response gaps increase operational disruption and slow the organization's ability to contain events.",
        "action": "Improve incident readiness through clearer response procedures, logging visibility, and escalation readiness.",
    },
    {
        "key": "compliance_vendor",
        "label": "Compliance and third-party governance",
        "keywords": ("compliance", "vendors", "third-party", "standards", "regulatory"),
        "risk": "Weak vendor and compliance governance can create avoidable exposure beyond internal systems alone.",
        "action": "Strengthen third-party and compliance governance so external dependencies are held to clearer security expectations.",
    },
    {
        "key": "physical_security",
        "label": "Physical security",
        "keywords": ("physical", "devices", "servers", "laptops"),
        "risk": "Weak physical controls can undermine otherwise strong digital safeguards.",
        "action": "Reinforce baseline physical controls over devices and critical equipment.",
    },
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
    return selected_answer.get("option") or selected_answer.get("text") or selected_answer.get("label") or "No response"


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


def _infer_theme(question: str, category: str, report_type: str) -> Dict[str, str]:
    haystack = f"{category} {question}".lower()
    rules = EMPLOYEE_THEME_RULES if report_type == "employee" else ORGANIZATION_THEME_RULES
    for rule in rules:
        if any(keyword in haystack for keyword in rule["keywords"]):
            return rule
    fallback_label = category if report_type == "organization" else category
    return {
        "key": category.lower().replace(" ", "_").replace("&", "and").replace("-", "_"),
        "label": fallback_label,
        "risk": f"Weaknesses in {category.lower()} can raise cyber risk and reduce operational confidence.",
        "action": f"Strengthen the controls behind {category.lower()} with a clearer ownership and follow-through routine.",
    }


def _build_evidence_line(item: Dict[str, Any]) -> str:
    return f"{item['question']} -> {item['selected_answer']}"


def analyze_assessment(assessment_data: List[Dict[str, Any]], report_type: str) -> Dict[str, Any]:
    question_summaries: List[Dict[str, Any]] = []
    category_totals: Dict[str, Dict[str, float]] = defaultdict(lambda: {"earned": 0, "possible": 0, "count": 0})
    category_evidence: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    theme_summary: Dict[str, Dict[str, Any]] = {}
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
        theme = _infer_theme(question, category, report_type)

        summary = {
            "category": category,
            "question": question,
            "selected_answer": answer_text,
            "score": score,
            "max_score": possible,
            "score_ratio": round(score_ratio, 3),
            "interpretation": interpretation,
            "theme_key": theme["key"],
            "theme_label": theme["label"],
            "theme_risk": theme["risk"],
            "theme_action": theme["action"],
            "feedback": question_data.get("feedback", {}),
        }
        question_summaries.append(summary)
        category_evidence[category].append(summary)

        category_totals[category]["earned"] += score
        category_totals[category]["possible"] += possible
        category_totals[category]["count"] += 1
        total_score += score
        max_score += possible

        theme_bucket = theme_summary.setdefault(
            theme["key"],
            {
                "key": theme["key"],
                "label": theme["label"],
                "risk": theme["risk"],
                "action": theme["action"],
                "strengths": [],
                "watch": [],
                "gaps": [],
                "score_ratios": [],
            },
        )
        theme_bucket["score_ratios"].append(score_ratio)
        if interpretation == "strength":
            strengths.append(summary)
            theme_bucket["strengths"].append(summary)
        elif interpretation == "watch":
            watch_items.append(summary)
            theme_bucket["watch"].append(summary)
        else:
            gaps.append(summary)
            theme_bucket["gaps"].append(summary)

        if interpretation != "strength":
            action_counter.update({theme["action"]: 2 if interpretation == "gap" else 1})

    overall_score = round((total_score / max_score) * 100, 1) if max_score else 0.0
    category_scores = {
        category: round((values["earned"] / values["possible"]) * 100, 1) if values["possible"] else 0.0
        for category, values in category_totals.items()
    }

    sorted_categories = sorted(category_scores.items(), key=lambda item: item[1])
    top_gaps = sorted_categories[:3]
    top_strength_categories = sorted(category_scores.items(), key=lambda item: item[1], reverse=True)[:3]

    repeated_patterns = []
    most_important_risks = []
    strongest_habits = []
    mixed_signals = []
    top_priorities = []

    for theme in theme_summary.values():
        avg_ratio = sum(theme["score_ratios"]) / len(theme["score_ratios"]) if theme["score_ratios"] else 0
        evidence = [
            *[_build_evidence_line(item) for item in theme["gaps"][:2]],
            *[_build_evidence_line(item) for item in theme["watch"][:2]],
            *[_build_evidence_line(item) for item in theme["strengths"][:1]],
        ][:4]

        weak_count = len(theme["gaps"]) + len(theme["watch"])
        if weak_count > 1:
            repeated_patterns.append({"theme": theme["label"], "count": weak_count, "evidence": evidence})
        if theme["gaps"]:
            most_important_risks.append(
                {
                    "theme": theme["label"],
                    "risk": theme["risk"],
                    "evidence": evidence,
                    "severity": len(theme["gaps"]) * 2 + len(theme["watch"]),
                }
            )
        if theme["strengths"]:
            strongest_habits.append(
                {
                    "theme": theme["label"],
                    "why_it_helps": "This area appears to provide a more stable control foundation than other parts of the assessment.",
                    "evidence": [_build_evidence_line(item) for item in theme["strengths"][:2]],
                    "score": round(avg_ratio * 100, 1),
                }
            )
        if theme["strengths"] and (theme["gaps"] or theme["watch"]):
            mixed_signals.append(
                {
                    "theme": theme["label"],
                    "summary": "The answers suggest some useful control foundations exist, but follow-through is inconsistent across adjacent practices.",
                    "evidence": evidence,
                }
            )
        if weak_count:
            breadth_factor = 1 if weak_count >= 2 else 0
            priority_score = (len(theme["gaps"]) * 3) + (len(theme["watch"]) * 2) + (1 if avg_ratio < 0.5 else 0) + breadth_factor
            top_priorities.append(
                {
                    "theme": theme["label"],
                    "priority_score": priority_score,
                    "reason": theme["risk"],
                    "action": theme["action"],
                    "evidence": evidence,
                }
            )

    repeated_patterns.sort(key=lambda item: item["count"], reverse=True)
    most_important_risks.sort(key=lambda item: item["severity"], reverse=True)
    strongest_habits.sort(key=lambda item: item["score"], reverse=True)
    top_priorities.sort(key=lambda item: item["priority_score"], reverse=True)

    answer_evidence_by_category = []
    for category, items in category_evidence.items():
        answer_evidence_by_category.append(
            {
                "category": category,
                "score": category_scores.get(category, 0.0),
                "highlights": [_build_evidence_line(item) for item in items[:4]],
                "strengths": [_build_evidence_line(item) for item in items if item["interpretation"] == "strength"][:2],
                "risks": [_build_evidence_line(item) for item in items if item["interpretation"] != "strength"][:3],
            }
        )
    answer_evidence_by_category.sort(key=lambda item: item["score"])

    priority_actions = [item["action"] for item in top_priorities[:3]]
    if not priority_actions:
        priority_actions = [action for action, _count in action_counter.most_common(3)]

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
        "strongest_habits": strongest_habits[:4],
        "most_important_risks": most_important_risks[:4],
        "mixed_signals": mixed_signals[:4],
        "top_priorities": top_priorities[:3],
        "answer_evidence_by_category": answer_evidence_by_category,
    }
