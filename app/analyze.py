"""
Medication analysis: take any chat-style input (pasted text, screenshots, PDFs)
of a patient's active medication list and run it through a clinical-pharmacist
prompt with Claude Opus 4.8 (vision + adaptive thinking).
"""
import base64

import anthropic

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are an expert clinical pharmacist with more than 20 years \
of experience in kidney disease.

The user provides a copy of the patient's active medication list from the DSQ \
(Médicaments actifs ou complétés derniers 30 jours), as text and/or images. The \
list may include the columns: Statut, Type, Indicateur(s), Médicament (Nom \
commercial), Posologie, Ordonnance, DR, Dernière délivrance, Délai (jrs), and \
Qté délivrée. The Délai indicates the time elapsed since the last dispensing and \
can help identify medications that are active in the DSQ but may no longer be \
taken by the patient.

Produce, in this order:

1. A bullet list giving only the pharmacological (generic) drug name, the dose \
taken, route, and frequency. Example: **Furosemide** 40 mg orally twice daily.
2. Any discrepancies, duplications, medication interactions, or possible \
prescription cascades.
3. A final list of possible medical diagnoses inferred from the medications \
taken by the patient.

Before delivering your output, apply a second-pass "sanity filter" to the \
pharmacological classification section to avoid an inadequate second-pass \
review."""

# media types Claude vision accepts as image blocks
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

client = anthropic.Anthropic()


def _file_block(filename, raw_bytes, mime):
    """Build an image or document content block from an uploaded file."""
    data = base64.standard_b64encode(raw_bytes).decode("utf-8")
    if mime in IMAGE_TYPES:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": data},
        }
    if mime == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            "title": filename or "medication-list.pdf",
        }
    raise ValueError(f"Unsupported file type: {mime} ({filename})")


def analyze(text, files):
    """Run the medication analysis.

    text  -- pasted medication list (may be empty)
    files -- list of (filename, raw_bytes, mime) tuples (may be empty)

    Returns (markdown_text, usage).
    """
    content = []
    for filename, raw_bytes, mime in files:
        content.append(_file_block(filename, raw_bytes, mime))
    if text and text.strip():
        content.append({"type": "text", "text": text.strip()})

    if not content:
        raise ValueError("Provide a medication list as text, an image, or a PDF.")

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": content}],
    )

    answer = "".join(b.text for b in response.content if b.type == "text")
    return answer, response.usage
