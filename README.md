# Accessibility Fixer (MVP)

A beginner-friendly Streamlit app that analyzes a PDF and reports common accessibility warning signals.

## What this version checks

- Number of pages
- Whether pages contain selectable text
- Whether images are present
- Pages likely to have image-description/alt-text risk (images + no selectable text)
- Simple warnings for likely accessibility issues:
  - image-only/scanned pages
  - likely missing heading structure
  - basic readability/structure warning for long PDFs
- Page-by-page signals table to make review easier

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
    └── remediation.py
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

## Run the app

```bash
streamlit run app.py
```

Then open the local URL shown in your terminal (usually `http://localhost:8501`).

## How to use

1. Upload a PDF.
2. Click **Analyze PDF**.
3. Review:
   - Summary status
   - Page/text/image metrics
   - Plain-English issue explanations
   - Page-by-page details table
4. Click **Download remediated draft** to export a new PDF copy.

## Beginner notes

- `app.py` handles the user interface.
- `accessibility_fixer/pdf_analyzer.py` contains the PDF analysis logic.
- `accessibility_fixer/remediation.py` builds a downloadable remediated draft file.
- The analysis intentionally uses simple rules so it's easy to learn and extend.

## Next feature ideas

- OCR suggestions per page
- Better heading detection using font size/style signals
- Export report as JSON or CSV
- Track repeated decorative images/logos
- Optional LLM-assisted rewrite suggestions for long dense paragraphs
