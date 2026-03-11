from Feedback_Generators.employee_feedback_generator import EmployeeFeedbackGenerator
from Feedback_Generators.organization_feedback_generator import OrganizationFeedbackGenerator

import json
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.colors import black
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib import fonts
import re
import os


def load_assessment_data(file_path):
    absolute_path = os.path.abspath(file_path)
    if not os.path.exists(absolute_path):
        print(f"Warning: {absolute_path} does not exist. Returning empty data.")
        return []  # Return an empty list or default value
    with open(absolute_path, 'r') as file:
        data = json.load(file)
        return data

def get_user_responses(questionnaire):
    responses = {}
    for item in questionnaire['questions']:
        if 'category' in item:
            print(f"\nCategory: {item['category']}")
        if 'questions' in item:
            for question in item['questions']:
                print(f"\n{question['question']}")
                for idx, answer in enumerate(question['answers']):
                    print(f"{idx + 1}. {answer['option']}")
                while True:
                    try:
                        response = int(input("Select an option (1-5): ")) - 1
                        if 0 <= response < len(question['answers']):
                            responses[question['question']] = question['answers'][response]['score']
                            break
                        else:
                            print("Invalid choice. Please select a valid option.")
                    except ValueError:
                        print("Invalid input. Please enter a number between 1 and 5.")
        else:
            print(f"\n{item['question']}")
            for idx, answer in enumerate(item['answers']):
                print(f"{idx + 1}. {answer['text']}")
            while True:
                try:
                    response = int(input("Select an option (1-5): ")) - 1
                    if 0 <= response < len(item['answers']):
                        responses[item['question']] = item['answers'][response]['value']
                        break
                    else:
                        print("Invalid choice. Please select a valid option.")
                except ValueError:
                    print("Invalid input. Please enter a number between 1 and 5.")
    return responses

def format_bullet(text, style):
    """
    Converts a Markdown-style bullet point into a formatted Paragraph with:
    - Bold label at the start (e.g., "Access Control:")
    - Bold inline phrases using **like this**
    """
    # Remove leading * or - or whitespace
    text = text.strip()
    if text.startswith("*") or text.startswith("-"):
        text = text[1:].strip()

    # Bold label before colon
    if ':' in text:
        parts = text.split(":", 1)
        label = f'<b>{parts[0]}:</b>'
        remainder = parts[1].strip()
        text = f'{label} {remainder}'

    # Convert **bold** markdown to HTML <b> for ReportLab
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    return Paragraph(f'• {text}', style)

def save_feedback_to_pdf(feedback_text, title, filename):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []

    # Define styles for different heading levels
    title_style = ParagraphStyle(name='TitleStyle', 
                                fontSize=18, 
                                leading=24, 
                                alignment=TA_LEFT, 
                                spaceAfter=12, 
                                fontName='Helvetica-Bold')
    
    h1_style = ParagraphStyle(name='H1Style',
                            fontSize=16,
                            leading=20,
                            spaceAfter=10,
                            fontName='Helvetica-Bold',
                            textColor=black)
    
    h2_style = ParagraphStyle(name='H2Style',
                            fontSize=14,
                            leading=18,
                            spaceAfter=8,
                            fontName='Helvetica-Bold',
                            textColor=black)
    
    h3_style = ParagraphStyle(name='H3Style',
                            fontSize=12,
                            leading=16,
                            spaceAfter=6,
                            fontName='Helvetica-Bold',
                            textColor=black)
    
    bullet_style = ParagraphStyle(name='BulletStyle',
                                fontSize=11,
                                leading=16,
                                leftIndent=20,
                                spaceAfter=6,
                                fontName='Helvetica')
    
    body_style = ParagraphStyle(name='BodyStyle',
                              fontSize=11,
                              leading=16,
                              spaceAfter=10,
                              fontName='Helvetica')

    # Add main title
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 12))

    # Process feedback content
    lines = feedback_text.split('\n')
    
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # Handle different header levels
        if stripped_line.startswith('# '):
            # H1: Main section (e.g., "# Cybersecurity Assessment Feedback")
            header_text = stripped_line[2:].strip()
            elements.append(Paragraph(header_text, h1_style))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=black))
            elements.append(Spacer(1, 12))
            
        elif stripped_line.startswith('## '):
            # H2: Subsection (e.g., "## What You're Doing Well")
            header_text = stripped_line[3:].strip()
            elements.append(Paragraph(header_text, h2_style))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=black))
            elements.append(Spacer(1, 8))
            
        elif stripped_line.startswith('### '):
            # H3: Sub-subsection (e.g., "### Access Control")
            header_text = stripped_line[4:].strip()
            elements.append(Paragraph(header_text, h3_style))
            elements.append(Spacer(1, 6))
            
        elif stripped_line.startswith('- '):
            # Bullet points
            bullet_text = stripped_line[2:].strip()
            formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bullet_text)
            elements.append(Paragraph(f'• {formatted_text}', bullet_style))
            elements.append(Spacer(1, 4))
            
        else:
            # Body text with optional bold formatting
            formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', stripped_line)
            elements.append(Paragraph(formatted_text, body_style))
            elements.append(Spacer(1, 6))

    doc.build(elements)

def main():
    # Load assessment data generated by saveAssessmentData
    employee_data = load_assessment_data('src/data/employee_assessment.json')
    organization_data = load_assessment_data('src/data/organization_assessment.json')

    # Check if data is empty and warn the user
    if not employee_data:
        print("Warning: No employee assessment data found.")
    if not organization_data:
        print("Warning: No organization assessment data found.")

    # Initialize feedback generators with assessment data
    employee_feedback_generator = EmployeeFeedbackGenerator(employee_data)

    organization_feedback_generator = OrganizationFeedbackGenerator(organization_data)

    # Generate feedback
    employee_feedback = employee_feedback_generator.generate_feedback() if employee_data else "No employee data available."
    organization_feedback = organization_feedback_generator.generate_feedback() if organization_data else "No organization data available."

    # Define output directory for PDF reports
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'Generated_PDF_Report'))
    os.makedirs(output_dir, exist_ok=True)

    # Save feedback to PDFs
    save_feedback_to_pdf(employee_feedback, "Employee Feedback", os.path.join(output_dir, "employee_feedback_report.pdf"))
    save_feedback_to_pdf(organization_feedback, "Organization Feedback", os.path.join(output_dir, "organization_feedback_report.pdf"))


if __name__ == "__main__":
    main()