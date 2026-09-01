# Cyber Hygiene Feedback Tool

A hosted cybersecurity self-assessment for small and medium organizations. Staff
open a link, answer about ten minutes of multiple-choice questions, and receive
their own private PDF report. Leadership receives an anonymized team-wide
picture, their own organizational self-assessment, and a combined report showing
where the two disagree.

That gap — *"leadership rates security training as mature, but most staff can't
identify a phishing email"* — is the artifact neither assessment produces alone.

---

## The two assessments

| Track | Who answers | Measures |
|---|---|---|
| **Employee** | All staff, anonymously | What people actually do |
| **Organization** | One leadership respondent | What controls are believed to be in place |

## What each party receives

- **Each employee** — their own private report. Never shown to their employer.
- **Leadership** — the anonymized employee aggregate, their own self-assessment,
  and the combined gap report.
- **The organization** — a measured human-risk baseline: stated controls versus
  observed behavior.

## Privacy, in one paragraph

No name, email, job title, or free-text field is collected anywhere — every
question is multiple choice. Individual answers are never visible to the
employer. No leadership-facing breakdown is produced below five respondents.
Each client organization's leadership credential is scoped to their own campaign
and cannot reach another client's data. Full detail, written to be handed to a
prospective client: [docs/DATA_HANDLING.md](docs/DATA_HANDLING.md).

---

## Quick start

```powershell
pip install -r requirements.txt
$env:OPENAI_API_KEY="sk-..."          # or: .\scripts\set-openai-key.ps1
python src/serve.py
```

Then open <http://127.0.0.1:8080/admin>, create a campaign, and copy the staff
link it gives you. On loopback no admin token is needed.

For a real deployment — HTTPS, Docker, tokens, backups — see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Do not expose `src/server.py`; it is
Flask's development server.

## Running an engagement

[docs/RUNBOOK.md](docs/RUNBOOK.md) covers it end to end: scoping with the client,
routing the three credentials, watching participation, generating and delivering
the reports, and deleting the data afterwards.

---

## How it fits together

```
Operator ──> /admin ──────────> creates a campaign
                                 │
                                 ├─ staff link       ──> /c/<token>  (employee questionnaire)
                                 ├─ leadership link  ──> /c/<token>  (organization questionnaire)
                                 └─ leadership code  ──> /admin      (that campaign's rollups only)

Respondent ─> /c/<token> ─> consent ─> questions ─> submit
                                                     │
                                                     ├─> stored: data/<org>/<campaign>/<track>/<id>.json
                                                     └─> their own PDF, via their link alone

Leadership ─> aggregate | organization | combined ──> PDF rollups (min. 5 respondents)
```

The link token decides which questionnaire opens, so a staff link cannot reach
the leadership assessment. The respondent id that retrieves a private report is
issued only to the browser that submitted it, and is never given to leadership.

## Project structure

```text
src/
  serve.py                   # Production entry point (waitress) — use this
  server.py                  # Flask app and all endpoints
  campaign_store.py          # Campaign registry, tokens, path-safe storage
  main.py                    # PDF generation and AI section parsing
  Feedback_Generators/       # One prompt builder per report type
  Question_And_Data/         # Questionnaire JSON (read-only configuration)
  utils/report_analysis.py   # Scoring, aggregation, gap comparison
  webinterface/              # Respondent UI and admin console
  data/                      # LOCAL ONLY — submissions (gitignored)
  Generated_PDF_Report/      # LOCAL ONLY — generated PDFs (gitignored)

scripts/
  export_research_data.py    # Anonymized CSV dataset for research
  delete_org_data.py         # Erase one organization, irreversibly
  regenerate_reports.py      # Rebuild PDFs after a failed batch
  migrate_to_campaigns.py    # One-time migration from the single-file model

docs/
  DATA_HANDLING.md           # Client-facing privacy document
  DEPLOYMENT.md              # Hosting, HTTPS, backups, deletion
  RUNBOOK.md                 # Running an engagement
  CONSENT.md                 # Consent text and participant invitations
  ROADMAP.md                 # Where this is going
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Covers the scoring arithmetic, PDF rendering, path-traversal defenses, link
token isolation, role separation and cross-tenant boundaries, and the operator
scripts. The OpenAI client is mocked at its boundary — no test reaches the live
API.

## Configuration

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. Report generation. |
| `CYBERFEEDBACK_ADMIN_TOKEN` | Operator credential. Required off loopback. |
| `CYBERFEEDBACK_PUBLIC_URL` | Public base URL used to build campaign links. |
| `OPENAI_MODEL` | Default `gpt-5.5`. |

Full table in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The API key is read only
from the environment and is never stored in the repository.
