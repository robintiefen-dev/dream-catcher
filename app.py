"""Streamlit entry point for Accessibility Fixer MVP."""

import streamlit as st

from accessibility_fixer.pdf_analyzer import analyze_pdf
from accessibility_fixer.remediation import build_remediated_pdf
from accessibility_fixer.report_export import analysis_to_json_bytes, page_details_to_csv_bytes
from accessibility_fixer.rewrite_suggestions import generate_rewrite_suggestions


def render_page_details_table(result) -> None:
    """Show a simple page-by-page table for beginners to inspect."""
    rows = []
    for detail in result.page_details:
        rows.append(
            {
                "Page": detail.page_number,
                "Has selectable text": "Yes" if detail.has_selectable_text else "No",
                "Has images": "Yes" if detail.has_images else "No",
                "Heading signals": detail.heading_signal_count,
                "OCR suggestion": detail.ocr_suggestion,
                "Repeated image hits": detail.repeated_image_hits,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


# Page title and short app description.
st.set_page_config(page_title="Accessibility Fixer", page_icon="📄")
st.title("📄 Accessibility Fixer")
st.write(
    "Upload a PDF and run a quick accessibility check for common issues "
    "(text, images, heading structure, and basic readability signals)."
)

# PDF uploader accepts only .pdf files.
uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])

if uploaded_file is not None:
    st.success(f"Loaded: {uploaded_file.name}")

    if st.button("Analyze PDF"):
        with st.spinner("Analyzing PDF..."):
            pdf_bytes = uploaded_file.read()

            try:
                result = analyze_pdf(pdf_bytes)
            except ValueError as error:
                st.error(str(error))
                st.stop()

            st.session_state["pdf_bytes"] = pdf_bytes
            st.session_state["analysis_result"] = result

# Render analysis from session state so follow-up actions (exports/suggestions) still work.
result = st.session_state.get("analysis_result")
pdf_bytes = st.session_state.get("pdf_bytes")

if result and pdf_bytes:
    st.subheader("Summary")
    st.write(f"**Status:** {result.summary_status}")

    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Pages", result.page_count)
    top2.metric("Pages with text", result.pages_with_text)
    top3.metric("Pages without text", result.pages_without_text)
    top4.metric("Pages with images", result.pages_with_images)

    bottom1, bottom2, bottom3 = st.columns(3)
    bottom1.metric("Likely alt-text risk pages", result.likely_missing_alt_text_pages)
    bottom2.metric("Pages with repeated images", result.pages_with_repeated_images)
    bottom3.metric("Bookmarks", result.bookmark_count)

    st.subheader("Accessibility issues found")
    if not result.issues:
        st.success("No major issues found by these basic checks.")
    else:
        for issue in result.issues:
            st.warning(f"**{issue.title}**\n\n{issue.explanation}")

    with st.expander("Page-by-page details"):
        st.caption("Use this table to quickly find pages that may need accessibility fixes.")
        render_page_details_table(result)

    st.subheader("Download analysis report")
    st.caption("Export this analysis as JSON or CSV.")
    json_bytes = analysis_to_json_bytes(result)
    csv_bytes = page_details_to_csv_bytes(result)
    base_name = uploaded_file.name.replace(".pdf", "") if uploaded_file else "analysis"

    report_col1, report_col2 = st.columns(2)
    report_col1.download_button(
        label="Download JSON report",
        data=json_bytes,
        file_name=f"{base_name}_accessibility_report.json",
        mime="application/json",
    )
    report_col2.download_button(
        label="Download CSV page report",
        data=csv_bytes,
        file_name=f"{base_name}_page_details.csv",
        mime="text/csv",
    )

    st.subheader("Optional LLM-assisted rewrite suggestions")
    st.caption(
        "Find dense paragraphs and generate readability rewrite suggestions. "
        "If no API key is provided, rule-based suggestions are used."
    )

    use_llm = st.checkbox("Use LLM (optional)")
    api_key = ""
    model_name = "gpt-4o-mini"

    if use_llm:
        api_key = st.text_input("OpenAI API key", type="password")
        model_name = st.text_input("Model", value="gpt-4o-mini")

    if st.button("Generate rewrite suggestions"):
        with st.spinner("Generating rewrite suggestions..."):
            suggestions = generate_rewrite_suggestions(
                pdf_bytes=pdf_bytes,
                use_llm=use_llm,
                api_key=api_key if use_llm else None,
                model=model_name,
            )

        if not suggestions:
            st.info("No dense paragraphs detected by the current heuristic.")
        else:
            for suggestion in suggestions:
                st.info(
                    f"**Page {suggestion.page_number} ({suggestion.source})**\n\n"
                    f"**Original excerpt:** {suggestion.original_excerpt}\n\n"
                    f"**Suggestion:** {suggestion.suggestion}"
                )

    st.subheader("Download a remediated draft PDF")
    st.caption(
        "This creates a new PDF copy with metadata updates and a remediation-notes page. "
        "It is a helpful draft, not full PDF/UA remediation."
    )

    remediated_pdf_bytes = build_remediated_pdf(pdf_bytes, result)
    output_name = (uploaded_file.name.replace(".pdf", "") if uploaded_file else "document") + "_remediated_draft.pdf"
    st.download_button(
        label="Download remediated draft",
        data=remediated_pdf_bytes,
        file_name=output_name,
        mime="application/pdf",
    )
elif uploaded_file is None:
    st.info("Upload a PDF to begin.")
