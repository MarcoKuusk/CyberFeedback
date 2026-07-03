import json
import os
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, request, send_from_directory

import campaign_store
from main import generate_org_report, generate_report
from utils.report_analysis import MIN_AGGREGATE_N

app = Flask(__name__, static_folder="webinterface")

DATA_DIR = campaign_store.DATA_DIR
QUESTIONNAIRE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Question_And_Data"))
GENERATED_REPORT_DIR = campaign_store.GENERATED_REPORT_DIR
# Single source of truth for tracks lives in campaign_store (Phase 1, step 5).
ALLOWED_REPORT_TYPES = campaign_store.ALLOWED_TRACKS
# Org-level report modes (Phase 2) — allowlisted like tracks before any file I/O.
ALLOWED_ORG_REPORT_MODES = campaign_store.ALLOWED_ORG_REPORT_MODES

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(GENERATED_REPORT_DIR, exist_ok=True)


def _questionnaire_file(report_type: str) -> str:
    return os.path.join(QUESTIONNAIRE_DIR, f"{report_type}_questionnaire.json")


def _json_error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


def _validate_selected_answer(item: Dict[str, Any]) -> bool:
    selected = item.get("selectedAnswer")
    if selected is None:
        return True
    return isinstance(selected, dict) and isinstance(selected.get("option"), str) and isinstance(selected.get("score"), int)


def _validate_payload(payload: Any) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be an object."

    responses = payload.get("responses")
    metadata = payload.get("metadata", {})

    if not isinstance(responses, list) or not responses:
        return False, "Responses must be a non-empty list."
    if not isinstance(metadata, dict):
        return False, "Metadata must be an object."

    required_keys = {"question", "category", "answers"}
    for item in responses:
        if not isinstance(item, dict) or not required_keys.issubset(item.keys()):
            return False, "Each response must contain question, category, and answers."
        if not isinstance(item.get("answers"), list):
            return False, "Each response must include an answers list."
        if not _validate_selected_answer(item):
            return False, "Selected answers must include option and score values."

    return True, ""


def _validate_campaign(payload: Any) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be an object."

    org_name = payload.get("org_name")
    tracks = payload.get("tracks")

    if not isinstance(org_name, str) or not org_name.strip():
        return False, "Organization name is required."
    if not isinstance(tracks, list) or not tracks:
        return False, "At least one track is required."
    if not all(isinstance(track, str) for track in tracks):
        return False, "Tracks must be strings."
    unknown = sorted({t for t in tracks if t not in ALLOWED_REPORT_TYPES})
    if unknown:
        return False, "Tracks must be a subset of the allowed tracks."

    return True, ""


@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/admin")
def serve_admin():
    # Local-only campaign admin (dev convenience). The campaign API it drives is
    # unauthenticated in Phase 1 and only safe on 127.0.0.1; auth lands in Phase 3
    # (see docs/PHASE1_PLAN.md §3) before this is exposed anywhere hosted.
    return send_from_directory(app.static_folder, "admin.html")


@app.route("/api/questionnaire/<report_type>")
def get_questionnaire(report_type):
    if report_type not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid report type.", 400)

    file_path = _questionnaire_file(report_type)
    if not os.path.exists(file_path):
        return _json_error("Questionnaire not found.", 404)

    with open(file_path, "r", encoding="utf-8") as file:
        questionnaire = json.load(file)
    return jsonify({"status": "ok", "questionnaire": questionnaire})


@app.route("/api/campaigns", methods=["GET"])
def list_campaigns_endpoint():
    return jsonify({"status": "ok", "campaigns": campaign_store.list_campaigns()})


@app.route("/api/campaigns", methods=["POST"])
def create_campaign_endpoint():
    # NOTE: This endpoint is intentionally unauthenticated in Phase 1 and is only
    # acceptable because the app binds 127.0.0.1 for local dev. It MUST be
    # auth-gated in Phase 3 before any hosting (see docs/PHASE1_PLAN.md §3).
    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_campaign(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    try:
        campaign = campaign_store.create_campaign(payload["org_name"], payload["tracks"])
    except ValueError:
        return _json_error("Could not create campaign from the supplied details.", 400)

    return jsonify({"status": "ok", "campaign": campaign}), 201


@app.route("/api/campaigns/<campaign_id>/submissions", methods=["GET"])
def list_submissions_endpoint(campaign_id):
    if not campaign_store.is_valid_id(campaign_id):
        return _json_error("Invalid campaign id.", 400)
    campaign = campaign_store.get_campaign(campaign_id)
    if campaign is None:
        return _json_error("Campaign not found.", 404)

    # Per track, list respondent ids and whether a report has been generated.
    # No submission contents (PII) are read or returned — only opaque ids.
    submissions = {}
    for track in campaign.get("tracks", []):
        rows = []
        for respondent_id in campaign_store.list_submissions(campaign_id, track):
            has_report = os.path.exists(campaign_store.report_path(campaign_id, track, respondent_id))
            rows.append({"respondent_id": respondent_id, "has_report": has_report})
        submissions[track] = rows

    # Surface the anonymity floor so the admin UI can explain why an aggregate is
    # unavailable for a small employee track (no per-respondent data is exposed).
    return jsonify(
        {
            "status": "ok",
            "campaign": campaign,
            "submissions": submissions,
            "min_aggregate_n": MIN_AGGREGATE_N,
        }
    )


@app.route("/saveAssessmentData/<campaign_id>/<track>", methods=["POST"])
def save_assessment_data(campaign_id, track):
    if track not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid track.", 400)
    if not campaign_store.is_valid_id(campaign_id):
        return _json_error("Invalid campaign id.", 400)

    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_payload(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    try:
        respondent_id = campaign_store.save_submission(campaign_id, track, payload)
    except ValueError:
        return _json_error("Invalid track for this campaign.", 400)
    except LookupError:
        return _json_error("Campaign not found.", 404)

    return jsonify(
        {
            "status": "ok",
            "message": f"{track.title()} assessment saved.",
            "respondent_id": respondent_id,
        }
    )


@app.route("/generateFeedback/<campaign_id>/<track>/<respondent_id>", methods=["POST"])
def generate_feedback(campaign_id, track, respondent_id):
    if track not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid track.", 400)
    if not campaign_store.is_valid_id(campaign_id) or not campaign_store.is_valid_id(respondent_id):
        return _json_error("Invalid identifier.", 400)

    # Resolve the submission first. These calls have well-defined failure modes;
    # keep their narrow handlers separate from report generation so a LookupError
    # subclass (e.g. KeyError) raised deep inside generation can't be misread as
    # "campaign not found".
    try:
        assessment_data, metadata = campaign_store.load_submission(campaign_id, track, respondent_id)
        output_path = campaign_store.report_path(campaign_id, track, respondent_id)
    except LookupError:
        return _json_error("Campaign not found.", 404)
    except FileNotFoundError:
        return _json_error("No saved submission found for this respondent.", 404)
    except ValueError:
        return _json_error("Invalid identifier.", 400)

    try:
        report_file, summary = generate_report(track, assessment_data, metadata, output_path)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(str(exc), 500)
    except Exception:
        return _json_error("Report generation failed. Check server logs for details.", 500)

    return jsonify(
        {
            "status": "ok",
            "message": f"{os.path.basename(report_file)} is ready.",
            "summary": summary,
        }
    )


@app.route("/downloadReport/<campaign_id>/<track>/<respondent_id>", methods=["GET"])
def download_report(campaign_id, track, respondent_id):
    if track not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid track.", 400)
    if not campaign_store.is_valid_id(campaign_id) or not campaign_store.is_valid_id(respondent_id):
        return _json_error("Invalid identifier.", 400)

    try:
        file_path = campaign_store.report_path(campaign_id, track, respondent_id)
    except ValueError:
        return _json_error("Invalid identifier.", 400)
    except LookupError:
        return _json_error("Campaign not found.", 404)

    if not os.path.exists(file_path):
        return _json_error("Requested report is not available yet.", 404)

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=f"{track}_feedback_report.pdf",
    )


@app.route("/generateOrgReport/<campaign_id>/<mode>", methods=["POST"])
def generate_org_report_endpoint(campaign_id, mode):
    # NOTE: Org-level reports expose *aggregated org data* and must be treated as
    # leadership/admin-only. Like /api/campaigns, this is unauthenticated in
    # Phase 2 and acceptable ONLY because the app binds 127.0.0.1. It MUST be
    # auth-gated in Phase 3 before any hosting. The min-N anonymization inside
    # aggregate_assessment is the second line of defense regardless of auth.
    if mode not in ALLOWED_ORG_REPORT_MODES:
        return _json_error("Invalid report mode.", 400)
    if not campaign_store.is_valid_id(campaign_id):
        return _json_error("Invalid campaign id.", 400)
    if campaign_store.get_campaign(campaign_id) is None:
        return _json_error("Campaign not found.", 404)

    try:
        output_path = campaign_store.org_report_path(campaign_id, mode)
    except LookupError:
        return _json_error("Campaign not found.", 404)
    except ValueError:
        return _json_error("Invalid report mode.", 400)

    try:
        report_file, _summary = generate_org_report(mode, campaign_id, output_path)
    except LookupError:
        return _json_error("Campaign not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(str(exc), 500)
    except Exception:
        return _json_error("Report generation failed. Check server logs for details.", 500)

    return jsonify(
        {
            "status": "ok",
            "message": f"{os.path.basename(report_file)} is ready.",
            "mode": mode,
        }
    )


@app.route("/downloadOrgReport/<campaign_id>/<mode>", methods=["GET"])
def download_org_report(campaign_id, mode):
    if mode not in ALLOWED_ORG_REPORT_MODES:
        return _json_error("Invalid report mode.", 400)
    if not campaign_store.is_valid_id(campaign_id):
        return _json_error("Invalid campaign id.", 400)

    try:
        file_path = campaign_store.org_report_path(campaign_id, mode)
    except ValueError:
        return _json_error("Invalid report mode.", 400)
    except LookupError:
        return _json_error("Campaign not found.", 404)

    if not os.path.exists(file_path):
        return _json_error("Requested report is not available yet.", 404)

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=f"{mode}_report.pdf",
    )


@app.route("/<path:path>")
def serve_static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
