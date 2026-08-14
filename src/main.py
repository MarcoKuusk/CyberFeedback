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
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
    "success": colors.HexColor("#15803d"),
    "warning": colors.HexColor("#b45309"),
    "danger": colors.HexColor("#b91c1c"),
    "surface": colors.HexColor("#f8fafc"),
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
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            textColor=REPORT_COLORS["ink"],
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=REPORT_COLORS["ink"],
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=REPORT_COLORS["brand"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=REPORT_COLORS["ink"],
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Muted",
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=REPORT_COLORS["muted"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            # Not "Bullet": getSampleStyleSheet() already defines that name, and
            # StyleSheet1.add() raises KeyError on a duplicate — which silently
            # broke every PDF until it was caught by a test.
            name="ReportBullet",
            fontName="Helvetica",
            fontSize=10.2,
            leading=14,
            textColor=REPORT_COLORS["ink"],
            leftIndent=16,
            firstLineIndent=-8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetricValue",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=REPORT_COLORS["brand"],
            alignment=TA_LEFT,
        )
    )
    return styles


def _metric_table(summary: Dict[str, Any], styles) -> Table:
    data = [
        [
            Paragraph("Overall score", styles["Muted"]),
            Paragraph("Maturity", styles["Muted"]),
            Paragraph("Top focus", styles["Muted"]),
        ],
        [
            Paragraph(f"{summary['overall_score']:.1f}%", styles["MetricValue"]),
            Paragraph(summary["maturity_label"], styles["MetricValue"]),
            Paragraph(
                summary["top_gap_categories"][0]["category"] if summary["top_gap_categories"] else "No major gaps identified",
                styles["Body"],
            ),
        ],
    ]
    table = Table(data, colWidths=[1.5 * inch, 1.5 * inch, 3.3 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), REPORT_COLORS["surface"]),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.75, REPORT_COLORS["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _category_score_table(summary: Dict[str, Any], styles) -> Table:
    rows = [[Paragraph("Category", styles["Muted"]), Paragraph("Score", styles["Muted"]), Paragraph("Status", styles["Muted"])]]
    for category, score in sorted(summary["category_scores"].items(), key=lambda item: item[1]):
        if score >= 80:
            status = "Strong"
        elif score >= 60:
            status = "Moderate"
        else:
            status = "Needs Attention"
        rows.append(
            [
                Paragraph(category, styles["Body"]),
                Paragraph(f"{score:.1f}%", styles["Body"]),
                Paragraph(status, styles["Body"]),
            ]
        )
    table = Table(rows, colWidths=[3.8 * inch, 1.0 * inch, 1.7 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), REPORT_COLORS["surface"]),
                ("BOX", (0, 0), (-1, -1), 0.75, REPORT_COLORS["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _draw_page_chrome(canvas_obj, doc, report_title: str):
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(REPORT_COLORS["line"])
    canvas_obj.setFillColor(REPORT_COLORS["brand"])
    canvas_obj.rect(doc.leftMargin, doc.height + doc.topMargin + 10, 90, 6, stroke=0, fill=1)
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(REPORT_COLORS["ink"])
    canvas_obj.drawString(doc.leftMargin, doc.height + doc.topMargin - 2, report_title)
    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.setFillColor(REPORT_COLORS["muted"])
    canvas_obj.drawRightString(doc.pagesize[0] - doc.rightMargin, 24, f"Page {doc.page}")
    canvas_obj.drawString(doc.leftMargin, 24, datetime.now().strftime("Generated %d %b %Y"))
    canvas_obj.restoreState()


def save_feedback_to_pdf(feedback_text: str, summary: Dict[str, Any], title: str, filename: str):
    styles = _build_styles()
    sections = _parse_ai_sections(feedback_text)
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=44, leftMargin=44, topMargin=52, bottomMargin=40)
    elements: List[Any] = []

    elements.append(Paragraph(title, styles["ReportTitle"]))
    elements.append(Paragraph("Professional cyber hygiene assessment designed for clear decision-making and practical follow-through.", styles["Muted"]))
    elements.append(Spacer(1, 10))
    elements.append(_metric_table(summary, styles))
    elements.append(Spacer(1, 14))

    executive_lines = sections.pop("Executive Summary", [])
    if executive_lines:
        elements.append(Paragraph("Executive Summary", styles["SectionHeading"]))
        elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
        elements.append(Spacer(1, 6))
        elements.extend(Paragraph(_clean_inline_markup(line), styles["Body"]) for line in executive_lines)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph("Top Priorities", styles["SectionHeading"]))
    elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
    elements.append(Spacer(1, 6))
    for action in summary["priority_actions"][:5] or ["No urgent actions identified."]:
        elements.append(Paragraph(f"- {_clean_inline_markup(action)}", styles["ReportBullet"]))
    elements.append(Spacer(1, 10))

    if summary["top_gap_categories"]:
        elements.append(Paragraph("Highest-Risk Categories", styles["SectionHeading"]))
        elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
        elements.append(Spacer(1, 6))
        for item in summary["top_gap_categories"]:
            elements.append(Paragraph(f"- <b>{_clean_inline_markup(item['category'])}</b>: {item['score']:.1f}%", styles["ReportBullet"]))
        elements.append(Spacer(1, 10))

    for section_name, lines in sections.items():
        if section_name in {"Overview", "Overall Score Snapshot"} or not lines:
            continue
        if section_name == "Category Breakdown":
            elements.append(Paragraph(section_name, styles["SectionHeading"]))
            elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
            elements.append(Spacer(1, 6))
            elements.append(_category_score_table(summary, styles))
            elements.append(Spacer(1, 8))
        else:
            elements.append(Paragraph(section_name, styles["SectionHeading"]))
            elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
            elements.append(Spacer(1, 6))

        for line in lines:
            if line.startswith("### "):
                elements.append(Paragraph(_clean_inline_markup(line[4:].strip()), styles["SubHeading"]))
            elif line.startswith("- "):
                elements.append(Paragraph(_clean_inline_markup(line), styles["ReportBullet"]))
            else:
                elements.append(Paragraph(_clean_inline_markup(line), styles["Body"]))
        elements.append(Spacer(1, 8))

    doc.build(
        elements,
        onFirstPage=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
        onLaterPages=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
    )


def generate_report(
    report_type: str,
    assessment_data: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    output_path: str,
):
    """Render one respondent's report to an explicit path.

    The caller supplies the full destination (from `campaign_store.report_path`)
    rather than a directory: the previous fixed `{report_type}_feedback_report.pdf`
    name meant concurrent respondents overwrote each other's PDFs, and a download
    could serve one person's report to another.
    """
    if not assessment_data:
        raise ValueError(f"No {report_type} assessment data available.")

    generator_class = EmployeeFeedbackGenerator if report_type == "employee" else OrganizationFeedbackGenerator
    generator = generator_class(assessment_data, metadata=metadata)
    feedback = generator.generate_feedback()
    summary = analyze_assessment(assessment_data, report_type=report_type)

    save_feedback_to_pdf(feedback, summary, REPORT_TITLES[report_type], output_path)
    return output_path, summary


def main():
    employee_data, employee_metadata = load_assessment_payload("src/data/employee_assessment.json")
    organization_data, organization_metadata = load_assessment_payload("src/data/organization_assessment.json")

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))
    os.makedirs(output_dir, exist_ok=True)

    # Legacy CLI path, kept for pre-campaign local files. The campaign-scoped
    # flow goes through server.py -> campaign_store.report_path().
    if employee_data:
        generate_report(
            "employee", employee_data, employee_metadata, os.path.join(output_dir, "employee_feedback_report.pdf")
        )
    else:
        print("Warning: No employee assessment data found.")

    if organization_data:
        generate_report(
            "organization",
            organization_data,
            organization_metadata,
            os.path.join(output_dir, "organization_feedback_report.pdf"),
        )
    else:
        print("Warning: No organization assessment data found.")


if __name__ == "__main__":
    main()
