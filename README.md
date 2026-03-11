# Cyber Hygiene Feedback Tool

## Overview
Cyber Hygiene Feedback Tool helps employees and SMEs assess cyber hygiene through structured questionnaires, guided review, and polished PDF reports. The refreshed experience focuses on clearer summaries, stronger presentation quality, grounded AI recommendations, and safer local configuration.

## What changed
- Professional, PDF-first report layout with score snapshot, priority actions, category breakdown, and appendix highlights.
- AI prompts now use selected answer text, category scores, repeated patterns, and prioritized actions instead of only raw weak/strong lists.
- Simpler web flow with a review step before submission, cleaner results view, and clearer report generation status.
- API key loading now uses the `OPENAI_API_KEY` environment variable instead of repository config.
- Assessment and generated report files are treated as local artifacts and ignored by git.

## Project Structure
```text
src/
  main.py                        # Report generation entry point and PDF rendering
  server.py                      # Flask app, questionnaire API, assessment saving, report download
  Feedback_Generators/           # AI prompt generation for employee and organization reports
  Question_And_Data/             # Questionnaire source JSON files
  Generated_PDF_Report/          # Generated PDFs (local artifact)
  data/                          # Saved assessment responses (local artifact)
  utils/report_analysis.py       # Shared scoring and assessment summarization logic
  webinterface/                  # HTML, CSS, and JS for the assessment experience
```

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set your OpenAI API key in the shell before starting the app.
   PowerShell example:
   ```powershell
   $env:OPENAI_API_KEY="your_api_key_here"
   ```
3. Start the Flask server:
   ```bash
   python src/server.py
   ```
4. Open the app at [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Usage
- Choose either the employee or organization assessment.
- Complete the questionnaire and review your answers before saving.
- View the immediate summary in the browser.
- Generate and download the full PDF report when ready.

## Notes
- If `OPENAI_API_KEY` is missing, PDF generation will fail with a clear error message.
- Saved assessments and generated reports may contain sensitive operational information and should be handled as local-only data unless you intentionally move them elsewhere.
