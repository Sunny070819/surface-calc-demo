"""Thin Flask router: parse the request, call the relevant module, return JSON.
Serves the existing surface-calculate.html directly so the whole POC runs as a
single process on a single port with no CORS friction; flask-cors is still
enabled as a fallback for the (unlikely) case someone opens the HTML via file://.
"""

import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import config
import contour_detection
import dxf_parser
import excel_db
import geometry_utils
import qualification
import sap_client
import sap_export
import sap_sync_log
import standard_products
import standard_sheets

app = Flask(__name__)
CORS(app)
app.json.ensure_ascii = False


@app.get("/")
def index():
    directory = os.path.dirname(config.FRONTEND_HTML_PATH)
    filename = os.path.basename(config.FRONTEND_HTML_PATH)
    return send_from_directory(directory, filename)


@app.get("/api/config")
def get_config():
    return jsonify({
        "threshold_cm2": config.AREA_DISCARD_THRESHOLD_CM2,
        "grid_cell_size_cm": config.GRID_CELL_SIZE_CM,
    })


@app.get("/api/standard-products")
def get_standard_products():
    return jsonify(standard_products.load_products())


@app.get("/api/standard-sheets")
def get_standard_sheets():
    return jsonify(standard_sheets.load_sheets())


@app.post("/api/client-log")
def client_log():
    # Lets the frontend surface a non-fatal fallback (e.g. an unmapped SAP
    # material) in the backend log without interrupting the user's flow.
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "warning").lower()
    message = data.get("message") or ""
    log_fn = getattr(app.logger, level, None) or app.logger.warning
    log_fn("[client] %s", message)
    return jsonify({"ok": True})


@app.post("/api/analyze-photo")
def analyze_photo():
    if "image" not in request.files:
        return jsonify({"ok": False, "warning": "缺少 image 檔案。"}), 400
    image_bytes = request.files["image"].read()
    try:
        display_width = int(float(request.form.get("display_width", 0)))
        display_height = int(float(request.form.get("display_height", 0)))
    except ValueError:
        return jsonify({"ok": False, "warning": "display_width/display_height 格式錯誤。"}), 400
    if display_width <= 0 or display_height <= 0:
        return jsonify({"ok": False, "warning": "缺少有效的 display_width/display_height。"}), 400

    result = contour_detection.detect_contour(image_bytes, display_width, display_height)
    return jsonify(result)


@app.post("/api/analyze-dxf")
def analyze_dxf():
    if "dxf" not in request.files:
        return jsonify({"ok": False, "warning": "缺少 dxf 檔案。"}), 400
    dxf_bytes = request.files["dxf"].read()
    try:
        scale = float(request.form.get("scale_cm_per_unit", 1.0))
    except ValueError:
        return jsonify({"ok": False, "warning": "scale_cm_per_unit 格式錯誤。"}), 400
    if scale <= 0:
        return jsonify({"ok": False, "warning": "比例尺必須大於 0。"}), 400

    result = dxf_parser.parse_dxf(dxf_bytes, scale)
    return jsonify(result)


def _polygon_from_request(data):
    points = data.get("polygon_cm")
    if not points or len(points) < 3:
        raise ValueError("polygon_cm 至少需要 3 個點。")
    return geometry_utils.points_to_polygon(points)


def _sheet_from_request(data):
    sheet = data.get("sheet") or {}
    try:
        length_cm = float(sheet.get("length_cm"))
        width_cm = float(sheet.get("width_cm"))
    except (TypeError, ValueError):
        raise ValueError("尚未設定標準原紙板尺寸。")
    if length_cm <= 0 or width_cm <= 0:
        raise ValueError("原紙板尺寸必須大於 0。")
    return length_cm, width_cm


@app.post("/api/evaluate")
def evaluate():
    data = request.get_json(silent=True) or {}
    try:
        polygon = _polygon_from_request(data)
        sheet_length_cm, sheet_width_cm = _sheet_from_request(data)
    except ValueError as e:
        return jsonify({"ok": False, "warning": str(e)}), 400

    result = qualification.evaluate_design(polygon, sheet_length_cm, sheet_width_cm, data.get("products"))
    return jsonify(result)


@app.post("/api/stock-in")
def stock_in():
    data = request.get_json(silent=True) or {}
    try:
        polygon = _polygon_from_request(data)
        sheet_length_cm, sheet_width_cm = _sheet_from_request(data)
    except ValueError as e:
        return jsonify({"ok": False, "warning": str(e)}), 400

    # Recompute server-side rather than trusting client-supplied counts.
    eval_result = qualification.evaluate_design(polygon, sheet_length_cm, sheet_width_cm)
    if not eval_result["qualifies"]:
        return jsonify({"ok": False, "reason": eval_result["reason"], "evaluate_result": eval_result})

    leftover_points = eval_result["leftover_polygon_cm"]
    leftover_polygon = geometry_utils.points_to_polygon(leftover_points)
    bbox = geometry_utils.bbox(leftover_polygon)
    sheet_info = data.get("sheet") or {}
    candidate_options = data.get("candidate_options")
    if not candidate_options:
        candidate_options = [
            {
                "product_id": product_id,
                "fits": option.get("fits", 0),
                "unit_price": option.get("unit_price"),
                "benefit": option.get("benefit"),
            }
            for product_id, option in (eval_result.get("nesting") or {}).items()
        ]
    binding_status = data.get("binding_status") or "UNBOUND"

    row = excel_db.append_record(
        batch=data.get("batch_no"),
        source_filename=data.get("source_filename"),
        source_type=data.get("source_type"),
        contour_method=data.get("contour_method"),
        area_cm2=eval_result["area_cm2"],
        polygon_cm=leftover_points,
        length_cm=round(bbox["length"], 2),
        width_cm=round(bbox["width"], 2),
        fits_by_product=eval_result["nesting"],
        material=data.get("material"),
        grid_cell_size_cm=eval_result["grid_cell_size_cm"],
        verdict="合格入庫",
        sheet_name=sheet_info.get("name"),
        sheet_area_cm2=eval_result["sheet_area_cm2"],
        product_area_cm2=eval_result["product_area_cm2"],
        product_fit_count=eval_result["product_fit_count"],
        candidate_options=candidate_options,
        binding_status=binding_status,
    )
    return jsonify({"ok": True, "scrap_id": row["餘料編號"], "row": row})


@app.post("/api/sap/export/<scrap_id>")
def sap_export_route(scrap_id):
    record = excel_db.get_record(scrap_id)
    if record is None:
        return jsonify({"ok": False, "error": f"本地找不到餘料編號 {scrap_id} 的紀錄。"}), 404

    data = request.get_json(silent=True) or {}
    matnr = data.get("matnr")
    if not matnr:
        return jsonify({"ok": False, "error": "缺少 matnr（SAP 料號），請提供後再送出。"}), 400

    try:
        result = sap_export.export_to_sap(
            record, matnr,
            board_length_cm=data.get("board_length_cm"),
            board_width_cm=data.get("board_width_cm"),
            product_area_cm2=data.get("product_area_cm2"),
            scrap_area_cm2=data.get("scrap_area_cm2") or record.get("總面積(cm²)"),
            plant=data.get("plant") or "2604",
            sloc=data.get("sloc") or "100B",
            quantity=data.get("quantity") or 1,
            zone=data.get("zone"),
            scrap_length_cm=data.get("scrap_length_cm"),
            scrap_width_cm=data.get("scrap_width_cm"),
            candidate_options=data.get("candidate_options") or record.get("候選方案(JSON)"),
            binding_status=data.get("binding_status") or record.get("綁定狀態") or "UNBOUND",
        )
    except sap_client.SapConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(result), (200 if result.get("ok") else 502)


@app.post("/api/sap/export-simple/<scrap_id>")
def sap_export_simple_route(scrap_id):
    """Simplified export path (see sap_client.post_remnant_simple): just
    matnr/sloc/quantity, no board/product-area negotiation. A separate route
    from /api/sap/export/<scrap_id> above -- that one (and export_to_sap/
    post_remnant behind it) is left untouched, the two paths run in parallel.
    """
    record = excel_db.get_record(scrap_id)
    if record is None:
        return jsonify({"ok": False, "error": f"本地找不到餘料編號 {scrap_id} 的紀錄。"}), 404

    data = request.get_json(silent=True) or {}
    matnr = data.get("matnr")
    sloc = data.get("sloc")
    quantity = data.get("quantity")
    if not matnr:
        return jsonify({"ok": False, "error": "缺少 matnr（SAP 料號），請提供後再送出。"}), 400
    if not sloc:
        return jsonify({"ok": False, "error": "缺少 sloc（儲位），請提供後再送出。"}), 400
    if not quantity:
        return jsonify({"ok": False, "error": "缺少 quantity（數量），請提供後再送出。"}), 400

    try:
        result = sap_client.post_remnant_simple(matnr, sloc, quantity)
    except sap_client.SapConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    sap_sync_log.append_simple_sync_record(
        scrap_id=scrap_id, matnr=matnr, sloc=sloc, quantity=quantity, result=result,
    )

    return jsonify(result), (200 if result.get("ok") else 502)


if __name__ == "__main__":
    # Bound to 0.0.0.0 so colleagues on the same network can reach it via LAN IP.
    # debug is hardcoded off here: the Werkzeug debug reloader exposes an
    # interactive console that lets anyone who can reach this port run arbitrary
    # code on this machine, which is only acceptable when bound to localhost.
    app.run(host='0.0.0.0', port=5000, debug=False)
