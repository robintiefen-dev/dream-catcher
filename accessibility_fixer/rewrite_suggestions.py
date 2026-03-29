"""Optional rewrite suggestion helpers for dense PDF paragraphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import fitz  # PyMuPDF


@dataclass
class RewriteSuggestion:
    """Represents one paragraph rewrite suggestion."""

    page_number: int
    original_excerpt: str
    suggestion: str
    source: str  # "rule_based" or "llm"


def _extract_dense_paragraphs(page_text: str) -> list[str]:
    """Return paragraphs that look dense and hard to read.

    Heuristic:
    - paragraph has at least 90 words
    - average sentence length is above ~22 words
    """
    dense_paragraphs: list[str] = []
    raw_paragraphs = [part.strip() for part in page_text.split("\n\n") if part.strip()]

    for paragraph in raw_paragraphs:
        words = paragraph.split()
        if len(words) < 90:
            continue

        sentences = [s.strip() for s in paragraph.replace("\n", " ").split(".") if s.strip()]
        if not sentences:
            continue

        avg_sentence_words = sum(len(sentence.split()) for sentence in sentences) / max(len(sentences), 1)
        if avg_sentence_words >= 22:
            dense_paragraphs.append(paragraph)

    return dense_paragraphs


def _rule_based_rewrite(paragraph: str) -> str:
    """Generate a simple rewrite recommendation without using an LLM."""
    return (
        "Try splitting this paragraph into 2-4 shorter paragraphs, use shorter sentences, "
        "replace jargon with simpler words, and convert long lists into bullet points."
    )


def _llm_rewrite(paragraph: str, api_key: str, model: str) -> str:
    """Use OpenAI to suggest a clearer rewrite for one paragraph.

    This import is inside the function so the app still runs without the package
    when users do not enable LLM suggestions.
    """
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError(
            "openai package is not installed. Install it to use LLM rewrite suggestions."
        ) from exc

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "Rewrite dense text into plain English while preserving meaning.",
            },
            {
                "role": "user",
                "content": (
                    "Rewrite this paragraph to improve readability and accessibility. "
                    "Keep it concise and preserve facts:\n\n"
                    + paragraph
                ),
            },
        ],
        max_output_tokens=220,
    )

    return response.output_text.strip()


def generate_rewrite_suggestions(
    pdf_bytes: bytes,
    use_llm: bool = False,
    api_key: Optional[str] = None,
    model: str = "gpt-4o-mini",
    max_suggestions: int = 6,
) -> List[RewriteSuggestion]:
    """Generate rewrite suggestions for dense paragraphs in a PDF."""
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    suggestions: List[RewriteSuggestion] = []

    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        dense_paragraphs = _extract_dense_paragraphs(page_text)

        for paragraph in dense_paragraphs:
            excerpt = " ".join(paragraph.split())[:280]

            if use_llm and api_key:
                try:
                    suggestion_text = _llm_rewrite(paragraph=paragraph, api_key=api_key, model=model)
                    source = "llm"
                except Exception:
                    suggestion_text = _rule_based_rewrite(paragraph)
                    source = "rule_based"
            else:
                suggestion_text = _rule_based_rewrite(paragraph)
                source = "rule_based"

            suggestions.append(
                RewriteSuggestion(
                    page_number=page_index + 1,
                    original_excerpt=excerpt,
                    suggestion=suggestion_text,
                    source=source,
                )
            )

            if len(suggestions) >= max_suggestions:
                document.close()
                return suggestions

    document.close()
    return suggestions
