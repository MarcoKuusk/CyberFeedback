"""Shared synthetic assessment fixtures for the org-level report tests.

Extracted from the Phase 2 test suite so `test_org_reports.py` and
`test_org_generators.py` do not import across test modules. Scores are chosen so
every rolled-up figure in the assertions is exact.
"""


# Employee behavior categories, in a fixed order so tie-breaking is deterministic.
EMP_CATEGORIES = [
    "Phishing Awareness & Email Security",
    "Password & Access Management",
    "Device & Data Security",
    "Remote Work & Public Network Security",
    "Incident Reporting & Cybersecurity Culture",
]

# Per-category selected scores (out of a max of 4) for 5 synthetic respondents.
# Chosen so every rolled-up figure below is exact.
EMP_SCORES = {
    "Phishing Awareness & Email Security": [0, 0, 2, 4, 4],
    "Password & Access Management": [4, 4, 4, 4, 0],
    "Device & Data Security": [2, 2, 2, 2, 2],
    "Remote Work & Public Network Security": [3, 3, 3, 3, 3],
    "Incident Reporting & Cybersecurity Culture": [4, 4, 4, 0, 0],
}


def _make_submission(scores_by_category, max_score=4, marker=""):
    """One respondent's raw `responses` list with a controllable score per category.

    `marker` is embedded only in user-answer-shaped fields (never in feedback.action)
    so anonymity tests can assert it does not leak into any aggregate.
    """
    responses = []
    for category in EMP_CATEGORIES:
        if category not in scores_by_category:
            continue
        selected = scores_by_category[category]
        responses.append(
            {
                "question": f"Question for {category} {marker}".strip(),
                "category": category,
                "answers": [{"option": "low", "score": 0}, {"option": "high", "score": max_score}],
                "selectedAnswer": {"option": f"chosen {marker}".strip(), "score": selected},
                "feedback": {"action": f"Do for {category}"},
            }
        )
    return responses


def _employee_submissions(n=5, marker=""):
    return [
        _make_submission({cat: EMP_SCORES[cat][i] for cat in EMP_CATEGORIES}, marker=marker)
        for i in range(n)
    ]


def _org_submission(control_scores, max_score=4):
    responses = []
    for category, selected in control_scores.items():
        responses.append(
            {
                "question": f"Org question for {category}",
                "category": category,
                "answers": [{"option": "low", "score": 0}, {"option": "high", "score": max_score}],
                "selectedAnswer": {"option": "chosen", "score": selected},
                "feedback": {"action": f"Improve {category}"},
            }
        )
    return responses


CONTROL_SCORES = {
    "Identity & Access Management": 4,               # 100% -> Password (80) -> gap +20
    "Security Awareness & Training": 4,              # 100% -> Phishing (50) -> gap +50
    "Remote Work Security": 2,                       # 50%  -> Remote (75)  -> gap -25
    "Incident Response & Business Continuity": 4,    # 100% -> Incident (60) -> gap +40
    "Network & Endpoint Security": 4,               # 100% -> Device (50)  -> gap +50
    "Data Classification & Protection": 3,          # 75%  -> Device (50)  -> gap +25
    "Backup & Recovery": 2,                          # control-only
    "Software & Patch Management": 4,                # control-only
    "Compliance & Regulatory Alignment": 3,          # control-only
    "Physical Security": 2,                          # control-only
    "Third-Party Risk": 0,                           # control-only
}
