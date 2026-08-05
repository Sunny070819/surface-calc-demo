"""One-off matrix test: for each of the 3 material types x both stocking
plans (A -> SBED, B -> CUBE), stock in a synthetic scrap record locally then
export it through the real /api/sap/export-simple/<scrap_id> Flask route --
exercising the exact same code path the frontend uses (material -> matnr
mapping, plan -> sloc mapping, length/width fallback from the stored record)
-- and hits the real SAP ICF endpoint for each of the 6 combinations.

Requires SAP_ICF_URL / SAP_ICF_USERNAME / SAP_ICF_PASSWORD (same as
test_sap_direct.py) already set in the environment. Writes to throwaway
local Excel DB files in a temp directory, never touches the real
data/scrap_inventory.xlsx or data/sap_sync_log.xlsx.

Usage:
    python test_sap_export_matrix.py
"""

import os
import tempfile

import config

config.EXCEL_DB_PATH = os.path.join(tempfile.mkdtemp(), "scrap_inventory_test.xlsx")
config.SAP_SYNC_LOG_PATH = os.path.join(tempfile.mkdtemp(), "sap_sync_log_test.xlsx")

import app as app_module  # noqa: E402  (must import after the config overrides above)

# Mirrors surface-calculate.html's MATERIAL_TO_SAP_MATNR_SIMPLE / stockLocSelect
# mapping -- kept as a literal copy here rather than imported, since the
# frontend mapping lives in JS, not Python.
MATERIAL_TO_MATNR_SIMPLE = {"防火": "SCRAP3-FR", "防水": "SCRAP3-WP", "再生紙": "SCRAP3-RC"}
PLAN_TO_SLOC = {"A": "SBED", "B": "CUBE"}


def stock_in_one(client, material):
    payload = {
        "polygon_cm": [{"x": 0, "y": 0}, {"x": 30, "y": 0}, {"x": 30, "y": 30}, {"x": 0, "y": 30}],
        "sheet": {"length_cm": 100, "width_cm": 100, "name": "TEST-SHEET"},
        "material": material,
        "source_type": "manual",
        "contour_method": "矩陣測試腳本",
    }
    resp = client.post("/api/stock-in", json=payload)
    data = resp.get_json()
    if not data or not data.get("ok"):
        raise RuntimeError(f"本機入庫失敗（材質={material}）：{data}")
    return data["scrap_id"]


def main():
    missing = [
        name for name, value in (
            ("SAP_ICF_URL", config.SAP_ICF_URL),
            ("SAP_ICF_USERNAME", config.SAP_ICF_USERNAME),
            ("SAP_ICF_PASSWORD", config.SAP_ICF_PASSWORD),
        )
        if not value
    ]
    if missing:
        print(f"缺少環境變數：{', '.join(missing)}（請比照 test_sap_direct.py 的方式設定後再執行）")
        return

    app_module.app.testing = True
    client = app_module.app.test_client()

    rows = []
    for material, matnr in MATERIAL_TO_MATNR_SIMPLE.items():
        for plan, sloc in PLAN_TO_SLOC.items():
            try:
                scrap_id = stock_in_one(client, material)
            except RuntimeError as e:
                rows.append({
                    "material": material, "matnr": matnr, "sloc": sloc, "scrap_id": "—",
                    "http": None, "ok": False, "log_ok": None, "posting_ok": None,
                    "matdoc": None, "matdoc_year": None, "error": str(e),
                })
                continue

            resp = client.post(f"/api/sap/export-simple/{scrap_id}", json={
                "matnr": matnr, "sloc": sloc, "quantity": 1,
            })
            data = resp.get_json() or {}
            rows.append({
                "material": material, "matnr": matnr, "sloc": sloc, "scrap_id": scrap_id,
                "http": resp.status_code, "ok": data.get("ok"),
                "log_ok": data.get("log_ok"), "posting_ok": data.get("posting_ok"),
                "matdoc": data.get("matdoc"), "matdoc_year": data.get("matdoc_year"),
                "error": data.get("error"),
            })

    header = f"{'材質':<6}{'matnr':<11}{'sloc':<6}{'scrap_id':<14}{'HTTP':<6}{'ok':<7}{'log_ok':<8}{'posting_ok':<11}{'matdoc':<14}{'年度':<6}錯誤訊息"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['material']:<6}{r['matnr']:<11}{r['sloc']:<6}{r['scrap_id']:<14}"
            f"{str(r['http']):<6}{str(r['ok']):<7}{str(r['log_ok']):<8}{str(r['posting_ok']):<11}"
            f"{str(r['matdoc']):<14}{str(r['matdoc_year']):<6}{r['error'] or ''}"
        )

    ok_count = sum(1 for r in rows if r["ok"])
    print(f"\n共 {len(rows)} 組，成功 {ok_count} 組，失敗 {len(rows) - ok_count} 組。")


if __name__ == "__main__":
    main()
