from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
import subprocess

app = Flask(__name__, static_folder='webinterface')
CORS(app)  # Enable CORS for all routes

# Directory to save assessment data
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))
GENERATED_REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'Generated_PDF_Report'))

# Ensure the directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(GENERATED_REPORT_DIR, exist_ok=True)

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route('/saveAssessmentData/<filename>', methods=['POST'])
def save_assessment_data(filename):
    try:
        # Ensure the filename ends with .json
        if not filename.endswith('.json'):
            return jsonify({"error": "Invalid file type"}), 400

        # Get the JSON data from the request
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Save the data to the specified file
        file_path = os.path.join(DATA_DIR, filename)
        with open(file_path, 'w') as file:
            json.dump(data, file, indent=4)

        return jsonify({"message": f"Data saved to {filename}."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generateFeedback/<report_type>', methods=['POST'])
def generate_feedback(report_type):
    try:
        # Run main.py to generate feedback reports
        main_script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'main.py'))
        try:
            subprocess.run(['python', main_script_path], check=True)
            print("Feedback reports generated successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Error running main.py: {e}")
            return jsonify({"error": "Failed to generate feedback reports"}), 500

        # Determine the file to serve
        if report_type == "employee":
            file_name = "employee_feedback_report.pdf"
        elif report_type == "organization":
            file_name = "organization_feedback_report.pdf"
        else:
            return jsonify({"error": "Invalid report type"}), 400

        file_path = os.path.join(GENERATED_REPORT_DIR, file_name)
        if not os.path.exists(file_path):
            return jsonify({"error": f"{file_name} not found"}), 404

        return jsonify({"message": f"{file_name} is ready for download."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/downloadReport/<report_type>', methods=['GET'])
def download_report(report_type):
    try:
        # Determine the file to serve
        if report_type == "employee":
            file_name = "employee_feedback_report.pdf"
        elif report_type == "organization":
            file_name = "organization_feedback_report.pdf"
        else:
            return jsonify({"error": "Invalid report type"}), 400

        file_path = os.path.join(GENERATED_REPORT_DIR, file_name)
        if not os.path.exists(file_path):
            return jsonify({"error": f"{file_name} not found"}), 404

        return send_from_directory(GENERATED_REPORT_DIR, file_name, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)