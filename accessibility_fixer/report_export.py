"""Export helpers for Accessibility Fixer analysis reports."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from accessibility_fixer.pdf_analyzer import AnalysisResult


def analysis_to_dict(result: AnalysisResult) -> dict:
    """Convert an AnalysisResult dataclass into a plain dictionary."""
    return asdict(result)


def analysis_to_json_bytes(result: AnalysisResult) -> bytes:
    """Serialize analysis output to pretty JSON bytes for download."""
    payload = analysis_to_dict(result)
    return json.dumps(payload, indent=2).encode("utf-8")


def page_details_to_csv_bytes(result: AnalysisResult) -> bytes:
    """Serialize page-level details to CSV bytes for download."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "page_number",
            "has_selectable_text",
            "has_images",
            "has_tables",
            "table_count",
            "form_field_count",
            "heading_signal_count",
            "ocr_suggestion",
            "repeated_image_hits",
        ]
    )

    for detail in result.page_details:
        writer.writerow(
            [
                detail.page_number,
                detail.has_selectable_text,
                detail.has_images,
                detail.has_tables,
                detail.table_count,
                detail.form_field_count,
                detail.heading_signal_count,
                detail.ocr_suggestion,
                detail.repeated_image_hits,
            ]
        )

    return output.getvalue().encode("utf-8")
