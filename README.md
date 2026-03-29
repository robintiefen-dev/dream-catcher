# Accessibility Fixer (MVP)

A beginner-friendly Streamlit app that analyzes a PDF and reports common accessibility warning signals.

## What this version checks

- Number of pages
- Whether pages contain selectable text
- Whether images are present
- Pages likely to have image-description/alt-text risk (images + no selectable text)
- Simple warnings for likely accessibility issues:
  - image-only/scanned pages
  - likely missing heading structure (using font size/style heading signals)
  - heading hierarchy depth checks (detecting heading level jumps)
  - basic readability/structure warning for long PDFs
  - table extraction checks (table presence + possible missing headers)
  - form-field checks (presence + possible missing labels)
  - language metadata checks (default document language present/missing)
  - color contrast hints for extracted text styles (heuristic)
  - reading-order region checks (heuristic block-order warnings)
  - image-caption association checks (nearby caption hints)
  - link annotation purpose checks (descriptive link-text hints with multi-line/nearby-label context)
  - link destination-quality checks (missing URI, unsupported schemes, and internal-only host hints)
  - optional live link validation mode (HTTP HEAD checks for external HTTP(S) links)
  - configurable live link retry/backoff and allowlist/denylist filtering
- Page-by-page signals table to make review easier
- OCR suggestions per page for fast triage
- Downloadable analysis report export (JSON and CSV)
- Downloadable per-link live validation CSV export (status/error fields) for audits
- Repeated decorative image/logo tracking across pages
- Bookmark/navigation suggestions based on detected document outline

## New in this iteration: Remediated draft output

After analysis, the app can generate a **remediated draft PDF** you can download.

This output currently does:
- Preserve original pages
- Add basic metadata defaults (Title/Subject/Keywords)
- Append a final "Remediation Notes" page with recommended fixes

This output does **not** yet do full PDF/UA remediation (for example: true structural tagging, verified reading order, and verified alt text).

> Note: This is a first-pass helper, not a full PDF/UA compliance checker.

## Project structure

```text
.
├── app.py
├── requirements.txt
├── README.md
└── accessibility_fixer/
    ├── pdf_analyzer.py
    ├── remediation.py
    ├── report_export.py
    └── rewrite_suggestions.py
```

## Setup

1. Create and activate a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows PowerShell
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

`openai` is included for optional LLM rewrite suggestions.

## Run the app

```bash
streamlit run app.py
```

Then open the local URL shown in your terminal (usually `http://localhost:8501`).

## How to use

1. Upload a PDF.
2. (Optional) Enable **live link validation** for HTTP reachability checks.
3. (Optional) Configure retry/backoff and allowlist/denylist patterns for live validation policy.
4. Click **Analyze PDF**.
5. Review:
   - Summary status
   - Page/text/image/table/form/bookmark/heading/language/contrast/reading-order/caption/link/destination metrics
   - Plain-English issue explanations
   - Page-by-page details table (includes table count, form field count, OCR suggestion, repeated image hits, low-contrast hints, reading-order hints, missing-caption hints, and link-purpose hints per page)
6. Download analysis reports:
   - **JSON report** (full analysis payload)
   - **CSV page report** (page-by-page table)
   - **CSV link validation report** (per-link page number + method/status/error + attempts + UTC timestamp rows when live validation is enabled)
7. (Optional) Generate rewrite suggestions for dense paragraphs:
   - rule-based suggestions by default
   - LLM suggestions if you enable LLM mode and provide an API key
8. Click **Download remediated draft** to export a new PDF copy.

## Beginner notes

- `app.py` handles the user interface.
- `accessibility_fixer/pdf_analyzer.py` contains the PDF analysis logic.
- `accessibility_fixer/remediation.py` builds a downloadable remediated draft file with OCR guidance notes.
- `accessibility_fixer/report_export.py` exports analysis as JSON and CSV files.
- `accessibility_fixer/rewrite_suggestions.py` provides optional rewrite suggestions for dense paragraphs (rule-based or LLM-assisted).
- The analysis intentionally uses simple rules so it's easy to learn and extend.

## Next feature ideas

- Add per-link validation results export (status code/error) for audit-friendly reporting
