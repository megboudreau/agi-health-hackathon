# 🩺 Coding Copilot — AGI Health Hackathon

Helps clinicians find the right **billing / diagnostic codes** for a prescription
or encounter, instead of hunting through a ~900-page coding manual by hand.

## How it works

No vector database. The entire manual is loaded into Claude Opus 4.8's **1M-token
context window** on every query. Two API features carry the demo:

- **Prompt caching** — the manual is written to cache on the first request and
  read at ~10% of input cost on every request after, so repeat lookups are cheap
  and fast.
- **Citations** — Claude returns the exact page(s) each code came from, so a
  clinician can verify the source in one click.

```
clinician types scenario ──▶ Flask ──▶ Claude Opus 4.8
                                          (manual in context, cached)
                                          ◀── cited codes
```

If the manual ever outgrows the context window, swap `app/rag.py` for a chunk +
retrieve step — the Flask layer and UI don't change.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

Drop the coding manual (PDF or .txt) in `data/` and point `SOURCE_DOC` at it in
`.env`.

## Run

```bash
python -m app.server
# open http://localhost:5000
```

## Layout

| Path | What |
|------|------|
| `app/rag.py` | Loads the manual, calls Claude with caching + citations |
| `app/server.py` | Flask routes (`/` and `/api/lookup`) |
| `app/templates/index.html` | Single-page search UI |
| `data/` | The source manual lives here (gitignored) |

## Notes

- Model: `claude-opus-4-8` (1M context, native PDF + citations).
- PDFs are capped at 100 pages on 200K-context models — Opus 4.8's large window
  is why a 900-page doc works. Very large PDFs may need to be split into a few
  `document` blocks.
