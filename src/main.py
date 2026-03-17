from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from Feedback_Generators.employee_feedback_generator import EmployeeFeedbackGenerator
from Feedback_Generators.organization_feedback_generator import OrganizationFeedbackGenerator
from utils.report_analysis import analyze_assessment


REPORT_TITLES = {
    "employee": "Employee Cyber Hygiene Report",
    "organization": "Organization Cyber Hygiene Report",
}

REPORT_COLORS = {
    "ink": colors.HexColor("#1f2937"),
    "muted": colors.HexColor("#6b7280"),
    "line": colors.HexColor("#d1d5db"),
    "brand": colors.HexColor("#1d4ed8"),
    "brand_soft": colors.HexColor("#dbeafe"),
    "surface": colors.HexColor("#f8fafc"),
    "success_soft": colors.HexColor("#f0fdf4"),
    "warning_soft": colors.HexColor("#fffbeb"),
    "danger_soft": colors.HexColor("#fef2f2"),
}


def load_assessment_payload(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    absolute_path = os.path.abspath(file_path)
    if not os.path.exists(absolute_path):
        print(f"Warning: {absolute_path} does not exist. Returning empty data.")
        return [], {}

    with open(absolute_path, "r", encoding="utf-8") as file:
        payload = json.load(file)

    if isinstance(payload, dict):
        return payload.get("responses", []), payload.get("metadata", {})
    if isinstance(payload, list):
        return payload, {}
    return [], {}


def _clean_inline_markup(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = text.replace("&", "&amp;")
    text = text.replace("<b>", "[[B]]").replace("</b>", "[[/B]]")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("[[B]]", "<b>").replace("[[/B]]", "</b>")


def _parse_ai_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_section = "Overview"
    sections[current_section] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# ") or line.startswith("## "):
            current_section = line.lstrip("# ").strip()
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)

    return sections


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitleCustom", fontName="Helvetica-Bold", fontSize=22, leading=28, textColor=REPORT_COLORS["ink"], spaceAfter=8))
    styles.add(ParagraphStyle(name="SectionHeadingCustom", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=REPORT_COLORS["ink"], spaceAfter=6))
    styles.add(ParagraphStyle(name="SubHeadingCustom", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=REPORT_COLORS["brand"], spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.4, leading=14.5, textColor=REPORT_COLORS["ink"], spaceAfter=6))
    styles.add(ParagraphStyle(name="MutedCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12.5, textColor=REPORT_COLORS["muted"], spaceAfter=4))
    styles.add(ParagraphStyle(name="BulletCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.2, leading=14, textColor=REPORT_COLORS["ink"], leftIndent=16, firstLineIndent=-8, spaceAfter=4))
    styles.add(ParagraphStyle(name="MetricValueCustom", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=REPORT_COLORS["brand"], alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="CalloutTitleCustom", fontName="Helvetica-Bold", fontSize=11, leading=13, textColor=REPORT_COLORS["ink"], spaceAfter=3))
    return styles


def _metric_table(summary: Dict[str, Any], styles, report_type: str) -> Table:
    strongest = summary["top_strength_categories"][0]["category"] if summary["top_strength_categories"] else "No clear standout"
    weakest = summary["top_gap_categories"][0]["category"] if summary["top_gap_categories"] else "No major gap"
    labels = ["Overall score", "Maturity", "Strongest area", "Top focus"]
    if report_type == "organization":
        labels = ["Overall score", "Maturity", "Strongest control", "Top leadership focus"]
    data = [
        [Paragraph(label, styles["MutedCustom"]) for label in labels],
        [
            Paragraph(f"{summary['overall_score']:.1f}%", styles["MetricValueCustom"]),
            Paragraph(summary["maturity_label"], styles["MetricValueCustom"]),
            Paragraph(strongest, styles["BodyCustom"]),
            Paragraph(weakest, styles["BodyCustom"]),
        ],
    ]
    table = Table(data, colWidths=[1.2 * inch, 1.2 * inch, 1.9 * inch, 2.0 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), REPORT_COLORS["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.75, REPORT_COLORS["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _callout_table(title: str, items: List[str], styles, background) -> Table:
    rows = [[Paragraph(title, styles["CalloutTitleCustom"])]]
    for item in items:
        rows.append([Paragraph(_clean_inline_markup(f"- {item}"), styles["BulletCustom"])])
    table = Table(rows, colWidths=[6.2 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _category_score_table(summary: Dict[str, Any], styles, report_type: str) -> Table:
    meaning_header = "What it suggests" if report_type == "employee" else "Leadership interpretation"
    rows = [[Paragraph("Category", styles["MutedCustom"]), Paragraph("Score", styles["MutedCustom"]), Paragraph(meaning_header, styles["MutedCustom"])]]
    ordered = sorted(summary["answer_evidence_by_category"], key=lambda item: item["score"])
    for item in ordered:
        if item["score"] >= 80:
            status = "This area appears comparatively mature and can be used as a stable foundation."
        elif item["score"] >= 60:
            status = "There is a workable base here, but the controls or routines are not consistently strong."
        else:
            status = "This area needs leadership attention because the answers suggest meaningful control gaps."
        if report_type == "employee":
            if item["score"] >= 80:
                status = "Confident habits show up consistently"
            elif item["score"] >= 60:
                status = "Some good habits exist, but follow-through is mixed"
            else:
                status = "This area needs more consistent day-to-day habits"
        rows.append([
            Paragraph(item["category"], styles["BodyCustom"]),
            Paragraph(f"{item['score']:.1f}%", styles["BodyCustom"]),
            Paragraph(status, styles["BodyCustom"]),
        ])
    table = Table(rows, colWidths=[2.3 * inch, 0.8 * inch, 3.1 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), REPORT_COLORS["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.75, REPORT_COLORS["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _draw_page_chrome(canvas_obj, doc, report_title: str):
    canvas_obj.saveState()
    canvas_obj.setFillColor(REPORT_COLORS["brand"])
    canvas_obj.rect(doc.leftMargin, doc.height + doc.topMargin + 10, 120, 6, stroke=0, fill=1)
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(REPORT_COLORS["ink"])
    canvas_obj.drawString(doc.leftMargin, doc.height + doc.topMargin - 2, report_title)
    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.setFillColor(REPORT_COLORS["muted"])
    canvas_obj.drawRightString(doc.pagesize[0] - doc.rightMargin, 24, f"Page {doc.page}")
    canvas_obj.drawString(doc.leftMargin, 24, datetime.now().strftime("Generated %d %b %Y"))
    canvas_obj.restoreState()


def _render_section(elements: List[Any], section_name: str, lines: List[str], styles):
    elements.append(Paragraph(section_name, styles["SectionHeadingCustom"]))
    elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
    elements.append(Spacer(1, 6))
    for line in lines:
        if line.startswith("### "):
            elements.append(Paragraph(_clean_inline_markup(line[4:].strip()), styles["SubHeadingCustom"]))
        elif line.startswith("- "):
            elements.append(Paragraph(_clean_inline_markup(line), styles["BulletCustom"]))
        else:
            elements.append(Paragraph(_clean_inline_markup(line), styles["BodyCustom"]))
    elements.append(Spacer(1, 8))


def _render_employee_report(elements: List[Any], sections: Dict[str, List[str]], summary: Dict[str, Any], styles):
    priority_lines = [item["action"] for item in summary.get("top_priorities", [])[:3]] or summary.get("priority_actions", [])[:3]
    if priority_lines:
        elements.append(_callout_table("Immediate priorities", priority_lines, styles, REPORT_COLORS["warning_soft"]))
        elements.append(Spacer(1, 10))

    for heading in [
        "Executive Summary",
        "Overall Score Snapshot",
        "What This Means for You",
        "What You Are Doing Well",
        "Biggest Habits to Improve",
        "Next 30/60/90 Days",
    ]:
        lines = sections.pop(heading, [])
        if lines:
            _render_section(elements, heading, lines, styles)

    category_lines = sections.pop("Category Breakdown", [])
    if category_lines:
        elements.append(Paragraph("Category Breakdown", styles["SectionHeadingCustom"]))
        elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
        elements.append(Spacer(1, 6))
        weakest = summary["answer_evidence_by_category"][0]["category"] if summary.get("answer_evidence_by_category") else "No clear gap"
        strongest = sorted(summary.get("answer_evidence_by_category", []), key=lambda item: item["score"], reverse=True)[0]["category"] if summary.get("answer_evidence_by_category") else "No clear strength"
        elements.append(_callout_table("Read this section first", [f"Weakest category: {weakest}", f"Strongest category: {strongest}"], styles, REPORT_COLORS["surface"]))
        elements.append(Spacer(1, 8))
        elements.append(_category_score_table(summary, styles, "employee"))
        elements.append(Spacer(1, 8))
        for line in category_lines:
            elements.append(Paragraph(_clean_inline_markup(line), styles["BulletCustom"] if line.startswith("- ") else styles["BodyCustom"]))
        elements.append(Spacer(1, 8))

    appendix_lines = sections.pop("Appendix: Response Highlights", [])
    if appendix_lines:
        _render_section(elements, "Appendix: Response Highlights", appendix_lines, styles)


def _render_organization_report(elements: List[Any], sections: Dict[str, List[str]], summary: Dict[str, Any], styles):
    priority_lines = []
    for item in summary.get("top_priorities", [])[:3]:
        priority_lines.append(f"{item['theme']}: {item['action']}")
    if not priority_lines:
        priority_lines = summary.get("priority_actions", [])[:3]
    if priority_lines:
        elements.append(_callout_table("Top leadership actions", priority_lines, styles, REPORT_COLORS["warning_soft"]))
        elements.append(Spacer(1, 10))

    risk_lines = []
    for item in summary.get("most_important_risks", [])[:3]:
        risk_lines.append(f"{item['theme']}: {item['risk']}")
    if risk_lines:
        elements.append(_callout_table("Biggest risks on the current path", risk_lines, styles, REPORT_COLORS["danger_soft"]))
        elements.append(Spacer(1, 10))

    for heading in [
        "Executive Summary",
        "Overall Score Snapshot",
        "What This Means for Leadership",
        "Key Strengths",
        "Biggest Risks to Address",
        "Immediate / Next Quarter / Next Two Quarters",
    ]:
        lines = sections.pop(heading, [])
        if lines:
            _render_section(elements, heading, lines, styles)

    category_lines = sections.pop("Category Breakdown", [])
    if category_lines:
        elements.append(Paragraph("Category Breakdown", styles["SectionHeadingCustom"]))
        elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
        elements.append(Spacer(1, 6))
        weakest = summary["answer_evidence_by_category"][0]["category"] if summary.get("answer_evidence_by_category") else "No clear gap"
        strongest = sorted(summary.get("answer_evidence_by_category", []), key=lambda item: item["score"], reverse=True)[0]["category"] if summary.get("answer_evidence_by_category") else "No clear strength"
        elements.append(_callout_table("Leadership reading order", [f"Start with weakest area: {weakest}", f"Use this strength as a base: {strongest}"], styles, REPORT_COLORS["surface"]))
        elements.append(Spacer(1, 8))
        elements.append(_category_score_table(summary, styles, "organization"))
        elements.append(Spacer(1, 8))
        for line in category_lines:
            elements.append(Paragraph(_clean_inline_markup(line), styles["BulletCustom"] if line.startswith("- ") else styles["BodyCustom"]))
        elements.append(Spacer(1, 8))

    appendix_lines = sections.pop("Appendix: Response Highlights", [])
    if appendix_lines:
        _render_section(elements, "Appendix: Response Highlights", appendix_lines, styles)


def save_feedback_to_pdf(feedback_text: str, summary: Dict[str, Any], title: str, filename: str):
    styles = _build_styles()
    sections = _parse_ai_sections(feedback_text)
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=44, leftMargin=44, topMargin=52, bottomMargin=40)
    elements: List[Any] = []
    report_type = summary.get("report_type", "employee")

    intro_copy = "A practical employee cyber hygiene report built from your questionnaire answers."
    if report_type == "organization":
        intro_copy = "An executive-ready cyber hygiene report built from your organization's assessment answers."

    elements.append(Paragraph(title, styles["ReportTitleCustom"]))
    elements.append(Paragraph(intro_copy, styles["MutedCustom"]))
    elements.append(Spacer(1, 10))
    elements.append(_metric_table(summary, styles, report_type))
    elements.append(Spacer(1, 12))

    if report_type == "organization":
        _render_organization_report(elements, sections, summary, styles)
    else:
        _render_employee_report(elements, sections, summary, styles)

    for section_name, lines in sections.items():
        if section_name == "Overview" or not lines:
            continue
        _render_section(elements, section_name, lines, styles)

    doc.build(
        elements,
        onFirstPage=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
        onLaterPages=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
    )


def generate_report(report_type: str, assessment_data: List[Dict[str, Any]], metadata: Dict[str, Any], output_dir: str):
    if not assessment_data:
        raise ValueError(f"No {report_type} assessment data available.")

    generator_class = EmployeeFeedbackGenerator if report_type == "employee" else OrganizationFeedbackGenerator
    generator = generator_class(assessment_data, metadata=metadata)
    feedback = generator.generate_feedback()
    summary = analyze_assessment(assessment_data, report_type=report_type)

    filename = os.path.join(output_dir, f"{report_type}_feedback_report.pdf")
    save_feedback_to_pdf(feedback, summary, title=REPORT_TITLES[report_type], filename=filename)
    return filename, summary


def main():
    employee_data, employee_metadata = load_assessment_payload("src/data/employee_assessment.json")
    organization_data, organization_metadata = load_assessment_payload("src/data/organization_assessment.json")

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))
    os.makedirs(output_dir, exist_ok=True)

    if employee_data:
        generate_report("employee", employee_data, employee_metadata, output_dir)
    else:
        print("Warning: No employee assessment data found.")

    if organization_data:
        generate_report("organization", organization_data, organization_metadata, output_dir)
    else:
        print("Warning: No organization assessment data found.")


if __name__ == "__main__":
    main()
