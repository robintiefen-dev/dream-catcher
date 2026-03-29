"""Helpers to create a basic remediated PDF output.

This module intentionally keeps remediation simple for MVP/learning purposes.
"""

from __future__ import annotations

from datetime import datetime

import fitz  # PyMuPDF

from accessibility_fixer.pdf_analyzer import AnalysisResult


def _build_notes_text(result: AnalysisResult) -> str:
    """Create plain-English remediation notes to append into the PDF."""
    lines = [
        "Accessibility Fixer - Remediation Notes",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Summary status: {result.summary_status}",
        "",
        "What this remediated copy includes:",
        "- Basic metadata defaults (Title/Subject/Keywords).",
        "- This notes page with next-step accessibility actions.",
        "",
        "Suggested fixes:",
    ]

    if not result.issues:
        lines.append("- No major issues found by basic checks.")
    else:
        for issue in result.issues:
            lines.append(f"- {issue.title}: {issue.explanation}")

    lines.extend(
        [
            "",
            "OCR suggestions by page:",
        ]
    )
    for detail in result.page_details:
        lines.append(f"- Page {detail.page_number}: {detail.ocr_suggestion}")

    lines.extend(
        [
            "",
            "Important:",
            "This is not full PDF/UA remediation.",
            "Manual tagging, reading order, and verified alt text are still needed.",
        ]
    )

    return "\n".join(lines)


def build_remediated_pdf(pdf_bytes: bytes, result: AnalysisResult) -> bytes:
    """Return a new PDF copy with basic metadata + remediation notes page.

    The original pages are kept as-is. This is an MVP helper, not a full accessibility fixer.
    """
    document = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Add or update simple metadata fields.
    metadata = document.metadata or {}
    metadata["title"] = metadata.get("title") or "Remediated PDF (Accessibility Fixer MVP)"
    metadata["subject"] = "Accessibility remediation draft"
    metadata["keywords"] = "accessibility, pdf, remediation, mvp"
    document.set_metadata(metadata)

    # Append one notes page at the end.
    notes_page = document.new_page(-1)
    notes = _build_notes_text(result)
    notes_page.insert_textbox(
        fitz.Rect(50, 50, 545, 792 - 50),
        notes,
        fontsize=11,
        fontname="helv",
        lineheight=1.3,
    )

    output_bytes = document.tobytes(garbage=3, deflate=True)
    document.close()
    return output_bytes
