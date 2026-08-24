"""
resume_parser.py
-----------------
Handles raw text extraction from uploaded resume files (PDF or .txt).

Design note: we deliberately keep this module "dumb" — it only pulls raw
text off the page. All the *intelligence* (identifying skills, experience,
education) is delegated to the LLM in llm_matcher.py. Regex/keyword based
extraction is brittle across resume formats; letting the LLM read the raw
text and return structured JSON is far more robust and is the core idea
the assignment is testing (LLM prompt quality).
"""

import pdfplumber
import io


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF resume, page by page."""
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_chunks.append(page_text)
    return "\n".join(text_chunks)


def extract_text_from_upload(filename: str, file_bytes: bytes) -> str:
    """
    Dispatch based on file extension. Supports .pdf and .txt.
    Raises ValueError for unsupported types so the API layer can
    return a clean 400 error.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)
    elif lower.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {filename}. Use .pdf or .txt")

    if not text.strip():
        raise ValueError(
            f"No extractable text found in {filename}. "
            "It may be a scanned/image-based PDF (would need OCR)."
        )
    return text
