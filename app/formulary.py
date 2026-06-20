"""
RAMQ exception-drug formulary lookup.

Build the DB once with:  python -m scripts.build_formulary

search(name) returns:
  {
    "name":    "DAPAGLIFLOZINE",
    "brands":  "Forxiga, Apo-Dapagliflozin, ...",
    "section": "CV",
    "codes": [
      {"code": "CV399", "indication": "Pour le traitement..."},
      {"code": "CV679", "indication": "..."}
    ]
  }
  or None if not found.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "ramq.db"
_con: sqlite3.Connection | None = None


def load() -> None:
    global _con
    if not DB_PATH.exists():
        print("[formulary] ramq.db not found — run: python -m scripts.build_formulary", flush=True)
        return
    _con = sqlite3.connect(DB_PATH, check_same_thread=False)
    _con.row_factory = sqlite3.Row
    n = _con.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
    print(f"[formulary] {n} drugs loaded from ramq.db", flush=True)


def search(drug_name: str) -> dict | None:
    if _con is None:
        return None

    q = drug_name.strip()

    # 1. FTS prefix search on name + brands
    row = _con.execute(
        "SELECT d.id, d.name, d.brands, d.section "
        "FROM drugs_fts f JOIN drugs d ON f.rowid = d.id "
        "WHERE drugs_fts MATCH ? ORDER BY rank LIMIT 1",
        (q + "*",),
    ).fetchone()

    # 2. Fallback: LIKE on name or brands
    if not row:
        row = _con.execute(
            "SELECT id, name, brands, section FROM drugs "
            "WHERE name LIKE ? COLLATE NOCASE OR brands LIKE ? COLLATE NOCASE LIMIT 1",
            (f"%{q}%", f"%{q}%"),
        ).fetchone()

    if not row:
        return None

    codes = _con.execute(
        "SELECT code, indication FROM codes WHERE drug_id = ? ORDER BY code",
        (row["id"],),
    ).fetchall()

    return {
        "name":    row["name"],
        "brands":  row["brands"],
        "section": row["section"],
        "codes":   [{"code": c["code"], "indication": c["indication"]} for c in codes],
    }
