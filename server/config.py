"""Central place for POC tunables. All values here are placeholders until
台芯實業 provides real numbers for the area threshold and standard products."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
STANDARD_PRODUCTS_PATH = os.path.join(BASE_DIR, "standard_products.json")
STANDARD_SHEETS_PATH = os.path.join(BASE_DIR, "standard_sheets.json")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")
EXCEL_DB_PATH = os.path.join(DATA_DIR, "scrap_inventory.xlsx")
FRONTEND_HTML_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "surface-calculate.html"))

# --- SAP ICF integration (ZAI_DIM endpoint) ---
# Never hardcode the URL or credentials here -- test vs. production endpoints and
# the account differ per environment, and the test credentials in the handbook are
# already publicly exposed, so production MUST use different ones supplied only
# via environment variables (see sap_client.py).
SAP_ICF_URL = os.environ.get("SAP_ICF_URL")
SAP_ICF_USERNAME = os.environ.get("SAP_ICF_USERNAME")
SAP_ICF_PASSWORD = os.environ.get("SAP_ICF_PASSWORD")
# Skipping TLS verification is a test-environment-only workaround; production must
# not set SAP_ICF_VERIFY_SSL=false once a real certificate is in place.
SAP_ICF_VERIFY_SSL = os.environ.get("SAP_ICF_VERIFY_SSL", "true").strip().lower() not in ("false", "0", "no")
SAP_ICF_TIMEOUT_SECONDS = float(os.environ.get("SAP_ICF_TIMEOUT_SECONDS", "30"))
# Only transient network failures (timeout/connection error) are retried, capped
# here; a 401 is never retried regardless of this value -- see sap_client.py.
SAP_ICF_MAX_RETRIES = int(os.environ.get("SAP_ICF_MAX_RETRIES", "2"))
SAP_SYNC_LOG_PATH = os.path.join(DATA_DIR, "sap_sync_log.xlsx")
