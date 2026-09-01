# CyberFeedback — Claude Code Guide

## Project Overview

**Cyber Hygiene Feedback Tool** — a Flask + OpenAI web app that lets employees and SMEs complete cybersecurity self-assessments and receive AI-generated PDF reports with graded recommendations.

**Stack:** Python 3, Flask, waitress, OpenAI API, ReportLab, vanilla HTML/CSS/JS  
**Run (dev):** `python src/serve.py` → http://127.0.0.1:8080  
**Run (prod):** `src/serve.py` under Docker behind HTTPS — see `docs/DEPLOYMENT.md`. Never expose `src/server.py` (Flask dev server).  
**Env required:** `OPENAI_API_KEY` (never hardcode; never commit)
**Default OpenAI model:** `gpt-5.5` via the Responses API (`OPENAI_MODEL` can override locally)

**Deployment model:** hosted multi-tenant. Each client organization gets a campaign; each campaign issues per-track link tokens and its own leadership viewer token.

## Project Structure

```
src/
  serve.py                   # Production entry point (waitress) + startup preflight
  server.py                  # Flask app, all API endpoints, role gates
  campaign_store.py          # Campaign registry, link/viewer tokens, path-safe storage
  main.py                    # PDF generation, AI section parsing
  Feedback_Generators/       # AI prompt builders per report type
  Question_And_Data/         # Questionnaire JSON files (source of truth)
  utils/report_analysis.py   # Scoring, aggregation, gap comparison
  webinterface/              # Frontend: index.html, scripts.js, admin.html, admin.js
  data/                      # LOCAL ONLY — saved assessment responses
  Generated_PDF_Report/      # LOCAL ONLY — generated PDFs

scripts/
  export_research_data.py    # Anonymized CSV export (never emits ids or org names)
  delete_org_data.py         # Irreversible per-organization erasure
  regenerate_reports.py      # Rebuild PDFs after a failed batch
```

## Development Commands

```powershell
# Install dependencies
pip install -r requirements.txt

# Set API key (PowerShell)
$env:OPENAI_API_KEY="sk-..."

# Or save it to your Windows user environment without storing it in the repo
.\scripts\set-openai-key.ps1

# Optional model overrides
$env:OPENAI_MODEL="gpt-5.5"
$env:OPENAI_REASONING_EFFORT="medium"

# Start server
python src/server.py

# Run from project root
cd src && python server.py
```

## Security Rules — Read Before Every Change

This is a **cybersecurity product**. Users trust it to handle sensitive assessment data. Apply strict standards throughout.

### Never do
- Hardcode secrets, API keys, tokens, or credentials anywhere in source
- Accept user-controlled strings in file paths without validation (path traversal risk)
- Expose internal tracebacks or stack traces in API error responses
- Log assessment responses or personal data to the console or files
- Disable CORS without explicit justification
- Use `eval()`, `exec()`, or dynamic code execution on any input
- Render user-supplied content as raw HTML (XSS)
- Store sensitive assessment data outside `src/data/` (which is gitignored)

### Always do
- Validate `report_type` against the `ALLOWED_REPORT_TYPES` allowlist before any file I/O
- Sanitize file paths with `os.path.abspath()` and confirm they stay within expected directories
- Return generic error messages to the client; log specifics server-side only
- Confirm new endpoints follow the existing `_json_error()` / `_validate_payload()` pattern
- Keep the OpenAI API key loaded exclusively via `os.getenv("OPENAI_API_KEY")`
- Treat questionnaire JSON files as read-only configuration — never write to them at runtime

### Authorization invariants — do not weaken without a deliberate decision

These are enforced server-side and covered by tests. Breaking one silently breaks a promise made to participants in the consent text.

- **Track is derived from the link token**, never from a request parameter. `resolve_token()` returns `(campaign, track)` together.
- **The operator role is global; the viewer role is scoped to one campaign.** `_require_org_access` compares the viewer's campaign against the `campaign_id` in the URL. Cross-tenant access must return 403, not 404.
- **A viewer never receives a `respondent_id`** — it is the bearer credential for that person's private report. `/api/campaigns/{id}/submissions` returns counts only for that role.
- **The admin console has no individual-report download.** Recovery is `scripts/regenerate_reports.py`, which writes PDFs back without reading them out.
- **The research export emits no `respondent_id`, no org name, and no submission metadata.** Tests assert their absence; keep them passing.
- **`MIN_AGGREGATE_N = 5`** suppression is applied inside `aggregate_assessment()`, not in the UI.

When adding an endpoint, decide explicitly which of the three credentials may reach it: operator token, campaign viewer token, or link token.

### Path traversal guard pattern
Every file path derived from request input must be validated:
```python
safe_base = os.path.abspath(DATA_DIR)
candidate = os.path.abspath(os.path.join(DATA_DIR, filename))
if not candidate.startswith(safe_base + os.sep):
    return _json_error("Invalid path.", 400)
```

### Input validation pattern (server.py)
All POST endpoints must call `_validate_payload()` before touching the filesystem.  
Add new endpoint validation as a dedicated `_validate_*` function following the same `(bool, str)` return convention.

## AI / OpenAI Integration

- Model calls live in `Feedback_Generators/` — one class per report type, with shared OpenAI request setup in `openai_response_client.py`
- Prompts are built from structured assessment summaries, never from raw user text
- AI output is parsed by `_parse_ai_sections()` in `main.py` — treat it as untrusted text (escape before rendering)
- Token limits: keep prompts lean; the assessment summary is already condensed by `analyze_assessment()`

## Data Flow

```
Operator  → POST /api/campaigns                     → registry + per-track tokens + viewer token
          → GET  /api/campaigns/{id}/links          → the URLs to distribute

Respondent→ GET  /c/{token}                         → single-page app
          → GET  /api/link/{token}                  → resolves campaign + THE ONE granted track
          → POST /api/link/{token}/submit           → data/{org}/{campaign}/{track}/{respondent}.json
          → POST /api/link/{token}/report/{rid}     → AI prompt → PDF
          → GET  /api/link/{token}/report/{rid}     → their own PDF

Leadership→ POST /generateOrgReport/{campaign}/{mode}   (mode: aggregate|organization|combined)
          → GET  /downloadOrgReport/{campaign}/{mode}
```

**The track comes from the token, never from the client.** A staff link cannot open the leadership questionnaire, and a leadership token cannot render an employee's report.

## What to Avoid

- Do not add a database unless explicitly requested — local JSON is intentional for the current scope
- Do not add authentication middleware speculatively — scope it when multi-user support is planned
- Do not expose the Flask debug server (`debug=True`) in any non-development context
- Do not store assessment data in cookies, localStorage, or any client-side persistence

## Testing

`python -m pytest` — the suite covers scoring, PDF rendering, path traversal, token isolation, role separation, cross-tenant boundaries, and the operator scripts.

- Use `pytest` with real file fixtures, not mocked JSON I/O
- Test `_validate_payload()` for both valid and adversarial inputs
- Never test against the live OpenAI API — mock at the `generate_report_text` boundary
- New endpoints need a test proving the *unauthorized* role is refused, not only that the authorized one works

## Sensitive Files (never commit)

```
.env, .env.*
src/data/
src/Generated_PDF_Report/
src/config.json
venv/
```

All excluded in `.gitignore`. If you see these staged, abort and investigate.
