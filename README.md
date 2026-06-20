# 💊 Medication Analysis — AGI Health Hackathon

A no-login web app that takes a patient's active medication list — pasted text,
a screenshot, a PDF, or any combination — and returns an expert clinical-pharmacist
review: a normalized drug/dose/route/frequency list, flagged discrepancies,
duplications, interactions and prescription cascades, and inferred diagnoses.

## How it works

```
paste text / drop image / drop PDF ──▶ Flask ──▶ Claude Opus 4.8
                                                  (vision + adaptive thinking,
                                                   clinical-pharmacist system prompt)
                                                  ◀── markdown review
```

- **Multimodal input** — images and PDFs go straight to Claude's vision; pasted
  text rides alongside them in the same message. Paste a screenshot with ⌘V.
- **One prompt** — the clinical-pharmacist persona and task live in the system
  prompt (`app/analyze.py`); whatever you provide is the patient data.
- **Adaptive thinking** at high effort, so the reasoning (interactions, cascades,
  the second-pass sanity filter) gets room to work.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

## Run

```bash
python -m app.server
# open http://localhost:5000
```

## Layout

| Path | What |
|------|------|
| `app/analyze.py` | The clinical-pharmacist prompt + multimodal Claude call |
| `app/server.py` | Flask routes (`/` and `/api/analyze`) |
| `app/templates/index.html` | Single-page UI: textarea + drag/drop/paste uploads |

## Notes

- Model: `claude-opus-4-8` (vision, native PDF, adaptive thinking).
- Uploads capped at 30 MB (Anthropic's request limit is 32 MB).
- Clinical decision-support aid for demo purposes — not a substitute for
  professional judgment.
