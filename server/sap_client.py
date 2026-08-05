"""HTTP client for the SAP ICF remnant-classification endpoint (/sap/bc/zai_dim,
handler ZAI_DIM_HANDLER). Since the 2026-07-29 SAP-side rewrite this is no longer
a dumb dimension-log write: SAP computes remnant_area = board_area - product_area,
then internally calls Z_SCRAP_CLASSIFY, which does the MIGO 501 goods receipt
(producing a batch), works out the storage-bin zone, and assigns the batch
classification -- so a single successful call here means the remnant is already
physically in stock under the returned batch/bin_zone.

Field contract (do not rename -- the SAP-side service is already activated against
these exact keys): matnr, board_length, board_width, product_area, source_id, and
the optional zone/plant/sloc/quantity/scrap_length/scrap_width/unit. All numeric
values are sent as strings because the SAP handler parses them as strings.
`charg` (batch) is no longer sent -- batches are assigned by SAP's own MIGO 501
call and returned to us, never supplied by the caller.

Error handling follows the confirmed table:
  401 bad credentials -- NEVER auto-retried. SAP locks the account after 5 bad
      attempts, so retrying a wrong password is actively harmful.
  403 SICF service not activated -- an SAP-side config problem; do not try to
      route around it, just surface it clearly.
  400 a required field is missing or non-numeric
  404 matnr not found in MARA (only SCRAP-FR / SCRAP-WP / SCRAP-RC are
      maintained for plant 2604)
  422 a business-rule failure inside SAP (e.g. product_area >= board_area, or
      the MIGO 501 / Z_SCRAP_CLASSIFY call itself failed) -- SAP's response body
      carries the real human-readable reason in `message`, so that's preferred
      over any fixed text.
Only transient failures (connection/timeout) are retried, capped at
config.SAP_ICF_MAX_RETRIES with exponential backoff.
"""

import time

import requests

import config

# Codes where the failure reason is fixed and never depends on the response body.
FRIENDLY_ERRORS = {
    401: "SAP 帳號或密碼錯誤。請勿重複嘗試以免帳號被鎖定；請確認 SAP_ICF_USERNAME / SAP_ICF_PASSWORD 環境變數設定正確。",
    403: "SAP 服務未啟用（SICF 設定問題）。這不是本軟體的錯誤，請聯絡 SAP 端負責人確認服務已啟用。",
    405: "呼叫方式錯誤（非 POST）。這是軟體本身的錯誤，請回報開發人員。",
}

# Codes where SAP's JSON body carries the real, human-readable reason in
# `message` (missing/non-numeric field for 400, unknown matnr for 404, a
# business-rule failure -- e.g. product_area exceeding board area, or the
# MIGO 501 / Z_SCRAP_CLASSIFY call itself failing -- for 422). The text below
# is only a fallback for when the body isn't parseable JSON.
BODY_MESSAGE_ERRORS = {
    400: "傳送的欄位格式有誤（缺漏或非數值）。請確認輸入的欄位。",
    404: "料號在 SAP 查無資料，請確認料號是否正確（2604 廠僅維護 SCRAP-FR / SCRAP-WP / SCRAP-RC）。",
    422: "SAP 業務規則檢查失敗（例如成品面積超過原紙板，或入庫/分類失敗）。",
}


class SapConfigError(Exception):
    """SAP_ICF_URL / SAP_ICF_USERNAME / SAP_ICF_PASSWORD not configured."""


def _require_config():
    missing = [
        name for name, value in (
            ("SAP_ICF_URL", config.SAP_ICF_URL),
            ("SAP_ICF_USERNAME", config.SAP_ICF_USERNAME),
            ("SAP_ICF_PASSWORD", config.SAP_ICF_PASSWORD),
        )
        if not value
    ]
    if missing:
        raise SapConfigError(
            "尚未設定 SAP 連線環境變數：" + "、".join(missing) + "（請用環境變數設定，勿寫死於程式碼）"
        )


def _error_result(payload, *, http_status=None, sap_status=None, error):
    return {
        "ok": False, "http_status": http_status, "sap_status": sap_status,
        "guid": None, "batch": None, "bin_zone": None, "remnant_area": None,
        "message": None, "error": error, "payload": payload,
    }


def post_remnant(*, matnr, board_length_cm, board_width_cm, product_area_cm2,
                  plant="2604", sloc="100B", quantity=1, zone=None,
                  scrap_length_cm=None, scrap_width_cm=None, unit="CM", source_id):
    """POSTs one remnant-classification request. Returns:
    {"ok": bool, "http_status": int|None, "sap_status": "S"|"E"|None,
     "guid": str|None, "batch": str|None, "bin_zone": str|None,
     "remnant_area": str|None, "message": str|None, "error": str|None,
     "payload": dict}
    `error` is always a human-readable message, never a raw SAP/HTTP code.
    """
    _require_config()

    # Validate the required numeric fields, and that product_area doesn't
    # exceed the board it's supposedly cut from, before making any HTTP call
    # at all -- SAP returns 422 for exactly this, and there's no point
    # spending a round trip (and burning toward the retry/lockout budget) to
    # discover that locally.
    required = (
        ("board_length", board_length_cm),
        ("board_width", board_width_cm),
        ("product_area", product_area_cm2),
    )
    parsed = {}
    for field_name, value in required:
        try:
            parsed[field_name] = float(value)
        except (TypeError, ValueError):
            return _error_result(
                None, error=f"{field_name} 必須是數值，收到的是：{value!r}（未送出，本機先擋下）",
            )
        if parsed[field_name] <= 0:
            return _error_result(
                None, error=f"{field_name} 必須大於 0，收到的是：{value!r}（未送出，本機先擋下）",
            )

    board_area = parsed["board_length"] * parsed["board_width"]
    if parsed["product_area"] >= board_area:
        return _error_result(
            None,
            error=(
                f"成品面積（{parsed['product_area']} cm²）不可大於等於原紙板面積"
                f"（{board_area} cm²），沒有餘料可入庫（未送出，本機先擋下）"
            ),
        )

    payload = {
        "matnr": str(matnr),
        "board_length": str(board_length_cm),
        "board_width": str(board_width_cm),
        "product_area": str(product_area_cm2),
        "source_id": str(source_id),
        "zone": str(zone) if zone else str(matnr),
        "plant": str(plant) if plant else "2604",
        "sloc": str(sloc) if sloc else "100B",
        "quantity": str(quantity) if quantity else "1",
        "unit": unit or "CM",
    }
    if scrap_length_cm is not None:
        payload["scrap_length"] = str(scrap_length_cm)
    if scrap_width_cm is not None:
        payload["scrap_width"] = str(scrap_width_cm)

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(
                config.SAP_ICF_URL,
                json=payload,
                auth=(config.SAP_ICF_USERNAME, config.SAP_ICF_PASSWORD),
                verify=config.SAP_ICF_VERIFY_SSL,
                timeout=config.SAP_ICF_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            if attempt <= config.SAP_ICF_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 10))
                continue
            return _error_result(
                payload,
                error=f"無法連線到 SAP（{e.__class__.__name__}），已重試 {attempt - 1} 次仍失敗：{e}",
            )

        if resp.status_code in FRIENDLY_ERRORS:
            return _error_result(payload, http_status=resp.status_code, error=FRIENDLY_ERRORS[resp.status_code])

        if resp.status_code in BODY_MESSAGE_ERRORS:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            message = body.get("message") if isinstance(body, dict) else None
            return _error_result(
                payload, http_status=resp.status_code,
                error=message or BODY_MESSAGE_ERRORS[resp.status_code],
            )

        if resp.status_code != 200:
            return _error_result(
                payload, http_status=resp.status_code,
                error=f"SAP 回應非預期的狀態碼 {resp.status_code}：{resp.text[:300]}",
            )

        try:
            data = resp.json()
        except ValueError:
            return _error_result(payload, http_status=resp.status_code, error="SAP 回應不是有效的 JSON，請確認服務狀態。")

        sap_status = data.get("status")
        return {
            "ok": sap_status == "S",
            "http_status": resp.status_code,
            "sap_status": sap_status,
            "guid": data.get("guid"),
            "batch": data.get("batch"),
            "bin_zone": data.get("bin_zone"),
            "remnant_area": data.get("remnant_area"),
            "message": data.get("message"),
            "error": None if sap_status == "S" else (data.get("message") or f"SAP 回傳失敗狀態（status={sap_status}）。"),
            "payload": payload,
        }
