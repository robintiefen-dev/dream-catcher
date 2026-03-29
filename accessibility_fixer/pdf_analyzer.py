"""Simple PDF accessibility checks for the Accessibility Fixer MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import fitz  # PyMuPDF


@dataclass
class Issue:
    """Represents one accessibility warning in plain English."""

    title: str
    explanation: str


@dataclass
class PageDetail:
    """Represents simple accessibility signals for one page."""

    page_number: int
    has_selectable_text: bool
    has_images: bool
    heading_like_lines: int
    ocr_suggestion: str


@dataclass
class AnalysisResult:
    """Stores all analysis results for a PDF."""

    page_count: int
    pages_with_text: int
    pages_without_text: int
    pages_with_images: int
    likely_missing_alt_text_pages: int
    page_details: List[PageDetail] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    @property
    def summary_status(self) -> str:
        """Return a simple status string based on number of issues."""
        if not self.issues:
            return "Looks good (basic checks only)"
        if len(self.issues) <= 2:
            return "Needs attention"
        return "Needs significant accessibility improvements"


# Common heading-like words to look for in text blocks.
HEADING_KEYWORDS = ["introduction", "summary", "chapter", "section", "conclusion"]


def _count_heading_like_lines(page_text: str) -> int:
    """Count short lines that look like headings using simple keyword matching."""
    count = 0
    for line in page_text.splitlines():
        clean_line = line.strip().lower()
        if not clean_line:
            continue
        if len(clean_line) < 70 and any(word in clean_line for word in HEADING_KEYWORDS):
            count += 1
    return count


def _build_ocr_suggestion(has_text: bool, has_images: bool) -> str:
    """Return a short OCR recommendation for one page."""
    if has_text:
        return "No OCR needed (selectable text found)."
    if has_images:
        return "Run OCR on this page and verify reading order + text accuracy."
    return "No text detected. Check if this page is blank/decorative or run OCR if needed."


def analyze_pdf(pdf_bytes: bytes) -> AnalysisResult:
    """Run beginner-friendly first-pass accessibility checks on a PDF.

    Raises:
        ValueError: If the uploaded file is not a readable PDF.
    """
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # Keep this broad to return a user-friendly message.
        raise ValueError("Could not read this file as a valid PDF.") from exc

    page_count = document.page_count
    pages_with_text = 0
    pages_with_images = 0
    total_heading_like_lines = 0
    likely_missing_alt_text_pages = 0
    page_details: List[PageDetail] = []

    for page_index, page in enumerate(document):
        text = page.get_text("text").strip()
        has_text = bool(text)
        if has_text:
            pages_with_text += 1

        heading_like_lines = _count_heading_like_lines(text)
        total_heading_like_lines += heading_like_lines

        images = page.get_images(full=True)
        has_images = bool(images)
        if has_images:
            pages_with_images += 1

        # Simple alt-text warning signal:
        # if a page has images but no selectable text, image descriptions are likely missing or inaccessible.
        if has_images and not has_text:
            likely_missing_alt_text_pages += 1

        page_details.append(
            PageDetail(
                page_number=page_index + 1,
                has_selectable_text=has_text,
                has_images=has_images,
                heading_like_lines=heading_like_lines,
                ocr_suggestion=_build_ocr_suggestion(has_text=has_text, has_images=has_images),
            )
        )

    pages_without_text = page_count - pages_with_text

    issues: List[Issue] = []

    if pages_without_text == page_count:
        issues.append(
            Issue(
                title="No selectable text detected",
                explanation=(
                    "This PDF appears to be image-only (like a scan). "
                    "Screen readers may not be able to read it unless OCR is added."
                ),
            )
        )
    elif pages_without_text > 0:
        issues.append(
            Issue(
                title="Some pages have no selectable text",
                explanation=(
                    f"{pages_without_text} page(s) may be scanned images or contain text "
                    "that assistive technology cannot easily read."
                ),
            )
        )

    if pages_without_text > 0:
        issues.append(
            Issue(
                title="OCR recommended",
                explanation=(
                    "At least one page has no selectable text. "
                    "Run OCR on those pages and verify reading order and accuracy."
                ),
            )
        )

    if pages_with_images > 0:
        issues.append(
            Issue(
                title="Images found (review alt text manually)",
                explanation=(
                    "Images were detected. This MVP cannot reliably read PDF alt text metadata yet, "
                    "so image descriptions should be manually reviewed."
                ),
            )
        )

    if likely_missing_alt_text_pages > 0:
        issues.append(
            Issue(
                title="Likely missing image descriptions on some pages",
                explanation=(
                    f"{likely_missing_alt_text_pages} page(s) include images but no selectable text. "
                    "These pages are at higher risk for inaccessible visual-only content."
                ),
            )
        )

    if total_heading_like_lines == 0 and pages_with_text > 0:
        issues.append(
            Issue(
                title="Weak or missing heading structure",
                explanation=(
                    "No obvious heading-like lines were detected. "
                    "Using clear headings helps screen reader navigation."
                ),
            )
        )

    if page_count > 15:
        issues.append(
            Issue(
                title="Long document readability warning",
                explanation=(
                    "Long PDFs are harder to navigate without strong structure. "
                    "Consider adding clear headings, bookmarks, and short sections."
                ),
            )
        )

    document.close()

    return AnalysisResult(
        page_count=page_count,
        pages_with_text=pages_with_text,
        pages_without_text=pages_without_text,
        pages_with_images=pages_with_images,
        likely_missing_alt_text_pages=likely_missing_alt_text_pages,
        page_details=page_details,
        issues=issues,
    )
