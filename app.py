"""Streamlit entry point for Accessibility Fixer MVP."""

import streamlit as st

from accessibility_fixer.pdf_analyzer import analyze_pdf


def render_page_details_table(result) -> None:
    """Show a simple page-by-page table for beginners to inspect."""
    rows = []
    for detail in result.page_details:
        rows.append(
            {
                "Page": detail.page_number,
                "Has selectable text": "Yes" if detail.has_selectable_text else "No",
                "Has images": "Yes" if detail.has_images else "No",
                "Heading-like lines": detail.heading_like_lines,
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

        st.subheader("Summary")
        st.write(f"**Status:** {result.summary_status}")

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Pages", result.page_count)
        col2.metric("Pages with text", result.pages_with_text)
        col3.metric("Pages without text", result.pages_without_text)
        col4.metric("Pages with images", result.pages_with_images)
        col5.metric("Likely alt-text risk pages", result.likely_missing_alt_text_pages)

        st.subheader("Accessibility issues found")
        if not result.issues:
            st.success("No major issues found by these basic checks.")
        else:
            for issue in result.issues:
                st.warning(f"**{issue.title}**\n\n{issue.explanation}")

        with st.expander("Page-by-page details"):
            st.caption("Use this table to quickly find pages that may need accessibility fixes.")
            render_page_details_table(result)
else:
    st.info("Upload a PDF to begin.")
