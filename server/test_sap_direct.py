"""Standalone smoke test for sap_client.post_remnant_simple() against the real
SAP ICF endpoint -- bypasses Flask/the browser UI entirely, so you can verify
an ABAP-side handler change immediately after deploying it.

Connection settings (SAP_ICF_URL / SAP_ICF_USERNAME / SAP_ICF_PASSWORD /
SAP_ICF_VERIFY_SSL) are read from the environment, same convention as
start_server.ps1 and config.py -- never hardcoded here. Run this the same way
you'd run app.py: with those env vars already set in the shell.

Usage:
    python test_sap_direct.py
"""

import config
import sap_client


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
        print(f"缺少環境變數：{', '.join(missing)}（請比照 start_server.ps1 的方式設定後再執行）")
        return

    print(f"SAP_ICF_URL         = {config.SAP_ICF_URL}")
    print(f"SAP_ICF_USERNAME    = {config.SAP_ICF_USERNAME}")
    print(f"SAP_ICF_VERIFY_SSL  = {config.SAP_ICF_VERIFY_SSL}")
    print("呼叫 sap_client.post_remnant_simple(matnr='SCRAP2-WP', sloc='SBED', quantity=1, "
          "length_cm=50, width_cm=30, area_cm2=1500) ...")
    print()

    try:
        result = sap_client.post_remnant_simple(
            matnr="SCRAP2-WP", sloc="SBED", quantity=1, length_cm=50, width_cm=30, area_cm2=1500,
        )
    except sap_client.SapConfigError as e:
        print(f"設定錯誤：{e}")
        return
    except Exception as e:
        print(f"呼叫失敗（未預期的例外 {e.__class__.__name__}）：{e}")
        return

    print("=== 回應內容 ===")
    print(f"ok           = {result.get('ok')}")
    print(f"http_status  = {result.get('http_status')}")
    print(f"sap_status   = {result.get('sap_status')}")
    print(f"matdoc       = {result.get('matdoc')}")
    print(f"matdoc_year  = {result.get('matdoc_year')}")
    print(f"message      = {result.get('message')}")
    print(f"error        = {result.get('error')}")
    print(f"payload（送出的內容） = {result.get('payload')}")


if __name__ == "__main__":
    main()
