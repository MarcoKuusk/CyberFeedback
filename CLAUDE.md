# CyberFeedback — Claude Code Guide

## Project Overview

**Cyber Hygiene Feedback Tool** — a Flask + OpenAI web app that lets employees and SMEs complete cybersecurity self-assessments and receive AI-generated PDF reports with graded recommendations.

**Stack:** Python 3, Flask, OpenAI API, ReportLab, PyMuPDF, vanilla HTML/CSS/JS  
**Run:** `python src/server.py` → http://127.0.0.1:5000  
**Env required:** `OPENAI_API_KEY` (never hardcode; never commit)
**Default OpenAI model:** `gpt-5.5` via the Responses API (`OPENAI_MODEL` can override locally)

## Project Structure

```
src/
  server.py                  # Flask app, all API endpoints
  main.py                    # PDF generation, AI section parsing
  Feedback_Generators/       # AI prompt builders per report type
  Question_And_Data/         # Questionnaire JSON files (source of truth)
  utils/report_analysis.py   # Scoring, pattern detection, priority actions
  webinterface/              # Frontend: index.html, scripts.js, styles.css
  data/                      # LOCAL ONLY — saved assessment responses
  Generated_PDF_Report/      # LOCAL ONLY — generated PDFs
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
Browser → POST /saveAssessmentData/{type} → src/data/{type}_assessment.json
       → POST /generateFeedback/{type}    → AI prompt → PDF → src/Generated_PDF_Report/
       → GET  /downloadReport/{type}      → PDF streamed to browser
```

## What to Avoid

- Do not add a database unless explicitly requested — local JSON is intentional for the current scope
- Do not add authentication middleware speculatively — scope it when multi-user support is planned
- Do not expose the Flask debug server (`debug=True`) in any non-development context
- Do not store assessment data in cookies, localStorage, or any client-side persistence

## Testing

No automated test suite yet. When adding tests:
- Use `pytest` with real file fixtures, not mocked JSON I/O
- Test the `_validate_payload()` path for both valid and adversarial inputs
- Never test against live OpenAI API — mock the `openai` client at the boundary

## Sensitive Files (never commit)

```
.env, .env.*
src/data/
src/Generated_PDF_Report/
src/config.json
venv/
```

All excluded in `.gitignore`. If you see these staged, abort and investigate.
