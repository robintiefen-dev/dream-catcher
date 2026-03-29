"""Simple PDF accessibility checks for the Accessibility Fixer MVP."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from statistics import median
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
    heading_signal_count: int
    ocr_suggestion: str
    repeated_image_hits: int


@dataclass
class AnalysisResult:
    """Stores all analysis results for a PDF."""

    page_count: int
    pages_with_text: int
    pages_without_text: int
    pages_with_images: int
    likely_missing_alt_text_pages: int
    repeated_image_groups: int
    pages_with_repeated_images: int
    bookmark_count: int
    has_bookmarks: bool
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


def _extract_text_spans(page: fitz.Page) -> list[dict]:
    """Return all text spans from a page dictionary output."""
    spans: list[dict] = []
    page_dict = page.get_text("dict")

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # type 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                spans.append(span)

    return spans


def _count_heading_signals(page: fitz.Page) -> int:
    """Estimate heading count from font size/style cues."""
    spans = _extract_text_spans(page)
    if not spans:
        return 0

    sizes = [span.get("size", 0) for span in spans if span.get("size", 0) > 0]
    if not sizes:
        return 0

    body_size = median(sizes)
    heading_count = 0

    for span in spans:
        text = span.get("text", "").strip()
        font_name = str(span.get("font", "")).lower()
        font_size = float(span.get("size", 0) or 0)

        short_enough = len(text) <= 120
        is_bold = "bold" in font_name
        is_larger = font_size >= body_size * 1.2

        if short_enough and (is_bold or is_larger):
            heading_count += 1

    return heading_count


def _build_ocr_suggestion(has_text: bool, has_images: bool) -> str:
    """Return a short OCR recommendation for one page."""
    if has_text:
        return "No OCR needed (selectable text found)."
    if has_images:
        return "Run OCR on this page and verify reading order + text accuracy."
    return "No text detected. Check if this page is blank/decorative or run OCR if needed."


def _image_hashes_for_page(document: fitz.Document, page: fitz.Page) -> list[str]:
    """Return content hashes for images on a page."""
    hashes: list[str] = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        try:
            image_data = document.extract_image(xref)
        except Exception:
            # Skip unreadable image objects.
            continue

        raw_bytes = image_data.get("image")
        if not raw_bytes:
            continue

        digest = hashlib.sha1(raw_bytes).hexdigest()
        hashes.append(digest)

    return hashes


def analyze_pdf(pdf_bytes: bytes) -> AnalysisResult:
    """Run beginner-friendly first-pass accessibility checks on a PDF.

    Raises:
        ValueError: If the uploaded file is not a readable PDF.
    """
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("Could not read this file as a valid PDF.") from exc

    page_count = document.page_count
    pages_with_text = 0
    pages_with_images = 0
    total_heading_signals = 0
    likely_missing_alt_text_pages = 0

    toc = document.get_toc(simple=True)
    bookmark_count = len(toc)
    has_bookmarks = bookmark_count > 0

    # Temporary data so we can calculate repeated-image signals after scanning all pages.
    page_summaries: list[dict] = []
    image_occurrence_counts: dict[str, int] = {}

    for page_index, page in enumerate(document):
        text = page.get_text("text").strip()
        has_text = bool(text)
        if has_text:
            pages_with_text += 1

        heading_signal_count = _count_heading_signals(page)
        total_heading_signals += heading_signal_count

        image_hashes = _image_hashes_for_page(document, page)
        has_images = bool(image_hashes)
        if has_images:
            pages_with_images += 1

        if has_images and not has_text:
            likely_missing_alt_text_pages += 1

        for image_hash in set(image_hashes):
            image_occurrence_counts[image_hash] = image_occurrence_counts.get(image_hash, 0) + 1

        page_summaries.append(
            {
                "page_number": page_index + 1,
                "has_selectable_text": has_text,
                "has_images": has_images,
                "heading_signal_count": heading_signal_count,
                "ocr_suggestion": _build_ocr_suggestion(has_text=has_text, has_images=has_images),
                "image_hashes": image_hashes,
            }
        )

    # Treat images seen on 3+ pages as repeated/logo-like decorative candidates.
    repeated_hashes = {h for h, count in image_occurrence_counts.items() if count >= 3}

    page_details: List[PageDetail] = []
    pages_with_repeated_images = 0
    for summary in page_summaries:
        repeated_hits = sum(1 for h in set(summary["image_hashes"]) if h in repeated_hashes)
        if repeated_hits > 0:
            pages_with_repeated_images += 1

        page_details.append(
            PageDetail(
                page_number=summary["page_number"],
                has_selectable_text=summary["has_selectable_text"],
                has_images=summary["has_images"],
                heading_signal_count=summary["heading_signal_count"],
                ocr_suggestion=summary["ocr_suggestion"],
                repeated_image_hits=repeated_hits,
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

    if len(repeated_hashes) > 0:
        issues.append(
            Issue(
                title="Repeated images/logos detected",
                explanation=(
                    f"Detected {len(repeated_hashes)} repeated image pattern(s) across "
                    f"{pages_with_repeated_images} page(s). These may be decorative logos or icons."
                ),
            )
        )

    if total_heading_signals == 0 and pages_with_text > 0:
        issues.append(
            Issue(
                title="Weak or missing heading structure",
                explanation=(
                    "No heading signals were detected from font size/style cues. "
                    "Using clear heading styles helps screen reader navigation."
                ),
            )
        )

    if page_count >= 8 and not has_bookmarks:
        issues.append(
            Issue(
                title="Missing bookmark navigation",
                explanation=(
                    "This document has enough pages that bookmarks would help navigation. "
                    "Consider adding bookmarks that match major section headings."
                ),
            )
        )
    elif bookmark_count > 0 and page_count >= 8 and bookmark_count < 3:
        issues.append(
            Issue(
                title="Limited bookmark navigation",
                explanation=(
                    f"Only {bookmark_count} bookmark(s) were found. "
                    "Consider adding more bookmarks for major sections to improve navigation."
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
        repeated_image_groups=len(repeated_hashes),
        pages_with_repeated_images=pages_with_repeated_images,
        bookmark_count=bookmark_count,
        has_bookmarks=has_bookmarks,
        page_details=page_details,
        issues=issues,
    )
