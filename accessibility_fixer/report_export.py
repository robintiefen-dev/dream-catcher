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
            "low_contrast_hint_count",
            "reading_order_warning_count",
            "missing_caption_hint_count",
            "link_count",
            "unclear_link_purpose_count",
            "destination_warning_count",
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
                detail.low_contrast_hint_count,
                detail.reading_order_warning_count,
                detail.missing_caption_hint_count,
                detail.link_count,
                detail.unclear_link_purpose_count,
                detail.destination_warning_count,
            ]
        )

    return output.getvalue().encode("utf-8")


def link_validation_to_csv_bytes(result: AnalysisResult) -> bytes:
    """Serialize live link validation rows to CSV bytes for audit workflows."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "page_number",
            "url",
            "method",
            "status_code",
            "error",
            "passed",
            "skipped_by_policy",
            "attempt_count",
            "checked_at_utc",
        ]
    )

    for row in result.link_validation_results:
        writer.writerow(
            [
                row.page_number,
                row.url,
                row.method,
                row.status_code if row.status_code is not None else "",
                row.error,
                row.passed,
                row.skipped_by_policy,
                row.attempt_count,
                row.checked_at_utc,
            ]
        )

    return output.getvalue().encode("utf-8")
