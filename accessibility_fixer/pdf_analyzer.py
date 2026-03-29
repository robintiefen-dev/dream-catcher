"""Simple PDF accessibility checks for the Accessibility Fixer MVP."""

from __future__ import annotations

import hashlib
import time
from fnmatch import fnmatch
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from dataclasses import dataclass, field
from statistics import median
from typing import List

import fitz  # PyMuPDF


@dataclass
class Issue:
    title: str
    explanation: str


@dataclass
class LinkValidationResult:
    page_number: int
    url: str
    method: str
    status_code: int | None
    error: str
    passed: bool
    skipped_by_policy: bool
    attempt_count: int
    checked_at_utc: str


@dataclass
class PageDetail:
    page_number: int
    has_selectable_text: bool
    has_images: bool
    has_tables: bool
    table_count: int
    form_field_count: int
    heading_signal_count: int
    ocr_suggestion: str
    repeated_image_hits: int
    low_contrast_hint_count: int
    reading_order_warning_count: int
    missing_caption_hint_count: int
    link_count: int
    unclear_link_purpose_count: int
    destination_warning_count: int


@dataclass
class AnalysisResult:
    page_count: int
    pages_with_text: int
    pages_without_text: int
    pages_with_images: int
    pages_with_tables: int
    total_tables: int
    table_header_warning_count: int
    pages_with_form_fields: int
    total_form_fields: int
    unlabeled_form_field_count: int
    likely_missing_alt_text_pages: int
    repeated_image_groups: int
    pages_with_repeated_images: int
    bookmark_count: int
    has_bookmarks: bool
    heading_levels_detected: int
    heading_hierarchy_jumps: int
    has_language_metadata: bool
    metadata_language: str
    pages_with_low_contrast_text: int
    low_contrast_span_count: int
    pages_with_reading_order_warnings: int
    reading_order_warning_count: int
    images_without_caption_hints: int
    pages_with_caption_warnings: int
    total_links: int
    unclear_link_purpose_count: int
    pages_with_link_purpose_warnings: int
    link_destination_warning_count: int
    pages_with_link_destination_warnings: int
    live_link_validation_enabled: bool
    live_links_checked: int
    live_link_failures: int
    live_links_skipped_by_policy: int
    link_validation_results: List[LinkValidationResult] = field(default_factory=list)
    page_details: List[PageDetail] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    @property
    def summary_status(self) -> str:
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

        if len(text) <= 120 and (("bold" in font_name) or font_size >= body_size * 1.2):
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
    hierarchy_jumps = sum(1 for previous, current in zip(levels, levels[1:]) if current - previous > 1)
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
        if raw_bytes:
            hashes.append(hashlib.sha1(raw_bytes).hexdigest())
    return hashes


def _detect_tables(page: fitz.Page) -> tuple[int, int]:
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


def _detect_form_fields(page: fitz.Page) -> tuple[int, int]:
    """Return (form_field_count, unlabeled_form_field_count) for a page."""
    try:
        widgets = list(page.widgets() or [])
    except Exception:
        return 0, 0

    total_fields = len(widgets)
    unlabeled = 0
    for widget in widgets:
        field_name = str(getattr(widget, "field_name", "") or "").strip()
        field_label = str(getattr(widget, "field_label", "") or "").strip()
        if not field_name and not field_label:
            unlabeled += 1

    return total_fields, unlabeled




def _color_int_to_rgb(color_value: int) -> tuple[int, int, int]:
    """Convert PyMuPDF text color int to RGB tuple."""
    red = (color_value >> 16) & 255
    green = (color_value >> 8) & 255
    blue = color_value & 255
    return red, green, blue


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Calculate WCAG relative luminance for an RGB color."""
    def channel(value: int) -> float:
        c = value / 255
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _count_low_contrast_spans(page: fitz.Page) -> int:
    """Count text spans that may have weak contrast against white background.

    Heuristic: contrast ratio against white < 4.5:1.
    """
    low_contrast = 0
    spans = _extract_text_spans(page)
    for span in spans:
        color_value = int(span.get("color", 0) or 0)
        rgb = _color_int_to_rgb(color_value)
        luminance = _relative_luminance(rgb)

        # White background luminance is 1.0
        contrast_ratio = (1.0 + 0.05) / (luminance + 0.05)
        if contrast_ratio < 4.5:
            low_contrast += 1

    return low_contrast



def _count_reading_order_warnings(page: fitz.Page) -> int:
    """Estimate reading-order region issues from text block geometry.

    Heuristics:
    - y-position backward jumps larger than 40 points
    - extraction order differs a lot from rough top-to-bottom then left-to-right order
    """
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return 0

    text_blocks = [b for b in blocks if len(b) >= 5 and str(b[4]).strip()]
    if len(text_blocks) < 3:
        return 0

    backward_jumps = 0
    previous_y = text_blocks[0][1]
    for block in text_blocks[1:]:
        y0 = block[1]
        if y0 < previous_y - 40:
            backward_jumps += 1
        previous_y = y0

    sorted_indices = sorted(
        range(len(text_blocks)),
        key=lambda i: (round(text_blocks[i][1] / 20), text_blocks[i][0]),
    )
    mismatch_count = sum(1 for idx, sorted_idx in enumerate(sorted_indices) if idx != sorted_idx)

    warning_count = backward_jumps
    if mismatch_count >= 3:
        warning_count += 1

    return warning_count




def _count_image_caption_warnings(page: fitz.Page) -> int:
    """Count images that do not have nearby caption-like text blocks."""
    try:
        block_data = page.get_text("blocks")
    except Exception:
        return 0

    text_blocks = []
    for block in block_data:
        if len(block) < 5:
            continue
        text = str(block[4] or "").strip()
        if not text:
            continue
        rect = fitz.Rect(block[0], block[1], block[2], block[3])
        text_blocks.append((rect, text))

    caption_warnings = 0
    for image_info in page.get_images(full=True):
        xref = image_info[0]
        try:
            image_rects = page.get_image_rects(xref)
        except Exception:
            image_rects = []

        for image_rect in image_rects:
            has_caption_hint = False
            for text_rect, text in text_blocks:
                vertical_gap = text_rect.y0 - image_rect.y1
                close_below = 0 <= vertical_gap <= 70
                overlapping_side = abs(text_rect.x0 - image_rect.x0) <= 120

                caption_like = text.lower().startswith(("figure", "fig.", "fig ", "image", "photo"))
                short_line = len(text) <= 140

                if close_below and overlapping_side and (caption_like or short_line):
                    has_caption_hint = True
                    break

            if not has_caption_hint:
                caption_warnings += 1

    return caption_warnings


def _assess_link_annotation_purpose(page: fitz.Page) -> tuple[int, int, int]:
    """Return (total_links, unclear_link_purpose_count, destination_warning_count) for a page.

    Heuristics for unclear purpose:
    - no nearby text captured in/near the link rectangle
    - generic anchor text (for example "click here")
    - raw URL shown as anchor text
    - weak anchor text with no meaningful nearby label/context
    """
    try:
        links = list(page.get_links() or [])
    except Exception:
        return 0, 0, 0

    if not links:
        return 0, 0, 0

    try:
        words = page.get_text("words")
    except Exception:
        words = []
    try:
        text_blocks = page.get_text("blocks")
    except Exception:
        text_blocks = []

    generic_labels = {
        "click here",
        "here",
        "read more",
        "more",
        "link",
        "this link",
        "learn more",
    }

    block_text_regions: list[tuple[fitz.Rect, str]] = []
    for block in text_blocks:
        if len(block) < 5:
            continue
        text = str(block[4] or "").strip()
        if not text:
            continue
        block_text_regions.append((fitz.Rect(block[0], block[1], block[2], block[3]), text))

    def normalize(text: str) -> str:
        compact = " ".join(text.split()).strip().lower()
        return compact.strip("()[]{}<>:;,.!?\"'")

    def collect_anchor_text(link_rect: fitz.Rect) -> str:
        """Capture anchor text for single-line and multi-line link rectangles."""
        # Give link text a little breathing room so wrapped/multi-line text still intersects.
        capture_rect = fitz.Rect(link_rect.x0 - 3, link_rect.y0 - 4, link_rect.x1 + 3, link_rect.y1 + 8)
        near_words = [w for w in words if fitz.Rect(w[:4]).intersects(capture_rect)]
        near_words.sort(key=lambda w: (round(w[1], 1), w[0]))
        return " ".join(str(w[4]).strip() for w in near_words if str(w[4]).strip())

    def collect_nearby_label_text(link_rect: fitz.Rect) -> str:
        """Capture nearby label/context text above the link when anchor text is weak."""
        label_candidates: list[str] = []
        for region_rect, region_text in block_text_regions:
            vertical_gap_above = link_rect.y0 - region_rect.y1
            horizontal_overlap = min(link_rect.x1, region_rect.x1) - max(link_rect.x0, region_rect.x0)
            # Prioritize lines directly above or slightly left-aligned labels near the link.
            if -8 <= vertical_gap_above <= 90 and horizontal_overlap >= -40:
                label_candidates.append(region_text)
        if not label_candidates:
            return ""
        label_candidates.sort(key=lambda text: len(text))
        return " ".join(label_candidates[:2])

    unclear_count = 0
    destination_warning_count = 0
    for link in links:
        link_rect = link.get("from")
        if link_rect is None:
            unclear_count += 1
            continue

        rect = fitz.Rect(link_rect)
        anchor_text = collect_anchor_text(rect)
        nearby_label = collect_nearby_label_text(rect)
        combined_context = " ".join(part for part in [anchor_text, nearby_label] if part).strip()

        if not combined_context:
            unclear_count += 1
            continue

        anchor_text = " ".join(anchor_text.split())
        normalized_anchor = normalize(anchor_text)
        normalized_context = normalize(combined_context)
        context_word_count = len([w for w in normalized_context.split() if w])

        if (
            len(anchor_text) < 3
            or normalized_anchor in generic_labels
            or normalized_anchor.startswith(("http://", "https://", "www."))
            or (normalized_anchor in {"here", "more", "this"} and context_word_count <= 3)
        ):
            unclear_count += 1

        kind = int(link.get("kind", 0) or 0)
        uri = str(link.get("uri", "") or "").strip()
        if kind == fitz.LINK_URI:
            if not uri:
                destination_warning_count += 1
                continue
            parsed = urlparse(uri)
            scheme = parsed.scheme.lower()
            host = parsed.netloc.lower()
            if scheme not in {"http", "https", "mailto", "tel"}:
                destination_warning_count += 1
                continue
            if scheme in {"http", "https"}:
                if not host:
                    destination_warning_count += 1
                    continue
                if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith((".local", ".internal")):
                    destination_warning_count += 1

    return len(links), unclear_count, destination_warning_count


def _extract_external_http_uris(page: fitz.Page, page_number: int) -> list[tuple[int, str]]:
    """Extract (page_number, external HTTP(S) URI) rows from page link annotations."""
    try:
        links = list(page.get_links() or [])
    except Exception:
        return []

    uris: list[tuple[int, str]] = []
    for link in links:
        if int(link.get("kind", 0) or 0) != fitz.LINK_URI:
            continue
        uri = str(link.get("uri", "") or "").strip()
        if not uri:
            continue
        parsed = urlparse(uri)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            uris.append((page_number, uri))
    return uris


def _validate_external_links(
    uri_rows: list[tuple[int, str]],
    timeout_seconds: float = 3.0,
    max_checks: int = 30,
    max_retries: int = 1,
    backoff_seconds: float = 0.5,
    allowlist_patterns: list[str] | None = None,
    denylist_patterns: list[str] | None = None,
) -> tuple[int, int, int, list[LinkValidationResult]]:
    """Return (checked_count, failure_count, skipped_by_policy_count, result_rows) using HTTP HEAD checks.

    Optional best-effort validator for externally reachable HTTP(S) URLs.
    """
    checked = 0
    failures = 0
    skipped_by_policy = 0
    result_rows: list[LinkValidationResult] = []
    per_url_cache: dict[str, LinkValidationResult] = {}
    allowlist = [p.strip() for p in (allowlist_patterns or []) if p.strip()]
    denylist = [p.strip() for p in (denylist_patterns or []) if p.strip()]

    def matches_any_pattern(target: str, patterns: list[str]) -> bool:
        return any(fnmatch(target, pattern) for pattern in patterns)

    for page_number, uri in uri_rows:
        if uri in per_url_cache:
            cached = per_url_cache[uri]
            result_rows.append(
                LinkValidationResult(
                    page_number=page_number,
                    url=uri,
                    method=cached.method,
                    status_code=cached.status_code,
                    error=cached.error,
                    passed=cached.passed,
                    skipped_by_policy=cached.skipped_by_policy,
                    attempt_count=cached.attempt_count,
                    checked_at_utc=cached.checked_at_utc,
                )
            )
            continue

        if checked >= max_checks:
            skipped_by_policy += 1
            skipped_row = LinkValidationResult(
                page_number=page_number,
                url=uri,
                method="POLICY",
                status_code=None,
                error="Skipped due to max_checks limit",
                passed=False,
                skipped_by_policy=True,
                attempt_count=0,
                checked_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            per_url_cache[uri] = skipped_row
            result_rows.append(skipped_row)
            continue

        parsed = urlparse(uri)
        host = parsed.netloc.lower()
        policy_target = f"{host}{parsed.path}".strip("/")

        if allowlist and not matches_any_pattern(policy_target, allowlist):
            skipped_by_policy += 1
            skipped_row = LinkValidationResult(
                page_number=page_number,
                url=uri,
                method="POLICY",
                status_code=None,
                error="Skipped by allowlist policy",
                passed=False,
                skipped_by_policy=True,
                attempt_count=0,
                checked_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            per_url_cache[uri] = skipped_row
            result_rows.append(skipped_row)
            continue
        if denylist and matches_any_pattern(policy_target, denylist):
            skipped_by_policy += 1
            skipped_row = LinkValidationResult(
                page_number=page_number,
                url=uri,
                method="POLICY",
                status_code=None,
                error="Skipped by denylist policy",
                passed=False,
                skipped_by_policy=True,
                attempt_count=0,
                checked_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            per_url_cache[uri] = skipped_row
            result_rows.append(skipped_row)
            continue

        checked += 1
        attempt = 0
        link_failed = False
        status_code: int | None = None
        used_method = "HEAD"
        error_message = ""
        while attempt <= max_retries:
            try:
                req = Request(uri, method="HEAD")
                with urlopen(req, timeout=timeout_seconds) as response:
                    status = getattr(response, "status", 200) or 200
                    status_code = int(status)
                    if status >= 400:
                        link_failed = True
                    else:
                        link_failed = False
                    break
            except HTTPError as exc:
                status_code = int(getattr(exc, "code", 0) or 0) or None
                # Some servers reject HEAD; retry with GET before counting a failure.
                if exc.code == 405:
                    try:
                        used_method = "GET"
                        fallback_req = Request(uri, method="GET")
                        with urlopen(fallback_req, timeout=timeout_seconds) as response:
                            status = getattr(response, "status", 200) or 200
                            status_code = int(status)
                            link_failed = status >= 400
                            error_message = ""
                            break
                    except Exception:
                        link_failed = True
                        error_message = "GET fallback failed after HEAD 405"
                else:
                    link_failed = True
                    error_message = f"HTTPError: {exc.code}"
            except (URLError, ValueError):
                link_failed = True
                error_message = "URL error or invalid URL"

            if attempt < max_retries:
                sleep_for = max(0.0, backoff_seconds) * (2 ** attempt)
                time.sleep(sleep_for)
            attempt += 1

        if link_failed:
            failures += 1
        result_rows.append(
            LinkValidationResult(
                page_number=page_number,
                url=uri,
                method=used_method,
                status_code=status_code,
                error=error_message if link_failed else "",
                passed=not link_failed,
                skipped_by_policy=False,
                attempt_count=attempt + 1,
                checked_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        )
        per_url_cache[uri] = result_rows[-1]

    return checked, failures, skipped_by_policy, result_rows


def analyze_pdf(
    pdf_bytes: bytes,
    enable_live_link_validation: bool = False,
    live_link_timeout_seconds: float = 3.0,
    live_link_max_retries: int = 1,
    live_link_backoff_seconds: float = 0.5,
    live_link_allowlist_patterns: list[str] | None = None,
    live_link_denylist_patterns: list[str] | None = None,
) -> AnalysisResult:
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
    pages_with_form_fields = 0
    total_form_fields = 0
    unlabeled_form_field_count = 0
    total_heading_signals = 0
    likely_missing_alt_text_pages = 0
    pages_with_low_contrast_text = 0
    low_contrast_span_count = 0
    pages_with_reading_order_warnings = 0
    reading_order_warning_count = 0
    images_without_caption_hints = 0
    pages_with_caption_warnings = 0
    total_links = 0
    unclear_link_purpose_count = 0
    pages_with_link_purpose_warnings = 0
    link_destination_warning_count = 0
    pages_with_link_destination_warnings = 0
    external_http_uris: list[tuple[int, str]] = []

    toc = document.get_toc(simple=True)
    bookmark_count = len(toc)
    has_bookmarks = bookmark_count > 0

    metadata = document.metadata or {}
    metadata_language = str(metadata.get("language", "") or "").strip()
    has_language_metadata = bool(metadata_language)

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

        form_field_count, unlabeled_fields = _detect_form_fields(page)
        if form_field_count > 0:
            pages_with_form_fields += 1
        total_form_fields += form_field_count
        unlabeled_form_field_count += unlabeled_fields

        low_contrast_count = _count_low_contrast_spans(page)
        if low_contrast_count > 0:
            pages_with_low_contrast_text += 1
        low_contrast_span_count += low_contrast_count

        reading_order_count = _count_reading_order_warnings(page)
        if reading_order_count > 0:
            pages_with_reading_order_warnings += 1
        reading_order_warning_count += reading_order_count

        missing_caption_count = _count_image_caption_warnings(page)
        if missing_caption_count > 0:
            pages_with_caption_warnings += 1
        images_without_caption_hints += missing_caption_count

        page_link_count, unclear_links, destination_warnings = _assess_link_annotation_purpose(page)
        total_links += page_link_count
        unclear_link_purpose_count += unclear_links
        link_destination_warning_count += destination_warnings
        if unclear_links > 0:
            pages_with_link_purpose_warnings += 1
        if destination_warnings > 0:
            pages_with_link_destination_warnings += 1
        external_http_uris.extend(_extract_external_http_uris(page, page_index + 1))

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
                "form_field_count": form_field_count,
                "heading_signal_count": heading_signal_count,
                "ocr_suggestion": _build_ocr_suggestion(has_text=has_text, has_images=has_images),
                "image_hashes": image_hashes,
                "low_contrast_hint_count": low_contrast_count,
                "reading_order_warning_count": reading_order_count,
                "missing_caption_hint_count": missing_caption_count,
                "link_count": page_link_count,
                "unclear_link_purpose_count": unclear_links,
                "destination_warning_count": destination_warnings,
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
                form_field_count=summary["form_field_count"],
                heading_signal_count=summary["heading_signal_count"],
                ocr_suggestion=summary["ocr_suggestion"],
                repeated_image_hits=repeated_hits,
                low_contrast_hint_count=summary["low_contrast_hint_count"],
                reading_order_warning_count=summary["reading_order_warning_count"],
                missing_caption_hint_count=summary["missing_caption_hint_count"],
                link_count=summary["link_count"],
                unclear_link_purpose_count=summary["unclear_link_purpose_count"],
                destination_warning_count=summary["destination_warning_count"],
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

    if total_form_fields > 0:
        issues.append(Issue("Form fields detected", f"Detected {total_form_fields} form field(s) across {pages_with_form_fields} page(s). Ensure each field has a clear accessible label and tab order."))

    if unlabeled_form_field_count > 0:
        issues.append(Issue("Possible unlabeled form fields", f"{unlabeled_form_field_count} form field(s) may be missing accessible labels (field name/label not found)."))

    if low_contrast_span_count > 0:
        issues.append(Issue("Possible low text contrast", f"Detected {low_contrast_span_count} text span(s) with possible low contrast across {pages_with_low_contrast_text} page(s). Consider darker text colors for readability."))

    if reading_order_warning_count > 0:
        issues.append(Issue("Possible reading-order region issues", f"Detected {reading_order_warning_count} reading-order warning signal(s) across {pages_with_reading_order_warnings} page(s). Review multi-column layout and tagged reading order."))

    if images_without_caption_hints > 0:
        issues.append(Issue("Possible missing image captions", f"Detected {images_without_caption_hints} image(s) without nearby caption hints across {pages_with_caption_warnings} page(s). Add clear figure captions where needed."))

    if unclear_link_purpose_count > 0:
        issues.append(Issue("Possible unclear link purpose", f"Detected {unclear_link_purpose_count} link annotation(s) with weak/missing purpose text across {pages_with_link_purpose_warnings} page(s). Use descriptive link text so destination purpose is clear."))

    if link_destination_warning_count > 0:
        issues.append(Issue("Possible weak link destinations", f"Detected {link_destination_warning_count} link destination warning(s) across {pages_with_link_destination_warnings} page(s) (for example missing URI, unsupported scheme, or internal-only host). Verify links resolve for end users."))

    live_links_checked = 0
    live_link_failures = 0
    live_links_skipped_by_policy = 0
    link_validation_results: list[LinkValidationResult] = []
    if enable_live_link_validation:
        live_links_checked, live_link_failures, live_links_skipped_by_policy, link_validation_results = _validate_external_links(
            external_http_uris,
            timeout_seconds=live_link_timeout_seconds,
            max_retries=max(0, int(live_link_max_retries)),
            backoff_seconds=max(0.0, float(live_link_backoff_seconds)),
            allowlist_patterns=live_link_allowlist_patterns,
            denylist_patterns=live_link_denylist_patterns,
        )
        if live_link_failures > 0:
            issues.append(Issue("Live link validation warnings", f"HTTP validation found {live_link_failures} potentially unreachable external link(s) out of {live_links_checked} checked URL(s). Re-test and confirm destination availability."))
        if live_links_skipped_by_policy > 0:
            issues.append(Issue("Live link validation policy skips", f"Skipped {live_links_skipped_by_policy} external link(s) due to allowlist/denylist policy settings."))

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

    if not has_language_metadata:
        issues.append(Issue("Missing document language metadata", "No document language metadata was detected. Set a default document language (for example en-US) so assistive technology can pronounce text correctly."))

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
        pages_with_form_fields=pages_with_form_fields,
        total_form_fields=total_form_fields,
        unlabeled_form_field_count=unlabeled_form_field_count,
        likely_missing_alt_text_pages=likely_missing_alt_text_pages,
        repeated_image_groups=len(repeated_hashes),
        pages_with_repeated_images=pages_with_repeated_images,
        bookmark_count=bookmark_count,
        has_bookmarks=has_bookmarks,
        heading_levels_detected=heading_levels_detected,
        heading_hierarchy_jumps=heading_hierarchy_jumps,
        has_language_metadata=has_language_metadata,
        metadata_language=metadata_language,
        pages_with_low_contrast_text=pages_with_low_contrast_text,
        low_contrast_span_count=low_contrast_span_count,
        pages_with_reading_order_warnings=pages_with_reading_order_warnings,
        reading_order_warning_count=reading_order_warning_count,
        images_without_caption_hints=images_without_caption_hints,
        pages_with_caption_warnings=pages_with_caption_warnings,
        total_links=total_links,
        unclear_link_purpose_count=unclear_link_purpose_count,
        pages_with_link_purpose_warnings=pages_with_link_purpose_warnings,
        link_destination_warning_count=link_destination_warning_count,
        pages_with_link_destination_warnings=pages_with_link_destination_warnings,
        live_link_validation_enabled=enable_live_link_validation,
        live_links_checked=live_links_checked,
        live_link_failures=live_link_failures,
        live_links_skipped_by_policy=live_links_skipped_by_policy,
        link_validation_results=link_validation_results,
        page_details=page_details,
        issues=issues,
    )
