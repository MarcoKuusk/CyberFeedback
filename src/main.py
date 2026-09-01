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

import campaign_store
from Feedback_Generators.combined_gap_feedback_generator import CombinedGapFeedbackGenerator
from Feedback_Generators.employee_feedback_generator import EmployeeFeedbackGenerator
from Feedback_Generators.org_aggregate_feedback_generator import OrgAggregateFeedbackGenerator
from Feedback_Generators.organization_feedback_generator import OrganizationFeedbackGenerator
from utils.report_analysis import (
    MATURITY_BANDS,
    MIN_AGGREGATE_N,
    aggregate_assessment,
    analyze_assessment,
    compare_tracks,
)


REPORT_TITLES = {
    "employee": "Employee Cyber Hygiene Report",
    "organization": "Organization Cyber Hygiene Report",
    "org_aggregate": "Team Human-Risk Report",
    "organization_rollup": "Organization Self-Assessment Report",
    "combined": "Stated Controls vs. Observed Behavior",
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
            # "Bullet" is already defined in ReportLab's default sample stylesheet,
            # so a custom name avoids a KeyError on add().
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


# --------------------------------------------------------------------------- #
# Org-level report layouts (Phase 2). These reuse the styles, page chrome, and
# section parsing above; only the tables differ. The per-person layout above is
# untouched.
# --------------------------------------------------------------------------- #
def _grid_table_style(header_row: bool = True) -> TableStyle:
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.75, REPORT_COLORS["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, REPORT_COLORS["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header_row:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), REPORT_COLORS["surface"]))
    return TableStyle(commands)


def _heading(elements: List[Any], text: str, styles) -> None:
    elements.append(Paragraph(text, styles["SectionHeading"]))
    elements.append(HRFlowable(width="100%", thickness=0.6, color=REPORT_COLORS["line"]))
    elements.append(Spacer(1, 6))


def _render_ai_body(elements: List[Any], sections: Dict[str, List[str]], styles) -> None:
    """Render remaining AI sections generically (Overview and empties skipped)."""
    for section_name, lines in sections.items():
        if section_name in {"Overview", "Overall Score Snapshot"} or not lines:
            continue
        _heading(elements, section_name, styles)
        for line in lines:
            if line.startswith("### "):
                elements.append(Paragraph(_clean_inline_markup(line[4:].strip()), styles["SubHeading"]))
            elif line.startswith("- "):
                elements.append(Paragraph(_clean_inline_markup(line), styles["ReportBullet"]))
            else:
                elements.append(Paragraph(_clean_inline_markup(line), styles["Body"]))
        elements.append(Spacer(1, 8))


def _pop_executive_summary(elements: List[Any], sections: Dict[str, List[str]], styles) -> None:
    executive_lines = sections.pop("Executive Summary", [])
    if executive_lines:
        _heading(elements, "Executive Summary", styles)
        elements.extend(Paragraph(_clean_inline_markup(line), styles["Body"]) for line in executive_lines)
        elements.append(Spacer(1, 8))


def _aggregate_metric_table(aggregate: Dict[str, Any], styles) -> Table:
    data = [
        [
            Paragraph("Respondents", styles["Muted"]),
            Paragraph("Mean score", styles["Muted"]),
            Paragraph("Maturity", styles["Muted"]),
        ],
        [
            Paragraph(str(aggregate["respondent_count"]), styles["MetricValue"]),
            Paragraph(f"{aggregate['mean_overall_score']:.1f}%", styles["MetricValue"]),
            Paragraph(aggregate["maturity_label"], styles["MetricValue"]),
        ],
    ]
    table = Table(data, colWidths=[1.7 * inch, 1.7 * inch, 2.9 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def _band_distribution_table(aggregate: Dict[str, Any], styles) -> Table:
    rows = [[Paragraph("Maturity band", styles["Muted"]), Paragraph("Respondents", styles["Muted"])]]
    for _threshold, label in MATURITY_BANDS:
        rows.append(
            [
                Paragraph(label, styles["Body"]),
                Paragraph(str(aggregate["band_distribution"].get(label, 0)), styles["Body"]),
            ]
        )
    table = Table(rows, colWidths=[3.8 * inch, 2.7 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def _gap_prevalence_table(aggregate: Dict[str, Any], styles) -> Table:
    rows = [
        [
            Paragraph("Category", styles["Muted"]),
            Paragraph("Team mean", styles["Muted"]),
            Paragraph("% needing attention", styles["Muted"]),
        ]
    ]
    for category, share in sorted(aggregate["gap_prevalence"].items(), key=lambda item: item[1], reverse=True):
        mean = aggregate["category_means"].get(category, 0.0)
        rows.append(
            [
                Paragraph(category, styles["Body"]),
                Paragraph(f"{mean:.1f}%", styles["Body"]),
                Paragraph(f"{share * 100:.0f}%", styles["Body"]),
            ]
        )
    table = Table(rows, colWidths=[3.5 * inch, 1.5 * inch, 1.5 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def save_aggregate_to_pdf(feedback_text: str, aggregate: Dict[str, Any], title: str, filename: str):
    styles = _build_styles()
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=44, leftMargin=44, topMargin=52, bottomMargin=40)
    elements: List[Any] = [Paragraph(title, styles["ReportTitle"])]

    if aggregate.get("suppressed"):
        # Never render a partial breakdown — one honest page and stop.
        elements.append(Paragraph("Aggregate withheld to protect respondent anonymity.", styles["Muted"]))
        elements.append(Spacer(1, 14))
        elements.append(
            Paragraph(
                f"This campaign has {aggregate.get('respondent_count', 0)} employee submission(s). A team-wide "
                f"breakdown is only produced once at least {aggregate.get('min_n', MIN_AGGREGATE_N)} employees have "
                "responded, so no individual can be identified from the aggregate. No per-category results were "
                "computed for this report.",
                styles["Body"],
            )
        )
        doc.build(
            elements,
            onFirstPage=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
            onLaterPages=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
        )
        return

    elements.append(
        Paragraph("Anonymized team-wide human-risk summary. No individual responses are identified.", styles["Muted"])
    )
    elements.append(Spacer(1, 10))
    elements.append(_aggregate_metric_table(aggregate, styles))
    elements.append(Spacer(1, 14))

    sections = _parse_ai_sections(feedback_text)
    _pop_executive_summary(elements, sections, styles)

    _heading(elements, "Maturity Distribution", styles)
    elements.append(_band_distribution_table(aggregate, styles))
    elements.append(Spacer(1, 10))

    _heading(elements, "Prevalent Gaps", styles)
    elements.append(_gap_prevalence_table(aggregate, styles))
    elements.append(Spacer(1, 10))

    _render_ai_body(elements, sections, styles)

    doc.build(
        elements,
        onFirstPage=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
        onLaterPages=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
    )


def _gap_pairs_table(comparison: Dict[str, Any], styles) -> Table:
    rows = [
        [
            Paragraph("Category", styles["Muted"]),
            Paragraph("Stated control", styles["Muted"]),
            Paragraph("Observed behavior", styles["Muted"]),
            Paragraph("Gap", styles["Muted"]),
        ]
    ]
    for pair in comparison["pairs"]:
        rows.append(
            [
                Paragraph(pair["control_category"], styles["Body"]),
                Paragraph(f"{pair['control_score']:.1f}%", styles["Body"]),
                Paragraph(f"{pair['behavior_score']:.1f}%", styles["Body"]),
                Paragraph(f"{pair['gap']:+.1f}", styles["Body"]),
            ]
        )
    table = Table(rows, colWidths=[2.7 * inch, 1.3 * inch, 1.4 * inch, 1.1 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def _control_scores_table(control_scores: Dict[str, float], styles) -> Table:
    rows = [[Paragraph("Control category", styles["Muted"]), Paragraph("Stated maturity", styles["Muted"])]]
    for category, score in sorted(control_scores.items(), key=lambda item: item[1]):
        rows.append([Paragraph(category, styles["Body"]), Paragraph(f"{score:.1f}%", styles["Body"])])
    table = Table(rows, colWidths=[4.5 * inch, 2.0 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def _control_only_table(control_only: List[Dict[str, Any]], styles) -> Table:
    rows = [[Paragraph("Control category", styles["Muted"]), Paragraph("Stated maturity", styles["Muted"])]]
    for item in control_only:
        rows.append([Paragraph(item["category"], styles["Body"]), Paragraph(f"{item['score']:.1f}%", styles["Body"])])
    table = Table(rows, colWidths=[4.5 * inch, 2.0 * inch], hAlign="LEFT")
    table.setStyle(_grid_table_style())
    return table


def save_gap_to_pdf(feedback_text: str, comparison: Dict[str, Any], title: str, filename: str):
    styles = _build_styles()
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=44, leftMargin=44, topMargin=52, bottomMargin=40)
    elements: List[Any] = [Paragraph(title, styles["ReportTitle"])]
    elements.append(
        Paragraph("Stated control maturity compared with anonymized, observed staff behavior.", styles["Muted"])
    )
    elements.append(Spacer(1, 10))

    sections = _parse_ai_sections(feedback_text)
    _pop_executive_summary(elements, sections, styles)

    if comparison.get("suppressed"):
        # Degraded: no behavior comparison, but still render the org self-assessment side.
        _heading(elements, "Comparison Unavailable", styles)
        elements.append(
            Paragraph(
                f"The employee aggregate is withheld because only {comparison.get('respondent_count', 0)} staff have "
                f"responded (minimum {comparison.get('min_n', MIN_AGGREGATE_N)} for anonymity). The organization's "
                "stated controls are shown below; the staff-behavior comparison will appear once enough employees "
                "participate.",
                styles["Body"],
            )
        )
        elements.append(Spacer(1, 10))
        _heading(elements, "Stated Controls", styles)
        elements.append(_control_scores_table(comparison.get("control_scores", {}), styles))
        elements.append(Spacer(1, 10))
    else:
        _heading(elements, "Stated Control vs. Observed Behavior", styles)
        elements.append(_gap_pairs_table(comparison, styles))
        elements.append(Spacer(1, 10))

    if comparison.get("control_only"):
        _heading(elements, "Controls Without Behavioral Signal", styles)
        elements.append(
            Paragraph(
                "These controls are stated by leadership but have no counterpart in the employee questionnaire, so the "
                "campaign collects no behavioral signal for them.",
                styles["Muted"],
            )
        )
        elements.append(Spacer(1, 4))
        elements.append(_control_only_table(comparison["control_only"], styles))
        elements.append(Spacer(1, 10))

    _render_ai_body(elements, sections, styles)

    doc.build(
        elements,
        onFirstPage=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
        onLaterPages=lambda canvas_obj, current_doc: _draw_page_chrome(canvas_obj, current_doc, title),
    )


def generate_report(report_type: str, assessment_data: List[Dict[str, Any]], metadata: Dict[str, Any], output_path: str):
    """Render the per-respondent PDF to an explicit, pre-validated output path.

    `output_path` is the full destination file path (supplied by
    campaign_store.report_path in the server flow). The parent directory is
    created if needed so callers don't have to pre-make the nested
    org/campaign/track folders.
    """
    if not assessment_data:
        raise ValueError(f"No {report_type} assessment data available.")

    generator_class = EmployeeFeedbackGenerator if report_type == "employee" else OrganizationFeedbackGenerator
    generator = generator_class(assessment_data, metadata=metadata)
    feedback = generator.generate_feedback()
    summary = analyze_assessment(assessment_data, report_type=report_type)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    save_feedback_to_pdf(feedback, summary, REPORT_TITLES[report_type], output_path)
    return output_path, summary


def _load_track_submissions(campaign_id: str, track: str) -> List[List[Dict[str, Any]]]:
    """Return each stored respondent's raw `responses` list for a track.

    All path building stays inside campaign_store's _safe_join guard — main.py
    never constructs a data path by hand. Metadata is deliberately dropped: only
    scored answers feed org-level output, never per-respondent metadata.
    """
    submissions: List[List[Dict[str, Any]]] = []
    for respondent_id in campaign_store.list_respondents(campaign_id, track):
        responses, _metadata = campaign_store.load_submission(campaign_id, track, respondent_id)
        submissions.append(responses)
    return submissions


def generate_org_report(mode: str, campaign_id: str, output_path: str):
    """Produce one org-level PDF (aggregate | organization | combined).

    Gathers inputs only through campaign_store, so path handling stays contained.
    Raises LookupError for an unknown campaign (-> 404), ValueError for a mode
    whose required track is absent or which has no data (-> 400). `output_path` is
    the pre-validated destination from campaign_store.org_report_path.
    """
    campaign = campaign_store.get_campaign(campaign_id)
    if campaign is None:
        raise LookupError("Campaign not found.")
    tracks = campaign.get("tracks", [])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if mode == "aggregate":
        if "employee" not in tracks:
            raise ValueError("This campaign has no employee track to aggregate.")
        aggregate = aggregate_assessment(_load_track_submissions(campaign_id, "employee"), report_type="employee")
        # Skip the OpenAI call entirely when suppressed — the PDF is a fixed page.
        feedback = "" if aggregate.get("suppressed") else OrgAggregateFeedbackGenerator(aggregate).generate_feedback()
        save_aggregate_to_pdf(feedback, aggregate, REPORT_TITLES["org_aggregate"], output_path)
        return output_path, aggregate

    if mode == "organization":
        if "organization" not in tracks:
            raise ValueError("This campaign has no organization track.")
        combined = [item for submission in _load_track_submissions(campaign_id, "organization") for item in submission]
        if not combined:
            raise ValueError("No organization submissions to report on.")
        summary = analyze_assessment(combined, report_type="organization")
        feedback = OrganizationFeedbackGenerator(combined, metadata={}).generate_feedback()
        save_feedback_to_pdf(feedback, summary, REPORT_TITLES["organization_rollup"], output_path)
        return output_path, summary

    if mode == "combined":
        if "employee" not in tracks or "organization" not in tracks:
            raise ValueError("A combined report requires both the employee and organization tracks.")
        aggregate = aggregate_assessment(_load_track_submissions(campaign_id, "employee"), report_type="employee")
        combined = [item for submission in _load_track_submissions(campaign_id, "organization") for item in submission]
        if not combined:
            raise ValueError("No organization submissions to report on.")
        org_summary = analyze_assessment(combined, report_type="organization")
        comparison = compare_tracks(aggregate, org_summary)
        feedback = CombinedGapFeedbackGenerator(comparison).generate_feedback()
        save_gap_to_pdf(feedback, comparison, REPORT_TITLES["combined"], output_path)
        return output_path, comparison

    raise ValueError("Invalid report mode.")


def main():
    employee_data, employee_metadata = load_assessment_payload("src/data/employee_assessment.json")
    organization_data, organization_metadata = load_assessment_payload("src/data/organization_assessment.json")

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "Generated_PDF_Report"))
    os.makedirs(output_dir, exist_ok=True)

    if employee_data:
        generate_report("employee", employee_data, employee_metadata, os.path.join(output_dir, "employee_feedback_report.pdf"))
    else:
        print("Warning: No employee assessment data found.")

    if organization_data:
        generate_report("organization", organization_data, organization_metadata, os.path.join(output_dir, "organization_feedback_report.pdf"))
    else:
        print("Warning: No organization assessment data found.")


if __name__ == "__main__":
    main()
