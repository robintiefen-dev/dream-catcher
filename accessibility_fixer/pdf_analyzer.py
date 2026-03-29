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
    has_tables: bool
    table_count: int
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
    pages_with_tables: int
    total_tables: int
    table_header_warning_count: int
    likely_missing_alt_text_pages: int
    repeated_image_groups: int
    pages_with_repeated_images: int
    bookmark_count: int
    has_bookmarks: bool
    heading_levels_detected: int
    heading_hierarchy_jumps: int
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
    spans: list[dict] = []
    page_dict = page.get_text("dict")

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    spans.append(span)

    return spans


def _heading_candidate_sizes(page: fitz.Page) -> list[float]:
    spans = _extract_text_spans(page)
    if not spans:
        return []

    sizes = [float(span.get("size", 0) or 0) for span in spans if float(span.get("size", 0) or 0) > 0]
    if not sizes:
        return []

    body_size = median(sizes)
    candidates: list[float] = []

    for span in spans:
        text = span.get("text", "").strip()
        font_name = str(span.get("font", "")).lower()
        font_size = float(span.get("size", 0) or 0)

        short_enough = len(text) <= 120
        is_bold = "bold" in font_name
        is_larger = font_size >= body_size * 1.2

        if short_enough and (is_bold or is_larger):
            candidates.append(font_size)

    return candidates


def _infer_heading_levels_and_jumps(heading_sizes: list[float]) -> tuple[int, int]:
    if not heading_sizes:
        return 0, 0

    unique_sizes_desc = sorted({round(size, 1) for size in heading_sizes}, reverse=True)

    size_bands: list[float] = []
    for size in unique_sizes_desc:
        if not size_bands or abs(size - size_bands[-1]) > 0.7:
            size_bands.append(size)

    def nearest_band_level(size: float) -> int:
        best_band_index = min(range(len(size_bands)), key=lambda i: abs(size - size_bands[i]))
        return best_band_index + 1

    levels = [nearest_band_level(size) for size in heading_sizes]
    heading_levels_detected = len(set(levels))

    hierarchy_jumps = 0
    for previous, current in zip(levels, levels[1:]):
        if current - previous > 1:
            hierarchy_jumps += 1

    return heading_levels_detected, hierarchy_jumps


def _build_ocr_suggestion(has_text: bool, has_images: bool) -> str:
    if has_text:
        return "No OCR needed (selectable text found)."
    if has_images:
        return "Run OCR on this page and verify reading order + text accuracy."
    return "No text detected. Check if this page is blank/decorative or run OCR if needed."


def _image_hashes_for_page(document: fitz.Document, page: fitz.Page) -> list[str]:
    hashes: list[str] = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        try:
            image_data = document.extract_image(xref)
        except Exception:
            continue

        raw_bytes = image_data.get("image")
        if not raw_bytes:
            continue

        hashes.append(hashlib.sha1(raw_bytes).hexdigest())

    return hashes


def _detect_tables(page: fitz.Page) -> tuple[int, int]:
    """Return (table_count, header_warning_count) for a page.

    Header warning heuristic:
    - first row exists but has mostly empty cells (likely missing clear headers)
    """
    if not hasattr(page, "find_tables"):
        return 0, 0

    try:
        tables_result = page.find_tables()
    except Exception:
        return 0, 0

    tables = tables_result.tables if tables_result else []
    table_count = len(tables)
    header_warning_count = 0

    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            continue

        if not rows:
            continue

        first_row = rows[0]
        if not first_row:
            continue

        empty_cells = sum(1 for cell in first_row if not str(cell or "").strip())
        if empty_cells >= max(1, len(first_row) // 2):
            header_warning_count += 1

    return table_count, header_warning_count


def analyze_pdf(pdf_bytes: bytes) -> AnalysisResult:
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("Could not read this file as a valid PDF.") from exc

    page_count = document.page_count
    pages_with_text = 0
    pages_with_images = 0
    pages_with_tables = 0
    total_tables = 0
    table_header_warning_count = 0
    total_heading_signals = 0
    likely_missing_alt_text_pages = 0

    toc = document.get_toc(simple=True)
    bookmark_count = len(toc)
    has_bookmarks = bookmark_count > 0

    page_summaries: list[dict] = []
    image_occurrence_counts: dict[str, int] = {}
    document_heading_sizes: list[float] = []

    for page_index, page in enumerate(document):
        text = page.get_text("text").strip()
        has_text = bool(text)
        if has_text:
            pages_with_text += 1

        heading_sizes = _heading_candidate_sizes(page)
        heading_signal_count = len(heading_sizes)
        total_heading_signals += heading_signal_count
        document_heading_sizes.extend(heading_sizes)

        image_hashes = _image_hashes_for_page(document, page)
        has_images = bool(image_hashes)
        if has_images:
            pages_with_images += 1

        table_count, header_warnings = _detect_tables(page)
        has_tables = table_count > 0
        if has_tables:
            pages_with_tables += 1
        total_tables += table_count
        table_header_warning_count += header_warnings

        if has_images and not has_text:
            likely_missing_alt_text_pages += 1

        for image_hash in set(image_hashes):
            image_occurrence_counts[image_hash] = image_occurrence_counts.get(image_hash, 0) + 1

        page_summaries.append(
            {
                "page_number": page_index + 1,
                "has_selectable_text": has_text,
                "has_images": has_images,
                "has_tables": has_tables,
                "table_count": table_count,
                "heading_signal_count": heading_signal_count,
                "ocr_suggestion": _build_ocr_suggestion(has_text=has_text, has_images=has_images),
                "image_hashes": image_hashes,
            }
        )

    repeated_hashes = {h for h, count in image_occurrence_counts.items() if count >= 3}
    heading_levels_detected, heading_hierarchy_jumps = _infer_heading_levels_and_jumps(document_heading_sizes)

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
                has_tables=summary["has_tables"],
                table_count=summary["table_count"],
                heading_signal_count=summary["heading_signal_count"],
                ocr_suggestion=summary["ocr_suggestion"],
                repeated_image_hits=repeated_hits,
            )
        )

    pages_without_text = page_count - pages_with_text
    issues: List[Issue] = []

    if pages_without_text == page_count:
        issues.append(Issue("No selectable text detected", "This PDF appears to be image-only (like a scan). Screen readers may not be able to read it unless OCR is added."))
    elif pages_without_text > 0:
        issues.append(Issue("Some pages have no selectable text", f"{pages_without_text} page(s) may be scanned images or contain text that assistive technology cannot easily read."))

    if pages_without_text > 0:
        issues.append(Issue("OCR recommended", "At least one page has no selectable text. Run OCR on those pages and verify reading order and accuracy."))

    if pages_with_images > 0:
        issues.append(Issue("Images found (review alt text manually)", "Images were detected. This MVP cannot reliably read PDF alt text metadata yet, so image descriptions should be manually reviewed."))

    if likely_missing_alt_text_pages > 0:
        issues.append(Issue("Likely missing image descriptions on some pages", f"{likely_missing_alt_text_pages} page(s) include images but no selectable text. These pages are at higher risk for inaccessible visual-only content."))

    if total_tables > 0:
        issues.append(Issue("Tables detected (manual structure check recommended)", f"Detected {total_tables} table(s) across {pages_with_tables} page(s). Verify header rows, reading order, and merged-cell clarity."))

    if table_header_warning_count > 0:
        issues.append(Issue("Possible missing table headers", f"{table_header_warning_count} table(s) may have weak/missing header rows based on empty top-row cells."))

    if len(repeated_hashes) > 0:
        issues.append(Issue("Repeated images/logos detected", f"Detected {len(repeated_hashes)} repeated image pattern(s) across {pages_with_repeated_images} page(s). These may be decorative logos or icons."))

    if total_heading_signals == 0 and pages_with_text > 0:
        issues.append(Issue("Weak or missing heading structure", "No heading signals were detected from font size/style cues. Using clear heading styles helps screen reader navigation."))

    if heading_hierarchy_jumps > 0:
        issues.append(Issue("Heading hierarchy depth warning", f"Detected {heading_hierarchy_jumps} heading level jump(s) (for example H1 to H3). Try using a consistent hierarchy like H1 → H2 → H3."))

    if page_count >= 8 and not has_bookmarks:
        issues.append(Issue("Missing bookmark navigation", "This document has enough pages that bookmarks would help navigation. Consider adding bookmarks that match major section headings."))
    elif bookmark_count > 0 and page_count >= 8 and bookmark_count < 3:
        issues.append(Issue("Limited bookmark navigation", f"Only {bookmark_count} bookmark(s) were found. Consider adding more bookmarks for major sections to improve navigation."))

    if page_count > 15:
        issues.append(Issue("Long document readability warning", "Long PDFs are harder to navigate without strong structure. Consider adding clear headings, bookmarks, and short sections."))

    document.close()

    return AnalysisResult(
        page_count=page_count,
        pages_with_text=pages_with_text,
        pages_without_text=pages_without_text,
        pages_with_images=pages_with_images,
        pages_with_tables=pages_with_tables,
        total_tables=total_tables,
        table_header_warning_count=table_header_warning_count,
        likely_missing_alt_text_pages=likely_missing_alt_text_pages,
        repeated_image_groups=len(repeated_hashes),
        pages_with_repeated_images=pages_with_repeated_images,
        bookmark_count=bookmark_count,
        has_bookmarks=has_bookmarks,
        heading_levels_detected=heading_levels_detected,
        heading_hierarchy_jumps=heading_hierarchy_jumps,
        page_details=page_details,
        issues=issues,
    )
