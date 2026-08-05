"""Central place for POC tunables. All values here are placeholders until
台芯實業 provides real numbers for the area threshold and standard products."""

import json
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# When packaged with PyInstaller (--onefile), sys.frozen is set and bundled
# files live under the temp extraction dir sys._MEIPASS -- that dir is wiped
# and recreated on every launch, so nothing the customer needs to persist or
# edit (data/, standard_products.json, standard_sheets.json, SAP settings)
# can live there. RESOURCE_DIR is for read-only bundled files (the frontend
# HTML); EXTERNAL_DIR is a writable location next to the exe itself that
# survives across runs and that a customer/operator can open in Explorer.
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
EXTERNAL_DIR = os.path.dirname(sys.executable) if IS_FROZEN else BASE_DIR


def _ensure_external_copy(filename):
    """On first run of the packaged exe, seed an editable copy of a bundled
    default file (standard_products.json etc.) next to the exe, so the
    customer's own edits survive the next launch instead of being reset to
    the bundled default every time (a fresh temp dir every run otherwise)."""
    external_path = os.path.join(EXTERNAL_DIR, filename)
    if IS_FROZEN and not os.path.exists(external_path):
        bundled_path = os.path.join(RESOURCE_DIR, filename)
        if os.path.exists(bundled_path):
            shutil.copyfile(bundled_path, external_path)
    return external_path

# --- Qualification ---
AREA_DISCARD_THRESHOLD_CM2 = 300.0  # placeholder, mirrors the existing HTML prototype's default
LOG_DISCARDS = False  # if True, discarded items are also written to Excel with a discard reason

# --- Nesting (grid approximation) ---
GRID_CELL_SIZE_CM = 1.0  # placeholder cell size; auto-coarsened if it would exceed MAX_GRID_CELLS
MAX_GRID_CELLS = 200 * 200
TRY_ROTATIONS_DEG = [0, 90]

# --- Contour detection ---
CONTOUR_DETECTION_CONFIDENCE_THRESHOLD = 0.5
CONTOUR_MAX_WORKING_DIMENSION_PX = 1600
CONTOUR_MIN_AREA_RATIO = 0.01  # reject detected contour if smaller than 1% of image area

# --- Paths ---
# standard_products.json / standard_sheets.json are meant to be hand-edited by
# an operator with no server restart required (see standard_products.py /
# standard_sheets.py). When packaged, that has to be an editable copy sitting
# next to the exe (seeded from the bundled default on first run), not the
# read-only bundled copy itself, which would silently reset every launch.
STANDARD_PRODUCTS_PATH = _ensure_external_copy("standard_products.json")
STANDARD_SHEETS_PATH = _ensure_external_copy("standard_sheets.json")
UPLOAD_FOLDER = os.path.join(EXTERNAL_DIR, "uploads")
DATA_DIR = os.path.join(EXTERNAL_DIR, "data")
EXCEL_DB_PATH = os.path.join(DATA_DIR, "scrap_inventory.xlsx")
# The frontend HTML is never edited by the customer, so reading it straight
# out of the read-only bundled resource dir is fine even though that dir gets
# wiped and re-extracted on every launch.
FRONTEND_HTML_PATH = (
    os.path.join(RESOURCE_DIR, "surface-calculate.html") if IS_FROZEN
    else os.path.abspath(os.path.join(BASE_DIR, "..", "surface-calculate.html"))
)

# --- SAP ICF integration (ZAI_DIM endpoint) ---
# Never hardcode the URL or credentials directly in source -- test vs.
# production endpoints and the account differ per environment. For local/dev
# runs (not frozen) these still only come from env vars, matching
# start_server.ps1. For the packaged exe, they're read from an external
# sap_config.json sitting next to the exe (see _load_sap_config below):
# still plaintext on disk and extractable from the exe with tools like
# pyinstxtractor, but at least not compiled into the binary and swappable
# without a rebuild if the account/password ever needs to change.
def _load_sap_config():
    if not IS_FROZEN:
        return {}
    config_path = os.path.join(EXTERNAL_DIR, "sap_config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_sap_config = _load_sap_config()


def _sap_setting(key, default=None):
    return _sap_config.get(key) or os.environ.get(key, default)


SAP_ICF_URL = _sap_setting("SAP_ICF_URL")
SAP_ICF_USERNAME = _sap_setting("SAP_ICF_USERNAME")
SAP_ICF_PASSWORD = _sap_setting("SAP_ICF_PASSWORD")
# Skipping TLS verification is a test-environment-only workaround; production must
# not set SAP_ICF_VERIFY_SSL=false once a real certificate is in place.
SAP_ICF_VERIFY_SSL = str(_sap_setting("SAP_ICF_VERIFY_SSL", "true")).strip().lower() not in ("false", "0", "no")
SAP_ICF_TIMEOUT_SECONDS = float(_sap_setting("SAP_ICF_TIMEOUT_SECONDS", "30"))
# Only transient network failures (timeout/connection error) are retried, capped
# here; a 401 is never retried regardless of this value -- see sap_client.py.
SAP_ICF_MAX_RETRIES = int(_sap_setting("SAP_ICF_MAX_RETRIES", "2"))
SAP_SYNC_LOG_PATH = os.path.join(DATA_DIR, "sap_sync_log.xlsx")
