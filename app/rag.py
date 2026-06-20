"""
Core lookup logic: load the full coding manual into context, ask Claude for the
right billing/diagnostic code, and return cited answers.

No vector DB — the whole document rides in the 1M-token context window. Prompt
caching makes every query after the first cheap (~0.1x the input cost), and
citations make Claude point at the exact page each code came from.
"""
import base64
import functools
import os

import anthropic

# Opus 4.8: 1M-token context window, native citations, prompt caching.
MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are a medical coding assistant for clinicians. Given a \
clinical scenario or a prescription, you find the correct billing and/or \
diagnostic codes from the reference manual provided to you.

Rules:
- Only use codes that appear in the provided manual. Never invent a code.
- For each code, give the code, its official description, and a one-line reason \
it applies to the scenario.
- If multiple codes could apply, list them ranked by relevance and say what \
distinguishes them.
- If the manual does not contain a clearly applicable code, say so plainly \
rather than guessing.
- Be concise. Clinicians are busy."""

client = anthropic.Anthropic()


@functools.lru_cache(maxsize=1)
def _load_document_block():
    """Build the Anthropic `document` content block for the source manual.

    Cached so we read the file from disk once per process. The returned block
    carries cache_control so the manual is written to the prompt cache on the
    first request and read cheaply on every subsequent one.
    """
    path = os.environ.get("SOURCE_DOC", "data/coding-manual.pdf")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Source document not found at {path!r}. Drop the manual in data/ "
            f"and set SOURCE_DOC in your .env (see .env.example)."
        )

    if path.lower().endswith(".pdf"):
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        source = {"type": "base64", "media_type": "application/pdf", "data": data}
    else:
        with open(path, "r", encoding="utf-8") as f:
            source = {"type": "text", "media_type": "text/plain", "data": f.read()}

    return {
        "type": "document",
        "source": source,
        "title": os.path.basename(path),
        "citations": {"enabled": True},
        # Cache the (large) manual so repeat queries don't re-pay full input cost.
        "cache_control": {"type": "ephemeral"},
    }


def lookup(question: str):
    """Answer a coding question against the manual.

    Returns a list of content blocks. Text blocks may carry a `citations` array
    pointing at the exact page(s) in the manual the answer came from.
    """
    document = _load_document_block()

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    document,
                    {"type": "text", "text": question},
                ],
            }
        ],
    )
    return response


def render_answer(response):
    """Flatten an API response into {text, citations} for the web UI."""
    out = []
    for block in response.content:
        if block.type != "text":
            continue
        cites = []
        for c in (block.citations or []):
            cite = {"document_title": getattr(c, "document_title", None)}
            # PDF citations carry page numbers; text citations carry char offsets.
            if getattr(c, "type", None) == "page_location":
                cite["start_page"] = c.start_page_number
                cite["end_page"] = c.end_page_number
            cite["cited_text"] = getattr(c, "cited_text", "")
            cites.append(cite)
        out.append({"text": block.text, "citations": cites})
    return out
