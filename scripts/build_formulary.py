"""
One-time script: extract RAMQ exception codes from PDF → SQLite.

Schema:
  drugs(id, name UNIQUE, brands, section)
  codes(id, drug_id FK, code, indication)

Usage:
    cd /path/to/agi-health-hackathon
    python -m scripts.build_formulary

Reads:  data/ramq_exception.pdf
Writes: data/ramq.db  (replaces if exists)
"""
import base64
import json
import os
import re
import sqlite3
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

PDF_PATH = Path(__file__).parent.parent / "data" / "ramq_exception.pdf"
DB_PATH  = Path(__file__).parent.parent / "data" / "ramq.db"

SECTIONS = ["AI", "CV", "DE", "EN", "GI", "GU", "GY", "MS", "OP", "RE", "SN", "VA"]

# Sections known to be large get more output budget
SECTION_MAX_TOKENS = {
    "DE": 16000,  # Dermatology — large
    "RE": 16000,  # Respiratory — large
    "SN": 16000,  # Nervous system — large
}

EXTRACT_PROMPT = """
This is the RAMQ (Régie de l'assurance maladie du Québec) exception drug code directory.

Extract ONLY the drugs in the {section} section (pages labelled "CODIFICATION - {section}").
Ignore all other sections, index pages, and introduction pages.

Return a JSON array where each element is one unique drug:
{{
  "drug_name": "DAPAGLIFLOZINE",
  "brands": ["Forxiga", "AG-Dapagliflozin"],
  "section": "{section}",
  "codes": [
    {{"code": "CV399", "indication": "Pour le traitement..."}},
    {{"code": "CV679", "indication": "Pour le traitement..."}}
  ]
}}

Rules:
- drug_name: the generic/INN name in ALL CAPS exactly as shown
- brands: all brand names listed under that drug name
- codes: ALL codes for this drug with their full indication text
- One element per unique drug name

Return ONLY the JSON array, no prose, no markdown fences.
"""


def extract_section(client: anthropic.Anthropic, pdf_b64: str, section: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(section=section)
    max_tokens = SECTION_MAX_TOKENS.get(section, 8000)
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    drugs = json.loads(raw)
    print(f"{len(drugs)} drugs (out={response.usage.output_tokens})")
    return drugs


def extract(client: anthropic.Anthropic, resume: bool = True) -> list[dict]:
    """Extract all sections. With resume=True, skips sections already in the DB."""
    pdf_b64 = base64.standard_b64encode(PDF_PATH.read_bytes()).decode()

    # Find which sections are already done (for resume)
    done_sections: set[str] = set()
    if resume and DB_PATH.exists():
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT DISTINCT section FROM drugs").fetchall()
        done_sections = {r[0] for r in rows}
        con.close()
        if done_sections:
            print(f"Resuming — already have: {', '.join(sorted(done_sections))}")

    all_drugs: list[dict] = []
    for section in SECTIONS:
        if section in done_sections:
            print(f"  {section}: skipped (already extracted)")
            continue
        print(f"  Extracting {section}…", end=" ", flush=True)
        try:
            drugs = extract_section(client, pdf_b64, section)
            all_drugs.extend(drugs)
            # Write this section immediately so progress is saved
            if DB_PATH.exists():
                _append_to_db(drugs)
                print(f"    → saved to DB")
        except json.JSONDecodeError as e:
            print(f"PARSE ERROR: {e} — skipping, re-run to retry")
        except Exception as e:
            print(f"ERROR: {e}")
            print("Progress saved. Re-run to resume from here.")
            break

    return all_drugs


def _append_to_db(drugs: list[dict]) -> None:
    """Append drugs to existing DB (used during resume)."""
    con = sqlite3.connect(DB_PATH)
    for d in drugs:
        cur = con.execute(
            "INSERT OR IGNORE INTO drugs(name, brands, section) VALUES (?,?,?)",
            (d["drug_name"], ", ".join(d.get("brands", [])), d.get("section", "")),
        )
        drug_id = cur.lastrowid or con.execute(
            "SELECT id FROM drugs WHERE name=?", (d["drug_name"],)
        ).fetchone()[0]
        for c in d.get("codes", []):
            con.execute(
                "INSERT INTO codes(drug_id, code, indication) VALUES (?,?,?)",
                (drug_id, c["code"], c["indication"]),
            )
    con.execute("INSERT INTO drugs_fts(rowid, name, brands) SELECT id, name, brands FROM drugs WHERE id NOT IN (SELECT rowid FROM drugs_fts)")
    con.commit()
    con.close()


def build_db(drugs: list[dict]) -> None:
    DB_PATH.unlink(missing_ok=True)  # type: ignore[call-arg]
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE drugs (
            id      INTEGER PRIMARY KEY,
            name    TEXT NOT NULL UNIQUE,
            brands  TEXT,
            section TEXT
        );
        CREATE TABLE codes (
            id         INTEGER PRIMARY KEY,
            drug_id    INTEGER NOT NULL REFERENCES drugs(id),
            code       TEXT NOT NULL,
            indication TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE drugs_fts USING fts5(
            name, brands,
            content=drugs, content_rowid=id
        );
    """)

    drug_count = 0
    code_count = 0
    for d in drugs:
        cur = con.execute(
            "INSERT OR IGNORE INTO drugs(name, brands, section) VALUES (?,?,?)",
            (d["drug_name"], ", ".join(d.get("brands", [])), d.get("section", "")),
        )
        drug_id = cur.lastrowid
        if drug_id == 0:
            drug_id = con.execute("SELECT id FROM drugs WHERE name=?", (d["drug_name"],)).fetchone()[0]
        drug_count += 1

        for c in d.get("codes", []):
            con.execute(
                "INSERT INTO codes(drug_id, code, indication) VALUES (?,?,?)",
                (drug_id, c["code"], c["indication"]),
            )
            code_count += 1

    # Populate FTS
    con.execute("INSERT INTO drugs_fts(rowid, name, brands) SELECT id, name, brands FROM drugs")
    con.commit()
    con.close()
    print(f"Wrote {drug_count} drugs, {code_count} codes → {DB_PATH}")


if __name__ == "__main__":
    import sys
    fresh = "--fresh" in sys.argv  # pass --fresh to wipe and restart

    client = anthropic.Anthropic()

    if fresh or not DB_PATH.exists():
        # Create empty DB with schema so sections can be appended as they complete
        build_db([])
        print("Created empty ramq.db")

    extract(client, resume=not fresh)

    # Final count
    con = sqlite3.connect(DB_PATH)
    nd = con.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
    nc = con.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    done = {r[0] for r in con.execute("SELECT DISTINCT section FROM drugs").fetchall()}
    con.close()
    missing = set(SECTIONS) - done
    print(f"\nDB: {nd} drugs, {nc} codes — sections done: {', '.join(sorted(done))}")
    if missing:
        print(f"Missing: {', '.join(sorted(missing))} — re-run to complete")
    else:
        print("All sections complete — commit data/ramq.db")
