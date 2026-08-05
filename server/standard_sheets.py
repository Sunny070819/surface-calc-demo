"""Loads the configurable standard raw-paperboard-sheet list (multiple presets can
coexist since different orders may use different sheet stock). Same load-on-every-call
pattern as standard_products.py -- an operator can edit standard_sheets.json and see the
change on the next request with no server restart, since the real sheet sizes aren't
known yet either.
"""

import json

import config


def load_sheets():
    with open(config.STANDARD_SHEETS_PATH, "r", encoding="utf-8") as f:
        sheets = json.load(f)
    for s in sheets:
        required = {"id", "name", "length_cm", "width_cm", "area_cm2"}
        missing = required - s.keys()
        if missing:
            raise ValueError(f"standard_sheets.json entry {s} missing fields: {missing}")
    return sheets


def get_sheet(sheet_id):
    for s in load_sheets():
        if s["id"] == sheet_id:
            return s
    return None
