"""
Medication analysis: take any chat-style input (pasted text, screenshots, PDFs)
of a patient's active medication list and run it through a clinical-pharmacist
prompt with Claude Opus 4.8 (vision + adaptive thinking).
"""
import base64
import json
import re

import anthropic

from app.prompts import ACTIVE_PROMPT

MODEL = "claude-opus-4-8"

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


def analyze(text, files, patient_context="", context_files=None):
    """Run the medication analysis.

    text            -- pasted medication list (may be empty)
    files           -- list of (filename, raw_bytes, mime) tuples (may be empty)
    patient_context -- optional free-text clinical context from the physician
    context_files   -- optional list of (filename, raw_bytes, mime) for lab images etc.

    Returns (markdown_text, usage).
    """
    content = []
    if patient_context or context_files:
        content.append({"type": "text", "text": "PATIENT CONTEXT (provided by physician):" + (f"\n{patient_context}" if patient_context else "")})
        for filename, raw_bytes, mime in (context_files or []):
            content.append(_file_block(filename, raw_bytes, mime))
    for filename, raw_bytes, mime in files:
        content.append(_file_block(filename, raw_bytes, mime))
    if text and text.strip():
        content.append({"type": "text", "text": f"MEDICATION LIST:\n{text.strip()}"})

    if not content or (not patient_context and not text.strip() and not files):
        raise ValueError("Provide a medication list as text, an image, or a PDF.")

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=ACTIVE_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": content}],
    )

    answer = "".join(b.text for b in response.content if b.type == "text")
    return answer, response.usage


HAIKU = "claude-haiku-4-5-20251001"


def _haiku(prompt: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=HAIKU,
        max_tokens=max_tokens,
        system="You are a pharmacist assistant. Return ONLY valid JSON, no prose, no markdown fences.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw


def resolve_drug(raw: str) -> dict:
    """Normalize a drug name (English or French) → {english, french} INN names."""
    text = _haiku(
        f"Drug name entered by physician: {raw!r}\n"
        'Return JSON: {"english": "<English INN generic name lowercase>", "french": "<French INN nom générique lowercase>"}',
        120,
    )
    try:
        return json.loads(text)
    except Exception:
        return {"english": raw, "french": raw}


def translate_indications(texts: list) -> list:
    """Translate a list of French RAMQ indication strings to English."""
    text = _haiku(
        f"Translate each French medical text to English. Return a JSON array in the same order:\n{json.dumps(texts)}",
        max(400, len(texts) * 200),
    )
    try:
        result = json.loads(text)
        if isinstance(result, list) and len(result) == len(texts):
            return result
    except Exception:
        pass
    return texts


def check_drug(new_drug: str, current_analysis: str):
    """Targeted interaction check for one new drug against the already-reviewed regimen."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=(
            "You are a clinical pharmacist. The physician has a patient's medication "
            "regimen that has already been reviewed (summary below). During the visit "
            "they are considering adding a new drug. In 4–6 bullet points, identify: "
            "drug interactions with the current regimen, contraindications, dose "
            "considerations, and any monitoring needed. Start each bullet with a "
            "severity tag: [Severe], [Moderate], or [Mild]. Be concise."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"EXISTING REGIMEN REVIEW:\n{current_analysis}\n\n"
                f"NEW DRUG BEING CONSIDERED: {new_drug}"
            ),
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, response.usage


def explain(item_text):
    """Return a 2-3 sentence clinical explanation of a single flag or action bullet."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=(
            "You are a clinical pharmacist explaining a medication flag or recommended "
            "action to a family physician in Ontario. In 2-3 sentences explain WHY this "
            "matters clinically — the mechanism, the specific risk, or the evidence. "
            "Be concrete and practical. Do not restate the flag; explain it."
        ),
        messages=[{"role": "user", "content": item_text}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, response.usage
