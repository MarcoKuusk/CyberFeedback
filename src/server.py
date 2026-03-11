import json
import os
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, request, send_from_directory

from main import generate_report, load_assessment_payload

app = Flask(__name__, static_folder="webinterface")

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
QUESTIONNAIRE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Question_And_Data"))
GENERATED_REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))
ALLOWED_REPORT_TYPES = {"employee", "organization"}

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(GENERATED_REPORT_DIR, exist_ok=True)


def _assessment_file(report_type: str) -> str:
    return os.path.join(DATA_DIR, f"{report_type}_assessment.json")


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


@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


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


@app.route("/saveAssessmentData/<report_type>", methods=["POST"])
def save_assessment_data(report_type):
    if report_type not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid report type.", 400)

    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_payload(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    file_path = _assessment_file(report_type)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)

    return jsonify({"status": "ok", "message": f"{report_type.title()} assessment saved."})


@app.route("/generateFeedback/<report_type>", methods=["POST"])
def generate_feedback(report_type):
    if report_type not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid report type.", 400)

    try:
        assessment_data, metadata = load_assessment_payload(_assessment_file(report_type))
        report_path, summary = generate_report(report_type, assessment_data, metadata, GENERATED_REPORT_DIR)
        return jsonify(
            {
                "status": "ok",
                "message": f"{os.path.basename(report_path)} is ready.",
                "summary": summary,
            }
        )
    except FileNotFoundError:
        return _json_error("No saved assessment data found for this report type.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(str(exc), 500)
    except Exception:
        return _json_error("Report generation failed. Check server logs for details.", 500)


@app.route("/downloadReport/<report_type>", methods=["GET"])
def download_report(report_type):
    if report_type not in ALLOWED_REPORT_TYPES:
        return _json_error("Invalid report type.", 400)

    file_name = f"{report_type}_feedback_report.pdf"
    file_path = os.path.join(GENERATED_REPORT_DIR, file_name)
    if not os.path.exists(file_path):
        return _json_error("Requested report is not available yet.", 404)

    return send_from_directory(GENERATED_REPORT_DIR, file_name, as_attachment=True)


@app.route("/<path:path>")
def serve_static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
